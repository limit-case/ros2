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
// ROS-free core of the glass filter. No rclcpp/cv_bridge here.
#include <cstddef>
#include <cstdint>
#include <vector>

namespace limit_case_ros2
{

struct GlassParams
{
  int downsample = 2;
  float min_basin_depth_m = 0.02f;
  float min_basin_depth_rel = 0.03f;
  int min_region_area_px = 150;  // at full resolution
  float max_range_m = 4.0f;
  // Default false: holes are impassable and a patch reachable only through holes
  // is ignored. true = BFS wall rule (holes take the elevation of the valid cells they border).
  bool treat_invalid_as_wall = false;
  // boundary_verify: holes are impassable finite walls for enclosure. A region is flagged only if
  // at least `min_nearer_boundary_frac` of its boundary is valid pixels nearer than the region;
  // the cloud depth is the median of those pixels. Overrides treat_invalid_as_wall.
  bool boundary_verify = false;
  float min_nearer_boundary_frac = 0.1f;
  // boundary_verify only: also flag regions with no nearer valid boundary (holes alone);
  // mask only, no cloud.
  bool flag_hole_only = false;
  bool use_rgb = false;
  int specular_v_thresh = 240;  // HSV V (0..255) above which a pixel is a highlight
  int specular_s_thresh = 40;   // HSV S (0..255) below which a pixel is a highlight
  float confidence_threshold = 0.5f;
  int cloud_stride = 2;
};

struct GlassResult
{
  int width = 0, height = 0;
  std::vector<uint8_t> mask;      // w*h, 255 = suspected see-through
  std::vector<float> fill_depth;  // w*h meters, glass surface estimate where mask set (0 = none)
  int regions_total = 0;          // candidate regions after area filter
  int regions_flagged = 0;
  int regions_unbounded = 0;      // dropped: touching the image border
  float flagged_fraction = 0.0f;  // flagged pixels / all pixels
};

/// depth_m: row-major w*h float meters; invalid = 0, NaN, negative or > max_range_m.
/// bgr: optional w*h*3 bgr8 (only read if params.use_rgb), may be nullptr.
void filterGlass(
  const std::vector<float> & depth_m, int w, int h, const uint8_t * bgr, const GlassParams & params,
  GlassResult & out);

/// 16UC1 depth -> meters (scale = meters per unit, 0.001 for mm). 0 stays invalid.
void depthToMeters(const uint16_t * src, size_t n, float scale, float * dst);
void depthToMeters(const uint16_t * src, size_t n, float scale, std::vector<float> & dst);

/// Back-project flagged pixels (every `stride`-th row/col) at their fill depth.
/// Returns packed xyz float32 triplets (x right, y down, z forward) in the depth frame.
std::vector<float> backProjectFlagged(
  const GlassResult & res, float fx, float fy, float cx, float cy, int stride);

}  // namespace limit_case_ros2
