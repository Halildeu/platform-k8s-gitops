-- Faz 21.3 D35 follow-up — operator-applied least-privilege role for permission-service.
--
-- This is NOT a Flyway migration. It is operator-driven SQL applied as DB
-- superuser (`postgres`) against `reports_db`. It MUST be applied AFTER
-- V19+V20+V21+V22+V23 (data_access schema is required), and BEFORE the
-- Vault populate step (the password is set separately by the operator
-- runbook — see `docs/d35-dedicated-reports-role-runbook.md`).
--
-- Codex review: thread `019dd2af`. Verdicts:
-- - SECURITY INVOKER on validate_scope_ref() (caller's perms enforce grant
--   surface).
-- - DELETE NOT granted on data_access.scope/scope_outbox: V19 audit model
--   keeps `revoked_at` soft-delete, V22 outbox keeps PROCESSED rows for
--   audit trail. Backend AccessScopeService.revoke() confirmed soft-delete
--   only (UPDATE revoked_at = now()).
-- - All 4 workcube_mikrolink anchor tables granted SELECT (company,
--   pro_projects, branch, department) — matches the 4 scope_kind branches
--   in validate_scope_ref().
-- - Explicit EXECUTE on the three functions to avoid relying on PUBLIC
--   defaults.
-- - Role created NOLOGIN here. Operator separately runs
--   ALTER ROLE permission_reports_writer WITH LOGIN PASSWORD '<generated>'
--   from the runbook (LOGIN flips only after the password is set).
--
-- Idempotent / safe-to-rerun: DO block guards CREATE ROLE; subsequent
-- GRANT statements are inherently idempotent.

BEGIN;

-- ============================================================================
-- 1. Role bootstrap (NOLOGIN; operator flips LOGIN after setting password)
-- ============================================================================

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'permission_reports_writer') THEN
    CREATE ROLE permission_reports_writer
      NOLOGIN
      NOSUPERUSER
      NOCREATEDB
      NOCREATEROLE
      NOREPLICATION
      NOBYPASSRLS;

    COMMENT ON ROLE permission_reports_writer IS
      'Faz 21.3 dedicated reports_db role for permission-service runtime. '
      'Least-privilege: SELECT on data_access read tables + workcube_mikrolink '
      'anchor tables, SELECT/INSERT/UPDATE (no DELETE — V19 soft-delete + V22 '
      'audit outbox) on data_access.scope and scope_outbox, USAGE on sequences, '
      'EXECUTE on validate_scope_ref + scope_validate_trg + recover_stuck_outbox_rows. '
      'NOLOGIN by default — operator sets password and flips LOGIN.';
  END IF;
END$$;

-- ============================================================================
-- 2. Database connect
-- ============================================================================

GRANT CONNECT ON DATABASE reports_db TO permission_reports_writer;

-- ============================================================================
-- 3. data_access schema grants
-- ============================================================================

GRANT USAGE ON SCHEMA data_access TO permission_reports_writer;

-- Read-only on org-mapping tables (validate_scope_ref join, AccessScopeService
-- list/get, future scope-listing UI).
GRANT SELECT ON data_access.organization
              , data_access.organization_company
  TO permission_reports_writer;

-- Write surface — explicitly NOT granting DELETE (Codex 019dd2af verdict).
-- Backend uses revoked_at = now() UPDATE for soft-delete (verified at
-- AccessScopeService.revoke() in platform-backend PR-G follow-up).
GRANT SELECT, INSERT, UPDATE ON data_access.scope
                              , data_access.scope_outbox
  TO permission_reports_writer;

-- Sequence usage for INSERTs into scope/scope_outbox.
GRANT USAGE ON SEQUENCE data_access.scope_id_seq
                      , data_access.scope_outbox_id_seq
  TO permission_reports_writer;

-- Explicit revoke creation rights — defense against future migrations
-- accidentally granting CREATE.
REVOKE CREATE ON SCHEMA data_access FROM permission_reports_writer;

-- ============================================================================
-- 4. workcube_mikrolink anchor table grants (validate_scope_ref existence
--    check requires SELECT on the 4 scope_kind anchor tables)
-- ============================================================================

GRANT USAGE ON SCHEMA workcube_mikrolink TO permission_reports_writer;

-- 4 anchor tables matching the 4 branches in validate_scope_ref():
--   company → COMPANY → workcube_mikrolink.company
--   project → PRO_PROJECTS → workcube_mikrolink.pro_projects
--   branch  → BRANCH → workcube_mikrolink.branch
--   depot   → DEPARTMENT → workcube_mikrolink.department
GRANT SELECT ON workcube_mikrolink.company
              , workcube_mikrolink.pro_projects
              , workcube_mikrolink.branch
              , workcube_mikrolink.department
  TO permission_reports_writer;

-- ============================================================================
-- 5. Function EXECUTE grants (avoid relying on PUBLIC defaults — Codex
--    019dd2af recommendation)
-- ============================================================================

-- validate_scope_ref(text, text, text) — INSERT trigger guard
GRANT EXECUTE ON FUNCTION data_access.validate_scope_ref(TEXT, TEXT, TEXT)
  TO permission_reports_writer;

-- scope_validate_trg() — trigger function (called by trigger as caller, but
-- explicit EXECUTE for clarity)
GRANT EXECUTE ON FUNCTION data_access.scope_validate_trg()
  TO permission_reports_writer;

-- recover_stuck_outbox_rows() — V22 ops cleanup (called by poller's
-- recoverStuckRows path; metrics confirmed alive in 2026-04-28 preflight)
GRANT EXECUTE ON FUNCTION data_access.recover_stuck_outbox_rows(INTERVAL)
  TO permission_reports_writer;

-- ============================================================================
-- 6. Default privileges for future tables/sequences in data_access
--    (defensive; operator can extend if data_access ever gains new tables
--    without re-applying this script)
-- ============================================================================

-- Note: ALTER DEFAULT PRIVILEGES applies to objects created by the role
-- that runs ALTER. Run this script as the same role that creates future
-- data_access objects (typically `platform`).

ALTER DEFAULT PRIVILEGES IN SCHEMA data_access
  GRANT SELECT ON TABLES TO permission_reports_writer;

-- (NOT extending INSERT/UPDATE defaults — new tables should be evaluated
-- on a per-case basis and explicitly granted.)

COMMIT;

-- ============================================================================
-- Operator next steps (do NOT include in this transaction):
--
--   1. Generate password (32+ chars):
--        openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | cut -c1-44
--
--   2. ALTER role to LOGIN with the generated password:
--        ALTER ROLE permission_reports_writer
--        WITH LOGIN PASSWORD '<generated>';
--
--   3. DB smoke test (BEFORE Vault populate):
--        SELECT current_user, has_table_privilege('permission_reports_writer',
--          'data_access.scope', 'INSERT') AS can_insert_scope;
--        SELECT has_table_privilege('permission_reports_writer',
--          'data_access.scope', 'DELETE') AS can_delete_scope_must_be_false;
--        SELECT has_function_privilege('permission_reports_writer',
--          'data_access.validate_scope_ref(text, text, text)', 'EXECUTE')
--          AS can_execute_validate;
--
--   4. Vault populate (operator runbook docs/d35-dedicated-reports-role-runbook.md).
-- ============================================================================
