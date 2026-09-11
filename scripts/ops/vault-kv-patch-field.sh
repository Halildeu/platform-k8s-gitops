#!/usr/bin/env bash
# vault-kv-patch-field.sh — Patch ONE field of an existing KV v2 secret on the
# test or production Vault on aiserver, with the value arriving only via stdin.
#
# Owner/operator action (the production Vault is owner-gated by policy). The
# value is read from a no-echo prompt or, with --secret-stdin, from a pipe such as
# `pbpaste | …` — never argv, env-by-value, history or a log line. The Vault root
# token is read on aiserver inside the same pipe and never printed. Output is the
# path, key names and the resulting version only.
#
# Usage:
#   ./vault-kv-patch-field.sh --vault prod --path kv/platform/notification-orchestrator --field smtp_password
#   pbpaste | ./vault-kv-patch-field.sh --vault test --path kv/platform/foo --field bar --secret-stdin
#
# Guard rails: the secret must already exist (patch, never put), the field name
# is validated, and a value with a newline is refused.

set -euo pipefail

SSH_HOST="${VAULT_KV_SSH_HOST:-aiadmin@aiserver}"
VAULT_ENV=""
KV_PATH=""
FIELD=""
SECRET_STDIN=0

usage() {
    cat <<'USAGE'
Usage: vault-kv-patch-field.sh --vault test|prod --path kv/<mount-path> --field NAME [--secret-stdin] [--ssh-host HOST]

Patches a single field of an existing KV v2 secret. The value is prompted without
echo, or read from a pipe with --secret-stdin; it is never accepted as an argument.
Prints only the path, key names and the new version.
USAGE
}

die() { echo "ERROR: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --vault) VAULT_ENV="$2"; shift 2 ;;
        --path) KV_PATH="$2"; shift 2 ;;
        --field) FIELD="$2"; shift 2 ;;
        --secret-stdin) SECRET_STDIN=1; shift ;;
        --ssh-host) SSH_HOST="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument: $1" ;;
    esac
done

case "$VAULT_ENV" in
    test) VAULT_CONTAINER="platform-vault-test"; VAULT_INIT_FILE="/srv/platform/secrets/backup-auth/vault-init-test.json" ;;
    prod) VAULT_CONTAINER="platform-vault-prod"; VAULT_INIT_FILE="/srv/platform/secrets/backup-auth/vault-init-prod.json" ;;
    *) die "--vault must be test or prod" ;;
esac
[[ "$KV_PATH" =~ ^kv/[A-Za-z0-9._/-]+$ && "$KV_PATH" != *..* ]] || die "--path must look like kv/<path>"
[[ "$FIELD" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || die "--field must be a plain key name"

if [[ "$SECRET_STDIN" == "1" ]]; then
    [[ ! -t 0 ]] || die "--secret-stdin expects the value on a pipe (e.g. pbpaste | ...)"
    IFS= read -r VALUE || true
    VALUE="${VALUE%$'\r'}"
else
    [[ -t 0 ]] || die "run from an interactive terminal (or pass --secret-stdin with the value on a pipe); the value is never an argument"
    read -rs -p "${VAULT_ENV} ${KV_PATH} ${FIELD} value (input hidden): " VALUE
    echo >&2
fi
[[ ${#VALUE} -ge 8 ]] || die "value is implausibly short"
[[ "$VALUE" != *$'\n'* && "$VALUE" != *$'\r'* ]] || die "value must be a single line"

REMOTE=$(cat <<'EOR'
set -euo pipefail
{
    sudo -n jq -er '.root_token | select(type == "string" and length > 0)' "$VAULT_INIT_FILE"
    cat
} | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    vault kv metadata get "$1" >/dev/null 2>&1 || { echo "ERROR: secret does not exist: $1 (patch only, no put)" >&2; exit 2; }
    exec vault kv patch -format=json "$1" "$2"=-
' sh "$KV_PATH" "$FIELD" |
    jq -c --arg path "$KV_PATH" --arg field "$FIELD" '{path: $path, field: $field, version: .data.version, created_time: .data.created_time}'
EOR
)

printf '%s' "$VALUE" | ssh -o BatchMode=yes "$SSH_HOST" \
    "VAULT_INIT_FILE=$(printf '%q' "$VAULT_INIT_FILE") VAULT_CONTAINER=$(printf '%q' "$VAULT_CONTAINER") KV_PATH=$(printf '%q' "$KV_PATH") FIELD=$(printf '%q' "$FIELD") bash -c $(printf '%q' "$REMOTE")"
unset VALUE
