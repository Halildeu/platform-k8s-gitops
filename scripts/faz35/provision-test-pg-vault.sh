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
PUBLIC_GATE_USERNAME="${PUBLIC_GATE_USERNAME:-etik-test}"
PUBLIC_GATE_PASSWORD_FILE="${PUBLIC_GATE_PASSWORD_FILE:-/home/halil/bootstrap-drill/etik-speak-public-gate.password}"

[ "$PG_CONTAINER" = "platform-pg-test" ] || {
  echo "FATAL: this script is test-only; PG_CONTAINER=$PG_CONTAINER refused" >&2
  exit 1
}
[ "$VAULT_CONTAINER" = "platform-vault-test" ] || {
  echo "FATAL: this script is test-only; VAULT_CONTAINER=$VAULT_CONTAINER refused" >&2
  exit 1
}
[ "$VAULT_INIT_FILE" = "/home/halil/bootstrap-drill/vault-init-test.json" ] || {
  echo "FATAL: VAULT_INIT_FILE override refused" >&2
  exit 1
}
[ "$VAULT_PATH" = "kv/platform/etik-speak" ] || {
  echo "FATAL: VAULT_PATH override refused" >&2
  exit 1
}
[ "$PUBLIC_GATE_USERNAME" = "etik-test" ] && \
  [ "$PUBLIC_GATE_PASSWORD_FILE" = "/home/halil/bootstrap-drill/etik-speak-public-gate.password" ] || {
  echo "FATAL: public test-gate target override refused" >&2
  exit 1
}
command -v openssl >/dev/null 2>&1 || { echo "FATAL: openssl missing" >&2; exit 1; }
[ -r "$VAULT_INIT_FILE" ] || { echo "FATAL: Vault init file unreadable" >&2; exit 1; }

vault_root_token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")
trap 'unset db_password vault_root_token existing_db_password public_gate_password public_gate_hash public_gate_htpasswd vault_entry_json' EXIT

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

vault_entry_status=0
if vault_entry_json=$(printf '%s\n' "$vault_root_token" | docker exec -i \
  -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    err=$(mktemp)
    trap '\''rm -f "$err"'\'' EXIT
    if vault kv get -format=json "$1" 2>"$err"; then
      exit 0
    fi
    grep -Eqi "no value found|not found" "$err" && exit 44
    exit 45
  ' sh "$VAULT_PATH"); then
  vault_entry_status=0
else
  vault_entry_status=$?
fi
case "$vault_entry_status" in
  0) existing_db_password=$(printf '%s' "$vault_entry_json" | jq -r '.data.data.ETHICS_DB_PASSWORD // empty') ;;
  44) existing_db_password="" ;;
  *) echo "FATAL: Vault read failed; refusing to classify it as missing" >&2; exit 1 ;;
esac
unset vault_entry_json

if [ -n "$existing_db_password" ]; then
  db_password=$existing_db_password
  vault_action='patch'
  vault_password_write=false
else
  db_password=$(openssl rand -hex 24)
  [ "$vault_entry_status" = 0 ] && vault_action='patch' || vault_action='put'
  vault_password_write=true
fi

# Commit the newly generated password to Vault before changing PostgreSQL. If
# PostgreSQL fails, the same password remains recoverable and a rerun converges.
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

verified_db_password=$(vault_get_field ETHICS_DB_PASSWORD)
[ "$verified_db_password" = "$db_password" ] || {
  echo "FATAL: Vault DB password read-after-write mismatch" >&2
  exit 1
}
unset verified_db_password

ensure_local_secret_file() {
  local file=$1 generated=$2 owner mode
  if [ -e "$file" ] || [ -L "$file" ]; then
    [ ! -L "$file" ] && [ -f "$file" ] || {
      echo "FATAL: secret file must be a regular non-symlink: $file" >&2
      exit 1
    }
  else
    umask 077
    (set -C; printf '%s' "$generated" >"$file") || {
      echo "FATAL: exclusive secret file creation failed: $file" >&2
      exit 1
    }
  fi
  chmod 600 "$file"
  owner=$(stat -c '%u' "$file")
  mode=$(stat -c '%a' "$file")
  [ "$owner" = "$(id -u)" ] && [ "$mode" = 600 ] || {
    echo "FATAL: secret file owner/mode check failed: $file" >&2
    exit 1
  }
}

public_gate_candidate=$(openssl rand -base64 36 | tr -d '/+=' | cut -c1-36)
ensure_local_secret_file "$PUBLIC_GATE_PASSWORD_FILE" "$public_gate_candidate"
unset public_gate_candidate
public_gate_password=$(<"$PUBLIC_GATE_PASSWORD_FILE")
[ ${#public_gate_password} -ge 24 ] || { echo "FATAL: public gate password too short" >&2; exit 1; }
public_gate_hash=$(printf '%s' "$public_gate_password" | openssl passwd -apr1 -stdin)
public_gate_htpasswd="$PUBLIC_GATE_USERNAME:$public_gate_hash"
{ printf '%s\n' "$vault_root_token"; printf '%s' "$public_gate_htpasswd"; } | \
  docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 \
    "$VAULT_CONTAINER" sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      vault kv patch "$1" EDGE_BASIC_AUTH_HTPASSWD=- >/dev/null
    ' sh "$VAULT_PATH"
verified_gate_htpasswd=$(vault_get_field EDGE_BASIC_AUTH_HTPASSWD)
[ "$verified_gate_htpasswd" = "$public_gate_htpasswd" ] || {
  echo "FATAL: Vault public-gate hash read-after-write mismatch" >&2
  exit 1
}
unset verified_gate_htpasswd public_gate_password public_gate_hash public_gate_htpasswd

# Create/validate the login role without embedding a cleartext password in SQL.
docker exec "$PG_CONTAINER" psql -U postgres -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ethics_app') THEN
    IF EXISTS (
      SELECT FROM pg_roles
      WHERE rolname = 'ethics_app'
        AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
    ) THEN
      RAISE EXCEPTION 'ethics_app has unsafe role attributes';
    END IF;
    ALTER ROLE ethics_app WITH LOGIN;
  ELSE
    CREATE ROLE ethics_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;
SQL

# psql's \password command hashes client-side and avoids cleartext password SQL
# in server statement logs. The password itself arrives only over stdin.
printf '%s\n' "$db_password" | docker exec -i "$PG_CONTAINER" sh -c '
  set -eu
  IFS= read -r ETHICS_DB_PASSWORD
  { printf "\\password ethics_app\n"; printf "%s\n%s\n" "$ETHICS_DB_PASSWORD" "$ETHICS_DB_PASSWORD"; } \
    | psql -X -U postgres -v ON_ERROR_STOP=1 >/dev/null
  unset ETHICS_DB_PASSWORD
'

role_state=$(docker exec "$PG_CONTAINER" psql -U postgres -At -F '|' -c \
  "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='ethics_app'")
[ "$role_state" = "t|f|f|f|f|f" ] || {
  echo "FATAL: ethics_app least-privilege assertion failed" >&2
  exit 1
}

db_owner=$(docker exec "$PG_CONTAINER" psql -U postgres -Atc \
  "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='ethics'")
if [ -z "$db_owner" ]; then
  docker exec "$PG_CONTAINER" psql -U postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE ethics OWNER ethics_app" >/dev/null
elif [ "$db_owner" != ethics_app ]; then
  echo "FATAL: existing ethics database owner is not ethics_app" >&2
  exit 1
fi

schema_owner=$(docker exec "$PG_CONTAINER" psql -U postgres -d ethics -Atc \
  "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='public'")
case "$schema_owner" in
  ethics_app|pg_database_owner) ;;
  *) echo "FATAL: unexpected ethics.public schema owner" >&2; exit 1 ;;
esac
docker exec "$PG_CONTAINER" psql -U postgres -d ethics -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
REVOKE ALL ON DATABASE ethics FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE ethics TO ethics_app;
ALTER SCHEMA public OWNER TO ethics_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO ethics_app;
SQL
isolation_state=$(docker exec "$PG_CONTAINER" psql -U postgres -d ethics -At -F '|' -c \
  "SELECT pg_get_userbyid(nspowner),has_database_privilege('public','ethics','CONNECT'),has_database_privilege('ethics_app','ethics','CONNECT'),has_schema_privilege('public','public','CREATE'),has_schema_privilege('ethics_app','public','CREATE') FROM pg_namespace WHERE nspname='public'")
[ "$isolation_state" = "ethics_app|f|t|f|t" ] || {
  echo "FATAL: ethics database/schema isolation assertion failed" >&2
  exit 1
}

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
echo "Vault: $VAULT_PATH DB keys + public test gate seeded; raw values not printed"
echo "PUBLIC_GATE_USERNAME=$PUBLIC_GATE_USERNAME"
echo "PUBLIC_GATE_PASSWORD_FILE=$PUBLIC_GATE_PASSWORD_FILE"
