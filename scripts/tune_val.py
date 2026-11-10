#!/usr/bin/env python3
r"""Val-only parameter search over filter_cli variants, with the fixed selection rule.

Rule (docs/DECISIONS.md D6): maximize `wrong removed` subject to `correct lost` <= 5% on
ClearGrasp D435 val (rel5%, mask region, pooled).

This script can only read real-val/d435: the test sets are never touched here. It stages the val
depth once, runs filter_cli per configuration (the official path; no Python re-implementation),
and scores with GlassBench's three-bucket definition using compact per-pixel category maps.
Writes results/tune_val.csv (every configuration) and results/selected.json (the winner).

  tune_val.py --workdir /tmp/lc_val \\
      --cli "docker run --rm -v /tmp/lc_val:/tmp/lc_val IMG \\
             /ws/install/limit_case_ros2/lib/limit_case_ros2/filter_cli"
"""
import argparse
import csv
import itertools
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_glassbench as ev  # noqa: E402,I100

SPLIT = 'real-val/d435'  # hard-wired: tuning never reads test data
BASE = ['downsample=3']  # decision D7: downsample 3 at 1280x720
THRESH = {'min_basin_depth_m': [0.01, 0.02, 0.03], 'min_basin_depth_rel': [0.015, 0.03],
          'confidence_threshold': [0.3, 0.5]}
VARIANTS = {
    'b_skip': {},
    'c_strict': {'boundary_verify': ['true'], 'min_nearer_boundary_frac': [0.1, 0.3]},
    'c_holeonly': {'boundary_verify': ['true'], 'flag_hole_only': ['true'],
                   'min_nearer_boundary_frac': [0.1, 0.3]},
}
MAX_CORRECT_LOST = 5.0  # percent, fixed before any test run


def configs():
    for vname, extra in VARIANTS.items():
        space = {**THRESH, **extra}
        keys = list(space)
        for vals in itertools.product(*[space[k] for k in keys]):
            yield vname, dict(zip(keys, vals))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cli', required=True)
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--glassbench', default=os.environ.get('GLASSBENCH', '~/glassbench'))
    ap.add_argument('--params', default='config/default.yaml')
    ap.add_argument('--out', default='results')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    import cv2
    loader = ev.load_glassbench(a.glassbench)
    items = loader.list_cleargrasp([SPLIT])
    items = items[:a.limit] if a.limit else items
    wd = Path(a.workdir)
    din, dout = wd / 'depth', wd / 'out'
    for d in (din, dout):
        d.mkdir(parents=True, exist_ok=True)
    (wd / 'params.yaml').write_text(Path(a.params).read_text())

    # sid -> uint8: bits 0-1 bucket (1 missing, 2 correct, 3 wrong), bit 2 = transparent mask
    cats = {}
    for _, split, sid in items:
        s = loader.load_cleargrasp(split, sid)
        f = din / f'{sid}.tiff'
        if not f.exists():
            cv2.imwrite(str(f), s['depth_raw'].astype(np.float32))
        raw, gt = s['depth_raw'], s['depth_gt']
        valid = np.isfinite(gt) & (gt > 0)
        present = raw > 0
        correct = present & (np.abs(raw - gt) <= 0.05 * gt)
        c = np.zeros(raw.shape, np.uint8)
        c[valid & ~present] = 1
        c[valid & correct] = 2
        c[valid & present & ~correct] = 3
        c[valid & s['mask']] |= 4
        cats[sid] = c

    rows = []
    for n, (vname, kv) in enumerate(configs()):
        sets = BASE + [f'{k}={v}' for k, v in kv.items()]
        cmd = shlex.split(a.cli) + ['--depth', str(din), '--out', str(dout), '--params',
                                    str(wd / 'params.yaml'), '--no-fill']
        for kvs in sets:
            cmd += ['--set', kvs]
        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f'filter_cli failed:\n{proc.stderr}')
        lat = [float(ln.split(',')[1]) for ln in proc.stdout.splitlines()
               if ln.count(',') == 1 and not ln.startswith('TOTAL')]
        # wrong, wrong_fl, correct, correct_fl, o_ret, o_ret_fl, flagged_total, n
        tot = np.zeros(8, np.int64)
        for sid, c in cats.items():
            flag = cv2.imread(str(dout / f'{sid}_mask.png'), cv2.IMREAD_UNCHANGED) > 0
            b, inmask = c & 3, (c & 4) > 0
            tot += [int(((b == 3) & inmask).sum()), int(((b == 3) & inmask & flag).sum()),
                    int(((b == 2) & inmask).sum()), int(((b == 2) & inmask & flag).sum()),
                    int((((b == 2) | (b == 3)) & ~inmask & (c > 0)).sum()),
                    int((((b == 2) | (b == 3)) & ~inmask & (c > 0) & flag).sum()),
                    int(flag.sum()), 0]
        row = dict(variant=vname, **kv, downsample=3,
                   wrong_removed=ev.pct(tot[1], tot[0]), correct_lost=ev.pct(tot[3], tot[2]),
                   outside_flagged=ev.pct(tot[5], tot[4]),
                   latency_ms_mean=float(np.mean(lat)),
                   latency_ms_p95=float(np.percentile(lat, 95)))
        rows.append(row)
        print(f"[{n}] {vname} {kv} -> removed {row['wrong_removed']:.1f}% lost "
              f"{row['correct_lost']:.1f}% outside {row['outside_flagged']:.1f}% "
              f'({time.time() - t0:.0f}s)', flush=True)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(out / 'tune_val.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, keys, restval='')
        w.writeheader()
        w.writerows(rows)
    ok = [r for r in rows if r['correct_lost'] <= MAX_CORRECT_LOST]
    if not ok:
        sys.exit('no configuration satisfies correct_lost <= 5%')
    best = max(ok, key=lambda r: r['wrong_removed'])
    sel = {k: (float(v) if isinstance(v, np.floating) else v) for k, v in best.items()}
    (out / 'selected.json').write_text(json.dumps(sel, indent=2))
    print('SELECTED:', best)


if __name__ == '__main__':
    main()
