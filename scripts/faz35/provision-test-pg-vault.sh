#!/usr/bin/env bash
# Faz 35 Etik Speak: platform-test PostgreSQL role/database and Vault seed.
# Run on staging-sw. Raw credentials never leave the host or reach stdout.
set -euo pipefail
# A caller may invoke bash -x; disable tracing before any credential is read.
set +x

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EXPECTED_ESO_POLICY="$SCRIPT_DIR/../../bootstrap/vault-policies/test/etik-speak-eso.hcl"
ESO_POLICY_FILE="${ESO_POLICY_FILE:-$EXPECTED_ESO_POLICY}"
ESO_POLICY_NAME="${ESO_POLICY_NAME:-etik-speak-eso-test}"
ESO_APPROLE_NAME="${ESO_APPROLE_NAME:-etik-speak-eso-test}"
ESO_SECRET_NAME="${ESO_SECRET_NAME:-etik-speak-vault-approle}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"

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
for binding in \
  "$ESO_POLICY_NAME=etik-speak-eso-test" \
  "$ESO_APPROLE_NAME=etik-speak-eso-test" \
  "$ESO_SECRET_NAME=etik-speak-vault-approle" \
  "$KUBE_CONTEXT=k3d-test" \
  "$KUBE_NS=platform-test"; do
  [ "${binding%%=*}" = "${binding#*=}" ] || {
    echo "FATAL: ESO provisioning target override refused: ${binding%%=*}" >&2
    exit 1
  }
done
[ -f "$ESO_POLICY_FILE" ] && [ ! -L "$ESO_POLICY_FILE" ] || {
  echo "FATAL: dedicated ESO policy must be a regular non-symlink" >&2
  exit 1
}
[ "$(cd "$(dirname "$ESO_POLICY_FILE")" && pwd -P)/$(basename "$ESO_POLICY_FILE")" = \
  "$(cd "$(dirname "$EXPECTED_ESO_POLICY")" && pwd -P)/$(basename "$EXPECTED_ESO_POLICY")" ] || {
  echo "FATAL: ESO_POLICY_FILE override refused" >&2
  exit 1
}
command -v openssl >/dev/null 2>&1 || { echo "FATAL: openssl missing" >&2; exit 1; }
[ -r "$VAULT_INIT_FILE" ] && [ -f "$VAULT_INIT_FILE" ] && [ ! -L "$VAULT_INIT_FILE" ] || {
  echo "FATAL: Vault init file must be a readable regular non-symlink" >&2
  exit 1
}
[ "$(stat -c '%u' "$VAULT_INIT_FILE")" = "$(id -u)" ] && \
  [ "$(stat -c '%a' "$VAULT_INIT_FILE")" = 600 ] || {
  echo "FATAL: Vault init file must be invoking-user-owned mode 600" >&2
  exit 1
}

vault_root_token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE")
approle_secret_file=""
trap 'unset db_password vault_root_token existing_db_password public_gate_password public_gate_hash public_gate_htpasswd vault_entry_json approle_json approle_secret_id; [ -z "${approle_secret_file:-}" ] || rm -f "$approle_secret_file"' EXIT

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
    owner=$(stat -c '%u' "$file")
    mode=$(stat -c '%a' "$file")
    [ "$owner" = "$(id -u)" ] && [ "$mode" = 600 ] || {
      echo "FATAL: existing secret file was not invoking-user-owned mode 600; rotation required: $file" >&2
      exit 1
    }
  else
    umask 077
    (set -C; printf '%s' "$generated" >"$file") || {
      echo "FATAL: exclusive secret file creation failed: $file" >&2
      exit 1
    }
    chmod 600 "$file"
  fi
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
[[ "$public_gate_password" =~ ^[A-Za-z0-9_-]{24,128}$ ]] || {
  echo "FATAL: public gate password fails the canonical length/format policy" >&2
  exit 1
}
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

# Create a product-scoped Vault policy/AppRole and place only its secret_id in
# the product namespace. The broad shared ClusterSecretStore role is never
# referenced by Etik Speak. Policy and role configuration are idempotent; the
# static secret_id is rotated on each reviewed provisioner run.
{
  printf '%s\n' "$vault_root_token"
  cat "$ESO_POLICY_FILE"
} | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 \
  "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    policy_file=$(mktemp)
    trap '\''rm -f "$policy_file"'\'' EXIT
    cat >"$policy_file"
    vault policy write "$1" "$policy_file" >/dev/null
    vault write "auth/approle/role/$2" \
      token_policies="$1" token_no_default_policy=true \
      token_ttl=15m token_max_ttl=30m \
      secret_id_ttl=720h secret_id_num_uses=0 >/dev/null
  ' sh "$ESO_POLICY_NAME" "$ESO_APPROLE_NAME"

role_id=$(printf '%s\n' "$vault_root_token" | docker exec -i \
  -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    exec vault read -field=role_id "auth/approle/role/$1/role-id"
  ' sh "$ESO_APPROLE_NAME")
printf '%s' "$role_id" | grep -Eq '^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$' || {
  echo "FATAL: dedicated ESO AppRole role_id is not a UUID" >&2
  exit 1
}

old_accessors=$(printf '%s\n' "$vault_root_token" | docker exec -i \
  -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    error_file=$(mktemp)
    trap '\''rm -f "$error_file"'\'' EXIT
    if vault list -format=json "auth/approle/role/$1/secret-id" 2>"$error_file"; then
      exit 0
    fi
    if grep -Eqi "no value found|not found" "$error_file"; then
      printf "[]"
      exit 0
    fi
    printf "Vault AppRole accessor list failed; rotation refused.\n" >&2
    exit 45
  ' sh "$ESO_APPROLE_NAME") || {
  echo "FATAL: existing AppRole credentials could not be enumerated" >&2
  exit 1
}
approle_json=$(printf '%s\n' "$vault_root_token" | docker exec -i \
  -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    exec vault write -format=json -f "auth/approle/role/$1/secret-id"
  ' sh "$ESO_APPROLE_NAME")
approle_secret_id=$(printf '%s' "$approle_json" | jq -r '.data.secret_id // empty')
new_accessor=$(printf '%s' "$approle_json" | jq -r '.data.secret_id_accessor // empty')
[ -n "$approle_secret_id" ] && [ -n "$new_accessor" ] || {
  echo "FATAL: dedicated ESO AppRole secret generation failed" >&2
  exit 1
}

umask 077
approle_secret_file=$(mktemp)
printf '%s' "$approle_secret_id" >"$approle_secret_file"
chmod 600 "$approle_secret_file"
kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" create secret generic "$ESO_SECRET_NAME" \
  --from-file=secret-id="$approle_secret_file" --dry-run=client -o yaml \
  | kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NS" apply -f - >/dev/null
unset approle_secret_id approle_json
rm -f "$approle_secret_file"
approle_secret_file=""

printf '%s' "$old_accessors" | jq -r '.[]?' | while IFS= read -r accessor; do
  [ -n "$accessor" ] && [ "$accessor" != "$new_accessor" ] || continue
  printf '%s\n' "$vault_root_token" | docker exec -i \
    -e VAULT_ADDR=http://127.0.0.1:8200 -e SECRET_ID_ACCESSOR="$accessor" \
    "$VAULT_CONTAINER" sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      vault write "auth/approle/role/$1/secret-id-accessor/destroy" \
        secret_id_accessor="$SECRET_ID_ACCESSOR" >/dev/null
    ' sh "$ESO_APPROLE_NAME"
done
final_accessors=$(printf '%s\n' "$vault_root_token" | docker exec -i \
  -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    exec vault list -format=json "auth/approle/role/$1/secret-id"
  ' sh "$ESO_APPROLE_NAME") || {
  echo "FATAL: post-rotation AppRole credential enumeration failed" >&2
  exit 1
}
printf '%s' "$final_accessors" | jq -e --arg expected "$new_accessor" \
  'type == "array" and length == 1 and .[0] == $expected' >/dev/null || {
  echo "FATAL: stale AppRole credential accessor remains after rotation" >&2
  exit 1
}
unset old_accessors final_accessors new_accessor

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
    IF EXISTS (
      WITH RECURSIVE inherited(roleid) AS (
        SELECT roleid FROM pg_auth_members
          WHERE member = (SELECT oid FROM pg_roles WHERE rolname = 'ethics_app')
        UNION
        SELECT member_of.roleid FROM pg_auth_members member_of
          JOIN inherited ON member_of.member = inherited.roleid
      )
      SELECT 1 FROM inherited
    ) THEN
      RAISE EXCEPTION 'ethics_app inherits an unexpected role';
    END IF;
    IF EXISTS (
      SELECT 1 FROM pg_db_role_setting
      WHERE setrole = (SELECT oid FROM pg_roles WHERE rolname = 'ethics_app')
    ) THEN
      RAISE EXCEPTION 'ethics_app has unexpected role/database settings';
    END IF;
    ALTER ROLE ethics_app WITH LOGIN NOINHERIT;
  ELSE
    CREATE ROLE ethics_app LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;
SQL

# A reused login must not carry direct ACLs from another product. Ownership is
# checked separately; PUBLIC grants are cluster defaults and are not direct
# grants to ethics_app.
database_acl_count=$(docker exec "$PG_CONTAINER" psql -X -U postgres -d postgres -Atc "
  SELECT count(*) FROM pg_database d, LATERAL aclexplode(d.datacl) x
  WHERE x.grantee = (SELECT oid FROM pg_roles WHERE rolname='ethics_app')
    AND NOT (d.datname='ethics' AND d.datdba=x.grantee)")
[ "$database_acl_count" = 0 ] || {
  echo "FATAL: ethics_app has unexpected direct database ACLs" >&2
  exit 1
}
while IFS= read -r database_name; do
  object_acl_count=$(docker exec "$PG_CONTAINER" psql -X -U postgres -d "$database_name" -Atc "
    WITH target AS (SELECT oid FROM pg_roles WHERE rolname='ethics_app')
    SELECT
      (SELECT count(*) FROM pg_namespace n, LATERAL aclexplode(n.nspacl) x, target t WHERE x.grantee=t.oid) +
      (SELECT count(*) FROM pg_class c, LATERAL aclexplode(c.relacl) x, target t WHERE x.grantee=t.oid) +
      (SELECT count(*) FROM pg_attribute a, LATERAL aclexplode(a.attacl) x, target t WHERE x.grantee=t.oid) +
      (SELECT count(*) FROM pg_proc p, LATERAL aclexplode(p.proacl) x, target t WHERE x.grantee=t.oid) +
      (SELECT count(*) FROM pg_type y, LATERAL aclexplode(y.typacl) x, target t WHERE x.grantee=t.oid) +
      (SELECT count(*) FROM pg_default_acl a, LATERAL aclexplode(a.defaclacl) x, target t WHERE x.grantee=t.oid)")
  [ "$object_acl_count" = 0 ] || {
    echo "FATAL: ethics_app has unexpected direct object/default ACLs in $database_name" >&2
    exit 1
  }
done < <(docker exec "$PG_CONTAINER" psql -X -U postgres -d postgres -Atc \
  "SELECT datname FROM pg_database WHERE datallowconn AND datname <> 'template0' ORDER BY datname")

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
  "SELECT rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='ethics_app'")
[ "$role_state" = "t|f|f|f|f|f|f" ] || {
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
echo "Vault/ESO: dedicated read-only Etik Speak AppRole + namespaced secret rotated"
echo "PUBLIC_GATE_USERNAME=$PUBLIC_GATE_USERNAME"
echo "PUBLIC_GATE_PASSWORD_FILE=$PUBLIC_GATE_PASSWORD_FILE"
echo "ETHICS_VAULT_ROLE_ID=$role_id"
