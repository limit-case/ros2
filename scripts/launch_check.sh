#!/bin/bash
# Launch-day check for limit_case_ros2 v0.1.0. Run it once the repo is public.
#   scripts/launch_check.sh [--notes FILE]
# FILE defaults to out/release/release_notes_v0.1.0.md; if missing, the release body is read with gh.
# Prints PASS/FAIL per check; exit status is 1 if anything failed.
set -uo pipefail
REPO=limit-case/ros2
TAG=v0.1.0
ROOT=$(cd "$(dirname "$0")/.." && pwd)
NOTES=$ROOT/out/release/release_notes_v0.1.0.md
while [ $# -gt 0 ]; do
  case "$1" in
    --notes) NOTES=$2; shift 2 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FAILS=0
result() { # PASS|FAIL, name, detail
  [ "$1" = FAIL ] && FAILS=$((FAILS + 1))
  printf '%-4s  %s%s\n' "$1" "$2" "${3:+  ($3)}"
}
code() { # HTTP status of a URL (HEAD, then GET if HEAD is refused)
  local c
  c=$(curl -s -o /dev/null -m 20 -A launch-check -w '%{http_code}' -I "$1")
  case "$c" in 2??|3??) echo "$c"; return ;; esac
  curl -s -o /dev/null -m 20 -A launch-check -w '%{http_code}' "$1"
}
is_ok() { case "$1" in 2??|3??) return 0 ;; *) return 1 ;; esac; }

# 1. CI badge returns an image
BADGE=https://github.com/$REPO/actions/workflows/ci.yml/badge.svg
CT=$(curl -s -o /dev/null -m 20 -L -w '%{http_code} %{content_type}' "$BADGE")
case "$CT" in 200\ image/*) result PASS "CI badge is an image" ;; *) result FAIL "CI badge is an image" "$CT" ;; esac

# 2. release exists with both assets
ASSETS=$(gh release view "$TAG" -R "$REPO" --json assets --jq '.assets[].name' 2>/dev/null)
if [ -z "$ASSETS" ]; then
  result FAIL "release $TAG exists" "gh cannot see it"
else
  result PASS "release $TAG exists"
fi
for a in demo_bag.tar.gz SHA256SUMS; do
  if printf '%s\n' "$ASSETS" | grep -qx "$a"; then result PASS "release asset $a"; else result FAIL "release asset $a" "missing"; fi
done

# 3. fetch_demo_bag.sh downloads and the hash matches (the script itself checks the SHA256)
if "$ROOT/scripts/fetch_demo_bag.sh" --dest "$WORK/fetch" >"$WORK/fetch.log" 2>&1; then
  result PASS "fetch_demo_bag.sh downloads, SHA256 verified"
else
  result FAIL "fetch_demo_bag.sh downloads, SHA256 verified" "$(tail -n 1 "$WORK/fetch.log")"
fi
# 3b. the published SHA256SUMS agrees with the hash pinned in the script
PINNED=$(sed -n 's/^SHA256=//p' "$ROOT/scripts/fetch_demo_bag.sh")
PUB=$(curl -fsL -m 30 "https://github.com/$REPO/releases/download/$TAG/SHA256SUMS" 2>/dev/null | awk '/demo_bag.tar.gz/ {print $1}')
if [ -n "$PUB" ] && [ "$PUB" = "$PINNED" ]; then result PASS "SHA256SUMS matches pinned hash"; else result FAIL "SHA256SUMS matches pinned hash" "${PUB:-not downloadable}"; fi

# 4. README GIF raw URL loads
for ref in main "$TAG"; do
  U=https://raw.githubusercontent.com/$REPO/$ref/docs/media/gt_error.gif
  C=$(code "$U")
  if [ "$C" = 200 ]; then result PASS "GIF raw URL ($ref)"; else result FAIL "GIF raw URL ($ref)" "HTTP $C"; fi
done

# 5. every http(s) link in README.md and the release notes
if [ -f "$NOTES" ]; then cp "$NOTES" "$WORK/notes.md"; else gh release view "$TAG" -R "$REPO" --json body --jq .body >"$WORK/notes.md" 2>/dev/null; fi
cat "$ROOT/README.md" "$WORK/notes.md" \
  | grep -oE 'https?://[^][[:space:])>"'"'"'<`]+' | sed -E 's/[.,;:}]+$//' \
  | grep -vE '^https?://(localhost|127\.|0\.0\.0\.0)' | sort -u >"$WORK/links.txt"
N=0; BAD=0
while read -r u; do
  N=$((N + 1))
  c=$(code "$u")
  if ! is_ok "$c"; then BAD=$((BAD + 1)); result FAIL "link" "$u -> HTTP $c"; fi
done <"$WORK/links.txt"
[ "$BAD" -eq 0 ] && result PASS "all $N links in README and release notes return 2xx/3xx"

echo
if [ "$FAILS" -eq 0 ]; then echo "ALL PASS"; else echo "$FAILS FAILED"; exit 1; fi
