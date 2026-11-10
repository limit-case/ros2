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

#include <limits>
#include <vector>

#include "limit_case_ros2/priority_flood.hpp"

using limit_case_ros2::priorityFlood;

TEST(PriorityFlood, FivePitFilledToRim)
{
  // Rim at 5, 3x3 interior; center pit at 1, ring at 3.
  std::vector<float> e = {5, 5, 5, 5, 5, 5, 3, 3, 3, 5, 5, 3, 1,
                          3, 5, 5, 3, 3, 3, 5, 5, 5, 5, 5, 5};
  std::vector<float> f;
  priorityFlood(e, 5, 5, f);
  for (int y = 0; y < 5; ++y) {
    for (int x = 0; x < 5; ++x) {
      EXPECT_FLOAT_EQ(f[y * 5 + x], 5.0f) << x << "," << y;
    }
  }
}

TEST(PriorityFlood, BordersNeverRaisedAndFillAtLeastElev)
{
  std::vector<float> e = {9, 2, 9, 9, 9, 9, 9, 9, 1, 1, 9, 9, 9, 9, 9, 9, 0, 4, 4, 4, 9, 9, 9, 4, 0,
                          3, 4, 9, 9, 9, 4, 3, 0, 4, 9, 9, 9, 4, 4, 4, 4, 9, 9, 9, 9, 9, 9, 9, 2};
  std::vector<float> f;
  priorityFlood(e, 7, 7, f);
  for (int y = 0; y < 7; ++y) {
    for (int x = 0; x < 7; ++x) {
      const int i = y * 7 + x;
      EXPECT_GE(f[i], e[i]);
      if (x == 0 || y == 0 || x == 6 || y == 6) {
        EXPECT_FLOAT_EQ(f[i], e[i]);
      }
    }
  }
  // Closed pit (rim 4, interior 0/3) fills to 4.
  EXPECT_FLOAT_EQ(f[3 * 7 + 3], 4.0f);
  EXPECT_FLOAT_EQ(f[4 * 7 + 4], 4.0f);
  EXPECT_FLOAT_EQ(f[3 * 7 + 4], 4.0f);
  // Channel (0,1)-(1,1)-(2,1)... drains out through border cell (1,0)=2: stays low.
  EXPECT_FLOAT_EQ(f[1 * 7 + 1], 2.0f);  // 1 raised only to the outlet level 2
  EXPECT_FLOAT_EQ(f[1 * 7 + 2], 2.0f);
}

TEST(PriorityFlood, FlatAndTinyGrids)
{
  std::vector<float> f;
  priorityFlood({1, 1, 1, 1}, 2, 2, f);
  EXPECT_EQ(f.size(), 4u);
  for (float v : f) {
    EXPECT_FLOAT_EQ(v, 1.0f);
  }
  priorityFlood({}, 0, 0, f);
  EXPECT_TRUE(f.empty());
}

TEST(PriorityFlood, InfWallsBoundButStayInf)
{
  const float inf = std::numeric_limits<float>::infinity();
  std::vector<float> e = {0,   0, 0, 0,   0,   0,   inf, inf, inf, 0, 0, inf, -2,
                          inf, 0, 0, inf, inf, inf, 0,   0,   0,   0, 0, 0};
  std::vector<float> f;
  priorityFlood(e, 5, 5, f);
  EXPECT_FLOAT_EQ(f[12], inf);  // enclosed by walls: filled to wall level
  EXPECT_FLOAT_EQ(f[6], inf);
}
