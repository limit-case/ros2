# Recording the demo clip on a Mac (RViz in Docker, viewed in the browser)

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
3. Get the demo bag as `./demo_bag/` (a directory with `demo_bag.mcap` and `metadata.yaml`, 66 MiB): download it from
   the release, or rebuild it with the command at the bottom of `docs/demo_scenes.md`.

## Every time

1. Start the container (it loops the bag, so the clip can be any length):

   ```bash
   docker run --rm --name lcdemo -p 6080:6080 --shm-size=1g -v "$PWD/demo_bag:/bag:ro" limit-case-demo
   ```

   Wait about 20 s for `Open http://localhost:6080/...` and the RViz start-up lines.
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

## Headline clip: ground-truth error view (20 to 30 s)

This is the clip for the README and the launch. It shows the failure itself, not the filter: the raw cloud coloured
by ground truth. Red = glass pixels the camera got wrong (more than 5% off), white = glass pixels it got right, dim
grey = everything that is not glass. Missing pixels are simply absent.

Start the container with `gt:=true` appended (the bag folder must contain `gt_sidecar.npz`, see
`docs/demo_scenes.md`):

```bash
docker run --rm --name lcdemo -p 6080:6080 --shm-size=1g -v "$PWD/demo_bag:/bag:ro" limit-case-demo gt:=true
```

Judge the scenes first without RViz: `out/gt_preview/<scene>.png` (orbit view, side view, side view with the true
surface). Scene order in the loop: 14 (0 to 4 s), 18 (4 to 8 s), 19 (8 to 12 s). To hold one scene (14 or 18; 19 is weak),
toggle pause from a second terminal when it is on screen:

```bash
docker exec lcdemo bash -c '. /opt/ros/$ROS_DISTRO/setup.bash && ros2 service call /rosbag2_player/toggle_paused rosbag2_interfaces/srv/TogglePaused'
```

RViz opens on the **Orbit start** view. The **Views** panel (bottom left) has the two saved views; double-click
one to jump, or type the numbers into *Current View*.

| Take | Time | Do | Caption |
|---|---|---|---|
| 1. Camera's eye | 0 to 5 s | Hold the opening view on scene 14 or 18. Do not move | This is what the depth camera reported. Red = wrong |
| 2. Slow orbit | 5 to 15 s | Drag slowly left to right, about a quarter turn (Yaw 2.3 down to about 0.8), keep Pitch near 0.45 | The red points are not on the glass. They are behind it |
| 3. Side view | 15 to 22 s | Double-click **Side (depth gap)** (Yaw -1.57, Pitch 0.02, camera on the left, depth to the right). Hold | White: where the glass is. Red: where the camera said it was |
| 4. Truth on | 22 to 28 s | Still in the side view, tick **True surface from ground truth (green)** | Green = the real surface. The gap is the error |

Tips: one slow drag beats several short ones; let go of the mouse for a second at the start and end of every take so
the clip can be cut there. The median gap is about 4 cm, so stay zoomed in (Distance 0.6 to 0.8) for takes 3 and 4.
Do not show the filter in this clip.

## Optional second clip: the filter (follows `docs/video_script.md`)

Start the container without `gt:=true`.

| Time | Do | Say or caption |
|---|---|---|
| 0 to 8 s | Untick **Filtered** and **Suspected**. Only the grey raw cloud. Slowly orbit | Depth camera: confident, wrong |
| 8 to 16 s | Tick **Filtered** | Remove the bad pixels: glass becomes unknown space |
| 16 to 26 s | Tick **Suspected** | Publish the glass surface as an obstacle |

Be honest in the caption about what the red is. In these scenes a lot of it sits on the black case and the far wall
rather than the glass (see `docs/demo_scenes.md` and the README limitation); do not claim every red point is glass.

## Make the README GIF

Use the ground-truth clip (takes 2 to 4), not the filter clip. Save it as `docs/gt_error.gif`; the README has a
placeholder for it.

```bash
ffmpeg -i ~/Desktop/Screen\ Recording*.mov -ss 5 -t 12 -vf "fps=12,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" docs/gt_error.gif
ls -lh docs/gt_error.gif   # keep it under 5 MB; lower fps or scale if bigger
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
