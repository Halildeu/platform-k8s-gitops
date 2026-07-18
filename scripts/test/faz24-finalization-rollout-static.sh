#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_RENDER="$(mktemp)"
TEST_ESO_RENDER="$(mktemp)"
PROD_RENDER="$(mktemp)"
PROD_ESO_RENDER="$(mktemp)"
MUTATED_EVIDENCE="$(mktemp)"
trap 'rm -f -- "${TEST_RENDER}" "${TEST_ESO_RENDER}" "${PROD_RENDER}" "${PROD_ESO_RENDER}" "${MUTATED_EVIDENCE}"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

command -v kustomize >/dev/null 2>&1 || fail "kustomize is required"
python3 -m py_compile \
  "${ROOT}/scripts/test/verify-faz24-finalization-rollout.py" \
  "${ROOT}/scripts/test/verify-faz24-finalization-source-evidence.py" \
  "${ROOT}/scripts/test/verify-faz24-finalization-remote-evidence.py" \
  "${ROOT}/scripts/test/verify-faz24-finalization-build-provenance.py"
kustomize build "${ROOT}/kustomize/overlays/test" >"${TEST_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/test/eso" >"${TEST_ESO_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/prod" >"${PROD_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/prod/eso" >"${PROD_ESO_RENDER}"

python3 "${ROOT}/scripts/test/verify-faz24-finalization-rollout.py" \
  "${TEST_RENDER}" "${TEST_ESO_RENDER}" "${PROD_RENDER}" "${PROD_ESO_RENDER}"
python3 "${ROOT}/scripts/test/verify-faz24-finalization-source-evidence.py" \
  "${ROOT}/docs/faz-24-evidence/2026-07-18-finalization-source-ci.json"

python3 - \
  "${ROOT}/docs/faz-24-evidence/2026-07-18-finalization-source-ci.json" \
  "${MUTATED_EVIDENCE}" <<'PY'
import json
import sys

source, target = sys.argv[1:]
with open(source, encoding="utf-8") as stream:
    evidence = json.load(stream)
evidence["acceptedClaims"]["desiredImageProvenance"] = True
with open(target, "w", encoding="utf-8") as stream:
    json.dump(evidence, stream)
PY
if python3 "${ROOT}/scripts/test/verify-faz24-finalization-source-evidence.py" \
  "${MUTATED_EVIDENCE}" >/dev/null 2>&1; then
  fail "source verifier accepted an unauthorized image-provenance claim"
fi

grep -Fq 'verify-faz24-finalization-remote-evidence.py' \
  "${ROOT}/.github/workflows/ci.yml" || \
  fail "CI lost the fail-closed remote GitHub evidence guard"
if grep -Fq 'verify-faz24-finalization-build-provenance.py' \
    "${ROOT}/.github/workflows/ci.yml"; then
  fail "operator-only image provenance verifier became a static CI acceptance gate"
fi

grep -Fq 'MEETING_INTERNAL_SERVICE_JWT_CLIENT_IDS: meeting-ai,transcript-service' \
  "${TEST_RENDER}" || fail "test transcript-service meeting authorization missing"
if grep -Fq 'MEETING_INTERNAL_SERVICE_JWT_CLIENT_IDS: meeting-ai,transcript-service' \
    "${PROD_RENDER}"; then
  fail "test-only transcript-service meeting authorization leaked into prod render"
fi

printf '%s\n' 'PASS: Faz 24 finalization rollout static contract'
