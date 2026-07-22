#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_RENDER="$(mktemp)"
PROD_RENDER="$(mktemp)"
trap 'rm -f "${TEST_RENDER}" "${PROD_RENDER}"' EXIT

kustomize build "${ROOT}/kustomize/overlays/test" >"${TEST_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/prod" >"${PROD_RENDER}"

python3 "${ROOT}/scripts/test/verify-faz24-live-analyze-enable.py" \
  "${TEST_RENDER}" \
  "${PROD_RENDER}" \
  "${ROOT}/kustomize/base/apps/audio-gateway/configmap.yaml"

echo 'Faz 24 live-analyze test-only enable guard: PASS'
