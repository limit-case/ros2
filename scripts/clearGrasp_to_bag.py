#!/usr/bin/env python3
r"""Convert ClearGrasp real scenes (RGB, raw depth, intrinsics JSON) to a rosbag2 .mcap at 5 Hz.

Pure Python via `rosbags` (pip install rosbags numpy opencv-python); no ROS install needed.
Publishes the RealSense topic names from readthis.md section 4:
  /camera/aligned_depth_to_color/image_raw (16UC1 mm)  /camera/aligned_depth_to_color/camera_info
  /camera/color/image_raw (rgb8)
Download ClearGrasp yourself (e.g. glassbench/datasets/cleargrasp-dataset-test-val). Defaults match
its real-test naming: <id>-transparent-depth-img.exr (float meters),
<id>-transparent-rgb-img.jpg, camera_intrinsics.yaml:
  clearGrasp_to_bag.py --data .../real-test/d435 \\
      --intrinsics .../real-test/d435/camera_intrinsics.yaml --out demo_bag
Frames are 1280x720; the 0.5 default scale keeps a bag well under 100 MB (a GitHub release
asset). Use --scenes to pick scene ids and --frames-per-scene to hold each static capture.
"""
import argparse
import inspect
import json
import os
from pathlib import Path
import re
import sys

os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from rosbags.rosbag2 import Writer  # noqa: E402
from rosbags.rosbag2.enums import CompressionFormat, CompressionMode  # noqa: E402
from rosbags.typesys import get_typestore, Stores  # noqa: E402

try:
    from rosbags.rosbag2 import StoragePlugin
except ImportError:  # older rosbags: mcap not selectable
    StoragePlugin = None

DEPTH_T, RGB_T = '/camera/aligned_depth_to_color/image_raw', '/camera/color/image_raw'
INFO_T = '/camera/aligned_depth_to_color/camera_info'
FRAME = 'camera_color_optical_frame'


def load_k(path):
    """Read fx, fy, cx, cy from ClearGrasp `camera_intrinsics.yaml` or JSON (fx/fy/cx/cy or K)."""
    text = Path(path).read_text()
    if path.endswith('.json'):
        j = json.loads(text)
        if 'K' in j:
            k = j['K']
            return float(k[0]), float(k[4]), float(k[2]), float(k[5])
        return float(j['fx']), float(j['fy']), float(j['cx']), float(j['cy'])
    kv = {}
    for line in text.splitlines():
        m = re.match(r'\s*(fx|fy|cx|cy)\s*:\s*([0-9.+-eE]+)', line)
        if m:
            kv[m.group(1)] = float(m.group(2))
    return kv['fx'], kv['fy'], kv['cx'], kv['cy']


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', required=True)
    ap.add_argument('--out', required=True, help='output bag directory (must not exist)')
    ap.add_argument('--depth-suffix', default='-transparent-depth-img.exr')
    ap.add_argument('--rgb-suffix', default='-transparent-rgb-img.jpg')
    ap.add_argument('--intrinsics', required=True,
                    help='camera_intrinsics.yaml next to the scenes')
    ap.add_argument('--metadata-version', type=int, default=8, choices=(8, 9),
                    help='rosbag2 metadata version; 8 is readable by Humble and Jazzy')
    ap.add_argument('--compress', choices=('none', 'file', 'message'), default='none',
                    help='zstd compression of the bag (rosbag2 reads it transparently)')
    ap.add_argument('--hz', type=float, default=5.0)
    ap.add_argument('--max-frames', type=int, default=60, help='max number of scenes')
    ap.add_argument('--scenes', default=None,
                    help='comma-separated scene ids (e.g. 000000003,000000010), in this order')
    ap.add_argument('--frames-per-scene', type=int, default=1,
                    help='repeat each static capture this many times at --hz')
    ap.add_argument('--stride', type=int, default=1, help='take every Nth scene')
    ap.add_argument('--scale', type=float, default=0.5,
                    help='resize factor (intrinsics scale too); ClearGrasp is 1280x720')
    a = ap.parse_args()

    fx, fy, cx, cy = load_k(a.intrinsics)
    depth_files = sorted(Path(a.data).rglob('*' + a.depth_suffix))
    if a.scenes:
        by_id = {p.name[:-len(a.depth_suffix)]: p for p in depth_files}
        ids = a.scenes.split(',')
        missing = [i for i in ids if i not in by_id]
        if missing:
            sys.exit(f'unknown scene ids: {missing}')
        depth_files = [by_id[i] for i in ids]
    else:
        depth_files = depth_files[::a.stride][:a.max_frames]
    if not depth_files:
        sys.exit('no depth files found')

    ts = get_typestore(Stores.ROS2_HUMBLE)
    T = ts.types
    Time, Header = T['builtin_interfaces/msg/Time'], T['std_msgs/msg/Header']
    Image, CameraInfo = T['sensor_msgs/msg/Image'], T['sensor_msgs/msg/CameraInfo']
    RegionOfInterest = T['sensor_msgs/msg/RegionOfInterest']
    kw = {'storage_plugin': StoragePlugin.MCAP} if StoragePlugin else {}
    if 'version' in inspect.signature(Writer.__init__).parameters:  # rosbags >= 0.10
        kw['version'] = a.metadata_version
    if not kw:
        print('warning: this rosbags version cannot write mcap; writing the default storage',
              file=sys.stderr)

    writer = Writer(a.out, **kw)
    if a.compress != 'none':
        mode = getattr(CompressionMode, a.compress.upper())
        writer.set_compression(mode, CompressionFormat.ZSTD)
    with writer as wr:
        cd = wr.add_connection(DEPTH_T, Image.__msgtype__, typestore=ts)
        cc = wr.add_connection(RGB_T, Image.__msgtype__, typestore=ts)
        ci = wr.add_connection(INFO_T, CameraInfo.__msgtype__, typestore=ts)
        n_out = 0
        for dp in depth_files:
            stem = dp.name[:-len(a.depth_suffix)]
            rp = dp.with_name(stem + a.rgb_suffix)
            d = cv2.imread(str(dp), cv2.IMREAD_UNCHANGED)
            rgb = cv2.imread(str(rp), cv2.IMREAD_COLOR)
            if d is None or rgb is None:
                print(f'skip {stem}: unreadable', file=sys.stderr)
                continue
            if d.ndim == 3:
                d = d[..., 0]
            # EXR meters -> mm
            d_mm = d.astype(np.float32) * (1000.0 if d.dtype != np.uint16 else 1.0)
            d_mm = np.clip(np.nan_to_num(d_mm, nan=0.0), 0, 65535).astype(np.uint16)
            if rgb.shape[:2] != d_mm.shape:
                rgb = cv2.resize(rgb, (d_mm.shape[1], d_mm.shape[0]))
            s = a.scale
            if s != 1.0:
                size = (int(d_mm.shape[1] * s), int(d_mm.shape[0] * s))
                d_mm = cv2.resize(d_mm, size, interpolation=cv2.INTER_NEAREST)
                rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
            h, w = d_mm.shape
            k = np.array([fx * s, 0, cx * s, 0, fy * s, cy * s, 0, 0, 1], dtype=np.float64)
            p = np.array([fx * s, 0, cx * s, 0, 0, fy * s, cy * s, 0, 0, 0, 1, 0],
                         dtype=np.float64)
            rgb_flat = np.ascontiguousarray(rgb[..., ::-1]).reshape(-1)
            depth_flat = np.frombuffer(d_mm.tobytes(), np.uint8)
            roi = RegionOfInterest(x_offset=0, y_offset=0, height=0, width=0, do_rectify=False)
            for _ in range(a.frames_per_scene):
                t_ns = int(n_out / a.hz * 1e9)
                n_out += 1
                hdr = Header(stamp=Time(sec=t_ns // 10**9, nanosec=t_ns % 10**9), frame_id=FRAME)
                wr.write(cd, t_ns, ts.serialize_cdr(Image(
                    header=hdr, height=h, width=w, encoding='16UC1', is_bigendian=0,
                    step=w * 2, data=depth_flat), Image.__msgtype__))
                wr.write(cc, t_ns, ts.serialize_cdr(Image(
                    header=hdr, height=h, width=w, encoding='rgb8', is_bigendian=0,
                    step=w * 3, data=rgb_flat), Image.__msgtype__))
                wr.write(ci, t_ns, ts.serialize_cdr(CameraInfo(
                    header=hdr, height=h, width=w, distortion_model='plumb_bob',
                    d=np.zeros(5, dtype=np.float64), k=k,
                    r=np.eye(3, dtype=np.float64).reshape(-1), p=p,
                    binning_x=0, binning_y=0, roi=roi), CameraInfo.__msgtype__))
    print(f'wrote {a.out} ({len(depth_files)} scenes, {n_out} frames at {a.hz} Hz)')


if __name__ == '__main__':
    main()
