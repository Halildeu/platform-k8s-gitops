#!/usr/bin/env bash
#
# Faz 35 ES-302 — make the append-only audit ledger append-only in fact, not just
# by convention (platform-backend#1005).
#
# `ethics_worm_audit` carries an append-only trigger, and the trigger works. But the
# table is owned by `ethics_app` — the runtime role — and in PostgreSQL an owner may
# disable triggers on its own table. The guarantee was therefore held in place by the
# permission of the one role capable of breaking it. Measured, not assumed: as
# `ethics_app` on a scratch table the trigger refused a DELETE, then a single
# `ALTER TABLE ... DISABLE TRIGGER` let the same DELETE through, and TRUNCATE too.
#
# In a whistleblowing system this is not a filing detail. The promise that protects a
# reporter is that the record of what was done to their case cannot be rewritten
# afterwards. That promise needs two independent locks, so that losing one still leaves
# the other standing:
#
#   ACL       runtime role holds SELECT + INSERT only, and owns nothing
#   trigger   append-only invariant, ENABLE ALWAYS (fires on replicas too)
#
# The split is the standard least-privilege layout: a migration role owns the schema and
# runs Flyway; the runtime role only reads and appends. It is not exotic — it is what
# the ledger already claimed to be.
#
# Usage:
#   scripts/faz35/harden-worm-ownership.sh            # --check, read-only
#   scripts/faz35/harden-worm-ownership.sh --apply
#
# Exit: 0 hardened (or --check found nothing to do) · 1 gap remains · 2 could not determine
set -euo pipefail
set +x

MODE="${1:---check}"
PG_CONTAINER="${PG_CONTAINER:-platform-pg-test}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_PATH="kv/platform/etik-speak"
DB_NAME="ethics"
DB_SCHEMA="ethics_service"
RUNTIME_ROLE="ethics_app"
MIGRATOR_ROLE="ethics_migrator"
KUBE_CTX="${KUBE_CTX:-k3d-test}"
KUBE_NS="${KUBE_NS:-platform-test}"

VAULT_INIT_FILE_DEFAULT="/srv/platform/secrets/backup-auth/vault-init-test.json"
[ -r "$VAULT_INIT_FILE_DEFAULT" ] || VAULT_INIT_FILE_DEFAULT="$HOME/bootstrap-drill/vault-init-test.json"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-$VAULT_INIT_FILE_DEFAULT}"

# The append-only pair. Both carry the same trigger and the same reasoning.
APPEND_ONLY_TABLES="ethics_worm_audit ethics_evidence_derivations"

case "$MODE" in
  --check | --apply) ;;
  *)
    echo "kullanim: $0 [--check|--apply]" >&2
    exit 64
    ;;
esac

# Test-only, and refuses to be pointed anywhere else. Production credential and
# ownership changes are owner-gated; this script must not be the thing that quietly
# reaches them.
if [ "$(hostname -s)" != "aiserver" ] || ! hostname -I | grep -qw "10.9.10.15"; then
  echo "FATAL: bu TEST betigi yetkili aiserver 10.9.10.15 uzerinde kosmalidir" >&2
  exit 1
fi
[ "$PG_CONTAINER" = "platform-pg-test" ] || {
  echo "FATAL: PG_CONTAINER override reddedildi" >&2
  exit 1
}
[ "$VAULT_CONTAINER" = "platform-vault-test" ] || {
  echo "FATAL: VAULT_CONTAINER override reddedildi" >&2
  exit 1
}
[ "$VAULT_INIT_FILE" = "$VAULT_INIT_FILE_DEFAULT" ] || {
  echo "FATAL: VAULT_INIT_FILE override reddedildi" >&2
  exit 1
}
for command_name in docker jq openssl kubectl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "FATAL: gerekli komut yok: $command_name" >&2
    exit 1
  }
done

vault_root_token=""
migrator_password=""
vault_stdout=""
vault_stderr=""
trap 'unset vault_root_token migrator_password existing_password; [ -z "${vault_stdout:-}" ] || rm -f "$vault_stdout"; [ -z "${vault_stderr:-}" ] || rm -f "$vault_stderr"' EXIT

gaps=0
note() { printf '      %s\n' "$1"; }
ok() { printf '  \033[32m✓\033[0m %-42s %s\n' "$1" "${2:-}"; }
gap() { printf '  \033[31m✗\033[0m %-42s %s\n' "$1" "${2:-}"; gaps=$((gaps + 1)); }

psql_q() { docker exec "$PG_CONTAINER" psql -U postgres -d "$DB_NAME" -t -A -c "$1" 2>/dev/null; }

printf '\nEtik Speak WORM defteri — degistirilemezlik zemini (%s)\n\n' "$MODE"

# ── Ölçüm ────────────────────────────────────────────────────────────────────────────
# Reported before anything is changed, so --apply and --check tell the same story about
# where things stood.
schema_owner=$(psql_q "select pg_get_userbyid(nspowner) from pg_namespace where nspname='$DB_SCHEMA'")
if [ "$schema_owner" = "$MIGRATOR_ROLE" ]; then
  ok "sema sahibi" "$schema_owner"
else
  gap "sema sahibi" "$schema_owner (calisma zamani rolu)"
fi

for table in $APPEND_ONLY_TABLES; do
  table_owner=$(psql_q "select tableowner from pg_tables where schemaname='$DB_SCHEMA' and tablename='$table'")
  [ -n "$table_owner" ] || {
    echo "FATAL: $DB_SCHEMA.$table bulunamadi" >&2
    exit 2
  }
  if [ "$table_owner" = "$MIGRATOR_ROLE" ]; then
    ok "$table sahibi" "$table_owner"
  else
    gap "$table sahibi" "$table_owner — tetikleyicisini kapatabilir"
  fi

  # Owner rights are implicit and do not show up here; this is the *explicit* grant
  # surface, which is a separate lock and is worth closing on its own.
  writable=$(psql_q "
    select coalesce(string_agg(privilege_type, ','), '') from information_schema.table_privileges
     where table_schema='$DB_SCHEMA' and table_name='$table' and grantee='$RUNTIME_ROLE'
       and privilege_type in ('UPDATE','DELETE','TRUNCATE')")
  if [ -z "$writable" ]; then
    ok "$table yikici yetki" "yok"
  else
    gap "$table yikici yetki" "$writable"
  fi

  # 'O' fires on origin only — a replica would replay changes with the invariant off.
  trigger_state=$(psql_q "
    select tgenabled from pg_trigger
     where tgrelid='$DB_SCHEMA.$table'::regclass and not tgisinternal limit 1")
  case "$trigger_state" in
    A) ok "$table tetikleyici" "ENABLE ALWAYS" ;;
    O) gap "$table tetikleyici" "ORIGIN — replica'da calismaz" ;;
    "") gap "$table tetikleyici" "YOK" ;;
    *) gap "$table tetikleyici" "$trigger_state" ;;
  esac
done

if [ -n "$(psql_q "select 1 from pg_roles where rolname='$MIGRATOR_ROLE'")" ]; then
  ok "$MIGRATOR_ROLE rolu" "var"
else
  gap "$MIGRATOR_ROLE rolu" "yok"
fi

# Flyway must be able to alter the ledger after ownership moves, so the deployment has to
# be carrying the migrator credential before ownership is transferred. Key names only —
# values are never read.
flyway_wired=$(kubectl --context "$KUBE_CTX" -n "$KUBE_NS" get secret ethics-service-secrets \
  -o jsonpath='{.data}' 2>/dev/null | tr ',' '\n' | grep -c 'SPRING_FLYWAY_USER' || true)
if [ "${flyway_wired:-0}" -ge 1 ]; then
  ok "SPRING_FLYWAY_USER kosuluyor" "secret'ta var"
else
  gap "SPRING_FLYWAY_USER kosuluyor" "yok — once ExternalSecret senkronu"
fi

if [ "$MODE" = "--check" ]; then
  printf '\n'
  [ "$gaps" -eq 0 ] && { printf 'Sonuc: zemin saglam.\n\n'; exit 0; }
  printf 'Sonuc: %d acik. Kapatmak icin: %s --apply\n\n' "$gaps" "$0"
  exit 1
fi

# ── Uygulama ─────────────────────────────────────────────────────────────────────────
[ "$gaps" -eq 0 ] && {
  printf '\nSonuc: yapilacak degisiklik yok.\n\n'
  exit 0
}

[ -r "$VAULT_INIT_FILE" ] && [ -f "$VAULT_INIT_FILE" ] && [ ! -L "$VAULT_INIT_FILE" ] || {
  echo "FATAL: Vault init dosyasi okunabilir, duz ve symlink olmayan bir dosya olmali" >&2
  exit 2
}
vault_root_token=$(jq -er '.root_token | select(type == "string" and length >= 20)' "$VAULT_INIT_FILE")

printf '\n  --- uygulaniyor ---\n'

# 1. Migration role. Least-privilege attributes are asserted, not assumed: a role that
#    quietly carries SUPERUSER would reintroduce exactly the problem being closed.
docker exec -i "$PG_CONTAINER" psql -U postgres -v ON_ERROR_STOP=1 >/dev/null <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$MIGRATOR_ROLE') THEN
    CREATE ROLE $MIGRATOR_ROLE LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS;
  ELSIF EXISTS (
    SELECT FROM pg_roles WHERE rolname = '$MIGRATOR_ROLE'
      AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  ) THEN
    RAISE EXCEPTION '$MIGRATOR_ROLE guvensiz role attribute tasiyor';
  END IF;
  -- Membership would hand the runtime role SET ROLE back into ownership and undo the
  -- whole exercise. The ATS pattern grants it deliberately for ALTER DEFAULT PRIVILEGES;
  -- here it must not exist.
  IF EXISTS (
    SELECT FROM pg_auth_members m
      JOIN pg_roles r ON r.oid = m.roleid
      JOIN pg_roles g ON g.oid = m.member
     WHERE r.rolname = '$MIGRATOR_ROLE' AND g.rolname = '$RUNTIME_ROLE'
  ) THEN
    RAISE EXCEPTION '$RUNTIME_ROLE, $MIGRATOR_ROLE uyesi — SET ROLE ile sahiplige geri doner';
  END IF;
END
\$\$;
SQL
echo "  rol hazir: $MIGRATOR_ROLE"

# 2. Credential. Reused when Vault already holds one, so a re-run does not rotate a
#    password the running deployment is already using. Raw material travels on stdin
#    only — never argv, never a log line.
vault_stdout=$(mktemp)
vault_stderr=$(mktemp)
printf '%s\n' "$vault_root_token" | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 \
  "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    exec vault kv get -format=json "$1"
  ' sh "$VAULT_PATH" >"$vault_stdout" 2>"$vault_stderr" || {
  echo "FATAL: Vault dokumani okunamadi" >&2
  exit 2
}
existing_password=$(jq -r '.data.data.ETHICS_MIGRATOR_PASSWORD // empty' "$vault_stdout")
rm -f "$vault_stdout" "$vault_stderr"
vault_stdout=""
vault_stderr=""

if [ -n "$existing_password" ]; then
  migrator_password=$existing_password
  echo "  parola: Vault'taki mevcut deger yeniden kullanildi (rotasyon yok)"
else
  migrator_password=$(openssl rand -hex 24)
  { printf '%s\n' "$vault_root_token"; printf '%s' "$migrator_password"; } |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv patch "$1" ETHICS_MIGRATOR_PASSWORD=- >/dev/null
    ' sh "$VAULT_PATH"
  { printf '%s\n' "$vault_root_token"; printf '%s' "$MIGRATOR_ROLE"; } |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv patch "$1" ETHICS_MIGRATOR_USERNAME=- >/dev/null
    ' sh "$VAULT_PATH"
  echo "  parola: uretildi ve Vault'a yazildi (ham deger yazdirilmadi)"
fi

# psql's \password hashes client-side, so no cleartext reaches the server statement log.
printf '%s\n' "$migrator_password" | docker exec -i "$PG_CONTAINER" sh -c '
  set -eu
  IFS= read -r MIGRATOR_PASSWORD
  { printf "\\password '"$MIGRATOR_ROLE"'\n"; printf "%s\n%s\n" "$MIGRATOR_PASSWORD" "$MIGRATOR_PASSWORD"; } \
    | psql -X -U postgres -v ON_ERROR_STOP=1 >/dev/null
  unset MIGRATOR_PASSWORD
'
unset migrator_password existing_password

# 2b. Connect-level rights, granted here rather than with the ownership transfer.
#     Flyway starts using this role the moment the secret syncs — which happens before
#     the transfer, by design — and a role that cannot CONNECT fails the pod at boot.
#     Measured the hard way: the first run of this script left the role unable to reach
#     the database at all ("User does not have CONNECT privilege"), which would have
#     surfaced as an outage rather than as a message.
docker exec -i "$PG_CONTAINER" psql -U postgres -d "$DB_NAME" -v ON_ERROR_STOP=1 >/dev/null <<SQL
GRANT CONNECT, TEMPORARY ON DATABASE $DB_NAME TO $MIGRATOR_ROLE;
GRANT USAGE ON SCHEMA $DB_SCHEMA TO $MIGRATOR_ROLE;
-- Flyway reads and appends its own history on every boot, ownership or not.
GRANT SELECT, INSERT, UPDATE, DELETE ON $DB_SCHEMA.ethics_flyway_history TO $MIGRATOR_ROLE;
SQL
echo "  baglanti yetkileri verildi (CONNECT + USAGE + flyway gecmisi)"

# 3. Ownership transfer is refused until the deployment can actually run Flyway as the
#    new role. Moving ownership first would leave the next pending migration unable to
#    alter the ledger, and the failure would surface as a service that will not boot —
#    long after this script exited reporting success.
if [ "${flyway_wired:-0}" -lt 1 ]; then
  printf '\n'
  echo "  SAHIPLIK DEVRI ATLANDI — SPRING_FLYWAY_USER henuz calisan secret'ta yok."
  note "Rol ve Vault anahtarlari hazir. Siradaki adim: ExternalSecret senkronu +"
  note "pod yeniden baslatma, ardindan bu betigi tekrar --apply ile calistirin."
  printf '\nSonuc: yarim — devir icin on kosul bekliyor.\n\n'
  exit 1
fi

# 4. Grants before ownership: changing the owner does not carry the old owner's implicit
#    rights over as explicit ones, so the runtime role must already hold what it needs or
#    it loses access the moment ownership moves.
docker exec -i "$PG_CONTAINER" psql -U postgres -d "$DB_NAME" -v ON_ERROR_STOP=1 >/dev/null <<SQL
GRANT USAGE ON SCHEMA $DB_SCHEMA TO $RUNTIME_ROLE;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA $DB_SCHEMA TO $RUNTIME_ROLE;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA $DB_SCHEMA TO $RUNTIME_ROLE;

ALTER SCHEMA $DB_SCHEMA OWNER TO $MIGRATOR_ROLE;

DO \$\$
DECLARE r record;
BEGIN
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = '$DB_SCHEMA' LOOP
    EXECUTE format('ALTER TABLE $DB_SCHEMA.%I OWNER TO $MIGRATOR_ROLE', r.tablename);
  END LOOP;
  FOR r IN SELECT c.relname FROM pg_class c
            WHERE c.relkind = 'S' AND c.relnamespace = '$DB_SCHEMA'::regnamespace LOOP
    EXECUTE format('ALTER SEQUENCE $DB_SCHEMA.%I OWNER TO $MIGRATOR_ROLE', r.relname);
  END LOOP;
  -- The trigger functions enforce the invariant; leaving them behind would let the
  -- runtime role rewrite the enforcement instead of the rows.
  FOR r IN SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args
             FROM pg_proc p WHERE p.pronamespace = '$DB_SCHEMA'::regnamespace LOOP
    EXECUTE format('ALTER FUNCTION $DB_SCHEMA.%I(%s) OWNER TO $MIGRATOR_ROLE',
                   r.proname, r.args);
  END LOOP;
END
\$\$;

-- Objects a future migration creates must reach the runtime role too, or the next
-- feature ships a table the application cannot read.
ALTER DEFAULT PRIVILEGES FOR ROLE $MIGRATOR_ROLE IN SCHEMA $DB_SCHEMA
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $RUNTIME_ROLE;
ALTER DEFAULT PRIVILEGES FOR ROLE $MIGRATOR_ROLE IN SCHEMA $DB_SCHEMA
  GRANT USAGE, SELECT ON SEQUENCES TO $RUNTIME_ROLE;

-- The runtime role no longer creates objects anywhere; that is the migrator's job.
REVOKE CREATE ON SCHEMA $DB_SCHEMA FROM $RUNTIME_ROLE;
REVOKE CREATE ON SCHEMA public FROM $RUNTIME_ROLE;
SQL
echo "  sahiplik devredildi + calisma zamani yetkileri korundu"

# Trigger names do not follow one rule across the two tables, so they are read rather
# than derived. A guessed name silently leaves the trigger on ORIGIN.
for table in $APPEND_ONLY_TABLES; do
  trigger_name=$(psql_q "
    select tgname from pg_trigger where tgrelid='$DB_SCHEMA.$table'::regclass
      and not tgisinternal limit 1")
  [ -n "$trigger_name" ] || {
    echo "FATAL: $table uzerinde append-only tetikleyici bulunamadi" >&2
    exit 2
  }
  docker exec -i "$PG_CONTAINER" psql -U postgres -d "$DB_NAME" -v ON_ERROR_STOP=1 >/dev/null <<SQL
REVOKE UPDATE, DELETE, TRUNCATE ON $DB_SCHEMA.$table FROM $RUNTIME_ROLE;
ALTER TABLE $DB_SCHEMA.$table ENABLE ALWAYS TRIGGER $trigger_name;
SQL
  echo "  $table: yikici yetki alindi + $trigger_name ENABLE ALWAYS"
done

# ── Negatif kanıt ────────────────────────────────────────────────────────────────────
# The only honest acceptance is the attack failing. Each attempt runs inside a
# transaction that is rolled back, so an attempt that unexpectedly *succeeds* proves the
# gap without leaving it open.
printf '\n  --- negatif kanit (%s kimligiyle) ---\n' "$RUNTIME_ROLE"
probe() {
  local label=$1 statement=$2 output
  output=$(docker exec -i "$PG_CONTAINER" psql -U "$RUNTIME_ROLE" -d "$DB_NAME" \
    -v ON_ERROR_STOP=1 -t -A 2>&1 <<SQL || true
BEGIN;
$statement
ROLLBACK;
SQL
  )
  if printf '%s' "$output" | grep -qiE 'must be owner|permission denied|append-only|yetki'; then
    ok "$label" "reddedildi"
  else
    gap "$label" "GECTI — engel yok"
    note "$(printf '%s' "$output" | head -1)"
  fi
}
probe "tetikleyiciyi kapatma" "ALTER TABLE $DB_SCHEMA.ethics_worm_audit DISABLE TRIGGER USER;"
probe "TRUNCATE" "TRUNCATE $DB_SCHEMA.ethics_worm_audit;"
probe "DELETE" "DELETE FROM $DB_SCHEMA.ethics_worm_audit;"

printf '\n'
if [ "$gaps" -eq 0 ]; then
  printf 'Sonuc: zemin saglam — ACL ve tetikleyici birbirinden bagimsiz iki engel.\n\n'
  exit 0
fi
printf 'Sonuc: %d acik kaldi.\n\n' "$gaps"
exit 1
