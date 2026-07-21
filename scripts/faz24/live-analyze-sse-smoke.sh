#!/usr/bin/env bash
# Faz 24 İ5 — canlı-analiz SSE end-to-end smoke.
#
# Verifies the full chain landed in İ2-İ4:
#   1. Subscribe to meeting-ai `GET /analyze/live/stream/{meeting_id}` (SSE)
#   2. Fire `POST /analyze/live` with a fresh meeting_id + a small transcript
#   3. Assert an `event: analysis` frame lands on the SSE stream carrying
#      `"is_partial": true` and the version we published
#
# Not a replacement for attended desktop smoke (Zeynep's Windows viewer);
# this proves the SERVER-SIDE chain works so a viewer regression can be
# isolated to the client. Run this against test cluster (meeting-ai
# bridge service or direct port-forward) before asking Zeynep to smoke
# the desktop paneli.
#
# Usage:
#   MEETING_AI_URL=http://localhost:8400 ./live-analyze-sse-smoke.sh
#
# Optional env:
#   MEETING_ID     — override the UUID (default: uuidgen)
#   SEGMENT_SEQ    — override the version (default: 42)
#   TIMEOUT_SEC    — SSE subscribe window (default: 5)
#   AUTH_HEADER    — full `Authorization: Bearer …` value (default: unset)

set -euo pipefail

BASE_URL="${MEETING_AI_URL:-http://localhost:8400}"
MEETING_ID="${MEETING_ID:-$(uuidgen | tr 'A-Z' 'a-z')}"
SEGMENT_SEQ="${SEGMENT_SEQ:-42}"
TIMEOUT_SEC="${TIMEOUT_SEC:-5}"
AUTH_HEADER="${AUTH_HEADER:-}"

TMPDIR="${TMPDIR:-/tmp}"
SSE_OUT="${TMPDIR}/faz24-sse-smoke-${MEETING_ID}.out"
: > "${SSE_OUT}"

cleanup() {
    local sse_pid="${1:-}"
    if [[ -n "${sse_pid}" ]]; then
        kill -TERM "${sse_pid}" 2>/dev/null || true
        # Wait a short beat for curl to flush its buffer before we grep.
        sleep 0.5
        # Best-effort kill in case TERM was ignored (curl in the middle of a read).
        kill -KILL "${sse_pid}" 2>/dev/null || true
    fi
    rm -f "${SSE_OUT}"
}

echo "==> Faz 24 live-analyze SSE smoke"
echo "    meeting-ai base: ${BASE_URL}"
echo "    meeting_id:      ${MEETING_ID}"
echo "    segment_seq:     ${SEGMENT_SEQ}"
echo "    timeout:         ${TIMEOUT_SEC}s"
echo

echo "--- 1/3 subscribe SSE (background) ---"
CURL_ARGS=(
    --silent --show-error
    --no-buffer
    --max-time "${TIMEOUT_SEC}"
    -H "Accept: text/event-stream"
    -H "Cache-Control: no-cache"
)
if [[ -n "${AUTH_HEADER}" ]]; then
    CURL_ARGS+=(-H "${AUTH_HEADER}")
fi
curl "${CURL_ARGS[@]}" \
    "${BASE_URL%/}/analyze/live/stream/${MEETING_ID}" \
    > "${SSE_OUT}" 2>&1 &
SSE_PID=$!
trap "cleanup ${SSE_PID}" EXIT

# Give the SSE handshake a moment so the subscriber is registered with the
# hub BEFORE the publish below. Otherwise the publish has zero subscribers
# and the smoke fails on a race rather than a real regression.
sleep 1

echo "--- 2/3 POST /analyze/live ---"
PUBLISH_BODY=$(cat <<JSON
{
  "transcript": "Faz 24 live-analyze SSE smoke — smoke koşumu.",
  "meeting_id": "${MEETING_ID}",
  "segment_seq": ${SEGMENT_SEQ}
}
JSON
)

PUBLISH_ARGS=(--silent --show-error -X POST -H "Content-Type: application/json")
if [[ -n "${AUTH_HEADER}" ]]; then
    PUBLISH_ARGS+=(-H "${AUTH_HEADER}")
fi
PUBLISH_STATUS=$(curl "${PUBLISH_ARGS[@]}" \
    -o "${TMPDIR}/faz24-publish-out.json" \
    -w "%{http_code}" \
    --data "${PUBLISH_BODY}" \
    "${BASE_URL%/}/analyze/live")

if [[ "${PUBLISH_STATUS}" != "200" ]]; then
    echo "FAIL: /analyze/live returned ${PUBLISH_STATUS}"
    cat "${TMPDIR}/faz24-publish-out.json"
    exit 1
fi
echo "    /analyze/live returned 200"

echo "--- 3/3 wait for SSE frame ---"
# Poll the sink file until we see the expected pin or the SSE curl times out.
DEADLINE=$(( $(date +%s) + TIMEOUT_SEC ))
FRAME_SEEN=0
VERSION_SEEN=0
while (( $(date +%s) < DEADLINE )); do
    if grep -q '^event: analysis$' "${SSE_OUT}" && \
       grep -q '"is_partial": true' "${SSE_OUT}"; then
        FRAME_SEEN=1
    fi
    if grep -q "\"version\": ${SEGMENT_SEQ}" "${SSE_OUT}"; then
        VERSION_SEEN=1
    fi
    if (( FRAME_SEEN && VERSION_SEEN )); then
        break
    fi
    sleep 0.2
done

if (( FRAME_SEEN && VERSION_SEEN )); then
    echo
    echo "PASS: SSE delivered an event: analysis frame with is_partial=true and version=${SEGMENT_SEQ}"
    echo
    echo "Frames received:"
    grep -E '^(event|data|:)' "${SSE_OUT}" | head -30 || true
    exit 0
fi

echo
echo "FAIL: expected pins missing from SSE output"
echo "    frame_seen=${FRAME_SEEN} (event: analysis + is_partial=true)"
echo "    version_seen=${VERSION_SEEN} (\"version\": ${SEGMENT_SEQ})"
echo
echo "Raw SSE capture:"
cat "${SSE_OUT}" || true
exit 1
