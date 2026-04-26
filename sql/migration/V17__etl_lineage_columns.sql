-- Faz 16.3 Gün 7 iter-8 — additive ETL lineage columns for canonical final
-- tables. V16 was an immutable applied migration; this V17 brings any
-- already-applied schema in line with the runner's load_batch() expectations:
--
--   build_upsert_sql() inserts into:
--       (<business cols>, source_schema, source_table, source_pk, content_hash)
--   conflict key:
--       (source_schema, source_table, source_pk)
--
-- Idempotent: every statement uses IF NOT EXISTS / IF EXISTS so re-running on
-- a cluster that already received V17 is a no-op. Safe on empty DBs (test
-- clusters) and on DBs where V16 has been live with rows (Day 8+).
--
-- Backfill semantics:
--   * source_table  = upper(<table_name>)  for any pre-existing rows.
--   * source_pk     = unique per-row sentinel `["__pre_v17_<migration_row_id>"]`.
--                     A single fixed value would have collided in the new
--                     UNIQUE (source_schema, source_table, source_pk) index
--                     for tables with 2+ pre-existing rows. Per-row sentinel
--                     keeps the index satisfiable.
--                     IMPORTANT: these sentinel rows do NOT match the real
--                     ETL conflict key, so the next `etl-worker run` will
--                     INSERT new (real source_pk) rows alongside them. They
--                     must be cleaned up by an operator after lineage is
--                     real, e.g.:
--                       DELETE FROM workcube_mikrolink.<t>
--                       WHERE source_pk LIKE '["__pre_v17_%';
--                     V17 itself does NOT delete them (data-loss potential).
--
-- Codex thread: 019dc6fb iter-9 REVISE.

BEGIN;

-- ============================================================================
-- One-shot helper to apply the same shape change to every canonical table
-- ============================================================================

DO $$
DECLARE
    t TEXT;
    -- Codex iter-9: list MUST mirror V16 canonical CREATE TABLE statements
    -- (20 tables). Drift will surface as ALTER TABLE on a missing relation.
    canonical_tables TEXT[] := ARRAY[
        'branch',
        'company',
        'consumer',
        'department',
        'employee_daily_in_out',
        'employee_positions',
        'employees',
        'employees_detail',
        'employees_identy',
        'employees_in_out',
        'employees_puantaj',
        'employees_puantaj_rows',
        'employees_salary',
        'employees_salary_history',
        'money_history',
        'offtime',
        'our_company',
        'pro_projects',
        'setup_document_type',
        'training_class_attender'
    ];
BEGIN
    FOREACH t IN ARRAY canonical_tables LOOP
        -- Add columns if missing.
        EXECUTE format(
            'ALTER TABLE workcube_mikrolink.%I ADD COLUMN IF NOT EXISTS source_table VARCHAR(128)', t
        );
        EXECUTE format(
            'ALTER TABLE workcube_mikrolink.%I ADD COLUMN IF NOT EXISTS source_pk TEXT', t
        );

        -- Backfill any pre-existing rows so NOT NULL can be enforced safely.
        EXECUTE format(
            'UPDATE workcube_mikrolink.%I SET source_table = upper(%L) WHERE source_table IS NULL',
            t, t
        );
        -- Codex iter-9 fix: per-row sentinel so the new UNIQUE index over
        -- (source_schema, source_table, source_pk) doesn't collide on tables
        -- with 2+ pre-existing rows. Operators clean these up after the next
        -- ETL run inserts real lineage values; see header doc.
        EXECUTE format(
            'UPDATE workcube_mikrolink.%I '
            'SET source_pk = ''["__pre_v17_'' || migration_row_id || ''"]'' '
            'WHERE source_pk IS NULL',
            t
        );

        -- Enforce NOT NULL after backfill.
        EXECUTE format(
            'ALTER TABLE workcube_mikrolink.%I ALTER COLUMN source_table SET NOT NULL', t
        );
        EXECUTE format(
            'ALTER TABLE workcube_mikrolink.%I ALTER COLUMN source_pk SET NOT NULL', t
        );

        -- Conflict-key support: a UNIQUE INDEX is fine; ON CONFLICT (...) accepts
        -- a matching unique index OR a UNIQUE constraint. We use index here so
        -- this script is idempotent without a CONSTRAINT name to depend on.
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_%I_lineage_unique '
            'ON workcube_mikrolink.%I (source_schema, source_table, source_pk)',
            t, t
        );

        -- Lookup helper for reconcile ANY() queries.
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_%I_lineage_pk '
            'ON workcube_mikrolink.%I (source_pk)',
            t, t
        );
    END LOOP;
END $$;

COMMIT;
