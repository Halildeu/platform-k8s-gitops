-- Faz 21.1 — depot scope_kind → DEPARTMENT contract widening (Codex 019dc8b4
-- iter-1/2/3 + Faz 21.A decision doc).
--
-- V19 set scope_kind='depot' to 'TBD_DEPOT_TABLE' as a fail-closed
-- placeholder. With Faz 21.A merged (PR #164, decision: depot source =
-- DEPARTMENT), this V20 migration:
--   1. Drops the old check.
--   2. Re-adds the check with depot → DEPARTMENT.
--   3. Replaces validate_scope_ref() with a depot/DEPARTMENT branch.
--
-- Idempotent / safe-to-rerun: ALTER DROP CONSTRAINT IF EXISTS + re-ADD
-- + CREATE OR REPLACE FUNCTION. Net effect on a cluster that already
-- received V20 is the same final shape (not a strict no-op, but
-- semantically a fixed point).

BEGIN;

-- ============================================================================
-- 1. scope_kind ↔ source_table CHECK rebuild
-- ============================================================================

ALTER TABLE data_access.scope
    DROP CONSTRAINT IF EXISTS scope_kind_source_table_consistent;

ALTER TABLE data_access.scope
    ADD CONSTRAINT scope_kind_source_table_consistent CHECK (
        (scope_kind = 'company' AND scope_source_table = 'COMPANY')      OR
        (scope_kind = 'project' AND scope_source_table = 'PRO_PROJECTS') OR
        (scope_kind = 'branch'  AND scope_source_table = 'BRANCH')       OR
        (scope_kind = 'depot'   AND scope_source_table = 'DEPARTMENT')
    );

-- ============================================================================
-- 2. validate_scope_ref() — depot/DEPARTMENT branch
-- ============================================================================

CREATE OR REPLACE FUNCTION data_access.validate_scope_ref(
    p_kind TEXT,
    p_source_table TEXT,
    p_ref TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_count BIGINT;
BEGIN
    IF p_kind = 'company' AND p_source_table = 'COMPANY' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.company
        WHERE source_pk = p_ref AND source_schema = 'workcube_mikrolink';
    ELSIF p_kind = 'project' AND p_source_table = 'PRO_PROJECTS' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.pro_projects
        WHERE source_pk = p_ref AND source_schema = 'workcube_mikrolink';
    ELSIF p_kind = 'branch' AND p_source_table = 'BRANCH' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.branch
        WHERE source_pk = p_ref AND source_schema = 'workcube_mikrolink';
    ELSIF p_kind = 'depot' AND p_source_table = 'DEPARTMENT' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.department
        WHERE source_pk = p_ref AND source_schema = 'workcube_mikrolink';
    ELSE
        RETURN FALSE;
    END IF;
    RETURN v_count > 0;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION data_access.validate_scope_ref(TEXT,TEXT,TEXT) IS
    'Faz 21.1: depot branch widened to DEPARTMENT (Faz 21.A karar). '
    'V19 placeholder TBD_DEPOT_TABLE artık aktif değil.';

COMMIT;
