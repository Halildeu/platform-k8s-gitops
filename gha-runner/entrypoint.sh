#!/usr/bin/env bash
# iter-50 Step 3.4a — Self-hosted runner entrypoint.
#
# Codex 019dded6 ek sertleştirme:
#   --ephemeral runner her job sonrası deregister + exit eder. Container
#   restart sırasında HER SEFER TAZE registration token almak gerekir;
#   .env içindeki statik token approach yanlış (token 1h geçerli, tek
#   kullanımlık). Doğru model:
#     PAT → POST /actions/runners/registration-token → fresh token →
#     config.sh --ephemeral → run.sh → exit → loop'tan baştan al.
#
# Required env:
#   RUNNER_REPO — owner/repo (e.g. Halildeu/platform-k8s-gitops)
#   RUNNER_PAT  — fine-grained PAT, Administration: Write scope on repo
#
# Codex S1 sertleştirmesi:
#   - Tek amaçlı runner; sadece testai-deploy event'leri için.
#   - Labels: self-hosted, staging-sw, testai-deploy.
#   - Trap unregister + ephemeral mode + retry on token failure.

set -euo pipefail

: "${RUNNER_REPO:?RUNNER_REPO required (e.g. Halildeu/platform-k8s-gitops)}"
: "${RUNNER_PAT:?RUNNER_PAT required (fine-grained PAT, Administration: Write scope)}"

RUNNER_NAME="${RUNNER_NAME:-staging-sw-testai-deploy}"
# Codex S1: tek amaçlı runner labels
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,staging-sw,testai-deploy}"
RUNNER_GROUP="${RUNNER_GROUP:-Default}"
RUNNER_WORKDIR="${RUNNER_WORKDIR:-_work}"

cd /home/runner

# Fetch fresh registration token from GitHub API.
# Endpoint requires Administration: Write on the target repo.
# Token is single-use, 1h TTL — must be re-fetched per registration.
get_registration_token() {
  curl -sf -X POST \
    -H "Authorization: token ${RUNNER_PAT}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/repos/${RUNNER_REPO}/actions/runners/registration-token" \
    | jq -r '.token // empty'
}

# Cleanup on shutdown — fetch a fresh token to unregister.
# (The original registration token is consumed by config.sh; we need a
# new one for `config.sh remove` if the runner is still listed.)
cleanup() {
  echo "[entrypoint] Removing runner registration..."
  local cleanup_token
  cleanup_token=$(get_registration_token || true)
  if [ -n "${cleanup_token:-}" ]; then
    ./config.sh remove --token "${cleanup_token}" || true
  else
    echo "[entrypoint] Could not fetch cleanup token; runner may remain stuck in GitHub UI"
  fi
}
trap 'cleanup; exit 130' INT TERM

# Codex sertleştirme: ephemeral loop. Each iteration:
#   1. Fetch fresh registration token (PAT → API)
#   2. config.sh --ephemeral --replace (handles re-registration cleanly)
#   3. run.sh (exits after one job due to --ephemeral)
#   4. Loop back to step 1
echo "[entrypoint] Starting ephemeral runner loop..."
while true; do
  TOKEN=$(get_registration_token)
  if [ -z "${TOKEN}" ]; then
    echo "[entrypoint] Failed to fetch registration token (PAT scope issue?); retrying in 30s..."
    sleep 30
    continue
  fi

  # iter-47c hotfix — actions/runner --replace some versions still
  # reject re-config with "already configured". Clean stale .runner
  # state at each iteration so config.sh stays idempotent.
  ./config.sh remove --token "${TOKEN}" 2>/dev/null || true

  ./config.sh \
    --url "https://github.com/${RUNNER_REPO}" \
    --token "${TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABELS}" \
    --runnergroup "${RUNNER_GROUP}" \
    --work "${RUNNER_WORKDIR}" \
    --unattended \
    --replace \
    --ephemeral

  echo "[entrypoint] Registered: ${RUNNER_NAME} (labels: ${RUNNER_LABELS})"
  echo "[entrypoint] Awaiting job..."

  # --ephemeral: run.sh exits after first completed job.
  ./run.sh || true

  echo "[entrypoint] Job complete; re-registering for next..."
done
