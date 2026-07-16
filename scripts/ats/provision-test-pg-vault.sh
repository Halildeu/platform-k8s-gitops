#!/usr/bin/env bash
# 39d-2a — ats PG rolü + DB + Vault kv seed (test ortamı; idempotent).
# Parola bu host'ta üretilir; stdout'a ASLA basılmaz (yalnız key adları).
#
# Recovery-only kullanım (mevcut DB/parola/Vault değerine dokunmaz):
#   provision-test-pg-vault.sh --roles-only
set -euo pipefail

MODE=${1:-full}
case "$MODE" in
  full|--roles-only) ;;
  *) echo "usage: $0 [--roles-only]" >&2; exit 2 ;;
esac

# Cluster-scoped role DDL yalnız postgres admin düzleminde yapılır. Flyway V4
# rolü IF NOT EXISTS ile kullanır; runtime ats_app'a CREATEROLE verilmez.
docker exec -i platform-pg-test psql -U postgres -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ats_governance_writer') THEN
    CREATE ROLE ats_governance_writer
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  ELSIF EXISTS (
    SELECT FROM pg_roles
    WHERE rolname = 'ats_governance_writer'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION 'ats_governance_writer guvensiz role attribute tasiyor';
  END IF;
END
$$;
SQL
ROLE_STATE=$(docker exec platform-pg-test psql -U postgres -At -F '|' -c \
  "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='ats_governance_writer'")
[ "$ROLE_STATE" = "f|f|f|f|f|f" ] || {
  echo "FATAL: ats_governance_writer NOLOGIN/least-privilege assert basarisiz" >&2
  exit 1
}
echo "PG: ats_governance_writer NOLOGIN role OK"

assert_ats_app_role() {
  local app_role_state
  app_role_state=$(docker exec platform-pg-test psql -U postgres -At -F '|' -c \
    "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='ats_app'")
  [ "$app_role_state" = "t|f|f|f|f|f" ] || {
    echo "FATAL: ats_app LOGIN/no-admin-attributes assert basarisiz" >&2
    exit 1
  }
  echo "PG: ats_app LOGIN/no-admin-attributes role OK"
}

if [ "$MODE" = "--roles-only" ]; then
  # Recovery, mevcut runtime rolünde önceden oluşmuş yetki genişlemesini de
  # kabul etmez. Bu yol hiçbir parola üretmeden veya Vault'a erişmeden çıkar.
  assert_ats_app_role
  echo "PG: roles-only recovery OK (DB password/Vault degismedi)"
  exit 0
fi

PW=$(openssl rand -hex 16)

# --- PG: ats_app rolü (varsa parola rotate) + ats DB ---
docker exec -i platform-pg-test psql -U postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
DO \$\$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ats_app') THEN
    IF EXISTS (
      SELECT FROM pg_roles
      WHERE rolname = 'ats_app'
        AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
    ) THEN
      RAISE EXCEPTION 'ats_app guvensiz admin role attribute tasiyor';
    END IF;
    ALTER ROLE ats_app WITH LOGIN PASSWORD '${PW}';
  ELSE
    CREATE ROLE ats_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS PASSWORD '${PW}';
  END IF;
END
\$\$;
SQL
assert_ats_app_role
if ! docker exec platform-pg-test psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='ats'" | grep -q 1; then
  docker exec platform-pg-test psql -U postgres -c "CREATE DATABASE ats OWNER ats_app" >/dev/null
fi
echo "PG: ats_app role + ats db OK"

# --- Vault seed: kv/platform/ats (root token dosyadan; ekrana basılmaz) ---
ROOT=$(python3 -c 'import json;print(json.load(open("/home/halil/bootstrap-drill/vault-init-test.json"))["root_token"])')
docker exec -e VAULT_TOKEN="$ROOT" -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test \
  vault kv put kv/platform/ats \
    ATS_DB_URL="jdbc:postgresql://postgres:5432/ats" \
    ATS_DB_USERNAME="ats_app" \
    ATS_DB_PASSWORD="$PW" >/dev/null
echo "VAULT: kv/platform/ats seeded"

# --- doğrulama: yalnız key adları ---
docker exec -e VAULT_TOKEN="$ROOT" -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test \
  vault kv get -format=json kv/platform/ats \
  | python3 -c 'import json,sys; print("VAULT keys:", sorted(json.load(sys.stdin)["data"]["data"].keys()))'

# --- canlı bağlantı testi: ats_app ile ats DB ---
RES=$(docker exec -e PGPASSWORD="$PW" platform-pg-test \
  psql -U ats_app -d ats -h 127.0.0.1 -tAc "SELECT current_user || '@' || current_database()")
echo "PG login test: $RES"
