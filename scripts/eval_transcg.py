#!/usr/bin/env python3
"""v0.2 confirmation run on TransCG D435 (docs/v0.2_protocol.md): RGB proposal against v0.1.

Runs both methods on the same views and scores them with the metric code of eval_glassbench.py:
  rgb   ring_flag() of eval_rgb_proposal.py (imported, not copied), ClearGrasp mask network
  v01   the depth-only filter_cli with config/realsense_d435.yaml
Scenes come from the official split in TransCG's metadata.json ("train" / "test" lists). Only D435
views with ground truth are used.

Streaming and resumable: one scene at a time. For every finished scene only the bucket counts
(numbers, no pixels) are kept in <out>/<name>/scenes/scene<N>.json and a line is added to
<out>/<name>/done.log; a scene that has its JSON is skipped on the next start. With
--delete-scene-after the scene's folder in the dataset is removed once its counts are saved, so
the dataset never has to be on disk as a whole (scripts/run_transcg_zip.sh does that per zip).
The held-out split prints no metric and no verdict until every official scene is done.

Confidence intervals: bootstrap over scenes (not pixels), 2000 resamples, seed 20261112.
PASS needs all three (protocol section 4):
  wrong removed (rgb) >= 1.5 x wrong removed (v01), and the 95% CI lower bound of the ratio >= 1.5
  correct lost (rgb) <= correct lost (v01) + 2.0 percentage points
  outside-mask flagged (rgb) < outside-mask flagged (v01)
A bootstrap over views is also reported, as secondary: it is optimistic (views of one scene are
not independent) and never decides PASS.

TransCG is CC BY-NC-SA 4.0. Everything is written to --out (default out/transcg, gitignored);
this script refuses to write into results/. Only the pooled summary and the bootstrap rows
(eval_<name>_summary.csv, eval_<name>_bootstrap.csv; no image or scene ids) may be copied out.

  eval_transcg.py --split train --limit 10          plumbing check, at most 10 TRAIN views
  eval_transcg.py --split test --allow-test         the held-out run: only after the owner says go
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_glassbench import bucket_counts, load_glassbench, summarize  # noqa: E402, I100
from eval_rgb_proposal import ring_flag, yaml_params  # noqa: E402, I100

METHODS = ('rgb', 'v01')
METRICS = ('wrong_removed', 'correct_lost', 'outside_flagged')
FIELDS = (('mask', 'wrong'), ('mask', 'wrong_flagged'), ('mask', 'correct'),
          ('mask', 'correct_flagged'), ('nonmask', 'returned'), ('nonmask', 'returned_flagged'))
COVER = ('wrong', 'wrong_in_pred', 'pred', 'gt', 'inter', 'union')
MAX_TRAIN_VIEWS = 10


def official_scenes(root, split):
    """Scene numbers of the official split, from TransCG's metadata.json."""
    return sorted(json.loads((Path(root) / 'metadata.json').read_text())[split])


def scene_views(views, scene, per_scene, seed):
    """D435 views of one scene: all of them, or a fixed number drawn with seed + scene."""
    mine = sorted(v for v in views if Path(v).parent.name == f'scene{scene}')
    if per_scene and len(mine) > per_scene:
        rng = np.random.default_rng(seed + scene)
        mine = [mine[i] for i in sorted(rng.choice(len(mine), per_scene, replace=False))]
    return mine


def metrics_from(t):
    """The three protocol metrics in % from totals in FIELDS order (last axis)."""
    with np.errstate(divide='ignore', invalid='ignore'):
        return (100.0 * t[..., 1] / t[..., 0], 100.0 * t[..., 3] / t[..., 2],
                100.0 * t[..., 5] / t[..., 4])


def bootstrap(per_unit, resamples, seed, unit='scene'):
    """Point estimates and 95% CIs; per_unit[method][unit][region] = counts, units resampled."""
    units = sorted(per_unit[METHODS[0]])
    arr = {m: np.array([[per_unit[m][u][r].get(k, 0) for r, k in FIELDS] for u in units],
                       np.float64) for m in METHODS}
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(units), (resamples, len(units)))
    point = {m: [float(x) for x in metrics_from(arr[m].sum(axis=0))] for m in METHODS}
    draws = {m: metrics_from(np.stack([arr[m][p].sum(axis=0) for p in pick])) for m in METHODS}

    def row(method, metric, value, x):
        x = np.asarray(x, float)
        lo, hi = ((float('nan'), float('nan')) if np.isnan(x).all()
                  else (float(np.nanpercentile(x, 2.5)), float(np.nanpercentile(x, 97.5))))
        return {'method': method, 'metric': metric, 'point': value, 'ci95_lo': lo, 'ci95_hi': hi,
                'unit': unit, 'units': len(units), 'resamples': resamples, 'seed': seed}
    rows = [row(m, k, point[m][i], draws[m][i]) for m in METHODS for i, k in enumerate(METRICS)]
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio = draws['rgb'][0] / draws['v01'][0]
    ratio[~np.isfinite(ratio)] = np.nan
    v = point['v01'][0]
    rows.append(row('rgb/v01', 'wrong_removed_ratio',
                    point['rgb'][0] / v if v else float('nan'), ratio))
    return rows


def verdict(rows):
    """Apply the three declared conditions. Returns (PASS or FAIL, {condition: bool})."""
    p = {(r['method'], r['metric']): r for r in rows}
    ratio = p['rgb/v01', 'wrong_removed_ratio']
    checks = {
        'ratio_point_ge_1.5': ratio['point'] >= 1.5,
        'ratio_ci95_lo_ge_1.5': ratio['ci95_lo'] >= 1.5,
        'correct_lost_within_2pp': (p['rgb', 'correct_lost']['point']
                                    <= p['v01', 'correct_lost']['point'] + 2.0),
        'outside_flagged_lower': (p['rgb', 'outside_flagged']['point']
                                  < p['v01', 'outside_flagged']['point'])}
    return ('PASS' if all(checks.values()) else 'FAIL'), checks


def freeze_record(params):
    """Commit and sha256 of the frozen files: must not change between the scenes of one run."""
    here = Path(__file__).resolve().parent
    files = [here / 'eval_rgb_proposal.py', here / 'eval_glassbench.py', Path(params)]
    head = subprocess.run(['git', '-C', str(here), 'rev-parse', 'HEAD'], capture_output=True,
                          text=True).stdout.strip() or 'unknown'
    return {'commit': head, 'sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                                       for f in files}}


def write_csv(path, rows):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def run_scene(a, loader, model_box, scene, views, work, staged, thresholds):
    """Run both methods on one scene. Returns the dict that is saved as scene<N>.json."""
    import cv2
    din, dout = work / 'depth', work / 'out'
    for d in (din, dout):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    if model_box[0] is None:
        gb = Path(a.glassbench).expanduser() / 'tools'
        for sub in ('flagging', 'evaluation', ''):
            sys.path.insert(0, str(gb / sub))
        import flag_eval  # GlassBench: ClearGrasp DeepLabV3 mask network, RGB only
        model_box[0] = (flag_eval, flag_eval.build())
    flag_eval, model = model_box[0]
    out_views, cover = [], dict.fromkeys(COVER, 0)
    for c0 in range(0, len(views), a.chunk):
        chunk = views[c0:c0 + a.chunk]
        for view in chunk:
            s = loader.load_transcg(view, 'D435')
            cv2.imwrite(str(din / f'{Path(view).name}.tiff'), s['depth_raw'].astype(np.float32))
        cmd = shlex.split(a.cli) + ['--depth', str(din), '--out', str(dout),
                                    '--params', str(staged)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f'filter_cli failed:\n{proc.stderr}')
        for view in chunk:
            s = loader.load_transcg(view, 'D435')
            raw, gt, mask = s['depth_raw'], s['depth_gt'], s['mask']
            pred = flag_eval.predict_mask(model, s['rgb'])
            v01 = cv2.imread(str(dout / f'{Path(view).name}_mask.png'), cv2.IMREAD_UNCHANGED) > 0
            if pred.shape != raw.shape or v01.shape != raw.shape:
                sys.exit(f'{s["id"]}: mask shapes {pred.shape} / {v01.shape} != depth '
                         f'{raw.shape}')
            flags = {'rgb': ring_flag(raw, pred, a.ring_px, *thresholds, a.min_ring_px, True),
                     'v01': v01}
            out_views.append({'id': s['id'], 'counts': {
                m: {region: bucket_counts(raw, gt, sel, flags[m], a.tol)
                    for region, sel in (('mask', mask), ('nonmask', ~mask))} for m in METHODS}})
            c = bucket_counts(raw, gt, mask, pred, a.tol)
            for k, v in (('wrong', c['wrong']), ('wrong_in_pred', c['wrong_flagged']),
                         ('pred', int(pred.sum())), ('gt', int(mask.sum())),
                         ('inter', int((pred & mask).sum())),
                         ('union', int((pred | mask).sum()))):
                cover[k] += v
        for f in list(din.iterdir()) + list(dout.iterdir()):
            f.unlink()
    return {'scene': scene, 'views': out_views, 'cover': cover}


def finalize(a, name, state, split_total, done):
    """Pool the saved counts, bootstrap, write the two CSVs that may leave out/, print a table."""
    rows = {m: [] for m in METHODS}
    per_scene = {m: {} for m in METHODS}
    per_view = {m: {} for m in METHODS}
    cover = dict.fromkeys(COVER, 0)
    for scene in done:
        d = json.loads((state / 'scenes' / f'scene{scene}.json').read_text())
        for k in COVER:
            cover[k] += d['cover'][k]
        for v in d['views']:
            for m in METHODS:
                per_view[m][v['id']] = v['counts'][m]
                for region, c in v['counts'][m].items():
                    rows[m].append(dict(id=v['id'], region=region, tol=a.tol, **c))
                    acc = per_scene[m].setdefault(scene, {}).setdefault(region, {})
                    for k, x in c.items():
                        acc[k] = acc.get(k, 0) + x
    n_views = len(per_view['rgb'])

    def pct(x, y):
        return 100.0 * x / y if y else float('nan')
    p = yaml_params(a.params)
    summaries = []
    for m in METHODS:
        s = summarize(rows[m], [], f'{name}_{m}', f'transcg/{a.split}/D435', a.tol)
        s.pop('latency_ms_mean')
        s.pop('latency_ms_p95')
        rgb = m == 'rgb'
        s.update(method=m, scenes=len(done), official_split_scenes=split_total,
                 views_per_scene=a.views_per_scene or 'all', seed=a.seed, params=a.params,
                 ring_px=a.ring_px if rgb else '', min_ring_px=a.min_ring_px if rgb else '',
                 min_basin_depth_m=p['min_basin_depth_m'],
                 min_basin_depth_rel=p['min_basin_depth_rel'],
                 proposal_iou=pct(cover['inter'], cover['union']) if rgb else '',
                 proposal_area_vs_gt=pct(cover['pred'], cover['gt']) if rgb else '',
                 wrong_inside_proposal=pct(cover['wrong_in_pred'], cover['wrong']) if rgb else '')
        summaries.append(s)
    boot = bootstrap(per_scene, a.resamples, a.seed, 'scene')
    result, checks = verdict(boot)
    secondary = bootstrap(per_view, a.resamples, a.seed, 'view')
    for r in boot:
        r.update(role='decides PASS/FAIL', verdict=result)
    for r in secondary:
        r.update(role='secondary, optimistic, never decides', verdict='')
    out = Path(a.out)
    write_csv(out / f'eval_{name}_summary.csv', summaries)
    write_csv(out / f'eval_{name}_bootstrap.csv', boot + secondary)

    print(f'\n{name}: {n_views} views, {len(done)} scenes, tolerance {a.tol}')
    print('| Method | Wrong among returned (raw -> after) | Wrong removed [95% CI] | '
          'Correct lost [95% CI] | Outside-mask flagged [95% CI] |')
    print('|---|---|---|---|---|')
    b = {(r['method'], r['metric']): r for r in boot}
    for s in summaries:
        cells = ' | '.join(
            f"{b[s['method'], k]['point']:.1f}% [{b[s['method'], k]['ci95_lo']:.1f}, "
            f"{b[s['method'], k]['ci95_hi']:.1f}]" for k in METRICS)
        print(f"| {s['method']} | {s['wrong_among_returned_raw']:.1f}% -> "
              f"{s['wrong_among_returned_after']:.1f}% | {cells} |")
    r, r2 = b['rgb/v01', 'wrong_removed_ratio'], secondary[-1]
    print(f"ratio wrong removed rgb / v01: {r['point']:.2f} "
          f"[{r['ci95_lo']:.2f}, {r['ci95_hi']:.2f}] (bootstrap over scenes)")
    print(f"  secondary, optimistic (bootstrap over views): "
          f"[{r2['ci95_lo']:.2f}, {r2['ci95_hi']:.2f}]")
    s = summaries[0]
    print(f"missing in mask {s['missing_pct']:.1f}%, proposal IoU {s['proposal_iou']:.1f}%, "
          f"area vs GT {s['proposal_area_vs_gt']:.1f}%, wrong inside proposal "
          f"{s['wrong_inside_proposal']:.1f}%")
    print(f'checks: {checks}')
    print(f'VERDICT: {result}' if a.split == 'test' else
          f'(plumbing run on TRAIN, not a result; the verdict logic returned {result})')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--split', required=True, choices=['train', 'test'])
    ap.add_argument('--allow-test', action='store_true',
                    help='required for the held-out split (approved, committed protocol)')
    ap.add_argument('--limit', type=int, default=0,
                    help=f'train only, required: first N views of one scene, <= {MAX_TRAIN_VIEWS}')
    ap.add_argument('--views-per-scene', type=int, default=0, help='0 = all views with GT')
    ap.add_argument('--seed', type=int, default=20261112)
    ap.add_argument('--resamples', type=int, default=2000)
    ap.add_argument('--scenes', default=None,
                    help='only these official scenes this time, e.g. 11,12 (default: every '
                         'official scene found on disk that is not done yet)')
    ap.add_argument('--delete-scene-after', action='store_true',
                    help='remove a scene folder from the dataset once its counts are saved')
    ap.add_argument('--glassbench', default=os.environ.get('GLASSBENCH', '~/glassbench'))
    ap.add_argument('--params', default='config/realsense_d435.yaml')
    ap.add_argument('--ring-px', type=int, default=15)
    ap.add_argument('--min-ring-px', type=int, default=20)
    ap.add_argument('--tol', default='rel5%')
    ap.add_argument('--cli', default='ros2 run limit_case_ros2 filter_cli')
    ap.add_argument('--out', default='out/transcg',
                    help='state lives in <out>/<name>/ (mount <out>/<name>/work at the same '
                         'path when --cli runs in Docker)')
    ap.add_argument('--name', default=None)
    ap.add_argument('--chunk', type=int, default=40, help='views per filter_cli call')
    a = ap.parse_args()
    if a.split == 'test' and not a.allow_test:
        sys.exit('held-out split: pass --allow-test only after the owner says go '
                 '(docs/v0.2_protocol.md)')
    if a.split == 'train' and not 0 < a.limit <= MAX_TRAIN_VIEWS:
        sys.exit(f'train split is for plumbing only: pass --limit 1..{MAX_TRAIN_VIEWS}')
    if a.split == 'train' and a.delete_scene_after:
        sys.exit('--delete-scene-after is for the held-out run only')
    if Path('results').resolve() in [Path(a.out).resolve(), *Path(a.out).resolve().parents]:
        sys.exit('TransCG output must not go to results/ (see docs/v0.2_protocol.md section 5)')
    name = a.name or f'transcg_d435_{a.split}'
    state = Path(a.out) / name
    work = (state / 'work').resolve()
    (state / 'scenes').mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    staged = work / 'params.yaml'
    staged.write_text(Path(a.params).read_text())
    p = yaml_params(a.params)
    thresholds = (p['min_basin_depth_m'], p['min_basin_depth_rel'])

    frozen, record = state / 'frozen.json', freeze_record(a.params)
    if not frozen.exists():
        frozen.write_text(json.dumps(record, indent=2))
    elif json.loads(frozen.read_text()) != record:
        sys.exit(f'commit or frozen files changed since this run started (see {frozen}); '
                 'a run must use one frozen state')

    loader = load_glassbench(a.glassbench)
    official = official_scenes(loader.TRANSCG_ROOT, a.split)

    def done_scenes():
        return [n for n in official if (state / 'scenes' / f'scene{n}.json').exists()]

    todo = [n for n in official if n not in done_scenes()
            and (Path(loader.TRANSCG_ROOT) / f'scene{n}').is_dir()]
    if a.scenes:
        todo = [n for n in todo if n in {int(x) for x in a.scenes.split(',')}]
    if a.split == 'train':
        todo = todo[:1] if not done_scenes() else []
    print(f'{a.split}: {len(official)} official scenes, {len(done_scenes())} done, '
          f'{len(todo)} on disk to do', flush=True)
    all_views = loader.list_transcg('D435') if todo else []
    model_box = [None]
    for scene in todo:
        t0 = time.time()
        views = scene_views(all_views, scene, a.views_per_scene, a.seed)
        if a.split == 'train':
            views = views[:a.limit]
        if not views:
            sys.exit(f'scene{scene}: no D435 view with ground truth; fix or remove the folder')
        data = run_scene(a, loader, model_box, scene, views, work, staged, thresholds)
        tmp = state / 'scenes' / f'scene{scene}.json.tmp'
        tmp.write_text(json.dumps(data))
        tmp.replace(state / 'scenes' / f'scene{scene}.json')  # atomic: a scene is done or not
        took = time.time() - t0
        with open(state / 'done.log', 'a') as f:
            f.write(f'{time.strftime("%Y-%m-%dT%H:%M:%S")} scene{scene} views={len(views)} '
                    f'seconds={took:.0f}\n')
        if a.delete_scene_after:
            shutil.rmtree(Path(loader.TRANSCG_ROOT) / f'scene{scene}')
        print(f'scene{scene}: {len(views)} views in {took:.0f} s ({took / len(views):.2f} s per '
              f'view), {len(done_scenes())}/{len(official)} scenes done', flush=True)

    done = done_scenes()
    if a.split == 'test' and len(done) < len(official):
        missing = [n for n in official if n not in done]
        print(f'{len(done)}/{len(official)} official test scenes done. No metric is shown until '
              f'all are done. Still needed: {missing}')
        return
    finalize(a, name, state, len(official), done)


if __name__ == '__main__':
    main()
