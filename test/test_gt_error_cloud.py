"""Bucket classification and cloud packing of scripts/gt_error_cloud.py on a tiny example."""
import importlib.util
from pathlib import Path

import numpy as np

_path = Path(__file__).resolve().parent.parent / 'scripts' / 'gt_error_cloud.py'
_spec = importlib.util.spec_from_file_location('gt_error_cloud', _path)
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def tiny():
    """Return raw, gt, mask for a 2x4 image; the left 2x2 block is the transparent object."""
    gt = np.full((2, 4), 1.0, np.float32)
    mask = np.zeros((2, 4), bool)
    mask[:, :2] = True
    raw = np.array([[1.04, 1.30, 1.50, 0.0],     # correct (4% off), wrong (too far), outside, hole
                    [0.00, 0.90, 1.00, 1.0]],    # missing in mask, wrong (too near), outside x2
                   np.float32)
    return raw, gt, mask


def test_buckets():
    raw, gt, mask = tiny()
    b = g.classify(raw, gt, mask)
    expect = np.array([[g.CORRECT, g.WRONG, g.OUTSIDE, g.MISSING],
                       [g.MISSING, g.WRONG, g.OUTSIDE, g.OUTSIDE]], np.uint8)
    assert (b == expect).all()


def test_tolerance_edge_and_missing_gt():
    gt = np.array([[2.0, 2.0, 0.0, np.nan]], np.float32)
    raw = np.array([[2.1, 2.11, 1.0, 1.0]], np.float32)   # exactly 5%: correct; 5.5%: wrong
    b = g.classify(raw, gt, np.ones((1, 4), bool))
    assert list(b[0]) == [g.CORRECT, g.WRONG, g.UNKNOWN, g.UNKNOWN]


def test_stats_and_score():
    raw, gt, mask = tiny()
    s = g.error_stats(raw, gt, g.classify(raw, gt, mask))
    assert s['wrong_px'] == 2 and s['correct_px'] == 1 and s['wrong_too_far_px'] == 1
    assert abs(s['gap_median_m'] - 0.1) < 1e-6      # median of +0.30 and -0.10
    assert abs(s['score'] - 0.2) < 1e-6


def test_cloud_colours_and_geometry():
    raw, gt, mask = tiny()
    xyz, rgb = g.coloured_cloud(raw, g.classify(raw, gt, mask), 2.0, 2.0, 1.0, 0.0)
    assert len(xyz) == 6                             # 2 missing pixels are not shown
    colours = {tuple(c) for c in rgb}
    assert colours == {(255, 0, 0), (255, 255, 255), (90, 90, 90)}
    red = xyz[(rgb == (255, 0, 0)).all(axis=1)]
    # pixel (u=1, v=0), z=1.3 -> x=0, y=0 ; pixel (u=1, v=1), z=0.9 -> x=0, y=0.45
    assert np.allclose(sorted(red.tolist()), [[0, 0, 1.3], [0, 0.45, 0.9]], atol=1e-6)
    data = g.cloud_bytes(xyz, rgb)
    assert len(data) == 16 * 6
    packed = np.frombuffer(data, '<u4').reshape(-1, 4)[:, 3]
    assert set(packed.tolist()) == {0xFF0000, 0xFFFFFF, 0x5A5A5A}


def test_depth_crc_distinguishes_scenes():
    a = np.arange(12, dtype=np.uint16).reshape(3, 4)
    b = a.copy()
    b[0, 0] = 7
    assert g.depth_crc(a) == g.depth_crc(a.copy()) != g.depth_crc(b)
