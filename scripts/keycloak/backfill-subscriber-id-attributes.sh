#!/usr/bin/env bash
#
# backfill-subscriber-id-attributes.sh — Faz 23.6 PR-2 backfill for the
# canonical `subscriberId` Keycloak user attribute (Codex thread
# `019e03de` AGREE iter-1 model C).
#
# For every Keycloak user in the target realm, look up the canonical
# user-service `users.id` row by email and write it to the Keycloak
# user attribute `subscriberId`. The matching JWT mapper
# (`oidc-usermodel-attribute-mapper`) then surfaces it as the
# `subscriberId` access-token claim.
#
# Defaults are dry-run (`APPLY=0`): the script reads what it WOULD
# update and emits a JSON report. Set `APPLY=1` to actually mutate the
# realm. Conflict signals (multiple user-service hits, drift between
# Keycloak attribute and canonical id) abort by default — set
# `ALLOW_OVERWRITE=1` only when you've reconciled the conflict
# manually.
#
# HARD RULE notes:
#   * The script never updates the operator's own login user. Set
#     `OPERATOR_LOGIN_USERNAME` to your own login user (or pass via
#     env) to skip that record from the sweep ("Kullanıcı Aktif
#     Credential'ına Dokunma" rule).
#   * Test persona seeded by dev-local-realm.json
#     (`subscriber-claim-test@localtest.me`) is allowed; that user is
#     NOT a real login user.
#   * Live realm apply (`APPLY=1` against staging/prod) requires an
#     explicit operator decision and the runbook captures the dry-run
#     report as evidence first.
#
# Usage examples:
#   # Dev-local dry-run (default)
#   ./backfill-subscriber-id-attributes.sh
#
#   # Live apply against test realm
#   APPLY=1 KEYCLOAK_REALM=platform-test KEYCLOAK_BASE_URL=https://kc.test.example \
#     KEYCLOAK_ADMIN_USERNAME=ops-bot KEYCLOAK_ADMIN_PASSWORD=$KC_ADMIN_PW \
#     USER_SERVICE_URL=https://api.test.example/user-service \
#     USER_SERVICE_TOKEN=$SVC_TOKEN \
#     OPERATOR_LOGIN_USERNAME=halilkocoglu \
#       ./backfill-subscriber-id-attributes.sh
#
set -euo pipefail
shopt -s lastpipe

# ─── Config (env-overridable) ───────────────────────────────────────────

KEYCLOAK_BASE_URL="${KEYCLOAK_BASE_URL:-http://localhost:8081}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-dev-local}"
KEYCLOAK_ADMIN_USERNAME="${KEYCLOAK_ADMIN_USERNAME:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
KEYCLOAK_ADMIN_CLIENT_ID="${KEYCLOAK_ADMIN_CLIENT_ID:-admin-cli}"

USER_SERVICE_URL="${USER_SERVICE_URL:-http://localhost:8090/user-service}"
USER_SERVICE_TOKEN="${USER_SERVICE_TOKEN:-}"

PAGE_SIZE="${PAGE_SIZE:-100}"
APPLY="${APPLY:-0}"
ALLOW_OVERWRITE="${ALLOW_OVERWRITE:-0}"

# Operator's own login username — protected from the backfill sweep.
# Empty by default; set via env in real runs so the operator can
# never accidentally touch their own user.
OPERATOR_LOGIN_USERNAME="${OPERATOR_LOGIN_USERNAME:-}"

# ─── Helpers ────────────────────────────────────────────────────────────

require() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERROR: '$1' is required" >&2
        exit 2
    }
}
require curl
require jq

die() {
    echo "ERROR: $*" >&2
    exit 1
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

# ─── 2. Sweep users page-by-page ────────────────────────────────────────

# Tally counters
total_seen=0
updated=0
would_update=0
already_correct=0
skipped_no_email=0
skipped_no_match=0
skipped_operator=0
conflicts_json="[]"

offset=0
while :; do
    page_json="$(
        curl -fsS -G "$KEYCLOAK_BASE_URL/admin/realms/$KEYCLOAK_REALM/users" \
            -H "Authorization: Bearer $admin_token" \
            --data-urlencode "first=$offset" \
            --data-urlencode "max=$PAGE_SIZE" \
            --data-urlencode "briefRepresentation=false" 2>/dev/null
    )" || die "list users failed at offset=$offset"
    page_count="$(printf '%s' "$page_json" | jq 'length')"
    if [ "$page_count" -eq 0 ]; then
        break
    fi

    # Iterate users in this page.
    for i in $(seq 0 $((page_count - 1))); do
        user="$(printf '%s' "$page_json" | jq ".[$i]")"
        total_seen=$((total_seen + 1))

        kc_user_id="$(printf '%s' "$user" | jq -r '.id')"
        kc_username="$(printf '%s' "$user" | jq -r '.username')"
        kc_email="$(printf '%s' "$user" | jq -r '.email // .username // empty')"

        # Operator-protection: skip the operator's own login user.
        if [ -n "$OPERATOR_LOGIN_USERNAME" ] && [ "$kc_username" = "$OPERATOR_LOGIN_USERNAME" ]; then
            skipped_operator=$((skipped_operator + 1))
            continue
        fi

        if [ -z "$kc_email" ]; then
            skipped_no_email=$((skipped_no_email + 1))
            continue
        fi

        # Look up canonical id via user-service.
        # The script intentionally hits an internal-only endpoint
        # (`/api/users/internal/by-email/{email}`) that returns at most
        # one row. Adapt the URL/auth to your user-service contract.
        lookup_args=(-fsS -H "Accept: application/json")
        if [ -n "$USER_SERVICE_TOKEN" ]; then
            lookup_args+=(-H "Authorization: Bearer $USER_SERVICE_TOKEN")
        fi
        lookup_resp="$(
            curl "${lookup_args[@]}" \
                "$USER_SERVICE_URL/api/users/internal/by-email/$(printf '%s' "$kc_email" | jq -sRr @uri)" \
                2>/dev/null \
            || true
        )"

        if [ -z "$lookup_resp" ]; then
            skipped_no_match=$((skipped_no_match + 1))
            continue
        fi

        # Conflict guard: more than one canonical match.
        canonical_match_count="$(printf '%s' "$lookup_resp" | jq 'if type == "array" then length else 1 end' 2>/dev/null || echo 0)"
        if [ "$canonical_match_count" -gt 1 ]; then
            conflicts_json="$(printf '%s' "$conflicts_json" | jq --arg u "$kc_username" --arg e "$kc_email" '. + [{type: "multiple-canonical-matches", username: $u, email: $e}]')"
            continue
        fi

        # Extract canonical id (handle both array and object responses).
        canonical_id="$(printf '%s' "$lookup_resp" | jq -r 'if type == "array" then .[0].id else .id end // empty')"
        if [ -z "$canonical_id" ]; then
            skipped_no_match=$((skipped_no_match + 1))
            continue
        fi

        # Existing attribute (may be empty / array of one).
        current_attr="$(printf '%s' "$user" | jq -r '.attributes.subscriberId[0] // empty')"

        if [ "$current_attr" = "$canonical_id" ]; then
            already_correct=$((already_correct + 1))
            continue
        fi

        # Drift guard: existing attribute set but disagrees with canonical id.
        if [ -n "$current_attr" ] && [ "$current_attr" != "$canonical_id" ] && [ "$ALLOW_OVERWRITE" != "1" ]; then
            conflicts_json="$(printf '%s' "$conflicts_json" | jq --arg u "$kc_username" --arg e "$kc_email" --arg c "$current_attr" --arg n "$canonical_id" '. + [{type: "attribute-drift", username: $u, email: $e, current: $c, canonical: $n}]')"
            continue
        fi

        if [ "$APPLY" != "1" ]; then
            would_update=$((would_update + 1))
            continue
        fi

        # APPLY=1: PUT the merged user representation.
        merged_user="$(printf '%s' "$user" | jq --arg sid "$canonical_id" '.attributes = ((.attributes // {}) + {subscriberId: [$sid]})')"
        curl -fsS -X PUT "$KEYCLOAK_BASE_URL/admin/realms/$KEYCLOAK_REALM/users/$kc_user_id" \
            -H "Authorization: Bearer $admin_token" \
            -H "Content-Type: application/json" \
            --data-binary "$merged_user" >/dev/null \
            || die "PUT user $kc_username (id=$kc_user_id) failed"
        updated=$((updated + 1))
    done

    if [ "$page_count" -lt "$PAGE_SIZE" ]; then
        break
    fi
    offset=$((offset + page_count))
done

# ─── 3. Emit JSON report ───────────────────────────────────────────────

jq -n \
    --arg realm "$KEYCLOAK_REALM" \
    --argjson apply "$([ "$APPLY" = "1" ] && echo true || echo false)" \
    --argjson allowOverwrite "$([ "$ALLOW_OVERWRITE" = "1" ] && echo true || echo false)" \
    --arg operatorLogin "$OPERATOR_LOGIN_USERNAME" \
    --argjson totalSeen "$total_seen" \
    --argjson updated "$updated" \
    --argjson wouldUpdate "$would_update" \
    --argjson alreadyCorrect "$already_correct" \
    --argjson skippedNoEmail "$skipped_no_email" \
    --argjson skippedNoMatch "$skipped_no_match" \
    --argjson skippedOperator "$skipped_operator" \
    --argjson conflicts "$conflicts_json" \
    '{
       realm: $realm,
       apply: $apply,
       allowOverwrite: $allowOverwrite,
       operatorLoginProtected: $operatorLogin,
       totalUsersSeen: $totalSeen,
       updated: $updated,
       wouldUpdate: $wouldUpdate,
       alreadyCorrect: $alreadyCorrect,
       skippedNoEmail: $skippedNoEmail,
       skippedNoUserServiceMatch: $skippedNoMatch,
       skippedOperator: $skippedOperator,
       conflicts: $conflicts
     }'

# Conflicts present without ALLOW_OVERWRITE → exit non-zero so the
# runbook can gate the apply on a clean report.
conflict_count="$(printf '%s' "$conflicts_json" | jq 'length')"
if [ "$conflict_count" -gt 0 ] && [ "$ALLOW_OVERWRITE" != "1" ]; then
    exit 1
fi
exit 0
