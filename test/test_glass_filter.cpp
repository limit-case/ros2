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

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

#include "limit_case_ros2/glass_filter.hpp"

using limit_case_ros2::filterGlass;
using limit_case_ros2::GlassParams;
using limit_case_ros2::GlassResult;

namespace
{
constexpr int W = 160, H = 120;

// Scene in integer millimetres so the 16UC1 and 32FC1 paths are exactly comparable.
struct Scene
{
  std::vector<uint16_t> mm = std::vector<uint16_t>(W * H, 1500);
  void rect(int x0, int y0, int x1, int y1, uint16_t v)
  {
    for (int y = y0; y < y1; ++y) {
      for (int x = x0; x < x1; ++x) {
        mm[y * W + x] = v;
      }
    }
  }
  std::vector<float> meters() const
  {
    std::vector<float> f;
    limit_case_ros2::depthToMeters(mm.data(), mm.size(), 0.001f, f);
    return f;
  }
};

// Wall 1.5 m, ring at 1.0 m (x 50..110, y 30..90), glass patch reading 1.9 m (x 65..95, y 45..75).
Scene glassScene()
{
  Scene s;
  s.rect(50, 30, 110, 90, 1000);
  s.rect(65, 45, 95, 75, 1900);
  return s;
}

int countMask(const GlassResult & r, int x0, int y0, int x1, int y1)
{
  int n = 0;
  for (int y = y0; y < y1; ++y) {
    for (int x = x0; x < x1; ++x) {
      n += r.mask[y * W + x] ? 1 : 0;
    }
  }
  return n;
}
}  // namespace

TEST(GlassFilter, PatchInsideRingFlagged)
{
  GlassResult r;
  filterGlass(glassScene().meters(), W, H, nullptr, GlassParams(), r);
  const int patch = 30 * 30;
  EXPECT_GE(countMask(r, 65, 45, 95, 75), static_cast<int>(0.8 * patch));
  EXPECT_EQ(countMask(r, 0, 0, W, 30), 0);      // wall above
  EXPECT_EQ(countMask(r, 50, 30, 110, 45), 0);  // ring top band
  EXPECT_EQ(countMask(r, 50, 75, 110, 90), 0);  // ring bottom band
  EXPECT_EQ(countMask(r, 50, 45, 65, 75), 0);   // ring left band
  EXPECT_EQ(r.regions_flagged, 1);
  // Fill depth = enclosing ring (1.0 m).
  EXPECT_NEAR(r.fill_depth[60 * W + 80], 1.0f, 0.02f);
  // Point cloud sits on the ring plane.
  auto xyz = limit_case_ros2::backProjectFlagged(r, 200.f, 200.f, 80.f, 60.f, 2);
  ASSERT_FALSE(xyz.empty());
  EXPECT_EQ(xyz.size() % 3, 0u);
  EXPECT_NEAR(xyz[2], 1.0f, 0.02f);
}

TEST(GlassFilter, PatchTouchingBorderNotFlagged)
{
  Scene s;
  s.rect(0, 0, 40, 40, 1000);  // frame touching the corner
  s.rect(0, 0, 30, 30, 1900);  // "glass" reaching the image border
  GlassResult r;
  filterGlass(s.meters(), W, H, nullptr, GlassParams(), r);
  EXPECT_EQ(countMask(r, 0, 0, W, H), 0);
}

TEST(GlassFilter, OpaqueBoxNothingFlagged)
{
  Scene s;
  s.rect(50, 30, 110, 90, 1000);  // closer box on a wall: a hill, no basin
  GlassResult r;
  filterGlass(s.meters(), W, H, nullptr, GlassParams(), r);
  EXPECT_EQ(countMask(r, 0, 0, W, H), 0);
  EXPECT_EQ(r.regions_flagged, 0);
}

TEST(GlassFilter, InvalidRingWallMode)
{
  Scene s;
  s.rect(50, 30, 110, 90, 0);    // invalid ring
  s.rect(65, 45, 95, 75, 1900);  // patch reading far, enclosed by holes only
  GlassParams p;
  p.treat_invalid_as_wall = true;
  GlassResult r;
  filterGlass(s.meters(), W, H, nullptr, p, r);
  EXPECT_GE(countMask(r, 65, 45, 95, 75), static_cast<int>(0.8 * 900));
  EXPECT_EQ(countMask(r, 0, 0, W, 30), 0);
  EXPECT_EQ(countMask(r, 50, 30, 110, 45), 0);  // invalid pixels are never flagged
  EXPECT_TRUE(std::isfinite(r.fill_depth[60 * W + 80]));

  p.treat_invalid_as_wall = false;  // holes are skipped: patch unreachable, not a basin
  filterGlass(s.meters(), W, H, nullptr, p, r);
  EXPECT_EQ(countMask(r, 0, 0, W, H), 0);
}

TEST(GlassFilter, Encoding16And32Identical)
{
  Scene s = glassScene();
  std::vector<float> f32(s.mm.size());
  for (size_t i = 0; i < f32.size(); ++i) {
    f32[i] = static_cast<float>(s.mm[i]) * 0.001f;
  }
  GlassResult a, b;
  filterGlass(s.meters(), W, H, nullptr, GlassParams(), a);
  filterGlass(f32, W, H, nullptr, GlassParams(), b);
  EXPECT_EQ(a.mask, b.mask);
  EXPECT_GT(countMask(a, 0, 0, W, H), 0);
}

TEST(GlassFilter, DownsampleOneAlsoWorksAndNaNIsInvalid)
{
  std::vector<float> d = glassScene().meters();
  d[10] = std::numeric_limits<float>::quiet_NaN();
  GlassParams p;
  p.downsample = 1;
  GlassResult r;
  filterGlass(d, W, H, nullptr, p, r);
  EXPECT_GE(countMask(r, 65, 45, 95, 75), static_cast<int>(0.8 * 900));
  EXPECT_EQ(r.mask[10], 0);
}

TEST(GlassFilter, TinyRegionIgnoredAndBadInputSafe)
{
  Scene s;
  s.rect(50, 30, 110, 90, 1000);
  s.rect(78, 58, 82, 62, 1900);  // 4x4 pit, far below min_region_area_px
  GlassResult r;
  filterGlass(s.meters(), W, H, nullptr, GlassParams(), r);
  EXPECT_EQ(countMask(r, 0, 0, W, H), 0);

  filterGlass(std::vector<float>(10, 1.f), W, H, nullptr, GlassParams(), r);  // size mismatch
  EXPECT_EQ(countMask(r, 0, 0, W, H), 0);
  filterGlass(std::vector<float>(W * H, 0.f), W, H, nullptr, GlassParams(), r);  // all invalid
  EXPECT_EQ(countMask(r, 0, 0, W, H), 0);
}

TEST(GlassFilter, SpecularVoteRaisesWeakRegion)
{
  // Shallow basin (3.5 cm): geometry-only score = 0.6*0.7/0.85 = 0.494 < 0.5, highlights lift it.
  Scene s;
  s.rect(50, 30, 110, 90, 1000);
  s.rect(65, 45, 95, 75, 1035);
  GlassParams p;
  p.use_rgb = true;
  std::vector<uint8_t> bgr(W * H * 3, 100);
  GlassResult r;
  filterGlass(s.meters(), W, H, bgr.data(), p, r);
  EXPECT_EQ(r.regions_flagged, 0);
  for (int y = 45; y < 75; ++y) {
    for (int x = 65; x < 95; ++x) {
      for (int c = 0; c < 3; ++c) {
        bgr[(y * W + x) * 3 + c] = 255;
      }  // white highlight
    }
  }
  filterGlass(s.meters(), W, H, bgr.data(), p, r);
  EXPECT_EQ(r.regions_flagged, 1);
}

TEST(GlassFilter, NonDivisibleSizeAndDownsample)
{
  const int w = 161, h = 121;  // not multiples of the downsample factor
  std::vector<float> d(static_cast<size_t>(w) * h, 1.5f);
  for (int y = 30; y < 90; ++y) {
    for (int x = 50; x < 110; ++x) {
      d[y * w + x] = 1.0f;
    }
  }
  for (int y = 45; y < 75; ++y) {
    for (int x = 65; x < 95; ++x) {
      d[y * w + x] = 1.9f;
    }
  }
  GlassParams p;
  p.downsample = 3;
  GlassResult r;
  filterGlass(d, w, h, nullptr, p, r);
  EXPECT_EQ(r.mask.size(), static_cast<size_t>(w) * h);
  int n = 0;
  for (int y = 45; y < 75; ++y) {
    for (int x = 65; x < 95; ++x) {
      n += r.mask[y * w + x] ? 1 : 0;
    }
  }
  EXPECT_GE(n, static_cast<int>(0.7 * 900));
  EXPECT_EQ(r.regions_flagged, 1);
}

TEST(GlassFilter, DefaultsSkipInvalidAsWalls)
{
  GlassParams p;
  EXPECT_FALSE(p.treat_invalid_as_wall);
  EXPECT_FALSE(p.boundary_verify);
}

TEST(GlassFilter, BoundaryVerifyUsesNearerValidBoundary)
{
  Scene s = glassScene();      // ring 1.0 m, patch 1.9 m, wall 1.5 m
  s.rect(50, 30, 110, 45, 0);  // top band of the ring becomes holes; rest of the ring stays valid
  GlassParams p;
  p.boundary_verify = true;
  GlassResult r;
  filterGlass(s.meters(), W, H, nullptr, p, r);
  EXPECT_GE(countMask(r, 65, 45, 95, 75), static_cast<int>(0.8 * 900));
  EXPECT_NEAR(r.fill_depth[60 * W + 80], 1.0f, 0.02f);  // median of the nearer boundary pixels
  auto xyz = limit_case_ros2::backProjectFlagged(r, 200.f, 200.f, 80.f, 60.f, 2);
  ASSERT_FALSE(xyz.empty());
  EXPECT_NEAR(xyz[2], 1.0f, 0.02f);
}

TEST(GlassFilter, BoundaryVerifyHoleOnlyRegions)
{
  Scene s;
  s.rect(50, 30, 110, 90, 0);  // patch ringed only by holes
  s.rect(65, 45, 95, 75, 1900);
  GlassParams p;
  p.boundary_verify = true;
  GlassResult r;
  filterGlass(s.meters(), W, H, nullptr, p, r);
  EXPECT_EQ(countMask(r, 0, 0, W, H), 0);  // holes alone: not flagged

  p.flag_hole_only = true;  // opt-in: mask only, no cloud
  filterGlass(s.meters(), W, H, nullptr, p, r);
  EXPECT_GE(countMask(r, 65, 45, 95, 75), static_cast<int>(0.8 * 900));
  EXPECT_EQ(r.fill_depth[60 * W + 80], 0.0f);
  EXPECT_TRUE(limit_case_ros2::backProjectFlagged(r, 200.f, 200.f, 80.f, 60.f, 1).empty());
}
