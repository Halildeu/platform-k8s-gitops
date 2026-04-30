#!/usr/bin/env bash
# iter-50 Step 3.4a — Self-hosted runner entrypoint.
#
# Codex 019dded6 S1 sertleştirmesi:
#   - Tek amaçlı runner; sadece testai-deploy event'leri için.
#   - Labels: self-hosted, staging-sw, testai-deploy.
#   - Runner registration token PAT yerine; her container start'ta yeni
#     ephemeral token (--ephemeral flag).
#   - Runner stop sırasında temiz unregister (TRAP).

set -euo pipefail

# Required env (docker-compose .env'den alınır)
: "${RUNNER_REPO:?RUNNER_REPO required (e.g. Halildeu/platform-k8s-gitops)}"
: "${RUNNER_REGISTRATION_TOKEN:?RUNNER_REGISTRATION_TOKEN required (1h validity, generate from GitHub UI)}"

RUNNER_NAME="${RUNNER_NAME:-staging-sw-testai-deploy}"
# Codex S1: tek amaçlı runner labels
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,staging-sw,testai-deploy}"
RUNNER_GROUP="${RUNNER_GROUP:-Default}"
RUNNER_WORKDIR="${RUNNER_WORKDIR:-_work}"

cd /home/runner

# Cleanup on shutdown — unregister runner from GitHub.
# `RUNNER_TOKEN` set edilmezse `--token` argümanı için RUNNER_REGISTRATION_TOKEN
# fallback kullan.
cleanup() {
  echo "[entrypoint] Removing runner registration..."
  ./config.sh remove --token "${RUNNER_REGISTRATION_TOKEN:-}" || true
}
trap 'cleanup; exit 130' INT TERM

# Idempotent registration: if already configured, just run; else config + run.
if [ ! -f .runner ]; then
  echo "[entrypoint] First-time runner registration..."
  ./config.sh \
    --url "https://github.com/${RUNNER_REPO}" \
    --token "${RUNNER_REGISTRATION_TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABELS}" \
    --runnergroup "${RUNNER_GROUP}" \
    --work "${RUNNER_WORKDIR}" \
    --unattended \
    --replace \
    --ephemeral
  echo "[entrypoint] Registered: ${RUNNER_NAME} (labels: ${RUNNER_LABELS})"
else
  echo "[entrypoint] Existing .runner config detected; reusing."
fi

# Run loop. --ephemeral exits after one job; outer loop re-registers + runs again.
echo "[entrypoint] Starting runner..."
./run.sh
