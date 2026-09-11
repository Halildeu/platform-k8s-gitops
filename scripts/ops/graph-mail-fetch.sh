#!/usr/bin/env bash
# graph-mail-fetch.sh — Download whole messages (.eml MIME) and their attachments
# from a mailbox the read-only Graph identity may read, into a local directory.
#
# Runbook: docs/runbooks/RB-graph-mail-agent-read.md §11
#
# Boundary:
# - Identity is FIXED to `graph-read` (app acik-mail-graph-read, Mail.Read only,
#   Vault kv/platform/graph-read, AppRole graph-mail-read-ops). The send-capable
#   legacy identity is never used here.
# - Read-only Graph: GET /messages/{id}, /messages/{id}/$value (MIME),
#   /messages/{id}/attachments, /attachments/{id}/$value. No write/move/delete.
# - Everything sensitive (Vault token, client secret, Graph token, message bodies)
#   stays on aiserver; the only thing crossing ssh is a tar stream of the fetched
#   files, extracted locally. The remote temp dir is removed on exit.
# - Attachments are saved byte-for-byte and never opened or executed here.
# - Fail-closed size guard: the sum of attachment sizes must stay under
#   --max-total-mb (default 100) before a single byte is downloaded.
#
# Usage:
#   ./graph-mail-fetch.sh --mailbox halil.kocoglu@acik.com --top 2 --dest ~/Downloads/mail-halil
#   ./graph-mail-fetch.sh --mailbox ai@acik.com --message-id <id> [--message-id <id>...] --dest DIR
#
# Output layout (per message): <dest>/<received>_<subject-slug>/message.eml,
#   message.json, attachments.json, attachments/<original name>

set -euo pipefail

MAILBOX=""
TOP=0
DEST=""
SSH_HOST="aiadmin@aiserver"
IDENTITY="graph-read"
MAX_TOTAL_MB=100
FORCE=0
MSG_IDS=()

usage() {
    cat <<'EOF'
Usage: graph-mail-fetch.sh --mailbox EMAIL (--top N | --message-id ID ...) --dest DIR [options]

Options:
  --mailbox EMAIL       Mailbox to read (required; must be inside the graph-read scope)
  --top N               Newest N messages (1..20)
  --message-id ID       Exact Graph message id (repeatable)
  --dest DIR            Local target directory (created; must be empty unless --force)
  --max-total-mb N      Abort if attachments exceed N MB in total (default: 100)
  --force               Allow a non-empty --dest
  --ssh-host HOST       SSH host for the in-band Graph call (default: aiadmin@aiserver)
  -h, --help            Show this help

Identity is fixed to graph-read (Mail.Read only). Files are saved, never opened.
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mailbox) MAILBOX="$2"; shift 2 ;;
        --top) TOP="$2"; shift 2 ;;
        --message-id) MSG_IDS+=("$2"); shift 2 ;;
        --dest) DEST="$2"; shift 2 ;;
        --max-total-mb) MAX_TOTAL_MB="$2"; shift 2 ;;
        --force) FORCE=1; shift ;;
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument: $1" ;;
    esac
done

[[ "$MAILBOX" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] || die "--mailbox must be an e-mail address"
[[ -n "$DEST" ]] || die "--dest is required"
[[ "$TOP" =~ ^[0-9]+$ && "$TOP" -le 20 ]] || die "--top must be 0..20"
[[ "$MAX_TOTAL_MB" =~ ^[0-9]+$ && "$MAX_TOTAL_MB" -ge 1 ]] || die "--max-total-mb must be a positive integer"
if [[ "$TOP" -eq 0 && ${#MSG_IDS[@]} -eq 0 ]]; then die "pass --top N or at least one --message-id"; fi
if [[ "$TOP" -gt 0 && ${#MSG_IDS[@]} -gt 0 ]]; then die "--top and --message-id are mutually exclusive"; fi
for id in "${MSG_IDS[@]+"${MSG_IDS[@]}"}"; do
    [[ "$id" =~ ^[A-Za-z0-9_=-]{20,}$ ]] || die "message id has an unexpected shape"
done

mkdir -p "$DEST"
if [[ "$FORCE" -ne 1 ]] && [[ -n "$(ls -A "$DEST" 2>/dev/null)" ]]; then
    die "--dest is not empty (use --force to add into it): $DEST"
fi

MSG_IDS_JOINED=""
if [[ ${#MSG_IDS[@]} -gt 0 ]]; then MSG_IDS_JOINED=$(printf '%s\n' "${MSG_IDS[@]}"); fi

# Remote body is a QUOTED heredoc: nothing expands locally. Status/errors go to
# stderr; stdout carries only the tar stream, which is extracted into --dest.
ssh -o BatchMode=yes "$SSH_HOST" \
    "IDENTITY='${IDENTITY}' MAILBOX='${MAILBOX}' TOP='${TOP}' MAX_TOTAL_MB='${MAX_TOTAL_MB}' MSG_IDS_JOINED='${MSG_IDS_JOINED}' VAULT_PATH='kv/platform/${IDENTITY}' bash -s" <<'EOSSH' | tar -xf - -C "$DEST"
set -euo pipefail

readonly VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
# Every identity constant is spelled out literally per branch: the contract test
# pins these strings, and a derived value would let a typo select the wrong role.
case "${IDENTITY:-}" in
    graph-read)
        readonly APPROLE_ROLE_ID_FILE="${APPROLE_ROLE_ID_FILE:-/srv/platform/secrets/graph-mail-read-vault/role-id}"
        readonly APPROLE_SECRET_ID_FILE="${APPROLE_SECRET_ID_FILE:-/srv/platform/secrets/graph-mail-read-vault/secret-id}"
        readonly EXPECTED_VAULT_PATH="kv/platform/graph-read"
        readonly EXPECTED_VAULT_POLICY="graph-mail-read-ops-ro"
        ;;
    *)
        echo "ERROR: unknown Graph mail identity '${IDENTITY:-}'" >&2
        exit 2
        ;;
esac
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
    -w '%{http_code}' "${VAULT_ADDR}/v1/kv/data/platform/${IDENTITY}") || {
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

# ---- read-only fetch ----------------------------------------------------------
readonly GRAPH="https://graph.microsoft.com/v1.0"
WORK=$(mktemp -d)
FETCH_TOTAL=0

fetch_cleanup() {
    # Remove the work dir, then hand the ORIGINAL exit code to the auth cleanup so
    # the short-lived Vault token is still revoked and the status is preserved.
    local rc=$?
    rm -rf "$WORK"
    unset ACCESS_TOKEN CLIENT_SECRET GRAPH_DATA TOKEN_RESPONSE
    (exit "$rc")
    cleanup
}
trap fetch_cleanup EXIT

graph_get() { # url outfile -> http code
    curl -sS -o "$2" -w '%{http_code}' -H "Authorization: Bearer ${ACCESS_TOKEN}" -H "Accept: application/json" "$1"
}

sanitize() { # keep unicode, drop path separators and control chars, cap length
    printf '%s' "$1" | tr -d '\000-\037' | tr '/\\' '__' | sed -e 's/^\.\{1,2\}$/_/' | cut -c1-150
}

if [[ -n "${MSG_IDS_JOINED:-}" ]]; then
    mapfile -t IDS <<<"$MSG_IDS_JOINED"
else
    LIST="$WORK/list.json"
    CODE=$(graph_get "${GRAPH}/users/${MAILBOX}/messages?\$top=${TOP}&\$select=id&\$orderby=receivedDateTime%20desc" "$LIST")
    [[ "$CODE" == "200" ]] || { echo "ERROR: message list HTTP ${CODE}: $(jq -r '.error.code // "-"' "$LIST" 2>/dev/null)" >&2; exit 4; }
    mapfile -t IDS < <(jq -r '.value[].id' "$LIST")
fi
[[ ${#IDS[@]} -gt 0 ]] || { echo "ERROR: no messages selected" >&2; exit 4; }

# Size guard first: nothing is downloaded until every attachment list is known.
declare -a ATT_FILES=()
for i in "${!IDS[@]}"; do
    ID="${IDS[$i]}"
    META="$WORK/meta-$i.json"
    CODE=$(graph_get "${GRAPH}/users/${MAILBOX}/messages/${ID}?\$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,hasAttachments" "$META")
    [[ "$CODE" == "200" ]] || { echo "ERROR: message ${i} HTTP ${CODE}: $(jq -r '.error.code // "-"' "$META" 2>/dev/null)" >&2; exit 4; }
    ATT="$WORK/att-$i.json"
    CODE=$(graph_get "${GRAPH}/users/${MAILBOX}/messages/${ID}/attachments?\$select=id,name,size,contentType,isInline&\$top=200" "$ATT")
    [[ "$CODE" == "200" ]] || { echo "ERROR: attachment list ${i} HTTP ${CODE}: $(jq -r '.error.code // "-"' "$ATT" 2>/dev/null)" >&2; exit 4; }
    SUM=$(jq '[.value[].size // 0] | add // 0' "$ATT")
    FETCH_TOTAL=$((FETCH_TOTAL + SUM))
    ATT_FILES+=("$ATT")
done
LIMIT=$((MAX_TOTAL_MB * 1024 * 1024))
if [[ "$FETCH_TOTAL" -gt "$LIMIT" ]]; then
    echo "ERROR: attachments total ${FETCH_TOTAL} bytes exceeds --max-total-mb ${MAX_TOTAL_MB}" >&2
    exit 5
fi

OUT="$WORK/out"; mkdir -p "$OUT"
for i in "${!IDS[@]}"; do
    ID="${IDS[$i]}"; META="$WORK/meta-$i.json"; ATT="${ATT_FILES[$i]}"
    RECEIVED=$(jq -r '.receivedDateTime // "unknown"' "$META" | sed -e 's/[:]//g' -e 's/\.[0-9]*Z$/Z/')
    SUBJECT=$(jq -r '.subject // "no-subject"' "$META")
    SLUG=$(printf '%s' "$SUBJECT" | tr -d '\000-\037' | tr '/\\:*?"<>|' '_________' | cut -c1-60)
    DIR="$OUT/${RECEIVED}_${SLUG}"
    n=1; while [[ -e "$DIR" ]]; do DIR="$OUT/${RECEIVED}_${SLUG}_$n"; n=$((n+1)); done
    mkdir -p "$DIR/attachments"
    jq '{id, subject, from: .from.emailAddress, to: [.toRecipients[]?.emailAddress], cc: [.ccRecipients[]?.emailAddress], receivedDateTime, hasAttachments}' "$META" > "$DIR/message.json"
    CODE=$(curl -sS -o "$DIR/message.eml" -w '%{http_code}' -H "Authorization: Bearer ${ACCESS_TOKEN}" "${GRAPH}/users/${MAILBOX}/messages/${ID}/\$value")
    [[ "$CODE" == "200" ]] || { echo "ERROR: MIME ${i} HTTP ${CODE}" >&2; exit 4; }
    jq '[.value[] | {id, name, size, contentType, isInline, type: .["@odata.type"]}]' "$ATT" > "$DIR/attachments.json"
    while IFS=$'\t' read -r AID ANAME ATYPE; do
        [[ -n "$AID" ]] || continue
        SAFE=$(sanitize "$ANAME"); [[ -n "$SAFE" ]] || SAFE="attachment"
        if [[ "$ATYPE" == "#microsoft.graph.itemAttachment" && "$SAFE" != *.eml ]]; then SAFE="${SAFE}.eml"; fi
        TARGET="$DIR/attachments/$SAFE"; k=1
        while [[ -e "$TARGET" ]]; do TARGET="$DIR/attachments/${k}_${SAFE}"; k=$((k+1)); done
        CODE=$(curl -sS -o "$TARGET" -w '%{http_code}' -H "Authorization: Bearer ${ACCESS_TOKEN}" "${GRAPH}/users/${MAILBOX}/messages/${ID}/attachments/${AID}/\$value")
        [[ "$CODE" == "200" ]] || { echo "ERROR: attachment '${ANAME}' HTTP ${CODE}" >&2; exit 4; }
    done < <(jq -r '.value[] | [.id, .name, .["@odata.type"]] | @tsv' "$ATT")
    echo "fetched: $(basename "$DIR") ($(find "$DIR/attachments" -type f | wc -l | tr -d ' ') attachments)" >&2
done

tar -C "$OUT" -cf - .
EOSSH
