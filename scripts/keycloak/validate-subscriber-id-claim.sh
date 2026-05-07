#!/usr/bin/env bash
#
# validate-subscriber-id-claim.sh — Faz 23.6 PR-2 dry-run validator for
# the canonical `subscriberId` JWT claim (Codex thread `019e03de` AGREE
# iter-1 model C).
#
# Verifies that:
#   1. The Keycloak realm has the subscriberId protocol mapper wired on
#      the OIDC client (built-in oidc-usermodel-attribute-mapper).
#   2. The test persona (or a caller-supplied user) has
#      `attributes.subscriberId` populated with the expected value.
#   3. A token issued via password grant carries `subscriberId` in the
#      access token payload with the expected value.
#
# Output: a JSON evidence summary (no token, no secret leakage). Exit
# code 0 = all checks passed; non-zero = mismatch / missing mapper /
# Keycloak unreachable.
#
# Usage examples:
#   # Dev fixture run (default args — checks the seeded test persona)
#   ./validate-subscriber-id-claim.sh
#
#   # Specific user / specific expected ID
#   TEST_USERNAME=alice@corp.example \
#   TEST_PASSWORD='REPLACE_BEFORE_RUN' \
#   EXPECTED_SUBSCRIBER_ID=42 \
#     ./validate-subscriber-id-claim.sh
#
# HARD RULE notes:
#   * Default test persona is `subscriber-claim-test@localtest.me`; this
#     file MUST NOT touch the operator's own login user (see global
#     "Kullanıcı Aktif Credential'ına Dokunma" rule). Pass TEST_USERNAME
#     to target a different persona only when you know its credentials
#     are a test secret.
#   * The script never prints the access token. The evidence summary
#     reports only the boolean outcome and the maskeli claim type.
#
set -euo pipefail
shopt -s lastpipe

# ─── Config (env-overridable) ───────────────────────────────────────────

KEYCLOAK_BASE_URL="${KEYCLOAK_BASE_URL:-http://localhost:8081}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-dev-local}"
KEYCLOAK_ADMIN_USERNAME="${KEYCLOAK_ADMIN_USERNAME:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
KEYCLOAK_ADMIN_CLIENT_ID="${KEYCLOAK_ADMIN_CLIENT_ID:-admin-cli}"

OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-platform-gateway}"
OIDC_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-dev-local-client-secret-NOT_FOR_PROD}"

TEST_USERNAME="${TEST_USERNAME:-subscriber-claim-test@localtest.me}"
TEST_PASSWORD="${TEST_PASSWORD:-subscriber-test-NOT_FOR_PROD}"
EXPECTED_SUBSCRIBER_ID="${EXPECTED_SUBSCRIBER_ID:-1204}"

# Hardening flag: when set, the script will create/update the test
# persona with the expected attribute before token issuance. Off by
# default to keep the script idempotent + safe (live realms must not
# have personas mutated without an explicit operator decision).
ENSURE_TEST_PERSONA="${ENSURE_TEST_PERSONA:-0}"

# ─── Helpers ────────────────────────────────────────────────────────────

require() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERROR: '$1' is required (install via brew/apt and retry)" >&2
        exit 2
    }
}
require curl
require jq
require base64

die() {
    echo "ERROR: $*" >&2
    exit 1
}

# Decode a base64url-encoded JWT segment to JSON.
b64url_decode() {
    local seg="$1"
    local pad
    seg="$(printf '%s' "$seg" | tr '_-' '/+')"
    pad=$(( (4 - ${#seg} % 4) % 4 ))
    seg="${seg}$(printf '=%.0s' $(seq 1 "$pad"))"
    printf '%s' "$seg" | base64 -d 2>/dev/null
}

# ─── 1. Admin token ─────────────────────────────────────────────────────

admin_token_json="$(
    curl -fsS -X POST "$KEYCLOAK_BASE_URL/realms/master/protocol/openid-connect/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d grant_type=password \
        -d "client_id=$KEYCLOAK_ADMIN_CLIENT_ID" \
        -d "username=$KEYCLOAK_ADMIN_USERNAME" \
        -d "password=$KEYCLOAK_ADMIN_PASSWORD" 2>/dev/null
)" || die "admin token request failed (Keycloak unreachable or admin creds wrong)"
admin_token="$(printf '%s' "$admin_token_json" | jq -r '.access_token // empty')"
[ -n "$admin_token" ] || die "admin token response missing access_token"

# ─── 2. Mapper presence on OIDC client ─────────────────────────────────

client_repr="$(
    curl -fsS -G "$KEYCLOAK_BASE_URL/admin/realms/$KEYCLOAK_REALM/clients" \
        -H "Authorization: Bearer $admin_token" \
        --data-urlencode "clientId=$OIDC_CLIENT_ID" 2>/dev/null
)" || die "list clients failed for realm=$KEYCLOAK_REALM"
client_id_uuid="$(printf '%s' "$client_repr" | jq -r '.[0].id // empty')"
[ -n "$client_id_uuid" ] || die "client clientId=$OIDC_CLIENT_ID not found in realm=$KEYCLOAK_REALM"

mapper_present="false"
mapper_target_attr=""
mapper_claim_name=""
inline_mappers="$(printf '%s' "$client_repr" | jq -c '.[0].protocolMappers // []')"
if printf '%s' "$inline_mappers" | jq -e '.[] | select(.protocolMapper == "oidc-usermodel-attribute-mapper" and .config["claim.name"] == "subscriberId")' >/dev/null 2>&1; then
    mapper_present="true"
    mapper_target_attr="$(printf '%s' "$inline_mappers" | jq -r '.[] | select(.config["claim.name"] == "subscriberId") | .config["user.attribute"]' | head -n1)"
    mapper_claim_name="subscriberId"
else
    # Fallback: walk default client scopes (the prod-shaped layout
    # hoists this mapper into a dedicated `canonical-subscriber-id`
    # client scope; check every scope the client uses by default).
    default_scope_names="$(printf '%s' "$client_repr" | jq -r '.[0].defaultClientScopes // [] | .[]' 2>/dev/null || true)"
    while IFS= read -r scope_name; do
        [ -n "$scope_name" ] || continue
        scope_repr="$(
            curl -fsS -G "$KEYCLOAK_BASE_URL/admin/realms/$KEYCLOAK_REALM/client-scopes" \
                -H "Authorization: Bearer $admin_token" 2>/dev/null \
            | jq -c --arg n "$scope_name" '.[] | select(.name == $n)'
        )"
        [ -n "$scope_repr" ] || continue
        if printf '%s' "$scope_repr" | jq -e '.protocolMappers[] | select(.protocolMapper == "oidc-usermodel-attribute-mapper" and .config["claim.name"] == "subscriberId")' >/dev/null 2>&1; then
            mapper_present="true"
            mapper_target_attr="$(printf '%s' "$scope_repr" | jq -r '.protocolMappers[] | select(.config["claim.name"] == "subscriberId") | .config["user.attribute"]')"
            mapper_claim_name="subscriberId"
            break
        fi
    done <<<"$default_scope_names"
fi

if [ "$mapper_present" != "true" ]; then
    # Codex thread `019e03de` REVISE iter-2 (non-blocking): emit a
    # structured fail JSON instead of dying with a bare error so the
    # runbook can pipe the output to evidence files even on failure.
    jq -n \
        --arg realm "$KEYCLOAK_REALM" \
        --arg client "$OIDC_CLIENT_ID" \
        '{
           realm: $realm,
           client: $client,
           mapperPresent: false,
           failureReason: "subscriberId mapper not found on the OIDC client (checked inline + default client scopes); add the built-in oidc-usermodel-attribute-mapper or hoist into a canonical-subscriber-id client scope"
         }' >&2
    exit 1
fi

# ─── 3. (Optional) Ensure test persona has subscriberId attribute ──────

ensure_persona_summary="skipped"
if [ "$ENSURE_TEST_PERSONA" = "1" ]; then
    persona_lookup="$(
        curl -fsS -G "$KEYCLOAK_BASE_URL/admin/realms/$KEYCLOAK_REALM/users" \
            -H "Authorization: Bearer $admin_token" \
            --data-urlencode "username=$TEST_USERNAME" \
            --data-urlencode "exact=true" 2>/dev/null
    )"
    persona_id="$(printf '%s' "$persona_lookup" | jq -r '.[0].id // empty')"
    if [ -z "$persona_id" ]; then
        die "ENSURE_TEST_PERSONA=1 but persona '$TEST_USERNAME' not found in realm=$KEYCLOAK_REALM (script does not auto-create users)"
    fi
    persona_repr="$(
        curl -fsS "$KEYCLOAK_BASE_URL/admin/realms/$KEYCLOAK_REALM/users/$persona_id" \
            -H "Authorization: Bearer $admin_token"
    )"
    current_attr="$(printf '%s' "$persona_repr" | jq -r '.attributes.subscriberId[0] // empty')"
    if [ "$current_attr" != "$EXPECTED_SUBSCRIBER_ID" ]; then
        merged_repr="$(
            printf '%s' "$persona_repr" \
            | jq --arg sid "$EXPECTED_SUBSCRIBER_ID" '.attributes = ((.attributes // {}) + {subscriberId: [$sid]})'
        )"
        curl -fsS -X PUT "$KEYCLOAK_BASE_URL/admin/realms/$KEYCLOAK_REALM/users/$persona_id" \
            -H "Authorization: Bearer $admin_token" \
            -H "Content-Type: application/json" \
            --data-binary "$merged_repr" >/dev/null \
            || die "PUT user $persona_id failed (attribute update aborted)"
        ensure_persona_summary="updated"
    else
        ensure_persona_summary="already-correct"
    fi
fi

# ─── 4. Issue user token via password grant ────────────────────────────

token_json="$(
    curl -fsS -X POST "$KEYCLOAK_BASE_URL/realms/$KEYCLOAK_REALM/protocol/openid-connect/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d grant_type=password \
        -d "client_id=$OIDC_CLIENT_ID" \
        -d "client_secret=$OIDC_CLIENT_SECRET" \
        -d "username=$TEST_USERNAME" \
        -d "password=$TEST_PASSWORD" 2>/dev/null
)" || die "user token request failed (check OIDC client + persona credentials)"
access_token="$(printf '%s' "$token_json" | jq -r '.access_token // empty')"
[ -n "$access_token" ] || die "user token response missing access_token"

# ─── 5. Decode + assert claim ──────────────────────────────────────────

payload_seg="$(printf '%s' "$access_token" | cut -d. -f2)"
[ -n "$payload_seg" ] || die "token payload empty (decode failed)"
claims_json="$(b64url_decode "$payload_seg")"
[ -n "$claims_json" ] || die "token payload decode produced empty JSON"

actual_subscriber_id="$(printf '%s' "$claims_json" | jq -r '.subscriberId // empty')"
claim_type="$(printf '%s' "$claims_json" | jq -r 'if .subscriberId == null then "absent" elif (.subscriberId | type) == "string" then "string" elif (.subscriberId | type) == "number" then "number" else "other" end')"

subscriber_id_present="false"
subscriber_id_matches_expected="false"
[ -n "$actual_subscriber_id" ] && subscriber_id_present="true"
[ "$actual_subscriber_id" = "$EXPECTED_SUBSCRIBER_ID" ] && subscriber_id_matches_expected="true"

# ─── 6. Emit evidence summary (NO token / NO secret) ───────────────────

jq -n \
    --arg realm "$KEYCLOAK_REALM" \
    --arg client "$OIDC_CLIENT_ID" \
    --arg testUsername "$TEST_USERNAME" \
    --arg expected "$EXPECTED_SUBSCRIBER_ID" \
    --arg actual "$actual_subscriber_id" \
    --arg claimType "$claim_type" \
    --arg mapperAttr "$mapper_target_attr" \
    --arg ensure "$ensure_persona_summary" \
    --argjson present "$subscriber_id_present" \
    --argjson matches "$subscriber_id_matches_expected" \
    '{
       realm: $realm,
       client: $client,
       testUsername: $testUsername,
       mapperAttribute: $mapperAttr,
       ensureTestPersona: $ensure,
       expectedSubscriberId: $expected,
       subscriberIdPresent: $present,
       subscriberIdMatchesExpected: $matches,
       claimType: $claimType
     }'

if [ "$subscriber_id_matches_expected" = "true" ] && [ "$subscriber_id_present" = "true" ]; then
    exit 0
else
    exit 1
fi
