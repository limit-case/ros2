# Demo scenes

`demo_bag` holds three ClearGrasp D435 real-test scenes, 20 frames each at 5 Hz (4 s per scene, 12 s per loop),
640x360, scene ids `000000014`, `000000018`, `000000019`. This page records how they were chosen.

## How they were chosen

All 23 D435 real-test scenes were run through `filter_cli` with `config/realsense_d435.yaml` at the bag's
640x360 resolution (`scripts/eval_glassbench.py --resize 640x360`, per-scene rows in
`results/eval_demo_scene_selection.csv`). "Wrong" pixels are the silent failures inside the glass mask
(raw depth returned but off by more than 5% of the ground truth; here all of them read too far, i.e. see-through).
"Caught" means the filter flagged them.

Rule, written before looking at the picture: rank scenes by the number of wrong glass pixels caught and take the top
three, **after excluding scene `000000022`**. Scene 22 ranks second, but only because it flags the entire inside of a
cardboard box (100% of its correct glass pixels and 29.8% of the returned pixels outside the glass). On screen that
is a red box, not a caught glass object, so it would mislead. That exclusion is a judgement call; swap it in with
`--scenes` if you prefer. Note also that the demo bag uses test scenes: nothing here was tuned on them.

| Scene | Wrong px in glass mask | Wrong px flagged (caught) | Correct glass px lost | Outside-mask returned px flagged | Picked |
|---|---|---|---|---|---|
| 000000014 | 1635 | 1253 (76.6%) | 191 of 1077 (17.7%) | 19506 of 185358 (10.5%) | **yes** |
| 000000022 | 874 | 874 (100.0%) | 1909 of 1909 (100.0%) | 61949 of 207709 (29.8%) |  |
| 000000018 | 2060 | 515 (25.0%) | 693 of 1967 (35.2%) | 19128 of 182364 (10.5%) | **yes** |
| 000000019 | 433 | 212 (49.0%) | 429 of 1835 (23.4%) | 21022 of 192538 (10.9%) | **yes** |
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
| 000000015 | 1232 | 0 (0.0%) | 0 of 574 (0.0%) | 24062 of 189505 (12.7%) |  |
| 000000017 | 778 | 0 (0.0%) | 0 of 568 (0.0%) | 23045 of 193403 (11.9%) |  |
| 000000020 | 1227 | 0 (0.0%) | 0 of 1264 (0.0%) | 19686 of 190958 (10.3%) |  |
| 000000021 | 1265 | 0 (0.0%) | 0 of 403 (0.0%) | 21558 of 193312 (11.2%) |  |

(Sorted by wrong pixels caught. Percentages are of that scene's pixels in the same category.)

## What the demo does and does not show

- In all three scenes the filter does catch see-through pixels on the glass (25% to 77% of the wrong ones).
- It also flags correct glass pixels (18% to 35%) and, more visibly, a lot of pixels **outside** the glass: roughly 10%
  of the returned pixels elsewhere in the frame. In the RViz view the biggest red patches are on the black case under
  the glass and on the far wall band, not on the glass itself. Those flagged pixels become phantom obstacles
  in the red cloud, exactly the limitation stated in the README. The clip should not be captioned as if every red
  point were glass.
- Scenes `000000003` (80 of 84 wrong caught, but 31% of correct glass lost) and `000000016` (150 caught, nothing
  correct lost, but 12.8% outside flagged) were the next candidates.
- 17 of the 23 scenes catch no wrong glass pixel at all (four of them, 10 to 13, have none to catch). Three scenes out of 23 is a favourable slice of the data, not a typical one.

Regenerate the bag: see the docstring of `scripts/clearGrasp_to_bag.py`; the command used was

```bash
scripts/clearGrasp_to_bag.py --data ~/glassbench/datasets/cleargrasp-dataset-test-val/real-test/d435 \
    --intrinsics ~/glassbench/datasets/cleargrasp-dataset-test-val/real-test/d435/camera_intrinsics.yaml \
    --out demo_bag --scenes 000000014,000000018,000000019 --frames-per-scene 20
```
