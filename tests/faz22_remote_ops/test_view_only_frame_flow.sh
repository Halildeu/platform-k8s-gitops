#!/usr/bin/env bash
# Fixture tests for the canonical VIEW_ONLY broker frame-flow parser
# (scripts/faz22-remote-ops/lib-view-only-frame-flow.sh). Codex 019f559d S2 matrix:
# received == broker got >=2 real non-inert PNG frames (DELIVERED | DROPPED_NO_VIEWER);
# delivered == >=2 DELIVERED. Everything malformed/foreign fails closed.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/faz22-remote-ops/lib-view-only-frame-flow.sh
source "$REPO_ROOT/scripts/faz22-remote-ops/lib-view-only-frame-flow.sh"

SID="rb-viewonly-attended-TEST"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

frame() { # <seq> <bytes> <type> <disposition> [session]
  printf 'view-only frame: session=%s stream=op-x seq=%s bytes=%s type=%s disposition=%s ts=1\n' \
    "${5:-$SID}" "$1" "$2" "$3" "$4"
}

check() { # <name> <expect received:0|1> <expect delivered:0|1> <logfile>
  local name="$1" er="$2" ed="$3" log="$4" gr gd
  broker_log_has_received_frame_flow  "$log" "$SID"; gr=$?
  broker_log_has_delivered_frame_flow "$log" "$SID"; gd=$?
  if [ "$gr" = "$er" ] && [ "$gd" = "$ed" ]; then
    printf 'PASS  %s (received=%s delivered=%s)\n' "$name" "$gr" "$gd"; pass=$((pass+1))
  else
    printf 'FAIL  %s (received got=%s want=%s ; delivered got=%s want=%s)\n' "$name" "$gr" "$er" "$gd" "$ed"; fail=$((fail+1))
  fi
}

# 1. real DROPPED frames (the live #1580 bundle case) -> received PASS(0), delivered FAIL(1)
{ frame 0 90654 image/png DROPPED_NO_VIEWER; frame 1 90654 image/png DROPPED_NO_VIEWER; } > "$TMP/dropped.log"
check "dropped-no-viewer-2frames" 0 1 "$TMP/dropped.log"

# 2. delivered frames -> received PASS(0), delivered PASS(0)
{ frame 0 90654 image/png DELIVERED; frame 1 90654 image/png DELIVERED; } > "$TMP/delivered.log"
check "delivered-2frames" 0 0 "$TMP/delivered.log"

# 3. bytes=0 (inert) -> both FAIL(1)
{ frame 0 0 image/png DROPPED_NO_VIEWER; frame 1 0 image/png DROPPED_NO_VIEWER; } > "$TMP/zerobytes.log"
check "zero-bytes-inert" 1 1 "$TMP/zerobytes.log"

# 4. foreign session -> both FAIL(1)
{ frame 0 90654 image/png DROPPED_NO_VIEWER other-sid; frame 1 90654 image/png DROPPED_NO_VIEWER other-sid; } > "$TMP/foreign.log"
check "foreign-session" 1 1 "$TMP/foreign.log"

# 5. wrong media type -> both FAIL(1)
{ frame 0 90654 image/jpeg DROPPED_NO_VIEWER; frame 1 90654 image/jpeg DROPPED_NO_VIEWER; } > "$TMP/wrongtype.log"
check "wrong-media-type" 1 1 "$TMP/wrongtype.log"

# 6. unknown/error disposition -> both FAIL(1)
{ frame 0 90654 image/png POLICY_DROP; frame 1 90654 image/png ERROR; } > "$TMP/baddisp.log"
check "unknown-disposition" 1 1 "$TMP/baddisp.log"

# 7. only one seq (not >=2) -> both FAIL(1)
frame 0 90654 image/png DROPPED_NO_VIEWER > "$TMP/oneframe.log"
check "single-frame" 1 1 "$TMP/oneframe.log"

# 8. the literal word FRAME in unrelated text -> both FAIL(1)
printf 'some audit line mentioning FRAME and SCREEN_VIEW but not a real frame session=%s\n' "$SID" > "$TMP/textonly.log"
check "text-only-no-real-frame" 1 1 "$TMP/textonly.log"

echo "---"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
