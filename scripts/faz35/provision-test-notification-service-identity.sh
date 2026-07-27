#!/usr/bin/env bash
# Faz 35 ES-208 — seed one TEST-only service credential into the two Vault
# documents consumed by auth-service and ethics-service. Raw material never
# reaches argv, stdout, stderr, Git or Kubernetes imperative mutation.
set -euo pipefail
set +x

MODE="${1:---check}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE_DEFAULT="$HOME/bootstrap-drill/vault-init-test.json"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-$VAULT_INIT_FILE_DEFAULT}"
AUTH_PATH="kv/platform/auth-service"
AUTH_FIELD="service_client_ethics_service_secret"
ETHICS_PATH="kv/platform/etik-speak"
ETHICS_FIELD="ETHICS_NOTIFICATION_CLIENT_SECRET"

case "$MODE" in
  --check|--apply) ;;
  *)
    echo "FATAL: usage: $0 [--check|--apply]" >&2
    exit 64
    ;;
esac
if [ "$(hostname -s)" != "aiserver" ] ||
  ! hostname -I | grep -qw "10.9.10.15"; then
  echo "FATAL: this TEST provisioner must run on authoritative aiserver 10.9.10.15" >&2
  exit 1
fi
[ "$VAULT_CONTAINER" = "platform-vault-test" ] || {
  echo "FATAL: VAULT_CONTAINER override refused" >&2
  exit 1
}
[ "$VAULT_INIT_FILE" = "$VAULT_INIT_FILE_DEFAULT" ] || {
  echo "FATAL: VAULT_INIT_FILE override refused" >&2
  exit 1
}
for command_name in docker jq mktemp openssl sha256sum stat; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "FATAL: required command missing: $command_name" >&2
    exit 1
  }
done
[ -r "$VAULT_INIT_FILE" ] && [ -f "$VAULT_INIT_FILE" ] &&
  [ ! -L "$VAULT_INIT_FILE" ] || {
  echo "FATAL: Vault init file must be a readable regular non-symlink" >&2
  exit 1
}
[ "$(stat -c '%u' "$VAULT_INIT_FILE")" = "$(id -u)" ] &&
  [ "$(stat -c '%a' "$VAULT_INIT_FILE")" = 600 ] || {
  echo "FATAL: Vault init file must be invoking-user-owned mode 600" >&2
  exit 1
}
[ "$(docker inspect -f '{{.State.Running}}' "$VAULT_CONTAINER")" = true ] || {
  echo "FATAL: platform-vault-test is not running" >&2
  exit 1
}

vault_root_token=$(
  jq -er '.root_token | select(type == "string" and length >= 20)' \
    "$VAULT_INIT_FILE"
)
auth_document=""
ethics_document=""
candidate=""
trap 'unset vault_root_token auth_document ethics_document auth_value ethics_value candidate verified_auth verified_ethics; [ -z "${vault_stdout:-}" ] || rm -f "$vault_stdout"; [ -z "${vault_stderr:-}" ] || rm -f "$vault_stderr"' EXIT

vault_read_document() {
  local path=$1 status=0
  vault_stdout=$(mktemp /tmp/faz35-notify-vault-out.XXXXXX)
  vault_stderr=$(mktemp /tmp/faz35-notify-vault-err.XXXXXX)
  chmod 600 "$vault_stdout" "$vault_stderr"
  if printf '%s\n' "$vault_root_token" | docker exec -i \
      -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
        set -eu
        IFS= read -r VAULT_TOKEN
        export VAULT_TOKEN
        exec vault kv get -format=json "$1"
      ' sh "$path" >"$vault_stdout" 2>"$vault_stderr"; then
    status=0
  else
    status=$?
  fi
  [ "$status" -eq 0 ] || {
    echo "FATAL: Vault document read failed for approved TEST path" >&2
    return "$status"
  }
  jq -e -s 'length == 1 and (.[0].data.data | type == "object")' \
    "$vault_stdout" >/dev/null || {
    echo "FATAL: Vault response is not one valid KV v2 document" >&2
    return 1
  }
  cat "$vault_stdout"
  rm -f "$vault_stdout" "$vault_stderr"
  vault_stdout=""
  vault_stderr=""
}

vault_patch_stdin() {
  local path=$1 field=$2 value=$3
  { printf '%s\n' "$vault_root_token"; printf '%s' "$value"; } |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 \
      "$VAULT_CONTAINER" sh -c '
        set -eu
        IFS= read -r VAULT_TOKEN
        export VAULT_TOKEN
        exec vault kv patch "$1" "$2"=- >/dev/null
      ' sh "$path" "$field"
}

auth_document=$(vault_read_document "$AUTH_PATH")
ethics_document=$(vault_read_document "$ETHICS_PATH")
auth_value=$(printf '%s' "$auth_document" | jq -er \
  --arg field "$AUTH_FIELD" '.data.data[$field] // ""')
ethics_value=$(printf '%s' "$ethics_document" | jq -er \
  --arg field "$ETHICS_FIELD" '.data.data[$field] // ""')
unset auth_document ethics_document

if [ -n "$auth_value" ] && [ -n "$ethics_value" ] &&
  [ "$auth_value" != "$ethics_value" ]; then
  echo "FATAL: existing auth/ethics notification credentials diverge; automatic rotation refused" >&2
  exit 1
fi
candidate="${auth_value:-$ethics_value}"
if [ -n "$candidate" ]; then
  printf '%s' "$candidate" | grep -Eq '^[0-9a-f]{64}$' || {
    echo "FATAL: existing notification credential violates the exact 256-bit hex policy" >&2
    exit 1
  }
fi

if [ "$MODE" = "--check" ]; then
  if [ -n "$auth_value" ] && [ -n "$ethics_value" ]; then
    printf 'notification_identity=READY hash=sha256:%s\n' \
      "$(printf '%s' "$candidate" | sha256sum | awk '{print $1}')"
    exit 0
  fi
  printf 'notification_identity=MISSING auth=%s ethics=%s\n' \
    "$([ -n "$auth_value" ] && printf present || printf missing)" \
    "$([ -n "$ethics_value" ] && printf present || printf missing)"
  exit 2
fi

[ "${CONFIRM_TEST_NOTIFICATION_IDENTITY:-}" = "seed-faz35-es208" ] || {
  echo "FATAL: --apply requires CONFIRM_TEST_NOTIFICATION_IDENTITY=seed-faz35-es208" >&2
  exit 1
}
if [ -z "$candidate" ]; then
  candidate=$(openssl rand -hex 32)
fi
[ -n "$auth_value" ] ||
  vault_patch_stdin "$AUTH_PATH" "$AUTH_FIELD" "$candidate"
[ -n "$ethics_value" ] ||
  vault_patch_stdin "$ETHICS_PATH" "$ETHICS_FIELD" "$candidate"

verified_auth=$(vault_read_document "$AUTH_PATH" | jq -er \
  --arg field "$AUTH_FIELD" '.data.data[$field]')
verified_ethics=$(vault_read_document "$ETHICS_PATH" | jq -er \
  --arg field "$ETHICS_FIELD" '.data.data[$field]')
[ "$verified_auth" = "$candidate" ] &&
  [ "$verified_ethics" = "$candidate" ] || {
  echo "FATAL: notification credential read-after-write mismatch" >&2
  exit 1
}
printf 'notification_identity=READY hash=sha256:%s\n' \
  "$(printf '%s' "$candidate" | sha256sum | awk '{print $1}')"
