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

#pragma once
// ROS wrapper around the ROS-free core (glass_filter.hpp). Composable node.
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "diagnostic_updater/diagnostic_updater.hpp"
#include "limit_case_ros2/glass_filter.hpp"
#include "message_filters/subscriber.h"
#include "message_filters/sync_policies/approximate_time.h"
#include "message_filters/synchronizer.h"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/camera_info.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"

namespace limit_case_ros2
{

class GlassFilterNode : public rclcpp::Node
{
public:
  explicit GlassFilterNode(const rclcpp::NodeOptions & options);

private:
  using Image = sensor_msgs::msg::Image;
  using SyncPolicy = message_filters::sync_policies::ApproximateTime<Image, Image>;

  void declareParams();
  rcl_interfaces::msg::SetParametersResult onParams(const std::vector<rclcpp::Parameter> & ps);
  void onDepth(const Image::ConstSharedPtr & depth, const Image::ConstSharedPtr & color);
  void onCameraInfo(const sensor_msgs::msg::CameraInfo::ConstSharedPtr msg);
  void fillDiagnostics(diagnostic_updater::DiagnosticStatusWrapper & stat);

  std::mutex mtx_;  // guards params_ and stats
  GlassParams params_;
  bool publish_cloud_ = true;
  std::string profile_;

  rclcpp::Subscription<Image>::SharedPtr depth_sub_;
  rclcpp::Subscription<sensor_msgs::msg::CameraInfo>::SharedPtr info_sub_;
  std::shared_ptr<message_filters::Subscriber<Image>> sync_depth_sub_, sync_color_sub_;
  std::shared_ptr<message_filters::Synchronizer<SyncPolicy>> sync_;
  rclcpp::Publisher<Image>::SharedPtr filtered_pub_, mask_pub_;
  rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr cloud_pub_;
  rclcpp::node_interfaces::OnSetParametersCallbackHandle::SharedPtr param_cb_;
  diagnostic_updater::Updater updater_;

  sensor_msgs::msg::CameraInfo::ConstSharedPtr info_;
  std::deque<double> latencies_ms_;  // last 100
  std::deque<double> arrival_s_;     // last 30 arrival times
  float last_flagged_pct_ = 0.f;
  int last_regions_ = 0, last_unbounded_ = 0;
  bool last_passthrough_ = false;
};

}  // namespace limit_case_ros2
