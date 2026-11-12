#!/bin/bash
# One command: render the ground-truth error clip and the README GIF, offscreen, in Docker.
#   tools/render_gt_clip.sh [extra arguments for scripts/render_gt_clip.py]
# Needs ./demo_bag/gt_sidecar.npz (release asset; scripts/fetch_demo_bag.sh). Writes
# out/clip/gt_clip_1080p.mp4, out/clip/frames/*.png and docs/media/gt_error.gif.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f demo_bag/gt_sidecar.npz ]; then
  echo "demo_bag/gt_sidecar.npz not found. Get the demo bag first: scripts/fetch_demo_bag.sh" >&2
  exit 1
fi
docker build -q -t limit-case-render tools/render
docker run --rm -v "$PWD:/repo" limit-case-render "$@"
