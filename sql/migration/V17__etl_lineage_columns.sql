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
--   * source_pk     = NULL → set to '[]' as a deterministic sentinel so
--                     NOT NULL can be enforced. The ETL runner will
--                     overwrite these on the next ON CONFLICT update because
--                     content_hash is identical, so this acts as a one-time
--                     marker for "row was migrated before lineage existed".
--                     Operators investigating sentinel rows should re-run
--                     `etl-worker reconcile` post-load.
--
-- Codex thread: 019dc6fb iter-8 REVISE.

BEGIN;

-- ============================================================================
-- One-shot helper to apply the same shape change to every canonical table
-- ============================================================================

DO $$
DECLARE
    t TEXT;
    canonical_tables TEXT[] := ARRAY[
        'branch',
        'company',
        'consumer',
        'department',
        'employees',
        'employees_detail',
        'employees_identy',
        'employees_in_out',
        'employees_puantaj',
        'employees_puantaj_rows',
        'employees_position_history',
        'positions',
        'position_categories',
        'sector_categories',
        'subsector',
        'training_class',
        'training_class_attender',
        'training_class_files',
        'training_class_levels',
        'training_class_member'
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
        EXECUTE format(
            'UPDATE workcube_mikrolink.%I SET source_pk = ''[]'' WHERE source_pk IS NULL',
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
