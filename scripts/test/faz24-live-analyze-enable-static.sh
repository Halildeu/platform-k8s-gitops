#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_RENDER="$(mktemp)"
PROD_RENDER="$(mktemp)"
trap 'rm -f "${TEST_RENDER}" "${PROD_RENDER}"' EXIT

kustomize build "${ROOT}/kustomize/overlays/test" >"${TEST_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/prod" >"${PROD_RENDER}"

grep -Fq 'AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED: "false"' \
  "${ROOT}/kustomize/base/apps/audio-gateway/configmap.yaml"
grep -Fq 'AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED: "true"' "${TEST_RENDER}"
grep -Fq 'AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_BASE_URL: http://meeting-ai-service:8080' \
  "${TEST_RENDER}"
grep -Fq 'audio-gateway.acik.com/live-analyze-enable-rev: 2026-07-22-244-enable-v1' \
  "${TEST_RENDER}"

if grep -Fq 'AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED: "true"' "${PROD_RENDER}"; then
  echo 'live-analyze test gate leaked into the prod render' >&2
  exit 1
fi

echo 'Faz 24 live-analyze test-only enable guard: PASS'
