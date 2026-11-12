# Offscreen renderer for scripts/render_gt_clip.py (PyVista on a virtual X display, software OpenGL).
# Built and run by tools/render_gt_clip.sh; the repository is mounted at run time, nothing is copied in.
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb libgl1 libgl1-mesa-dri libxrender1 libxext6 libx11-6 ffmpeg fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy==2.5.4 pillow==13.0.0 pyvista==0.49.2 vtk==9.7.2
ENV LIBGL_ALWAYS_SOFTWARE=1 PYVISTA_OFF_SCREEN=true DISPLAY=:99
WORKDIR /repo
# Xvfb is started by hand: xvfb-run waits for a signal it never gets when it runs as PID 1.
ENTRYPOINT ["/bin/sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp >/dev/null 2>&1 & sleep 2; exec python3 scripts/render_gt_clip.py \"$@\"", "render"]
