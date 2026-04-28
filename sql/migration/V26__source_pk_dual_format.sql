-- Faz 21.3 — V26 source_pk dual-format compatibility fix.
--
-- Discovery context:
--   2026-04-28 D35-1 first live test: V25 validate_scope_ref rejected
--   scope_ref=["1"] for company/OUR_COMPANY even though:
--     - workcube_mikrolink.our_company had source_pk='["1"]' (loaded by ETL)
--     - data_access.organization_company had workcube_company_source_pk='["1"]'
--     - org_id=1 (AÇIK) was correctly mapped
--
--   Root cause: V25 used `WHERE source_pk = v_pk` where v_pk =
--   p_ref::jsonb->>0 (extracts "1" from '["1"]'). But ETL worker
--   (per Codex iter-6 contract on transform.py:make_source_pk) stores
--   source_pk in canonical JSON array form ('["1"]'). Comparing
--   extracted "1" to stored '["1"]' → mismatch → reject.
--
--   The same drift affected the test fixture (raw '1' string in test_v19_v20)
--   vs the production ETL writes '["1"]'. Test passed because fixture used
--   raw form, but production data uses JSON form.
--
-- V26 fix:
--   Make validate_scope_ref tolerate BOTH formats via OR predicate:
--     (source_pk = v_pk OR source_pk = p_ref)
--   AND accept either format on the organization_company JOIN side too.
--
--   This is forward-compatible: when ETL contract is canonical (JSON),
--   the second clause matches; when test fixture uses raw form, first
--   clause matches. No format normalization required at write time.
--
-- Codex thread: continuation of `019dd34e` PR-2 (V25). V25's anchor table
-- correction was right; V26 is the format-canonicalization missing piece.
--
-- Idempotent: CREATE OR REPLACE FUNCTION; no schema mutations.

BEGIN;

-- ============================================================================
-- validate_scope_ref() V26: dual-format tolerance for source_pk + oc_map join
-- ============================================================================

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
    -- ADR-0008: scope_ref = JSON array string ('["1"]'). Extract first element
    -- as raw "1" for backward-compat with test fixtures. ETL worker stores
    -- source_pk as JSON canonical form per transform.py:make_source_pk
    -- (Codex iter-6); accept both via OR predicate below.
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
          ON (oc_map.workcube_company_source_pk = oc.source_pk
              OR oc_map.workcube_company_source_pk = v_pk
              OR oc_map.workcube_company_source_pk = oc.comp_id::text)
        WHERE (oc.source_pk = v_pk OR oc.source_pk = p_ref)
          AND oc.source_schema = 'workcube_mikrolink'
          AND oc_map.org_id = p_org_id;

    ELSIF p_kind = 'project' AND p_source_table = 'PRO_PROJECTS' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.pro_projects p
        JOIN workcube_mikrolink.company c
          ON c.company_id = p.company_id
        JOIN workcube_mikrolink.our_company oc
          ON oc.comp_id = c.our_company_id
        JOIN data_access.organization_company oc_map
          ON (oc_map.workcube_company_source_pk = oc.source_pk
              OR oc_map.workcube_company_source_pk = oc.comp_id::text)
        WHERE (p.source_pk = v_pk OR p.source_pk = p_ref)
          AND p.source_schema = 'workcube_mikrolink'
          AND oc_map.org_id = p_org_id;

    ELSIF p_kind = 'branch' AND p_source_table = 'BRANCH' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.branch b
        JOIN workcube_mikrolink.company c
          ON c.company_id = b.company_id
        JOIN workcube_mikrolink.our_company oc
          ON oc.comp_id = c.our_company_id
        JOIN data_access.organization_company oc_map
          ON (oc_map.workcube_company_source_pk = oc.source_pk
              OR oc_map.workcube_company_source_pk = oc.comp_id::text)
        WHERE (b.source_pk = v_pk OR b.source_pk = p_ref)
          AND b.source_schema = 'workcube_mikrolink'
          AND oc_map.org_id = p_org_id;

    ELSIF p_kind = 'depot' AND p_source_table = 'DEPARTMENT' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.department d
        JOIN workcube_mikrolink.our_company oc
          ON oc.comp_id = d.our_company_id
        JOIN data_access.organization_company oc_map
          ON (oc_map.workcube_company_source_pk = oc.source_pk
              OR oc_map.workcube_company_source_pk = oc.comp_id::text)
        WHERE (d.source_pk = v_pk OR d.source_pk = p_ref)
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
    'Faz 21.3 V26: dual-format source_pk compatibility. ETL worker stores '
    'source_pk as canonical JSON array (transform.py:make_source_pk per '
    'Codex iter-6); test fixtures may use raw form. Both accepted via OR '
    'predicate. V25 introduced tenant predicates; V26 adds format-tolerance.';

COMMIT;
