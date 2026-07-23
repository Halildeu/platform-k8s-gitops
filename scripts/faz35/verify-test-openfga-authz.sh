#!/usr/bin/env bash
# Read-only, host-side Faz 35 TEST authorization proof. This script is sent to
# aiserver over SSH by preflight-test-activation.sh; it never prints tokens,
# passwords or resolved subject IDs.
set -euo pipefail
set +x
umask 077

STORE_ID="${1:-}"
MODEL_ID="${2:-}"
KUBE_CONTEXT="k3d-test"
KUBE_NS="platform-test"
POD_DEPLOY="deploy/meeting-service"
OPENFGA_BASE="http://openfga:8080"
KC_BASE_URL="http://127.0.0.1:8082"
KC_REALM="platform-test"
KC_EXPECTED_ISSUER="https://testai.acik.com/realms/platform-test"
ETHICS_ORG_ID="00000000-0000-0000-0000-000000000001"
WRONG_ETHICS_ORG_ID="00000000-0000-0000-0000-000000000002"
RECUSAL_SENTINEL_CASE_ID="00000000-0000-0000-0000-000000000035"

printf '%s' "$STORE_ID$MODEL_ID" | grep -Eq '^[0-9A-HJKMNP-TV-Z]{52}$' || {
  echo "FATAL: OpenFGA proof requires canonical pinned store/model ULIDs" >&2
  exit 1
}
for command_name in curl jq python3 kubectl mktemp stat; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "FATAL: OpenFGA proof dependency missing: $command_name" >&2
    exit 1
  }
done

TMP_DIR=$(mktemp -d /tmp/faz35-openfga-readonly.XXXXXX)
trap 'find "$TMP_DIR" -type f -delete 2>/dev/null || true; find "$TMP_DIR" -depth -type d -empty -delete 2>/dev/null || true' EXIT

resolve_persona_subject() {
  local username=$1 password_file=$2 expected_org=$3 label=$4
  local token_file="$TMP_DIR/$label-token.json" claims_file="$TMP_DIR/$label-claims.json" code
  [ -r "$password_file" ] && [ -f "$password_file" ] && [ ! -L "$password_file" ] || {
    echo "FATAL: $label password file is not a readable regular non-symlink" >&2
    exit 1
  }
  [ "$(stat -c '%u' "$password_file")" = "$(id -u)" ] && \
    [ "$(stat -c '%a' "$password_file")" = 600 ] || {
    echo "FATAL: $label password file must be invoking-user-owned mode 600" >&2
    exit 1
  }
  code=$(curl -sS --max-time 15 -o "$token_file" -w '%{http_code}' \
    -X POST "$KC_BASE_URL/realms/$KC_REALM/protocol/openid-connect/token" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode 'grant_type=password' \
    --data-urlencode 'client_id=frontend' \
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
parts = sys.stdin.read().strip().split(".")
if len(parts) != 3:
    raise SystemExit(1)
payload = parts[1] + "=" * (-len(parts[1]) % 4)
claims = json.loads(base64.urlsafe_b64decode(payload))
print(json.dumps({
    "iss": claims.get("iss"),
    "sub": claims.get("sub"),
    "preferred_username": claims.get("preferred_username"),
    "org_id": claims.get("org_id"),
    "azp": claims.get("azp"),
    "roles": claims.get("realm_access", {}).get("roles", []),
}, separators=(",", ":")))
' >"$claims_file" || {
    echo "FATAL: $label live Keycloak token is not a valid JWT" >&2
    exit 1
  }
  jq -e --arg issuer "$KC_EXPECTED_ISSUER" --arg username "$username" \
    --arg org "$expected_org" '
      .iss == $issuer and
      (.sub | type == "string" and test("^[0-9A-Fa-f-]{36}$")) and
      .preferred_username == $username and .org_id == $org and
      .azp == "frontend" and
      (.roles | type == "array" and index("ethics-manager") != null)
    ' "$claims_file" >/dev/null || {
    echo "FATAL: $label no longer matches the fixed TEST Keycloak persona" >&2
    exit 1
  }
  jq -r '.sub' "$claims_file"
}

STAFF_SUBJECT=$(resolve_persona_subject ethics-manager-test \
  /srv/platform/secrets/faz35-test/ethics-manager-test.password "$ETHICS_ORG_ID" staff)
WRONG_ORG_SUBJECT=$(resolve_persona_subject ethics-manager-wrong-org-test \
  /srv/platform/secrets/faz35-test/ethics-manager-wrong-org-test.password "$WRONG_ETHICS_ORG_ID" wrong-org)
DENIED_SUBJECT=$(resolve_persona_subject ethics-manager-denied-test \
  /srv/platform/secrets/faz35-test/ethics-manager-denied-test.password "$ETHICS_ORG_ID" denied)
[ "$STAFF_SUBJECT" != "$WRONG_ORG_SUBJECT" ] && \
  [ "$STAFF_SUBJECT" != "$DENIED_SUBJECT" ] && \
  [ "$WRONG_ORG_SUBJECT" != "$DENIED_SUBJECT" ] || {
  echo "FATAL: TEST OpenFGA proof personas are not distinct" >&2
  exit 1
}

ke() { kubectl --request-timeout=15s --context "$KUBE_CONTEXT" -n "$KUBE_NS" "$@"; }
pod_post() {
  local endpoint=$1
  ke exec -i "$POD_DEPLOY" -- curl --connect-timeout 5 --max-time 15 -sS \
    -w '\n%{http_code}' -X POST "$endpoint" -H 'Content-Type: application/json' -d @-
}

collect_direct_relations() {
  local subject=$1 object=$2 token='' response code body next relations='[]' page_count=0 payload
  while :; do
    payload=$(jq -nc --arg user "user:$subject" --arg object "$object" --arg token "$token" \
      '{tuple_key:{user:$user,object:$object},page_size:100}
       + (if $token == "" then {} else {continuation_token:$token} end)')
    response=$(printf '%s' "$payload" | pod_post "$OPENFGA_BASE/stores/$STORE_ID/read")
    code=${response##*$'\n'}
    body=${response%$'\n'*}
    if [ "$code" != 200 ] || ! printf '%s' "$body" | jq -e \
        '.tuples | type == "array"' >/dev/null; then
      echo "FATAL: OpenFGA direct tuple read failed" >&2
      exit 1
    fi
    relations=$(jq -nc --argjson accumulated "$relations" --argjson page "$body" \
      '$accumulated + ($page.tuples | map(.key.relation))')
    next=$(printf '%s' "$body" | jq -r '.continuation_token // ""')
    [ -n "$next" ] || break
    [ "$next" != "$token" ] || { echo "FATAL: repeated OpenFGA continuation token" >&2; exit 1; }
    token=$next
    page_count=$((page_count + 1))
    [ "$page_count" -lt 1000 ] || { echo "FATAL: OpenFGA tuple pagination overflow" >&2; exit 1; }
  done
  printf '%s' "$relations" | jq -c 'sort'
}

assert_relation_set() {
  local subject=$1 object=$2 expected=$3 label=$4 actual
  actual=$(collect_direct_relations "$subject" "$object")
  printf '%s' "$actual" | jq -e --argjson expected "$expected" \
    '. == ($expected | sort)' >/dev/null || {
    echo "FATAL: $label direct relations drifted from the exact allowlist" >&2
    exit 1
  }
}

check_expected() {
  local subject=$1 relation=$2 object=$3 expected=$4 label=$5 response code body
  response=$(jq -nc --arg model "$MODEL_ID" --arg user "user:$subject" \
    --arg relation "$relation" --arg object "$object" \
    '{authorization_model_id:$model,tuple_key:{user:$user,relation:$relation,object:$object}}' \
    | pod_post "$OPENFGA_BASE/stores/$STORE_ID/check")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  [ "$code" = 200 ] && [ "$(printf '%s' "$body" | jq -r '.allowed')" = "$expected" ] || {
    echo "FATAL: OpenFGA $label expected allowed=$expected" >&2
    exit 1
  }
}

assert_exact_tuple() {
  local user=$1 relation=$2 object=$3 label=$4 response code body
  response=$(jq -nc --arg user "$user" --arg relation "$relation" --arg object "$object" \
    '{tuple_key:{user:$user,relation:$relation,object:$object},page_size:2}' \
    | pod_post "$OPENFGA_BASE/stores/$STORE_ID/read")
  code=${response##*$'\n'}
  body=${response%$'\n'*}
  if [ "$code" != 200 ] || ! printf '%s' "$body" | jq -e \
    --arg user "$user" --arg relation "$relation" --arg object "$object" '
      (.tuples | length) == 1 and
      .tuples[0].key.user == $user and
      .tuples[0].key.relation == $relation and
      .tuples[0].key.object == $object
    ' >/dev/null; then
    echo "FATAL: explicit $label sentinel tuple is missing or ambiguous" >&2
    exit 1
  fi
}

canonical_product="ethics_product:$ETHICS_ORG_ID"
wrong_product="ethics_product:$WRONG_ETHICS_ORG_ID"
sentinel_case="ethics_case:$RECUSAL_SENTINEL_CASE_ID"
assert_relation_set "$STAFF_SUBJECT" "$canonical_product" '["handler","triager"]' staff
assert_relation_set "$WRONG_ORG_SUBJECT" "$wrong_product" '[]' wrong-org-object
assert_relation_set "$WRONG_ORG_SUBJECT" "$canonical_product" '[]' wrong-org-canonical-object
assert_relation_set "$DENIED_SUBJECT" "$canonical_product" '[]' denied-persona

for relation in case_viewer case_triager case_handler; do
  check_expected "$STAFF_SUBJECT" "$relation" "$canonical_product" true "staff-$relation"
done
for relation in viewer triager handler technical_admin evidence_approver \
  ethics_product_admin content_denied case_viewer case_triager case_handler \
  evidence_reveal_approved; do
  check_expected "$WRONG_ORG_SUBJECT" "$relation" "$wrong_product" false "wrong-org-object-$relation"
  check_expected "$WRONG_ORG_SUBJECT" "$relation" "$canonical_product" false "wrong-org-canonical-$relation"
  check_expected "$DENIED_SUBJECT" "$relation" "$canonical_product" false "denied-persona-$relation"
done
for relation in evidence_approver evidence_reveal_approved ethics_product_admin \
  technical_admin content_denied; do
  check_expected "$STAFF_SUBJECT" "$relation" "$canonical_product" false "staff-least-privilege-$relation"
done

assert_exact_tuple "ethics_product:$ETHICS_ORG_ID" product "$sentinel_case" recusal-product
assert_exact_tuple "user:$STAFF_SUBJECT" recused "$sentinel_case" recusal-user
check_expected "$STAFF_SUBJECT" case_viewer "$sentinel_case" false recusal-sentinel

echo "OpenFGA authorization: live read-only persona, tuple, allow, deny and recusal proofs PASS"
