#!/usr/bin/env bash
# 39d-2a — ats PG rolü + DB + Vault kv seed (test ortamı; idempotent).
# Parola bu host'ta üretilir; stdout'a ASLA basılmaz (yalnız key adları).
set -euo pipefail

PW=$(openssl rand -hex 16)

# --- PG: ats_app rolü (varsa parola rotate) + ats DB ---
docker exec -i platform-pg-test psql -U postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
DO \$\$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ats_app') THEN
    ALTER ROLE ats_app WITH LOGIN PASSWORD '${PW}';
  ELSE
    CREATE ROLE ats_app LOGIN PASSWORD '${PW}';
  END IF;
END
\$\$;
SQL
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
