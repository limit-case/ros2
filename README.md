# limit_case_ros2

**Catch depth cameras lying about glass.**

<!-- TODO(owner, Day 8): demo GIF here: raw cloud passing through glass -> filtered -> red suspected obstacles.
     ![demo](docs/demo.gif) -->

A ROS 2 node that sits between a depth camera driver and your navigation or manipulation stack. It finds
**silent depth failures on transparent objects**: pixels where the camera returns a confident value that is
wrong because it measured the surface *behind* the glass.

> **Not a safety certification.** This is research-grade software. Do not rely on it as the only
> protection against collisions. It has no safety certification of any kind.

## Why this exists

<!-- TODO(owner): origin story, 3 sentences. -->

GlassBench ([github.com/limit-case/glassbench](https://github.com/limit-case/glassbench)) found that
99.8%+ of wrong pixels on transparent objects read **too far**. That one fact drives the algorithm.

## Results

v0.1 is an **honest depth-only baseline**. On ClearGrasp D435 test the filter flags **14.6%** of confidently wrong glass pixels while losing **7.9%** of correct ones, at **7.4 ms** per 1280x720 frame (core only, `downsample: 3`).
That is a small share of the problem: most wrong pixels survive. See "Why depth alone misses glass" below.

| Set (tolerance 5%, transparent-mask pixels) | Wrong among returned (raw -> after) | Wrong pixels removed | Correct pixels lost | Outside-mask flagged | Core latency mean / p95 (ms) |
|---|---|---|---|---|---|
| D435 test (23 scenes), run once | 23.9% -> 22.6% | 14.6% | 7.9% | 8.7% | 7.4 / 7.6 |
| D415 test (90 scenes), run once | 36.9% -> 35.2% | 11.4% | 4.5% | 8.7% | 3.3 / 3.7 |
| D435 val (173), the tuning set | 51.3% -> 48.6% | 14.6% | 4.7% | 6.0% | 7.3 / 8.6 |

Notes:
- Tuned **only** on ClearGrasp D435 val with `scripts/tune_val.py`; the D435 and D415 test sets were each run once,
  with the `realsense_d435.yaml` profile. The tuning budget was "correct pixels lost <= 5% on val"; D435 test exceeds it
  (7.9%), so the val budget does not transfer exactly.
- "Wrong among returned" = wrong / (correct + wrong): the chance that a depth the sensor chose to report is wrong.
- Definitions follow [GlassBench](https://github.com/limit-case/glassbench) `docs/measurement.md`: GT-valid pixels only;
  missing = raw 0 and never counted as wrong; wrong = returned and more than 5% off ground truth.
- Latency is the core filter only (`filter_cli`), on an arm64 Docker VM with 2 CPUs, Release build. It excludes image
  decoding, `cv_bridge` conversion and publishing, which the node's diagnostics report separately.

Latency per resolution (D435 val frames, resized with nearest neighbour for 640x480):

| Resolution | `downsample` | Mean / p95 core latency (ms) |
|---|---|---|
| 1280x720 | 3 | 7.3 / 8.6 |
| 640x480 | 2 (spec default) | 5.3 / 6.1 |
| 640x480 | 3 | 3.0 / 3.3 |

All numbers come from `results/*.csv` (`scripts/eval_glassbench.py`, `scripts/tune_val.py`) produced by `filter_cli`.

## Why depth alone misses glass

- Almost every wrong pixel on glass reads **too far** (99.8% to 100.0% across the three sets):
  the camera measured the surface behind.
- But glass is rarely *wrong* alone. A large share of transparent-object pixels come back **missing**:
  32.2% (D435 test), 39.7% (D435 val) and 62.5% (D415 test) of the pixels inside the transparent-object mask have no depth at all.
- The basin idea needs a ring of *returned*, nearer pixels around the glass. Where that ring is made of holes, there
  is no evidence in the depth image that the glass is there. The first version of the invalid-pixel rule let glass drain
  through the holes beside it (we believe this is why it did almost nothing), and making holes impassable and requiring
  a nearer valid boundary helps only partly:

| Invalid-pixel rule (D435 val, 173 scenes) | Wrong among returned (raw -> after) | Wrong pixels removed | Correct pixels lost |
|---|---|---|---|
| BFS wall: holes take the elevation of the valid pixels beside them (spec-default thresholds) | 51.3% -> 50.3% | 5.2% | 1.1% |
| Holes impassable, spec-default thresholds | 51.3% -> 48.9% | 13.5% | 4.7% |
| Holes impassable + nearer-boundary check, tuned on val (`realsense_d435.yaml`) | 51.3% -> 48.6% | 14.6% | 4.7% |

- Even the best depth-only variant leaves roughly 85% of wrong pixels in place, and
  flags 6.0% of returned pixels outside the glass mask on val (a false-alarm cost).
- Roadmap consequence: v0.2 lets an **RGB mask propose the region and depth verify the too-far pixels** inside it.

## Quickstart

```bash
cd ~/ros2_ws/src
git clone https://github.com/limit-case/limit_case_ros2.git
cd .. && rosdep install --from-paths src -y --ignore-src
colcon build --packages-select limit_case_ros2
source install/setup.bash
ros2 launch limit_case_ros2 limit_case_filter.launch.py sensor_profile:=realsense_d435
```

`realsense_d435` is the profile the results above were measured with. `default` keeps the spec defaults.

Supported: ROS 2 Jazzy (primary) and Humble. Develop on any OS with `docker/Dockerfile` or the devcontainer.

## Try it without hardware

Download the demo bag from the latest GitHub release, then:

```bash
ros2 launch limit_case_ros2 demo_bag.launch.py bag:=<path-to-demo-bag>
```

RViz shows the raw cloud in grey, the filtered cloud in white and the suspected glass surface in red.

No ROS install on a Mac, or no display? `docker/Dockerfile.demo` runs RViz in a container you view in the browser
(noVNC); see [`docs/recording.md`](docs/recording.md). Which scenes the bag contains, and why:
[`docs/demo_scenes.md`](docs/demo_scenes.md).

## How it works

Glass is usually surrounded by pixels that read correctly (rim, frame, label, table edge, holes). Its interior
reads **farther** than that boundary, so in a depth image it looks like a **basin**. Treat depth as terrain
(`elevation = -depth`) and fill depressions with **Priority-Flood** (Barnes, Lehman, Mulla 2014, O(n log n)).

1. Downsample (min of valid pixels: nearest surface wins). Invalid pixels are impassable walls (`realsense_d435`: plus a
   check that part of each region's boundary is valid pixels nearer than the region).
2. Priority-Flood fill. The fill level is the depth of the enclosing boundary, our estimate of the glass surface.
3. Basin depth = `depth - fill depth`. Candidates must pass an absolute and a relative threshold.
4. Connected components, drop small and border-touching regions, score each region
   (basin depth, adjacency to invalid pixels, optional specular highlights), flag at `confidence_threshold`.
5. Outputs: filtered depth, mask, and a point cloud of the fill surface back-projected with the intrinsics.

Dropping pixels is not enough: Nav2 and MoveIt discard invalid pixels, so glass would become *unknown* space,
not an obstacle. The `suspected_obstacles` cloud is what makes the robot avoid it.

## Topics

| Topic | Type | Notes |
|---|---|---|
| `depth/image` (sub) | `sensor_msgs/Image` | `16UC1` (mm) or `32FC1` (m). Launch default: `/camera/aligned_depth_to_color/image_raw` |
| `depth/camera_info` (sub) | `sensor_msgs/CameraInfo` | intrinsics for the cloud |
| `color/image` (sub) | `sensor_msgs/Image` | optional, only if `use_rgb: true` (ApproximateTime, slop 0.03 s) |
| `/limit_case/depth/filtered` | `sensor_msgs/Image` | same encoding; flagged pixels 0 (`16UC1`) / NaN (`32FC1`) |
| `/limit_case/mask` | `sensor_msgs/Image` | `mono8`, 255 = suspected see-through |
| `/limit_case/suspected_obstacles` | `sensor_msgs/PointCloud2` | estimated glass surface, depth frame |
| `/diagnostics` | `diagnostic_msgs/DiagnosticArray` | flagged %, regions, latency mean/p95, input rate |

All outputs reuse the input depth header.

## Parameters

| Name | Default | Meaning |
|---|---|---|
| `sensor_profile` | `default` | name of the loaded YAML profile (logging) |
| `downsample` | 2 | run the core at 1/N resolution |
| `min_basin_depth_m` | 0.02 | pixel must read at least this much farther than the fill level |
| `min_basin_depth_rel` | 0.03 | and at least this fraction of its depth |
| `min_region_area_px` | 150 | at full resolution |
| `max_range_m` | 4.0 | ignore pixels beyond this |
| `treat_invalid_as_wall` | false | false: holes are impassable, a patch reachable only through holes is ignored. true: BFS wall option (holes take the elevation of the valid cells they border) |
| `boundary_verify` | false | variant (c): flag a region only if part of its boundary is valid pixels nearer than it; cloud depth = median of those pixels |
| `min_nearer_boundary_frac` / `flag_hole_only` | 0.1 / false | variant (c) tuning: required share of nearer valid boundary; flag hole-only regions in the mask without a cloud |
| `use_rgb` | false | enable the specular highlight vote (startup only) |
| `specular_v_thresh` / `specular_s_thresh` | 240 / 40 | HSV highlight thresholds |
| `confidence_threshold` | 0.5 | lower = more aggressive |
| `publish_cloud` / `cloud_stride` | true / 2 | suspected-obstacle cloud |

Offline evaluation without ROS: `filter_cli` (PNG/EXR folders in, masks out) and `scripts/eval_glassbench.py`.

## Nav2

See [`nav2/costmap_snippet.yaml`](nav2/costmap_snippet.yaml). Two observation sources:
the filtered depth cloud (`marking: true, clearing: true`) and `/limit_case/suspected_obstacles`
(`marking: true, clearing: false`). **Clearing must be off for the glass cloud**: on the next frame the glass reads
as far-away free space, so a clearing source would raytrace through the glass and erase the cells just marked.

## Limitations

- A pane that fills the whole view, or a region touching the image border, is not enclosed, so it is not flagged.
- Glass seen against a background that is *closer* than its rim (rare) is missed.
- Opaque concave objects (a bowl seen from above) can form real basins. The relative threshold and the score
  reduce this; v0.3 adds a learned RGB detector to fix it properly.
- Glass whose surroundings are only missing pixels, sitting against a background at the same depth as those
  surroundings, produces no dip at all, so there is no basin to fill. Depth alone cannot solve this; the learned
  RGB detector planned for v0.3 is meant to cover it.
- **False alarms outside the glass.** On both test sets (D435: 23 scenes, D415: 90 scenes) 8.7% of the returned
  pixels *outside* the glass mask are flagged (`results/eval_cg_test_*.csv`, column "Outside-mask flagged"; 6.0% on
  D435 val). The filter cannot tell a depth basin on glass from other occluded or concave areas.
- **Flagged pixels become phantom obstacles.** The `suspected_obstacles` cloud is built from every flagged region, so
  false alarms are published as obstacles too, not just dropped from the depth image. In the demo bag many of the red points sit on a dark
  case and a far wall, not on the glass (see `docs/demo_scenes.md`). Use this node where a spurious obstacle is
  cheaper than a collision with glass.
- Not safety certified.

## Hardware Wall of Fame

Help us map every camera. Open an issue with your sensor model and a short bag if it misses a failure.
Seeded with: RealSense D415, D435, L515.

## Roadmap

- v0.1 (this release): honest depth-only baseline.
- v0.2: an RGB mask proposes the glass region, depth verifies the too-far pixels inside it.
- v0.3: learned RGB detector (covers glass surrounded only by missing pixels, which depth cannot).
- Later: Gazebo glass simulation plugin, remote rosbag reports.

## Citation and license

If you use this, please cite GlassBench: <!-- TODO(owner): paste BibTeX -->

Apache-2.0, see [LICENSE](LICENSE). ClearGrasp data is Apache-2.0. TransCG (CC BY-NC-SA) may be evaluated
locally but its images and derived images are never committed here.
