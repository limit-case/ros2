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

#include "limit_case_ros2/glass_filter.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>

#include "limit_case_ros2/priority_flood.hpp"

namespace limit_case_ros2
{

namespace
{

inline bool validDepth(float d, float max_range)
{
  return std::isfinite(d) && d > 0.0f && d <= max_range;
}

// Give each invalid cell a finite wall elevation: the max elevation of the valid cells it
// borders, propagated outward (BFS). Keeps fill levels finite when a patch is ringed by holes.
void assignWalls(std::vector<float> & e, const std::vector<uint8_t> & valid, int w, int h)
{
  std::vector<int> frontier;
  std::vector<uint8_t> done(valid);
  for (int i = 0; i < w * h; ++i) {
    if (valid[i]) {
      frontier.push_back(i);
    }
  }
  const int dx[4] = {-1, 1, 0, 0}, dy[4] = {0, 0, -1, 1};
  while (!frontier.empty()) {
    std::vector<int> next;
    std::vector<float> val;
    for (int c : frontier) {
      const int cx = c % w, cy = c / w;
      for (int k = 0; k < 4; ++k) {
        const int nx = cx + dx[k], ny = cy + dy[k];
        if (nx < 0 || ny < 0 || nx >= w || ny >= h) {
          continue;
        }
        const int j = ny * w + nx;
        if (done[j]) {
          continue;
        }
        if (
          e[j] == -std::numeric_limits<float>::infinity() ||
          e[j] == std::numeric_limits<float>::infinity()) {
          e[j] = e[c];
          next.push_back(j);
        } else {
          e[j] = std::max(e[j], e[c]);  // already touched this wave
        }
      }
    }
    // Mark wave as done only after the whole wave (so max over same-wave parents applies).
    for (int j : next) {
      done[j] = 1;
    }
    frontier.swap(next);
  }
}

}  // namespace

void depthToMeters(const uint16_t * src, size_t n, float scale, float * dst)
{
  for (size_t i = 0; i < n; ++i) {
    dst[i] = static_cast<float>(src[i]) * scale;
  }
}

void depthToMeters(const uint16_t * src, size_t n, float scale, std::vector<float> & dst)
{
  dst.resize(n);
  depthToMeters(src, n, scale, dst.data());
}

void filterGlass(
  const std::vector<float> & depth_m, int w, int h, const uint8_t * bgr, const GlassParams & p,
  GlassResult & out)
{
  const float inf = std::numeric_limits<float>::infinity();
  out = GlassResult();
  out.width = w;
  out.height = h;
  const size_t N = static_cast<size_t>(w) * static_cast<size_t>(h);
  out.mask.assign(N, 0);
  out.fill_depth.assign(N, 0.0f);
  if (w <= 0 || h <= 0 || depth_m.size() != N) {
    return;
  }

  const int d = std::max(1, p.downsample);
  const int lw = (w + d - 1) / d, lh = (h + d - 1) / d;
  const size_t LN = static_cast<size_t>(lw) * lh;

  // 1. Downsample with min-of-valid (nearest surface wins).
  std::vector<float> ld(LN, 0.0f);
  std::vector<uint8_t> valid(LN, 0);
  for (int ly = 0; ly < lh; ++ly) {
    for (int lx = 0; lx < lw; ++lx) {
      float best = inf;
      for (int y = ly * d; y < std::min(h, (ly + 1) * d); ++y) {
        for (int x = lx * d; x < std::min(w, (lx + 1) * d); ++x) {
          const float v = depth_m[static_cast<size_t>(y) * w + x];
          if (validDepth(v, p.max_range_m) && v < best) {
            best = v;
          }
        }
      }
      if (best != inf) {
        ld[static_cast<size_t>(ly) * lw + lx] = best;
        valid[static_cast<size_t>(ly) * lw + lx] = 1;
      }
    }
  }

  // 2. Elevation map e = -depth. Invalid cells depend on the mode:
  //   default            +inf (impassable; a patch reachable only through holes is ignored)
  //   treat_invalid_as_wall  finite BFS wall (see assignWalls)
  //   boundary_verify    finite impassable wall at the nearest valid elevation
  std::vector<float> e(LN);
  bool any_valid = false;
  float emax = -inf;
  for (size_t i = 0; i < LN; ++i) {
    if (valid[i]) {
      any_valid = true;
      emax = std::max(emax, -ld[i]);
    }
  }
  if (!any_valid) {
    return;
  }
  const bool verify = p.boundary_verify;
  const bool bfs = p.treat_invalid_as_wall && !verify;
  for (size_t i = 0; i < LN; ++i) {
    e[i] = valid[i] ? -ld[i] : (verify ? emax : (bfs ? -inf : inf));
  }
  if (bfs) {
    assignWalls(e, valid, lw, lh);
  }

  // 3. Priority-Flood.
  std::vector<float> fill;
  priorityFlood(e, lw, lh, fill);

  // 4/5. Basin depth and candidates (valid cells with finite fill only).
  std::vector<float> basin(LN, 0.0f);
  std::vector<uint8_t> cand(LN, 0);
  for (size_t i = 0; i < LN; ++i) {
    if (!valid[i] || !std::isfinite(fill[i])) {
      continue;
    }
    const float b = fill[i] - e[i];
    basin[i] = b;
    if (b > p.min_basin_depth_m && b > p.min_basin_depth_rel * ld[i]) {
      cand[i] = 1;
    }
  }

  // Optional specular map at low-res (any highlight in the block after a 5x5 dilation).
  std::vector<uint8_t> spec_lo;
  if (p.use_rgb && bgr != nullptr) {
    std::vector<uint8_t> spec(N, 0), tmp(N, 0);
    for (size_t i = 0; i < N; ++i) {
      const int b = bgr[3 * i], g = bgr[3 * i + 1], r = bgr[3 * i + 2];
      const int mx = std::max({b, g, r}), mn = std::min({b, g, r});
      const int s = mx == 0 ? 0 : (255 * (mx - mn)) / mx;
      spec[i] = (mx > p.specular_v_thresh && s < p.specular_s_thresh) ? 1 : 0;
    }
    for (int y = 0; y < h; ++y) {  // horizontal pass, radius 2
      for (int x = 0; x < w; ++x) {
        uint8_t m = 0;
        for (int k = std::max(0, x - 2); k <= std::min(w - 1, x + 2); ++k) {
          m |= spec[static_cast<size_t>(y) * w + k];
        }
        tmp[static_cast<size_t>(y) * w + x] = m;
      }
    }
    spec_lo.assign(LN, 0);
    for (int y = 0; y < h; ++y) {  // vertical pass fused with block reduction
      for (int x = 0; x < w; ++x) {
        uint8_t m = 0;
        for (int k = std::max(0, y - 2); k <= std::min(h - 1, y + 2); ++k) {
          m |= tmp[static_cast<size_t>(k) * w + x];
        }
        if (m) {
          spec_lo[static_cast<size_t>(y / d) * lw + x / d] = 1;
        }
      }
    }
  }

  // 6/7. Connected components (8-conn), area/border filter, scoring.
  const int min_area = std::max(1, p.min_region_area_px / (d * d));
  std::vector<int> label(LN, -1);
  std::vector<uint8_t> flagged_lo(LN, 0);
  std::vector<float> cell_fill(LN, 0.0f);  // verify mode: per-region cloud depth (0 = none)
  std::vector<int> stamp(LN, -1);
  int rid = 0;
  std::vector<int> stack, members;
  for (size_t s0 = 0; s0 < LN; ++s0) {
    if (!cand[s0] || label[s0] >= 0) {
      continue;
    }
    members.clear();
    stack.assign(1, static_cast<int>(s0));
    label[s0] = 1;
    bool touches_border = false;
    while (!stack.empty()) {
      const int c = stack.back();
      stack.pop_back();
      members.push_back(c);
      const int cx = c % lw, cy = c / lw;
      if (cx <= 1 || cy <= 1 || cx >= lw - 2 || cy >= lh - 2) {
        touches_border = true;
      }
      for (int oy = -1; oy <= 1; ++oy) {
        for (int ox = -1; ox <= 1; ++ox) {
          const int nx = cx + ox, ny = cy + oy;
          if (nx < 0 || ny < 0 || nx >= lw || ny >= lh) {
            continue;
          }
          const int j = ny * lw + nx;
          if (cand[j] && label[j] < 0) {
            label[j] = 1;
            stack.push_back(j);
          }
        }
      }
    }
    if (static_cast<int>(members.size()) < min_area) {
      continue;
    }
    if (touches_border) {
      ++out.regions_unbounded;
      continue;
    }
    ++out.regions_total;

    // Score. Perimeter = member cells with a 4-neighbour outside the region.
    double sum_b = 0.0;
    int perim = 0, perim_inv = 0, spec_cnt = 0;
    for (int c : members) {
      label[c] = 2;
    }  // mark current region
    for (int c : members) {
      sum_b += basin[c];
      if (!spec_lo.empty() && spec_lo[c]) {
        ++spec_cnt;
      }
      const int cx = c % lw, cy = c / lw;
      bool edge = false, near_invalid = false;
      const int dx[4] = {-1, 1, 0, 0}, dy[4] = {0, 0, -1, 1};
      for (int k = 0; k < 4; ++k) {
        const int nx = cx + dx[k], ny = cy + dy[k];
        if (nx < 0 || ny < 0 || nx >= lw || ny >= lh) {
          edge = true;
          continue;
        }
        const int j = ny * lw + nx;
        if (label[j] != 2) {
          edge = true;
          if (!valid[j]) {
            near_invalid = true;
          }
        }
      }
      if (edge) {
        ++perim;
        if (near_invalid) {
          ++perim_inv;
        }
      }
    }
    const float n = static_cast<float>(members.size());
    const float geometry = std::min(1.0f, std::max(0.0f, static_cast<float>(sum_b / n) / 0.05f));
    const float adj = perim > 0 ? static_cast<float>(perim_inv) / perim : 0.0f;
    float score;
    if (!spec_lo.empty()) {
      const float spec = std::min(1.0f, (spec_cnt / n) / 0.05f);
      score = 0.6f * geometry + 0.25f * adj + 0.15f * spec;
    } else {
      score = (0.6f * geometry + 0.25f * adj) / 0.85f;
    }
    if (score < p.confidence_threshold) {
      continue;
    }
    if (!verify) {
      ++out.regions_flagged;
      for (int c : members) {
        flagged_lo[c] = 1;
      }
      continue;
    }
    // Variant (c): the boundary must contain valid pixels nearer than the region.
    std::vector<float> depths;
    for (int c : members) {
      depths.push_back(ld[c]);
    }
    std::nth_element(depths.begin(), depths.begin() + depths.size() / 2, depths.end());
    const float region_med = depths[depths.size() / 2];
    std::vector<float> nearer;
    ++rid;
    for (int c : members) {
      const int cx = c % lw, cy = c / lw;
      const int ddx[4] = {-1, 1, 0, 0}, ddy[4] = {0, 0, -1, 1};
      for (int k = 0; k < 4; ++k) {
        const int nx = cx + ddx[k], ny = cy + ddy[k];
        if (nx < 0 || ny < 0 || nx >= lw || ny >= lh) {
          continue;
        }
        const int j = ny * lw + nx;
        if (label[j] == 2 || !valid[j] || stamp[j] == rid) {
          continue;
        }
        if (ld[j] < region_med - p.min_basin_depth_m) {
          stamp[j] = rid;
          nearer.push_back(ld[j]);
        }
      }
    }
    const float frac = perim > 0 ? static_cast<float>(nearer.size()) / perim : 0.0f;
    float cloud_z = 0.0f;
    if (!nearer.empty() && frac >= p.min_nearer_boundary_frac) {
      std::nth_element(nearer.begin(), nearer.begin() + nearer.size() / 2, nearer.end());
      cloud_z = nearer[nearer.size() / 2];
    } else if (!(nearer.empty() && p.flag_hole_only)) {
      continue;  // not enough valid nearer boundary (holes alone, or too little)
    }
    ++out.regions_flagged;
    for (int c : members) {
      flagged_lo[c] = 1;
      cell_fill[c] = cloud_z;
    }
  }

  // 8. Upsample (nearest) and AND with the full-res candidate test.
  size_t flagged = 0;
  for (int y = 0; y < h; ++y) {
    for (int x = 0; x < w; ++x) {
      const size_t li = static_cast<size_t>(y / d) * lw + x / d;
      if (!flagged_lo[li]) {
        continue;
      }
      const size_t i = static_cast<size_t>(y) * w + x;
      const float z = depth_m[i];
      if (!validDepth(z, p.max_range_m)) {
        continue;
      }
      float fill_z = -fill[li];  // enclosure level (test only in verify mode)
      const float b = z - fill_z;
      if (b > p.min_basin_depth_m && b > p.min_basin_depth_rel * z) {
        out.mask[i] = 255;
        out.fill_depth[i] = verify ? cell_fill[li] : fill_z;
        ++flagged;
      }
    }
  }
  out.flagged_fraction = static_cast<float>(flagged) / static_cast<float>(N);
}

std::vector<float> backProjectFlagged(
  const GlassResult & res, float fx, float fy, float cx, float cy, int stride)
{
  std::vector<float> xyz;
  const int s = std::max(1, stride);
  for (int v = 0; v < res.height; v += s) {
    for (int u = 0; u < res.width; u += s) {
      const size_t i = static_cast<size_t>(v) * res.width + u;
      if (!res.mask[i]) {
        continue;
      }
      const float z = res.fill_depth[i];
      if (!(z > 0.0f)) {
        continue;
      }  // no depth estimate for this region
      xyz.push_back((u - cx) * z / fx);
      xyz.push_back((v - cy) * z / fy);
      xyz.push_back(z);
    }
  }
  return xyz;
}

}  // namespace limit_case_ros2
