#!/usr/bin/env bash
# Faz 35 Etik Speak: platform-test PostgreSQL role/database and Vault seed.
# Run on staging-sw. Raw credentials never leave the host or reach stdout.
set -euo pipefail
# A caller may invoke bash -x; disable tracing before any credential is read.
set +x

PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/home/halil/bootstrap-drill/vault-init-test.json}"
VAULT_PATH="${VAULT_PATH:-kv/platform/etik-speak}"

[ "$PG_CONTAINER" = "platform-pg-test" ] || {
  echo "FATAL: this script is test-only; PG_CONTAINER=$PG_CONTAINER refused" >&2
  exit 1
}
[ "$VAULT_CONTAINER" = "platform-vault-test" ] || {
  echo "FATAL: this script is test-only; VAULT_CONTAINER=$VAULT_CONTAINER refused" >&2
  exit 1
}
command -v openssl >/dev/null 2>&1 || { echo "FATAL: openssl missing" >&2; exit 1; }
[ -r "$VAULT_INIT_FILE" ] || { echo "FATAL: Vault init file unreadable" >&2; exit 1; }

vault_root_token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")
trap 'unset db_password vault_root_token existing_db_password' EXIT

# Keep the Vault token out of docker(1) argv. The static container-side shell
# reads it from stdin and exports it only for the short-lived Vault CLI child.
vault_get_field() {
  local field=$1
  printf '%s\n' "$vault_root_token" | docker exec -i \
    -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv get -field="$1" "$2"
    ' sh "$field" "$VAULT_PATH"
}

existing_db_password=$(vault_get_field ETHICS_DB_PASSWORD 2>/dev/null || true)
if [ -n "$existing_db_password" ]; then
  db_password=$existing_db_password
  vault_action='patch'
  vault_password_write=false
else
  db_password=$(openssl rand -hex 24)
  if printf '%s\n' "$vault_root_token" | docker exec -i \
    -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      vault kv get "$1" >/dev/null 2>&1
    ' sh "$VAULT_PATH"; then
    vault_action='patch'
  else
    vault_action='put'
  fi
  vault_password_write=true
fi

# Password travels over stdin, not docker argv. Existing unsafe role attributes
# abort before any password update, so a compromised role is never normalized
# silently. A rerun reuses the existing Vault password and avoids rotation drift.
printf '%s\n' "$db_password" | docker exec -i "$PG_CONTAINER" sh -c '
  set -eu
  IFS= read -r ETHICS_DB_PASSWORD
  export ETHICS_DB_PASSWORD
  psql -U postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
DO \$\$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = '\''ethics_app'\'') THEN
    IF EXISTS (
      SELECT FROM pg_roles
      WHERE rolname = '\''ethics_app'\''
        AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
    ) THEN
      RAISE EXCEPTION '\''ethics_app has unsafe role attributes'\'';
    END IF;
    ALTER ROLE ethics_app WITH LOGIN PASSWORD '\''${ETHICS_DB_PASSWORD}'\'';
  ELSE
    CREATE ROLE ethics_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS PASSWORD '\''${ETHICS_DB_PASSWORD}'\'';
  END IF;
END
\$\$;
SQL
'

role_state=$(docker exec "$PG_CONTAINER" psql -U postgres -At -F '|' -c \
  "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='ethics_app'")
[ "$role_state" = "t|f|f|f|f|f" ] || {
  echo "FATAL: ethics_app least-privilege assertion failed" >&2
  exit 1
}

if ! docker exec "$PG_CONTAINER" psql -U postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='ethics'" | grep -qx 1; then
  docker exec "$PG_CONTAINER" psql -U postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE ethics OWNER ethics_app" >/dev/null
fi

if [ "$vault_password_write" = true ]; then
  # The container shell consumes the token line first. Vault then consumes the
  # remaining password bytes for ETHICS_DB_PASSWORD=-, keeping both values out
  # of host/container command arguments and logs.
  { printf '%s\n' "$vault_root_token"; printf '%s' "$db_password"; } | \
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 \
      "$VAULT_CONTAINER" sh -c '
        set -eu
        IFS= read -r VAULT_TOKEN
        export VAULT_TOKEN
        vault kv "$1" "$2" \
          ETHICS_DB_USERNAME=ethics_app ETHICS_DB_PASSWORD=- >/dev/null
      ' sh "$vault_action" "$VAULT_PATH"
else
  printf '%s\n' "$vault_root_token" | docker exec -i \
    -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      vault kv patch "$1" ETHICS_DB_USERNAME=ethics_app >/dev/null
    ' sh "$VAULT_PATH"
fi

login_result=$(printf '%s\n' "$db_password" | docker exec -i "$PG_CONTAINER" sh -c '
  set -eu
  IFS= read -r PGPASSWORD
  export PGPASSWORD
  exec psql -U ethics_app -d ethics -h 127.0.0.1 -Atc \
    "SELECT current_user || '\''@'\'' || current_database()"
')
[ "$login_result" = "ethics_app@ethics" ] || {
  echo "FATAL: ethics_app login verification failed" >&2
  exit 1
}

echo "PG: ethics_app least-privilege role + ethics database OK"
echo "Vault: $VAULT_PATH DB keys seeded; raw values not printed"
