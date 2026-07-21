#!/usr/bin/env bash
# DEPRECATED — DD-EA-2 BOUNDARY VIOLATION. Fail-closed since board #2534.
#
# ## Why this is refused
#
# This helper SSHes to the cluster host and POSTs OpenFGA
# `/stores/<store>/write` directly (see the audit-only body below, ~line 94).
# That writes an authorization tuple while bypassing every product-side
# invariant that makes the grant trustworthy:
#
#   * scope_ref shape validation (a raw write cannot be rejected 400
#     ScopeReferenceInvalid — #2555 Slice B never runs);
#   * ADR-0008 canonical object-id encoding (a hand-written tuple can use any
#     shape, including ones the reader silently drops — this is exactly the
#     #2531 class of bug);
#   * the data_access_scopes DB row, so revoke has nothing to recompute from
#     and the grant becomes unrevokable through the product;
#   * the outbox + audit row, so the grant has no provenance;
#   * the authz version bump, so caches keep serving the pre-grant answer.
#
# It also writes `user:<KC-UUID>` where parts of the plane key on the platform
# numeric id — the #2530 subject drift.
#
# ## The evidence argument (#2534 decision)
#
# A 200 produced by writing OpenFGA directly is NOT evidence that the supported
# product path works. It proves only that OpenFGA accepts writes. Acceptance
# runs that used this script therefore attested to a path no customer can take.
#
# ## What to use instead
#
#   scripts/acceptance/grant-data-access-scope.sh --apply --user <kc-uuid> \
#       --kind PROJECT --ref 1204
#
# which drives POST /api/v1/access/scope — the same call an admin makes — and
# then POLLS /authz/me to prove the grant actually became reachable, rather
# than asserting its own write.
#
# ## Status
#
# Retained (not deleted) so the runbooks and current-state notes citing this
# path resolve to an explanation. The original body is kept verbatim for audit
# and is unreachable.

set -euo pipefail

cat >&2 <<'DEPRECATION'
[openfga-access-tuple-seed] REFUSING TO RUN — DD-EA-2 boundary violation.

  This script POSTs OpenFGA /stores/<store>/write directly, bypassing
  scope_ref validation, ADR-0008 canonical encoding, the data_access_scopes
  row (so the grant cannot be revoked through the product), the audit/outbox
  trail and the authz version bump.

  A 200 obtained this way is NOT evidence the product path works.

  Use instead:
      scripts/acceptance/grant-data-access-scope.sh --apply \
          --user <kc-uuid> --kind PROJECT --ref <id>

  Details: board #2534, and the header of this file.
DEPRECATION
exit 2

# ─────────────────────────────────────────────────────────────────────────────
# AUDIT-ONLY: original implementation, unreachable.
# ─────────────────────────────────────────────────────────────────────────────
if false; then
set -euo pipefail

err() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
info() { printf '\033[1;32m[info]\033[0m %s\n' "$*"; }

: "${ADMIN_UID:?ADMIN_UID is required (admin persona Keycloak UUID)}"
GRANTED_UID="${GRANTED_UID:-}"
SSH_TARGET="${SSH_TARGET:-halil@staging-sw}"
OPENFGA_URL="${OPENFGA_URL:-http://10.44.3.209:8080}"

# UUID format guard (lightweight — RFC 4122 8-4-4-4-12 hex)
uuid_re='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
if [[ ! "$ADMIN_UID" =~ $uuid_re ]]; then
    err "ADMIN_UID '$ADMIN_UID' is not a valid UUID"
    exit 2
fi
if [[ -n "$GRANTED_UID" ]] && [[ ! "$GRANTED_UID" =~ $uuid_re ]]; then
    err "GRANTED_UID '$GRANTED_UID' is not a valid UUID"
    exit 2
fi

# Vault values (run on operator station; never echo to stdout/transcript)
if [[ -z "${STORE_ID:-}" ]]; then
    if ! STORE_ID=$(vault kv get -field=store_id kv/platform/openfga 2>/dev/null); then
        err "Vault unreachable or kv/platform/openfga#store_id missing — supply STORE_ID env or fix Vault"
        exit 3
    fi
fi
if [[ -z "${MODEL_ID:-}" ]]; then
    if ! MODEL_ID=$(vault kv get -field=model_id kv/platform/openfga 2>/dev/null); then
        err "Vault unreachable or kv/platform/openfga#model_id missing — supply MODEL_ID env or fix Vault"
        exit 3
    fi
fi

info "Admin UID: ${ADMIN_UID}"
[[ -n "$GRANTED_UID" ]] && info "Granted UID: ${GRANTED_UID}"
info "OpenFGA URL: ${OPENFGA_URL}"
info "Store ID: ${STORE_ID:0:8}... (truncated)"
info "Model ID: ${MODEL_ID:0:8}... (truncated)"

# Build writes payload — admin gets both can_manage + can_view; granted gets can_view only.
build_writes() {
    local writes='[
      {"user": "user:'"${ADMIN_UID}"'", "relation": "can_manage", "object": "module:ACCESS"},
      {"user": "user:'"${ADMIN_UID}"'", "relation": "can_view",   "object": "module:ACCESS"}'
    if [[ -n "$GRANTED_UID" ]]; then
        writes+=',
      {"user": "user:'"${GRANTED_UID}"'", "relation": "can_view", "object": "module:ACCESS"}'
    fi
    writes+='
    ]'
    cat <<EOF
{
  "authorization_model_id": "${MODEL_ID}",
  "writes": {
    "tuple_keys": ${writes}
  }
}
EOF
}

write_via_ssh() {
    local payload
    payload=$(build_writes)
    info "POST ${OPENFGA_URL}/stores/<store>/write"
    # Allow 409 (already exists) — idempotent retry case
    local body http_code
    body=$(ssh "${SSH_TARGET}" "curl -s -o /tmp/openfga-write.body -w '%{http_code}' -X POST \
        '${OPENFGA_URL}/stores/${STORE_ID}/write' \
        -H 'Content-Type: application/json' \
        -d @- <<'EOJSON'
${payload}
EOJSON
        cat /tmp/openfga-write.body && rm -f /tmp/openfga-write.body" 2>&1) || true
    http_code="${body: -3}"
    body="${body:0:-3}"
    case "$http_code" in
        200|201)
            info "write OK (HTTP $http_code)"
            ;;
        409)
            warn "write returned 409 — tuple(s) already exist; will verify via /check"
            ;;
        *)
            err "write failed (HTTP $http_code): ${body}"
            exit 4
            ;;
    esac
}

check_tuple() {
    local user="$1" relation="$2" object="$3"
    local payload http_code body
    payload=$(cat <<EOF
{
  "authorization_model_id": "${MODEL_ID}",
  "tuple_key": {
    "user": "${user}",
    "relation": "${relation}",
    "object": "${object}"
  }
}
EOF
)
    body=$(ssh "${SSH_TARGET}" "curl -s -o /tmp/openfga-check.body -w '%{http_code}' -X POST \
        '${OPENFGA_URL}/stores/${STORE_ID}/check' \
        -H 'Content-Type: application/json' \
        -d '${payload}'
        cat /tmp/openfga-check.body && rm -f /tmp/openfga-check.body" 2>&1) || true
    http_code="${body: -3}"
    body="${body:0:-3}"
    if [[ "$http_code" != "200" ]]; then
        err "/check failed (HTTP $http_code): ${body}"
        return 1
    fi
    if echo "$body" | grep -qE '"allowed"\s*:\s*true'; then
        info "  ${user} can ${relation} ${object} → ALLOW ✓"
        return 0
    else
        err "  ${user} can ${relation} ${object} → DENY ✗ (body: ${body})"
        return 1
    fi
}

main() {
    write_via_ssh

    info "Verifying via /check..."
    local rc=0
    check_tuple "user:${ADMIN_UID}" "can_manage" "module:ACCESS" || rc=1
    check_tuple "user:${ADMIN_UID}" "can_view"   "module:ACCESS" || rc=1
    if [[ -n "$GRANTED_UID" ]]; then
        check_tuple "user:${GRANTED_UID}" "can_view" "module:ACCESS" || rc=1
    fi

    if [[ $rc -ne 0 ]]; then
        err "Seed verification failed; review /check responses above."
        exit 5
    fi
    info "All seed tuples verified — D35-3 prereq AUTH layer ready."
}

main "$@"

fi
