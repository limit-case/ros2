#!/usr/bin/env python3
"""v0.2 experiment: an RGB mask proposes the glass region, depth verifies the too-far pixels.

For every connected region of the predicted transparent mask:
  ring      = valid (raw > 0) pixels within --ring-px of the region, outside every predicted region
  reference = median raw depth of the ring (skipped if the ring has < --min-ring-px pixels)
  flag      = region pixels with raw > 0 that read farther than the reference by more than
              min_basin_depth_m AND more than min_basin_depth_rel of their own depth
The thresholds default to the v0.1 values in config/realsense_d435.yaml. No Priority-Flood: the
RGB mask replaces the depth-only enclosure, so holes around the glass cannot drain the region.

Scored with the same metric code as the v0.1 filter (bucket_counts / summarize from
eval_glassbench.py). Writes results/eval_<name>.csv, _summary.csv and .md.

Mask predictions: one 8-bit PNG per image, <pred-dir>/<scene id>.png, same size as the depth
image, > 0 = predicted transparent. --make-preds writes them with the ClearGrasp
mask-segmentation network through GlassBench (tools/flagging/flag_eval.py; needs torch):

  eval_rgb_proposal.py --split real-val/d435 --make-preds --pred-dir out/rgb_masks/real-val/d435
  eval_rgb_proposal.py --split real-val/d435 --pred-dir out/rgb_masks/real-val/d435

--proposal gt uses the ground-truth mask instead: the "GT mask reference". It is a reference
point, not an upper bound: the predicted mask over-covers the objects (column
proposal_area_vs_gt), so its ring sits farther out on cleaner background, and on D435 val it
removes more wrong pixels than the GT mask does.

Selection rule (approved 2026-11-12, results/rgb_proposal_selected.json): maximise wrong removed
subject to correct lost <= 5% on D435 val over the grid of tune_rgb_proposal.py. Test splits
need --allow-test and are run once each, with no change to the method afterwards.

Mask network provenance: ClearGrasp mask_segmentation checkpoint, trained on synthetic images
only (its config.yaml; the real D435 val images were evaluated during its training, never
trained on; the real test images are not referenced).
"""
import argparse
import os
from pathlib import Path
import re
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_glassbench import bucket_counts, load_glassbench, markdown  # noqa: E402, I100
from eval_glassbench import summarize, write_outputs  # noqa: E402, I100


def ring_flag(raw, pred, ring_px, min_m, min_rel, min_ring_px=20, per_region=True):
    """Flag predicted-mask pixels that read farther than the valid ring just outside the mask."""
    import cv2
    pred = np.asarray(pred, bool)
    valid = np.isfinite(raw) & (raw > 0)
    flag = np.zeros(raw.shape, bool)
    if per_region:
        n, labels = cv2.connectedComponents(pred.astype(np.uint8), connectivity=8)
    else:
        n, labels = 2, pred.astype(np.int32)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * ring_px + 1, 2 * ring_px + 1))
    for i in range(1, n):
        region = labels == i
        ys, xs = np.nonzero(region)
        y0, y1 = max(ys.min() - ring_px, 0), min(ys.max() + ring_px + 1, raw.shape[0])
        x0, x1 = max(xs.min() - ring_px, 0), min(xs.max() + ring_px + 1, raw.shape[1])
        sub = region[y0:y1, x0:x1]
        ring = (cv2.dilate(sub.astype(np.uint8), k) > 0) & ~pred[y0:y1, x0:x1] \
            & valid[y0:y1, x0:x1]
        if int(ring.sum()) < min_ring_px:
            continue
        r = raw[y0:y1, x0:x1]
        ref = float(np.median(r[ring]))
        far = r - ref
        flag[y0:y1, x0:x1] |= sub & valid[y0:y1, x0:x1] & (far > min_m) & (far > min_rel * r)
    return flag


def yaml_params(path):
    """Read min_basin_depth_m / min_basin_depth_rel from a sensor profile."""
    out = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r'\s*(min_basin_depth_m|min_basin_depth_rel)\s*:\s*([0-9.eE+-]+)', line)
        if m:
            out[m.group(1)] = float(m.group(2))
    return out


def make_preds(loader, glassbench, items, pred_dir):
    import cv2
    sys.path.insert(0, str(Path(glassbench).expanduser() / 'tools' / 'flagging'))
    sys.path.insert(0, str(Path(glassbench).expanduser() / 'tools' / 'evaluation'))
    sys.path.insert(0, str(Path(glassbench).expanduser() / 'tools'))
    import flag_eval  # GlassBench: ClearGrasp DeepLabV3 mask network, RGB only
    model = flag_eval.build()
    pred_dir.mkdir(parents=True, exist_ok=True)
    for _, split, sid in items:
        s = loader.load_cleargrasp(split, sid)
        pm = flag_eval.predict_mask(model, s['rgb'])
        cv2.imwrite(str(pred_dir / f'{sid}.png'), pm.astype(np.uint8) * 255)
    print(f'wrote {len(items)} masks to {pred_dir}')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', required=True,
                    choices=['real-test/d415', 'real-test/d435', 'real-val/d435'])
    ap.add_argument('--allow-test', action='store_true',
                    help='required for test splits (needs an approved selection rule)')
    ap.add_argument('--name', default=None)
    ap.add_argument('--glassbench', default=os.environ.get('GLASSBENCH', '~/glassbench'))
    ap.add_argument('--pred-dir', default=None, help='default: out/rgb_masks/<split>')
    ap.add_argument('--make-preds', action='store_true', help='write the masks and exit')
    ap.add_argument('--proposal', default='pred', choices=['pred', 'gt'])
    ap.add_argument('--params', default='config/realsense_d435.yaml')
    ap.add_argument('--min-basin-depth-m', type=float, default=None)
    ap.add_argument('--min-basin-depth-rel', type=float, default=None)
    ap.add_argument('--ring-px', type=int, default=15)
    ap.add_argument('--min-ring-px', type=int, default=20)
    ap.add_argument('--whole-mask', action='store_true',
                    help='one ring around the whole predicted mask instead of one per region')
    ap.add_argument('--tol', default='rel5%')
    ap.add_argument('--out', default='results')
    a = ap.parse_args()
    if 'test' in a.split and not a.allow_test:
        sys.exit('test split: pass --allow-test only after the selection rule is approved')

    import cv2
    loader = load_glassbench(a.glassbench)
    items = list(loader.list_cleargrasp([a.split]))
    pred_dir = Path(a.pred_dir or Path('out') / 'rgb_masks' / a.split)
    if a.make_preds:
        return make_preds(loader, a.glassbench, items, pred_dir)

    p = yaml_params(a.params)
    min_m = a.min_basin_depth_m if a.min_basin_depth_m is not None else p['min_basin_depth_m']
    min_rel = (a.min_basin_depth_rel if a.min_basin_depth_rel is not None
               else p['min_basin_depth_rel'])
    name = a.name or 'rgb_proposal_' + a.split.replace('real-', '').replace('/', '_')

    rows = []
    cover = {'wrong': 0, 'wrong_in_pred': 0, 'pred': 0, 'gt': 0, 'inter': 0, 'union': 0}
    for _, split, sid in items:
        s = loader.load_cleargrasp(split, sid)
        if a.proposal == 'gt':
            pred = s['mask']
        else:
            png = cv2.imread(str(pred_dir / f'{sid}.png'), cv2.IMREAD_UNCHANGED)
            if png is None:
                sys.exit(f'missing mask prediction {pred_dir / (sid + ".png")}; see --make-preds')
            pred = png > 0
        if pred.shape != s['depth_raw'].shape:
            sys.exit(f'{sid}: mask shape {pred.shape} != depth {s["depth_raw"].shape}')
        flag = ring_flag(s['depth_raw'], pred, a.ring_px, min_m, min_rel, a.min_ring_px,
                         not a.whole_mask)
        for region, m in (('mask', s['mask']), ('nonmask', ~s['mask'])):
            c = bucket_counts(s['depth_raw'], s['depth_gt'], m, flag, a.tol)
            if region == 'mask':  # how much of the problem the proposal covers at all
                c0 = bucket_counts(s['depth_raw'], s['depth_gt'], m, pred, a.tol)
                cover['wrong'] += c0['wrong']
                cover['wrong_in_pred'] += c0['wrong_flagged']
            rows.append(dict(id=s['id'], region=region, tol=a.tol, **c))
        cover['pred'] += int(pred.sum())
        cover['gt'] += int(s['mask'].sum())
        cover['inter'] += int((pred & s['mask']).sum())
        cover['union'] += int((pred | s['mask']).sum())

    summ = summarize(rows, [], name, a.split, a.tol)
    summ.update(
        resolution='native', method='rgb_proposal_ring', proposal=a.proposal,
        ring_px=a.ring_px, min_ring_px=a.min_ring_px, per_region=not a.whole_mask,
        min_basin_depth_m=min_m, min_basin_depth_rel=min_rel,
        proposal_iou=100.0 * cover['inter'] / cover['union'] if cover['union'] else float('nan'),
        proposal_area_vs_gt=100.0 * cover['pred'] / cover['gt'] if cover['gt'] else float('nan'),
        wrong_inside_proposal=(100.0 * cover['wrong_in_pred'] / cover['wrong']
                               if cover['wrong'] else float('nan')))
    write_outputs(rows, summ, Path(a.out), name)
    print(markdown(summ))
    print(f"proposal IoU {summ['proposal_iou']:.1f}%, area vs GT mask "
          f"{summ['proposal_area_vs_gt']:.1f}%, wrong pixels inside the proposal "
          f"{summ['wrong_inside_proposal']:.1f}%")


if __name__ == '__main__':
    main()
