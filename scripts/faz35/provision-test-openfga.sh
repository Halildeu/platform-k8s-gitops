#!/usr/bin/env bash
# Faz 35 Etik Speak: create/reuse the isolated test store, promote the exact
# compiled model, bind the synthetic staff subject, and patch Vault selectors.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MODEL_JSON="${MODEL_JSON:-$SCRIPT_DIR/../../runtime-artifacts/faz35-etik-speak/authorization-model-v1.json}"
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
[ -f "$MODEL_JSON" ] || { echo "FATAL: compiled model missing: $MODEL_JSON" >&2; exit 1; }
[ -n "$STAFF_SUBJECT" ] || {
  echo "FATAL: STAFF_SUBJECT is required; use provision-test-keycloak.sh output" >&2
  exit 1
}
printf '%s' "$STAFF_SUBJECT" | grep -Eq '^[0-9A-Fa-f-]{36}$' || {
  echo "FATAL: STAFF_SUBJECT must be a Keycloak UUID subject" >&2
  exit 1
}
command -v jq >/dev/null 2>&1 || { echo "FATAL: jq missing" >&2; exit 1; }

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
  '.authorization_models[]? | select((del(.id) | tojson) == ($desired | tojson)) | .id' | head -1)
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
docker exec -e VAULT_TOKEN="$vault_root_token" -e VAULT_ADDR=http://127.0.0.1:8200 \
  "$VAULT_CONTAINER" vault kv get "$VAULT_PATH" >/dev/null 2>&1 || {
  echo "FATAL: $VAULT_PATH missing; run provision-test-pg-vault.sh first" >&2
  exit 1
}
docker exec -e VAULT_TOKEN="$vault_root_token" -e VAULT_ADDR=http://127.0.0.1:8200 \
  "$VAULT_CONTAINER" vault kv patch "$VAULT_PATH" \
    ERP_OPENFGA_STORE_ID="$store_id" ERP_OPENFGA_MODEL_ID="$model_id" >/dev/null
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
