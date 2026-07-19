#!/usr/bin/env bash
# Faz 35 Etik Speak: create/reuse the isolated test store, promote the exact
# compiled model and bind the synthetic staff subject. Store/model IDs are
# non-secret outputs that must be pinned in GitOps by a new reviewed commit.
set -euo pipefail
# A caller may invoke bash -x; disable tracing before any credential is read.
set +x

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EXPECTED_MODEL_JSON="$SCRIPT_DIR/../../bootstrap/openfga/faz35-etik-speak/authorization-model-v1.json"
EXPECTED_MODEL_FGA="$SCRIPT_DIR/../../runtime-artifacts/faz35-etik-speak/authorization-model-v1.fga"
MODEL_LEDGER="$SCRIPT_DIR/../../runtime-artifacts/openfga-model/711364fb006ac49b630a5df6f5724516fe82086c2418a26aa9e1f829e97d6c33.json"
EXPECTED_MODEL_JSON_SHA256="711364fb006ac49b630a5df6f5724516fe82086c2418a26aa9e1f829e97d6c33"
EXPECTED_MODEL_FGA_SHA256="1a4fe00f5b169945f2672f58fbec1bff2c0332e4d1cf39b742b41c28a01a95a4"
MODEL_JSON="${MODEL_JSON:-$EXPECTED_MODEL_JSON}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"
POD_DEPLOY="${POD_DEPLOY:-deploy/meeting-service}"
OPENFGA_BASE="${OPENFGA_BASE:-http://openfga:8080}"
STORE_NAME="${STORE_NAME:-platform-test-etik-speak}"
ETHICS_ORG_ID="${ETHICS_ORG_ID:-00000000-0000-0000-0000-000000000001}"
WRONG_ETHICS_ORG_ID="${WRONG_ETHICS_ORG_ID:-00000000-0000-0000-0000-000000000002}"
STAFF_SUBJECT="${STAFF_SUBJECT:-}"
WRONG_ORG_SUBJECT="${WRONG_ORG_SUBJECT:-}"
DENIED_SUBJECT="${DENIED_SUBJECT:-}"
RECUSAL_SENTINEL_CASE_ID="00000000-0000-0000-0000-000000000035"

[ "$KUBE_NS" = "platform-test" ] && [ "$KUBE_CONTEXT" = "k3d-test" ] || {
  echo "FATAL: this script is k3d-test/platform-test only" >&2
  exit 1
}
for binding in \
  "$POD_DEPLOY=deploy/meeting-service" \
  "$OPENFGA_BASE=http://openfga:8080" \
  "$STORE_NAME=platform-test-etik-speak" \
  "$ETHICS_ORG_ID=00000000-0000-0000-0000-000000000001" \
  "$WRONG_ETHICS_ORG_ID=00000000-0000-0000-0000-000000000002"; do
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
for subject_binding in \
  "STAFF_SUBJECT=$STAFF_SUBJECT" \
  "WRONG_ORG_SUBJECT=$WRONG_ORG_SUBJECT" \
  "DENIED_SUBJECT=$DENIED_SUBJECT"; do
  subject_name=${subject_binding%%=*}
  subject_value=${subject_binding#*=}
  printf '%s' "$subject_value" | grep -Eq \
    '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$' || {
    echo "FATAL: $subject_name must be a Keycloak UUID from provision-test-keycloak.sh" >&2
    exit 1
  }
done
[ "$STAFF_SUBJECT" != "$WRONG_ORG_SUBJECT" ] && \
  [ "$STAFF_SUBJECT" != "$DENIED_SUBJECT" ] && \
  [ "$WRONG_ORG_SUBJECT" != "$DENIED_SUBJECT" ] || {
  echo "FATAL: positive and negative Keycloak subjects must be distinct" >&2
  exit 1
}
command -v jq >/dev/null 2>&1 || { echo "FATAL: jq missing" >&2; exit 1; }
sha256_stream() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum | awk '{print $1}';
  else shasum -a 256 | awk '{print $1}'; fi
}
model_json_canonical=$(jq -cS . "$MODEL_JSON")
model_json_sha=$(printf '%s' "$model_json_canonical" | sha256_stream)
[ "$model_json_sha" = "$EXPECTED_MODEL_JSON_SHA256" ] || {
  echo "FATAL: compiled OpenFGA model digest mismatch" >&2
  exit 1
}
model_source_sha=$(sha256_stream <"$EXPECTED_MODEL_FGA")
[ "$model_source_sha" = "$EXPECTED_MODEL_FGA_SHA256" ] || {
  echo "FATAL: OpenFGA source model digest mismatch" >&2
  exit 1
}
ledger_content_sha=$(jq -r '.artifact_content_digest | sub("^sha256:"; "")' "$MODEL_LEDGER")
[ "$model_json_sha" = "$ledger_content_sha" ] || {
  echo "FATAL: canonical OpenFGA model digest does not match runtime ledger" >&2
  exit 1
}

ke() { kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" "$@"; }
pod_get() { ke exec "$POD_DEPLOY" -- curl -fsS "$1"; }
pod_get_page() {
  local endpoint=$1 token=${2:-}
  if [ -n "$token" ]; then
    ke exec "$POD_DEPLOY" -- curl -fsSG "$endpoint" \
      --data-urlencode page_size=100 --data-urlencode "continuation_token=$token"
  else
    ke exec "$POD_DEPLOY" -- curl -fsSG "$endpoint" --data-urlencode page_size=100
  fi
}
pod_post() {
  local endpoint=$1
  ke exec -i "$POD_DEPLOY" -- curl -sS -w '\n%{http_code}' \
    -X POST "$endpoint" -H 'Content-Type: application/json' -d @-
}

collect_pages() {
  local endpoint=$1 array_key=$2 token='' next page accumulated='[]' page_count=0
  while :; do
    page=$(pod_get_page "$endpoint" "$token")
    accumulated=$(jq -nc --argjson accumulated "$accumulated" \
      --argjson page "$page" --arg key "$array_key" \
      '$accumulated + ($page[$key] // [])')
    next=$(printf '%s' "$page" | jq -r '.continuation_token // empty')
    [ -n "$next" ] || break
    [ "$next" != "$token" ] || {
      echo "FATAL: OpenFGA pagination returned a repeated continuation token" >&2
      exit 1
    }
    token=$next
    page_count=$((page_count + 1))
    [ "$page_count" -lt 1000 ] || {
      echo "FATAL: OpenFGA pagination exceeded the bounded page count" >&2
      exit 1
    }
  done
  printf '%s' "$accumulated"
}

ke exec "$POD_DEPLOY" -- sh -c 'command -v curl >/dev/null' || {
  echo "FATAL: curl missing in $POD_DEPLOY" >&2
  exit 1
}

stores=$(collect_pages "$OPENFGA_BASE/stores" stores)
store_matches=$(printf '%s' "$stores" | jq -c --arg n "$STORE_NAME" \
  '[.[] | select(.name==$n)]')
store_count=$(printf '%s' "$store_matches" | jq 'length')
[ "$store_count" -le 1 ] || {
  echo "FATAL: multiple OpenFGA stores use the canonical Etik Speak name" >&2
  exit 1
}
store_id=$(printf '%s' "$store_matches" | jq -r '.[0].id // empty')
if [ -z "$store_id" ]; then
  response=$(jq -nc --arg name "$STORE_NAME" '{name:$name}' | pod_post "$OPENFGA_BASE/stores")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  [ "$code" = 200 ] || [ "$code" = 201 ] || {
    echo "FATAL: OpenFGA store creation HTTP $code" >&2
    exit 1
  }
  store_id=$(printf '%s' "$body" | jq -r '.id // empty')
  stores=$(collect_pages "$OPENFGA_BASE/stores" stores)
  store_matches=$(printf '%s' "$stores" | jq -c --arg n "$STORE_NAME" \
    '[.[] | select(.name==$n)]')
  [ "$(printf '%s' "$store_matches" | jq 'length')" -eq 1 ] && \
    [ "$(printf '%s' "$store_matches" | jq -r '.[0].id')" = "$store_id" ] || {
    echo "FATAL: OpenFGA store uniqueness postcondition failed" >&2
    exit 1
  }
fi
[ -n "$store_id" ] || { echo "FATAL: OpenFGA store id unresolved" >&2; exit 1; }

desired=$(jq -cS . "$MODEL_JSON")
models=$(collect_pages "$OPENFGA_BASE/stores/$store_id/authorization-models" authorization_models)
model_matches=$(printf '%s' "$models" | jq -c --argjson desired "$desired" \
  '[.[] | select(del(.id) == $desired)]')
[ "$(printf '%s' "$model_matches" | jq 'length')" -le 1 ] || {
  echo "FATAL: multiple exact Etik Speak authorization models exist in the canonical store" >&2
  exit 1
}
model_id=$(printf '%s' "$model_matches" | jq -r '.[0].id // empty')
if [ -z "$model_id" ]; then
  response=$(pod_post "$OPENFGA_BASE/stores/$store_id/authorization-models" <"$MODEL_JSON")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  [ "$code" = 200 ] || [ "$code" = 201 ] || {
    echo "FATAL: OpenFGA model write HTTP $code" >&2
    exit 1
  }
  model_id=$(printf '%s' "$body" | jq -r '.authorization_model_id // empty')
  models=$(collect_pages "$OPENFGA_BASE/stores/$store_id/authorization-models" authorization_models)
  model_matches=$(printf '%s' "$models" | jq -c --argjson desired "$desired" \
    '[.[] | select(del(.id) == $desired)]')
  [ "$(printf '%s' "$model_matches" | jq 'length')" -eq 1 ] && \
    [ "$(printf '%s' "$model_matches" | jq -r '.[0].id')" = "$model_id" ] || {
    echo "FATAL: OpenFGA model uniqueness postcondition failed" >&2
    exit 1
  }
fi
[ -n "$model_id" ] || { echo "FATAL: OpenFGA model id unresolved" >&2; exit 1; }

collect_direct_relations() {
  local subject=$1 org_id=$2 token='' next response code body relations='[]' page_count=0 payload
  while :; do
    payload=$(jq -nc --arg user "user:$subject" --arg object "ethics_product:$org_id" \
      --arg token "$token" \
      '{tuple_key:{user:$user,object:$object},page_size:100}
       + (if $token == "" then {} else {continuation_token:$token} end)')
    response=$(printf '%s' "$payload" | pod_post "$OPENFGA_BASE/stores/$store_id/read")
    code=${response##*$'\n'}
    body=${response%$'\n'*}
    [ "$code" = 200 ] || {
      echo "FATAL: direct tuple read HTTP $code" >&2
      exit 1
    }
    relations=$(jq -nc --argjson accumulated "$relations" --argjson page "$body" \
      '$accumulated + [$page.tuples[]?.key.relation]')
    next=$(printf '%s' "$body" | jq -r '.continuation_token // empty')
    [ -n "$next" ] || break
    [ "$next" != "$token" ] || {
      echo "FATAL: OpenFGA tuple read returned a repeated continuation token" >&2
      exit 1
    }
    token=$next
    page_count=$((page_count + 1))
    [ "$page_count" -lt 1000 ] || {
      echo "FATAL: OpenFGA tuple pagination exceeded the bounded page count" >&2
      exit 1
    }
  done
  printf '%s' "$relations" | jq -c 'sort'
}

assert_direct_relation_allowlist() {
  local subject=$1 org_id=$2 expected_json=$3 label=$4 actual
  actual=$(collect_direct_relations "$subject" "$org_id")
  printf '%s' "$actual" | jq -e --argjson expected "$expected_json" '. == ($expected | sort)' >/dev/null || {
    echo "FATAL: $label direct relation set differs from its exact allowlist" >&2
    exit 1
  }
}

assert_direct_relation_subset() {
  local subject=$1 org_id=$2 allowed_json=$3 label=$4 actual
  actual=$(collect_direct_relations "$subject" "$org_id")
  printf '%s' "$actual" | jq -e --argjson allowed "$allowed_json" \
    '(. - $allowed) | length == 0' >/dev/null || {
    echo "FATAL: $label contains a direct relation outside its allowlist" >&2
    exit 1
  }
}

# Fail before mutation if any persona has drifted outside its exact direct
# product relation set. Team-derived effective privileges are checked below.
assert_direct_relation_subset "$STAFF_SUBJECT" "$ETHICS_ORG_ID" \
  '["handler","triager"]' positive-persona-precondition
assert_direct_relation_allowlist "$WRONG_ORG_SUBJECT" "$WRONG_ETHICS_ORG_ID" '[]' wrong-org-object
assert_direct_relation_allowlist "$WRONG_ORG_SUBJECT" "$ETHICS_ORG_ID" '[]' wrong-org-canonical-object
assert_direct_relation_allowlist "$DENIED_SUBJECT" "$ETHICS_ORG_ID" '[]' denied-persona

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
assert_direct_relation_allowlist "$STAFF_SUBJECT" "$ETHICS_ORG_ID" \
  '["handler","triager"]' positive-persona-postcondition

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

# Prove an explicit case deny, not merely the absence of a product grant. This
# persistent synthetic sentinel has no database/narrative counterpart; it
# exists only to verify that a freshly-added recusal defeats an otherwise
# authorized manager through the exact promoted model.
write_exact_tuple() {
  local user=$1 relation=$2 object=$3 response code body
  response=$(jq -nc --arg model "$model_id" --arg user "$user" \
    --arg relation "$relation" --arg object "$object" \
    '{authorization_model_id:$model,writes:{tuple_keys:[{user:$user,relation:$relation,object:$object}]}}' \
    | pod_post "$OPENFGA_BASE/stores/$store_id/write")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  case "$code" in
    200|201) ;;
    400|409) printf '%s' "$body" | grep -qi 'already exist' || {
      echo "FATAL: sentinel tuple write $relation HTTP $code" >&2; exit 1; }
      ;;
    *) echo "FATAL: sentinel tuple write $relation HTTP $code" >&2; exit 1 ;;
  esac
}
sentinel_object="ethics_case:$RECUSAL_SENTINEL_CASE_ID"
write_exact_tuple "ethics_product:$ETHICS_ORG_ID" product "$sentinel_object"
write_exact_tuple "user:$STAFF_SUBJECT" recused "$sentinel_object"
sentinel_response=$(jq -nc --arg model "$model_id" --arg user "user:$STAFF_SUBJECT" \
  --arg object "$sentinel_object" \
  '{authorization_model_id:$model,tuple_key:{user:$user,relation:"case_viewer",object:$object}}' \
  | pod_post "$OPENFGA_BASE/stores/$store_id/check")
sentinel_code=${sentinel_response##*$'\n'}
sentinel_body=${sentinel_response%$'\n'*}
[ "$sentinel_code" = 200 ] && [ "$(printf '%s' "$sentinel_body" | jq -r '.allowed')" = false ] || {
  echo "FATAL: explicit recusal sentinel did not fail closed" >&2
  exit 1
}

check_expected() {
  local subject=$1 relation=$2 org_id=$3 expected=$4 label=$5 response code body
  response=$(jq -nc --arg model "$model_id" --arg user "user:$subject" \
    --arg relation "$relation" --arg object "ethics_product:$org_id" \
    '{authorization_model_id:$model,tuple_key:{user:$user,relation:$relation,object:$object}}' \
    | pod_post "$OPENFGA_BASE/stores/$store_id/check")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  [ "$code" = 200 ] && [ "$(printf '%s' "$body" | jq -r '.allowed')" = "$expected" ] || {
    echo "FATAL: OpenFGA $label expected allowed=$expected" >&2
    exit 1
  }
}
for relation in \
  viewer triager handler technical_admin evidence_approver ethics_product_admin \
  content_denied case_viewer case_triager case_handler evidence_reveal_approved; do
  check_expected "$WRONG_ORG_SUBJECT" "$relation" "$WRONG_ETHICS_ORG_ID" false "wrong-org-object-$relation"
  check_expected "$WRONG_ORG_SUBJECT" "$relation" "$ETHICS_ORG_ID" false "wrong-org-canonical-$relation"
  check_expected "$DENIED_SUBJECT" "$relation" "$ETHICS_ORG_ID" false "denied-persona-$relation"
done
for relation in evidence_approver evidence_reveal_approved ethics_product_admin technical_admin content_denied; do
  check_expected "$STAFF_SUBJECT" "$relation" "$ETHICS_ORG_ID" false "positive-least-privilege-$relation"
done

echo "OpenFGA: isolated store/model; exact positive least privilege, explicit recusal and negative effective-deny postconditions OK"
echo "ETHICS_OPENFGA_STORE_ID=$store_id"
echo "ETHICS_OPENFGA_MODEL_ID=$model_id"
echo "OpenFGA: pin these non-secret IDs plus the canonical digest in GitOps before activation"
