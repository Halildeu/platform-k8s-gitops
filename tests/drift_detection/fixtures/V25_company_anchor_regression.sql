-- Negative test fixture for ADR-0011 DD-1 drift detection.
--
-- This fixture deliberately regresses V25 anchor contract: company branch
-- references workcube_mikrolink.COMPANY (V19/V20 era directory) instead of
-- workcube_mikrolink.our_company (V25 tenant anchor) + CHECK constraint
-- pair flipped to legacy 'COMPANY' source_table.
--
-- DO NOT use this file as a real migration; it is bait for the drift
-- detection script to verify negative case (exit 1).

BEGIN;

-- Regression #1: CHECK constraint legacy COMPANY pair
ALTER TABLE data_access.scope
    DROP CONSTRAINT IF EXISTS scope_kind_source_table_consistent;

ALTER TABLE data_access.scope
    ADD CONSTRAINT scope_kind_source_table_consistent CHECK (
        (scope_kind = 'company' AND scope_source_table = 'COMPANY')      OR  -- WRONG (V19/V20 era)
        (scope_kind = 'project' AND scope_source_table = 'PRO_PROJECTS') OR
        (scope_kind = 'branch'  AND scope_source_table = 'BRANCH')       OR
        (scope_kind = 'depot'   AND scope_source_table = 'DEPARTMENT')
    );

-- Regression #2: organization_company default + CHECK still legacy 'COMPANY'
-- (V25 should set both to 'OUR_COMPANY')
ALTER TABLE data_access.organization_company
    ALTER COLUMN source_table SET DEFAULT 'COMPANY';
-- Note: no ADD CONSTRAINT line — DD-1 check 3 should fail on missing 'OUR_COMPANY' default + CHECK

-- Regression #3: validate_scope_ref function company branch anchors COMPANY directory
DROP FUNCTION IF EXISTS data_access.validate_scope_ref(TEXT, TEXT, TEXT, BIGINT) CASCADE;

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
    BEGIN
        v_pk := p_ref::jsonb->>0;
    EXCEPTION
        WHEN OTHERS THEN RETURN FALSE;
    END;

    IF v_pk IS NULL THEN RETURN FALSE; END IF;

    IF p_kind = 'company' AND p_source_table = 'COMPANY' THEN
        -- WRONG: V19/V20 era anchor; V25 should be OUR_COMPANY
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.company c
        WHERE c.source_pk = v_pk
          AND c.source_schema = 'workcube_mikrolink';
    ELSE
        RETURN FALSE;
    END IF;

    RETURN v_count > 0;
END;
$$ LANGUAGE plpgsql STABLE;

COMMIT;
