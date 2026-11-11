# limit_case_ros2

[![ci](https://github.com/limit-case/ros2/actions/workflows/ci.yml/badge.svg)](https://github.com/limit-case/ros2/actions/workflows/ci.yml)

A depth camera missed a clear surface, returned the wall behind it, and the arm it was guiding broke my finger.

**Depth alone can't see glass. We measured why.**

<!-- TODO(owner): ground-truth error GIF (raw cloud, red = wrong, seen from the side). Record it with
     docs/recording.md, save as docs/gt_error.gif, then uncomment:
     ![Raw depth cloud coloured by ground truth: the red points sit behind the glass](docs/gt_error.gif) -->

`limit_case_ros2` is a ROS 2 node that sits between a depth camera driver and your navigation or manipulation
stack. It looks for **silent depth failures on transparent objects**: pixels where the camera returns a confident
value that is wrong because it measured the surface *behind* the glass.
[GlassBench](https://github.com/limit-case/glassbench) found that 99.8%+ of wrong pixels on transparent objects read
**too far**; v0.1 uses that one fact, with depth only, and reports honestly how far it gets.

> **Not a safety certification.** This is research-grade software. Do not rely on it as the only
> protection against collisions. It has no safety certification of any kind.

## Results

v0.1 is an **honest depth-only baseline**. On ClearGrasp D435 test (1280x720) the filter removes
**14.6%** of the confidently wrong glass pixels, loses **7.9%** of the correct ones, and flags
**8.7%** of the pixels outside the glass, at **7.4 ms** per frame (core only, `downsample: 3`).
Most wrong pixels survive. See "Why depth alone misses glass" below.

| Set (1280x720, tolerance 5%, transparent-mask pixels) | Wrong among returned (raw -> after) | Wrong pixels removed | Correct pixels lost | Outside-mask flagged | Core latency mean / p95 (ms) |
|---|---|---|---|---|---|
| D435 test (23 scenes), run once | 23.9% -> 22.6% | 14.6% | 7.9% | 8.7% | 7.4 / 7.6 |
| D435 val (173 scenes), the tuning set | 51.3% -> 48.6% | 14.6% | 4.7% | 6.0% | 7.3 / 8.6 |

Second camera, RealSense D415 test (90 scenes, run once, same `realsense_d435.yaml` profile, native 848x480):
36.9% -> 35.2% wrong among returned, 11.4% wrong removed, 4.5% correct lost, 8.7% outside-mask flagged.

Where every number comes from (all produced by `filter_cli` through `scripts/eval_glassbench.py`):

| Row | CSV | Command |
|---|---|---|
| D435 test | `results/eval_cg_test_d435_summary.csv` | `scripts/eval_glassbench.py --split real-test/d435 --name cg_test_d435 --params config/realsense_d435.yaml` |
| D435 val | `results/eval_cg_val_d435_summary.csv` | `scripts/eval_glassbench.py --split real-val/d435 --name cg_val_d435 --params config/realsense_d435.yaml` |
| D415 test | `results/eval_cg_test_d415_summary.csv` | `scripts/eval_glassbench.py --split real-test/d415 --name cg_test_d415 --params config/realsense_d435.yaml` |

Each command also writes the per-image rows (`results/eval_<name>.csv`). Columns used: `wrong_among_returned_raw`,
`wrong_among_returned_after`, `wrong_removed`, `correct_lost`, `outside_flagged`, `latency_ms_mean`, `latency_ms_p95`.

Notes:
- Tuned **only** on ClearGrasp D435 val (`scripts/tune_val.py`, every configuration in `results/tune_val.csv`). The
  two test sets were each run once. The tuning budget was "correct pixels lost <= 5% on val"; D435 test exceeds it
  (7.9%), so the val budget does not transfer exactly.
- "Wrong among returned" = wrong / (correct + wrong): the chance that a depth the sensor chose to report is wrong.
- Definitions follow GlassBench `docs/measurement.md`: ground-truth-valid pixels only; missing = raw 0 and never
  counted as wrong; wrong = returned and more than 5% off ground truth.
- Latency is the core filter only (`filter_cli`), on an arm64 Docker VM with 2 CPUs, Release build. It excludes image
  decoding, `cv_bridge` conversion and publishing, which the node's diagnostics report separately.

## Why depth alone misses glass

- Almost every wrong pixel on glass reads **too far** (99.8% to 100.0% across the three sets, column
  `wrong_too_far_pct`): the camera measured the surface behind.
- But glass is rarely *wrong* alone. A large share of transparent-object pixels come back **missing**:
  32.2% (D435 test), 39.7% (D435 val) and 62.5% (D415 test) of the pixels inside the transparent-object mask
  have no depth at all (column `missing_pct`).
- The basin idea needs a ring of *returned*, nearer pixels around the glass. Where that ring is made of holes, there
  is no evidence in the depth image that the glass is there. Letting holes take the depth of their neighbours lets
  the glass drain through the holes beside it; making holes impassable and requiring a nearer valid boundary helps
  only partly:

| Invalid-pixel rule (D435 val, 173 scenes, 1280x720) | Wrong among returned (raw -> after) | Wrong pixels removed | Correct pixels lost | CSV |
|---|---|---|---|---|
| BFS wall: holes take the elevation of the valid pixels beside them (default thresholds) | 51.3% -> 50.3% | 5.2% | 1.1% | `results/eval_cg_val_d435_ablation_bfs_summary.csv` |
| Holes impassable, default thresholds | 51.3% -> 48.9% | 13.5% | 4.7% | `results/eval_cg_val_d435_ablation_skip_defaults_summary.csv` |
| Holes impassable + nearer-boundary check, tuned on val (`realsense_d435.yaml`, shipped) | 51.3% -> 48.6% | 14.6% | 4.7% | `results/eval_cg_val_d435_summary.csv` |

  The two ablation rows: `scripts/eval_glassbench.py --split real-val/d435 --params config/default.yaml --set downsample=3`
  with `--name cg_val_d435_ablation_skip_defaults`, and with `--set treat_invalid_as_wall=true --name cg_val_d435_ablation_bfs`.
- Even the best depth-only variant leaves most wrong pixels in place and flags 6.0% of returned pixels outside the
  glass mask on val, 8.7% on test.
- Roadmap consequence: v0.2 lets an **RGB mask propose the region and depth verify the too-far pixels** inside it.

## Quick start

Install (ROS 2 Jazzy or Humble):

```bash
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src
git clone https://github.com/limit-case/ros2.git limit_case_ros2
cd .. && rosdep install --from-paths src -y --ignore-src
colcon build --packages-select limit_case_ros2
source install/setup.bash
```

Run the demo bag (no hardware; download `demo_bag` from the latest GitHub release):

```bash
ros2 launch limit_case_ros2 demo_bag.launch.py bag:=<path-to-demo_bag>
```

RViz shows the raw cloud in grey, the filtered cloud in white and the suspected glass surface in red.

See the failure itself, the ground-truth error view:

```bash
ros2 launch limit_case_ros2 demo_bag.launch.py bag:=<path-to-demo_bag> gt:=true
```

This colours the **raw** cloud with ClearGrasp ground truth: red = glass pixels that are wrong (more than 5% off),
white = glass pixels that are correct, dim grey = not glass, missing pixels not drawn. Orbit to the side: the red
points sit behind the glass. It needs `gt_sidecar.npz` in the bag folder (shipped with the release bag, or made with
`scripts/gt_error_cloud.py prepare`; see [`docs/demo_scenes.md`](docs/demo_scenes.md)).

On a live camera:

```bash
ros2 launch limit_case_ros2 limit_case_filter.launch.py sensor_profile:=realsense_d435
```

`realsense_d435` is the profile the results above were measured with. `default` keeps the untuned defaults.

No ROS install on a Mac, or no display? `docker/Dockerfile.demo` runs RViz in a container you view in the browser
(noVNC); see [`docs/recording.md`](docs/recording.md). Develop on any OS with `docker/Dockerfile` or the devcontainer.

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

- **Depth-only enclosure fails on most glass.** The filter needs glass to be enclosed by returned, nearer pixels.
  In ClearGrasp 32.2% to 62.5% of glass pixels are missing, so glass is mostly bordered by holes and no basin
  forms. That is why only 14.6% (D435 test) and 11.4% (D415 test) of the wrong pixels are removed.
- **False alarms become phantom obstacles.** On both test sets 8.7% of the returned pixels *outside* the glass mask
  are flagged (column `outside_flagged`; 6.0% on D435 val). The filter cannot tell a depth basin on glass from other
  occluded or concave areas, and the `suspected_obstacles` cloud is built from every flagged region, so these are
  published as obstacles, not just dropped from the depth image. In the demo bag many of the red points sit on a dark
  case and a far wall, not on the glass (see `docs/demo_scenes.md`). Use this node where a spurious obstacle is
  cheaper than a collision with glass.
- **Tuned on D435 val only.** One camera, one dataset, small objects on a table. The val budget (correct lost
  <= 5%) did not hold on D435 test (7.9%). D415 and L515 profiles are untuned; nothing here was measured on doors,
  windows or walls.
- A pane that fills the whole view, or a region touching the image border, is not enclosed, so it is not flagged.
- Glass seen against a background that is *closer* than its rim (rare) is missed.
- Opaque concave objects (a bowl seen from above) can form real basins.
- Not safety certified.

## Hardware Wall of Fame

Help us map every camera. Open an issue with your sensor model and a short bag if it misses a failure.
Seeded with: RealSense D415, D435, L515.

## Roadmap

- v0.1 (this release): honest depth-only baseline.
- v0.2: an RGB mask proposes the glass region, depth verifies the too-far pixels inside it.
- v0.3: learned RGB detector (covers glass surrounded only by missing pixels, which depth cannot).
- Later: Gazebo glass simulation plugin, remote rosbag reports.

## Citation and licences

If you use this, please cite GlassBench:

```bibtex
@misc{glassbench2026,
  title        = {GlassBench: Silent Depth Failures on Transparent Objects},
  author       = {{Limit Case}},
  year         = {2026},
  version      = {0.1.0},
  howpublished = {\url{https://github.com/limit-case/glassbench}}
}
```

- Code: Apache-2.0, see [LICENSE](LICENSE).
- [ClearGrasp](https://github.com/Shreeyak/cleargrasp) data (all numbers above, the demo bag and its ground-truth
  sidecar): Apache-2.0.
- [TransCG](https://graspnet.net/transcg): CC BY-NC-SA 4.0, **non-commercial**. It may be evaluated locally, but its
  images and anything derived from them are never committed or shipped here.
