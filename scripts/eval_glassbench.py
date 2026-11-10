#!/usr/bin/env python3
"""Evaluate the glass filter on GlassBench's ClearGrasp sets.

Uses GlassBench's own loaders and its three-bucket definition (glassbench/docs/measurement.md).

Per region, over GT-valid pixels only (GT finite and > 0):
  missing  raw == 0                                (a visible failure; never counted as wrong)
  correct  raw > 0 and |raw - gt| within tol        (tol: rel5% = 5% of gt, or abs1cm)
  wrong    raw > 0 and |raw - gt| outside tol       (a silent failure)
Reported (pooled over pixels, then divided once):
  wrong_among_returned_raw     wrong / (correct + wrong), before filtering
  wrong_among_returned_after   same, after removing the pixels we flag
  wrong_removed                % of wrong pixels we flag
  correct_lost                 % of correct pixels we flag
  outside_flagged              % of returned GT-valid pixels outside the mask we flag
                               (ClearGrasp control)
  latency mean / p95 ms        per frame, as printed by filter_cli
Writes results/eval_<name>.csv (per image), results/eval_<name>_summary.csv and
results/eval_<name>.md.

  eval_glassbench.py --split real-test/d435 --name cg_d435_test
Splits: real-test/d415, real-test/d435, real-val/d435. Tune on real-val/d435 only.
Needs the GlassBench repo (default ~/glassbench, override with --glassbench or $GLASSBENCH)
with its requirements installed (numpy, opencv, OpenEXR) and the ClearGrasp download in
datasets/. TransCG may be evaluated locally but its images and derived images are never
committed (CC BY-NC-SA).
"""
import argparse
import csv
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

import numpy as np

TOLS = {'rel5%': lambda gt: 0.05 * gt, 'abs1cm': lambda gt: 0.01 + 0 * gt}


def pct(a, b):
    return 100.0 * a / b if b else float('nan')


def bucket_counts(raw, gt, region, flag, tol):
    """Three-bucket counts over GT-valid pixels of `region`, split by whether we flagged them."""
    sel = region & np.isfinite(gt) & (gt > 0)
    r, g, f = raw[sel], gt[sel], flag[sel]
    present = r > 0
    correct = present & (np.abs(r - g) <= TOLS[tol](g))
    wrong = present & ~correct
    return {
        'n': int(r.size), 'missing': int((~present).sum()),
        'correct': int(correct.sum()), 'wrong': int(wrong.sum()),
        'wrong_far': int((wrong & (r > g)).sum()),
        'correct_flagged': int((correct & f).sum()), 'wrong_flagged': int((wrong & f).sum()),
        'returned_flagged': int((present & f).sum()), 'returned': int(present.sum())}


def summarize(rows, lat_ms, name, split, tol):
    def tot(region, k):
        return sum(r[k] for r in rows if r['region'] == region)
    m = lambda k: tot('mask', k)  # noqa: E731
    o = lambda k: tot('nonmask', k)  # noqa: E731
    returned = m('correct') + m('wrong')
    s = dict(  # noqa: C408
        name=name, split=split, tol=tol, images=len({r['id'] for r in rows}),
        mask_pixels=m('n'),
        correct_pct=pct(m('correct'), m('n')), missing_pct=pct(m('missing'), m('n')),
        wrong_pct=pct(m('wrong'), m('n')),
        wrong_too_far_pct=pct(m('wrong_far'), m('wrong')),
        wrong_among_returned_raw=pct(m('wrong'), returned),
        wrong_among_returned_after=pct(m('wrong') - m('wrong_flagged'),
                                       returned - m('wrong_flagged') - m('correct_flagged')),
        wrong_removed=pct(m('wrong_flagged'), m('wrong')),
        correct_lost=pct(m('correct_flagged'), m('correct')),
        outside_flagged=pct(o('returned_flagged'), o('returned')),
        latency_ms_mean=float(np.mean(lat_ms)) if lat_ms else float('nan'),
        latency_ms_p95=float(np.percentile(lat_ms, 95)) if lat_ms else float('nan'))
    return s


def markdown(s):
    return (
        '| Set | Images | Wrong among returned (raw -> after) | Wrong pixels removed | '
        'Correct pixels lost | Outside-mask flagged | Latency mean / p95 (ms) |\n'
        '|---|---|---|---|---|---|---|\n'
        f"| {s['name']} ({s['tol']}) | {s['images']} | "
        f"{s['wrong_among_returned_raw']:.1f}% -> {s['wrong_among_returned_after']:.1f}% | "
        f"{s['wrong_removed']:.1f}% | {s['correct_lost']:.1f}% | {s['outside_flagged']:.1f}% | "
        f"{s['latency_ms_mean']:.1f} / {s['latency_ms_p95']:.1f} |\n")


def write_outputs(rows, s, out, name):
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f'eval_{name}.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(out / f'eval_{name}_summary.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(s.keys()))
        w.writeheader()
        w.writerow(s)
    (out / f'eval_{name}.md').write_text(markdown(s))


def load_glassbench(root):
    root = Path(root).expanduser()
    sys.path.insert(0, str(root / 'tools' / 'loaders'))
    os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')
    import loader  # noqa: E402  (GlassBench's loader.py)
    return loader


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', required=True,
                    choices=['real-test/d415', 'real-test/d435', 'real-val/d435'])
    ap.add_argument('--name', default=None, help='output name (default: derived from split)')
    ap.add_argument('--glassbench', default=os.environ.get('GLASSBENCH', '~/glassbench'))
    ap.add_argument('--tol', default='rel5%', choices=list(TOLS))
    ap.add_argument('--params', default='config/default.yaml')
    ap.add_argument('--set', action='append', default=[], help='key=value override (grid search)')
    ap.add_argument('--cli', default='ros2 run limit_case_ros2 filter_cli')
    ap.add_argument('--use-rgb', action='store_true')
    ap.add_argument('--out', default='results')
    ap.add_argument('--workdir', default=None,
                    help='stage files here instead of a temp dir (needed when --cli runs '
                         'in Docker: mount this path at the same path)')
    ap.add_argument('--resize', default=None, metavar='WxH',
                    help='nearest-resize depth, GT and mask first (e.g. 640x480) to report '
                         'latency and metrics per resolution')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    name = a.name or 'cg_' + a.split.replace('real-', '').replace('/', '_')

    import cv2
    loader = load_glassbench(a.glassbench)
    items = list(loader.list_cleargrasp([a.split]))
    if a.limit:
        items = items[:a.limit]
    if not items:
        sys.exit(f'no samples for {a.split} under {loader.CLEARGRASP_ROOT}')

    size = tuple(int(v) for v in a.resize.lower().split('x')) if a.resize else None

    def prep(img, interp=cv2.INTER_NEAREST):
        return cv2.resize(img, size, interpolation=interp) if size else img

    rows, lat_ms = [], []
    cm = tempfile.TemporaryDirectory() if not a.workdir else None
    with (cm if cm else open(os.devnull)) as _:
        tmp = Path(cm.name if cm else a.workdir)
        tmp.mkdir(parents=True, exist_ok=True)
        din, rin, dout = tmp / 'depth', tmp / 'rgb', tmp / 'out'
        for d_ in (din, rin, dout):
            d_.mkdir(parents=True, exist_ok=True)
        for _, split, sid in items:  # float32 meters, exact (no mm quantisation)
            s = loader.load_cleargrasp(split, sid)
            cv2.imwrite(str(din / f'{sid}.tiff'), prep(s['depth_raw'].astype(np.float32)))
            if a.use_rgb:
                bgr = cv2.cvtColor(s['rgb'], cv2.COLOR_RGB2BGR)
                cv2.imwrite(str(rin / f'{sid}.png'), prep(bgr))
        cmd = shlex.split(a.cli) + ['--depth', str(din), '--out', str(dout)]
        if a.params and Path(a.params).exists():
            staged = tmp / 'params.yaml'  # same path is visible to a Dockerised CLI
            staged.write_text(Path(a.params).read_text())
            cmd += ['--params', str(staged)]
        if a.use_rgb:
            cmd += ['--rgb', str(rin)]
        for kv in a.set:
            cmd += ['--set', kv]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f'filter_cli failed:\n{proc.stderr}')
        lat = {}
        for line in proc.stdout.splitlines():
            p = line.split(',')
            if len(p) == 2 and p[0] != 'TOTAL':
                lat[p[0]] = float(p[1])

        for _, split, sid in items:
            s = loader.load_cleargrasp(split, sid)
            s['depth_raw'], s['depth_gt'] = prep(s['depth_raw']), prep(s['depth_gt'])
            s['mask'] = prep(s['mask'].astype(np.uint8)) > 0
            flag = cv2.imread(str(dout / f'{sid}_mask.png'), cv2.IMREAD_UNCHANGED) > 0
            if flag.shape != s['depth_raw'].shape:
                sys.exit(f'{sid}: mask shape {flag.shape} != depth {s["depth_raw"].shape}')
            lat_ms.append(lat.get(sid, float('nan')))
            for region, m in (('mask', s['mask']), ('nonmask', ~s['mask'])):
                c = bucket_counts(s['depth_raw'], s['depth_gt'], m, flag, a.tol)
                rows.append(dict(id=s['id'], region=region, tol=a.tol, **c))

    summ = summarize(rows, [x for x in lat_ms if x == x], name, a.split, a.tol)
    summ['resolution'] = a.resize or 'native'
    summ['params'] = a.params
    summ['overrides'] = ' '.join(a.set)
    write_outputs(rows, summ, Path(a.out), name)
    print(markdown(summ))


if __name__ == '__main__':
    main()
