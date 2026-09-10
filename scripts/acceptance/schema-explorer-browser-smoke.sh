#!/usr/bin/env bash
# Schema Explorer authenticated product-surface verify (gitops#3605).
#
# Real browser journey on testai with the synthetic planner persona
# (budget-smoke-planner, kv/platform/smoke-budget): route-scoped KC login ->
# /admin/schema-explorer -> source picker = ifs -> IFSAPP schema -> the IFS
# Oracle snapshot renders -> TRYPE_ALL_VOUCHER_QRY -> its columns.
#
# Same substrate as budget-workspace-browser-smoke.sh: pinned Playwright image,
# persona password on a 0600 file mount, evidence dir, fail-closed on console
# errors and non-2xx schema-service calls. No rollback coupling.
set -euo pipefail

BASE_URL="${BASE_URL:-https://testai.acik.com}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_JSON="${VAULT_INIT_JSON:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
VAULT_PATH="kv/platform/smoke-budget"
EVIDENCE_DIR="${EVIDENCE_DIR:?EVIDENCE_DIR is required}"

# Same pinned Playwright runtime as the fullats browser lane.
PLAYWRIGHT_VERSION="1.60.0"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright@sha256:83192064c7510f7ee73dd63dc5f22a5e01a92c81a2e6a9c715d9e3fe55471fd9"
PLAYWRIGHT_INTEGRITY="sha512-hheHdokM8cdqCb0lcE3s+zT4t4W+vvjpGxsZlDnikarzx8tSzMebh3UiFtgqwFwnTnjYQcsyMF8ei2mCO/tpeA=="

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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
    ' sh "$1" "$VAULT_PATH"
}

PLANNER_USERNAME="$(read_vault_field persona_username)"
read_vault_field persona_password > "$SECRET_DIR/planner.password"
[[ -n "$PLANNER_USERNAME" && -s "$SECRET_DIR/planner.password" ]] \
  || { echo "FATAL: $VAULT_PATH persona alanları okunamadı" >&2; exit 1; }
chmod 600 "$SECRET_DIR/planner.password"

echo "Browser smoke: persona=$PLANNER_USERNAME base=$BASE_URL"
docker run --rm --ipc=host --network host \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
  -e NPM_CONFIG_CACHE=/tmp/npm-cache \
  -e NODE_PATH=/tmp/se-pw/node_modules \
  -e BASE_URL="$BASE_URL" \
  -e PLANNER_USERNAME="$PLANNER_USERNAME" \
  -e PLANNER_PASSWORD_FILE=/run/secrets/planner.password \
  -e EVIDENCE_DIR=/evidence \
  -e EXPECTED_FRONTEND_DIGEST="${EXPECTED_FRONTEND_DIGEST:-}" \
  -e EXPECTED_TABLE="${EXPECTED_TABLE:-}" \
  -e EXPECTED_COLUMNS="${EXPECTED_COLUMNS:-}" \
  -e EXPECTED_LABELS="${EXPECTED_LABELS:-}" \
  -e PLAYWRIGHT_VERSION="$PLAYWRIGHT_VERSION" \
  -e PLAYWRIGHT_INTEGRITY="$PLAYWRIGHT_INTEGRITY" \
  -v "$REPO_ROOT:/work:ro" \
  -v "$SECRET_DIR:/run/secrets:ro" \
  -v "$EVIDENCE_DIR:/evidence" \
  -w /work \
  "$PLAYWRIGHT_IMAGE" bash -ceu '
    npm install --prefix /tmp/se-pw --ignore-scripts --no-audit --no-fund --package-lock \
      "playwright@$PLAYWRIGHT_VERSION" >/dev/null
    node - <<'"'"'NODE'"'"'
const fs = require("fs");
const lock = JSON.parse(fs.readFileSync("/tmp/se-pw/package-lock.json", "utf8"));
const pw = lock.packages["node_modules/playwright"];
if (pw?.version !== process.env.PLAYWRIGHT_VERSION || pw?.integrity !== process.env.PLAYWRIGHT_INTEGRITY) process.exit(31);
NODE
    node scripts/acceptance/schema-explorer-browser-smoke.cjs
  '

echo "PASS Budget Workspace gerçek browser yolculuğu"
echo "EVIDENCE_DIR=$EVIDENCE_DIR"
