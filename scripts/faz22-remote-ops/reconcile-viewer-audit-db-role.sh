#!/usr/bin/env bash
# Reconcile and verify the test VIEW_ONLY broker's least-privilege audit role.
# The Kubernetes Secret supplies only the role name. PostgreSQL administration
# stays inside the test Postgres container; no password or raw secret is read.

set -euo pipefail

ACTION="${1:-check}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
JQ_BIN="${JQ_BIN:-jq}"

KUBE_CONTEXT="k3d-test"
KUBE_NAMESPACE="platform-test"
BROKER_SECRET="endpoint-admin-remote-bridge-secrets-device-key"
DATABASE="endpoint_admin"
DB_SCHEMA="endpoint_admin_service"
AUDIT_TABLE="endpoint_audit_events"
COMPOSE_PROJECT="test"
COMPOSE_SERVICE="postgres"
APPLY_CONFIRM_LITERAL="RECONCILE_FAZ22_6_VIEWER_AUDIT_DB_ROLE"

die() {
  printf 'VIEWER_AUDIT_DB_ROLE status=blocked reason=%s\n' "$1" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing-command"
}

case "$ACTION" in
  check|apply) ;;
  *) die "unsupported-action" ;;
esac

if [[ "$ACTION" == "apply" ]] \
  && [[ "${VIEWER_AUDIT_DB_ROLE_CONFIRM:-}" != "$APPLY_CONFIRM_LITERAL" ]]; then
  die "apply-confirmation-missing"
fi

need_cmd "$KUBECTL_BIN"
need_cmd "$DOCKER_BIN"
need_cmd "$JQ_BIN"

# Command substitution keeps the ESO-projected username out of stdout. The
# identifier shape is deliberately narrower than PostgreSQL's full grammar so
# it can be bound safely through psql variables and format('%I', ...).
broker_role="$($KUBECTL_BIN --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
  get secret "$BROKER_SECRET" \
  -o 'go-template={{index .data "SPRING_DATASOURCE_USERNAME" | base64decode}}' \
  2>/dev/null)" || die "broker-role-secret-unreadable"

[[ "$broker_role" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]] \
  || die "broker-role-identifier-invalid"

container_ids="$($DOCKER_BIN ps \
  --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
  --filter "label=com.docker.compose.service=${COMPOSE_SERVICE}" \
  --format '{{.ID}}')" || die "postgres-container-discovery-failed"
container_count="$(printf '%s\n' "$container_ids" | sed '/^$/d' | wc -l | tr -d ' ')"
[[ "$container_count" == "1" ]] || die "postgres-container-count-not-one"
postgres_container="$(printf '%s\n' "$container_ids" | sed -n '1p')"

psql_exec() {
  local sql_payload
  sql_payload="$(cat)"
  # These variables intentionally expand in the Postgres container, not on the
  # self-hosted runner.
  # shellcheck disable=SC2016
  {
    # The validated role identifier travels over stdin, not docker argv or the
    # container process environment.
    printf '\\set broker_role %s\n' "$broker_role"
    printf '\\set db_schema %s\n' "$DB_SCHEMA"
    printf '\\set audit_table %s\n' "$AUDIT_TABLE"
    printf '%s\n' "$sql_payload"
  } | "$DOCKER_BIN" exec -i \
      -e "TARGET_DB=$DATABASE" \
      "$postgres_container" sh -eu -c '
        exec psql -X -qAt -v ON_ERROR_STOP=1 \
          -U "$POSTGRES_USER" -d "$TARGET_DB"
      '
}

read_matrix() {
  psql_exec <<'SQL'
WITH role_state AS (
  SELECT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = :'broker_role'
  ) AS role_exists
)
SELECT json_build_object(
  'roleExists', role_exists,
  'roleLogin', COALESCE((
    SELECT rolcanlogin FROM pg_roles WHERE rolname = :'broker_role'
  ), false),
  'roleNonPrivileged', COALESCE((
    SELECT NOT (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls)
    FROM pg_roles WHERE rolname = :'broker_role'
  ), false),
  'roleNoMembership', CASE WHEN role_exists THEN NOT EXISTS (
    SELECT 1
    FROM pg_auth_members membership
    JOIN pg_roles member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = :'broker_role'
  ) ELSE false END,
  'predefinedRoleMembership', CASE WHEN role_exists THEN EXISTS (
    SELECT 1
    FROM pg_roles target_role
    WHERE target_role.rolname LIKE 'pg\_%' ESCAPE '\'
      AND pg_has_role(:'broker_role', target_role.oid, 'MEMBER')
  ) ELSE false END,
  'schemaUsage', CASE WHEN role_exists THEN
    has_schema_privilege(:'broker_role', :'db_schema', 'USAGE')
  ELSE false END,
  'schemaCreate', CASE WHEN role_exists THEN
    has_schema_privilege(:'broker_role', :'db_schema', 'CREATE')
  ELSE false END,
  'auditSelect', CASE WHEN role_exists THEN has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'SELECT'
  ) ELSE false END,
  'auditInsert', CASE WHEN role_exists THEN has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'INSERT'
  ) ELSE false END,
  'auditUpdate', CASE WHEN role_exists THEN has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'UPDATE'
  ) ELSE false END,
  'auditDelete', CASE WHEN role_exists THEN has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'DELETE'
  ) ELSE false END,
  'auditTruncate', CASE WHEN role_exists THEN has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'TRUNCATE'
  ) ELSE false END,
  'auditReferences', CASE WHEN role_exists THEN has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'REFERENCES'
  ) ELSE false END,
  'auditTrigger', CASE WHEN role_exists THEN has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'TRIGGER'
  ) ELSE false END,
  'auditColumnUpdate', CASE WHEN role_exists THEN EXISTS (
    SELECT 1
    FROM pg_attribute attribute
    WHERE attribute.attrelid = format('%I.%I', :'db_schema', :'audit_table')::regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND has_column_privilege(
        :'broker_role',
        format('%I.%I', :'db_schema', :'audit_table'),
        attribute.attname,
        'UPDATE'
      )
  ) ELSE false END,
  'auditColumnReferences', CASE WHEN role_exists THEN EXISTS (
    SELECT 1
    FROM pg_attribute attribute
    WHERE attribute.attrelid = format('%I.%I', :'db_schema', :'audit_table')::regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND has_column_privilege(
        :'broker_role',
        format('%I.%I', :'db_schema', :'audit_table'),
        attribute.attname,
        'REFERENCES'
      )
  ) ELSE false END
)::text
FROM role_state;
SQL
}

matrix_is_least_privilege() {
  $JQ_BIN -e '
    .roleExists == true
    and .roleLogin == true
    and .roleNonPrivileged == true
    and .roleNoMembership == true
    and .predefinedRoleMembership == false
    and .schemaUsage == true
    and .schemaCreate == false
    and .auditSelect == true
    and .auditInsert == true
    and .auditUpdate == false
    and .auditDelete == false
    and .auditTruncate == false
    and .auditReferences == false
    and .auditTrigger == false
    and .auditColumnUpdate == false
    and .auditColumnReferences == false
  ' >/dev/null
}

if [[ "$ACTION" == "apply" ]]; then
  # Grants and the role-level SELECT+INSERT probe are one transaction. The
  # probe row is rolled back to a savepoint before the grants commit, so no
  # synthetic audit event can survive even if later verification fails.
  if ! psql_exec >/dev/null <<'SQL'
SELECT 1 / CASE WHEN COALESCE((
  SELECT rolcanlogin
    AND NOT (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls)
    AND NOT EXISTS (
      SELECT 1 FROM pg_auth_members WHERE member = pg_roles.oid
    )
    AND NOT EXISTS (
      SELECT 1
      FROM pg_roles target_role
      WHERE target_role.rolname LIKE 'pg\_%' ESCAPE '\'
        AND pg_has_role(pg_roles.oid, target_role.oid, 'MEMBER')
    )
  FROM pg_roles
  WHERE rolname = :'broker_role'
), false) THEN 1 ELSE 0 END AS require_safe_role_posture;

BEGIN;
SELECT format('GRANT USAGE ON SCHEMA %I TO %I', :'db_schema', :'broker_role') \gexec
SELECT format(
  'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM %I',
  :'db_schema', :'audit_table', :'broker_role'
) \gexec
SELECT format(
  'GRANT SELECT, INSERT ON TABLE %I.%I TO %I',
  :'db_schema', :'audit_table', :'broker_role'
) \gexec
SELECT format(
  'REVOKE UPDATE (%I) ON TABLE %I.%I FROM %I',
  attribute.attname, :'db_schema', :'audit_table', :'broker_role'
)
FROM pg_attribute attribute
WHERE attribute.attrelid = format('%I.%I', :'db_schema', :'audit_table')::regclass
  AND attribute.attnum > 0
  AND NOT attribute.attisdropped
\gexec
SELECT format(
  'REVOKE REFERENCES (%I) ON TABLE %I.%I FROM %I',
  attribute.attname, :'db_schema', :'audit_table', :'broker_role'
)
FROM pg_attribute attribute
WHERE attribute.attrelid = format('%I.%I', :'db_schema', :'audit_table')::regclass
  AND attribute.attnum > 0
  AND NOT attribute.attisdropped
\gexec

SELECT 1 / CASE WHEN (
  has_schema_privilege(:'broker_role', :'db_schema', 'USAGE')
  AND NOT has_schema_privilege(:'broker_role', :'db_schema', 'CREATE')
  AND has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'SELECT'
  )
  AND has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'INSERT'
  )
  AND NOT has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'UPDATE'
  )
  AND NOT has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'DELETE'
  )
  AND NOT has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'TRUNCATE'
  )
  AND NOT has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'REFERENCES'
  )
  AND NOT has_table_privilege(
    :'broker_role', format('%I.%I', :'db_schema', :'audit_table'), 'TRIGGER'
  )
  AND NOT EXISTS (
    SELECT 1
    FROM pg_attribute attribute
    WHERE attribute.attrelid = format('%I.%I', :'db_schema', :'audit_table')::regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND (
        has_column_privilege(
          :'broker_role', format('%I.%I', :'db_schema', :'audit_table'),
          attribute.attname, 'UPDATE'
        )
        OR has_column_privilege(
          :'broker_role', format('%I.%I', :'db_schema', :'audit_table'),
          attribute.attname, 'REFERENCES'
        )
      )
  )
) THEN 1 ELSE 0 END AS require_least_privilege_grants;

SAVEPOINT viewer_audit_role_probe;
SELECT format('SET LOCAL ROLE %I', :'broker_role') \gexec
SELECT id FROM endpoint_admin_service.endpoint_audit_events LIMIT 1;
INSERT INTO endpoint_admin_service.endpoint_audit_events (
  id,
  tenant_id,
  event_type,
  action,
  metadata,
  occurred_at,
  event_hash,
  event_hash_alg,
  event_hash_version,
  prev_event_hash
) VALUES (
  'f2260000-0000-4000-8000-000000000001'::uuid,
  'f2260000-0000-4000-8000-000000000002'::uuid,
  'VIEWER_AUDIT_DB_ROLE_PROBE',
  'ROLLBACK_ONLY',
  '{"synthetic":true,"persistence":"none"}'::jsonb,
  now(),
  repeat('a', 64),
  'SHA-256',
  1,
  NULL
);
ROLLBACK TO SAVEPOINT viewer_audit_role_probe;
COMMIT;
SQL
  then
    die "apply-transaction-failed"
  fi
fi

matrix_json="$(read_matrix)" || die "privilege-matrix-query-failed"
redacted_matrix="$(printf '%s\n' "$matrix_json" | $JQ_BIN -c '{
  roleExists,
  roleLogin,
  roleNonPrivileged,
  roleNoMembership,
  predefinedRoleMembership,
  schemaUsage,
  schemaCreate,
  auditSelect,
  auditInsert,
  auditUpdate,
  auditDelete,
  auditTruncate,
  auditReferences,
  auditTrigger,
  auditColumnUpdate,
  auditColumnReferences
}')" || die "privilege-matrix-json-invalid"
printf '%s\n' "$redacted_matrix"
printf '%s\n' "$matrix_json" | matrix_is_least_privilege \
  || die "least-privilege-contract-not-satisfied"

printf 'VIEWER_AUDIT_DB_ROLE status=pass action=%s target=test-only\n' "$ACTION"
