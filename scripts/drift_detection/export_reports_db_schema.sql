-- ADR-0011 DD-3 — Export reports_db.workcube_mikrolink.* actual schema as JSON.
--
-- Operator (kullanıcı) runbook:
--   docs/RB-faz-21-3-adr-0011-dd-3-schema-snapshot.md
--
-- Output target: docs/migration/reports-db-workcube-actual-schema.json
--
-- Codex 019dd409 B-prime: read-only operator export. Ne credential ne
-- mutation; sadece information_schema query'leri.
--
-- Usage (operator shell):
--   ssh halil@staging-sw "docker exec platform-pg-test psql \
--     -U platform -d reports_db \
--     -At -f - " < scripts/drift_detection/export_reports_db_schema.sql \
--     > docs/migration/reports-db-workcube-actual-schema.json
--
-- The output is a single JSON object with:
--   {
--     "generated_at": "<UTC ISO8601>",
--     "source_snapshot_sha256": "<sha256 of docs/migration/workcube-schema.json>",
--     "schema": "workcube_mikrolink",
--     "tables": {
--       "TABLE_NAME": {
--         "columns": [
--           {"name": "COL_NAME", "data_type": "text", "is_nullable": "YES"},
--           ...
--         ]
--       },
--       ...
--     }
--   }

\set ON_ERROR_STOP on

-- Variables — operator runbook'ta export zamanı set edilir
\if :{?source_sha256}
\else
  \set source_sha256 'placeholder-operator-fills'
\endif

\set generated_at `date -u +%Y-%m-%dT%H:%M:%SZ`

WITH cols AS (
    SELECT
        c.table_name,
        json_agg(
            json_build_object(
                'name', c.column_name,
                'data_type', c.data_type,
                'is_nullable', c.is_nullable,
                'character_maximum_length', c.character_maximum_length,
                'numeric_precision', c.numeric_precision,
                'numeric_scale', c.numeric_scale
            )
            ORDER BY c.ordinal_position
        ) AS columns
    FROM information_schema.columns c
    WHERE c.table_schema = 'workcube_mikrolink'
    GROUP BY c.table_name
)
SELECT json_build_object(
    'generated_at', :'generated_at',
    'source_snapshot_sha256', :'source_sha256',
    'schema', 'workcube_mikrolink',
    'tables', json_object_agg(table_name, json_build_object('columns', columns))
)::text
FROM cols;
