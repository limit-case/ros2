# Demo scenes

`demo_bag` holds three ClearGrasp D435 real-test scenes, 20 frames each at 5 Hz (4 s per scene, 12 s per loop),
640x360, in this order: `000000018`, `000000014`, `000000015`. The folder is 67 MiB: `demo_bag.mcap`,
`metadata.yaml`, `gt_sidecar.npz` (ground truth and mask for the `gt:=true` view) and `NOTICE` (ClearGrasp
attribution, Apache-2.0). This page records how the scenes were chosen. Nothing in the package was tuned on them.

## How they were chosen: by how clearly the failure shows

The headline visual is the ground-truth error view (`gt:=true`, `scripts/gt_error_cloud.py`): the raw cloud coloured
by GlassBench bucket, red = wrong (in the glass mask, more than 5% off ground truth), white = correct, dim grey = not
glass, missing = not shown. So the scenes are ranked by how clearly the through-glass error shows, not by filter
performance.

Rule, written before rendering any picture: at the bag resolution (640x360),
**score = number of wrong glass pixels x median depth gap (raw minus ground truth, metres) of those pixels**.
Many red points sitting far behind the glass score high. All 23 D435 test scenes, no filter involved
(`scripts/gt_error_cloud.py rank`, every scene in `results/gt_error_scene_ranking.csv`); top 12:

| Rank | Scene | Wrong px (red) | Median gap behind true surface | 90th pct gap | Score | In demo bag |
|---|---|---|---|---|---|---|
| 1 | 000000018 | 2042 | 3.7 cm | 5.1 cm | 76.2 | **yes** |
| 2 | 000000014 | 1608 | 4.4 cm | 8.0 cm | 70.6 | **yes** |
| 3 | 000000015 | 1216 | 4.2 cm | 6.7 cm | 50.9 | **yes** |
| 4 | 000000021 | 1262 | 3.8 cm | 4.1 cm | 48.3 |  |
| 5 | 000000020 | 1212 | 3.7 cm | 4.1 cm | 44.9 |  |
| 6 | 000000022 | 862 | 3.9 cm | 6.9 cm | 33.6 |  |
| 7 | 000000017 | 762 | 4.4 cm | 5.1 cm | 33.5 |  |
| 8 | 000000001 | 600 | 4.2 cm | 5.4 cm | 25.1 |  |
| 9 | 000000004 | 673 | 3.7 cm | 4.5 cm | 24.7 |  |
| 10 | 000000006 | 526 | 3.4 cm | 4.0 cm | 18.1 |  |
| 11 | 000000019 | 412 | 4.1 cm | 5.7 cm | 17.1 |  |
| 12 | 000000016 | 384 | 4.0 cm | 6.6 cm | 15.4 |  |

The bag holds ranks 1, 2 and 3: **18, 14, 15**.

- 18 has the most red points (four objects). 14 has the largest single red patch and the largest gap. 15 has one large
  red patch in front and a second object whose returned pixels are almost all wrong.
- An earlier bag (v0.1 development) held 14, 18 and 19, picked by filter performance. Scene 19 is rank 11 here, with
  about a third of the red of scene 15, so it was replaced.
- The gap is small in absolute terms: the median wrong pixel reads about 4 cm behind the true surface
  (3.7 to 4.4 cm in the bag scenes), because the objects stand on a table and the camera sees the table through them.
  From the camera's viewpoint that is invisible; from the side the red points lie on the table plane while the
  true surface (green, `/demo/gt_surface_points`) stands above it.
- Mask pixels that returned a depth but have no ground truth (434 to 896 px per bag scene) cannot be judged and are
  not drawn.

Static previews without RViz (orbit view, side view, side view with the true surface) are written to
`out/gt_preview/<scene>.png` by the `preview` command below.

## What the filter does on these scenes

All 23 D435 real-test scenes were run through `filter_cli` with `config/realsense_d435.yaml` at the bag's
640x360 resolution (`scripts/eval_glassbench.py --resize 640x360`, per-scene rows in
`results/eval_demo_scene_selection.csv`). "Wrong" pixels are the silent failures inside the glass mask; "caught"
means the filter flagged them.

| Scene | Wrong px in glass mask | Wrong px flagged (caught) | Correct glass px lost | Outside-mask returned px flagged | In demo bag |
|---|---|---|---|---|---|
| 000000014 | 1635 | 1253 (76.6%) | 191 of 1077 (17.7%) | 19506 of 185358 (10.5%) | **yes** |
| 000000022 | 874 | 874 (100.0%) | 1909 of 1909 (100.0%) | 61949 of 207709 (29.8%) |  |
| 000000018 | 2060 | 515 (25.0%) | 693 of 1967 (35.2%) | 19128 of 182364 (10.5%) | **yes** |
| 000000019 | 433 | 212 (49.0%) | 429 of 1835 (23.4%) | 21022 of 192538 (10.9%) |  |
| 000000016 | 392 | 150 (38.3%) | 0 of 540 (0.0%) | 24298 of 190148 (12.8%) |  |
| 000000003 | 84 | 80 (95.2%) | 445 of 1415 (31.4%) | 18556 of 175288 (10.6%) |  |
| 000000000 | 365 | 0 (0.0%) | 0 of 3551 (0.0%) | 4388 of 169999 (2.6%) |  |
| 000000001 | 604 | 0 (0.0%) | 0 of 3117 (0.0%) | 1218 of 172217 (0.7%) |  |
| 000000002 | 393 | 0 (0.0%) | 0 of 2237 (0.0%) | 10568 of 174400 (6.1%) |  |
| 000000004 | 707 | 0 (0.0%) | 0 of 1063 (0.0%) | 1415 of 177406 (0.8%) |  |
| 000000005 | 308 | 0 (0.0%) | 0 of 1027 (0.0%) | 1211 of 178913 (0.7%) |  |
| 000000006 | 552 | 0 (0.0%) | 0 of 3438 (0.0%) | 553 of 173700 (0.3%) |  |
| 000000007 | 320 | 0 (0.0%) | 0 of 4275 (0.0%) | 1413 of 168282 (0.8%) |  |
| 000000008 | 340 | 0 (0.0%) | 0 of 2290 (0.0%) | 1715 of 177855 (1.0%) |  |
| 000000009 | 295 | 0 (0.0%) | 0 of 3083 (0.0%) | 741 of 175249 (0.4%) |  |
| 000000010 | 0 | 0 (n/a) | 0 of 2142 (0.0%) | 2447 of 179457 (1.4%) |  |
| 000000011 | 0 | 0 (n/a) | 0 of 2426 (0.0%) | 2035 of 178184 (1.1%) |  |
| 000000012 | 0 | 0 (n/a) | 0 of 1883 (0.0%) | 1312 of 178835 (0.7%) |  |
| 000000013 | 0 | 0 (n/a) | 0 of 1957 (0.0%) | 1078 of 179612 (0.6%) |  |
| 000000015 | 1232 | 0 (0.0%) | 0 of 574 (0.0%) | 24062 of 189505 (12.7%) | **yes** |
| 000000017 | 778 | 0 (0.0%) | 0 of 568 (0.0%) | 23045 of 193403 (11.9%) |  |
| 000000020 | 1227 | 0 (0.0%) | 0 of 1264 (0.0%) | 19686 of 190958 (10.3%) |  |
| 000000021 | 1265 | 0 (0.0%) | 0 of 403 (0.0%) | 21558 of 193312 (11.2%) |  |

(Sorted by wrong pixels caught. Percentages are of that scene's pixels in the same category.)

- The filter demo (without `gt:=true`) on this bag is an honest mix: it catches 76.6% of the wrong glass pixels in
  scene 14, 25.0% in scene 18, and **none** in scene 15.
- It also flags correct glass pixels (17.7% and 35.2% in scenes 14 and 18) and, more visibly, pixels **outside** the
  glass: 10.5% to 12.7% of the returned pixels elsewhere in the frame. In the RViz view the biggest red patches are
  on the black case under the glass and on the far wall band, not on the glass itself. Those flagged pixels become
  phantom obstacles in the red cloud, exactly the limitation stated in the README. A filter clip should not be
  captioned as if every red point were glass.
- 17 of the 23 scenes catch no wrong glass pixel at all (four of them, 10 to 13, have none to catch).
- Scene `000000022` catches 100% only because it flags the entire inside of a cardboard box (100% of its correct
  glass pixels, 29.8% of the returned pixels outside the glass).

## Regenerate the bag, the sidecar and the previews

Needs `rosbags` (0.11.9 was used, Python 3.12; the 0.9 series that installs on Python 3.9 is too old) and an OpenCV
build that reads EXR (`opencv-python-headless<4.12` was used).

```bash
D=~/glassbench/datasets/cleargrasp-dataset-test-val/real-test/d435
scripts/clearGrasp_to_bag.py --data $D --intrinsics $D/camera_intrinsics.yaml \
    --out demo_bag --scenes 000000018,000000014,000000015 --frames-per-scene 20
scripts/gt_error_cloud.py prepare --data $D --scenes 000000018,000000014,000000015 --out demo_bag/gt_sidecar.npz
cp NOTICE demo_bag/NOTICE
scripts/gt_error_cloud.py preview --sidecar demo_bag/gt_sidecar.npz --out out/gt_preview
ros2 launch limit_case_ros2 demo_bag.launch.py bag:=demo_bag gt:=true
```
