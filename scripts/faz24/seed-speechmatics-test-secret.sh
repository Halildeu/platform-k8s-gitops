#!/usr/bin/env bash
set -euo pipefail

# Secret-safe TEST seed for Faz 24 #3240. The value is entered on the Vault
# host's TTY and is never placed in argv, shell history, stdout or this machine.

HOST="${SPEECHMATICS_VAULT_HOST:-staging-sw}"
VAULT_PATH="kv/platform/audio-gateway-speechmatics"

if [[ $# -gt 0 ]]; then
  printf 'usage: SPEECHMATICS_VAULT_HOST=<ssh-host> %s\n' "$0" >&2
  exit 2
fi

printf 'Target: %s (%s)\n' "$HOST" "$VAULT_PATH"
printf 'The API key will be read by the remote TTY without echo.\n'

REMOTE_SCRIPT=$(cat <<'REMOTE'
set -eu

restore_tty() {
  stty echo </dev/tty 2>/dev/null || true
  unset SPEECHMATICS_API_KEY
}
trap restore_tty EXIT HUP INT TERM

printf 'Speechmatics TEST API key: ' >&2
stty -echo </dev/tty
IFS= read -r SPEECHMATICS_API_KEY </dev/tty
stty echo </dev/tty
printf '\n' >&2

if [ -z "$SPEECHMATICS_API_KEY" ]; then
  printf 'ERROR: empty key refused\n' >&2
  exit 1
fi

printf '%s' "$SPEECHMATICS_API_KEY" \
  | vault kv put "$VAULT_PATH" api_key=- >/dev/null
unset SPEECHMATICS_API_KEY

vault kv get -format=json "$VAULT_PATH" \
  | jq -e '.data.data.api_key | type == "string" and length > 0' >/dev/null
printf 'Vault read-back: api_key present (value redacted)\n'
REMOTE
)

# Pass only the static script and Vault path in argv. The API key itself is read
# from /dev/tty on the remote host, so SSH stdin remains the user's terminal.
printf -v REMOTE_COMMAND 'VAULT_PATH=%q bash -lc %q' "$VAULT_PATH" "$REMOTE_SCRIPT"
ssh -tt "$HOST" "$REMOTE_COMMAND"
