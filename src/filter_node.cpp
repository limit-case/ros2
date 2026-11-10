// Copyright 2025 Yajan
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "limit_case_ros2/filter_node.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <string>

// cv_bridge moved its header between distros (Humble: .h, Jazzy: .hpp).
#if __has_include(<cv_bridge/cv_bridge.hpp>)
#include "cv_bridge/cv_bridge.hpp"
#else
#include "cv_bridge/cv_bridge.h"
#endif
#include "rclcpp_components/register_node_macro.hpp"
#include "sensor_msgs/image_encodings.hpp"
#include "sensor_msgs/point_cloud2_iterator.hpp"

namespace limit_case_ros2
{

namespace enc = sensor_msgs::image_encodings;

GlassFilterNode::GlassFilterNode(const rclcpp::NodeOptions & options)
: rclcpp::Node("glass_filter", options), updater_(this)
{
  declareParams();
  param_cb_ = add_on_set_parameters_callback(
    std::bind(&GlassFilterNode::onParams, this, std::placeholders::_1));

  // Inputs: sensor-data QoS (best effort, depth 5). Outputs: reliable. Both overridable.
  const auto in_qos = rclcpp::SensorDataQoS().keep_last(5);
  const auto out_qos = rclcpp::QoS(5).reliable();
  rclcpp::SubscriptionOptions sub_opts;
  sub_opts.qos_overriding_options = rclcpp::QosOverridingOptions::with_default_policies();
  rclcpp::PublisherOptions pub_opts;
  pub_opts.qos_overriding_options = rclcpp::QosOverridingOptions::with_default_policies();

  filtered_pub_ = create_publisher<Image>("/limit_case/depth/filtered", out_qos, pub_opts);
  mask_pub_ = create_publisher<Image>("/limit_case/mask", out_qos, pub_opts);
  cloud_pub_ = create_publisher<sensor_msgs::msg::PointCloud2>(
    "/limit_case/suspected_obstacles", out_qos, pub_opts);

  info_sub_ = create_subscription<sensor_msgs::msg::CameraInfo>(
    "depth/camera_info", in_qos,
    std::bind(&GlassFilterNode::onCameraInfo, this, std::placeholders::_1), sub_opts);

  if (params_.use_rgb) {
    // message_filters::Subscriber takes a QoS profile; ApproximateTime queue 10, slop 0.03 s.
    const auto rmw = in_qos.get_rmw_qos_profile();
    sync_depth_sub_ =
      std::make_shared<message_filters::Subscriber<Image>>(this, "depth/image", rmw);
    sync_color_sub_ =
      std::make_shared<message_filters::Subscriber<Image>>(this, "color/image", rmw);
    sync_ = std::make_shared<message_filters::Synchronizer<SyncPolicy>>(
      SyncPolicy(10), *sync_depth_sub_, *sync_color_sub_);
    sync_->setMaxIntervalDuration(rclcpp::Duration::from_seconds(0.03));
    sync_->registerCallback(
      std::bind(&GlassFilterNode::onDepth, this, std::placeholders::_1, std::placeholders::_2));
  } else {
    depth_sub_ = create_subscription<Image>(
      "depth/image", in_qos, [this](const Image::ConstSharedPtr msg) { onDepth(msg, nullptr); },
      sub_opts);
  }

  updater_.setHardwareID("limit_case_ros2");
  updater_.add("glass_filter", this, &GlassFilterNode::fillDiagnostics);
  RCLCPP_INFO(
    get_logger(), "glass_filter up (profile '%s', use_rgb=%s)", profile_.c_str(),
    params_.use_rgb ? "true" : "false");
}

void GlassFilterNode::declareParams()
{
  GlassParams d;
  profile_ = declare_parameter("sensor_profile", std::string("default"));
  params_.downsample = declare_parameter("downsample", d.downsample);
  params_.min_basin_depth_m = static_cast<float>(declare_parameter("min_basin_depth_m", 0.02));
  params_.min_basin_depth_rel = static_cast<float>(declare_parameter("min_basin_depth_rel", 0.03));
  params_.min_region_area_px = declare_parameter("min_region_area_px", d.min_region_area_px);
  params_.max_range_m = static_cast<float>(declare_parameter("max_range_m", 4.0));
  params_.treat_invalid_as_wall = declare_parameter("treat_invalid_as_wall", false);
  params_.boundary_verify = declare_parameter("boundary_verify", false);
  params_.min_nearer_boundary_frac =
    static_cast<float>(declare_parameter("min_nearer_boundary_frac", 0.1));
  params_.flag_hole_only = declare_parameter("flag_hole_only", false);
  params_.use_rgb = declare_parameter("use_rgb", false);  // read at startup only (topology)
  params_.specular_v_thresh = declare_parameter("specular_v_thresh", d.specular_v_thresh);
  params_.specular_s_thresh = declare_parameter("specular_s_thresh", d.specular_s_thresh);
  params_.confidence_threshold = static_cast<float>(declare_parameter("confidence_threshold", 0.5));
  publish_cloud_ = declare_parameter("publish_cloud", true);
  params_.cloud_stride = declare_parameter("cloud_stride", d.cloud_stride);
}

rcl_interfaces::msg::SetParametersResult GlassFilterNode::onParams(
  const std::vector<rclcpp::Parameter> & ps)
{
  rcl_interfaces::msg::SetParametersResult r;
  r.successful = true;
  std::lock_guard<std::mutex> lk(mtx_);
  for (const auto & p : ps) {
    const auto & n = p.get_name();
    if (n == "downsample") {
      params_.downsample = std::max<int64_t>(1, p.as_int());
    } else if (n == "min_basin_depth_m") {
      params_.min_basin_depth_m = p.as_double();
    } else if (n == "min_basin_depth_rel") {
      params_.min_basin_depth_rel = p.as_double();
    } else if (n == "min_region_area_px") {
      params_.min_region_area_px = p.as_int();
    } else if (n == "max_range_m") {
      params_.max_range_m = p.as_double();
    } else if (n == "treat_invalid_as_wall") {
      params_.treat_invalid_as_wall = p.as_bool();
    } else if (n == "boundary_verify") {
      params_.boundary_verify = p.as_bool();
    } else if (n == "min_nearer_boundary_frac") {
      params_.min_nearer_boundary_frac = p.as_double();
    } else if (n == "flag_hole_only") {
      params_.flag_hole_only = p.as_bool();
    } else if (n == "specular_v_thresh") {
      params_.specular_v_thresh = p.as_int();
    } else if (n == "specular_s_thresh") {
      params_.specular_s_thresh = p.as_int();
    } else if (n == "confidence_threshold") {
      params_.confidence_threshold = p.as_double();
    } else if (n == "publish_cloud") {
      publish_cloud_ = p.as_bool();
    } else if (n == "cloud_stride") {
      params_.cloud_stride = std::max<int64_t>(1, p.as_int());
    } else if (n == "use_rgb") {
      r.successful = false;
      r.reason = "use_rgb is read at startup only";
    }
  }
  return r;
}

void GlassFilterNode::onCameraInfo(const sensor_msgs::msg::CameraInfo::ConstSharedPtr msg)
{
  std::lock_guard<std::mutex> lk(mtx_);
  info_ = msg;
}

void GlassFilterNode::onDepth(
  const Image::ConstSharedPtr & depth, const Image::ConstSharedPtr & color)
{
  try {
    const auto t0 = std::chrono::steady_clock::now();
    GlassParams p;
    bool want_cloud;
    sensor_msgs::msg::CameraInfo::ConstSharedPtr info;
    {
      std::lock_guard<std::mutex> lk(mtx_);
      p = params_;
      want_cloud = publish_cloud_;
      info = info_;
    }

    const bool is16 = depth->encoding == enc::TYPE_16UC1;
    const bool is32 = depth->encoding == enc::TYPE_32FC1;
    if (!is16 && !is32) {
      RCLCPP_WARN_ONCE(
        get_logger(),
        "unsupported depth encoding '%s' (need 16UC1 or 32FC1); "
        "passing depth through unchanged",
        depth->encoding.c_str());
      filtered_pub_->publish(*depth);
      std::lock_guard<std::mutex> lk(mtx_);
      last_passthrough_ = true;
      return;
    }

    const int w = static_cast<int>(depth->width), h = static_cast<int>(depth->height);
    cv_bridge::CvImageConstPtr dimg = cv_bridge::toCvShare(depth, depth->encoding);
    std::vector<float> meters(static_cast<size_t>(w) * h);
    if (is16) {
      for (int y = 0; y < h; ++y) {
        const uint16_t * row = dimg->image.ptr<uint16_t>(y);
        depthToMeters(
          row, static_cast<size_t>(w), 0.001f, meters.data() + static_cast<size_t>(y) * w);
      }
    } else {
      for (int y = 0; y < h; ++y) {
        const float * row = dimg->image.ptr<float>(y);
        std::copy(row, row + w, meters.begin() + static_cast<size_t>(y) * w);
      }
    }

    cv::Mat bgr;
    if (p.use_rgb && color) {
      if (color->encoding == enc::BGR8 || color->encoding == enc::RGB8) {
        bgr = cv_bridge::toCvCopy(color, enc::BGR8)->image;
        if (bgr.cols != w || bgr.rows != h) {
          bgr.release();
        }
      } else {
        RCLCPP_WARN_ONCE(
          get_logger(), "color encoding '%s' unsupported; specular vote off",
          color->encoding.c_str());
      }
    }

    GlassResult res;
    filterGlass(meters, w, h, bgr.empty() ? nullptr : bgr.data, p, res);

    // Filtered depth: same encoding, flagged pixels -> 0 (16UC1) or NaN (32FC1).
    Image out = *depth;
    for (int y = 0; y < h; ++y) {
      uint8_t * row = out.data.data() + static_cast<size_t>(y) * out.step;
      for (int x = 0; x < w; ++x) {
        if (!res.mask[static_cast<size_t>(y) * w + x]) {
          continue;
        }
        if (is16) {
          reinterpret_cast<uint16_t *>(row)[x] = 0;
        } else {
          reinterpret_cast<float *>(row)[x] = std::numeric_limits<float>::quiet_NaN();
        }
      }
    }
    filtered_pub_->publish(out);

    Image mask;
    mask.header = depth->header;
    mask.height = h;
    mask.width = w;
    mask.encoding = enc::MONO8;
    mask.is_bigendian = false;
    mask.step = w;
    mask.data = res.mask;
    mask_pub_->publish(mask);

    if (want_cloud && info && info->k[0] > 0.0 && info->k[4] > 0.0) {
      const auto xyz = backProjectFlagged(
        res, static_cast<float>(info->k[0]), static_cast<float>(info->k[4]),
        static_cast<float>(info->k[2]), static_cast<float>(info->k[5]), p.cloud_stride);
      sensor_msgs::msg::PointCloud2 cloud;
      cloud.header = depth->header;
      sensor_msgs::PointCloud2Modifier mod(cloud);
      mod.setPointCloud2FieldsByString(1, "xyz");
      mod.resize(xyz.size() / 3);
      sensor_msgs::PointCloud2Iterator<float> ix(cloud, "x"), iy(cloud, "y"), iz(cloud, "z");
      for (size_t i = 0; i + 2 < xyz.size(); i += 3, ++ix, ++iy, ++iz) {
        *ix = xyz[i];
        *iy = xyz[i + 1];
        *iz = xyz[i + 2];
      }
      cloud_pub_->publish(cloud);
    }

    const double ms =
      std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::lock_guard<std::mutex> lk(mtx_);
    latencies_ms_.push_back(ms);
    if (latencies_ms_.size() > 100) {
      latencies_ms_.pop_front();
    }
    arrival_s_.push_back(now().seconds());
    if (arrival_s_.size() > 30) {
      arrival_s_.pop_front();
    }
    last_flagged_pct_ = 100.f * res.flagged_fraction;
    last_regions_ = res.regions_flagged;
    last_unbounded_ = res.regions_unbounded;
    last_passthrough_ = false;
  } catch (const std::exception & e) {  // never throw out of the callback
    RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 5000, "glass_filter callback: %s", e.what());
  }
}

void GlassFilterNode::fillDiagnostics(diagnostic_updater::DiagnosticStatusWrapper & stat)
{
  std::lock_guard<std::mutex> lk(mtx_);
  double mean = 0.0, p95 = 0.0, rate = 0.0;
  if (!latencies_ms_.empty()) {
    std::vector<double> v(latencies_ms_.begin(), latencies_ms_.end());
    for (double x : v) {
      mean += x;
    }
    mean /= static_cast<double>(v.size());
    std::sort(v.begin(), v.end());
    p95 = v[std::min(v.size() - 1, static_cast<size_t>(0.95 * static_cast<double>(v.size())))];
  }
  if (arrival_s_.size() >= 2 && arrival_s_.back() > arrival_s_.front()) {
    rate = static_cast<double>(arrival_s_.size() - 1) / (arrival_s_.back() - arrival_s_.front());
  }
  if (last_passthrough_) {
    stat.summary(diagnostic_msgs::msg::DiagnosticStatus::WARN, "unsupported depth encoding");
  } else if (latencies_ms_.empty()) {
    stat.summary(diagnostic_msgs::msg::DiagnosticStatus::WARN, "no frames yet");
  } else {
    stat.summary(diagnostic_msgs::msg::DiagnosticStatus::OK, "ok");
  }
  stat.add("flagged_percent", last_flagged_pct_);
  stat.add("regions_flagged", last_regions_);
  stat.add("regions_unbounded", last_unbounded_);
  stat.add("latency_ms_mean", mean);
  stat.add("latency_ms_p95", p95);
  stat.add("input_rate_hz", rate);
  stat.add("sensor_profile", profile_);
}

}  // namespace limit_case_ros2

RCLCPP_COMPONENTS_REGISTER_NODE(limit_case_ros2::GlassFilterNode)
