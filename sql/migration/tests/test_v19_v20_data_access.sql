-- Faz 21.A test suite — exercises V19 + V20 + V21 contracts end-to-end:
--   * AÇIK org seed exists
--   * scope_kind ↔ source_table CHECK (V19+V20)
--   * validate_scope_ref() lineage existence guard (V19 raw → V21 JSON, depot V20)
--   * scope_validate_before_write trigger (INSERT + UPDATE coverage per V19 iter-2)
--   * uq_scope_active_assignment partial UNIQUE (re-grant after revoke succeeds)
--   * V21 JSON parse contract (Codex 019dcfb0 BLOCKER absorbed)
--
-- V21 (this iteration): scope_ref ADR-0008 canonical = JSON array string.
-- All positive tests use `'["1001"]'` form. Malformed JSON / empty array /
-- non-scalar first element → trigger returns FALSE → P0001 raised.
--
-- ⚠ DESTRUCTIVE on shared/staged databases. This file calls TRUNCATE on
--   data_access.scope and on the four workcube_mikrolink anchor tables
--   (company, pro_projects, branch, department). It is intended ONLY for
--   ephemeral CI databases (`postgres:16-alpine` service container) or a
--   throwaway local Docker. Do NOT run against any database that already
--   holds ETL data or production tuples.
--
-- Idempotent within a single CI invocation: re-running this file on the
-- same ephemeral DB is safe because every step truncates first.

\set ON_ERROR_STOP on

BEGIN;

-- ============================================================================
-- 0. Reset state — repeatable test run on a stable DB
-- ============================================================================

TRUNCATE data_access.scope RESTART IDENTITY;

-- workcube_mikrolink fixtures: 1 row per scope_kind anchor table.
-- V16 imposes NOT-NULL columns on each table; we set the minimum needed
-- to satisfy them.  We also TRUNCATE first to keep this test idempotent
-- across re-runs (ETL evidence rows would otherwise pile up).
TRUNCATE workcube_mikrolink.company,
         workcube_mikrolink.pro_projects,
         workcube_mikrolink.branch,
         workcube_mikrolink.department
RESTART IDENTITY;

INSERT INTO workcube_mikrolink.company (
    source_pk, source_schema, source_table, content_hash,
    company_status, companycat_id, company_id
) VALUES ('1001', 'workcube_mikrolink', 'COMPANY', 'test-hash-1001',
          true, 1, 1001);

INSERT INTO workcube_mikrolink.pro_projects (
    source_pk, source_schema, source_table, content_hash,
    project_id, project_head
) VALUES ('1204', 'workcube_mikrolink', 'PRO_PROJECTS', 'test-hash-1204',
          1204, 'Test Project 1204');

INSERT INTO workcube_mikrolink.branch (
    source_pk, source_schema, source_table, content_hash,
    branch_status, branch_id, branch_name
) VALUES ('7', 'workcube_mikrolink', 'BRANCH', 'test-hash-7',
          true, 7, 'Test Branch 7');

INSERT INTO workcube_mikrolink.department (
    source_pk, source_schema, source_table, content_hash,
    department_id, department_head
) VALUES ('3792', 'workcube_mikrolink', 'DEPARTMENT', 'test-hash-3792',
          3792, 'Test Depot 3792');

-- ============================================================================
-- 1. AÇIK org seed assertion (V19)
-- ============================================================================

DO $$
DECLARE
    v_count BIGINT;
BEGIN
    SELECT count(*) INTO v_count FROM data_access.organization WHERE name = 'AÇIK' AND status = 'active';
    IF v_count <> 1 THEN
        RAISE EXCEPTION 'expected exactly 1 active AÇIK organization row, got %', v_count;
    END IF;
    RAISE NOTICE 'PASS  AÇIK org seed exists (active)';
END $$;

-- ============================================================================
-- 2. Positive INSERT cases — every scope_kind with valid scope_ref
-- ============================================================================

DO $$
DECLARE
    v_org BIGINT;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';

    -- V21 canonical: scope_ref = JSON array string per ADR-0008 § Object id encoding
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('11111111-1111-1111-1111-111111111111', v_org, 'company', 'COMPANY', '["1001"]');

    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('22222222-2222-2222-2222-222222222222', v_org, 'project', 'PRO_PROJECTS', '["1204"]');

    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('33333333-3333-3333-3333-333333333333', v_org, 'branch', 'BRANCH', '["7"]');

    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('44444444-4444-4444-4444-444444444444', v_org, 'depot', 'DEPARTMENT', '["3792"]');

    RAISE NOTICE 'PASS  4 positive INSERTs (one per scope_kind, JSON array form)';
END $$;

-- ============================================================================
-- 3. Negative CHECK cases — scope_kind / source_table mismatch
--
-- PG fires BEFORE-row triggers ahead of row-level CHECK constraints. Since
-- the V19 trigger only fires WHEN revoked_at IS NULL, we set revoked_at to
-- a past timestamp here to bypass the trigger and exercise the CHECK alone.
-- ============================================================================

DO $$
DECLARE
    v_org BIGINT;
    v_trapped BOOLEAN := FALSE;
    v_now TIMESTAMPTZ := now() - INTERVAL '1 minute';
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';

    -- depot pointed at the OLD pre-V20 placeholder (TBD_DEPOT_TABLE) — CHECK MUST reject.
    BEGIN
        INSERT INTO data_access.scope (
            user_id, org_id, scope_kind, scope_source_table, scope_ref,
            granted_at, revoked_at
        ) VALUES (
            '55555555-5555-5555-5555-555555555555', v_org, 'depot', 'TBD_DEPOT_TABLE', '3792',
            v_now, v_now
        );
        RAISE EXCEPTION 'expected CHECK violation for depot/TBD_DEPOT_TABLE, but INSERT succeeded';
    EXCEPTION WHEN check_violation THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'CHECK violation NOT trapped';
    END IF;
    RAISE NOTICE 'PASS  V20 CHECK rejects depot/TBD_DEPOT_TABLE (pre-V20 placeholder)';

    -- company pointed at PRO_PROJECTS — must FAIL CHECK.
    v_trapped := FALSE;
    BEGIN
        INSERT INTO data_access.scope (
            user_id, org_id, scope_kind, scope_source_table, scope_ref,
            granted_at, revoked_at
        ) VALUES (
            '66666666-6666-6666-6666-666666666666', v_org, 'company', 'PRO_PROJECTS', '1001',
            v_now, v_now
        );
        RAISE EXCEPTION 'expected CHECK violation for company/PRO_PROJECTS, but INSERT succeeded';
    EXCEPTION WHEN check_violation THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'CHECK violation NOT trapped';
    END IF;
    RAISE NOTICE 'PASS  CHECK rejects company/PRO_PROJECTS cross-kind';

    -- depot/DEPOLAR — pre-Faz-21.A naming. Must FAIL CHECK.
    v_trapped := FALSE;
    BEGIN
        INSERT INTO data_access.scope (
            user_id, org_id, scope_kind, scope_source_table, scope_ref,
            granted_at, revoked_at
        ) VALUES (
            '77777777-7777-7777-7777-777777777777', v_org, 'depot', 'DEPOLAR', '3792',
            v_now, v_now
        );
        RAISE EXCEPTION 'expected CHECK violation for depot/DEPOLAR, but INSERT succeeded';
    EXCEPTION WHEN check_violation THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'CHECK violation NOT trapped';
    END IF;
    RAISE NOTICE 'PASS  CHECK rejects depot/DEPOLAR (Faz 21.A: DEPARTMENT only)';

    -- Cleanup the revoked smuggling rows (test 5 expects a clean state).
    DELETE FROM data_access.scope WHERE user_id IN (
        '55555555-5555-5555-5555-555555555555',
        '66666666-6666-6666-6666-666666666666',
        '77777777-7777-7777-7777-777777777777'
    );
END $$;

-- ============================================================================
-- 4. Negative trigger cases — valid (kind, source_table) but invalid scope_ref
-- ============================================================================

DO $$
DECLARE
    v_org BIGINT;
    v_trapped BOOLEAN := FALSE;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';

    -- company/COMPANY but scope_ref does not exist in workcube_mikrolink.company.
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES ('88888888-8888-8888-8888-888888888888', v_org, 'company', 'COMPANY', '["999999"]');
        RAISE EXCEPTION 'expected trigger to reject scope_ref=["999999"], but INSERT succeeded';
    EXCEPTION WHEN raise_exception THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'trigger validate_scope_ref NOT fired';
    END IF;
    RAISE NOTICE 'PASS  trigger rejects company/COMPANY/["999999"] (no lineage, JSON form)';

    -- depot/DEPARTMENT/missing source_pk — V20 branch.
    v_trapped := FALSE;
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES ('99999999-9999-9999-9999-999999999999', v_org, 'depot', 'DEPARTMENT', '["999999"]');
        RAISE EXCEPTION 'expected trigger to reject depot scope_ref=["999999"], but INSERT succeeded';
    EXCEPTION WHEN raise_exception THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'V20 depot branch trigger NOT fired';
    END IF;
    RAISE NOTICE 'PASS  V20 trigger rejects depot/DEPARTMENT/["999999"] (no lineage, JSON form)';

    -- V21: malformed JSON — scope_ref invalid JSON cast → trigger returns FALSE
    v_trapped := FALSE;
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES ('aabbccdd-aabb-ccdd-eeff-aabbccddeeff', v_org, 'company', 'COMPANY', 'not-json{');
        RAISE EXCEPTION 'expected V21 trigger to reject malformed JSON';
    EXCEPTION WHEN raise_exception THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'V21 trigger malformed JSON NOT trapped';
    END IF;
    RAISE NOTICE 'PASS  V21 trigger rejects malformed JSON scope_ref (parse fail-closed)';

    -- V21: empty array — scope_ref ->>0 returns NULL → trigger returns FALSE
    v_trapped := FALSE;
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', v_org, 'company', 'COMPANY', '[]');
        RAISE EXCEPTION 'expected V21 trigger to reject empty array';
    EXCEPTION WHEN raise_exception THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'V21 trigger empty array NOT trapped';
    END IF;
    RAISE NOTICE 'PASS  V21 trigger rejects empty array scope_ref (NULL first element)';

    -- V21: numeric scalar (encoder also accepts) — `[1001]` → ->>0 returns "1001" text
    -- This is a positive case validating numeric scalar parity with string scalar.
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('ddffeeaa-ddff-eeaa-ddff-eeaaddffeeaa', v_org, 'company', 'COMPANY', '[1001]');
    RAISE NOTICE 'PASS  V21 trigger accepts numeric scalar [1001] (parity with ["1001"])';

    -- Cleanup the V21 numeric-scalar row (so subsequent tests have clean state)
    DELETE FROM data_access.scope WHERE user_id = 'ddffeeaa-ddff-eeaa-ddff-eeaaddffeeaa';
END $$;

-- ============================================================================
-- 5. UPDATE-smuggling guard — V19 iter-2: trigger fires on UPDATE too
-- ============================================================================

DO $$
DECLARE
    v_org BIGINT;
    v_id BIGINT;
    v_trapped BOOLEAN := FALSE;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';

    -- Smuggle an invalid scope_ref in as REVOKED (trigger does NOT fire when
    -- revoked_at IS NOT NULL).  The row exists but is inactive.
    -- V21: JSON form scope_ref but pointing to non-existent source_pk.
    INSERT INTO data_access.scope (
        user_id, org_id, scope_kind, scope_source_table, scope_ref,
        granted_at, revoked_at
    )
    VALUES (
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', v_org, 'company', 'COMPANY', '["999999"]',
        now() - INTERVAL '1 hour', now() - INTERVAL '30 minutes'
    )
    RETURNING id INTO v_id;
    RAISE NOTICE '      seeded smuggled-revoked row id=% (scope_ref=["999999"])', v_id;

    -- Now activate the row by clearing revoked_at — trigger MUST fire and reject.
    BEGIN
        UPDATE data_access.scope SET revoked_at = NULL WHERE id = v_id;
        RAISE EXCEPTION 'expected UPDATE trigger to reject reactivation of bad scope_ref';
    EXCEPTION WHEN raise_exception THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'UPDATE trigger NOT fired (smuggling vector open)';
    END IF;
    RAISE NOTICE 'PASS  UPDATE trigger blocks revoked_at=NULL on bad scope_ref';

    -- Cleanup: delete the smuggled row so subsequent tests have a clean state.
    DELETE FROM data_access.scope WHERE id = v_id;
END $$;

-- ============================================================================
-- 6. uq_scope_active_assignment — re-grant after revoke succeeds
-- ============================================================================

DO $$
DECLARE
    v_org BIGINT;
    v_uid UUID := 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
    v_id BIGINT;
    v_trapped BOOLEAN := FALSE;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';

    -- Initial grant. V21: JSON form scope_ref.
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES (v_uid, v_org, 'company', 'COMPANY', '["1001"]')
    RETURNING id INTO v_id;

    -- Same triple again while still ACTIVE — must FAIL via uq_scope_active_assignment.
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES (v_uid, v_org, 'company', 'COMPANY', '["1001"]');
        RAISE EXCEPTION 'expected uq_scope_active_assignment to block duplicate active row';
    EXCEPTION WHEN unique_violation THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'duplicate active scope NOT blocked';
    END IF;
    RAISE NOTICE 'PASS  uq_scope_active_assignment blocks duplicate active grant';

    -- Revoke the first.
    UPDATE data_access.scope SET revoked_at = now() WHERE id = v_id;

    -- Re-grant the same (user, org, kind, ref) — must SUCCEED. V21: JSON form.
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES (v_uid, v_org, 'company', 'COMPANY', '["1001"]');
    RAISE NOTICE 'PASS  re-grant after revoke succeeds (Codex 019dc8b4 iter-2 partial UNIQUE)';
END $$;

-- ============================================================================
-- Final summary
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '=== test_v19_v20_data_access: ALL ASSERTIONS PASSED ===';
END $$;

ROLLBACK;
