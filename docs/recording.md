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

## Suggested take (follows `docs/video_script.md`)

| Time | Do | Say or caption |
|---|---|---|
| 0 to 8 s | Untick **Filtered** and **Suspected**. Only the grey raw cloud. Slowly orbit | Depth camera: confident, wrong |
| 8 to 16 s | Tick **Filtered** | Remove the bad pixels: glass becomes unknown space |
| 16 to 26 s | Tick **Suspected** | Publish the glass surface as an obstacle |

Be honest in the caption about what the red is. In these scenes a lot of it sits on the black case and the far wall
rather than the glass (see `docs/demo_scenes.md` and the README limitation); do not claim every red point is glass.

## Make the README GIF

```bash
ffmpeg -i ~/Desktop/Screen\ Recording*.mov -ss 0 -t 10 -vf "fps=12,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse" demo.gif
ls -lh demo.gif   # keep it under 5 MB; lower fps or scale if bigger
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
