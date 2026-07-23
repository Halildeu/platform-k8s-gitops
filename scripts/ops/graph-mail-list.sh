#!/usr/bin/env bash
# graph-mail-list.sh — List ai@acik.com Inbox via Microsoft Graph (Application permission)
#
# Status: Codex `019ebac1` PARTIAL absorb 2026-05-28 — Mail.Read app-only Graph REST.
# ADR ref: docs/adr/0024-graph-mail-adapter-defer.md §D7 (agent/ops inbox read scope addition).
# Runbook: docs/runbooks/RB-graph-mail-agent-read.md
#
# Boundary:
# - Vault credential read on aiserver (D43 stdin-pipe pattern — credential never logged)
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
#    graph_tenant_id (mevcut send-path setup zaten kullanır)

set -euo pipefail

MAILBOX="ai@acik.com"
TOP=5
INCLUDE_BODY=0
SEARCH=""
FILTER=""
SSH_HOST="aiserver"
VAULT_PATH="kv/platform/graph"

usage() {
    cat <<'EOF'
Usage: graph-mail-list.sh [OPTIONS]

Options:
  --top N             Number of messages (default: 5; max: 50)
  --mailbox EMAIL     Mailbox to read (default: ai@acik.com)
  --include-body      Include bodyPreview (truncated 500 chars)
  --search QUERY      Graph $search filter (e.g., "alert", "subject:bounce")
  --filter EXPR       Graph $filter expression (OData)
  --ssh-host HOST     SSH host for Vault access (default: aiserver)
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

# Build $select fields based on --include-body
if [[ $INCLUDE_BODY -eq 1 ]]; then
    SELECT_FIELDS="id,subject,from,toRecipients,receivedDateTime,hasAttachments,bodyPreview"
else
    SELECT_FIELDS="id,subject,from,toRecipients,receivedDateTime,hasAttachments"
fi

# Build Graph query
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

# Execute on the selected Vault host — credential read + token + Graph call all in-band
# D43 pattern: credential never echoed; SSH session output only sanitized result
#
# Robust pattern: helper params (MAILBOX, GRAPH_QUERY, VAULT_PATH) are passed as
# single-quoted env vars in the SSH command string (protects $top/$select/& chars),
# and the remote body is a QUOTED heredoc (<<'EOSSH') so NO client-side expansion
# occurs — every $VAR inside is evaluated on the remote host only. This keeps Vault
# credentials (CLIENT_SECRET, VAULT_ROOT_TOKEN, ACCESS_TOKEN) from ever leaving
# the server, and avoids the double-expansion that breaks OData $-prefixed params.
ssh -o BatchMode=yes "$SSH_HOST" \
    "VAULT_PATH='${VAULT_PATH}' MAILBOX='${MAILBOX}' GRAPH_QUERY='${GRAPH_QUERY}' bash -s" <<'EOSSH'
set -euo pipefail

read_vault_root_token() {
    local candidate token
    for candidate in \
        /srv/platform/secrets/backup-auth/vault-init-prod.json \
        /home/halil/bootstrap-drill/vault-init-prod.json \
        /home/halil/bootstrap-drill/vault-init.json; do
        if [[ -r "$candidate" ]]; then
            token=$(jq -er '.root_token | select(type == "string" and length > 0)' \
                "$candidate" 2>/dev/null) && {
                printf '%s' "$token"
                return 0
            }
        elif sudo -n test -r "$candidate" 2>/dev/null; then
            token=$(sudo -n jq -er \
                '.root_token | select(type == "string" and length > 0)' \
                "$candidate" 2>/dev/null) && {
                printf '%s' "$token"
                return 0
            }
        fi
    done
    echo "ERROR: no readable Vault bootstrap token source on remote host" >&2
    return 1
}

VAULT_ROOT_TOKEN=$(read_vault_root_token)

# Read Graph credentials from Vault (no echo)
GRAPH_DATA=$(docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-prod \
    vault kv get -format=json "${VAULT_PATH}" 2>/dev/null || \
    docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault \
    vault kv get -format=json "${VAULT_PATH}")

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
    -H "ConsistencyLevel: eventual")

GRAPH_ERROR=$(echo "$GRAPH_RESPONSE" | jq -r '.error.code // empty')
if [[ -n "$GRAPH_ERROR" ]]; then
    echo "ERROR: Graph mailbox query failed: ${GRAPH_ERROR}" >&2
    exit 4
fi

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
        received: .receivedDateTime,
        has_attachments: .hasAttachments,
        body_preview: (if .bodyPreview then (.bodyPreview | .[0:500]) else null end)
    }]
}'

# Cleanup
unset ACCESS_TOKEN CLIENT_SECRET VAULT_ROOT_TOKEN GRAPH_DATA TOKEN_RESPONSE GRAPH_ERROR
EOSSH
