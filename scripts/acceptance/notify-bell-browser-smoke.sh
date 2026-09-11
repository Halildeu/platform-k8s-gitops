#!/usr/bin/env bash
# Platform shell notification bell — real browser journey (ES-301b, platform-backend#1153).
#
# KC login on testai as a TEST persona (default ethics-compliance-test, org …0003) -> the
# shell's own GET /api/v1/notify/inbox/me -> an item whose subject contains EXPECTED_SUBJECT
# (topic EXPECTED_TOPIC) -> bell open -> screenshots + journey.json. FORBIDDEN_SUBJECT, when
# set, must NOT appear (the other tier's item). Same substrate as the manager smoke: pinned
# Playwright image, persona password on a 0600 file mount, fail-closed.
set -euo pipefail

BASE_URL="${BASE_URL:-https://testai.acik.com}"
PERSONA="${PERSONA:-ethics-compliance-test}"
PERSONA_SECRET_DIR="${PERSONA_SECRET_DIR:-/srv/platform/secrets/faz35-test}"
EXPECTED_SUBJECT="${EXPECTED_SUBJECT:?EXPECTED_SUBJECT is required}"
EXPECTED_TOPIC="${EXPECTED_TOPIC:-ethics.case.escalation}"
FORBIDDEN_SUBJECT="${FORBIDDEN_SUBJECT:-}"
EVIDENCE_DIR="${EVIDENCE_DIR:?EVIDENCE_DIR is required}"

PLAYWRIGHT_VERSION="1.60.0"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright@sha256:83192064c7510f7ee73dd63dc5f22a5e01a92c81a2e6a9c715d9e3fe55471fd9"
PLAYWRIGHT_INTEGRITY="sha512-hheHdokM8cdqCb0lcE3s+zT4t4W+vvjpGxsZlDnikarzx8tSzMebh3UiFtgqwFwnTnjYQcsyMF8ei2mCO/tpeA=="

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$EVIDENCE_DIR"

SECRET_DIR="$(mktemp -d)"
trap 'rm -rf "$SECRET_DIR"' EXIT
chmod 700 "$SECRET_DIR"
# The persona files are root-owned 600; sudo is read-only here and the value
# goes straight to a file the container mounts, not through this shell's argv.
sudo cat "$PERSONA_SECRET_DIR/$PERSONA.password" > "$SECRET_DIR/persona.password"
[[ -s "$SECRET_DIR/persona.password" ]] || { echo "FATAL: persona password file empty/unreadable" >&2; exit 1; }
chmod 600 "$SECRET_DIR/persona.password"

echo "Browser smoke (bell): persona=$PERSONA base=$BASE_URL expected_subject=$EXPECTED_SUBJECT topic=$EXPECTED_TOPIC"
docker run --rm --ipc=host --network host \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
  -e NPM_CONFIG_CACHE=/tmp/npm-cache \
  -e NODE_PATH=/tmp/es-pw/node_modules \
  -e BASE_URL="$BASE_URL" \
  -e PERSONA_USERNAME="$PERSONA" \
  -e PERSONA_PASSWORD_FILE=/run/secrets/persona.password \
  -e EVIDENCE_DIR=/evidence \
  -e EXPECTED_SUBJECT="$EXPECTED_SUBJECT" \
  -e EXPECTED_TOPIC="$EXPECTED_TOPIC" \
  -e FORBIDDEN_SUBJECT="$FORBIDDEN_SUBJECT" \
  -e PLAYWRIGHT_VERSION="$PLAYWRIGHT_VERSION" \
  -e PLAYWRIGHT_INTEGRITY="$PLAYWRIGHT_INTEGRITY" \
  -v "$REPO_ROOT:/work:ro" \
  -v "$SECRET_DIR:/run/secrets:ro" \
  -v "$EVIDENCE_DIR:/evidence" \
  -w /work \
  "$PLAYWRIGHT_IMAGE" bash -ceu '
    npm install --prefix /tmp/es-pw --ignore-scripts --no-audit --no-fund --package-lock \
      "playwright@$PLAYWRIGHT_VERSION" >/dev/null
    node - <<'"'"'NODE'"'"'
const fs = require("fs");
const lock = JSON.parse(fs.readFileSync("/tmp/es-pw/package-lock.json", "utf8"));
const pw = lock.packages["node_modules/playwright"];
if (pw?.version !== process.env.PLAYWRIGHT_VERSION || pw?.integrity !== process.env.PLAYWRIGHT_INTEGRITY) process.exit(31);
NODE
    node scripts/acceptance/notify-bell-browser-smoke.cjs
  '

echo "PASS Etik Speak manager gerçek browser yolculuğu (ES-301)"
echo "EVIDENCE_DIR=$EVIDENCE_DIR"
