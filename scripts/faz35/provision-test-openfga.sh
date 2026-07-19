#!/usr/bin/env bash
# Faz 35 Etik Speak: create/reuse the isolated test store, promote the exact
# compiled model, bind the synthetic staff subject, and patch Vault selectors.
set -euo pipefail
# A caller may invoke bash -x; disable tracing before any credential is read.
set +x

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EXPECTED_MODEL_JSON="$SCRIPT_DIR/../../bootstrap/openfga/faz35-etik-speak/authorization-model-v1.json"
EXPECTED_MODEL_FGA="$SCRIPT_DIR/../../runtime-artifacts/faz35-etik-speak/authorization-model-v1.fga"
MODEL_LEDGER="$SCRIPT_DIR/../../runtime-artifacts/openfga-model/1a4fe00f5b169945f2672f58fbec1bff2c0332e4d1cf39b742b41c28a01a95a4.json"
EXPECTED_MODEL_JSON_SHA256="9234b1d6356698f7bd2825c0842d6eed31cd5cb99d30101d22eb2a01a821409c"
MODEL_JSON="${MODEL_JSON:-$EXPECTED_MODEL_JSON}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
POD_DEPLOY="${POD_DEPLOY:-deploy/meeting-service}"
OPENFGA_BASE="${OPENFGA_BASE:-http://openfga:8080}"
STORE_NAME="${STORE_NAME:-platform-test-etik-speak}"
ETHICS_ORG_ID="${ETHICS_ORG_ID:-00000000-0000-0000-0000-000000000001}"
STAFF_SUBJECT="${STAFF_SUBJECT:-}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/home/halil/bootstrap-drill/vault-init-test.json}"
VAULT_PATH="${VAULT_PATH:-kv/platform/etik-speak}"

[ "$KUBE_NS" = "platform-test" ] && [ "$KUBE_CONTEXT" = "k3d-test" ] || {
  echo "FATAL: this script is k3d-test/platform-test only" >&2
  exit 1
}
for binding in \
  "$POD_DEPLOY=deploy/meeting-service" \
  "$OPENFGA_BASE=http://openfga:8080" \
  "$STORE_NAME=platform-test-etik-speak" \
  "$ETHICS_ORG_ID=00000000-0000-0000-0000-000000000001" \
  "$VAULT_CONTAINER=platform-vault-test" \
  "$VAULT_INIT_FILE=/home/halil/bootstrap-drill/vault-init-test.json" \
  "$VAULT_PATH=kv/platform/etik-speak"; do
  [ "${binding%%=*}" = "${binding#*=}" ] || {
    echo "FATAL: mutation target override refused: ${binding%%=*}" >&2
    exit 1
  }
done
[ -f "$MODEL_JSON" ] || { echo "FATAL: compiled model missing: $MODEL_JSON" >&2; exit 1; }
[ "$(cd "$(dirname "$MODEL_JSON")" && pwd -P)/$(basename "$MODEL_JSON")" = \
  "$(cd "$(dirname "$EXPECTED_MODEL_JSON")" && pwd -P)/$(basename "$EXPECTED_MODEL_JSON")" ] || {
  echo "FATAL: MODEL_JSON override refused" >&2
  exit 1
}
[ -n "$STAFF_SUBJECT" ] || {
  echo "FATAL: STAFF_SUBJECT is required; use provision-test-keycloak.sh output" >&2
  exit 1
}
printf '%s' "$STAFF_SUBJECT" | grep -Eq '^[0-9A-Fa-f-]{36}$' || {
  echo "FATAL: STAFF_SUBJECT must be a Keycloak UUID subject" >&2
  exit 1
}
command -v jq >/dev/null 2>&1 || { echo "FATAL: jq missing" >&2; exit 1; }
sha256_stream() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum | awk '{print $1}';
  else shasum -a 256 | awk '{print $1}'; fi
}
model_json_sha=$(jq -cS . "$MODEL_JSON" | sha256_stream)
[ "$model_json_sha" = "$EXPECTED_MODEL_JSON_SHA256" ] || {
  echo "FATAL: compiled OpenFGA model digest mismatch" >&2
  exit 1
}
model_source_sha=$(sha256_stream <"$EXPECTED_MODEL_FGA")
ledger_source_sha=$(jq -r '.artifact_content_digest | sub("^sha256:"; "")' "$MODEL_LEDGER")
[ "$model_source_sha" = "$ledger_source_sha" ] || {
  echo "FATAL: OpenFGA source digest does not match runtime ledger" >&2
  exit 1
}

ke() { kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" "$@"; }
pod_get() { ke exec "$POD_DEPLOY" -- curl -fsS "$1"; }
pod_post() {
  local endpoint=$1
  ke exec -i "$POD_DEPLOY" -- curl -sS -w '\n%{http_code}' \
    -X POST "$endpoint" -H 'Content-Type: application/json' -d @-
}

ke exec "$POD_DEPLOY" -- sh -c 'command -v curl >/dev/null' || {
  echo "FATAL: curl missing in $POD_DEPLOY" >&2
  exit 1
}

stores=$(pod_get "$OPENFGA_BASE/stores?page_size=100")
store_id=$(printf '%s' "$stores" | jq -r --arg n "$STORE_NAME" \
  '.stores[]? | select(.name==$n) | .id' | head -1)
if [ -z "$store_id" ]; then
  response=$(jq -nc --arg name "$STORE_NAME" '{name:$name}' | pod_post "$OPENFGA_BASE/stores")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  [ "$code" = 200 ] || [ "$code" = 201 ] || {
    echo "FATAL: OpenFGA store creation HTTP $code" >&2
    exit 1
  }
  store_id=$(printf '%s' "$body" | jq -r '.id // empty')
fi
[ -n "$store_id" ] || { echo "FATAL: OpenFGA store id unresolved" >&2; exit 1; }

desired=$(jq -cS . "$MODEL_JSON")
models=$(pod_get "$OPENFGA_BASE/stores/$store_id/authorization-models?page_size=100")
model_id=$(printf '%s' "$models" | jq -r --argjson desired "$desired" \
  '.authorization_models[]? | select(del(.id) == $desired) | .id' | head -1)
if [ -z "$model_id" ]; then
  response=$(pod_post "$OPENFGA_BASE/stores/$store_id/authorization-models" <"$MODEL_JSON")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  [ "$code" = 200 ] || [ "$code" = 201 ] || {
    echo "FATAL: OpenFGA model write HTTP $code" >&2
    exit 1
  }
  model_id=$(printf '%s' "$body" | jq -r '.authorization_model_id // empty')
fi
[ -n "$model_id" ] || { echo "FATAL: OpenFGA model id unresolved" >&2; exit 1; }

[ -r "$VAULT_INIT_FILE" ] || { echo "FATAL: Vault init file unreadable" >&2; exit 1; }
vault_root_token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")
printf '%s\n' "$vault_root_token" | docker exec -i \
  -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    vault kv get "$1" >/dev/null 2>&1
  ' sh "$VAULT_PATH" || {
  echo "FATAL: $VAULT_PATH missing; run provision-test-pg-vault.sh first" >&2
  exit 1
}
printf '%s\n' "$vault_root_token" | docker exec -i \
  -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    vault kv patch "$1" ERP_OPENFGA_STORE_ID="$2" ERP_OPENFGA_MODEL_ID="$3" >/dev/null
  ' sh "$VAULT_PATH" "$store_id" "$model_id"
unset vault_root_token

write_relation() {
  local relation=$1 response code body
  response=$(jq -nc --arg model "$model_id" --arg user "user:$STAFF_SUBJECT" \
    --arg relation "$relation" --arg object "ethics_product:$ETHICS_ORG_ID" \
    '{authorization_model_id:$model,writes:{tuple_keys:[{user:$user,relation:$relation,object:$object}]}}' \
    | pod_post "$OPENFGA_BASE/stores/$store_id/write")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  case "$code" in
    200|201) ;;
    400|409) printf '%s' "$body" | grep -qi 'already exist' || {
      echo "FATAL: tuple write $relation HTTP $code" >&2; exit 1; }
      ;;
    *) echo "FATAL: tuple write $relation HTTP $code" >&2; exit 1 ;;
  esac
}
write_relation handler
write_relation triager

for relation in case_viewer case_triager case_handler; do
  response=$(jq -nc --arg model "$model_id" --arg user "user:$STAFF_SUBJECT" \
    --arg relation "$relation" --arg object "ethics_product:$ETHICS_ORG_ID" \
    '{authorization_model_id:$model,tuple_key:{user:$user,relation:$relation,object:$object}}' \
    | pod_post "$OPENFGA_BASE/stores/$store_id/check")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  [ "$code" = 200 ] && [ "$(printf '%s' "$body" | jq -r '.allowed')" = true ] || {
    echo "FATAL: OpenFGA $relation allow verification failed" >&2
    exit 1
  }
done

echo "OpenFGA: isolated Etik Speak store/model and staff allow checks OK"
echo "Vault: store/model selectors patched; raw values not printed"
