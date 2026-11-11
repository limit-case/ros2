#!/usr/bin/env python3
r"""Val-only grid for eval_rgb_proposal.py: ring width x thresholds, one row per configuration.

  tune_rgb_proposal.py --pred-dir out/rgb_masks/real-val/d435 \
      --out results/rgb_proposal_tune_val.csv
Always runs on ClearGrasp D435 val (real-val/d435); it has no option to touch a test split.
"""
import argparse
import csv
import itertools
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_glassbench import bucket_counts, load_glassbench, summarize  # noqa: E402
from eval_rgb_proposal import ring_flag  # noqa: E402

SPLIT = 'real-val/d435'
RINGS = (5, 15, 30, 60)
MIN_M = (0.005, 0.01, 0.02, 0.03)
MIN_REL = (0.0, 0.015, 0.03, 0.05)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glassbench', default=os.environ.get('GLASSBENCH', '~/glassbench'))
    ap.add_argument('--pred-dir', default='out/rgb_masks/' + SPLIT)
    ap.add_argument('--out', default='results/rgb_proposal_tune_val.csv')
    a = ap.parse_args()
    import cv2
    loader = load_glassbench(a.glassbench)
    data = []
    for _, split, sid in loader.list_cleargrasp([SPLIT]):
        s = loader.load_cleargrasp(split, sid)
        pred = cv2.imread(str(Path(a.pred_dir) / f'{sid}.png'), cv2.IMREAD_UNCHANGED)
        if pred is None:
            sys.exit(f'missing mask prediction for {sid} in {a.pred_dir}')
        data.append((s['id'], s['depth_raw'], s['depth_gt'], s['mask'], pred > 0))
    out = []
    for ring, m, rel in itertools.product(RINGS, MIN_M, MIN_REL):
        rows = []
        for sid, raw, gt, mask, pred in data:
            flag = ring_flag(raw, pred, ring, m, rel)
            for region, sel in (('mask', mask), ('nonmask', ~mask)):
                rows.append(dict(id=sid, region=region,
                                 **bucket_counts(raw, gt, sel, flag, 'rel5%')))
        s = summarize(rows, [], 'rgb_proposal_tune', SPLIT, 'rel5%')
        out.append(dict(split=SPLIT, ring_px=ring, min_basin_depth_m=m, min_basin_depth_rel=rel,
                        **{k: s[k] for k in ('wrong_among_returned_raw',
                                             'wrong_among_returned_after', 'wrong_removed',
                                             'correct_lost', 'outside_flagged')}))
        print(ring, m, rel, f"{s['wrong_removed']:.1f} {s['correct_lost']:.1f} "
              f"{s['outside_flagged']:.2f}", flush=True)
    with open(a.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)


if __name__ == '__main__':
    main()
