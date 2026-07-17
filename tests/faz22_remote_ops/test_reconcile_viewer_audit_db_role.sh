#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/faz22-remote-ops/reconcile-viewer-audit-db-role.sh"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/viewer-audit-role-test.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

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
    printf '%b' "${MOCK_CONTAINER_IDS-fake-postgres-container\\n}"
    ;;
  exec)
    sql="$(cat)"
    printf '%s\n' "$sql" >>"${MOCK_SQL_CAPTURE:?}"
    if [[ "$sql" == *"json_build_object"* ]]; then
      printf '%s\n' "${MOCK_MATRIX:?}"
    fi
    ;;
  *)
    exit 90
    ;;
esac
MOCK

chmod +x "$MOCK_BIN/kubectl" "$MOCK_BIN/docker"

valid_matrix='{"roleExists":true,"roleLogin":true,"roleNonPrivileged":true,"roleNoMembership":true,"predefinedRoleMembership":false,"schemaUsage":true,"schemaCreate":false,"auditSelect":true,"auditInsert":true,"auditUpdate":false,"auditDelete":false,"auditTruncate":false,"auditReferences":false,"auditTrigger":false,"auditColumnUpdate":false,"auditColumnReferences":false}'
invalid_matrix='{"roleExists":true,"roleLogin":true,"roleNonPrivileged":true,"roleNoMembership":true,"predefinedRoleMembership":false,"schemaUsage":true,"schemaCreate":false,"auditSelect":true,"auditInsert":false,"auditUpdate":false,"auditDelete":false,"auditTruncate":false,"auditReferences":false,"auditTrigger":false,"auditColumnUpdate":false,"auditColumnReferences":false}'

run_script() {
  PATH="$MOCK_BIN:$PATH" \
    MOCK_SQL_CAPTURE="$TMP_ROOT/sql.log" \
    MOCK_MATRIX="$MOCK_MATRIX" \
    MOCK_ROLE="${MOCK_ROLE:-viewer_broker_role}" \
    bash "$SCRIPT" "$@"
}

: >"$TMP_ROOT/sql.log"
MOCK_MATRIX="$valid_matrix" run_script check >"$TMP_ROOT/check.out"
grep -Fq '"auditSelect":true' "$TMP_ROOT/check.out"
grep -Fq '"auditInsert":true' "$TMP_ROOT/check.out"
grep -Fq '"schemaCreate":false' "$TMP_ROOT/check.out"
grep -Fq '"roleNoMembership":true' "$TMP_ROOT/check.out"
grep -Fq 'VIEWER_AUDIT_DB_ROLE status=pass action=check target=test-only' "$TMP_ROOT/check.out"
if grep -Fq 'viewer_broker_role' "$TMP_ROOT/check.out"; then
  echo "role name leaked to output" >&2
  exit 1
fi

: >"$TMP_ROOT/sql.log"
if MOCK_MATRIX="$invalid_matrix" run_script check >"$TMP_ROOT/invalid.out" 2>&1; then
  echo "missing INSERT privilege must fail closed" >&2
  exit 1
fi
grep -Fq 'reason=least-privilege-contract-not-satisfied' "$TMP_ROOT/invalid.out"

: >"$TMP_ROOT/sql.log"
if MOCK_MATRIX="$valid_matrix" run_script apply >"$TMP_ROOT/no-confirm.out" 2>&1; then
  echo "apply without confirmation must fail" >&2
  exit 1
fi
grep -Fq 'reason=apply-confirmation-missing' "$TMP_ROOT/no-confirm.out"
[[ ! -s "$TMP_ROOT/sql.log" ]]

: >"$TMP_ROOT/sql.log"
VIEWER_AUDIT_DB_ROLE_CONFIRM=RECONCILE_FAZ22_6_VIEWER_AUDIT_DB_ROLE \
  MOCK_MATRIX="$valid_matrix" run_script apply >"$TMP_ROOT/apply.out"
grep -Fq "REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM %I" "$TMP_ROOT/sql.log"
grep -Fq "GRANT SELECT, INSERT ON TABLE %I.%I TO %I" "$TMP_ROOT/sql.log"
grep -Fq 'SAVEPOINT viewer_audit_role_probe' "$TMP_ROOT/sql.log"
grep -Fq 'ROLLBACK TO SAVEPOINT viewer_audit_role_probe' "$TMP_ROOT/sql.log"
grep -Fq 'BEGIN;' "$TMP_ROOT/sql.log"
grep -Fq 'COMMIT;' "$TMP_ROOT/sql.log"
grep -Fq "SET LOCAL ROLE %I" "$TMP_ROOT/sql.log"
grep -Fq 'require_safe_role_posture' "$TMP_ROOT/sql.log"
grep -Fq 'require_least_privilege_grants' "$TMP_ROOT/sql.log"
grep -Fq 'REVOKE UPDATE (%I)' "$TMP_ROOT/sql.log"
grep -Fq 'REVOKE REFERENCES (%I)' "$TMP_ROOT/sql.log"
grep -Fq "'UPDATE'" "$TMP_ROOT/sql.log"
grep -Fq "'DELETE'" "$TMP_ROOT/sql.log"
grep -Fq "'TRUNCATE'" "$TMP_ROOT/sql.log"
grep -Fq "'REFERENCES'" "$TMP_ROOT/sql.log"
grep -Fq "'TRIGGER'" "$TMP_ROOT/sql.log"
grep -Fq 'VIEWER_AUDIT_DB_ROLE status=pass action=apply target=test-only' "$TMP_ROOT/apply.out"

for jq_filter in \
  '.schemaCreate = true' \
  '.auditUpdate = true' \
  '.auditDelete = true' \
  '.auditTruncate = true' \
  '.auditReferences = true' \
  '.auditTrigger = true' \
  '.auditColumnUpdate = true' \
  '.auditColumnReferences = true' \
  '.roleNoMembership = false' \
  '.predefinedRoleMembership = true'; do
  matrix="$(printf '%s\n' "$valid_matrix" | jq -c "$jq_filter")"
  if MOCK_MATRIX="$matrix" run_script check >"$TMP_ROOT/matrix-negative.out" 2>&1; then
    echo "matrix negative must fail: $jq_filter" >&2
    exit 1
  fi
  grep -Fq 'reason=least-privilege-contract-not-satisfied' "$TMP_ROOT/matrix-negative.out"
done

if MOCK_CONTAINER_IDS='' MOCK_MATRIX="$valid_matrix" run_script check \
  >"$TMP_ROOT/no-container.out" 2>&1; then
  echo "zero postgres containers must fail" >&2
  exit 1
fi
grep -Fq 'reason=postgres-container-count-not-one' "$TMP_ROOT/no-container.out"

if MOCK_CONTAINER_IDS='one\ntwo\n' MOCK_MATRIX="$valid_matrix" run_script check \
  >"$TMP_ROOT/two-containers.out" 2>&1; then
  echo "multiple postgres containers must fail" >&2
  exit 1
fi
grep -Fq 'reason=postgres-container-count-not-one' "$TMP_ROOT/two-containers.out"

: >"$TMP_ROOT/sql.log"
if MOCK_ROLE='invalid role' MOCK_MATRIX="$valid_matrix" run_script check \
  >"$TMP_ROOT/invalid-role.out" 2>&1; then
  echo "invalid role identifier must fail" >&2
  exit 1
fi
grep -Fq 'reason=broker-role-identifier-invalid' "$TMP_ROOT/invalid-role.out"
if grep -Fq 'invalid role' "$TMP_ROOT/invalid-role.out"; then
  echo "invalid role value leaked to output" >&2
  exit 1
fi

echo "PASS viewer audit DB role reconciler regression"
