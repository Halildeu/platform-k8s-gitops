#!/usr/bin/env bash
# Etik Speak manager authenticated product-surface verify — ES-301 escalation
# (platform-backend#882, gitops#3623).
#
# Real browser journey on testai as a synthetic TEST-org staff persona
# (default ethics-manager-synthetic-test, org …0003): KC login -> /ethic/ case
# grid -> "SLA eskalasyonu" column -> sorted top row "Seviye N" -> case detail
# line. The persona password comes from the Faz 35 secret dir on the host and
# is handed to the container on a 0600 file mount — never argv, never a log.
#
# Same substrate as schema-explorer-browser-smoke.sh: pinned Playwright image,
# evidence dir, fail-closed on console errors and non-2xx ethics-service calls.
set -euo pipefail

BASE_URL="${BASE_URL:-https://testai.acik.com}"
PERSONA="${PERSONA:-ethics-manager-synthetic-test}"
PERSONA_SECRET_DIR="${PERSONA_SECRET_DIR:-/srv/platform/secrets/faz35-test}"
EXPECTED_LEVEL="${EXPECTED_LEVEL:-1}"
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

# Allowlists travel into the container only when the caller set them (an unset variable
# keeps the harness default; an explicitly empty one means "nothing is known noise").
ALLOWLIST_ARGS=()
[ -n "${CONSOLE_ERROR_ALLOWLIST+x}" ] && ALLOWLIST_ARGS+=(-e "CONSOLE_ERROR_ALLOWLIST=$CONSOLE_ERROR_ALLOWLIST")
[ -n "${NON2XX_ALLOWLIST+x}" ] && ALLOWLIST_ARGS+=(-e "NON2XX_ALLOWLIST=$NON2XX_ALLOWLIST")
echo "Browser smoke: persona=$PERSONA base=$BASE_URL expected_level>=$EXPECTED_LEVEL"
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
  -e EXPECTED_LEVEL="$EXPECTED_LEVEL" \
  "${ALLOWLIST_ARGS[@]}" \
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
    node scripts/acceptance/etik-speak-manager-browser-smoke.cjs
  '

echo "PASS Etik Speak manager gerçek browser yolculuğu (ES-301)"
echo "EVIDENCE_DIR=$EVIDENCE_DIR"
