#!/bin/bash
# Get the demo bag (ClearGrasp-derived, Apache-2.0, see NOTICE inside): download the v0.1.0 release
# asset, check its SHA256 and unpack it to <dest>/demo_bag/.
#   scripts/fetch_demo_bag.sh                      download into ./demo_bag
#   scripts/fetch_demo_bag.sh --dest ~/data        download into ~/data/demo_bag
#   scripts/fetch_demo_bag.sh --local demo_bag.tar.gz   use an archive you already have
set -euo pipefail
VERSION=v0.1.0
URL=https://github.com/limit-case/ros2/releases/download/$VERSION/demo_bag.tar.gz
SHA256=7a7a2e563c72bf473c42d3e7d503c51895708b843cbe32c4342c7cb5bae7edb3
DEST=.
LOCAL=
while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST=$2; shift 2 ;;
    --local) LOCAL=$2; shift 2 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1 (see --help)" >&2; exit 2 ;;
  esac
done
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
if [ -n "$LOCAL" ]; then
  [ -f "$LOCAL" ] || { echo "no such file: $LOCAL" >&2; exit 1; }
  ARCHIVE=$LOCAL
else
  ARCHIVE=$TMP/demo_bag.tar.gz
  echo "Downloading $URL"
  if command -v curl >/dev/null; then
    curl -fL --retry 3 -o "$ARCHIVE" "$URL"
  elif command -v wget >/dev/null; then
    wget -O "$ARCHIVE" "$URL"
  else
    python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$URL" "$ARCHIVE"
  fi
fi
if command -v sha256sum >/dev/null; then
  GOT=$(sha256sum "$ARCHIVE" | cut -d' ' -f1)
else
  GOT=$(shasum -a 256 "$ARCHIVE" | cut -d' ' -f1)
fi
if [ "$GOT" != "$SHA256" ]; then
  echo "SHA256 mismatch for $ARCHIVE" >&2
  echo "  expected $SHA256" >&2
  echo "  got      $GOT" >&2
  exit 1
fi
mkdir -p "$DEST"
tar -xzf "$ARCHIVE" -C "$DEST"
echo "OK: $(cd "$DEST" && pwd)/demo_bag (SHA256 verified)"
echo "Run: ros2 launch limit_case_ros2 demo_bag.launch.py bag:=$(cd "$DEST" && pwd)/demo_bag"
