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

// Offline CLI: depth (and optional rgb) image folders in, masks + fill depth out. No ROS.
//   filter_cli --depth <dir> [--rgb <dir>] --out <dir> [--params file.yaml] [--depth-scale 0.001]
// Depth files: 16-bit PNG (units of --depth-scale, default mm) or float EXR/TIFF (meters).
// RGB files are matched by file stem. Prints "name,latency_ms" per frame and a total.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include "limit_case_ros2/glass_filter.hpp"
#include "opencv2/core.hpp"
#include "opencv2/imgcodecs.hpp"

using limit_case_ros2::GlassParams;
using limit_case_ros2::GlassResult;

namespace
{

// Reads the flat `key: value` lines of a ROS parameter YAML (nesting is ignored; keys are unique).
std::map<std::string, std::string> readFlatYaml(const std::string & path)
{
  std::map<std::string, std::string> kv;
  std::ifstream in(path);
  std::string line;
  while (std::getline(in, line)) {
    const auto hash = line.find('#');
    if (hash != std::string::npos) {
      line.erase(hash);
    }
    const auto colon = line.find(':');
    if (colon == std::string::npos) {
      continue;
    }
    auto trim = [](std::string s) {
      const char * ws = " \t\r\n\"'";
      const auto a = s.find_first_not_of(ws);
      if (a == std::string::npos) {
        return std::string();
      }
      return s.substr(a, s.find_last_not_of(ws) - a + 1);
    };
    const std::string k = trim(line.substr(0, colon)), v = trim(line.substr(colon + 1));
    if (!k.empty() && !v.empty()) {
      kv[k] = v;
    }
  }
  return kv;
}

GlassParams loadParams(const std::string & path)
{
  GlassParams p;
  if (path.empty()) {
    return p;
  }
  const auto kv = readFlatYaml(path);
  auto f = [&](const char * k, float & x) {
    const auto it = kv.find(k);
    if (it != kv.end()) {
      x = std::stof(it->second);
    }
  };
  auto i = [&](const char * k, int & x) {
    const auto it = kv.find(k);
    if (it != kv.end()) {
      x = std::stoi(it->second);
    }
  };
  auto b = [&](const char * k, bool & x) {
    const auto it = kv.find(k);
    if (it != kv.end()) {
      x = (it->second == "true");
    }
  };
  i("downsample", p.downsample);
  f("min_basin_depth_m", p.min_basin_depth_m);
  f("min_basin_depth_rel", p.min_basin_depth_rel);
  i("min_region_area_px", p.min_region_area_px);
  f("max_range_m", p.max_range_m);
  b("treat_invalid_as_wall", p.treat_invalid_as_wall);
  b("boundary_verify", p.boundary_verify);
  f("min_nearer_boundary_frac", p.min_nearer_boundary_frac);
  b("flag_hole_only", p.flag_hole_only);
  b("use_rgb", p.use_rgb);
  i("specular_v_thresh", p.specular_v_thresh);
  i("specular_s_thresh", p.specular_s_thresh);
  f("confidence_threshold", p.confidence_threshold);
  i("cloud_stride", p.cloud_stride);
  return p;
}

std::string stemOf(const std::string & path)
{
  const auto slash = path.find_last_of('/');
  std::string n = slash == std::string::npos ? path : path.substr(slash + 1);
  const auto dot = n.find_last_of('.');
  return dot == std::string::npos ? n : n.substr(0, dot);
}

void usage()
{
  std::fprintf(
    stderr,
    "usage: filter_cli --depth <dir> --out <dir> [--rgb <dir>] [--params <yaml>] "
    "[--depth-scale 0.001] [--set key=value ...] [--no-fill]\n");
}

}  // namespace

int main(int argc, char ** argv)
{
  // Newer OpenCV builds gate EXR I/O behind this variable; must be set before first use.
  setenv("OPENCV_IO_ENABLE_OPENEXR", "1", 0);

  std::string depth_dir, rgb_dir, out_dir, params_file;
  float depth_scale = 0.001f;
  std::vector<std::string> overrides;
  bool write_fill = true;
  for (int a = 1; a < argc; ++a) {
    const std::string s = argv[a];
    auto next = [&]() -> std::string { return a + 1 < argc ? argv[++a] : ""; };
    if (s == "--depth") {
      depth_dir = next();
    } else if (s == "--rgb") {
      rgb_dir = next();
    } else if (s == "--out") {
      out_dir = next();
    } else if (s == "--params") {
      params_file = next();
    } else if (s == "--depth-scale") {
      depth_scale = std::stof(next());
    } else if (s == "--set") {
      overrides.push_back(next());
    } else if (s == "--no-fill") {
      write_fill = false;
    } else {
      usage();
      return 2;
    }
  }
  if (depth_dir.empty() || out_dir.empty()) {
    usage();
    return 2;
  }

  GlassParams p = loadParams(params_file);
  for (const auto & o : overrides) {  // --set min_basin_depth_m=0.03 (for grid search)
    const auto eq = o.find('=');
    if (eq == std::string::npos) {
      continue;
    }
    const std::string k = o.substr(0, eq), v = o.substr(eq + 1);
    if (k == "downsample") {
      p.downsample = std::stoi(v);
    } else if (k == "min_basin_depth_m") {
      p.min_basin_depth_m = std::stof(v);
    } else if (k == "min_basin_depth_rel") {
      p.min_basin_depth_rel = std::stof(v);
    } else if (k == "min_region_area_px") {
      p.min_region_area_px = std::stoi(v);
    } else if (k == "max_range_m") {
      p.max_range_m = std::stof(v);
    } else if (k == "confidence_threshold") {
      p.confidence_threshold = std::stof(v);
    } else if (k == "treat_invalid_as_wall") {
      p.treat_invalid_as_wall = (v == "true");
    } else if (k == "boundary_verify") {
      p.boundary_verify = (v == "true");
    } else if (k == "min_nearer_boundary_frac") {
      p.min_nearer_boundary_frac = std::stof(v);
    } else if (k == "flag_hole_only") {
      p.flag_hole_only = (v == "true");
    } else if (k == "cloud_stride") {
      p.cloud_stride = std::stoi(v);
    } else if (k == "use_rgb") {
      p.use_rgb = (v == "true");
    } else {
      std::fprintf(stderr, "unknown --set key: %s\n", k.c_str());
      return 2;
    }
  }
  if (!rgb_dir.empty()) {
    p.use_rgb = true;
  }

  std::vector<std::string> files;
  for (const char * ext : {"png", "exr", "tiff", "tif"}) {
    std::vector<std::string> g;
    cv::glob(depth_dir + "/*." + ext, g, false);
    files.insert(files.end(), g.begin(), g.end());
  }
  std::sort(files.begin(), files.end());
  if (files.empty()) {
    std::fprintf(stderr, "no depth images in %s\n", depth_dir.c_str());
    return 1;
  }

  std::vector<std::string> rgbs;
  if (!rgb_dir.empty()) {
    for (const char * ext : {"png", "jpg", "jpeg"}) {
      std::vector<std::string> g;
      cv::glob(rgb_dir + "/*." + ext, g, false);
      rgbs.insert(rgbs.end(), g.begin(), g.end());
    }
  }
  std::map<std::string, std::string> rgb_by_stem;
  for (const auto & r : rgbs) {
    rgb_by_stem[stemOf(r)] = r;
  }

  const std::string mkdir = "mkdir -p '" + out_dir + "'";
  if (std::system(mkdir.c_str()) != 0) {
    return 1;
  }

  double total_ms = 0.0;
  int n_ok = 0;
  for (const auto & f : files) {
    cv::Mat raw = cv::imread(f, cv::IMREAD_UNCHANGED);
    if (raw.empty() || raw.channels() != 1) {
      std::fprintf(stderr, "skip (unreadable or not 1-channel): %s\n", f.c_str());
      continue;
    }
    std::vector<float> depth(static_cast<size_t>(raw.rows) * raw.cols);
    if (raw.depth() == CV_16U) {
      cv::Mat c = raw.isContinuous() ? raw : raw.clone();
      limit_case_ros2::depthToMeters(c.ptr<uint16_t>(), depth.size(), depth_scale, depth);
    } else {
      cv::Mat f32;
      raw.convertTo(f32, CV_32F);
      std::copy(f32.ptr<float>(), f32.ptr<float>() + depth.size(), depth.begin());
    }

    cv::Mat rgb;
    auto it = rgb_by_stem.find(stemOf(f));
    if (p.use_rgb && it != rgb_by_stem.end()) {
      rgb = cv::imread(it->second, cv::IMREAD_COLOR);
      if (rgb.rows != raw.rows || rgb.cols != raw.cols) {
        rgb.release();
      }
    }

    GlassResult res;
    const auto t0 = std::chrono::steady_clock::now();
    limit_case_ros2::filterGlass(
      depth, raw.cols, raw.rows, rgb.empty() ? nullptr : rgb.data, p, res);
    const double ms =
      std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    total_ms += ms;
    ++n_ok;

    const std::string stem = stemOf(f);
    cv::Mat mask(raw.rows, raw.cols, CV_8U, res.mask.data());
    cv::Mat fill(raw.rows, raw.cols, CV_32F, res.fill_depth.data());
    cv::imwrite(out_dir + "/" + stem + "_mask.png", mask);
    if (write_fill && !cv::imwrite(out_dir + "/" + stem + "_fill.exr", fill)) {
      std::fprintf(stderr, "warn: EXR write unavailable in this OpenCV; fill depth skipped\n");
    }
    std::printf("%s,%.3f\n", stem.c_str(), ms);
  }
  std::printf("TOTAL,%d,%.3f\n", n_ok, total_ms);
  return n_ok > 0 ? 0 : 1;
}
