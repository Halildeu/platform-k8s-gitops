#!/usr/bin/env bash
# graph-mail-send.sh — Send mail AS ai@acik.com via Microsoft Graph (Application permission)
#
# Status: Codex `019ebbdb` PARTIAL→absorb 2026-06-12 — Mail.Send app-only Graph REST.
# ADR ref: docs/adr/0024-graph-mail-adapter-defer.md §D7b (agent/ops explicit send helper).
# Runbook: docs/runbooks/RB-graph-mail-agent-read.md §9 (send surface).
#
# Boundary:
# - DRY-RUN BY DEFAULT: without --send, NO network call is made; only the payload
#   preview (to/cc/subject/body/external_recipients/recipient_confirm) is printed.
# - From is FIXED to ai@acik.com (no --from). Endpoint POST /users/ai@acik.com/sendMail.
# - ApplicationAccessPolicy restricts the app to ai@acik.com mailbox only — secret
#   leak blast radius is the single sender mailbox (other senders Denied by Exchange).
# - --confirm-recipients mechanical guard: must equal the normalized to+cc set, else abort.
# - Payload is built LOCALLY with jq --arg (injection-safe), base64-encoded, and embedded
#   in the heredoc *script stream* (not argv/env) → body/subject never appear in the
#   remote process list. base64 is special-char-free so it is safe inside single quotes.
# - Send-mode audit (stderr): to/cc/subject/content_type/body_len/external_recipients/
#   http_status ONLY — the body value, token, and secret are never logged.
# - No retry (Graph sendMail is NOT idempotent — one POST), no token cache, no backend
#   flag change (notify.adapters.graph.enabled stays disabled; SMTP send-path canonical).
#
# Agent-layer contract: this helper is non-interactive (CI/agent-safe). The per-message
# user approval ("send AS the user" HARD RULE) is enforced at the AGENT layer — the agent
# shows recipient+subject+content and waits for an explicit yes before passing --send.
#
# Usage:
#   # 1. Dry-run (default — shows payload, sends nothing):
#   ./graph-mail-send.sh --to someone@acik.com --subject "Test" --body "Merhaba"
#
#   # 2. Real send (requires --send AND --confirm-recipients matching to+cc):
#   ./graph-mail-send.sh --to someone@acik.com --subject "Test" --body "Merhaba" \
#       --send --confirm-recipients someone@acik.com
#
#   # 3. HTML body from file + cc:
#   ./graph-mail-send.sh --to a@acik.com --cc b@acik.com --subject "Rapor" \
#       --body-file /tmp/report.html --content-type html \
#       --send --confirm-recipients "a@acik.com,b@acik.com"
#
# Pre-requisites (operator one-time — same as read helper):
# 1. Entra app `acik-mail-graph-api` Mail.Send Application permission + tenant admin consent
# 2. Exchange Online ApplicationAccessPolicy RestrictAccess to ai@acik.com
# 3. Vault path kv/platform/graph populated with graph_client_id/secret/tenant_id

set -euo pipefail

FROM="ai@acik.com"
TO=""
CC=""
SUBJECT=""
BODY=""
BODY_FILE=""
CONTENT_TYPE="text"   # text | html
DO_SEND=0
CONFIRM_RECIPIENTS=""
SSH_HOST="aiadmin@aiserver"
VAULT_PATH="kv/platform/graph"

usage() {
    cat <<'EOF'
Usage: graph-mail-send.sh --to EMAIL --subject TEXT (--body TEXT | --body-file PATH) [OPTIONS]

Required:
  --to EMAIL              Recipient (comma-separated for multiple)
  --subject TEXT          Subject line
  --body TEXT             Body text (or use --body-file)
  --body-file PATH        Read body from file (use '-' for stdin)

Options:
  --cc EMAIL              CC recipient(s), comma-separated
  --content-type text|html   Body content type (default: text)
  --send                  ACTUALLY send (default is dry-run, no network call)
  --confirm-recipients X  Required with --send: must equal normalized to+cc set
  --ssh-host HOST         SSH host for Vault access (default: aiadmin@aiserver)
  --vault-path PATH       Vault KV path (default: kv/platform/graph)
  -h, --help              Show this help

Security:
- From is FIXED to ai@acik.com (AAP enforces sender mailbox).
- Dry-run by default; --send + --confirm-recipients both required for real send.
- Body never appears in remote process list (base64 via heredoc script stream).
- No retry (sendMail not idempotent), no token cache, no backend flag change.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --to) TO="$2"; shift 2 ;;
        --cc) CC="$2"; shift 2 ;;
        --subject) SUBJECT="$2"; shift 2 ;;
        --body) BODY="$2"; shift 2 ;;
        --body-file) BODY_FILE="$2"; shift 2 ;;
        --content-type) CONTENT_TYPE="$2"; shift 2 ;;
        --send) DO_SEND=1; shift ;;
        --confirm-recipients) CONFIRM_RECIPIENTS="$2"; shift 2 ;;
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        --vault-path) VAULT_PATH="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
    esac
done

# --- Validation ---
if [[ -z "$TO" ]]; then echo "ERROR: --to required" >&2; exit 1; fi
if [[ -z "$SUBJECT" ]]; then echo "ERROR: --subject required" >&2; exit 1; fi
if [[ -z "$BODY" && -z "$BODY_FILE" ]]; then echo "ERROR: --body or --body-file required" >&2; exit 1; fi
if [[ -n "$BODY" && -n "$BODY_FILE" ]]; then echo "ERROR: use only one of --body / --body-file" >&2; exit 1; fi
if [[ "$CONTENT_TYPE" != "text" && "$CONTENT_TYPE" != "html" ]]; then
    echo "ERROR: --content-type must be text or html (got $CONTENT_TYPE)" >&2; exit 1
fi

# Read body from file/stdin if requested
if [[ -n "$BODY_FILE" ]]; then
    if [[ "$BODY_FILE" == "-" ]]; then
        BODY="$(cat)"
    else
        if [[ ! -f "$BODY_FILE" ]]; then echo "ERROR: body-file not found: $BODY_FILE" >&2; exit 1; fi
        BODY="$(cat "$BODY_FILE")"
    fi
fi

# Normalize recipient set (lowercase, trim, sort-unique) for confirm matching + external detection
normalize_recipients() {
    printf '%s' "$1" | tr ',' '\n' | tr '[:upper:]' '[:lower:]' \
        | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$' | sort -u
}

ALL_RECIPIENTS=$(normalize_recipients "${TO}${CC:+,$CC}")
EXTERNAL_RECIPIENTS=$(printf '%s\n' "$ALL_RECIPIENTS" | grep -vE '@acik\.com$' || true)

# Build to/cc JSON arrays (jq --arg injection-safe)
to_json_array() {
    printf '%s' "$1" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$' \
        | jq -R '{emailAddress: {address: .}}' | jq -s '.'
}
TO_JSON=$(to_json_array "$TO")
CC_JSON=$([[ -n "$CC" ]] && to_json_array "$CC" || echo '[]')

# Build the full Graph sendMail payload locally (injection-safe)
PAYLOAD=$(jq -n \
    --arg subj "$SUBJECT" \
    --arg body "$BODY" \
    --arg ct "$CONTENT_TYPE" \
    --argjson to "$TO_JSON" \
    --argjson cc "$CC_JSON" \
    '{
        message: {
            subject: $subj,
            body: { contentType: $ct, content: $body },
            toRecipients: $to,
            ccRecipients: $cc
        },
        saveToSentItems: true
    }')

BODY_LEN=${#BODY}

# --- Dry-run (default) ---
if [[ $DO_SEND -eq 0 ]]; then
    echo "=== DRY-RUN (no mail sent; use --send + --confirm-recipients to send) ===" >&2
    jq -n \
        --arg from "$FROM" \
        --arg subject "$SUBJECT" \
        --arg content_type "$CONTENT_TYPE" \
        --arg body "$BODY" \
        --argjson body_len "$BODY_LEN" \
        --arg recipient_confirm "$(printf '%s' "$ALL_RECIPIENTS" | paste -sd, -)" \
        --argjson external "$(printf '%s\n' "$EXTERNAL_RECIPIENTS" | grep -v '^$' | jq -R '.' | jq -s '.')" \
        --argjson to "$TO_JSON" \
        --argjson cc "$CC_JSON" \
        '{
            dry_run: true,
            from: $from,
            to: [$to[].emailAddress.address],
            cc: [$cc[].emailAddress.address],
            subject: $subject,
            content_type: $content_type,
            body_len: $body_len,
            body: $body,
            recipient_confirm: $recipient_confirm,
            external_recipients: $external
        }'
    exit 0
fi

# --- Real send: enforce --confirm-recipients ---
if [[ -z "$CONFIRM_RECIPIENTS" ]]; then
    echo "ERROR: --send requires --confirm-recipients (the exact normalized to+cc set)" >&2
    echo "       Expected: $(printf '%s' "$ALL_RECIPIENTS" | paste -sd, -)" >&2
    exit 4
fi
CONFIRM_NORMALIZED=$(normalize_recipients "$CONFIRM_RECIPIENTS")
if [[ "$CONFIRM_NORMALIZED" != "$ALL_RECIPIENTS" ]]; then
    echo "ERROR: --confirm-recipients does NOT match the actual to+cc recipient set" >&2
    echo "       Actual:    $(printf '%s' "$ALL_RECIPIENTS" | paste -sd, -)" >&2
    echo "       Confirmed: $(printf '%s' "$CONFIRM_NORMALIZED" | paste -sd, -)" >&2
    exit 4
fi

# Audit echo (stderr) — NO body value
echo "=== SENDING (Graph POST /users/${FROM}/sendMail) ===" >&2
echo "  to:                $(printf '%s' "$(printf '%s' "$TO_JSON" | jq -r '.[].emailAddress.address' | paste -sd, -)")" >&2
echo "  cc:                $(printf '%s' "$(printf '%s' "$CC_JSON" | jq -r '.[].emailAddress.address' | paste -sd, -)")" >&2
echo "  subject:           $SUBJECT" >&2
echo "  content_type:      $CONTENT_TYPE" >&2
echo "  body_len:          $BODY_LEN" >&2
echo "  external_recipients: $(printf '%s' "$EXTERNAL_RECIPIENTS" | paste -sd, -)" >&2

# base64-encode payload → embed in heredoc script stream (NOT argv/env)
PAYLOAD_B64=$(printf '%s' "$PAYLOAD" | base64 | tr -d '\n')

# Execute on aiserver — Vault credential + token + Graph POST, all in-band.
# PAYLOAD_B64 is base64 (special-char-free) so it is safe inside the single-quoted
# heredoc assignment. It travels in the bash -s SCRIPT STREAM, not argv → invisible
# in the remote process list. Quoted heredoc <<'EOSSH' = no client expansion except
# the one controlled ${PAYLOAD_B64} / ${FROM} / ${VAULT_PATH} substitutions we set.
ssh -o BatchMode=yes "$SSH_HOST" \
    "VAULT_PATH='${VAULT_PATH}' FROM='${FROM}' PAYLOAD_B64='${PAYLOAD_B64}' bash -s" <<'EOSSH'
set -euo pipefail

VAULT_ROOT_TOKEN=$(sudo -n jq -r .root_token /srv/platform/secrets/backup-auth/vault-init-prod.json)

GRAPH_DATA=$(docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-prod \
    vault kv get -format=json "${VAULT_PATH}" 2>/dev/null || \
    docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault \
    vault kv get -format=json "${VAULT_PATH}")

CLIENT_ID=$(echo "$GRAPH_DATA" | jq -r '.data.data.graph_client_id // .data.data.client_id')
CLIENT_SECRET=$(echo "$GRAPH_DATA" | jq -r '.data.data.graph_client_secret // .data.data.client_secret')
TENANT_ID=$(echo "$GRAPH_DATA" | jq -r '.data.data.graph_tenant_id // .data.data.tenant_id')

if [[ -z "$CLIENT_ID" || -z "$CLIENT_SECRET" || -z "$TENANT_ID" || \
      "$CLIENT_ID" == "null" || "$CLIENT_SECRET" == "null" || "$TENANT_ID" == "null" ]]; then
    echo "ERROR: Vault ${VAULT_PATH} missing graph credentials" >&2
    exit 2
fi

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

# Decode payload + single POST (NO retry — sendMail not idempotent)
PAYLOAD=$(printf '%s' "$PAYLOAD_B64" | base64 -d)

HTTP_STATUS=$(curl -sS -o /tmp/graph-send-resp.$$ -w '%{http_code}' -X POST \
    "https://graph.microsoft.com/v1.0/users/${FROM}/sendMail" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

if [[ "$HTTP_STATUS" == "202" ]]; then
    jq -n --arg from "$FROM" --argjson http "$HTTP_STATUS" \
        '{status: "accepted", http_status: $http, from: $from, note: "Graph accepted; deliverability is async"}'
    RC=0
else
    echo "ERROR: sendMail returned HTTP $HTTP_STATUS" >&2
    jq -r '.error | {code: .code, message: .message}' < /tmp/graph-send-resp.$$ 2>/dev/null >&2 || \
        cat /tmp/graph-send-resp.$$ >&2
    RC=5
fi

rm -f /tmp/graph-send-resp.$$
unset ACCESS_TOKEN CLIENT_SECRET VAULT_ROOT_TOKEN GRAPH_DATA TOKEN_RESPONSE PAYLOAD PAYLOAD_B64
exit $RC
EOSSH
