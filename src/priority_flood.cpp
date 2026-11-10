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

#include "limit_case_ros2/priority_flood.hpp"

#include <cstddef>
#include <cstdint>
#include <queue>
#include <utility>

namespace limit_case_ros2
{

void priorityFlood(const std::vector<float> & elev, int w, int h, std::vector<float> & fill)
{
  const size_t n = static_cast<size_t>(w) * static_cast<size_t>(h);
  fill.assign(n, 0.0f);
  if (n == 0 || elev.size() != n) {
    return;
  }

  using Item = std::pair<float, int>;  // (level, index)
  std::priority_queue<Item, std::vector<Item>, std::greater<Item>> open;
  std::queue<int> pit;
  std::vector<uint8_t> closed(n, 0);

  auto seed = [&](int x, int y) {
    const int i = y * w + x;
    if (!closed[i]) {
      closed[i] = 1;
      fill[i] = elev[i];
      open.emplace(elev[i], i);
    }
  };
  for (int x = 0; x < w; ++x) {
    seed(x, 0);
    seed(x, h - 1);
  }
  for (int y = 0; y < h; ++y) {
    seed(0, y);
    seed(w - 1, y);
  }

  auto visit = [&](int c, int nx, int ny) {
    if (nx < 0 || ny < 0 || nx >= w || ny >= h) {
      return;
    }
    const int j = ny * w + nx;
    if (closed[j]) {
      return;
    }
    closed[j] = 1;
    if (elev[j] <= fill[c]) {
      fill[j] = fill[c];
      pit.push(j);
    } else {
      fill[j] = elev[j];
      open.emplace(elev[j], j);
    }
  };

  while (!open.empty() || !pit.empty()) {
    int c;
    if (!pit.empty()) {
      c = pit.front();
      pit.pop();
    } else {
      c = open.top().second;
      open.pop();
    }
    const int cx = c % w, cy = c / w;
    visit(c, cx - 1, cy);
    visit(c, cx + 1, cy);
    visit(c, cx, cy - 1);
    visit(c, cx, cy + 1);
  }
}

}  // namespace limit_case_ros2
