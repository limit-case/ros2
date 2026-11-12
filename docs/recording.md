# The demo clips

## Headline clip and README GIF: one command, no RViz

```bash
scripts/fetch_demo_bag.sh      # once; or rebuild the bag, see docs/demo_scenes.md
tools/render_gt_clip.sh
```

This builds a small Docker image (`tools/render/Dockerfile`: PyVista on a virtual display, software OpenGL) and runs
`scripts/render_gt_clip.py` in it. It needs only `demo_bag/gt_sidecar.npz` and takes about 3 minutes on 2 CPUs.
The camera path is fixed, so every run gives the same clip. Outputs:

| File | What |
|---|---|
| `out/clip/gt_clip_1080p.mp4` | 26 s, 1920x1080, H.264: scene 18 then scene 14, 13 s each |
| `out/clip/frames/*.png` | four stills per scene (orbit start, orbit, side view, side view with the true surface) |
| `docs/media/gt_error.gif` | README GIF: 800 px wide, 12 fps, the last 9.5 s of scene 14 (committed; ClearGrasp, Apache-2.0) |

Per scene: 0 to 5 s slow orbit starting from the depth camera's own viewpoint; 5 to 7 s move to the side view (the
table edge-on, camera on the left, depth to the right); 7 to 9.5 s hold; 9.5 to 13 s the true surface from ground
truth fades in (green). Colours are those of `scripts/gt_error_cloud.py`: red = wrong, white = correct, dim grey = not
glass, missing not drawn.

Options go straight to the script, for example `tools/render_gt_clip.sh --scenes 18,14,15`,
`--caption "..."`, `--gif-start 3.5 --gif-duration 9.5` (cut scene 18 instead), or
`--gif-only` to cut a new GIF from the existing mp4. A quick look at half size:
`tools/render_gt_clip.sh --width 960 --height 540 --fps 10 --out out/clip_test --gif out/clip_test/test.gif`.

The rest of this page is the manual way (RViz, screen recording). Keep it as a fallback and for the filter clip.

# Recording by hand on a Mac (RViz in Docker, viewed in the browser)

RViz runs in a container with a virtual display; you look at it through noVNC in your browser and screen-record
the browser. No XQuartz and no GPU passthrough needed. (XQuartz was not used: its indirect GLX does not render
RViz point clouds reliably on Apple Silicon.)

## One-time setup

1. Docker Desktop > Settings > Resources: give it **4+ CPUs and 4+ GB memory**. RViz uses software OpenGL inside
   the container, so CPU is the limit. With the default 2 CPUs the clouds update at only about 1.5 Hz.
2. Build the image from the repo root (about 10 minutes the first time; native arm64 on Apple Silicon):

   ```bash
   docker build -f docker/Dockerfile.demo -t limit-case-demo .
   ```

   Use `--build-arg ROS_DISTRO=humble` for Humble. The default is Jazzy.
3. Get the demo bag as `./demo_bag/` (a directory with `demo_bag.mcap`, `metadata.yaml`, `gt_sidecar.npz` and `NOTICE`, 67 MiB): get it with
   `scripts/fetch_demo_bag.sh`, or rebuild it with the command at the bottom of `docs/demo_scenes.md`.

## Every time

1. Start the container (it loops the bag, so the clip can be any length):

   ```bash
   docker run --rm --name lcdemo -p 6080:6080 --shm-size=1g -v "$PWD/demo_bag:/bag:ro" limit-case-demo
   ```

   Wait about 20 s for `Open http://localhost:6080/...` and the RViz start-up lines.
   This plain command is only for checking the setup. For a recording, use the command of the clip you are making:
   `gt:=true` for the headline clip, `play_duration:=7.9` for the filter clip (it keeps scene 15 out).
2. Open <http://localhost:6080/vnc.html?autoconnect=true&resize=scale> in Chrome or Safari. You should see RViz
   with a **Displays** panel on the left and three clouds on the right. `resize=scale` fits the 1280x720 virtual
   screen to the window; make the browser window 16:9 (for example 1280x800 including browser chrome) so it
   is not letterboxed. Use full-screen (`Ctrl+Cmd+F`) for the cleanest frame.
3. Rehearse once with the checkboxes in the Displays panel (the names carry the colours: raw grey, filtered
   white, suspected obstacles red). Drag in the 3D view to orbit, scroll to zoom. Every scene lasts 4 s, the loop
   lasts 12 s.
4. Record: press `Cmd+Shift+5`, choose **Record Selected Portion**, drag over the noVNC canvas (not the
   browser toolbar), click **Record**. Stop with the menu-bar stop button (or `Cmd+Ctrl+Esc`). The `.mov` lands on the
   Desktop. 20 to 30 s is one and a half to two and a half loops.

## Fallback take list for the headline clip: ground-truth error view (20 to 30 s)

The automated render above replaces this; use it only if you want a hand-held take. It shows the failure itself, not the filter: the raw cloud coloured
by ground truth. Red = glass pixels the camera got wrong (more than 5% off), white = glass pixels it got right, dim
grey = everything that is not glass. Missing pixels are simply absent.

Start the container with `gt:=true` appended (the bag folder must contain `gt_sidecar.npz`, see
`docs/demo_scenes.md`):

```bash
docker run --rm --name lcdemo -p 6080:6080 --shm-size=1g -v "$PWD/demo_bag:/bag:ro" limit-case-demo gt:=true
```

Judge the scenes first without RViz: `out/gt_preview/<scene>.png` (orbit view, side view, side view with the true
surface). Scene order in the loop: 18 (0 to 4 s), 14 (4 to 8 s), 15 (8 to 12 s); all three work. To hold one scene,
toggle pause from a second terminal when it is on screen:

```bash
docker exec lcdemo bash -c '. /opt/ros/$ROS_DISTRO/setup.bash && ros2 service call /rosbag2_player/toggle_paused rosbag2_interfaces/srv/TogglePaused'
```

RViz opens on the **Orbit start** view. The **Views** panel (bottom left) has the two saved views; double-click
one to jump, or type the numbers into *Current View*.

| Take | Time | Do | Caption |
|---|---|---|---|
| 1. Camera's eye | 0 to 5 s | Hold the opening view on scene 14 (largest red patch) or 18 (most objects). Do not move | This is what the depth camera reported. Red = wrong |
| 2. Slow orbit | 5 to 15 s | Drag slowly left to right, about a quarter turn (Yaw 2.3 down to about 0.8), keep Pitch near 0.45 | The red points are not on the glass. They are behind it |
| 3. Side view | 15 to 22 s | Double-click **Side (depth gap)** (Yaw -1.57, Pitch 0.02, camera on the left, depth to the right). Hold | White: where the glass is. Red: where the camera said it was |
| 4. Truth on | 22 to 28 s | Still in the side view, tick **True surface from ground truth (green)** | Green = the real surface. The gap is the error |

Tips: one slow drag beats several short ones; let go of the mouse for a second at the start and end of every take so
the clip can be cut there. The median gap is about 4 cm, so stay zoomed in (Distance 0.6 to 0.8) for takes 3 and 4.
Do not show the filter in this clip.

## Optional second clip: the filter

Start the container without `gt:=true` and with `play_duration:=7.9`, so the loop holds only scenes 18 and 14
(8 s per loop):

```bash
docker run --rm --name lcdemo -p 6080:6080 --shm-size=1g -v "$PWD/demo_bag:/bag:ro" limit-case-demo play_duration:=7.9
```

**Never show the filter on scene 15.** The filter flags none of its wrong glass pixels (`docs/demo_scenes.md`), so
any red there is a false alarm and a caption about "caught glass" would be untrue. If a recording was made without
`play_duration` (or on Humble, where that option does not exist), cut out seconds 8 to 12 of every 12 s loop.

| Time | Do | Say or caption |
|---|---|---|
| 0 to 8 s | Untick **Filtered** and **Suspected**. Only the grey raw cloud. Slowly orbit | Depth camera: confident, wrong |
| 8 to 16 s | Tick **Filtered** | Remove the bad pixels: glass becomes unknown space |
| 16 to 26 s | Tick **Suspected** | Publish the glass surface as an obstacle |

Be honest in the caption about what the red is. In these scenes a lot of it sits on the black case and the far wall
rather than the glass (see `docs/demo_scenes.md` and the README limitation); do not claim every red point is glass.

## Make a GIF from a hand-recorded clip

`tools/render_gt_clip.sh` already writes the README GIF (`docs/media/gt_error.gif`). To cut one from your own
recording instead, use the ground-truth clip (takes 2 to 4), not the filter clip:

```bash
ffmpeg -i recording.mov -ss 5 -t 12 -vf "fps=12,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" docs/media/gt_error.gif
ls -lh docs/media/gt_error.gif   # keep it under 8 MB; lower fps or scale if bigger
```

## Troubleshooting

- **Blank or black page**: the container is still starting; reload after RViz prints its subscription lines.
  `docker logs lcdemo | tail` shows where it is.
- **`No rosbag2 at /bag`**: the `-v` path must be the *directory* containing `metadata.yaml`.
- **Choppy clouds**: raise Docker CPUs, or close other apps. RViz renders with Mesa llvmpipe in software.
- **Stop**: `Ctrl+C` in the terminal, or `docker stop lcdemo`.
- **Different resolution**: `-e SCREEN=1920x1080x24` (the saved RViz window geometry is 1280x720, so also
  maximise the RViz window).

## Alternative: XQuartz

Possible but not tested here: install XQuartz, enable *Allow connections from network clients*, run `xhost +localhost`,
then run an `ros:jazzy` image with `-e DISPLAY=host.docker.internal:0 -e LIBGL_ALWAYS_INDIRECT=1`. Expect black or
unstable 3D views on Apple Silicon. Prefer the noVNC path above.
