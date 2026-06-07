#!/usr/bin/env bash
# Faz 22 #1267 — endpoint-admin OpenFGA runtime selector verifier.
#
# Read-only verification for the test cluster. It proves that endpoint-admin no
# longer receives OpenFGA store/model IDs from ConfigMap pins and instead sees
# the shared ESO-managed Secret values from kv/platform/openfga.
#
# This script intentionally prints only OpenFGA store/model identifiers. It
# never prints DB credentials, peppers, encryption keys, bearer tokens, cookies,
# or raw Secret JSON.

set -euo pipefail

CTX="${CTX:-k3d-test}"
NS="${NS:-platform-test}"
DEPLOY="${DEPLOY:-endpoint-admin-service}"
CM="${CM:-endpoint-admin-service-config}"
ES="${ES:-endpoint-admin-service-secrets}"
SECRET="${SECRET:-endpoint-admin-service-secrets}"
EXPECTED_MODEL_ID="${EXPECTED_MODEL_ID:-01KS8QE8T1EJ2DF5CRS4VV9YX1}"
EXPECTED_STORE_ID="${EXPECTED_STORE_ID:-01KPP0CFP4G82K42Y6NYSPT4JF}"
REPORT_PATH="${REPORT_PATH:-}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERR: required command not found: $1" >&2
    exit 2
  }
}

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

emit_report() {
  local verdict="$1"
  local reason="$2"
  if [ -n "$REPORT_PATH" ]; then
    mkdir -p "$(dirname "$REPORT_PATH")"
    cat >"$REPORT_PATH" <<EOF
{
  "verdict": "$verdict",
  "reason": "$(printf '%s' "$reason" | json_escape)",
  "context": "$CTX",
  "namespace": "$NS",
  "deployment": "$DEPLOY",
  "configmap": "$CM",
  "externalsecret": "$ES",
  "secret": "$SECRET",
  "expected_model_id": "$EXPECTED_MODEL_ID",
  "expected_store_id": "$EXPECTED_STORE_ID",
  "observed_model_id": "${OBSERVED_MODEL_ID:-}",
  "observed_store_id": "${OBSERVED_STORE_ID:-}",
  "pod_model_id": "${POD_MODEL_ID:-}",
  "pod_store_id": "${POD_STORE_ID:-}"
}
EOF
  fi
}

fail() {
  local msg="$1"
  echo "FAIL: $msg" >&2
  emit_report "FAIL" "$msg"
  exit 1
}

pass() {
  local msg="$1"
  echo "PASS: $msg"
  emit_report "PASS" "$msg"
}

b64decode() {
  base64 --decode 2>/dev/null || base64 -d
}

need kubectl
need jq
need python3
need base64

echo "== endpoint-admin OpenFGA runtime verifier =="
echo "context=$CTX namespace=$NS deployment=$DEPLOY"

kubectl --context "$CTX" -n "$NS" get deploy "$DEPLOY" >/dev/null \
  || fail "deployment not found: $NS/$DEPLOY"

CM_JSON="$(kubectl --context "$CTX" -n "$NS" get cm "$CM" -o json)"
CM_HAS_STORE="$(printf '%s' "$CM_JSON" | jq -r '.data | has("ERP_OPENFGA_STORE_ID")')"
CM_HAS_MODEL="$(printf '%s' "$CM_JSON" | jq -r '.data | has("ERP_OPENFGA_MODEL_ID")')"
CM_ENABLED="$(printf '%s' "$CM_JSON" | jq -r '.data.ERP_OPENFGA_ENABLED // ""')"
CM_API_URL="$(printf '%s' "$CM_JSON" | jq -r '.data.ERP_OPENFGA_API_URL // ""')"

echo "ConfigMap ERP_OPENFGA_ENABLED=$CM_ENABLED"
echo "ConfigMap ERP_OPENFGA_API_URL=$CM_API_URL"
echo "ConfigMap has STORE_ID key=$CM_HAS_STORE"
echo "ConfigMap has MODEL_ID key=$CM_HAS_MODEL"

[ "$CM_ENABLED" = "true" ] || fail "ConfigMap ERP_OPENFGA_ENABLED must be true"
[ "$CM_HAS_STORE" = "false" ] || fail "ConfigMap still carries ERP_OPENFGA_STORE_ID"
[ "$CM_HAS_MODEL" = "false" ] || fail "ConfigMap still carries ERP_OPENFGA_MODEL_ID"

ES_JSON="$(kubectl --context "$CTX" -n "$NS" get externalsecret "$ES" -o json)"
ES_READY="$(printf '%s' "$ES_JSON" | jq -r '[.status.conditions[]? | select(.type=="Ready")][0].status // "Missing"')"
STORE_REF="$(printf '%s' "$ES_JSON" | jq -r '.spec.data[]? | select(.secretKey=="ERP_OPENFGA_STORE_ID") | "\(.remoteRef.key)#\(.remoteRef.property)"')"
MODEL_REF="$(printf '%s' "$ES_JSON" | jq -r '.spec.data[]? | select(.secretKey=="ERP_OPENFGA_MODEL_ID") | "\(.remoteRef.key)#\(.remoteRef.property)"')"

echo "ExternalSecret Ready=$ES_READY"
echo "ExternalSecret STORE ref=$STORE_REF"
echo "ExternalSecret MODEL ref=$MODEL_REF"

[ "$ES_READY" = "True" ] || fail "ExternalSecret Ready is not True"
[ "$STORE_REF" = "kv/platform/openfga#store_id" ] || fail "ExternalSecret STORE ref mismatch"
[ "$MODEL_REF" = "kv/platform/openfga#model_id" ] || fail "ExternalSecret MODEL ref mismatch"

SECRET_JSON="$(kubectl --context "$CTX" -n "$NS" get secret "$SECRET" -o json)"
OBSERVED_STORE_ID="$(printf '%s' "$SECRET_JSON" | jq -r '.data.ERP_OPENFGA_STORE_ID // empty' | b64decode)"
OBSERVED_MODEL_ID="$(printf '%s' "$SECRET_JSON" | jq -r '.data.ERP_OPENFGA_MODEL_ID // empty' | b64decode)"

echo "Secret STORE_ID=$OBSERVED_STORE_ID"
echo "Secret MODEL_ID=$OBSERVED_MODEL_ID"

[ "$OBSERVED_STORE_ID" = "$EXPECTED_STORE_ID" ] || fail "Secret STORE_ID mismatch"
[ "$OBSERVED_MODEL_ID" = "$EXPECTED_MODEL_ID" ] || fail "Secret MODEL_ID mismatch"

kubectl --context "$CTX" -n "$NS" rollout status "deploy/$DEPLOY" --timeout=180s

POD_ENV="$(kubectl --context "$CTX" -n "$NS" exec "deploy/$DEPLOY" -- printenv)"
POD_ENABLED="$(printf '%s\n' "$POD_ENV" | sed -n 's/^ERP_OPENFGA_ENABLED=//p' | head -1)"
POD_API_URL="$(printf '%s\n' "$POD_ENV" | sed -n 's/^ERP_OPENFGA_API_URL=//p' | head -1)"
POD_STORE_ID="$(printf '%s\n' "$POD_ENV" | sed -n 's/^ERP_OPENFGA_STORE_ID=//p' | head -1)"
POD_MODEL_ID="$(printf '%s\n' "$POD_ENV" | sed -n 's/^ERP_OPENFGA_MODEL_ID=//p' | head -1)"

echo "Pod ERP_OPENFGA_ENABLED=$POD_ENABLED"
echo "Pod ERP_OPENFGA_API_URL=$POD_API_URL"
echo "Pod ERP_OPENFGA_STORE_ID=$POD_STORE_ID"
echo "Pod ERP_OPENFGA_MODEL_ID=$POD_MODEL_ID"

[ "$POD_ENABLED" = "true" ] || fail "pod ERP_OPENFGA_ENABLED mismatch"
[ "$POD_STORE_ID" = "$EXPECTED_STORE_ID" ] || fail "pod STORE_ID mismatch"
[ "$POD_MODEL_ID" = "$EXPECTED_MODEL_ID" ] || fail "pod MODEL_ID mismatch"

pass "endpoint-admin OpenFGA runtime selector resolves through ESO-managed kv/platform/openfga"
