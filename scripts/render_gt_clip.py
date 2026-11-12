#!/usr/bin/env python3
r"""Render the ground-truth error clip offscreen: no RViz, no screen recording, repeatable.

Reads the demo bag's sidecar (gt_sidecar.npz, ClearGrasp, Apache-2.0) and draws the RAW cloud with
the colours of gt_error_cloud.py: wrong = red, correct = white, outside the mask = dim grey,
missing = not shown. The true surface from ground truth (green) appears in the last shot.

Per scene (default 18 then 14, 13 s each, 26 s in total):
  0.0 to  5.0 s  slow orbit, starting from the depth camera's own viewpoint
  5.0 to  7.0 s  move to the side view (table edge-on, camera on the left, depth to the right)
  7.0 to  9.5 s  hold the side view: the red points lie behind the glass
  9.5 to 13.0 s  the true surface fades in (green)

Outputs: <out>/gt_clip_1080p.mp4 (H.264), the README GIF (a cut of the mp4) and a few PNG frames
in <out>/frames/ for a quick look.

Needs pyvista, numpy, pillow, ffmpeg and a display (Xvfb is enough). One command with Docker:
  tools/render_gt_clip.sh
or by hand inside any machine that has those:
  xvfb-run -a -s '-screen 0 1920x1080x24' scripts/render_gt_clip.py
"""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys

import numpy as np

CAPTION = 'Red: depth the camera reported confidently, but it is the wall behind the glass.'
CAPTION_GREEN = 'Green: where the glass surface really is (ground truth).'
SOURCE = 'ClearGrasp D435, ground truth'
T_ORBIT, T_MOVE, T_HOLD, T_FADE, T_GREEN = 5.0, 2.0, 2.5, 1.0, 2.5
T_SCENE = T_ORBIT + T_MOVE + T_HOLD + T_FADE + T_GREEN
ORBIT_AZIM, SIDE_AZIM, ORBIT_ELEV, SIDE_ELEV = 55.0, 90.0, 22.0, 2.0
BAR_H = 108  # caption bar height at 1080p
FONTS = ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         '/System/Library/Fonts/Supplemental/Arial.ttf')


def load_gt_module():
    """Import gt_error_cloud.py (same folder) for the bucket rules and the colours."""
    path = Path(__file__).resolve().parent / 'gt_error_cloud.py'
    spec = importlib.util.spec_from_file_location('gt_error_cloud', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def smooth(x):
    """Smoothstep easing, clamped to 0..1."""
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def unit(v):
    return v / np.linalg.norm(v)


def fit_plane(points, tries=300, tol=0.006, seed=0):
    """Dominant plane of `points`: seeded RANSAC (repeatable), then a least-squares refit.

    Returns the unit normal.
    """
    rng = np.random.default_rng(seed)
    pts = points[::max(1, len(points) // 20000)]
    best, best_count = None, -1
    for _ in range(tries):
        p0, p1, p2 = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(p1 - p0, p2 - p0)
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n /= norm
        count = int((np.abs((pts - p0) @ n) < tol).sum())
        if count > best_count:
            best, best_count = (p0, n), count
    p0, n = best
    inliers = points[np.abs((points - p0) @ n) < tol]
    return np.linalg.svd(inliers - inliers.mean(axis=0), full_matrices=False)[2][2]


def scene_frame(obj, outside, surface):
    """Table-aligned frame for one scene, from the cloud in the optical frame (camera at 0).

    Returns (focus, up, back, side, elev0, extent): `up` is the normal of the surface the objects
    stand on, `back` points from the objects towards the depth camera along that surface, `side`
    completes the frame, `elev0` is the camera's own elevation above the surface in degrees.
    """
    focus = (obj.min(axis=0) + obj.max(axis=0)) / 2.0
    radius = float(np.linalg.norm(obj.max(axis=0) - obj.min(axis=0))) / 2.0
    near = outside[np.linalg.norm(outside - focus, axis=1) < radius + 0.25]
    up = fit_plane(near if len(near) >= 200 else outside)
    to_camera = unit(-focus)
    if up @ to_camera < 0:
        up = -up
    back = unit(to_camera - (to_camera @ up) * up)
    side = np.cross(up, back)
    elev0 = float(np.degrees(np.arcsin(np.clip(to_camera @ up, -1.0, 1.0))))
    # frame the raw object points together with the true surface, which stands higher
    axes = np.stack([back, side, up], axis=1)
    local = (np.concatenate([obj, surface]) - focus) @ axes
    focus = focus + axes @ ((local.min(axis=0) + local.max(axis=0)) / 2.0)
    return focus, up, back, side, elev0, local.max(axis=0) - local.min(axis=0)


def shot(t, elev0, extent, aspect):
    """Camera and layer state at scene time t: (azimuth deg, elevation deg, half-width m, green)."""
    wide = max(0.20, float(max(extent[0], extent[1])) / 2.0 + 0.10)
    tight = max(0.13, float(extent[0]) / 2.0 + 0.07, (float(extent[2]) / 2.0 + 0.04) * aspect)
    if t < T_ORBIT:
        s = smooth(t / T_ORBIT)
        return (ORBIT_AZIM * s, elev0 + (ORBIT_ELEV - elev0) * s, wide, 0.0)
    t -= T_ORBIT
    if t < T_MOVE:
        s = smooth(t / T_MOVE)
        return (ORBIT_AZIM + (SIDE_AZIM - ORBIT_AZIM) * s,
                ORBIT_ELEV + (SIDE_ELEV - ORBIT_ELEV) * s, wide + (tight - wide) * s, 0.0)
    t -= T_MOVE + T_HOLD
    return (SIDE_AZIM, SIDE_ELEV, tight, smooth(t / T_FADE))


def camera_pose(azim, elev, half, frame, aspect):
    """Return (position, focal point, view-up, parallel scale): `half` m = half the image width."""
    focus, up, back, side = frame[:4]
    a, e = np.radians(azim), np.radians(elev)
    direction = np.cos(e) * (np.cos(a) * back + np.sin(a) * side) + np.sin(e) * up
    return focus + 3.0 * direction, focus, up, half / aspect


def load_font(size):
    from PIL import ImageFont
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def annotate(view, scene, green, caption, scale):
    """Put the 3D view above a plain caption bar; scene label and data source in small text."""
    from PIL import Image, ImageDraw
    vh, w = view.shape[:2]
    bar = int(BAR_H * scale)
    im = Image.new('RGB', (w, vh + bar), (0, 0, 0))
    im.paste(Image.fromarray(view), (0, 0))
    d = ImageDraw.Draw(im)
    big, small = load_font(int(34 * scale)), load_font(int(24 * scale))
    d.line([0, vh, w, vh], fill=(60, 60, 60), width=1)
    d.text((w // 2, vh + int(34 * scale)), caption, font=big, fill=(255, 255, 255), anchor='mm')
    grey = (200, 200, 200)
    d.text((int(28 * scale), int(22 * scale)), f'Scene {scene}', font=small, fill=grey)
    d.text((int(28 * scale), int(54 * scale)), SOURCE, font=small, fill=grey)
    if green > 0.0:
        c = tuple(int(v * green) for v in (0, 200, 110))
        d.text((w // 2, vh + int(80 * scale)), CAPTION_GREEN, font=load_font(int(29 * scale)),
               fill=c, anchor='mm')
    return np.asarray(im)


def render(a):
    import pyvista as pv
    g = load_gt_module()
    z = np.load(a.sidecar)
    fx, fy, cx, cy = (float(v) for v in z['k'])
    ids = [str(i) for i in z['ids']]
    w, h = a.width, a.height
    scale = h / 1080.0
    vh = h - int(BAR_H * scale)  # the 3D view sits above the caption bar
    out = Path(a.out)
    (out / 'frames').mkdir(parents=True, exist_ok=True)
    mp4 = out / 'gt_clip_1080p.mp4'
    enc = subprocess.Popen(
        ['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
         '-s', f'{w}x{h}', '-r', str(a.fps), '-i', '-', '-c:v', 'libx264', '-preset', 'slow',
         '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(mp4)],
        stdin=subprocess.PIPE)
    pl = pv.Plotter(off_screen=True, window_size=(w, vh), lighting='none')
    pl.set_background('black')
    pl.camera.parallel_projection = True  # a true side elevation: gaps are not foreshortened
    stills = {0.0: 'orbit_start', T_ORBIT * 0.6: 'orbit', T_ORBIT + T_MOVE + 1.0: 'side',
              T_SCENE - 1.0: 'side_true_surface'}
    n_scene = int(round(T_SCENE * a.fps))
    for scene in a.scenes.split(','):
        match = [i for i, sid in enumerate(ids) if sid.endswith(scene)]
        if not match:
            sys.exit(f'scene {scene} is not in {a.sidecar} (it has {", ".join(ids)})')
        i = match[0]
        raw = z['raw_mm'][i].astype(np.float32) / 1000.0
        gt, mask = z['gt_m'][i], z['mask'][i]
        b = g.classify(raw, gt, mask)

        def pts(depth, sel):
            return g.backproject(depth, fx, fy, cx, cy, sel)

        outside = pts(raw, b == g.OUTSIDE)
        true_surface = pts(gt, mask & (gt > 0))
        frame = scene_frame(pts(raw, (b == g.WRONG) | (b == g.CORRECT)), outside, true_surface)
        pl.clear_actors()
        layers = ((outside, g.COLOURS[g.OUTSIDE], 3.0), (pts(raw, b == g.CORRECT),
                  g.COLOURS[g.CORRECT], 6.0), (pts(raw, b == g.WRONG), g.COLOURS[g.WRONG], 6.0))
        for xyz, rgb, size in layers:
            if len(xyz):
                pl.add_points(xyz, color=[v / 255.0 for v in rgb], point_size=size * scale,
                              render_points_as_spheres=False, lighting=False)
        surface = pl.add_points(
            true_surface, color=[v / 255.0 for v in g.SURFACE_RGB],
            point_size=5.0 * scale, render_points_as_spheres=False, lighting=False)
        still_at = {int(round(t * a.fps)): name for t, name in stills.items()}
        for k in range(n_scene):
            azim, elev, half, green = shot(k / a.fps, frame[4], frame[5], w / vh)
            pos, focal, up, pscale = camera_pose(azim, elev, half, frame, w / vh)
            pl.camera.position, pl.camera.focal_point, pl.camera.up = pos, focal, up
            pl.camera.parallel_scale = pscale
            pl.camera.clipping_range = (0.01, 20.0)
            surface.SetVisibility(green > 0.0)
            surface.GetProperty().SetOpacity(green)
            pl.render()
            img = annotate(pl.screenshot(return_img=True)[:, :, :3], ids[i], green, a.caption,
                           scale)
            enc.stdin.write(np.ascontiguousarray(img).tobytes())
            if k in still_at:
                from PIL import Image
                path = out / 'frames' / f'{ids[i]}_{still_at[k]}.png'
                Image.fromarray(img).save(path)
                print(f'wrote {path}', flush=True)
        print(f'scene {ids[i]}: {n_scene} frames', flush=True)
    pl.close()
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit('ffmpeg failed while encoding the mp4')
    print(f'wrote {mp4}')
    return mp4


def make_gif(a, mp4):
    """Cut the strongest part (end of the orbit, side view, true surface) into the README GIF."""
    gif = Path(a.gif)
    gif.parent.mkdir(parents=True, exist_ok=True)
    vf = (f'fps={a.gif_fps},scale={a.gif_width}:-1:flags=lanczos,split[x][y];'
          '[x]palettegen=max_colors=64:stats_mode=diff[p];[y][p]paletteuse=dither=none')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-ss', str(a.gif_start),
                    '-t', str(a.gif_duration), '-i', str(mp4), '-vf', vf, '-loop', '0',
                    str(gif)], check=True)
    size = gif.stat().st_size / 1e6
    print(f'wrote {gif} ({size:.1f} MB)')
    if size > 8.0:
        sys.exit('GIF is over 8 MB: lower --gif-fps, --gif-width or --gif-duration')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sidecar', default='demo_bag/gt_sidecar.npz')
    ap.add_argument('--scenes', default='18,14', help='scene ids (or their endings), in order')
    ap.add_argument('--out', default='out/clip')
    ap.add_argument('--gif', default='docs/media/gt_error.gif')
    ap.add_argument('--caption', default=CAPTION)
    ap.add_argument('--width', type=int, default=1920)
    ap.add_argument('--height', type=int, default=1080)
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--gif-start', type=float, default=T_SCENE + T_ORBIT - 1.5,
                    help='start of the GIF cut in the mp4, seconds (default: second scene, '
                         'from the end of its orbit)')
    ap.add_argument('--gif-duration', type=float, default=T_SCENE - T_ORBIT + 1.5)
    ap.add_argument('--gif-fps', type=int, default=12)
    ap.add_argument('--gif-width', type=int, default=800)
    ap.add_argument('--gif-only', action='store_true', help='reuse the mp4, only cut the GIF')
    a = ap.parse_args(argv)
    mp4 = Path(a.out) / 'gt_clip_1080p.mp4' if a.gif_only else render(a)
    make_gif(a, mp4)


if __name__ == '__main__':
    main()
