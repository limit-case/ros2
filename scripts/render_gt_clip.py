#!/usr/bin/env python3
r"""Render the ground-truth error clip offscreen: no RViz, no screen recording, repeatable.

Reads the demo bag's sidecar (gt_sidecar.npz, ClearGrasp, Apache-2.0) and draws the RAW cloud with
the colours of gt_error_cloud.py: wrong = red, correct = white, outside the mask = dim grey,
missing = not shown, plus the true surface from ground truth in green.

Clip, per scene (default 18 then 14, 13 s each, 26 s in total):
  0.0 to  5.0 s  slow orbit, starting from the depth camera's own viewpoint
  5.0 to  7.0 s  move to the side view (table edge-on, camera on the left, depth to the right)
  7.0 to  7.5 s  hold the side view: the red points lie behind the glass
  7.5 to 13.0 s  the true surface fades in (green) and stays

README GIF (its own 8 s loop of one scene, default the last one, green shown in every frame):
  side view with the true surface (first frame, the poster), swing out to the orbit view and back.

Outputs: <out>/gt_clip_1080p.mp4 (H.264), <out>/frames/*.png (four stills per scene),
<out>/gt_gif_source.mp4, the GIF and <out>/gif_sheet.png (four frames of the GIF).

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

CAPTION = 'Red: depth the camera reported confidently. It is the table behind the glass.'
SOURCE = 'ClearGrasp D435, ground truth'
LEGEND = ('wrong (reads behind the glass)', 'correct', 'true glass surface (ground truth)',
          'not glass')
T_ORBIT, T_MOVE, T_SIDE, T_FADE, T_GREEN = 5.0, 2.0, 0.5, 1.0, 4.5
T_SCENE = T_ORBIT + T_MOVE + T_SIDE + T_FADE + T_GREEN
G_HOLD, G_SWING, G_END = 2.0, 2.5, 1.0  # GIF loop: hold, swing out, swing back, hold
T_GIF = G_HOLD + 2 * G_SWING + G_END
ORBIT_AZIM, SIDE_AZIM, ORBIT_ELEV, SIDE_ELEV = 55.0, 90.0, 22.0, 2.0
BAR_H = 84  # caption bar height at 1080p
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


def framing(extent, aspect):
    """Half-widths in metres of the orbit view and of the side view."""
    wide = max(0.20, float(max(extent[0], extent[1])) / 2.0 + 0.10)
    tight = max(0.13, float(extent[0]) / 2.0 + 0.07, (float(extent[2]) / 2.0 + 0.04) * aspect)
    return wide, tight


def shot(t, elev0, extent, aspect):
    """Clip state at scene time t: (azimuth deg, elevation deg, half-width, green opacity)."""
    wide, tight = framing(extent, aspect)
    if t < T_ORBIT:
        s = smooth(t / T_ORBIT)
        return (ORBIT_AZIM * s, elev0 + (ORBIT_ELEV - elev0) * s, wide, 0.0)
    t -= T_ORBIT
    if t < T_MOVE:
        s = smooth(t / T_MOVE)
        return (ORBIT_AZIM + (SIDE_AZIM - ORBIT_AZIM) * s,
                ORBIT_ELEV + (SIDE_ELEV - ORBIT_ELEV) * s, wide + (tight - wide) * s, 0.0)
    t -= T_MOVE + T_SIDE
    return (SIDE_AZIM, SIDE_ELEV, tight, smooth(t / T_FADE))


def gif_shot(t, elev0, extent, aspect):
    """GIF state at time t: starts and ends on the side view, green always shown."""
    wide, tight = framing(extent, aspect)
    t -= G_HOLD
    s = smooth(t / G_SWING) if t < G_SWING else 1.0 - smooth((t - G_SWING) / G_SWING)
    return (SIDE_AZIM + (ORBIT_AZIM - SIDE_AZIM) * s,
            SIDE_ELEV + (ORBIT_ELEV - SIDE_ELEV) * s, tight + (wide - tight) * s, 1.0)


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


def annotate(view, scene, colours, caption, scale):
    """Put the 3D view above a plain caption bar; scene label, data source and a small legend."""
    from PIL import Image, ImageDraw
    vh, w = view.shape[:2]
    bar = int(BAR_H * scale)
    im = Image.new('RGB', (w, vh + bar), (0, 0, 0))
    im.paste(Image.fromarray(view), (0, 0))
    d = ImageDraw.Draw(im)
    big, small = load_font(int(34 * scale)), load_font(int(24 * scale))
    d.line([0, vh, w, vh], fill=(60, 60, 60), width=1)
    d.text((w // 2, vh + bar // 2), caption, font=big, fill=(255, 255, 255), anchor='mm')
    grey = (200, 200, 200)
    d.text((int(28 * scale), int(22 * scale)), f'Scene {int(scene)}', font=small, fill=grey)
    d.text((int(28 * scale), int(54 * scale)), SOURCE, font=small, fill=grey)
    # legend, top right: one colour square and one line of text per layer
    sq, row = int(20 * scale), int(34 * scale)
    x0 = w - int(28 * scale) - sq - int(12 * scale) - int(max(d.textlength(t, font=small)
                                                               for t in LEGEND))
    pad = int(12 * scale)
    d.rectangle([x0 - pad, int(24 * scale) - pad, w, int(24 * scale) + len(LEGEND) * row],
                fill=(0, 0, 0))
    for n, (colour, text) in enumerate(zip(colours, LEGEND)):
        y = int(24 * scale) + n * row
        d.rectangle([x0, y, x0 + sq, y + sq], fill=tuple(colour))
        d.text((x0 + sq + int(12 * scale), y + sq // 2), text, font=small, fill=grey,
               anchor='lm')
    return np.asarray(im)


def encoder(path, w, h, fps, crf):
    return subprocess.Popen(
        ['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
         '-s', f'{w}x{h}', '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-preset', 'slow',
         '-crf', str(crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)],
        stdin=subprocess.PIPE)


def finish(enc, path):
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit(f'ffmpeg failed while encoding {path}')
    print(f'wrote {path}', flush=True)


def render(a):
    """Render the clip, the stills and the GIF source. Returns the path of the GIF source."""
    import pyvista as pv
    from PIL import Image
    g = load_gt_module()
    z = np.load(a.sidecar)
    fx, fy, cx, cy = (float(v) for v in z['k'])
    ids = [str(i) for i in z['ids']]
    w, h = a.width, a.height
    scale = h / 1080.0
    vh = h - int(BAR_H * scale)  # the 3D view sits above the caption bar
    out = Path(a.out)
    (out / 'frames').mkdir(parents=True, exist_ok=True)
    pl = pv.Plotter(off_screen=True, window_size=(w, vh), lighting='none')
    pl.set_background('black')
    pl.camera.parallel_projection = True  # a true side elevation: gaps are not foreshortened
    legend = (g.COLOURS[g.WRONG], g.COLOURS[g.CORRECT], g.SURFACE_RGB, g.COLOURS[g.OUTSIDE])

    def load(scene):
        """Put one scene into the plotter. Returns (scene id, frame, true-surface actor)."""
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
        return ids[i], frame, surface

    def draw(sid, frame, surface, state):
        azim, elev, half, green = state
        pos, focal, up, pscale = camera_pose(azim, elev, half, frame, w / vh)
        pl.camera.position, pl.camera.focal_point, pl.camera.up = pos, focal, up
        pl.camera.parallel_scale = pscale
        pl.camera.clipping_range = (0.01, 20.0)
        surface.SetVisibility(green > 0.0)
        surface.GetProperty().SetOpacity(green)
        pl.render()
        return annotate(pl.screenshot(return_img=True)[:, :, :3], sid, legend, a.caption, scale)

    mp4 = out / 'gt_clip_1080p.mp4'
    enc = encoder(mp4, w, h, a.fps, 18)
    stills = {0.0: 'orbit_start', T_ORBIT * 0.6: 'orbit', T_ORBIT + T_MOVE + 0.25: 'side',
              T_SCENE - 1.0: 'side_true_surface'}
    still_at = {int(round(t * a.fps)): name for t, name in stills.items()}
    scenes = a.scenes.split(',')
    for scene in scenes:
        sid, frame, surface = load(scene)
        for k in range(int(round(T_SCENE * a.fps))):
            img = draw(sid, frame, surface, shot(k / a.fps, frame[4], frame[5], w / vh))
            enc.stdin.write(np.ascontiguousarray(img).tobytes())
            if k in still_at:
                path = out / 'frames' / f'{sid}_{still_at[k]}.png'
                Image.fromarray(img).save(path)
                print(f'wrote {path}', flush=True)
    finish(enc, mp4)

    src = out / 'gt_gif_source.mp4'
    enc = encoder(src, w, h, a.gif_fps, 10)
    sid, frame, surface = load(a.gif_scene or scenes[-1])
    for k in range(int(round(T_GIF * a.gif_fps))):
        img = draw(sid, frame, surface, gif_shot(k / a.gif_fps, frame[4], frame[5], w / vh))
        enc.stdin.write(np.ascontiguousarray(img).tobytes())
    pl.close()
    finish(enc, src)
    return src


def make_gif(a, src):
    """Turn the GIF source into the README GIF and a four-frame contact sheet of it."""
    gif = Path(a.gif)
    gif.parent.mkdir(parents=True, exist_ok=True)
    vf = (f'scale={a.gif_width}:-1:flags=lanczos,split[x][y];'
          '[x]palettegen=max_colors=64:stats_mode=diff[p];[y][p]paletteuse=dither=none')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', str(src), '-vf', vf,
                    '-loop', '0', str(gif)], check=True)
    n = int(round(T_GIF * a.gif_fps))
    picks = '+'.join(f'eq(n,{k})' for k in (0, n // 3, 2 * n // 3, n - 1))
    sheet = Path(a.out) / 'gif_sheet.png'
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', str(gif), '-vf',
                    f"select='{picks}',tile=2x2", '-frames:v', '1', '-update', '1',
                    str(sheet)], check=True)
    size = gif.stat().st_size / 1e6
    print(f'wrote {gif} ({size:.1f} MB) and {sheet}')
    if size > 8.0:
        sys.exit('GIF is over 8 MB: lower --gif-fps or --gif-width')


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
    ap.add_argument('--gif-scene', default=None, help='scene of the GIF (default: the last one)')
    ap.add_argument('--gif-fps', type=int, default=10)
    ap.add_argument('--gif-width', type=int, default=800)
    ap.add_argument('--gif-only', action='store_true',
                    help='reuse <out>/gt_gif_source.mp4, only convert it to the GIF')
    a = ap.parse_args(argv)
    make_gif(a, Path(a.out) / 'gt_gif_source.mp4' if a.gif_only else render(a))


if __name__ == '__main__':
    main()
