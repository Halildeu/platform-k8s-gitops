#!/usr/bin/env bash
#
# TEST-only budget OAuth/persona reconciliation.
#
# Effective authorization is deliberately two-key:
#   1. route-requested optional OIDC scopes: budget:read + budget:write
#   2. realm role: budget-planner
#
# budget-service enforces both keys. Optional scope alone is not a user gate in
# Keycloak, so this script never treats client-scope role mappings as security.
# The shared TEST frontend currently projects realm roles with
# fullScopeAllowed=true. Narrowing that shared legacy surface is a separate
# migration because it would affect unrelated modules; this activation only
# adds the dedicated role and relies on the backend's explicit two-key gate.
# budget:approve and budget-approver are intentionally outside this activation.
#
# Usage on aiserver:
#   bash scripts/budget/provision-test-keycloak.sh --check
#   bash scripts/budget/provision-test-keycloak.sh --apply
#   bash scripts/budget/provision-test-keycloak.sh --rollback
#
# The script does not print credentials or tokens.
set -euo pipefail
set +x
umask 077

MODE="${1:---check}"
KC_CONTAINER="${KC_CONTAINER:-platform-kc-test}"
REALM="${REALM:-platform-test}"
FRONTEND_CLIENT="${FRONTEND_CLIENT:-frontend}"
PERSONA_USERNAME="${PERSONA_USERNAME:-admin@example.com}"
ROLE_NAME="budget-planner"
ROLE_DESCRIPTION="TEST budget actuals read and sync operator"
KCADM="/opt/keycloak/bin/kcadm.sh"
SCOPES=("budget:read" "budget:write")

[ "$KC_CONTAINER" = "platform-kc-test" ] &&
  [ "$REALM" = "platform-test" ] &&
  [ "$FRONTEND_CLIENT" = "frontend" ] &&
  [ "$PERSONA_USERNAME" = "admin@example.com" ] || {
  echo "FATAL: TEST Keycloak/persona target override refused" >&2
  exit 1
}

case "$MODE" in
  --check | --apply | --rollback) ;;
  *)
    echo "FATAL: mode must be --check, --apply or --rollback" >&2
    exit 1
    ;;
esac

for command in docker jq awk; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "FATAL: missing command: $command" >&2
    exit 1
  }
done

docker inspect "$KC_CONTAINER" --format '{{.State.Running}}' 2>/dev/null |
  grep -qx true || {
  echo "FATAL: TEST Keycloak container is not running" >&2
  exit 1
}

KCADM_CONFIG=$(docker exec "$KC_CONTAINER" mktemp /tmp/kcadm-budget.XXXXXX)
printf '%s' "$KCADM_CONFIG" |
  grep -Eq '^/tmp/kcadm-budget\.[A-Za-z0-9]+$' || {
  echo "FATAL: isolated kcadm config path contract failed" >&2
  exit 1
}
docker exec "$KC_CONTAINER" chmod 600 "$KCADM_CONFIG"
trap 'docker exec "$KC_CONTAINER" rm -f "$KCADM_CONFIG" >/dev/null 2>&1 || true' EXIT

kc() {
  docker exec "$KC_CONTAINER" "$KCADM" "$@" --config "$KCADM_CONFIG"
}

if ! docker exec -e KC_CONFIG="$KCADM_CONFIG" "$KC_CONTAINER" sh -c '
  set -eu
  [ -n "${KEYCLOAK_ADMIN_PASSWORD_FILE:-}" ]
  [ -r "$KEYCLOAK_ADMIN_PASSWORD_FILE" ]
  KC_CLI_PASSWORD=$(cat "$KEYCLOAK_ADMIN_PASSWORD_FILE")
  [ -n "$KC_CLI_PASSWORD" ]
  export KC_CLI_PASSWORD
  /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 --realm master --user admin \
    --config "$KC_CONFIG" >/dev/null 2>&1
  unset KC_CLI_PASSWORD
'; then
  echo "FATAL: isolated TEST Keycloak admin login failed" >&2
  exit 1
fi

kc get "realms/$REALM" --fields realm |
  jq -e --arg realm "$REALM" '.realm == $realm' >/dev/null || {
  echo "FATAL: realm guard failed" >&2
  exit 1
}

FRONTEND_UUID=$(kc get clients -r "$REALM" -q "clientId=$FRONTEND_CLIENT" --fields id,clientId |
  jq -er --arg client "$FRONTEND_CLIENT" '
    select(length == 1 and .[0].clientId == $client) | .[0].id
  ')
FRONTEND_SECURITY_JSON=$(kc get "clients/$FRONTEND_UUID" -r "$REALM" \
  --fields clientId,publicClient,fullScopeAllowed)
printf '%s' "$FRONTEND_SECURITY_JSON" | jq -e --arg client "$FRONTEND_CLIENT" '
    .clientId == $client and .publicClient == true and .fullScopeAllowed == true
  ' >/dev/null || {
  printf '%s' "$FRONTEND_SECURITY_JSON" |
    jq -r '"FATAL: frontend flags drift publicClient=\(.publicClient) fullScopeAllowed=\(.fullScopeAllowed)"'
  exit 1
}

USER_JSON=$(kc get users -r "$REALM" -q "username=$PERSONA_USERNAME" --fields id,username,enabled)
USER_UUID=$(printf '%s' "$USER_JSON" |
  jq -er --arg username "$PERSONA_USERNAME" '
    select(length == 1 and .[0].username == $username and .[0].enabled == true) | .[0].id
  ') || {
  echo "FATAL: exact enabled TEST persona not found" >&2
  exit 1
}

scope_id() {
  local name=$1
  kc get client-scopes -r "$REALM" --fields id,name |
    jq -r --arg name "$name" '
      [.[] | select(.name == $name)] |
      if length == 0 then "" elif length == 1 then .[0].id else error("duplicate scope") end
    '
}

scope_is_optional() {
  local id=$1
  kc get "clients/$FRONTEND_UUID/optional-client-scopes" -r "$REALM" --fields id |
    jq -e --arg id "$id" 'any(.[]; .id == $id)' >/dev/null
}

scope_is_default() {
  local id=$1
  kc get "clients/$FRONTEND_UUID/default-client-scopes" -r "$REALM" --fields id |
    jq -e --arg id "$id" 'any(.[]; .id == $id)' >/dev/null
}

role_exists() {
  kc get "roles/$ROLE_NAME" -r "$REALM" >/dev/null 2>&1
}

role_is_assigned() {
  kc get "users/$USER_UUID/role-mappings/realm" -r "$REALM" --fields name |
    jq -e --arg role "$ROLE_NAME" 'any(.[]; .name == $role)' >/dev/null
}

verify_role_shape() {
  kc get "roles/$ROLE_NAME" -r "$REALM" |
    jq -e --arg name "$ROLE_NAME" --arg description "$ROLE_DESCRIPTION" '
      .name == $name and .description == $description and
      .clientRole == false and .composite == false
    ' >/dev/null
}

verify_scope_shape() {
  local name=$1 id=$2
  kc get "client-scopes/$id" -r "$REALM" |
    jq -e --arg name "$name" '
      .name == $name and .protocol == "openid-connect" and
      .attributes["include.in.token.scope"] == "true" and
      .attributes["display.on.consent.screen"] == "false"
    ' >/dev/null
  kc get "client-scopes/$id/protocol-mappers/models" -r "$REALM" |
    jq -e 'length == 0' >/dev/null
  ! scope_is_default "$id"
}

check_state() {
  local failures=0 id
  role_exists && verify_role_shape && role_is_assigned || failures=$((failures + 1))
  for name in "${SCOPES[@]}"; do
    id=$(scope_id "$name")
    if [ -z "$id" ] || ! verify_scope_shape "$name" "$id" || ! scope_is_optional "$id"; then
      failures=$((failures + 1))
    fi
  done
  if [ "$failures" -eq 0 ]; then
    echo "CONVERGED: role=budget-planner scopes=budget:read,budget:write binding=optional approve=absent"
    return 0
  fi
  echo "DRIFT: budget TEST OAuth/persona contract is not converged ($failures check failures)"
  return 2
}

create_scope() {
  local name=$1
  kc create client-scopes -r "$REALM" \
    -s "name=$name" \
    -s 'protocol=openid-connect' \
    -s 'attributes={"include.in.token.scope":"true","display.on.consent.screen":"false"}' \
    >/dev/null
}

case "$MODE" in
  --check)
    check_state
    ;;
  --apply)
    if ! role_exists; then
      kc create roles -r "$REALM" \
        -s "name=$ROLE_NAME" \
        -s "description=$ROLE_DESCRIPTION" >/dev/null
    fi
    verify_role_shape || {
      echo "FATAL: existing budget-planner role drift" >&2
      exit 1
    }
    for name in "${SCOPES[@]}"; do
      id=$(scope_id "$name")
      if [ -z "$id" ]; then
        create_scope "$name"
        id=$(scope_id "$name")
      fi
      verify_scope_shape "$name" "$id" || {
        echo "FATAL: existing client scope drift: $name" >&2
        exit 1
      }
      if ! scope_is_optional "$id"; then
        # Keycloak models this association as an idempotent PUT. `kcadm
        # create` issues POST and the admin API rejects that method/path with
        # 404 even when both UUIDs exist.
        kc update "clients/$FRONTEND_UUID/optional-client-scopes/$id" -r "$REALM" >/dev/null
      fi
    done
    if ! role_is_assigned; then
      kc add-roles -r "$REALM" --uid "$USER_UUID" --rolename "$ROLE_NAME"
    fi
    check_state
    ;;
  --rollback)
    if role_exists && role_is_assigned; then
      kc remove-roles -r "$REALM" --uid "$USER_UUID" --rolename "$ROLE_NAME"
    fi
    for name in "${SCOPES[@]}"; do
      id=$(scope_id "$name")
      if [ -n "$id" ] && scope_is_optional "$id"; then
        kc delete "clients/$FRONTEND_UUID/optional-client-scopes/$id" -r "$REALM"
      fi
    done
    echo "ROLLED_BACK: persona role and frontend optional bindings removed; inert realm objects preserved"
    ;;
esac
