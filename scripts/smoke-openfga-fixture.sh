#!/usr/bin/env bash
# Faz 21.3 — OpenFGA fixture smoke test (D29 Zanzibar-ready third-level discipline).
# Runs every smoke_check from bootstrap/local-fixtures/openfga/tuples.json against
# the OpenFGA store at OPENFGA_URL and asserts the expected allow/deny outcome.
#
# Usage:
#   OPENFGA_URL=http://localhost:18080 ./scripts/smoke-openfga-fixture.sh
#
# Env:
#   OPENFGA_URL   (required) base URL e.g. http://localhost:32080
#   OPENFGA_STORE_ID  (optional) explicit store; otherwise auto-discover the first store.
#
# Exits 0 if all checks pass; non-zero on any mismatch (lists every failure).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TUPLES="${REPO_ROOT}/bootstrap/local-fixtures/openfga/tuples.json"

: "${OPENFGA_URL:?OPENFGA_URL must be set (e.g. http://localhost:18080)}"

if [[ ! -f "${TUPLES}" ]]; then
  echo "ERR: ${TUPLES} not found" >&2
  exit 2
fi

# Resolve store
STORE_ID="${OPENFGA_STORE_ID:-}"
if [[ -z "${STORE_ID}" ]]; then
  STORE_ID=$(curl -s --max-time 5 "${OPENFGA_URL}/stores" | jq -r '.stores[0].id // empty')
fi
if [[ -z "${STORE_ID}" ]]; then
  echo "ERR: no store found at ${OPENFGA_URL}; pass OPENFGA_STORE_ID or seed first" >&2
  exit 2
fi

# Use latest model
MODEL_ID=$(curl -s --max-time 5 "${OPENFGA_URL}/stores/${STORE_ID}/authorization-models" \
  | jq -r '.authorization_models[0].id // empty')
if [[ -z "${MODEL_ID}" ]]; then
  echo "ERR: no authorization model written to store ${STORE_ID}" >&2
  exit 2
fi

echo "store=${STORE_ID}"
echo "model=${MODEL_ID}"
echo "---"

PASS=0
FAIL=0
FAIL_LINES=()

# Iterate smoke_checks and call /check API for each.
while IFS= read -r ROW; do
  DESC=$(echo "${ROW}" | jq -r '.description')
  EXPECTED=$(echo "${ROW}" | jq -r '.expected')
  CHECK=$(echo "${ROW}" | jq -c '.check')
  PAYLOAD=$(jq -nc --arg mid "${MODEL_ID}" --argjson tk "${CHECK}" \
    '{authorization_model_id:$mid, tuple_key:$tk}')
  ACTUAL=$(curl -s --max-time 5 -X POST "${OPENFGA_URL}/stores/${STORE_ID}/check" \
    -H 'Content-Type: application/json' -d "${PAYLOAD}" | jq -r '.allowed // false')
  if [[ "${ACTUAL}" == "${EXPECTED}" ]]; then
    printf 'PASS  expected=%-5s actual=%-5s  %s\n' "${EXPECTED}" "${ACTUAL}" "${DESC}"
    PASS=$((PASS + 1))
  else
    printf 'FAIL  expected=%-5s actual=%-5s  %s\n' "${EXPECTED}" "${ACTUAL}" "${DESC}"
    FAIL=$((FAIL + 1))
    FAIL_LINES+=("${DESC} (expected=${EXPECTED} actual=${ACTUAL})")
  fi
done < <(jq -c '.smoke_checks[]' "${TUPLES}")

echo "---"
echo "summary: ${PASS} pass, ${FAIL} fail"
if (( FAIL > 0 )); then
  echo
  echo "Failed checks:"
  for line in "${FAIL_LINES[@]}"; do
    echo "  - ${line}"
  done
  exit 1
fi
