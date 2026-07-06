#!/usr/bin/env bash
# Regression guard for Faz 22.5 M2 canonical mTLS device hosts (#1359).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

TEST_HOST="mtls.testai.acik.com"
PROD_HOST="mtls.ai.acik.com"
OLD_HOST="endpoint-agent-mtls.testai.acik.com"
OLD_BASE="https://mtls.testai.acik.com/api/v1/endpoint-admin"
CANONICAL_BASE="https://mtls.testai.acik.com/api/v1/endpoint-agent"

cd "$REPO_ROOT"

required_files=(
  "kustomize/base/endpoint-agent-mtls/ingress-passthrough.yaml"
  "kustomize/base/endpoint-agent-mtls/host-nginx-stream-snippet.conf"
  "docs/runbooks/RB-faz22-M2-edge-mtls-activation.md"
  "docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md"
  "docs/adr/0012-EA-endpoint-admin-governance-charter.md"
  "docs/faz-22-software-deployment-plan.md"
)

for file in "${required_files[@]}"; do
  [ -f "$file" ] || { echo "missing required file: $file" >&2; exit 1; }
done

grep -q "host: ${TEST_HOST}" kustomize/base/endpoint-agent-mtls/ingress-passthrough.yaml
grep -q "${TEST_HOST}" kustomize/base/endpoint-agent-mtls/host-nginx-stream-snippet.conf
grep -q "${PROD_HOST}" kustomize/base/endpoint-agent-mtls/host-nginx-stream-snippet.conf
grep -q "${CANONICAL_BASE}" docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md
grep -q "${PROD_HOST}" docs/runbooks/RB-faz22-M2-edge-mtls-activation.md

if grep -R --line-number --fixed-strings "$OLD_HOST" \
  kustomize/base/endpoint-agent-mtls \
  docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md \
  docs/adr/0012-EA-endpoint-admin-governance-charter.md \
  docs/faz-22-software-deployment-plan.md; then
  echo "stale mTLS host found outside explicit current-state/runbook amendment notes" >&2
  exit 1
fi

if grep -R --line-number --fixed-strings "$OLD_BASE" \
  docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md \
  docs/adr/0012-EA-endpoint-admin-governance-charter.md \
  docs/faz-22-software-deployment-plan.md; then
  echo "stale mTLS AutoEnroll base path found; use ${CANONICAL_BASE}" >&2
  exit 1
fi

echo "PASS endpoint-agent mTLS host/base guard"
