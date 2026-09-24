#!/usr/bin/env bash
# Reopen a persisted meeting analysis in a real browser (gitops#3807 reboot acceptance).
#
# The canonical synthetic recording chain (faz24-platform-desktop-token-evidence
# with Speechmatics + require_live_analysis) proves the durable result over the
# API. This journey reopens that exact meeting in the product UI: route-scoped
# KC login -> /admin/meetings/<MEETING_ID> -> the intelligence result loads
# (HTTP 200) and the summary, decisions and actions render with exactly the
# durable counts. Evidence is counts and masked paths only; no analysis or
# transcript text is recorded. Same substrate as
# meeting-assignee-picker-browser-smoke.sh: pinned Playwright image, secrets on
# 0600 file mounts only, evidence dir, fail-closed on page errors.
set -euo pipefail

BASE_URL="${BASE_URL:-https://testai.acik.com}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_JSON="${VAULT_INIT_JSON:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
PERSONA_VAULT_PATH="${PERSONA_VAULT_PATH:?PERSONA_VAULT_PATH is required}"
PERSONA_PASSWORD_FIELD="${PERSONA_PASSWORD_FIELD:-persona_password}"
PERSONA_USERNAME="${PERSONA_USERNAME:?PERSONA_USERNAME is required}"
MEETING_ID="${MEETING_ID:?MEETING_ID is required}"
EXPECT_DECISIONS="${EXPECT_DECISIONS:?EXPECT_DECISIONS is required}"
EXPECT_ACTIONS="${EXPECT_ACTIONS:?EXPECT_ACTIONS is required}"
EVIDENCE_DIR="${EVIDENCE_DIR:?EVIDENCE_DIR is required}"
# Same pinned Playwright runtime as the fullats, schema-explorer and picker lanes.
PLAYWRIGHT_VERSION="1.60.0"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright@sha256:83192064c7510f7ee73dd63dc5f22a5e01a92c81a2e6a9c715d9e3fe55471fd9"
PLAYWRIGHT_INTEGRITY="sha512-hheHdokM8cdqCb0lcE3s+zT4t4W+vvjpGxsZlDnikarzx8tSzMebh3UiFtgqwFwnTnjYQcsyMF8ei2mCO/tpeA=="
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

[[ "$MEETING_ID" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] \
  || { echo "FATAL: MEETING_ID must be a lowercase UUID" >&2; exit 1; }
[[ "$EXPECT_DECISIONS" =~ ^[0-9]{1,3}$ && "$EXPECT_ACTIONS" =~ ^[0-9]{1,3}$ ]] \
  || { echo "FATAL: expected counts must be small integers" >&2; exit 1; }
mkdir -p "$EVIDENCE_DIR"
[[ -r "$VAULT_INIT_JSON" ]] || { echo "FATAL: vault init file unreadable" >&2; exit 1; }
docker inspect "$VAULT_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -qx true \
  || { echo "FATAL: TEST Vault container is not running" >&2; exit 1; }

SECRET_DIR="$(mktemp -d)"
trap 'rm -rf "$SECRET_DIR"' EXIT
chmod 700 "$SECRET_DIR"
read_vault_field() {
  python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_JSON" |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv get -field="$1" "$2"
    ' sh "$1" "$2"
}
read_vault_field "$PERSONA_PASSWORD_FIELD" "$PERSONA_VAULT_PATH" > "$SECRET_DIR/persona.password"
[[ -s "$SECRET_DIR/persona.password" ]] || { echo "FATAL: persona alanı okunamadı" >&2; exit 1; }
chmod 600 "$SECRET_DIR/persona.password"

echo "Browser reopen: persona=$PERSONA_USERNAME meeting=${MEETING_ID:0:8} base=$BASE_URL"
docker run --rm --ipc=host --network host \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
  -e NPM_CONFIG_CACHE=/tmp/npm-cache \
  -e NODE_PATH=/tmp/ma-pw/node_modules \
  -e BASE_URL="$BASE_URL" \
  -e PERSONA_USERNAME="$PERSONA_USERNAME" \
  -e PERSONA_PASSWORD_FILE=/run/secrets/persona.password \
  -e MEETING_ID="$MEETING_ID" \
  -e EXPECT_DECISIONS="$EXPECT_DECISIONS" \
  -e EXPECT_ACTIONS="$EXPECT_ACTIONS" \
  -e EVIDENCE_DIR=/evidence \
  -e PLAYWRIGHT_VERSION="$PLAYWRIGHT_VERSION" \
  -e PLAYWRIGHT_INTEGRITY="$PLAYWRIGHT_INTEGRITY" \
  -v "$REPO_ROOT:/work:ro" \
  -v "$SECRET_DIR:/run/secrets:ro" \
  -v "$EVIDENCE_DIR:/evidence" \
  -w /work \
  "$PLAYWRIGHT_IMAGE" bash -ceu '
    npm install --prefix /tmp/ma-pw --ignore-scripts --no-audit --no-fund --package-lock \
      "playwright@$PLAYWRIGHT_VERSION" >/dev/null
    node - <<'"'"'NODE'"'"'
const fs = require("fs");
const lock = JSON.parse(fs.readFileSync("/tmp/ma-pw/package-lock.json", "utf8"));
const pw = lock.packages["node_modules/playwright"];
if (pw?.version !== process.env.PLAYWRIGHT_VERSION || pw?.integrity !== process.env.PLAYWRIGHT_INTEGRITY) process.exit(31);
NODE
    node scripts/acceptance/meeting-analysis-reopen-browser-smoke.cjs
  '
