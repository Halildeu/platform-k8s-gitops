-- Faz 21.3 — V25 tenant anchor fix (COMPANY → OUR_COMPANY).
--
-- Codex thread `019dd34e` PARTIAL/AGREE-with-revisions:
-- discovery `docs/faz-21-3-evidence/2026-04-28-our-company-anchor-discovery.md`
-- + Codex hybrid contract:
--   * company → OUR_COMPANY (direct anchor, PK COMP_ID lineage source_pk)
--   * depot → DEPARTMENT (DEPARTMENT.OUR_COMPANY_ID FK, 1-hop tenant)
--   * branch → BRANCH (via COMPANY.OUR_COMPANY_ID, 2-hop tenant)
--   * project → PRO_PROJECTS (via COMPANY.OUR_COMPANY_ID, 2-hop tenant)
--
-- This migration:
--   1. Updates `scope_kind_source_table_consistent` CHECK constraint
--      (`company` ↔ `OUR_COMPANY`, was `COMPANY`).
--   2. Updates `data_access.organization_company` source_table
--      default + CHECK (`OUR_COMPANY`, was `COMPANY`). Comment added.
--   3. Recreates `validate_scope_ref()` with widened signature
--      (`p_org_id BIGINT` added) and tenant-aware predicates per scope_kind.
--   4. Recreates `scope_validate_trg()` to pass `NEW.org_id` to the
--      validator.
--   5. Truncates `data_access.organization_company` (currently 0 rows;
--      safe). The reseed CROSS JOIN for AÇIK org runs in Faz 16.2.A
--      runbook AFTER ETL load — moved out of this migration so it
--      doesn't depend on workcube_mikrolink.our_company being
--      pre-populated.
--
-- Live state when this migration designed (2026-04-28):
--   data_access.scope = 0 rows
--   data_access.organization_company = 0 rows
--   workcube_mikrolink.our_company in reports_db = 0 rows (ETL not loaded)
-- → No data corruption, no rows to migrate. Fix-forward clean.
--
-- Idempotent: CHECK DROP+ADD with IF EXISTS, function CREATE OR REPLACE,
-- TRUNCATE on a 0-row table is a no-op.

BEGIN;

-- ============================================================================
-- 1. scope_kind_source_table_consistent CHECK rebuild
--    (company source_table COMPANY → OUR_COMPANY)
-- ============================================================================

ALTER TABLE data_access.scope
    DROP CONSTRAINT IF EXISTS scope_kind_source_table_consistent;

ALTER TABLE data_access.scope
    ADD CONSTRAINT scope_kind_source_table_consistent CHECK (
        (scope_kind = 'company' AND scope_source_table = 'OUR_COMPANY')   OR
        (scope_kind = 'project' AND scope_source_table = 'PRO_PROJECTS')  OR
        (scope_kind = 'branch'  AND scope_source_table = 'BRANCH')        OR
        (scope_kind = 'depot'   AND scope_source_table = 'DEPARTMENT')
    );

-- ============================================================================
-- 2. organization_company default + CHECK update
-- ============================================================================

-- Default value flip
ALTER TABLE data_access.organization_company
    ALTER COLUMN source_table SET DEFAULT 'OUR_COMPANY';

-- CHECK rebuild (was = 'COMPANY')
ALTER TABLE data_access.organization_company
    DROP CONSTRAINT IF EXISTS organization_company_source_table_check;

ALTER TABLE data_access.organization_company
    ADD CONSTRAINT organization_company_source_table_check
    CHECK (source_table = 'OUR_COMPANY');

COMMENT ON TABLE data_access.organization_company IS
    'Faz 21.3 V25: org_id ↔ OUR_COMPANY (Workcube tenant-scoped) mapping. '
    'Column name workcube_company_source_pk kept for column-rename avoidance; '
    'value semantic = workcube_mikrolink.OUR_COMPANY.COMP_ID lineage source_pk. '
    'V19 originally referenced workcube_mikrolink.COMPANY (80,246-row directory) '
    'which was an anchor mistake — corrected here. See discovery: '
    'docs/faz-21-3-evidence/2026-04-28-our-company-anchor-discovery.md.';

COMMENT ON COLUMN data_access.organization_company.workcube_company_source_pk IS
    'Faz 21.3 V25: Workcube OUR_COMPANY.COMP_ID lineage source_pk (TEXT '
    'representation, populated by ETL V17 lineage columns). Column name '
    '"workcube_company_source_pk" preserved for migration friendliness; '
    'semantic is OUR_COMPANY tenant boundary.';

-- ============================================================================
-- 3. validate_scope_ref() — widened signature + tenant-aware predicates
-- ============================================================================
-- Drop the V19/V20/V21 3-arg version explicitly so the trigger can rebind.
-- (CASCADE handles trigger function dependency; trigger itself is rebuilt
-- in step 4.)

DROP FUNCTION IF EXISTS data_access.validate_scope_ref(TEXT, TEXT, TEXT) CASCADE;

CREATE OR REPLACE FUNCTION data_access.validate_scope_ref(
    p_kind TEXT,
    p_source_table TEXT,
    p_ref TEXT,
    p_org_id BIGINT
) RETURNS BOOLEAN AS $$
DECLARE
    v_count BIGINT;
    v_pk TEXT;
BEGIN
    -- ADR-0008 canonical scope_ref = JSON array string (örn. `'["1"]'`).
    -- V21 introduced jsonb->>0 first-element extraction (encoder fail-closed
    -- semantic preserved). V25 keeps that behavior; only table refs +
    -- tenant predicates change.
    BEGIN
        v_pk := p_ref::jsonb->>0;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN FALSE;
    END;

    IF v_pk IS NULL THEN
        RETURN FALSE;
    END IF;

    -- All four branches now require both:
    --   (a) lineage source_pk row EXISTS in correct anchor table
    --   (b) tenant-membership predicate matches p_org_id
    --
    -- Tenant predicate uses data_access.organization_company as the
    -- single source of truth for "which OUR_COMPANY rows belong to which
    -- org_id" (this is the AÇIK ↔ {Mikrolink, Pasif Boreas, Serban, ...}
    -- mapping). For company scope, the predicate is direct (the anchor
    -- IS OUR_COMPANY). For depot/branch/project, the predicate joins
    -- through OUR_COMPANY to reach the relevant FK column.

    IF p_kind = 'company' AND p_source_table = 'OUR_COMPANY' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.our_company oc
        JOIN data_access.organization_company oc_map
          ON oc_map.workcube_company_source_pk = oc.source_pk
        WHERE oc.source_pk = v_pk
          AND oc.source_schema = 'workcube_mikrolink'
          AND oc_map.org_id = p_org_id;

    ELSIF p_kind = 'project' AND p_source_table = 'PRO_PROJECTS' THEN
        -- PRO_PROJECTS.COMPANY_ID → COMPANY → COMPANY.OUR_COMPANY_ID
        --   → OUR_COMPANY.COMP_ID (lineage source_pk)
        --   → organization_company mapping → org_id check
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.pro_projects p
        JOIN workcube_mikrolink.company c
          ON c.company_id = p.company_id
        JOIN workcube_mikrolink.our_company oc
          ON oc.comp_id = c.our_company_id
        JOIN data_access.organization_company oc_map
          ON oc_map.workcube_company_source_pk = oc.comp_id::text
        WHERE p.source_pk = v_pk
          AND p.source_schema = 'workcube_mikrolink'
          AND oc_map.org_id = p_org_id;

    ELSIF p_kind = 'branch' AND p_source_table = 'BRANCH' THEN
        -- BRANCH.COMPANY_ID → COMPANY.OUR_COMPANY_ID → OUR_COMPANY.COMP_ID
        --   → organization_company mapping → org_id check
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.branch b
        JOIN workcube_mikrolink.company c
          ON c.company_id = b.company_id
        JOIN workcube_mikrolink.our_company oc
          ON oc.comp_id = c.our_company_id
        JOIN data_access.organization_company oc_map
          ON oc_map.workcube_company_source_pk = oc.comp_id::text
        WHERE b.source_pk = v_pk
          AND b.source_schema = 'workcube_mikrolink'
          AND oc_map.org_id = p_org_id;

    ELSIF p_kind = 'depot' AND p_source_table = 'DEPARTMENT' THEN
        -- DEPARTMENT.OUR_COMPANY_ID → OUR_COMPANY.COMP_ID (lineage source_pk)
        --   → organization_company mapping → org_id check
        --
        -- Note: DEPARTMENT.OUR_COMPANY_ID is nullable per snapshot; rows
        -- with NULL OUR_COMPANY_ID cannot be tenant-scoped → reject.
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.department d
        JOIN workcube_mikrolink.our_company oc
          ON oc.comp_id = d.our_company_id
        JOIN data_access.organization_company oc_map
          ON oc_map.workcube_company_source_pk = oc.comp_id::text
        WHERE d.source_pk = v_pk
          AND d.source_schema = 'workcube_mikrolink'
          AND d.our_company_id IS NOT NULL
          AND oc_map.org_id = p_org_id;
    ELSE
        RETURN FALSE;
    END IF;

    RETURN v_count > 0;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION data_access.validate_scope_ref(TEXT, TEXT, TEXT, BIGINT) IS
    'Faz 21.3 V25: tenant-aware scope_ref validation. Codex 019dd34e hybrid '
    'contract — anchor + tenant predicate per scope_kind (company direct via '
    'OUR_COMPANY, depot 1-hop via DEPARTMENT.OUR_COMPANY_ID, branch+project '
    '2-hop via COMPANY.OUR_COMPANY_ID). Replaces V19/V20/V21 3-arg version '
    'which used COMPANY directory (80,246 row) as anchor — tenant boundary '
    'effectively absent. Signature widened to include p_org_id; trigger '
    'function passes NEW.org_id. See discovery: '
    'docs/faz-21-3-evidence/2026-04-28-our-company-anchor-discovery.md.';

-- ============================================================================
-- 4. scope_validate_trg() — pass org_id to validator
-- ============================================================================

CREATE OR REPLACE FUNCTION data_access.scope_validate_trg() RETURNS TRIGGER AS $$
BEGIN
    IF NOT data_access.validate_scope_ref(
        NEW.scope_kind, NEW.scope_source_table, NEW.scope_ref, NEW.org_id
    ) THEN
        RAISE EXCEPTION 'data_access.scope: invalid scope_ref % for kind % / source_table % / org_id %',
            NEW.scope_ref, NEW.scope_kind, NEW.scope_source_table, NEW.org_id
            USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION data_access.scope_validate_trg() IS
    'Faz 21.3 V25: trigger function passes NEW.org_id to validate_scope_ref '
    '(widened 4-arg signature). RAISE EXCEPTION shape preserved; new field '
    'org_id added to error message for diagnostic clarity.';

-- ============================================================================
-- 5. Trigger rebind
--    DROP IF EXISTS — V19 created this trigger; DROP FUNCTION CASCADE in
--    step 3 only drops dependents of the function being dropped (the
--    3-arg validate_scope_ref). The trigger depends on scope_validate_trg
--    (the trigger function), not on validate_scope_ref directly, so it
--    survives the CASCADE. Drop explicitly so we can rebind cleanly.
-- ============================================================================

DROP TRIGGER IF EXISTS scope_validate_before_write ON data_access.scope;

CREATE TRIGGER scope_validate_before_write
    BEFORE INSERT OR UPDATE OF
        scope_kind, scope_source_schema, scope_source_table, scope_ref, revoked_at, org_id
    ON data_access.scope
    FOR EACH ROW
    EXECUTE FUNCTION data_access.scope_validate_trg();

-- ============================================================================
-- 6. Truncate organization_company (was 0 rows; safe)
--    Reseed runs in Faz 16.2.A runbook AFTER OUR_COMPANY ETL load.
-- ============================================================================

TRUNCATE data_access.organization_company RESTART IDENTITY;

-- (V19's CROSS JOIN seed was MOVED out of this migration. The reseed is
-- now a runbook step after `etl-worker run --tables OUR_COMPANY`. This
-- avoids hard dependency between the migration and ETL load order.)

COMMIT;
