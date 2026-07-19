#!/usr/bin/env bash
# Faz 35 Etik Speak: platform-test PostgreSQL role/database and Vault seed.
# Run on staging-sw. Raw credentials never leave the host or reach stdout.
set -euo pipefail

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

db_password=$(openssl rand -hex 24)
vault_root_token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")
trap 'unset db_password vault_root_token' EXIT

# Password travels over stdin, not argv. Existing unsafe role attributes abort
# before rotation so this script cannot normalize a compromised role silently.
docker exec -i -e ETHICS_DB_PASSWORD="$db_password" "$PG_CONTAINER" sh -c '
  set -eu
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

if docker exec -e VAULT_TOKEN="$vault_root_token" -e VAULT_ADDR=http://127.0.0.1:8200 \
  "$VAULT_CONTAINER" vault kv get "$VAULT_PATH" >/dev/null 2>&1; then
  vault_action='patch'
else
  vault_action='put'
fi
docker exec -e VAULT_TOKEN="$vault_root_token" -e VAULT_ADDR=http://127.0.0.1:8200 \
  -e ETHICS_DB_PASSWORD="$db_password" "$VAULT_CONTAINER" \
  vault kv "$vault_action" "$VAULT_PATH" \
    ETHICS_DB_USERNAME=ethics_app \
    ETHICS_DB_PASSWORD="$db_password" >/dev/null

login_result=$(docker exec -e PGPASSWORD="$db_password" "$PG_CONTAINER" \
  psql -U ethics_app -d ethics -h 127.0.0.1 -Atc \
  "SELECT current_user || '@' || current_database()")
[ "$login_result" = "ethics_app@ethics" ] || {
  echo "FATAL: ethics_app login verification failed" >&2
  exit 1
}

echo "PG: ethics_app least-privilege role + ethics database OK"
echo "Vault: $VAULT_PATH DB keys seeded; raw values not printed"
