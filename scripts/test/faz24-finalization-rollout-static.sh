#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_RENDER="$(mktemp)"
TEST_ESO_RENDER="$(mktemp)"
PROD_RENDER="$(mktemp)"
PROD_ESO_RENDER="$(mktemp)"
MUTATED_EVIDENCE="$(mktemp)"
MUTATED_PROD_RENDER="$(mktemp)"
MUTATED_WORKFLOW="$(mktemp)"
trap 'rm -f -- "${TEST_RENDER}" "${TEST_ESO_RENDER}" "${PROD_RENDER}" "${PROD_ESO_RENDER}" "${MUTATED_EVIDENCE}" "${MUTATED_PROD_RENDER}" "${MUTATED_WORKFLOW}"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

command -v kustomize >/dev/null 2>&1 || fail "kustomize is required"
python3 -m py_compile \
  "${ROOT}/scripts/faz24/transcript_ready_pre_enable_contract.py" \
  "${ROOT}/scripts/faz24/collect_transcript_ready_pre_enable_evidence.py" \
  "${ROOT}/scripts/faz24/verify_transcript_ready_pre_enable_evidence.py" \
  "${ROOT}/scripts/faz24/build_transcript_ready_permit_trust_root.py" \
  "${ROOT}/scripts/faz24/sign_transcript_ready_pre_enable_permit.py" \
  "${ROOT}/scripts/ops/bootstrap_faz24_transcript_ready_permit_transit.py" \
  "${ROOT}/scripts/test/verify-faz24-finalization-rollout.py" \
  "${ROOT}/scripts/test/verify-faz24-finalization-ci-wiring.py" \
  "${ROOT}/scripts/test/verify-faz24-finalization-source-evidence.py" \
  "${ROOT}/scripts/test/verify-faz24-finalization-remote-evidence.py" \
  "${ROOT}/scripts/test/verify-faz24-finalization-build-provenance.py" \
  "${ROOT}/scripts/test/verify-faz24-transcript-ready-pre-enable-static.py"
kustomize build "${ROOT}/kustomize/overlays/test" >"${TEST_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/test/eso" >"${TEST_ESO_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/prod" >"${PROD_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/prod/eso" >"${PROD_ESO_RENDER}"

python3 "${ROOT}/scripts/test/verify-faz24-finalization-rollout.py" \
  "${TEST_RENDER}" "${TEST_ESO_RENDER}" "${PROD_RENDER}" "${PROD_ESO_RENDER}"
python3 "${ROOT}/scripts/test/verify-faz24-finalization-source-evidence.py" \
  "${ROOT}/docs/faz-24-evidence/2026-07-18-finalization-source-ci.json"
python3 -m unittest \
  tests.faz24.test_analysis_capability_secret_contract \
  tests.faz24.test_finalization_evidence_verifiers \
  tests.faz24.test_transcript_ready_pre_enable_gate \
  tests.faz24.test_transcript_ready_permit_bootstrap \
  tests.faz24.test_transcript_ready_permit_signer
python3 "${ROOT}/scripts/test/verify-faz24-transcript-ready-pre-enable-static.py" \
  --test-render "${TEST_RENDER}" \
  --test-eso-render "${TEST_ESO_RENDER}" \
  --prod-render "${PROD_RENDER}" \
  --prod-eso-render "${PROD_ESO_RENDER}"

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

cp "${PROD_RENDER}" "${MUTATED_PROD_RENDER}"
cat >>"${MUTATED_PROD_RENDER}" <<'YAML'
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: forbidden-transcript-secret-regression
spec:
  template:
    spec:
      containers:
        - name: regression
          env:
            - name: TRANSCRIPT_MEETING_SERVICE_CLIENT_SECRET
              valueFrom:
                secretKeyRef:
                  name: unexpected-prod-secret
                  key: client-secret
YAML
if python3 "${ROOT}/scripts/test/verify-faz24-finalization-rollout.py" \
    "${TEST_RENDER}" "${TEST_ESO_RENDER}" \
    "${MUTATED_PROD_RENDER}" "${PROD_ESO_RENDER}" >/dev/null 2>&1; then
  fail "prod leakage verifier accepted a transcript meeting client-secret binding"
fi

python3 "${ROOT}/scripts/test/verify-faz24-finalization-ci-wiring.py" \
  "${ROOT}/.github/workflows/ci.yml"
cat >"${MUTATED_WORKFLOW}" <<'YAML'
name: regression
jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      # python3 scripts/test/verify-faz24-finalization-source-evidence.py docs/faz-24-evidence/2026-07-18-finalization-source-ci.json
      - name: verify-faz24-finalization-source-evidence.py
        run: printf '%s\n' 'not the verifier'
YAML
if python3 "${ROOT}/scripts/test/verify-faz24-finalization-ci-wiring.py" \
    "${MUTATED_WORKFLOW}" >/dev/null 2>&1; then
  fail "CI wiring verifier accepted a comment/name-only false positive"
fi

cat >"${MUTATED_WORKFLOW}" <<'YAML'
name: regression
jobs:
  guard:
    runs-on: ubuntu-latest
    steps:
      - name: forbidden network-bound remote evidence gate
        run: >-
          python3 scripts/test/verify-faz24-finalization-remote-evidence.py
          docs/faz-24-evidence/2026-07-18-finalization-source-ci.json
YAML
if python3 "${ROOT}/scripts/test/verify-faz24-finalization-ci-wiring.py" \
    "${MUTATED_WORKFLOW}" >/dev/null 2>&1; then
  fail "CI wiring verifier accepted the network/retention-bound remote gate"
fi

grep -Fq 'MEETING_INTERNAL_SERVICE_JWT_CLIENT_IDS: meeting-ai,transcript-service' \
  "${TEST_RENDER}" || fail "test transcript-service meeting authorization missing"
if grep -Fq 'MEETING_INTERNAL_SERVICE_JWT_CLIENT_IDS: meeting-ai,transcript-service' \
    "${PROD_RENDER}"; then
  fail "test-only transcript-service meeting authorization leaked into prod render"
fi

printf '%s\n' 'PASS: Faz 24 finalization rollout static contract'
