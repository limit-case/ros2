#!/usr/bin/env python3
r"""Ground-truth error view: colour the RAW point cloud by GlassBench bucket.

Uses ClearGrasp ground-truth depth (the same scene with opaque twins of the objects) and the
transparent-object mask. Buckets follow glassbench/docs/measurement.md, tolerance 5% of GT:
  wrong    in the mask, depth returned, more than 5% off ground truth    red
  correct  in the mask, depth returned, within 5% of ground truth        white
  outside  depth returned, outside the mask                              dim grey
  missing  no depth returned (raw == 0)                                  not shown
Mask pixels that returned a depth but have no ground truth cannot be judged; not shown either.

Sub-commands (the first three need only numpy/opencv/matplotlib, no ROS):
  prepare  read ClearGrasp scenes, write a small sidecar .npz (GT depth + mask at bag resolution)
  rank     rank scenes by how clearly the through-glass error shows; writes a CSV
  preview  render static PNGs (orbit and side viewpoints per scene) from the sidecar
  node     (default) ROS 2 node: subscribe to the bag's depth, publish the coloured cloud

  gt_error_cloud.py prepare --data .../real-test/d435 --scenes 000000014,000000018,000000019 \
      --out demo_bag/gt_sidecar.npz
  gt_error_cloud.py rank --data .../real-test/d435 --out results/gt_error_scene_ranking.csv
  gt_error_cloud.py preview --sidecar demo_bag/gt_sidecar.npz --out out/gt_preview
  ros2 launch limit_case_ros2 demo_bag.launch.py bag:=demo_bag gt:=true

Ranking rule (fixed before looking at any picture, independent of the filter):
  score = (number of wrong mask pixels) x (median of raw - GT over those pixels, in metres)
at the bag resolution. Many red points, sitting far behind the glass, score high.

The node matches each incoming depth frame to a sidecar scene by a CRC of the depth pixels, so
it needs no scene index in the bag. Topics: /demo/gt_error_points (the coloured raw cloud) and
/demo/gt_surface_points (where the object surface really is, from GT, green).
"""
import argparse
import csv
import os
from pathlib import Path
import sys
import zlib

import numpy as np

MISSING, CORRECT, WRONG, OUTSIDE, UNKNOWN = 0, 1, 2, 3, 4
NAMES = {MISSING: 'missing', CORRECT: 'correct', WRONG: 'wrong', OUTSIDE: 'outside',
         UNKNOWN: 'unknown'}
# bucket -> RGB. Buckets without an entry are not shown.
COLOURS = {WRONG: (255, 0, 0), CORRECT: (255, 255, 255), OUTSIDE: (90, 90, 90)}
SURFACE_RGB = (0, 200, 110)
TOL_REL = 0.05
DEPTH_SUFFIX, GT_SUFFIX, MASK_SUFFIX = ('-transparent-depth-img.exr', '-opaque-depth-img.exr',
                                        '-mask.png')


# ------------------------------------------------------------------ core (numpy only)
def classify(raw_m, gt_m, mask, tol_rel=TOL_REL):
    """Return a uint8 bucket image (MISSING/CORRECT/WRONG/OUTSIDE/UNKNOWN)."""
    raw_m = np.asarray(raw_m, np.float32)
    gt_m = np.asarray(gt_m, np.float32)
    mask = np.asarray(mask, bool)
    present = np.isfinite(raw_m) & (raw_m > 0)
    gt_valid = np.isfinite(gt_m) & (gt_m > 0)
    with np.errstate(invalid='ignore'):
        within = np.abs(raw_m - gt_m) <= tol_rel * gt_m
    out = np.full(raw_m.shape, MISSING, np.uint8)
    out[present & ~mask] = OUTSIDE
    out[present & mask & ~gt_valid] = UNKNOWN
    out[present & mask & gt_valid & within] = CORRECT
    out[present & mask & gt_valid & ~within] = WRONG
    return out


def backproject(depth_m, fx, fy, cx, cy, sel):
    """XYZ (N, 3) float32 in the optical frame for the pixels where `sel` is true."""
    v, u = np.nonzero(sel)
    z = depth_m[v, u].astype(np.float32)
    return np.stack([(u - cx) * z / fx, (v - cy) * z / fy, z], axis=1).astype(np.float32)


def coloured_cloud(raw_m, buckets, fx, fy, cx, cy):
    """Return (xyz float32 (N, 3), rgb uint8 (N, 3)) of the raw cloud, buckets as colours."""
    xyz, rgb = [], []
    for code, colour in COLOURS.items():
        p = backproject(raw_m, fx, fy, cx, cy, buckets == code)
        xyz.append(p)
        rgb.append(np.tile(np.array(colour, np.uint8), (len(p), 1)))
    return np.concatenate(xyz), np.concatenate(rgb)


def error_stats(raw_m, gt_m, buckets):
    """Count the buckets and measure how far behind the true surface the wrong pixels read."""
    wrong = buckets == WRONG
    gap = (np.asarray(raw_m, np.float32) - np.asarray(gt_m, np.float32))[wrong]
    n = int(wrong.sum())
    med = float(np.median(gap)) if n else 0.0
    return {
        'wrong_px': n, 'correct_px': int((buckets == CORRECT).sum()),
        'missing_in_mask_px': 0,  # filled by the caller, which knows the mask
        'wrong_too_far_px': int((gap > 0).sum()),
        'gap_median_m': med, 'gap_p90_m': float(np.percentile(gap, 90)) if n else 0.0,
        'score': n * med}


def depth_crc(depth_u16):
    """CRC32 of a uint16 depth image; identifies which scene a bag frame belongs to."""
    return zlib.crc32(np.ascontiguousarray(depth_u16, dtype='<u2').tobytes())


def pack_rgb(rgb_u8):
    """Pack (N, 3) uint8 RGB into the float32 `rgb` field PointCloud2 / RViz expect."""
    c = rgb_u8.astype(np.uint32)
    return ((c[:, 0] << 16) | (c[:, 1] << 8) | c[:, 2]).astype('<u4').view('<f4')


def cloud_bytes(xyz, rgb_u8):
    """Serialise points as x, y, z, rgb (4 x float32, point_step 16)."""
    buf = np.empty((len(xyz), 4), '<f4')
    buf[:, :3] = xyz
    buf[:, 3] = pack_rgb(rgb_u8)
    return buf.tobytes()


# ------------------------------------------------------------------ ClearGrasp I/O
def _read_exr(path):
    os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')
    import cv2
    d = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if d is None:
        sys.exit(f'cannot read {path}')
    if d.ndim == 3:
        d = d[..., 0]
    d = d.astype(np.float32)
    d[~np.isfinite(d) | (d < 0)] = 0.0
    return d


def load_k(path):
    """Read fx, fy, cx, cy from ClearGrasp `camera_intrinsics.yaml`."""
    import re
    kv = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r'\s*(fx|fy|cx|cy)\s*:\s*([0-9.+-eE]+)', line)
        if m:
            kv[m.group(1)] = float(m.group(2))
    return kv['fx'], kv['fy'], kv['cx'], kv['cy']


def load_scene(data, sid, scale):
    """Load one scene exactly as clearGrasp_to_bag.py writes it (mm, nearest resize)."""
    import cv2
    base = str(Path(data) / sid)
    raw = _read_exr(base + DEPTH_SUFFIX)
    gt = _read_exr(base + GT_SUFFIX)
    mask = cv2.imread(base + MASK_SUFFIX, cv2.IMREAD_UNCHANGED)
    if mask is None:
        sys.exit(f'cannot read {base + MASK_SUFFIX}')
    if mask.ndim == 3:
        mask = mask[..., 0]
    raw_mm = np.clip(raw * 1000.0, 0, 65535).astype(np.uint16)
    if scale != 1.0:
        size = (int(raw_mm.shape[1] * scale), int(raw_mm.shape[0] * scale))
        raw_mm = cv2.resize(raw_mm, size, interpolation=cv2.INTER_NEAREST)
        gt = cv2.resize(gt, size, interpolation=cv2.INTER_NEAREST)
        mask = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
    return raw_mm, gt, mask > 0


def scene_ids(data, scenes):
    if scenes:
        return scenes.split(',')
    return sorted(p.name[:-len(DEPTH_SUFFIX)] for p in Path(data).glob('*' + DEPTH_SUFFIX))


def scene_stats(raw_mm, gt, mask):
    raw_m = raw_mm.astype(np.float32) / 1000.0
    b = classify(raw_m, gt, mask)
    s = error_stats(raw_m, gt, b)
    s['missing_in_mask_px'] = int((mask & (b == MISSING) & (gt > 0)).sum())
    return s


# ------------------------------------------------------------------ sub-commands
def cmd_prepare(a):
    fx, fy, cx, cy = load_k(a.intrinsics or str(Path(a.data) / 'camera_intrinsics.yaml'))
    ids = scene_ids(a.data, a.scenes)
    raws, gts, masks = zip(*(load_scene(a.data, i, a.scale) for i in ids))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        a.out, ids=np.array(ids), raw_mm=np.stack(raws), gt_m=np.stack(gts),
        mask=np.stack(masks), crc=np.array([depth_crc(r) for r in raws], np.uint32),
        k=np.array([fx * a.scale, fy * a.scale, cx * a.scale, cy * a.scale], np.float64))
    print(f'wrote {a.out}: {len(ids)} scenes at {raws[0].shape[1]}x{raws[0].shape[0]}')


def cmd_rank(a):
    rows = []
    for sid in scene_ids(a.data, a.scenes):
        raw_mm, gt, mask = load_scene(a.data, sid, a.scale)
        rows.append(dict(scene=sid, resolution=f'{raw_mm.shape[1]}x{raw_mm.shape[0]}',
                         **scene_stats(raw_mm, gt, mask)))
    rows.sort(key=lambda r: -r['score'])
    for rank, r in enumerate(rows, 1):
        r['rank'] = rank
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"{r['rank']:2d} {r['scene']} wrong={r['wrong_px']:5d} "
              f"gap_med={r['gap_median_m']:.3f} m score={r['score']:.1f}")


def cmd_preview(a):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    z = np.load(a.sidecar)
    fx, fy, cx, cy = z['k']
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # (elev, azim, draw GT surface, title); axes are X = forward, Y = left, Z = up (body frame)
    views = ((30, -155, False, 'orbit view'),
             (0, -90, False, 'side view: camera to the left, depth to the right'),
             (0, -90, True, 'side view + where the surface really is (green, from GT)'))
    for sid, raw_mm, gt, mask in zip(z['ids'], z['raw_mm'], z['gt_m'], z['mask']):
        raw_m = raw_mm.astype(np.float32) / 1000.0
        b = classify(raw_m, gt, mask)
        s = scene_stats(raw_mm, gt, mask)

        def body(depth, sel, step=1):
            p = backproject(depth, fx, fy, cx, cy, sel)[::step]
            return p[:, 2], -p[:, 0], -p[:, 1]

        obj = np.stack(body(raw_m, (b == WRONG) | (b == CORRECT)), axis=1)
        centre = (obj.min(0) + obj.max(0)) / 2 if len(obj) else np.array([0.8, 0, 0])
        half = max(a.margin, float((obj.max(0) - obj.min(0)).max()) / 2 + 0.08) if len(obj) \
            else a.margin
        fig = plt.figure(figsize=(21, 7.5), facecolor='black')
        for i, (elev, azim, surface, title) in enumerate(views, 1):
            ax = fig.add_subplot(1, 3, i, projection='3d', facecolor='black')
            if surface:
                ax.scatter(*body(gt, mask & (gt > 0)), s=4, linewidths=0, depthshade=False,
                           c=[np.array(SURFACE_RGB) / 255.0])
            for code, size, step in ((OUTSIDE, 2, 1), (CORRECT, 9, 1), (WRONG, 9, 1)):
                ax.scatter(*body(raw_m, b == code, step), s=size, linewidths=0, depthshade=False,
                           c=[np.array(COLOURS[code]) / 255.0])
            ax.view_init(elev=elev, azim=azim)
            ax.set_box_aspect((1, 1, 1), zoom=1.5)
            for lim, c in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), centre):
                lim(c - half, c + half)
            ax.set_axis_off()
            ax.set_title(title, color='white', fontsize=11)
        fig.suptitle(
            f"scene {sid}: {s['wrong_px']} wrong (red), {s['correct_px']} correct (white), "
            f"median gap {100 * s['gap_median_m']:.1f} cm behind the true surface",
            color='white', fontsize=13)
        fig.subplots_adjust(left=0, right=1, bottom=0, top=0.93, wspace=0)
        path = out / f'{sid}.png'
        fig.savefig(path, dpi=100, facecolor='black')
        plt.close(fig)
        print(f'wrote {path}')


def cmd_node(a, ros_args):
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import Image, PointCloud2, PointField

    class GtErrorCloud(Node):

        def __init__(self):
            super().__init__('gt_error_cloud')
            path = self.declare_parameter('gt_file', a.sidecar or '').value
            if not path or not os.path.exists(path):
                raise SystemExit(f'gt_error_cloud: sidecar not found: "{path}" '
                                 '(make it with `gt_error_cloud.py prepare`)')
            z = np.load(path)
            self.k = [float(v) for v in z['k']]
            self.scenes = {}
            for sid, raw_mm, gt, mask, crc in zip(z['ids'], z['raw_mm'], z['gt_m'], z['mask'],
                                                  z['crc']):
                self.scenes[int(crc)] = (str(sid), self.build(raw_mm, gt, mask))
            self.pub = self.create_publisher(PointCloud2, '/demo/gt_error_points', 2)
            self.pub_surf = self.create_publisher(PointCloud2, '/demo/gt_surface_points', 2)
            self.create_subscription(Image, 'depth/image', self.on_depth, 5)
            self.last, self.warned = None, False
            self.get_logger().info(f'loaded {len(self.scenes)} scenes from {path}')

        def build(self, raw_mm, gt, mask):
            raw_m = raw_mm.astype(np.float32) / 1000.0
            b = classify(raw_m, gt, mask)
            xyz, rgb = coloured_cloud(raw_m, b, *self.k)
            sxyz = backproject(gt, *self.k, mask & (gt > 0))
            srgb = np.tile(np.array(SURFACE_RGB, np.uint8), (len(sxyz), 1))
            return (len(xyz), cloud_bytes(xyz, rgb)), (len(sxyz), cloud_bytes(sxyz, srgb))

        def msg(self, header, n, data):
            m = PointCloud2()
            m.header = header
            m.height, m.width = 1, n
            m.fields = [PointField(name=name, offset=4 * i, datatype=PointField.FLOAT32, count=1)
                        for i, name in enumerate(('x', 'y', 'z', 'rgb'))]
            m.is_bigendian, m.point_step, m.row_step, m.is_dense = False, 16, 16 * n, True
            m.data = data
            return m

        def on_depth(self, img):
            if img.encoding != '16UC1':
                if not self.warned:
                    self.get_logger().warn(f'expected 16UC1 depth, got {img.encoding}')
                    self.warned = True
                return
            hit = self.scenes.get(zlib.crc32(bytes(img.data)))
            if hit is None:
                if not self.warned:
                    self.get_logger().warn('depth frame matches no sidecar scene; is this the '
                                           'bag the sidecar was made for?')
                    self.warned = True
                return
            sid, (cloud, surf) = hit
            if sid != self.last:
                self.get_logger().info(f'scene {sid}')
                self.last = sid
            self.pub.publish(self.msg(img.header, *cloud))
            self.pub_surf.publish(self.msg(img.header, *surf))

    rclpy.init(args=ros_args)
    node = GtErrorCloud()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ros_args = None
    if '--ros-args' in argv:  # everything from --ros-args on belongs to rclpy
        i = argv.index('--ros-args')
        argv, ros_args = argv[:i], argv[i:]
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')

    def data_args(p):
        p.add_argument('--data', required=True, help='ClearGrasp folder, e.g. .../real-test/d435')
        p.add_argument('--scenes', default=None, help='comma-separated scene ids (default: all)')
        p.add_argument('--scale', type=float, default=0.5,
                       help='resize factor; must equal the one the bag was written with')
        p.add_argument('--out', required=True)

    p = sub.add_parser('prepare')
    data_args(p)
    p.add_argument('--intrinsics', default=None, help='default: <data>/camera_intrinsics.yaml')
    p = sub.add_parser('rank')
    data_args(p)
    p = sub.add_parser('preview')
    p.add_argument('--sidecar', required=True)
    p.add_argument('--out', default='out/gt_preview')
    p.add_argument('--margin', type=float, default=0.2,
                   help='minimum half-width of the view around the objects, metres')
    p = sub.add_parser('node')
    p.add_argument('--sidecar', default=None, help='or the ROS parameter gt_file')
    a = ap.parse_args(argv)
    if a.cmd in (None, 'node'):
        if a.cmd is None:
            a.sidecar = None
        return cmd_node(a, ros_args)
    return {'prepare': cmd_prepare, 'rank': cmd_rank, 'preview': cmd_preview}[a.cmd](a)


if __name__ == '__main__':
    main()
