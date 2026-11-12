#!/bin/bash
# Build the release assets into out/release/: demo_bag.tar.gz (demo_bag.mcap, metadata.yaml,
# gt_sidecar.npz, NOTICE) and SHA256SUMS. The archive is byte-reproducible (fixed order, times and
# owners), so its hash can be pinned in scripts/fetch_demo_bag.sh; this script checks that it is.
#   scripts/make_release_assets.sh [demo_bag_dir]
set -euo pipefail
cd "$(dirname "$0")/.."
BAG=${1:-demo_bag}
OUT=out/release
FILES="demo_bag.mcap metadata.yaml gt_sidecar.npz NOTICE"
for f in $FILES; do
  [ -f "$BAG/$f" ] || { echo "missing $BAG/$f" >&2; exit 1; }
done
cmp -s NOTICE "$BAG/NOTICE" || { echo "$BAG/NOTICE differs from ./NOTICE (cp NOTICE $BAG/)" >&2; exit 1; }
mkdir -p "$OUT"
python3 - "$BAG" "$OUT/demo_bag.tar.gz" $FILES <<'PY'
import gzip
import sys
import tarfile

bag, out, files = sys.argv[1], sys.argv[2], sys.argv[3:]
with open(out, 'wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as gz, \
        tarfile.open(fileobj=gz, mode='w', format=tarfile.USTAR_FORMAT) as tar:
    for name in sorted(files):
        info = tar.gettarinfo(f'{bag}/{name}', arcname=f'demo_bag/{name}')
        info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = 0, 0o644, 0, 0, '', ''
        with open(f'{bag}/{name}', 'rb') as f:
            tar.addfile(info, f)
PY
if command -v sha256sum >/dev/null; then SHA="sha256sum"; else SHA="shasum -a 256"; fi
(cd "$OUT" && $SHA demo_bag.tar.gz > SHA256SUMS && cat SHA256SUMS)
ls -lh "$OUT/demo_bag.tar.gz"
GOT=$(cut -d' ' -f1 "$OUT/SHA256SUMS")
WANT=$(sed -n 's/^SHA256=//p' scripts/fetch_demo_bag.sh)
if [ "$GOT" = "$WANT" ]; then
  echo "OK: hash matches scripts/fetch_demo_bag.sh"
else
  echo "MISMATCH: scripts/fetch_demo_bag.sh expects $WANT. Set SHA256=$GOT there and commit." >&2
  exit 1
fi
