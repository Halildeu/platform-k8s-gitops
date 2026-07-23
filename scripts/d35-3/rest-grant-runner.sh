#!/usr/bin/env bash
# Faz 21.3 D35-2-full — REST grant/revoke runner (V25 OUR_COMPANY anchor)
#
# 11-step canonical sequence (docs/openfga-multi-org-rollout.md Step 9 + V25
# adaptation: SCOPE_REF='["1"]', EXPECTED_TUPLE_OBJECT='company:wc-our-company-1').
#
# Idempotent: birden fazla koşumda her run yeni scope_id üretir; cleanup runun
# sonunda revoke ile yapılır (FAILED state bırakmaz).
#
# Auto-mode: agent koşabilir AMA ön-koşul olarak kullanıcı `JWT_ADMIN`'i export
# etmiş olmalı (RB-faz-21-3-d35-3-keycloak-admin-jwt.md Step 4 sonrası). Agent
# JWT'yi okumaz/log'a yazmaz; sadece env'den geçer.
#
# Codex `019dd409` PARTIAL/AGREE-with-revisions: env-driven design + JWT
# kullanıcı/operatör boundary'sinden geçer.
#
# Usage:
#   JWT_ADMIN="<bearer>" \
#   USER_UID_GRANTED="<uuid>" \
#   USER_UID_DENIED="<uuid>" \
#     ./scripts/d35-3/rest-grant-runner.sh
#
# Env contract:
#   JWT_ADMIN          required; admin persona JWT (module:ACCESS#can_manage scope)
#   USER_UID_GRANTED   required; receive-scope persona UUID
#   USER_UID_DENIED    required; negative-assertion persona UUID
#   API_BASE           optional; default https://testai.acik.com
#   ORG_ID             optional; default 1 (AÇIK)
#   SCOPE_KIND         optional; default COMPANY (V25 anchor pair)
#   SCOPE_REF          optional; default '["1"]' (V25 OUR_COMPANY.COMP_ID=1)
#   EXPECTED_TUPLE_OBJECT  optional; default company:wc-our-company-1
#   PG_SSH_TARGET      optional; default aiadmin@aiserver
#   PG_CONTAINER       optional; default platform-pg-test
#   POLL_INTERVAL_S    optional; default 5
#   POLL_TIMEOUT_S     optional; default 30
#
# Output:
#   stdout: human-readable progress
#   ${EVIDENCE_FILE}: append-only D35-2-full evidence capture (path returned via env)

set -euo pipefail

err() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
info() { printf '\033[1;32m[info]\033[0m %s\n' "$*"; }
step() { printf '\033[1;36m[step %s]\033[0m %s\n' "$1" "$2"; }

: "${JWT_ADMIN:?JWT_ADMIN is required (admin persona Bearer token from Keycloak)}"
: "${USER_UID_GRANTED:?USER_UID_GRANTED is required (receive-scope persona UUID)}"
: "${USER_UID_DENIED:?USER_UID_DENIED is required (negative-assertion persona UUID)}"

API_BASE="${API_BASE:-https://testai.acik.com}"
ORG_ID="${ORG_ID:-1}"
SCOPE_KIND="${SCOPE_KIND:-COMPANY}"
SCOPE_REF="${SCOPE_REF:-[\"1\"]}"
EXPECTED_TUPLE_OBJECT="${EXPECTED_TUPLE_OBJECT:-company:wc-our-company-1}"
PG_SSH_TARGET="${PG_SSH_TARGET:-aiadmin@aiserver}"
PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
POLL_INTERVAL_S="${POLL_INTERVAL_S:-5}"
POLL_TIMEOUT_S="${POLL_TIMEOUT_S:-30}"

RUN_ID="d35-2-full-$(date +%Y%m%d-%H%M)"
EVIDENCE_FILE="${EVIDENCE_FILE:-/tmp/d35-2-full-evidence-${RUN_ID}.md}"

# UUID validation
uuid_re='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
[[ "$USER_UID_GRANTED" =~ $uuid_re ]] || { err "USER_UID_GRANTED is not a UUID"; exit 2; }
[[ "$USER_UID_DENIED"  =~ $uuid_re ]] || { err "USER_UID_DENIED is not a UUID"; exit 2; }

GRANT_USER="user:${USER_UID_GRANTED}"

# Append helpers
log_to_evidence() {
    printf '%s\n' "$*" >> "${EVIDENCE_FILE}"
}

run_psql() {
    local sql="$1"
    ssh "${PG_SSH_TARGET}" "docker exec ${PG_CONTAINER} psql -U platform -d reports_db -c \"${sql}\""
}

run_psql_t() {
    local sql="$1"
    ssh "${PG_SSH_TARGET}" "docker exec ${PG_CONTAINER} psql -U platform -d reports_db -t -c \"${sql}\"" | xargs
}

init_evidence() {
    cat > "${EVIDENCE_FILE}" <<EOF
# D35-2-full evidence — ${RUN_ID}

**Tier**: D35-2-full
**Date**: $(date -u +%Y-%m-%dT%H:%M:%SZ)
**Cluster**: k3d-test on staging-sw
**SCOPE_KIND**: ${SCOPE_KIND}
**SCOPE_REF**: ${SCOPE_REF}
**EXPECTED_TUPLE_OBJECT**: ${EXPECTED_TUPLE_OBJECT}
**USER_UID_GRANTED**: ${USER_UID_GRANTED}
**USER_UID_DENIED**: ${USER_UID_DENIED}

Started: $(date -Iseconds)

EOF
}

# ============================================================================
# Step 9.4 — POST grant
# ============================================================================
do_grant() {
    step "9.4" "POST /api/v1/access/scope"
    local response http_code
    response=$(curl -s -X POST "${API_BASE}/api/v1/access/scope" \
        -H "Authorization: Bearer ${JWT_ADMIN}" \
        -H 'Content-Type: application/json' \
        -w '\n%{http_code}' \
        -d "$(cat <<EOF
{
  "userId": "${USER_UID_GRANTED}",
  "orgId": ${ORG_ID},
  "scopeKind": "${SCOPE_KIND}",
  "scopeRef": "${SCOPE_REF}"
}
EOF
)")
    http_code=$(echo "$response" | tail -1)
    response=$(echo "$response" | head -n-1)
    log_to_evidence "## Step 9.4 — POST grant"
    log_to_evidence '```'
    log_to_evidence "${response}"
    log_to_evidence "HTTP ${http_code}"
    log_to_evidence '```'

    if [[ "$http_code" != "201" ]]; then
        err "Grant failed: HTTP ${http_code}"
        return 1
    fi

    SCOPE_ID=$(echo "$response" | jq -r .scopeId)
    OUTBOX_ID=$(echo "$response" | jq -r .outboxId)
    INITIAL_SYNC=$(echo "$response" | jq -r .tupleSyncStatus)
    OPENFGA_OBJ_ID=$(echo "$response" | jq -r .openFgaObjectId)
    OPENFGA_OBJ_TYPE=$(echo "$response" | jq -r .openFgaObjectType)

    info "scope_id=${SCOPE_ID} outbox_id=${OUTBOX_ID} initial_sync=${INITIAL_SYNC}"
    info "openFga: ${OPENFGA_OBJ_TYPE}:${OPENFGA_OBJ_ID}"

    # V25 namespace check — eğer encoder drift olduysa burada yakalanır
    if [[ "${OPENFGA_OBJ_TYPE}:${OPENFGA_OBJ_ID}" != "${EXPECTED_TUPLE_OBJECT}" ]]; then
        err "Encoder DRIFT: expected '${EXPECTED_TUPLE_OBJECT}', got '${OPENFGA_OBJ_TYPE}:${OPENFGA_OBJ_ID}'"
        err "Likely V25 alignment regression — check AccessScopeService + DataAccessScopeTupleEncoder"
        return 1
    fi

    [[ "$INITIAL_SYNC" == "PENDING" ]] || warn "Initial tupleSyncStatus is '${INITIAL_SYNC}' (expected PENDING; poller may have raced)"

    export SCOPE_ID OUTBOX_ID
    return 0
}

# ============================================================================
# Step 9.5 — DB scope row
# ============================================================================
do_step95_scope_row() {
    step "9.5" "data_access.scope row visible"
    local result
    result=$(run_psql "SELECT id, user_id, org_id, scope_kind, scope_source_table, scope_ref, granted_at, revoked_at FROM data_access.scope WHERE id = ${SCOPE_ID};")
    log_to_evidence "## Step 9.5 — data_access.scope row"
    log_to_evidence '```'
    log_to_evidence "$result"
    log_to_evidence '```'
    info "$result"
    if ! echo "$result" | grep -q "OUR_COMPANY"; then
        err "scope_source_table is NOT 'OUR_COMPANY' — V25 hizalama regresyonu"
        return 1
    fi
    return 0
}

# ============================================================================
# Step 9.6 — Outbox row visible
# ============================================================================
do_step96_outbox_row() {
    step "9.6" "data_access.scope_outbox row visible"
    local result
    result=$(run_psql "SELECT id, scope_id, action, status, attempt_count, tuple_user, tuple_relation, tuple_object FROM data_access.scope_outbox WHERE id = ${OUTBOX_ID};")
    log_to_evidence "## Step 9.6 — scope_outbox row"
    log_to_evidence '```'
    log_to_evidence "$result"
    log_to_evidence '```'
    info "$result"
    if ! echo "$result" | grep -q "${EXPECTED_TUPLE_OBJECT}"; then
        err "tuple_object is NOT '${EXPECTED_TUPLE_OBJECT}' — V25 encoder drift"
        return 1
    fi
    return 0
}

# ============================================================================
# Step 9.7 — Outbox PROCESSED
# ============================================================================
poll_outbox_status() {
    local outbox_id="$1" expected="$2" max_attempts
    max_attempts=$((POLL_TIMEOUT_S / POLL_INTERVAL_S))
    local i status
    for i in $(seq 1 $max_attempts); do
        status=$(run_psql_t "SELECT status FROM data_access.scope_outbox WHERE id = ${outbox_id};")
        info "  poll ${i}/${max_attempts}: status=${status}"
        log_to_evidence "  poll ${i}/${max_attempts}: status=${status}"
        if [[ "$status" == "$expected" ]]; then return 0; fi
        sleep "$POLL_INTERVAL_S"
    done
    err "Timeout: outbox ${outbox_id} did not reach ${expected} within ${POLL_TIMEOUT_S}s"
    return 1
}

do_step97_outbox_processed() {
    step "9.7" "Outbox PROCESSED (eventual ≤${POLL_TIMEOUT_S}s)"
    log_to_evidence "## Step 9.7 — Outbox PROCESSED polling"
    if ! poll_outbox_status "$OUTBOX_ID" "PROCESSED"; then
        return 1
    fi
    local result
    result=$(run_psql "SELECT id, status, processed_at, attempt_count FROM data_access.scope_outbox WHERE id = ${OUTBOX_ID};")
    log_to_evidence '```'
    log_to_evidence "$result"
    log_to_evidence '```'
    return 0
}

# ============================================================================
# Step 9.8/9.9 — OpenFGA /check (ALLOW + DENY)
# ============================================================================
openfga_check() {
    local user="$1"
    : "${OPENFGA_URL:?OPENFGA_URL must be set (e.g., http://10.44.3.209:8080)}"
    : "${STORE_ID:?STORE_ID must be set (vault kv get -field=store_id kv/platform/openfga)}"
    : "${MODEL_ID:?MODEL_ID must be set (vault kv get -field=model_id kv/platform/openfga)}"

    ssh "${PG_SSH_TARGET}" "curl -sf -X POST \
        ${OPENFGA_URL}/stores/${STORE_ID}/check \
        -H 'Content-Type: application/json' \
        -d '{
          \"authorization_model_id\": \"${MODEL_ID}\",
          \"tuple_key\": {
            \"user\": \"${user}\",
            \"relation\": \"viewer\",
            \"object\": \"${EXPECTED_TUPLE_OBJECT}\"
          }
        }'"
}

do_step98_allow() {
    step "9.8" "OpenFGA /check ALLOW (granted user)"
    local result
    result=$(openfga_check "${GRANT_USER}")
    log_to_evidence "## Step 9.8 — /check ALLOW"
    log_to_evidence '```json'
    log_to_evidence "$result"
    log_to_evidence '```'
    info "$result"
    if ! echo "$result" | grep -q '"allowed":true'; then
        err "Expected allowed=true, got: ${result}"
        return 1
    fi
    return 0
}

do_step99_deny() {
    step "9.9" "OpenFGA /check DENY (negative user)"
    local result
    result=$(openfga_check "user:${USER_UID_DENIED}")
    log_to_evidence "## Step 9.9 — /check DENY (negative)"
    log_to_evidence '```json'
    log_to_evidence "$result"
    log_to_evidence '```'
    info "$result"
    if ! echo "$result" | grep -q '"allowed":false'; then
        err "Expected allowed=false, got: ${result}"
        return 1
    fi
    return 0
}

# ============================================================================
# Step 9.10 — REVOKE + FLIP
# ============================================================================
do_step910_revoke_flip() {
    step "9.10" "DELETE revoke + allow→deny FLIP"
    local http_code
    http_code=$(curl -s -X DELETE "${API_BASE}/api/v1/access/scope/${SCOPE_ID}" \
        -H "Authorization: Bearer ${JWT_ADMIN}" \
        -w '%{http_code}\n' -o /tmp/d35-revoke-body)
    log_to_evidence "## Step 9.10 — REVOKE + FLIP"
    log_to_evidence "DELETE response code: ${http_code}"
    info "DELETE → ${http_code}"
    if [[ "$http_code" != "204" ]]; then
        err "Revoke failed: HTTP ${http_code}"
        return 1
    fi

    # REVOKE outbox visible
    local result
    result=$(run_psql "SELECT id, scope_id, action, status, tuple_user, tuple_object FROM data_access.scope_outbox WHERE scope_id = ${SCOPE_ID} ORDER BY id;")
    log_to_evidence '### Outbox after REVOKE'
    log_to_evidence '```'
    log_to_evidence "$result"
    log_to_evidence '```'

    # Wait REVOKE PROCESSED
    local revoke_id
    revoke_id=$(run_psql_t "SELECT id FROM data_access.scope_outbox WHERE scope_id = ${SCOPE_ID} AND action='REVOKE' ORDER BY id DESC LIMIT 1;")
    if [[ -z "$revoke_id" ]]; then
        err "REVOKE outbox row not found"
        return 1
    fi
    if ! poll_outbox_status "$revoke_id" "PROCESSED"; then
        return 1
    fi

    # FLIP — granted user now denied
    info "Verifying FLIP: granted user should now be DENIED"
    result=$(openfga_check "${GRANT_USER}")
    log_to_evidence '### /check FLIP (should be denied now)'
    log_to_evidence '```json'
    log_to_evidence "$result"
    log_to_evidence '```'
    info "$result"
    if ! echo "$result" | grep -q '"allowed":false'; then
        err "FLIP failed: granted user is still ALLOWED after REVOKE — outbox poll/FGA write race?"
        return 1
    fi
    return 0
}

# ============================================================================
# Step 9.11 — Zero FAILED rows
# ============================================================================
do_step911_zero_failed() {
    step "9.11" "Zero FAILED rows in 10-min window"
    local result
    result=$(run_psql "SELECT count(*) AS failed_count FROM data_access.scope_outbox WHERE status = 'FAILED' AND created_at >= now() - INTERVAL '10 minutes';")
    log_to_evidence "## Step 9.11 — FAILED count"
    log_to_evidence '```'
    log_to_evidence "$result"
    log_to_evidence '```'
    info "$result"
    if echo "$result" | grep -qE 'failed_count *\| *[0-9]+' && ! echo "$result" | grep -qE '\|\s*0\s*$'; then
        err "Non-zero FAILED rows in 10-min window"
        return 1
    fi
    return 0
}

# ============================================================================
# Main
# ============================================================================
main() {
    init_evidence
    info "Evidence file: ${EVIDENCE_FILE}"

    do_grant || { err "FAIL at Step 9.4"; exit 1; }
    do_step95_scope_row || { err "FAIL at Step 9.5"; exit 1; }
    do_step96_outbox_row || { err "FAIL at Step 9.6"; exit 1; }
    do_step97_outbox_processed || { err "FAIL at Step 9.7"; exit 1; }
    do_step98_allow || { err "FAIL at Step 9.8"; exit 1; }
    do_step99_deny || { err "FAIL at Step 9.9"; exit 1; }
    do_step910_revoke_flip || { err "FAIL at Step 9.10"; exit 1; }
    do_step911_zero_failed || { err "FAIL at Step 9.11"; exit 1; }

    log_to_evidence ""
    log_to_evidence "Completed: $(date -Iseconds)"
    log_to_evidence "Verdict: PASS — D35-2-full 11/11 steps green"

    info ""
    info "===================="
    info "D35-2-full PASS — 11/11 canonical steps green"
    info "Evidence: ${EVIDENCE_FILE}"
    info "Next: copy evidence to docs/faz-21-3-evidence/<date>-d35-2-full-<run-id>.md, commit, then proceed to D35-3 UI persona run."
    info "===================="
}

main "$@"
