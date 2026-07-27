#!/usr/bin/env bash
# Faz 35 Etik Speak: create/reuse the isolated test store, promote the exact
# compiled model and bind the synthetic staff subject. Store/model IDs are
# non-secret outputs that must be pinned in GitOps by a new reviewed commit.
#
# A2c MIGRATION (2026-07-27, Faz 22 Sec KC hardening #2476): this script now mints
# via the dedicated confidential `smoke-client`, not the public browser client. Two
# reasons, both measured on `platform-test`:
#
#   1. `frontend` is a SHARED browser client, so its token carries whatever every other
#      feature has bolted on. The exact-set pin below had drifted and this script was
#      FAILING before the migration: the live token had gained `ats.screening.read` +
#      `ats.screening.write` (ATS work, unrelated to Etik Speak) and `requires-mfa`
#      (privileged-role composite). Pinning a shared client lets an unrelated feature
#      break ETHICS provisioning, and it did.
#   2. A2c turns `frontend.directAccessGrantsEnabled` off, so ROPC through it stops
#      working entirely.
#
# Measured claim delta, identical for all three ETHICS personas (org_id aside):
#   azp   frontend -> smoke-client
#   aud   9 -> 7   drops ats-api/audio-gateway-service/frontend/meeting-service/
#                  remote-bridge-operator-api; gains endpoint-admin-service/
#                  permission-service/variant-service via smoke-runtime-v1
#   scope 21 -> 5  drops all 16 ats.* + notify-canary; `ethics:case:manage` PRESERVED
#   roles 5 -> 2   drops default-roles-platform-test/offline_access/uma_authorization
#   resource_access {account:[...]} -> {}
#
# The `ethics-manager` audience and the `ethics:case:manage` scope both survive, which
# is what this script actually needs. The narrower token makes the least-privilege
# proof stronger, not weaker.
#
# The client secret is supplied BY THE CALLER as a file. This script deliberately does
# not read it from Vault: tests/deploy/test_faz35_etikspeak_provisioning_contract.py
# forbids this script from touching the Vault root token, and that boundary is correct.
set -euo pipefail
# A caller may invoke bash -x; disable tracing before any credential is read.
set +x
umask 077

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/faz35/lib-test-keycloak-binding.sh
source "$SCRIPT_DIR/lib-test-keycloak-binding.sh"
# shellcheck source=scripts/faz35/lib-openfga-model-normalization.sh
source "$SCRIPT_DIR/lib-openfga-model-normalization.sh"
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
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
KC_BASE_URL="${KC_BASE_URL:-http://127.0.0.1:8082}"
KC_REALM="${KC_REALM:-platform-test}"
KC_EXPECTED_ISSUER="https://testai.acik.com/realms/platform-test"
STAFF_USERNAME="${STAFF_USERNAME:-ethics-manager-test}"
SMOKE_CLIENT_SECRET_FILE_DEFAULT="/srv/platform/secrets/faz35-test/smoke-client.secret"
[ -r "$SMOKE_CLIENT_SECRET_FILE_DEFAULT" ] \
  || SMOKE_CLIENT_SECRET_FILE_DEFAULT="$HOME/bootstrap-drill/smoke-client.secret"
SMOKE_CLIENT_SECRET_FILE="${SMOKE_CLIENT_SECRET_FILE:-$SMOKE_CLIENT_SECRET_FILE_DEFAULT}"
STAFF_PASSWORD_FILE="${STAFF_PASSWORD_FILE:-/srv/platform/secrets/faz35-test/ethics-manager-test.password}"
WRONG_ORG_USERNAME="${WRONG_ORG_USERNAME:-ethics-manager-wrong-org-test}"
WRONG_ORG_PASSWORD_FILE="${WRONG_ORG_PASSWORD_FILE:-/srv/platform/secrets/faz35-test/ethics-manager-wrong-org-test.password}"
DENIED_USERNAME="${DENIED_USERNAME:-ethics-manager-denied-test}"
DENIED_PASSWORD_FILE="${DENIED_PASSWORD_FILE:-/srv/platform/secrets/faz35-test/ethics-manager-denied-test.password}"
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
  "$WRONG_ETHICS_ORG_ID=00000000-0000-0000-0000-000000000002" \
  "$KC_CONTAINER=platform-kc-test" \
  "$KC_BASE_URL=http://127.0.0.1:8082" \
  "$KC_REALM=platform-test" \
  "$STAFF_USERNAME=ethics-manager-test" \
  "$STAFF_PASSWORD_FILE=/srv/platform/secrets/faz35-test/ethics-manager-test.password" \
  "$WRONG_ORG_USERNAME=ethics-manager-wrong-org-test" \
  "$WRONG_ORG_PASSWORD_FILE=/srv/platform/secrets/faz35-test/ethics-manager-wrong-org-test.password" \
  "$DENIED_USERNAME=ethics-manager-denied-test" \
  "$DENIED_PASSWORD_FILE=/srv/platform/secrets/faz35-test/ethics-manager-denied-test.password"; do
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
for command_name in curl docker jq mktemp python3 stat; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "FATAL: required command missing: $command_name" >&2
    exit 1
  }
done
faz35_assert_test_keycloak_binding \
  "$KC_CONTAINER" "$KC_BASE_URL" "$KC_REALM" "$KC_EXPECTED_ISSUER" || {
  echo "FATAL: TEST Keycloak container/loopback/issuer binding is invalid" >&2
  exit 1
}

SUBJECT_TMP_DIR=$(mktemp -d /tmp/faz35-openfga-subjects.XXXXXX)
trap 'find "$SUBJECT_TMP_DIR" -type f -delete 2>/dev/null || true; find "$SUBJECT_TMP_DIR" -depth -type d -empty -delete 2>/dev/null || true' EXIT

validate_persona_password_file() {
  local file=$1 label=$2
  [ -r "$file" ] && [ -f "$file" ] && [ ! -L "$file" ] || {
    echo "FATAL: $label password must be a readable regular non-symlink" >&2
    exit 1
  }
  [ "$(stat -c '%u' "$file")" = "$(id -u)" ] && \
    [ "$(stat -c '%a' "$file")" = 600 ] || {
    echo "FATAL: $label password must be invoking-user-owned mode 600" >&2
    exit 1
  }
}

assert_subject_persona_binding() {
  local username=$1 password_file=$2 expected_subject=$3 expected_org=$4 label=$5 code
  local token_file="$SUBJECT_TMP_DIR/$label-token.json"
  local claims_file="$SUBJECT_TMP_DIR/$label-claims.json"
  validate_persona_password_file "$password_file" "$label"
  validate_persona_password_file "$SMOKE_CLIENT_SECRET_FILE" "smoke-client secret"
  code=$(curl -sS --max-time 15 -o "$token_file" -w '%{http_code}' \
    -X POST "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=smoke-client' \
    --data-urlencode "client_secret@$SMOKE_CLIENT_SECRET_FILE" \
    --data-urlencode "username=$username" \
    --data-urlencode "password@$password_file" \
    --data-urlencode 'scope=openid ethics-manager-audience ethics:case:manage' || printf '000')
  if [ "$code" != 200 ] || ! jq -e \
      '.access_token | type == "string" and length > 0' "$token_file" >/dev/null; then
    echo "FATAL: $label live Keycloak authentication failed" >&2
    exit 1
  fi
  jq -j '.access_token' "$token_file" | python3 -c '
import base64, json, sys
token = sys.stdin.read().strip().split(".")
if len(token) != 3:
    raise SystemExit(1)
payload = token[1] + "=" * (-len(token[1]) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))
print(json.dumps({
    "iss": claims.get("iss"),
    "sub": claims.get("sub"),
    "preferred_username": claims.get("preferred_username"),
    "org_id": claims.get("org_id"),
    "aud": claims.get("aud"),
    "azp": claims.get("azp"),
    "scope": claims.get("scope"),
    "roles": claims.get("realm_access", {}).get("roles", []),
    "resource_roles": claims.get("resource_access", {}),
    "groups": claims.get("groups", []),
    "has_authorization": "authorization" in claims,
}, separators=(",", ":")))
' >"$claims_file" || {
    echo "FATAL: $label live Keycloak token is not a valid JWT" >&2
    exit 1
  }
  jq -e --arg issuer "$KC_EXPECTED_ISSUER" --arg subject "$expected_subject" \
    --arg username "$username" --arg org "$expected_org" '
      .iss == $issuer and .sub == $subject and
      .preferred_username == $username and .org_id == $org and
      .azp == "smoke-client" and
      ((.aud | type) == "array") and
      ((.aud | sort) == ([
        "account", "auth-service", "endpoint-admin-service", "ethics-manager",
        "notification-orchestrator", "permission-service", "variant-service"
      ] | sort)) and
      ((.scope | type) == "string") and
      ((.scope | split(" ") | sort) == ([
        "email", "ethics:case:manage", "openid", "profile", "smoke-runtime-v1"
      ] | sort)) and
      ((.roles | type) == "array") and
      ((.roles | sort) == (["ethics-manager", "requires-mfa"] | sort)) and
      ((.resource_roles | keys | sort) == []) and
      ((.groups | type) == "array" and (.groups | length) == 0) and
      (.has_authorization == false)
    ' "$claims_file" >/dev/null || {
    echo "FATAL: $label subject/token does not match the exact least-privilege Keycloak persona contract" >&2
    exit 1
  }
}

assert_subject_persona_binding "$STAFF_USERNAME" "$STAFF_PASSWORD_FILE" \
  "$STAFF_SUBJECT" "$ETHICS_ORG_ID" staff
assert_subject_persona_binding "$WRONG_ORG_USERNAME" "$WRONG_ORG_PASSWORD_FILE" \
  "$WRONG_ORG_SUBJECT" "$WRONG_ETHICS_ORG_ID" wrong-org
assert_subject_persona_binding "$DENIED_USERNAME" "$DENIED_PASSWORD_FILE" \
  "$DENIED_SUBJECT" "$ETHICS_ORG_ID" denied

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
    printf '%s' "$page" | jq -e --arg key "$array_key" '
      type == "object" and has($key) and
      ((.[$key] | type) == "array") and
      has("continuation_token") and
      ((.continuation_token | type) == "string") and
      (if $key == "stores" then
         all(.[$key][];
           type == "object" and
           (.id | type == "string" and test("^[0-9A-HJKMNP-TV-Z]{26}$")) and
           (.name | type == "string" and length > 0) and
           .deleted_at == null)
       elif $key == "authorization_models" then
         all(.[$key][];
           type == "object" and
           (.id | type == "string" and test("^[0-9A-HJKMNP-TV-Z]{26}$")) and
           .schema_version == "1.1" and
           ((.type_definitions | type) == "array") and
           ((.type_definitions | length) > 0))
       else false end)
    ' >/dev/null || {
      echo "FATAL: OpenFGA $array_key page violates the exact response contract" >&2
      exit 1
    }
    accumulated=$(jq -nc --argjson accumulated "$accumulated" \
      --argjson page "$page" --arg key "$array_key" \
      '$accumulated + $page[$key]')
    next=$(printf '%s' "$page" | jq -r '.continuation_token')
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
desired_normalized=$(printf '%s' "$desired" | faz35_normalize_openfga_model)
models=$(collect_pages "$OPENFGA_BASE/stores/$store_id/authorization-models" authorization_models)
model_matches=$(printf '%s' "$models" | \
  faz35_select_equivalent_openfga_models "$desired_normalized")
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
  model_matches=$(printf '%s' "$models" | \
    faz35_select_equivalent_openfga_models "$desired_normalized")
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
    if ! printf '%s' "$body" | jq -e '
      type == "object" and
      has("tuples") and
      ((keys - ["continuation_token", "tuples"]) | length) == 0 and
      ((has("continuation_token") | not) or
       ((.continuation_token | type) == "string")) and
      (.tuples | type) == "array" and
      all(.tuples[];
        type == "object" and
        ((keys | sort) == ["key", "timestamp"]) and
        (.timestamp | type) == "string" and (.timestamp | length) > 0 and
        (.key | type) == "object" and
        ((.key | keys - ["condition", "object", "relation", "user"]) | length) == 0 and
        (.key | has("object") and has("relation") and has("user")) and
        ((.key | has("condition") | not) or .key.condition == null) and
        (.key.object | type) == "string" and (.key.object | length) > 0 and
        (.key.relation | type) == "string" and (.key.relation | length) > 0 and
        (.key.user | type) == "string" and (.key.user | length) > 0
      )
    ' >/dev/null; then
      echo "FATAL: direct tuple read response schema mismatch" >&2
      exit 1
    fi
    relations=$(jq -nc --argjson accumulated "$relations" --argjson page "$body" \
      '$accumulated + ($page.tuples | map(.key.relation))')
    next=$(printf '%s' "$body" | jq -r '.continuation_token // ""')
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
