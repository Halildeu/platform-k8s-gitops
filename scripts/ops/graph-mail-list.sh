#!/usr/bin/env bash
# graph-mail-list.sh — List ai@acik.com Inbox via Microsoft Graph (Application permission)
#
# Status: Codex `019ebac1` PARTIAL absorb 2026-05-28 — Mail.Read app-only Graph REST.
# ADR ref: docs/adr/0024-graph-mail-adapter-defer.md §D7 (agent/ops inbox read scope addition).
# Runbook: docs/runbooks/RB-graph-mail-agent-read.md
#
# Boundary:
# - Vault credential read on aiserver with a dedicated AppRole (no routine root token)
# - Client-credentials token (~1h TTL Graph default); NO persistent token cache (default)
# - Graph REST GET /users/ai@acik.com/messages (read-only; no write/delete/move)
# - ApplicationAccessPolicy restricts app to ai@acik.com mailbox only (Exchange Online)
# - Sanitized stdout: subject / from / receivedDateTime / hasAttachments / bodyPreview (truncated)
#   Full body / attachment content requires explicit --include-body flag
#
# Usage:
#   ./graph-mail-list.sh                        # last 5 messages (default)
#   ./graph-mail-list.sh --top 10               # last 10 messages
#   ./graph-mail-list.sh --top 5 --include-body # include bodyPreview full (500 chars max)
#   ./graph-mail-list.sh --mailbox ai@acik.com  # explicit mailbox (default: ai@acik.com)
#   ./graph-mail-list.sh --search "alert"       # Graph $search filter
#   ./graph-mail-list.sh --filter "from/emailAddress/address eq 'no-reply@example.com'"
#
# Output format: JSON (jq-compatible) — pipe to jq for further filtering.
#
# Pre-requisites (operator one-time):
# 1. Entra app `acik-mail-graph-api` Mail.Read Application permission + tenant admin consent
# 2. Exchange Online ApplicationAccessPolicy RestrictAccess to ai@acik.com (via mail-enabled
#    security group `Mail-Graph-Allowed-Mailboxes`)
# 3. Vault path kv/platform/graph populated with graph_client_id + graph_client_secret +
#    graph_tenant_id; dedicated graph-mail-ops AppRole provisioned by
#    scripts/ops/provision-graph-mail-vault-approle.sh

set -euo pipefail

MAILBOX="ai@acik.com"
TOP=5
INCLUDE_BODY=0
FULL_BODY=0
SEARCH=""
FILTER=""
SSH_HOST="aiadmin@aiserver"
VAULT_PATH="kv/platform/graph"

usage() {
    cat <<'EOF'
Usage: graph-mail-list.sh [OPTIONS]

Options:
  --top N             Number of messages (default: 5; max: 50)
  --mailbox EMAIL     Mailbox to read (default: ai@acik.com)
  --include-body      Include bodyPreview (truncated 500 chars)
  --full-body         Include full plain-text body (body_text, 6000 chars max)
  --search QUERY      Graph $search filter (e.g., "alert", "subject:bounce")
  --filter EXPR       Graph $filter expression (OData)
  --ssh-host HOST     SSH host for Vault access (default: aiadmin@aiserver)
  -h, --help          Show this help

Output: JSON array of message metadata.

Boundary:
- Read-only (no Graph write/delete/move)
- ApplicationAccessPolicy restricts to ai@acik.com only (Exchange policy gate)
- No persistent token cache; per-call Vault round-trip (~2s latency)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --top) TOP="$2"; shift 2 ;;
        --mailbox) MAILBOX="$2"; shift 2 ;;
        --include-body) INCLUDE_BODY=1; shift ;;
        --full-body) FULL_BODY=1; INCLUDE_BODY=1; shift ;;
        --search) SEARCH="$2"; shift 2 ;;
        --filter) FILTER="$2"; shift 2 ;;
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ $TOP -lt 1 || $TOP -gt 50 ]]; then
    echo "ERROR: --top must be 1..50 (got $TOP)" >&2
    exit 1
fi

# Build $select fields based on --include-body / --full-body.
# ccRecipients is always selected: whether a thread keeps its stakeholder in the
# loop is a property of the message, and without it a missing CC is invisible.
if [[ $FULL_BODY -eq 1 ]]; then
    SELECT_FIELDS="id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,bodyPreview,body"
elif [[ $INCLUDE_BODY -eq 1 ]]; then
    SELECT_FIELDS="id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments,bodyPreview"
else
    SELECT_FIELDS="id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments"
fi

# Build Graph query.
# Graph rejects $search combined with $orderby (SearchWithOrderBy); when a
# search is requested we drop server-side ordering and sort locally instead.
GRAPH_QUERY="/users/${MAILBOX}/messages?\$top=${TOP}&\$select=${SELECT_FIELDS}"
if [[ -n "$SEARCH" ]]; then
    SEARCH_ENC=$(printf '%s' "$SEARCH" | jq -sRr @uri)
    GRAPH_QUERY="${GRAPH_QUERY}&\$search=%22${SEARCH_ENC}%22"
else
    GRAPH_QUERY="${GRAPH_QUERY}&\$orderby=receivedDateTime%20desc"
fi
if [[ -n "$FILTER" ]]; then
    FILTER_ENC=$(printf '%s' "$FILTER" | jq -sRr @uri)
    GRAPH_QUERY="${GRAPH_QUERY}&\$filter=${FILTER_ENC}"
fi

# Execute on aiserver — Vault credential read + token + Graph call all in-band
# D43 pattern: credential never echoed; SSH session output only sanitized result
#
# Robust pattern: helper params (MAILBOX, GRAPH_QUERY, VAULT_PATH) are passed as
# single-quoted env vars in the SSH command string (protects $top/$select/& chars),
# and the remote body is a QUOTED heredoc (<<'EOSSH') so NO client-side expansion
# occurs — every $VAR inside is evaluated on aiserver only. This keeps Vault
# credentials (CLIENT_SECRET, VAULT_TOKEN, ACCESS_TOKEN) from ever leaving
# the server, and avoids the double-expansion that breaks OData $-prefixed params.
ssh -o BatchMode=yes "$SSH_HOST" \
    "VAULT_PATH='${VAULT_PATH}' MAILBOX='${MAILBOX}' GRAPH_QUERY='${GRAPH_QUERY}' bash -s" <<'EOSSH'
set -euo pipefail

readonly VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
readonly APPROLE_ROLE_ID_FILE="${APPROLE_ROLE_ID_FILE:-/srv/platform/secrets/graph-mail-vault/role-id}"
readonly APPROLE_SECRET_ID_FILE="${APPROLE_SECRET_ID_FILE:-/srv/platform/secrets/graph-mail-vault/secret-id}"
readonly EXPECTED_VAULT_PATH="kv/platform/graph"
readonly EXPECTED_VAULT_POLICY="graph-mail-ops-ro"
readonly MAX_VAULT_TOKEN_TTL=1800

VAULT_TOKEN=""
GRAPH_DATA_FILE=""

vault_curl() {
    local token="$1"
    shift
    # Feed the token header through curl config stdin so it is absent from argv.
    printf 'header = "X-Vault-Token: %s"\n' "$token" | curl --config - "$@"
}

cleanup() {
    local cleanup_rc=$?
    if [[ -n "$VAULT_TOKEN" ]]; then
        vault_curl "$VAULT_TOKEN" -sS -o /dev/null -X POST \
            "${VAULT_ADDR}/v1/auth/token/revoke-self" || true
    fi
    [[ -z "$GRAPH_DATA_FILE" ]] || rm -f "$GRAPH_DATA_FILE"
    unset VAULT_TOKEN ROLE_ID SECRET_ID LOGIN_RESPONSE CLIENT_SECRET ACCESS_TOKEN
    exit "$cleanup_rc"
}
trap cleanup EXIT

if [[ "$VAULT_PATH" != "$EXPECTED_VAULT_PATH" ]]; then
    echo "ERROR: Graph mail Vault path is fixed to ${EXPECTED_VAULT_PATH}" >&2
    exit 2
fi

ROLE_ID=$(sudo -n cat "$APPROLE_ROLE_ID_FILE" 2>/dev/null) || {
    echo "ERROR: Graph mail Vault AppRole role-id is unavailable" >&2
    exit 2
}
SECRET_ID=$(sudo -n cat "$APPROLE_SECRET_ID_FILE" 2>/dev/null) || {
    echo "ERROR: Graph mail Vault AppRole secret-id is unavailable" >&2
    exit 2
}

LOGIN_RESPONSE=$(
    jq -n --arg role_id "$ROLE_ID" --arg secret_id "$SECRET_ID" \
        '{role_id: $role_id, secret_id: $secret_id}' |
        curl -sS -X POST \
            -H "Content-Type: application/json" \
            --data-binary @- \
            "${VAULT_ADDR}/v1/auth/approle/login"
) || {
    echo "ERROR: Graph mail Vault AppRole login request failed" >&2
    exit 2
}

VAULT_TOKEN=$(printf '%s' "$LOGIN_RESPONSE" | jq -r '.auth.client_token // empty')
VAULT_TOKEN_TTL=$(printf '%s' "$LOGIN_RESPONSE" | jq -r '.auth.lease_duration // 0')
VAULT_POLICY_MATCH=$(printf '%s' "$LOGIN_RESPONSE" | jq -r \
    --arg expected "$EXPECTED_VAULT_POLICY" \
    '((.auth.policies // []) == [$expected]) and ((.auth.token_policies // []) == [$expected])')

if [[ -z "$VAULT_TOKEN" || "$VAULT_POLICY_MATCH" != "true" || \
      ! "$VAULT_TOKEN_TTL" =~ ^[0-9]+$ || "$VAULT_TOKEN_TTL" -lt 1 || \
      "$VAULT_TOKEN_TTL" -gt "$MAX_VAULT_TOKEN_TTL" ]]; then
    echo "ERROR: Graph mail Vault AppRole contract rejected login response" >&2
    exit 2
fi

unset ROLE_ID SECRET_ID LOGIN_RESPONSE

# Read the one allowed KV v2 path. The response file is mode 0600 via umask.
umask 077
GRAPH_DATA_FILE=$(mktemp)
VAULT_HTTP_STATUS=$(vault_curl "$VAULT_TOKEN" -sS -o "$GRAPH_DATA_FILE" \
    -w '%{http_code}' "${VAULT_ADDR}/v1/kv/data/platform/graph") || {
    echo "ERROR: Graph mail Vault read request failed" >&2
    exit 2
}
if [[ "$VAULT_HTTP_STATUS" != "200" ]]; then
    echo "ERROR: Graph mail Vault read denied (HTTP ${VAULT_HTTP_STATUS})" >&2
    exit 2
fi
GRAPH_DATA=$(cat "$GRAPH_DATA_FILE")

CLIENT_ID=$(echo "$GRAPH_DATA" | jq -r '.data.data.graph_client_id // .data.data.client_id')
CLIENT_SECRET=$(echo "$GRAPH_DATA" | jq -r '.data.data.graph_client_secret // .data.data.client_secret')
TENANT_ID=$(echo "$GRAPH_DATA" | jq -r '.data.data.graph_tenant_id // .data.data.tenant_id')

if [[ -z "$CLIENT_ID" || -z "$CLIENT_SECRET" || -z "$TENANT_ID" || \
      "$CLIENT_ID" == "null" || "$CLIENT_SECRET" == "null" || "$TENANT_ID" == "null" ]]; then
    echo "ERROR: Vault ${VAULT_PATH} missing graph_client_id / graph_client_secret / graph_tenant_id" >&2
    exit 2
fi

# Client credentials token (~1h TTL Graph default)
TOKEN_RESPONSE=$(curl -sS -X POST \
    "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=${CLIENT_ID}" \
    --data-urlencode "client_secret=${CLIENT_SECRET}" \
    -d "scope=https://graph.microsoft.com/.default" \
    -d "grant_type=client_credentials")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')

if [[ -z "$ACCESS_TOKEN" ]]; then
    echo "ERROR: Token acquisition failed" >&2
    echo "$TOKEN_RESPONSE" | jq -r '.error_description // .error // .' >&2
    exit 3
fi

# Graph call (read-only)
GRAPH_RESPONSE=$(curl -sS \
    "https://graph.microsoft.com/v1.0${GRAPH_QUERY}" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Accept: application/json" \
    -H 'Prefer: outlook.body-content-type="text"' \
    -H "ConsistencyLevel: eventual")

# Sanitize output — strip @odata.context noise + flatten
echo "$GRAPH_RESPONSE" | jq --arg mailbox "$MAILBOX" '{
    mailbox: $mailbox,
    count: (.value | length),
    error: (.error.code // null),
    messages: [(.value // [])[] | {
        id: .id,
        subject: .subject,
        from: (.from.emailAddress.address // null),
        from_name: (.from.emailAddress.name // null),
        to: [.toRecipients[]?.emailAddress.address],
        cc: [.ccRecipients[]?.emailAddress.address],
        received: .receivedDateTime,
        has_attachments: .hasAttachments,
        body_preview: (if .bodyPreview then (.bodyPreview | .[0:500]) else null end),
        body_text: (if .body.content then (.body.content | .[0:6000]) else null end)
    }] | sort_by(.received // "") | reverse
}'

# cleanup trap revokes the short-lived Vault token.
unset ACCESS_TOKEN CLIENT_SECRET GRAPH_DATA TOKEN_RESPONSE VAULT_TOKEN_TTL VAULT_POLICY_MATCH
EOSSH
