#!/usr/bin/env bash
# scripts/promotion/generate-ledger.sh
#
# Codex Sprint B B1 — promotion ledger entry generator.
# Invoked by platform-backend / platform-web CI after successful image
# build + GHCR push. Creates an initial release-candidates/<repo>/<sha>.json
# ledger entry with status="built" (no test/prod promotion yet).
#
# Usage:
#   generate-ledger.sh <repo> <service> <git_sha> <image_path> <image_digest>
#
# Args:
#   repo          — "platform-backend" or "platform-web"
#   service       — logical service name (matches services.yaml entry)
#   git_sha       — full 40+ char git commit SHA from upstream repo
#   image_path    — GHCR path (e.g. halildeu/platform-backend-user-service)
#   image_digest  — sha256:<64-hex> manifest digest from GHCR push response
#
# Optional env:
#   PUSH_RUN_ID    — GitHub Actions run.id from CI (added to image.push_run_id)
#   ROLLBACK_TO    — previous-known-good digest (added to metadata.rollback_to_digest)
#   CI_RUN_URL     — full URL to the CI build run (added to audit.ci_run_url)
#
# Output:
#   release-candidates/<repo>/<git_sha>.json
#
# Exit:
#   0 — ledger entry created or already exists
#   1 — argument validation failed
#   2 — write error

set -euo pipefail

if [[ "$#" -lt 5 ]]; then
  cat <<EOF
ERR: usage: generate-ledger.sh <repo> <service> <git_sha> <image_path> <image_digest>

Example:
  generate-ledger.sh \\
    platform-backend \\
    user-service \\
    548c1831719298ce1b0c8a52b2e37c9bdba3ed4a \\
    halildeu/platform-backend-user-service \\
    sha256:548c1831719298ce1b0c8a52b2e37c9bdba3ed4ab8cd939cfad54087774b390b
EOF
  exit 1
fi

REPO="$1"
SERVICE="$2"
GIT_SHA="$3"
IMAGE_PATH="$4"
IMAGE_DIGEST="$5"

# Validate
[[ "$REPO" =~ ^(platform-backend|platform-web)$ ]] || {
  echo "ERR: repo must be platform-backend or platform-web (got: $REPO)"; exit 1
}
[[ "$GIT_SHA" =~ ^[a-f0-9]{40,64}$ ]] || {
  echo "ERR: git_sha must be 40-64 hex chars (got: $GIT_SHA)"; exit 1
}
[[ "$IMAGE_DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]] || {
  echo "ERR: image_digest must be sha256:<64-hex> (got: $IMAGE_DIGEST)"; exit 1
}

GIT_SHORT_SHA="${GIT_SHA:0:8}"
TAG="sha-${GIT_SHA:0:7}"

REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LEDGER_DIR="$REPO_ROOT/release-candidates/$REPO"
LEDGER_FILE="$LEDGER_DIR/$GIT_SHA.json"

mkdir -p "$LEDGER_DIR"

# Idempotency: if ledger entry already exists, only emit a notice
if [[ -f "$LEDGER_FILE" ]]; then
  echo "[generate-ledger] $LEDGER_FILE already exists — preserving (idempotent)"
  echo "$LEDGER_FILE"
  exit 0
fi

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PUSH_RUN_ID="${PUSH_RUN_ID:-null}"
ROLLBACK_TO="${ROLLBACK_TO:-null}"
CI_RUN_URL="${CI_RUN_URL:-null}"

# Quote string fields properly in JSON
[[ "$PUSH_RUN_ID" != "null" ]] && PUSH_RUN_ID="$PUSH_RUN_ID" || PUSH_RUN_ID="null"
[[ "$ROLLBACK_TO" != "null" ]] && ROLLBACK_TO="\"$ROLLBACK_TO\"" || ROLLBACK_TO="null"
[[ "$CI_RUN_URL" != "null" ]] && CI_RUN_URL="\"$CI_RUN_URL\"" || CI_RUN_URL="null"

cat > "$LEDGER_FILE" <<EOF
{
  "schema_version": "1.0",
  "repo": "$REPO",
  "service": "$SERVICE",
  "git_sha": "$GIT_SHA",
  "git_short_sha": "$GIT_SHORT_SHA",
  "image": {
    "registry": "ghcr.io",
    "path": "$IMAGE_PATH",
    "digest": "$IMAGE_DIGEST",
    "tag": "$TAG",
    "push_run_id": $PUSH_RUN_ID,
    "pushed_at": "$NOW"
  },
  "promotion": {
    "test": {
      "promoted_at": null,
      "promoted_by_pr": null,
      "argocd_revision": null,
      "smoke_evidence": null,
      "verified_at": null,
      "candidate_pr": null,
      "candidate_pr_status": null
    },
    "prod": {
      "promoted_at": null,
      "promoted_by_pr": null,
      "argocd_revision": null,
      "smoke_evidence": null,
      "verified_at": null,
      "candidate_pr": null,
      "candidate_pr_status": null
    }
  },
  "metadata": {
    "required_migrations": [],
    "backward_compatible_until": null,
    "rollback_safe": true,
    "rollback_to_digest": $ROLLBACK_TO
  },
  "audit": {
    "created_at": "$NOW",
    "last_updated_at": "$NOW",
    "ci_run_url": $CI_RUN_URL
  }
}
EOF

echo "[generate-ledger] created $LEDGER_FILE"

# Validate against schema (best-effort)
if [[ -x "$REPO_ROOT/scripts/promotion/validate-ledger-schema.py" ]]; then
  if python3 "$REPO_ROOT/scripts/promotion/validate-ledger-schema.py" "$LEDGER_FILE" > /tmp/ledger-validate.log 2>&1; then
    echo "[generate-ledger] schema validation: OK"
  else
    echo "[generate-ledger] WARN: schema validation failed:"
    cat /tmp/ledger-validate.log | head -20
    echo "(ledger entry written anyway; CI promotion-ledger-validate workflow will catch it)"
  fi
fi

echo "$LEDGER_FILE"
