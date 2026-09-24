#!/usr/bin/env bash
# Meeting "Göreve ata" people picker — authenticated browser journey (gitops#3834).
#
# Synthetic persona meeting-normal-persona (kv/platform/meeting-normal-persona,
# converged by scripts/keycloak/setup-meeting-normal-persona.sh) is a regular
# meeting user: Meetings module via MEETING_INTELLIGENCE_PILOT, no user
# management — the admin user grid answers it 403, which is exactly the
# non-admin case this journey proves. Route-scoped KC login ->
# /admin/meetings/<fixture meeting> -> task row "Ata" -> type -> pick the
# persona itself -> the row shows the assignee by name (never a Keycloak id).
#
# The fixture meeting and task are created and deleted over the API with the
# same persona (smoke-client ROPC). Secrets live on 0600 file mounts only.
# Same substrate as schema-explorer-browser-smoke.sh: pinned Playwright image,
# evidence dir, fail-closed on console errors and on non-2xx picker/task calls.
set -euo pipefail

BASE_URL="${BASE_URL:-https://testai.acik.com}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_JSON="${VAULT_INIT_JSON:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
PERSONA_VAULT_PATH="${PERSONA_VAULT_PATH:-kv/platform/meeting-normal-persona}"
PERSONA_USERNAME="${PERSONA_USERNAME:-meeting-normal-persona}"
PICKER_QUERY="${PICKER_QUERY:-meeting-normal}"
EVIDENCE_DIR="${EVIDENCE_DIR:?EVIDENCE_DIR is required}"

# Same pinned Playwright runtime as the fullats and schema-explorer lanes.
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
    ' sh "$1" "$2"
}

read_vault_field persona_password "$PERSONA_VAULT_PATH" > "$SECRET_DIR/persona.password"
read_vault_field client_secret kv/platform/keycloak/smoke-client > "$SECRET_DIR/smoke-client.secret"
[[ -s "$SECRET_DIR/persona.password" && -s "$SECRET_DIR/smoke-client.secret" ]] \
  || { echo "FATAL: persona / smoke-client alanları okunamadı" >&2; exit 1; }
chmod 600 "$SECRET_DIR/persona.password" "$SECRET_DIR/smoke-client.secret"

echo "Browser smoke: persona=$PERSONA_USERNAME base=$BASE_URL"
docker run --rm --ipc=host --network host \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
  -e NPM_CONFIG_CACHE=/tmp/npm-cache \
  -e NODE_PATH=/tmp/ma-pw/node_modules \
  -e BASE_URL="$BASE_URL" \
  -e PERSONA_USERNAME="$PERSONA_USERNAME" \
  -e PICKER_QUERY="$PICKER_QUERY" \
  -e PERSONA_PASSWORD_FILE=/run/secrets/persona.password \
  -e SMOKE_CLIENT_SECRET_FILE=/run/secrets/smoke-client.secret \
  -e EVIDENCE_DIR=/evidence \
  -e EXPECT_ASSIGNEE_NAME="${EXPECT_ASSIGNEE_NAME:-1}" \
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
    node scripts/acceptance/meeting-assignee-picker-browser-smoke.cjs
  '

echo "PASS toplantı görev atama (kişi seçici) gerçek browser yolculuğu"
echo "EVIDENCE_DIR=$EVIDENCE_DIR"
