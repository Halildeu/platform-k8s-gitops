#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/reconcile-viewer-audit-db-role.sh"
REAL_DOCKER="$(command -v docker)"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:16-alpine}"
CONTAINER_NAME="viewer-audit-role-pg-$RANDOM-$$"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/viewer-audit-role-pg.XXXXXX")"

cleanup() {
  "$REAL_DOCKER" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

container_id="$($REAL_DOCKER run --rm -d \
  --name "$CONTAINER_NAME" \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  -e POSTGRES_USER=postgres \
  "$POSTGRES_IMAGE")"

init_complete=0
ready=0
for _ in $(seq 1 60); do
  if [[ "$init_complete" == "0" ]]; then
    postgres_logs="$("$REAL_DOCKER" logs "$container_id" 2>&1 || true)"
    if [[ "$postgres_logs" == *'PostgreSQL init process complete; ready for start up.'* ]]; then
      init_complete=1
    fi
  fi
  if [[ "$init_complete" == "1" ]]; then
    sql_ready="$(
      "$REAL_DOCKER" exec "$container_id" psql -X -qAt \
        -U postgres -d postgres -c 'SELECT 1' 2>/dev/null || true
    )"
    if [[ "$sql_ready" == "1" ]]; then
      ready=1
      break
    fi
  fi
  sleep 1
done
[[ "$ready" == "1" ]] || {
  echo "ephemeral postgres final server did not become SQL-ready" >&2
  exit 1
}

"$REAL_DOCKER" exec -i "$container_id" psql -X -v ON_ERROR_STOP=1 \
  -U postgres -d postgres >/dev/null <<'SQL'
CREATE DATABASE endpoint_admin;
SQL

"$REAL_DOCKER" exec -i "$container_id" psql -X -v ON_ERROR_STOP=1 \
  -U postgres -d endpoint_admin >/dev/null <<'SQL'
CREATE SCHEMA endpoint_admin_service;
REVOKE ALL ON SCHEMA endpoint_admin_service FROM PUBLIC;
CREATE TABLE endpoint_admin_service.endpoint_audit_events (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  device_id UUID,
  command_id UUID,
  event_type VARCHAR(100) NOT NULL,
  action VARCHAR(100) NOT NULL,
  performed_by_subject VARCHAR(255),
  correlation_id VARCHAR(128),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  before_state JSONB,
  after_state JSONB,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  prev_event_hash VARCHAR(64),
  event_hash VARCHAR(64),
  event_hash_alg VARCHAR(32),
  event_hash_version INTEGER
);
CREATE OR REPLACE FUNCTION endpoint_admin_service.require_audit_hash()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.event_hash IS NULL
    OR NEW.event_hash_alg IS NULL
    OR NEW.event_hash_version IS NULL THEN
    RAISE EXCEPTION 'audit hash required';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_require_audit_hash
BEFORE INSERT ON endpoint_admin_service.endpoint_audit_events
FOR EACH ROW EXECUTE FUNCTION endpoint_admin_service.require_audit_hash();
CREATE ROLE viewer_broker_role LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOREPLICATION NOBYPASSRLS;
SQL

MOCK_BIN="$TMP_ROOT/bin"
mkdir -p "$MOCK_BIN"

cat >"$MOCK_BIN/kubectl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s' "${MOCK_ROLE:-viewer_broker_role}"
MOCK

cat >"$MOCK_BIN/docker" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  ps)
    printf '%s\n' "${INTEGRATION_CONTAINER:?}"
    ;;
  exec)
    exec "${REAL_DOCKER:?}" "$@"
    ;;
  *)
    exit 90
    ;;
esac
MOCK

chmod +x "$MOCK_BIN/kubectl" "$MOCK_BIN/docker"

run_reconciler() {
  PATH="$MOCK_BIN:$PATH" \
    REAL_DOCKER="$REAL_DOCKER" \
    INTEGRATION_CONTAINER="$container_id" \
    MOCK_ROLE="${MOCK_ROLE:-viewer_broker_role}" \
    bash "$SCRIPT" "$@"
}

VIEWER_AUDIT_DB_ROLE_CONFIRM=RECONCILE_FAZ22_6_VIEWER_AUDIT_DB_ROLE \
  run_reconciler apply >"$TMP_ROOT/apply.out"
grep -Fq 'VIEWER_AUDIT_DB_ROLE status=pass action=apply target=test-only' \
  "$TMP_ROOT/apply.out"

probe_rows="$($REAL_DOCKER exec -i "$container_id" psql -X -qAt \
  -U postgres -d endpoint_admin -c \
  "SELECT count(*) FROM endpoint_admin_service.endpoint_audit_events WHERE id='f2260000-0000-4000-8000-000000000001'::uuid")"
[[ "$probe_rows" == "0" ]] || {
  echo "rollback-only probe row persisted" >&2
  exit 1
}

run_reconciler check >"$TMP_ROOT/check.out"
grep -Fq '"auditSelect":true' "$TMP_ROOT/check.out"
grep -Fq '"auditInsert":true' "$TMP_ROOT/check.out"
grep -Fq '"auditColumnUpdate":false' "$TMP_ROOT/check.out"

if MOCK_ROLE=missing_broker_role run_reconciler check \
  >"$TMP_ROOT/missing-role.out" 2>&1; then
  echo "missing role must fail closed" >&2
  exit 1
fi
grep -Fq '"roleExists":false' "$TMP_ROOT/missing-role.out"
grep -Fq 'reason=least-privilege-contract-not-satisfied' "$TMP_ROOT/missing-role.out"
if grep -Fq 'reason=privilege-matrix-query-failed' "$TMP_ROOT/missing-role.out"; then
  echo "missing role must return a truthful matrix" >&2
  exit 1
fi

"$REAL_DOCKER" exec -i "$container_id" psql -X -v ON_ERROR_STOP=1 \
  -U postgres -d endpoint_admin >/dev/null <<'SQL'
GRANT UPDATE (metadata) ON endpoint_admin_service.endpoint_audit_events
  TO viewer_broker_role;
GRANT REFERENCES (id) ON endpoint_admin_service.endpoint_audit_events
  TO viewer_broker_role;
SQL
if run_reconciler check >"$TMP_ROOT/column-grant.out" 2>&1; then
  echo "column mutation grants must fail closed" >&2
  exit 1
fi
grep -Fq '"auditColumnUpdate":true' "$TMP_ROOT/column-grant.out"
grep -Fq '"auditColumnReferences":true' "$TMP_ROOT/column-grant.out"

VIEWER_AUDIT_DB_ROLE_CONFIRM=RECONCILE_FAZ22_6_VIEWER_AUDIT_DB_ROLE \
  run_reconciler apply >"$TMP_ROOT/column-reconcile.out"
grep -Fq '"auditColumnUpdate":false' "$TMP_ROOT/column-reconcile.out"
grep -Fq '"auditColumnReferences":false' "$TMP_ROOT/column-reconcile.out"

"$REAL_DOCKER" exec -i "$container_id" psql -X -v ON_ERROR_STOP=1 \
  -U postgres -d endpoint_admin >/dev/null <<'SQL'
GRANT pg_read_all_data TO viewer_broker_role;
SQL
if run_reconciler check >"$TMP_ROOT/membership-check.out" 2>&1; then
  echo "predefined role membership must fail closed" >&2
  exit 1
fi
grep -Fq '"roleNoMembership":false' "$TMP_ROOT/membership-check.out"
grep -Fq '"predefinedRoleMembership":true' "$TMP_ROOT/membership-check.out"
if VIEWER_AUDIT_DB_ROLE_CONFIRM=RECONCILE_FAZ22_6_VIEWER_AUDIT_DB_ROLE \
  run_reconciler apply >"$TMP_ROOT/membership-apply.out" 2>&1; then
  echo "apply must not hide or remove inherited role membership" >&2
  exit 1
fi
grep -Fq 'reason=apply-transaction-failed' "$TMP_ROOT/membership-apply.out"

"$REAL_DOCKER" exec -i "$container_id" psql -X -v ON_ERROR_STOP=1 \
  -U postgres -d endpoint_admin >/dev/null <<'SQL'
REVOKE pg_read_all_data FROM viewer_broker_role;
SQL
VIEWER_AUDIT_DB_ROLE_CONFIRM=RECONCILE_FAZ22_6_VIEWER_AUDIT_DB_ROLE \
  run_reconciler apply >"$TMP_ROOT/final-apply.out"
run_reconciler check >"$TMP_ROOT/final-check.out"
grep -Fq 'VIEWER_AUDIT_DB_ROLE status=pass action=check target=test-only' \
  "$TMP_ROOT/final-check.out"

echo "PASS viewer audit DB role PostgreSQL integration"
