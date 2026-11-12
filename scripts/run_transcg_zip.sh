#!/bin/bash
# Held-out v0.2 run (docs/v0.2_protocol.md), one downloaded TransCG zip at a time, so the dataset
# never has to be on disk as a whole. For every OFFICIAL TEST scene inside the zip that is not done
# yet: extract only that scene, run both methods on it, keep the counts, delete the extracted scene.
# Resumable: finished scenes are skipped (out/transcg/transcg_d435_test/done.log).
#
#   scripts/run_transcg_zip.sh ~/Downloads/transcg-data-2.zip          # then delete the zip yourself
#   scripts/run_transcg_zip.sh --dry-run ~/Downloads/transcg-data-2.zip   # list what would be done
#
# Scenes that are already extracted in the dataset folder (for example 5, 7, 8) are evaluated in
# place and NOT deleted. TransCG is CC BY-NC-SA 4.0: nothing from it goes into a commit.
# Needs: GLASSBENCH (default ~/glassbench) with its .venv and datasets/transcg/metadata.json
# (from transcg-info.zip), Docker, and FILTER_CLI_IMAGE (default lc-cli:head) holding filter_cli
# built from the frozen commit.
set -euo pipefail
cd "$(dirname "$0")/.."
DRY=0
if [ "${1:-}" = "--dry-run" ]; then DRY=1; shift; fi
ZIP=${1:?usage: run_transcg_zip.sh [--dry-run] <transcg-data-N.zip>}
GB=${GLASSBENCH:-$HOME/glassbench}
ROOT=$GB/datasets/transcg
PY=$GB/.venv/bin/python
IMAGE=${FILTER_CLI_IMAGE:-lc-cli:head}
NAME=transcg_d435_test
WORK=$PWD/out/transcg/$NAME/work
CLI="docker run --rm -v $WORK:$WORK $IMAGE /ws/install/limit_case_ros2/lib/limit_case_ros2/filter_cli"
[ -f "$ROOT/metadata.json" ] || { echo "missing $ROOT/metadata.json (transcg-info.zip)" >&2; exit 1; }
mkdir -p "$WORK"

TEST=$(python3 -c 'import json,sys; print(" ".join(map(str, json.load(open(sys.argv[1]))["test"])))' "$ROOT/metadata.json")
# scene folders in the zip, with whatever prefix the zip uses (e.g. "transcg/scene11/" or "scene11/")
IN_ZIP=$(unzip -Z1 "$ZIP" | sed -n 's#^\(.*/\)\{0,1\}scene\([0-9][0-9]*\)/.*#\2 \1#p' | sort -un)
[ -n "$IN_ZIP" ] || { echo "no scene folders found in $ZIP" >&2; exit 1; }
while read -r N PREFIX; do
  case " $TEST " in *" $N "*) ;; *) continue ;; esac            # official test scenes only
  if [ -f "out/transcg/$NAME/scenes/scene$N.json" ]; then echo "scene$N: done, skipped"; continue; fi
  if [ "$DRY" = 1 ]; then
    if [ -d "$ROOT/scene$N" ]; then echo "scene$N: already on disk, would run in place and keep it"
    else echo "scene$N: would extract ${PREFIX}scene$N/, run, delete"; fi
    continue
  fi
  if [ -d "$ROOT/scene$N" ]; then
    echo "scene$N: already in $ROOT, evaluated in place and kept"
    "$PY" scripts/eval_transcg.py --split test --allow-test --scenes "$N" --cli "$CLI"
    continue
  fi
  TMP=$(mktemp -d "$ROOT/.extract.XXXXXX")
  unzip -q "$ZIP" "${PREFIX}scene$N/*" -d "$TMP"
  mv "$TMP/${PREFIX}scene$N" "$ROOT/scene$N"
  rm -rf "$TMP"
  "$PY" scripts/eval_transcg.py --split test --allow-test --scenes "$N" --delete-scene-after --cli "$CLI"
done <<< "$IN_ZIP"
[ "$DRY" = 1 ] || "$PY" scripts/eval_transcg.py --split test --allow-test --scenes 0 --cli "$CLI" | tail -25
