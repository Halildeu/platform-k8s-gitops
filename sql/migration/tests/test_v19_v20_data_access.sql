-- Faz 21.A + V22 test suite — exercises V19 + V20 + V21 + V22 contracts end-to-end:
--   * AÇIK org seed exists
--   * scope_kind ↔ source_table CHECK (V19+V20)
--   * validate_scope_ref() lineage existence guard (V19 raw → V21 JSON, depot V20)
--   * scope_validate_before_write trigger (INSERT + UPDATE coverage per V19 iter-2)
--   * uq_scope_active_assignment partial UNIQUE (re-grant after revoke succeeds)
--   * V21 JSON parse contract (Codex 019dcfb0 BLOCKER absorbed)
--   * V22 outbox table — claim/PROCESSING/PROCESSED/FAILED transitions
--   * V22 recover_stuck_outbox_rows() function
--   * V22 action + status CHECK constraints
--   * V22 5 indexes (claim, ordering, recovery, failed, scope_id)
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

-- V22 outbox FK references scope.id; CASCADE truncates outbox alongside.
TRUNCATE data_access.scope RESTART IDENTITY CASCADE;

-- workcube_mikrolink fixtures: V25 hybrid contract.
-- Anchor: OUR_COMPANY (was COMPANY); + COMPANY/BRANCH/DEPARTMENT/PRO_PROJECTS
-- with FK columns wired to OUR_COMPANY for tenant predicate join testing.
-- V16 imposes NOT-NULL columns on each table; we set the minimum needed
-- to satisfy them. TRUNCATE first for idempotency across re-runs.

-- V22 outbox FK references scope.id; CASCADE truncates outbox alongside.
-- Already done on line 36. Add organization_company truncate (V25 default
-- semantic).
TRUNCATE data_access.organization_company RESTART IDENTITY;

TRUNCATE workcube_mikrolink.our_company,
         workcube_mikrolink.company,
         workcube_mikrolink.pro_projects,
         workcube_mikrolink.branch,
         workcube_mikrolink.department
RESTART IDENTITY CASCADE;

-- OUR_COMPANY: tenant boundary anchor (V25). source_pk = lineage of COMP_ID.
-- Two rows simulating two tenant orgs (only one belongs to AÇIK; the other
-- exists but belongs to a different org → tenant boundary test).
INSERT INTO workcube_mikrolink.our_company (
    source_pk, source_schema, source_table, content_hash,
    comp_id, company_name
) VALUES
  ('1', 'workcube_mikrolink', 'OUR_COMPANY', 'test-hash-our-1', 1, 'AÇIK Tenant Mikrolink'),
  ('99', 'workcube_mikrolink', 'OUR_COMPANY', 'test-hash-our-99', 99, 'Other Tenant');

-- COMPANY directory rows: includes both AÇIK (our_company_id=1) and other
-- tenant (our_company_id=99); used for project/branch 2-hop predicate tests.
INSERT INTO workcube_mikrolink.company (
    source_pk, source_schema, source_table, content_hash,
    company_status, companycat_id, company_id, our_company_id
) VALUES
  ('1001', 'workcube_mikrolink', 'COMPANY', 'test-hash-1001',
   true, 1, 1001, 1),    -- AÇIK tenant
  ('1099', 'workcube_mikrolink', 'COMPANY', 'test-hash-1099',
   true, 1, 1099, 99);   -- Other tenant

-- PRO_PROJECTS: linked to AÇIK COMPANY (1001) for tenant predicate positive,
-- and to Other COMPANY (1099) for negative.
INSERT INTO workcube_mikrolink.pro_projects (
    source_pk, source_schema, source_table, content_hash,
    project_id, project_head, company_id
) VALUES
  ('1204', 'workcube_mikrolink', 'PRO_PROJECTS', 'test-hash-1204',
   1204, 'Test Project 1204 (AÇIK)', 1001),
  ('9999', 'workcube_mikrolink', 'PRO_PROJECTS', 'test-hash-9999',
   9999, 'Test Project 9999 (Other)', 1099);

-- BRANCH: same pattern as PRO_PROJECTS (2-hop tenant predicate).
INSERT INTO workcube_mikrolink.branch (
    source_pk, source_schema, source_table, content_hash,
    branch_status, branch_id, branch_name, company_id
) VALUES
  ('7', 'workcube_mikrolink', 'BRANCH', 'test-hash-7',
   true, 7, 'Test Branch 7 (AÇIK)', 1001),
  ('77', 'workcube_mikrolink', 'BRANCH', 'test-hash-77',
   true, 77, 'Test Branch 77 (Other)', 1099);

-- DEPARTMENT: 1-hop tenant predicate via OUR_COMPANY_ID.
INSERT INTO workcube_mikrolink.department (
    source_pk, source_schema, source_table, content_hash,
    department_id, department_head, our_company_id
) VALUES
  ('3792', 'workcube_mikrolink', 'DEPARTMENT', 'test-hash-3792',
   3792, 'Test Depot 3792 (AÇIK)', 1),
  ('3799', 'workcube_mikrolink', 'DEPARTMENT', 'test-hash-3799',
   3799, 'Test Depot 3799 (Other)', 99);

-- V25 reseed: organization_company mapping for AÇIK tenant.
-- (V25 migration moved the V19 CROSS JOIN seed out; in production this is
-- done via Faz 16.2.A runbook after OUR_COMPANY ETL load. In tests we seed
-- explicitly to exercise the mapping.)
INSERT INTO data_access.organization_company
    (org_id, workcube_company_source_pk, source_schema, source_table)
SELECT o.id, '1', 'workcube_mikrolink', 'OUR_COMPANY'
FROM data_access.organization o
WHERE o.name = 'AÇIK';
-- Note: source_pk='99' (Other tenant) deliberately NOT seeded — used in
-- negative tenant boundary tests below.

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

    -- V25 canonical: scope_source_table OUR_COMPANY for company kind.
    -- Tenant predicate validated via organization_company mapping seeded above.
    -- V21 canonical: scope_ref = JSON array string per ADR-0008 § Object id encoding
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('11111111-1111-1111-1111-111111111111', v_org, 'company', 'OUR_COMPANY', '["1"]');

    -- project: PRO_PROJECTS (1204) → COMPANY (1001) → OUR_COMPANY (1) → AÇIK
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('22222222-2222-2222-2222-222222222222', v_org, 'project', 'PRO_PROJECTS', '["1204"]');

    -- branch: BRANCH (7) → COMPANY (1001) → OUR_COMPANY (1) → AÇIK
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('33333333-3333-3333-3333-333333333333', v_org, 'branch', 'BRANCH', '["7"]');

    -- depot: DEPARTMENT (3792) → OUR_COMPANY (1) → AÇIK
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('44444444-4444-4444-4444-444444444444', v_org, 'depot', 'DEPARTMENT', '["3792"]');

    RAISE NOTICE 'PASS  4 positive INSERTs (V25 hybrid contract — anchor + tenant predicate)';
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
    EXCEPTION WHEN check_violation OR raise_exception THEN
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
    EXCEPTION WHEN check_violation OR raise_exception THEN
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
    EXCEPTION WHEN check_violation OR raise_exception THEN
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
        VALUES ('88888888-8888-8888-8888-888888888888', v_org, 'company', 'OUR_COMPANY', '["999"]');
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
        VALUES ('aabbccdd-aabb-ccdd-eeff-aabbccddeeff', v_org, 'company', 'OUR_COMPANY', 'not-json{');
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
        VALUES ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', v_org, 'company', 'OUR_COMPANY', '[]');
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
    VALUES ('ddffeeaa-ddff-eeaa-ddff-eeaaddffeeaa', v_org, 'company', 'OUR_COMPANY', '[1]');
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
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', v_org, 'company', 'OUR_COMPANY', '["999"]',
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
    VALUES (v_uid, v_org, 'company', 'OUR_COMPANY', '["1"]')
    RETURNING id INTO v_id;

    -- Same triple again while still ACTIVE — must FAIL via uq_scope_active_assignment.
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES (v_uid, v_org, 'company', 'OUR_COMPANY', '["1"]');
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
    VALUES (v_uid, v_org, 'company', 'OUR_COMPANY', '["1"]');
    RAISE NOTICE 'PASS  re-grant after revoke succeeds (Codex 019dc8b4 iter-2 partial UNIQUE)';
END $$;

-- ============================================================================
-- 7. V22 outbox table — schema + claim semantics + recovery (Codex 019dcf5c)
-- ============================================================================

DO $$
DECLARE
    v_org BIGINT;
    v_scope_id BIGINT;
    v_outbox_id BIGINT;
    v_recovered INT;
    v_claimed INT;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';

    -- Create a scope row to attach outbox to (V22 outbox FK references scope.id)
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('cccccccc-cccc-cccc-cccc-cccccccccccc', v_org, 'company', 'OUR_COMPANY', '["1"]')
    RETURNING id INTO v_scope_id;

    -- V22 outbox PENDING row INSERT (V23: tuple_* columns NOT NULL)
    INSERT INTO data_access.scope_outbox (
        scope_id, action, payload,
        tuple_user, tuple_relation, tuple_object
    )
    VALUES (
        v_scope_id, 'GRANT',
        jsonb_build_object(
            'scopeId', v_scope_id,
            'userId', 'cccccccc-cccc-cccc-cccc-cccccccccccc',
            'orgId', v_org,
            'scopeKind', 'company',
            'scopeRef', '["1001"]',
            'tuple', jsonb_build_object(
                'user', 'user:cccccccc-cccc-cccc-cccc-cccccccccccc',
                'relation', 'viewer',
                'object', 'company:wc-company-1001'
            )
        ),
        'user:cccccccc-cccc-cccc-cccc-cccccccccccc',
        'viewer',
        'company:wc-company-1001'
    )
    RETURNING id INTO v_outbox_id;
    RAISE NOTICE 'PASS  V22 outbox PENDING row INSERT (scope_id=% outbox_id=%)', v_scope_id, v_outbox_id;
END $$;

DO $$
DECLARE
    v_outbox_id BIGINT;
    v_status TEXT;
    v_attempt INT;
BEGIN
    SELECT id INTO v_outbox_id FROM data_access.scope_outbox
    WHERE scope_id = (SELECT id FROM data_access.scope WHERE user_id = 'cccccccc-cccc-cccc-cccc-cccccccccccc')
    LIMIT 1;

    -- Simulate poller claim: UPDATE PENDING → PROCESSING + lock metadata
    UPDATE data_access.scope_outbox
    SET status = 'PROCESSING',
        locked_by = 'test-poller-instance-1',
        locked_until = now() + INTERVAL '2 minutes',
        attempt_count = attempt_count + 1
    WHERE id = v_outbox_id AND status = 'PENDING'
    RETURNING status, attempt_count INTO v_status, v_attempt;

    IF v_status != 'PROCESSING' OR v_attempt != 1 THEN
        RAISE EXCEPTION 'V22 claim failed: status=% attempt=%', v_status, v_attempt;
    END IF;
    RAISE NOTICE 'PASS  V22 outbox claim transition PENDING→PROCESSING (attempt %)', v_attempt;

    -- Simulate successful FGA write completion: PROCESSING → PROCESSED
    UPDATE data_access.scope_outbox
    SET status = 'PROCESSED',
        processed_at = now(),
        locked_by = NULL,
        locked_until = NULL
    WHERE id = v_outbox_id AND status = 'PROCESSING';

    SELECT status INTO v_status FROM data_access.scope_outbox WHERE id = v_outbox_id;
    IF v_status != 'PROCESSED' THEN
        RAISE EXCEPTION 'V22 PROCESSED transition failed: status=%', v_status;
    END IF;
    RAISE NOTICE 'PASS  V22 outbox transition PROCESSING→PROCESSED (processed_at set)';
END $$;

DO $$
DECLARE
    v_org BIGINT;
    v_scope_id BIGINT;
    v_outbox_id BIGINT;
    v_recovered INT;
    v_status TEXT;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';

    -- Create another scope to attach a stuck-PROCESSING outbox row to
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('dddddddd-dddd-dddd-dddd-dddddddddddd', v_org, 'project', 'PRO_PROJECTS', '["1204"]')
    RETURNING id INTO v_scope_id;

    -- Insert a PROCESSING row with EXPIRED locked_until (pod crash simulation)
    INSERT INTO data_access.scope_outbox (
        scope_id, action, payload, status,
        tuple_user, tuple_relation, tuple_object,
        locked_by, locked_until, attempt_count
    )
    VALUES (
        v_scope_id, 'GRANT',
        jsonb_build_object('scopeId', v_scope_id, 'userId', 'dddddddd-dddd-dddd-dddd-dddddddddddd'),
        'PROCESSING',
        'user:dddddddd-dddd-dddd-dddd-dddddddddddd', 'viewer', 'project:wc-project-1204',
        'crashed-pod-instance', now() - INTERVAL '5 minutes',  -- stuck (locked_until past)
        2
    )
    RETURNING id INTO v_outbox_id;

    -- Run recovery function
    SELECT data_access.recover_stuck_outbox_rows() INTO v_recovered;

    IF v_recovered < 1 THEN
        RAISE EXCEPTION 'V22 stuck row recovery did not fire (recovered=%)', v_recovered;
    END IF;

    -- Verify the row is back to PENDING with locked_by/locked_until cleared
    SELECT status INTO v_status FROM data_access.scope_outbox WHERE id = v_outbox_id;
    IF v_status != 'PENDING' THEN
        RAISE EXCEPTION 'V22 stuck row not recovered to PENDING: status=%', v_status;
    END IF;
    RAISE NOTICE 'PASS  V22 recover_stuck_outbox_rows() releases PROCESSING→PENDING (recovered=%)', v_recovered;
END $$;

DO $$
DECLARE
    v_org BIGINT;
    v_scope_id BIGINT;
    v_trapped BOOLEAN := FALSE;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';
    SELECT id INTO v_scope_id FROM data_access.scope
    WHERE user_id = 'cccccccc-cccc-cccc-cccc-cccccccccccc' LIMIT 1;

    -- V22 CHECK: action must be GRANT or REVOKE (V23: tuple_* required)
    BEGIN
        INSERT INTO data_access.scope_outbox (
            scope_id, action, payload,
            tuple_user, tuple_relation, tuple_object
        )
        VALUES (
            v_scope_id, 'INVALID_ACTION', '{}'::jsonb,
            'user:test', 'viewer', 'company:test'
        );
        RAISE EXCEPTION 'V22 action CHECK NOT trapped';
    EXCEPTION WHEN check_violation OR raise_exception THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'V22 action CHECK should reject INVALID_ACTION';
    END IF;
    RAISE NOTICE 'PASS  V22 outbox action CHECK rejects unknown values';

    -- V22 CHECK: status must be one of 4 valid states (V23: tuple_* required)
    v_trapped := FALSE;
    BEGIN
        INSERT INTO data_access.scope_outbox (
            scope_id, action, payload, status,
            tuple_user, tuple_relation, tuple_object
        )
        VALUES (
            v_scope_id, 'GRANT', '{}'::jsonb, 'BOGUS_STATE',
            'user:test', 'viewer', 'company:test'
        );
        RAISE EXCEPTION 'V22 status CHECK NOT trapped';
    EXCEPTION WHEN check_violation OR raise_exception THEN
        v_trapped := TRUE;
    END;
    IF NOT v_trapped THEN
        RAISE EXCEPTION 'V22 status CHECK should reject BOGUS_STATE';
    END IF;
    RAISE NOTICE 'PASS  V22 outbox status CHECK rejects unknown values';
END $$;

DO $$
DECLARE
    v_count BIGINT;
BEGIN
    -- Verify V22 indexes exist (claim, recovery, failed, scope_id)
    -- NOTE: V23 dropped idx_scope_outbox_scope_ordering (Codex 019dd0e0 BLOCKER 2 fix);
    -- replaced by idx_scope_outbox_tuple_ordering. Verified separately below.
    SELECT count(*) INTO v_count FROM pg_indexes
    WHERE schemaname = 'data_access' AND tablename = 'scope_outbox'
      AND indexname IN (
          'idx_scope_outbox_claim',
          'idx_scope_outbox_recovery',
          'idx_scope_outbox_failed',
          'idx_scope_outbox_scope_id'
      );
    IF v_count != 4 THEN
        RAISE EXCEPTION 'V22 (post-V23) expected 4 indexes, got %', v_count;
    END IF;
    RAISE NOTICE 'PASS  V22 outbox 4 indexes present (claim/recovery/failed/scope_id; ordering moved to V23)';
END $$;

-- ============================================================================
-- 8. V23 outbox tuple typed columns + tuple-key ordering (Codex 019dd0e0 BLOCKER 2)
-- ============================================================================

DO $$
DECLARE
    v_count BIGINT;
BEGIN
    -- V23: tuple_user, tuple_relation, tuple_object NOT NULL columns added
    SELECT count(*) INTO v_count FROM information_schema.columns
    WHERE table_schema = 'data_access' AND table_name = 'scope_outbox'
      AND column_name IN ('tuple_user', 'tuple_relation', 'tuple_object')
      AND is_nullable = 'NO';
    IF v_count != 3 THEN
        RAISE EXCEPTION 'V23 expected 3 NOT NULL tuple columns, got %', v_count;
    END IF;
    RAISE NOTICE 'PASS  V23 outbox tuple_user/tuple_relation/tuple_object NOT NULL';
END $$;

DO $$
DECLARE
    v_count BIGINT;
BEGIN
    -- V23: idx_scope_outbox_tuple_ordering exists
    SELECT count(*) INTO v_count FROM pg_indexes
    WHERE schemaname = 'data_access'
      AND indexname = 'idx_scope_outbox_tuple_ordering';
    IF v_count != 1 THEN
        RAISE EXCEPTION 'V23 expected idx_scope_outbox_tuple_ordering, got %', v_count;
    END IF;
    -- And the V22 scope_id-based ordering index is dropped
    SELECT count(*) INTO v_count FROM pg_indexes
    WHERE schemaname = 'data_access'
      AND indexname = 'idx_scope_outbox_scope_ordering';
    IF v_count != 0 THEN
        RAISE EXCEPTION 'V23 should have dropped idx_scope_outbox_scope_ordering, but found %', v_count;
    END IF;
    RAISE NOTICE 'PASS  V23 idx_scope_outbox_tuple_ordering replaces V22 scope_id-based index';
END $$;

DO $$
DECLARE
    v_org BIGINT;
    v_scope_id_a BIGINT;
    v_scope_id_b BIGINT;
    v_outbox_a BIGINT;  -- GRANT scope_id_a (older)
    v_outbox_b BIGINT;  -- REVOKE scope_id_a
    v_outbox_c BIGINT;  -- GRANT scope_id_b (re-grant, same tuple)
    v_count BIGINT;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';

    -- V23 BLOCKER 2 SCENARIO: revoke+re-grant same tuple key (different scope.id)

    -- 1. First grant: scope_id=A, outbox GRANT
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa', v_org, 'company', 'OUR_COMPANY', '["1"]')
    RETURNING id INTO v_scope_id_a;

    INSERT INTO data_access.scope_outbox (
        scope_id, action, payload, tuple_user, tuple_relation, tuple_object
    )
    VALUES (
        v_scope_id_a, 'GRANT',
        jsonb_build_object('scopeId', v_scope_id_a),
        'user:11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'viewer', 'company:wc-company-1001'
    )
    RETURNING id INTO v_outbox_a;

    -- Simulate scope_id=A processed (PROCESSED)
    UPDATE data_access.scope_outbox SET status = 'PROCESSED', processed_at = now() WHERE id = v_outbox_a;

    -- 2. Revoke scope_id=A: outbox REVOKE same tuple
    UPDATE data_access.scope SET revoked_at = now() WHERE id = v_scope_id_a;
    INSERT INTO data_access.scope_outbox (
        scope_id, action, payload, tuple_user, tuple_relation, tuple_object
    )
    VALUES (
        v_scope_id_a, 'REVOKE',
        jsonb_build_object('scopeId', v_scope_id_a),
        'user:11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'viewer', 'company:wc-company-1001'
    )
    RETURNING id INTO v_outbox_b;

    -- 3. Re-grant: NEW scope_id=B (V19 partial UNIQUE allows post-revoke)
    INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
    VALUES ('11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa', v_org, 'company', 'OUR_COMPANY', '["1"]')
    RETURNING id INTO v_scope_id_b;

    INSERT INTO data_access.scope_outbox (
        scope_id, action, payload, tuple_user, tuple_relation, tuple_object
    )
    VALUES (
        v_scope_id_b, 'GRANT',
        jsonb_build_object('scopeId', v_scope_id_b),
        'user:11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'viewer', 'company:wc-company-1001'
    )
    RETURNING id INTO v_outbox_c;

    -- 4. CRITICAL TEST: simulate poller's claim NOT EXISTS guard.
    --    Outbox state: B (PROCESSED), A (PENDING REVOKE), C (PENDING GRANT same tuple)
    --    Claim eligibility for outbox C: NOT EXISTS older same-tuple PENDING/PROCESSING?
    --    Older same-tuple: outbox B (id < C.id, status PENDING) → MATCHES → NOT EXISTS = false
    --    → outbox C should NOT be claim-eligible until B processed.

    SELECT count(*) INTO v_count
    FROM data_access.scope_outbox outer_row
    WHERE outer_row.id = v_outbox_c
      AND outer_row.status = 'PENDING'
      AND NOT EXISTS (
          SELECT 1 FROM data_access.scope_outbox older
          WHERE older.tuple_user = outer_row.tuple_user
            AND older.tuple_relation = outer_row.tuple_relation
            AND older.tuple_object = outer_row.tuple_object
            AND older.id < outer_row.id
            AND older.status IN ('PENDING', 'PROCESSING')
      );

    IF v_count != 0 THEN
        RAISE EXCEPTION 'V23 ordering FAIL: outbox_c claim-eligible while older REVOKE outbox_b PENDING (count=%)', v_count;
    END IF;
    RAISE NOTICE 'PASS  V23 ordering guard blocks GRANT(scope_id=B) while REVOKE(scope_id=A) same-tuple PENDING';

    -- 5. Now process REVOKE outbox_b (simulate)
    UPDATE data_access.scope_outbox SET status = 'PROCESSED', processed_at = now() WHERE id = v_outbox_b;

    -- 6. Verify outbox_c is NOW claim-eligible (no older PENDING/PROCESSING for same tuple)
    SELECT count(*) INTO v_count
    FROM data_access.scope_outbox outer_row
    WHERE outer_row.id = v_outbox_c
      AND outer_row.status = 'PENDING'
      AND NOT EXISTS (
          SELECT 1 FROM data_access.scope_outbox older
          WHERE older.tuple_user = outer_row.tuple_user
            AND older.tuple_relation = outer_row.tuple_relation
            AND older.tuple_object = outer_row.tuple_object
            AND older.id < outer_row.id
            AND older.status IN ('PENDING', 'PROCESSING')
      );

    IF v_count != 1 THEN
        RAISE EXCEPTION 'V23 ordering FAIL: outbox_c not claim-eligible after REVOKE processed (count=%)', v_count;
    END IF;
    RAISE NOTICE 'PASS  V23 GRANT(scope_id=B) claim-eligible after REVOKE(scope_id=A) processed';

    -- Cleanup
    DELETE FROM data_access.scope_outbox WHERE id IN (v_outbox_a, v_outbox_b, v_outbox_c);
    DELETE FROM data_access.scope WHERE id IN (v_scope_id_a, v_scope_id_b);
END $$;

-- ============================================================================
-- 11. V25 tenant predicate negative tests (anchor + tenant-membership guard)
-- ============================================================================

-- Test 11.a: company OUR_COMPANY exists in workcube_mikrolink, but NOT mapped
-- to AÇIK org via organization_company → trigger reject (tenant boundary).
DO $$
DECLARE
    v_org BIGINT;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES ('11dd0099-aaaa-bbbb-cccc-dddd00009999', v_org, 'company', 'OUR_COMPANY', '["99"]');
        RAISE EXCEPTION 'V25 tenant predicate FAIL: company OUR_COMPANY=99 (other tenant) accepted, expected reject';
    EXCEPTION
        WHEN raise_exception THEN
            RAISE NOTICE 'PASS  V25 tenant boundary: company OUR_COMPANY=99 (no AÇIK mapping) rejected';
        WHEN OTHERS THEN
            RAISE EXCEPTION 'V25 tenant predicate fired wrong exception: %', SQLERRM;
    END;
END $$;

-- Test 11.b: branch BRANCH=77 references COMPANY=1099 (other tenant) →
-- trigger reject (2-hop tenant predicate).
DO $$
DECLARE
    v_org BIGINT;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES ('22dd0099-aaaa-bbbb-cccc-dddd00007777', v_org, 'branch', 'BRANCH', '["77"]');
        RAISE EXCEPTION 'V25 tenant predicate FAIL: branch BRANCH=77 (via other tenant COMPANY) accepted, expected reject';
    EXCEPTION
        WHEN raise_exception THEN
            RAISE NOTICE 'PASS  V25 tenant boundary 2-hop: branch BRANCH=77 (Other tenant company) rejected';
        WHEN OTHERS THEN
            RAISE EXCEPTION 'V25 branch predicate fired wrong exception: %', SQLERRM;
    END;
END $$;

-- Test 11.c: project PRO_PROJECTS=9999 references COMPANY=1099 (other tenant) →
-- trigger reject (2-hop tenant predicate).
DO $$
DECLARE
    v_org BIGINT;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES ('33dd0099-aaaa-bbbb-cccc-dddd00009999', v_org, 'project', 'PRO_PROJECTS', '["9999"]');
        RAISE EXCEPTION 'V25 tenant predicate FAIL: project PRO_PROJECTS=9999 (via other tenant COMPANY) accepted, expected reject';
    EXCEPTION
        WHEN raise_exception THEN
            RAISE NOTICE 'PASS  V25 tenant boundary 2-hop: project PRO_PROJECTS=9999 (Other tenant company) rejected';
        WHEN OTHERS THEN
            RAISE EXCEPTION 'V25 project predicate fired wrong exception: %', SQLERRM;
    END;
END $$;

-- Test 11.d: depot DEPARTMENT=3799 references OUR_COMPANY=99 (other tenant) →
-- trigger reject (1-hop tenant predicate).
DO $$
DECLARE
    v_org BIGINT;
BEGIN
    SELECT id INTO v_org FROM data_access.organization WHERE name = 'AÇIK';
    BEGIN
        INSERT INTO data_access.scope (user_id, org_id, scope_kind, scope_source_table, scope_ref)
        VALUES ('44dd0099-aaaa-bbbb-cccc-dddd00003799', v_org, 'depot', 'DEPARTMENT', '["3799"]');
        RAISE EXCEPTION 'V25 tenant predicate FAIL: depot DEPARTMENT=3799 (other tenant OUR_COMPANY) accepted, expected reject';
    EXCEPTION
        WHEN raise_exception THEN
            RAISE NOTICE 'PASS  V25 tenant boundary 1-hop: depot DEPARTMENT=3799 (Other tenant OUR_COMPANY) rejected';
        WHEN OTHERS THEN
            RAISE EXCEPTION 'V25 depot predicate fired wrong exception: %', SQLERRM;
    END;
END $$;

-- Test 11.e: validate_scope_ref function signature is widened (4-arg). Test
-- that the 3-arg version is gone (V25 explicit DROP CASCADE).
DO $$
DECLARE
    v_count BIGINT;
BEGIN
    SELECT count(*) INTO v_count
    FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'data_access'
      AND p.proname = 'validate_scope_ref'
      AND pg_get_function_identity_arguments(p.oid) = 'p_kind text, p_source_table text, p_ref text';
    IF v_count <> 0 THEN
        RAISE EXCEPTION 'V25 signature widening FAIL: 3-arg validate_scope_ref still exists, expected DROPped';
    END IF;
    RAISE NOTICE 'PASS  V25 signature widening: 3-arg validate_scope_ref dropped (only 4-arg present)';
END $$;

-- ============================================================================
-- Final summary
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '=== test_v19_v20_data_access: ALL ASSERTIONS PASSED (V25 hybrid contract) ===';
END $$;

ROLLBACK;
