-- Negative test fixture for ADR-0011 DD-2 — V26 ETL canonical p_ref regression.
--
-- This fixture removes "= p_ref" canonical acceptance from validate_scope_ref;
-- only "= v_pk" raw form remains. ETL canonical JSON output ("[\"1\"]") would
-- no longer match because v_pk is the extracted "1".
--
-- DO NOT use as real migration; bait for DD-2 negative test.

BEGIN;

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

    IF p_kind = 'company' AND p_source_table = 'OUR_COMPANY' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.our_company oc
        JOIN data_access.organization_company oc_map
          ON oc_map.workcube_company_source_pk = oc.source_pk
        WHERE oc.source_pk = v_pk  -- WRONG: missing OR oc.source_pk = p_ref
          AND oc.source_schema = 'workcube_mikrolink'
          AND oc_map.org_id = p_org_id;
    ELSIF p_kind = 'project' AND p_source_table = 'PRO_PROJECTS' THEN
        SELECT count(*) INTO v_count FROM workcube_mikrolink.pro_projects p
        WHERE p.source_pk = v_pk;  -- WRONG: missing canonical p_ref
    ELSIF p_kind = 'branch' AND p_source_table = 'BRANCH' THEN
        SELECT count(*) INTO v_count FROM workcube_mikrolink.branch b
        WHERE b.source_pk = v_pk;  -- WRONG
    ELSIF p_kind = 'depot' AND p_source_table = 'DEPARTMENT' THEN
        SELECT count(*) INTO v_count FROM workcube_mikrolink.department d
        WHERE d.source_pk = v_pk;  -- WRONG
    ELSE
        RETURN FALSE;
    END IF;

    RETURN v_count > 0;
END;
$$ LANGUAGE plpgsql STABLE;

COMMIT;
