#!/usr/bin/env bash
# seed-graph-read-kv.sh — Seed kv/platform/graph-read (the Mail.Read-only Entra app
# `acik-mail-graph-read`) on the production Vault.
#
# Explicit OWNER action: this mutates the production Vault, which is owner-gated.
# The client secret is read from a no-echo terminal prompt and travels only via
# stdin — never argv, never env-by-value, never shell history, never a log line.
# The Vault root token is read on aiserver inside the same pipe and is never
# printed. Output is limited to the KV path, its key names and the version written.
#
# Usage:
#   ./seed-graph-read-kv.sh --client-id <app-client-id> [--tenant-id <tenant-id>] [--ssh-host HOST]
#   pbpaste | ./seed-graph-read-kv.sh --client-id <app-client-id> --secret-stdin
#
# --secret-stdin reads the secret from a pipe instead of the prompt (e.g. straight
# from the clipboard after the portal's "copy" button), so the value never has to
# be typed, echoed, or held by anything but the pipe. Still never an argument.
#
# --tenant-id is optional: both apps live in the same tenant, so by default the
# value is copied on aiserver from kv/platform/graph (graph_tenant_id) inside the
# same in-band pipe — nothing that Vault already knows has to be retyped.
#
# Afterwards: provision-graph-mail-vault-approle.sh --identity graph-read, then
# graph-mail-list.sh --identity graph-read --show-roles --mailbox halil.kocoglu@acik.com

set -euo pipefail

SSH_HOST="${GRAPH_MAIL_VAULT_SSH_HOST:-aiadmin@aiserver}"
VAULT_CONTAINER="${GRAPH_MAIL_VAULT_CONTAINER:-platform-vault-prod}"
VAULT_INIT_FILE="${GRAPH_MAIL_VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-prod.json}"
KV_PATH="kv/platform/graph-read"
CLIENT_ID=""
TENANT_ID=""
SECRET_STDIN=0
GUID_RE='^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$'

usage() {
    cat <<'USAGE'
Usage: seed-graph-read-kv.sh --client-id <GUID> [--tenant-id <GUID>] [--ssh-host HOST] [--secret-stdin]

Writes graph_client_id / graph_tenant_id / graph_client_secret to kv/platform/graph-read
on the production Vault. --tenant-id defaults to graph_tenant_id of kv/platform/graph
(same tenant, read on the server). The secret is prompted without echo; it is never
accepted as an argument. Prints only the KV path, key names and the resulting version.
USAGE
}

die() { echo "ERROR: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --client-id) CLIENT_ID="$2"; shift 2 ;;
        --tenant-id) TENANT_ID="$2"; shift 2 ;;
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        --secret-stdin) SECRET_STDIN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument: $1" ;;
    esac
done

[[ "$CLIENT_ID" =~ $GUID_RE ]] || die "--client-id must be the app's client GUID"
[[ -z "$TENANT_ID" || "$TENANT_ID" =~ $GUID_RE ]] || die "--tenant-id must be the tenant GUID (or omit it to reuse kv/platform/graph)"
if [[ "$SECRET_STDIN" == "1" ]]; then
    [[ ! -t 0 ]] || die "--secret-stdin expects the secret on a pipe (e.g. pbpaste | ...)"
    IFS= read -r CLIENT_SECRET || true
    CLIENT_SECRET="${CLIENT_SECRET%$'\r'}"
else
    [[ -t 0 ]] || die "run from an interactive terminal (or pass --secret-stdin with the secret on a pipe); the secret is never an argument"
    read -rs -p "acik-mail-graph-read client secret (input hidden): " CLIENT_SECRET
    echo >&2
fi
[[ ${#CLIENT_SECRET} -ge 16 ]] || die "client secret is implausibly short"
[[ "$CLIENT_SECRET" != *$'\n'* && "$CLIENT_SECRET" != *$'\r'* ]] || die "client secret must be a single line"

# Remote body is a quoted heredoc: nothing expands locally. The root token and the
# secret meet only inside the docker exec pipe; stdout carries metadata only.
REMOTE=$(cat <<'EOR'
set -euo pipefail
GUID_RE='^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$'
if [[ -z "${TENANT_ID:-}" ]]; then
    TENANT_ID=$(
        sudo -n jq -er '.root_token | select(type == "string" and length > 0)' "$VAULT_INIT_FILE" |
            docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
                set -eu
                IFS= read -r VAULT_TOKEN
                export VAULT_TOKEN
                exec vault kv get -field=graph_tenant_id "$1"
            ' sh kv/platform/graph
    )
    [[ "$TENANT_ID" =~ $GUID_RE ]] || { echo "ERROR: kv/platform/graph carries no usable graph_tenant_id" >&2; exit 2; }
    echo "tenant_id copied from kv/platform/graph (${TENANT_ID:0:8}…)" >&2
fi
{
    sudo -n jq -er '.root_token | select(type == "string" and length > 0)' "$VAULT_INIT_FILE"
    cat
} | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    exec vault kv put -format=json "$1" graph_client_id="$2" graph_tenant_id="$3" graph_client_secret=-
' sh "$KV_PATH" "$CLIENT_ID" "$TENANT_ID" |
    jq -c --arg path "$KV_PATH" '{path: $path, version: .data.version, created_time: .data.created_time}'

sudo -n jq -er '.root_token | select(type == "string" and length > 0)' "$VAULT_INIT_FILE" |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
        set -eu
        IFS= read -r VAULT_TOKEN
        export VAULT_TOKEN
        exec vault kv get -format=json "$1"
    ' sh "$KV_PATH" |
    jq -c '{keys: (.data.data | keys), version: .data.metadata.version}'
EOR
)

printf '%s' "$CLIENT_SECRET" | ssh -o BatchMode=yes "$SSH_HOST" \
    "VAULT_INIT_FILE=$(printf '%q' "$VAULT_INIT_FILE") VAULT_CONTAINER=$(printf '%q' "$VAULT_CONTAINER") KV_PATH=$(printf '%q' "$KV_PATH") CLIENT_ID=$(printf '%q' "$CLIENT_ID") TENANT_ID=$(printf '%q' "$TENANT_ID") bash -c $(printf '%q' "$REMOTE")"
unset CLIENT_SECRET
