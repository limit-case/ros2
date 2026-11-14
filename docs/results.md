# Results

Every number here and in the README comes from `results/*.csv`, produced by `filter_cli` through
`scripts/eval_glassbench.py`. Data: [ClearGrasp](https://github.com/Shreeyak/cleargrasp) real images (Sajjan et al.,
ICRA 2020, Apache-2.0), measured with the [GlassBench](https://github.com/limit-case/glassbench) rules. The one
exception is the held-out TransCG run ([below](#held-out-transcg-d435-test)), whose pooled numbers are in
`results/transcg_d435_test_summary.csv`.

v0.1 is an **honest depth-only baseline**. On ClearGrasp D435 test (1280x720) the filter removes
**14.6%** of the confidently wrong glass pixels, loses **7.9%** of the correct ones, and flags
**8.7%** of the pixels outside the glass, at **7.4 ms** per frame (core only, `downsample: 3`).
Most wrong pixels survive.

## Headline table

| Set (1280x720, tolerance 5%, transparent-mask pixels) | Wrong among returned (raw -> after) | Wrong pixels removed | Correct pixels lost | Outside-mask flagged |
|---|---|---|---|---|
| D435 test (23 scenes), run once | 23.9% -> 22.6% | 14.6% | 7.9% | 8.7% |
| D435 val (173 scenes), the tuning set | 51.3% -> 48.6% | 14.6% | 4.7% | 6.0% |

Core latency: 7.4 ms mean, 7.6 ms p95 per 1280x720 frame (D435 test, `downsample: 3`).

Second camera, RealSense D415 test (90 scenes, run once, same `realsense_d435.yaml` profile, native 848x480):
36.9% -> 35.2% wrong among returned, 11.4% wrong removed, 4.5% correct lost, 8.7% outside-mask flagged.

## Held out: TransCG D435 test

A different dataset, never used for tuning, run once on 2026-11-14 under the frozen protocol
([`v0.2_protocol.md`](v0.2_protocol.md)): all 52 scenes of the official test split, 11766 D435 views, same
`realsense_d435.yaml` profile, tolerance 5%.

| Set | Wrong among returned (raw -> after) | Wrong pixels removed | Correct pixels lost | Outside-mask flagged |
|---|---|---|---|---|
| TransCG D435 test (52 scenes, held out, run once), v0.1 | 13.9% -> 10.8% | 28.6% | 4.5% | 2.4% |

> Evaluated on [TransCG](https://graspnet.net/transcg): Fang, H., Fang, H.-S., Xu, S., Lu, C. "TransCG: A Large-Scale Real-World Dataset for Transparent Object Depth Completion and a Grasping Baseline." IEEE RA-L 7(3):7383-7390, 2022. doi:10.1109/LRA.2022.3183256
> Licensed CC BY-NC-SA 4.0 (Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International),
> non-commercial. No TransCG data is redistributed here.

Source: `results/transcg_d435_test_summary.csv` (pooled values only, rows `v01`), written by
`scripts/eval_transcg.py`. 95% bootstrap intervals over scenes: wrong removed 23.6% to 33.9%, correct lost 3.1% to
6.0%, outside-mask flagged 1.9% to 2.9%.

TransCG has fewer missing glass pixels (27.1%, against 32.2% to 62.5% in ClearGrasp), which is consistent with the
explanation [below](#why-depth-alone-misses-glass) that holes around the glass stop the depth-only filter. It is
not proof: the two datasets differ in objects, backgrounds and ground truth as well.

## Sources

Where every number comes from:

| Row | CSV | Command |
|---|---|---|
| D435 test | `results/eval_cg_test_d435_summary.csv` | `scripts/eval_glassbench.py --split real-test/d435 --name cg_test_d435 --params config/realsense_d435.yaml` |
| D435 val | `results/eval_cg_val_d435_summary.csv` | `scripts/eval_glassbench.py --split real-val/d435 --name cg_val_d435 --params config/realsense_d435.yaml` |
| D415 test | `results/eval_cg_test_d415_summary.csv` | `scripts/eval_glassbench.py --split real-test/d415 --name cg_test_d415 --params config/realsense_d435.yaml` |

Each command also writes the per-image rows (`results/eval_<name>.csv`). Columns used: `wrong_among_returned_raw`,
`wrong_among_returned_after`, `wrong_removed`, `correct_lost`, `outside_flagged`.

## Definitions and notes

- Tuned **only** on ClearGrasp D435 val (`scripts/tune_val.py`, every configuration in `results/tune_val.csv`). The
  two test sets were each run once. The tuning budget was "correct pixels lost <= 5% on val"; D435 test exceeds it
  (7.9%), so the val budget does not transfer exactly.
- "Wrong among returned" = wrong / (correct + wrong): the chance that a depth the sensor chose to report is wrong.
- Definitions follow GlassBench `docs/measurement.md`: ground-truth-valid pixels only; missing = raw 0 and never
  counted as wrong; wrong = returned and more than 5% off ground truth.
- Latency (`latency_ms_mean`, `latency_ms_p95` of the D435 test CSV) is the core filter only (`filter_cli`), on an arm64 Docker VM with 2 CPUs, Release build. It excludes image
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

## v0.2 experiment: RGB proposes, depth verifies

Wrong removed / correct lost / outside-mask flagged, in %. Each test set was run once per setting
(`scripts/eval_rgb_proposal.py`; the selection rule is in `results/rgb_proposal_selected.json`).

| Setting | D435 val | D435 test | D415 test | CSVs |
|---|---|---|---|---|
| v0.1 depth-only | 14.6 / 4.7 / 6.0 | 14.6 / 7.9 / 8.7 | 11.4 / 4.5 / 8.7 | `results/eval_cg_{val_d435,test_d435,test_d415}_summary.csv` |
| RGB, selected on val (5 px ring, 3 cm) | 29.3 / 4.7 / 0.2 | 8.2 / 1.0 / 0.2 | 10.3 / 4.1 / 0.2 | `results/eval_rgb_proposal_*_selected_summary.csv` |
| RGB, untuned (v0.1 thresholds, 15 px ring) | 44.5 / 8.6 / 0.3 | 47.4 / 7.2 / 0.4 | 20.4 / 5.4 / 0.4 | `results/eval_rgb_proposal_*_v01thresh_summary.csv` |

The val-selected setting overfit: it removes fewer wrong pixels than v0.1 on both test sets. The untuned setting
transferred, but preferring it is a test-informed choice, not a clean held-out result. So the untuned setting was
frozen and run once on fresh data ([`v0.2_protocol.md`](v0.2_protocol.md)).

### Held-out result: the pre-registered criterion FAILED

TransCG D435 test, 52 scenes, run once (`results/transcg_d435_test_summary.csv`; intervals are the 95% bootstrap
over scenes):

| Metric | RGB proposal | v0.1 depth-only |
|---|---|---|
| Wrong removed | 35.7% (31.9 to 40.0) | 28.6% (23.6 to 33.9) |
| Correct lost | 11.0% (8.2 to 13.6) | 4.5% (3.1 to 6.0) |
| Outside-mask flagged | 2.2% (1.7 to 2.6) | 2.4% (1.9 to 2.9) |
| Wrong among returned (raw -> after) | 13.9% -> 10.4% | 13.9% -> 10.8% |

- Ratio of wrong removed: 1.25 (1.06 to 1.48). The bar was 1.5, for the point and for the lower bound: failed.
- Correct lost had to stay within 2 points of v0.1: failed.
- Outside-mask flagged had to be lower than v0.1: held.

**Verdict: FAIL.** The RGB mode stays experimental and off by default.

The proposal mask overlaps the true mask with an IoU of 45.9%, and 73.2% of the wrong pixels lie inside it. The
mask network was trained on synthetic images only and never saw TransCG, so mask quality is the likely bottleneck;
no experiment here separates the mask from the depth check. Citation and licence of TransCG:
[above](#held-out-transcg-d435-test).
