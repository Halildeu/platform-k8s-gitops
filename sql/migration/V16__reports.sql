-- Faz 16.2 — Flyway V16 Reports Migration (skeleton, Codex iter-3 AGREE)
-- Generator: scripts/migration/generate_v16_sql.py (40 tablo full DDL üretir)
-- Bu skeleton: section structure + audit + raw staging + 1 örnek parametric tablo (BANK_ACTIONS)
-- Tam 40 tablo DDL Gün 3 sprint sonunda generate edilir.
--
-- Section structure:
-- 00 extensions
-- 01 schemas
-- 02 migration metadata (audit)
-- 03 raw staging tables
-- 04 final canonical tables
-- 05 partitions (per-year LIST)
-- 06 indexes
-- 07 constraints minimal / NOT VALID
-- 08 comments

BEGIN;

-- ========================================
-- 00 EXTENSIONS
-- ========================================
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid

-- ========================================
-- 01 SCHEMAS
-- ========================================
CREATE SCHEMA IF NOT EXISTS workcube_mikrolink;
CREATE SCHEMA IF NOT EXISTS workcube_mssql_raw;
CREATE SCHEMA IF NOT EXISTS migration_audit;

COMMENT ON SCHEMA workcube_mikrolink IS 'Faz 16 — Workcube MSSQL canonical PG mirror (40 tablo subset)';
COMMENT ON SCHEMA workcube_mssql_raw IS 'Faz 16 — Worker staging (per-table fixed, TRUNCATE on success)';
COMMENT ON SCHEMA migration_audit IS 'Faz 16 — ETL run/state/reject audit';

-- ========================================
-- 02 MIGRATION METADATA (audit)
-- ========================================

CREATE TABLE migration_audit.migration_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    mode VARCHAR(20) NOT NULL CHECK (mode IN ('initial','final_delta','reconcile_only','dry_run')),
    status VARCHAR(20) NOT NULL CHECK (status IN ('RUNNING','SUCCESS','FAILED','ABORTED')),
    source_database VARCHAR(128) NOT NULL,
    worker_version VARCHAR(40),
    git_sha VARCHAR(40),
    contract_version VARCHAR(40),
    annex_version VARCHAR(40),
    started_by VARCHAR(128),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error_summary TEXT,
    notes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_migration_runs_status ON migration_audit.migration_runs (status, started_at DESC);

CREATE TABLE migration_audit.migration_table_state (
    run_id UUID NOT NULL REFERENCES migration_audit.migration_runs(run_id) ON DELETE CASCADE,
    table_name VARCHAR(128) NOT NULL,
    source_schema VARCHAR(128) NOT NULL,
    source_year SMALLINT,
    status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING','EXTRACTING','LOADING','VALIDATED','FAILED')),
    rows_extracted BIGINT NOT NULL DEFAULT 0,
    rows_loaded BIGINT NOT NULL DEFAULT 0,
    rows_rejected BIGINT NOT NULL DEFAULT 0,
    last_pk TEXT,
    checksum VARCHAR(64),
    content_hash VARCHAR(64),
    default_partition_rows BIGINT NOT NULL DEFAULT 0,
    batch_no INTEGER NOT NULL DEFAULT 0,
    extract_query_hash VARCHAR(64),
    max_updated_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (run_id, table_name, source_schema, COALESCE(source_year, 0))
);

CREATE INDEX idx_migration_table_state_status ON migration_audit.migration_table_state (status, table_name);

CREATE TABLE migration_audit.migration_rejects (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    source_schema VARCHAR(128),
    source_year SMALLINT,
    source_pk TEXT,
    column_name VARCHAR(128),
    reject_reason VARCHAR(40) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'ERROR' CHECK (severity IN ('WARN','ERROR','CRITICAL')),
    source_value TEXT,
    pg_error_code TEXT,
    pg_error_message TEXT,
    raw_payload JSONB,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolution_notes TEXT
);

CREATE INDEX idx_migration_rejects_run ON migration_audit.migration_rejects (run_id, table_name);
CREATE INDEX idx_migration_rejects_unresolved ON migration_audit.migration_rejects (table_name, rejected_at DESC) WHERE resolved_at IS NULL;

-- ========================================
-- 03 RAW STAGING (per-table fixed, TRUNCATE on success)
-- ========================================

-- Pattern: workcube_mssql_raw.<table_name> her tablo için fixed schema
-- raw_payload JSONB tüm MSSQL row'unu olduğu gibi tutar
-- Worker COPY ile bulk insert, transform sonrası TRUNCATE

CREATE TABLE workcube_mssql_raw.bank_actions (
    run_id UUID NOT NULL,
    source_schema VARCHAR(128) NOT NULL,
    source_year SMALLINT,
    source_pk TEXT,
    raw_payload JSONB NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_raw_bank_actions_run ON workcube_mssql_raw.bank_actions (run_id);

-- TODO: scripts/migration/generate_v16_sql.py 39 ek tablo için raw staging üretir

-- ========================================
-- 04+05 FINAL CANONICAL + PARTITIONS (örnek: BANK_ACTIONS)
-- ========================================

-- BANK_ACTIONS (parametric, schema_mode=yearly, used by fin-banka-hareketleri + fin-nakit-akis-ozet)
CREATE TABLE workcube_mikrolink.bank_actions (
    source_year SMALLINT NOT NULL,
    source_schema VARCHAR(128) NOT NULL,
    bank_action_id BIGINT NOT NULL,
    action_date TIMESTAMPTZ,
    amount NUMERIC(19,4),
    description TEXT,
    -- TODO: scripts/migration/generate_v16_sql.py snapshot JSON'dan tüm kolonları enumerate eder
    content_hash VARCHAR(64) NOT NULL,
    migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_year, bank_action_id)
) PARTITION BY LIST (source_year);

-- Partition seti: 2024-2028 + DEFAULT (Codex iter-3 öneri)
CREATE TABLE workcube_mikrolink.bank_actions_2024 PARTITION OF workcube_mikrolink.bank_actions FOR VALUES IN (2024);
CREATE TABLE workcube_mikrolink.bank_actions_2025 PARTITION OF workcube_mikrolink.bank_actions FOR VALUES IN (2025);
CREATE TABLE workcube_mikrolink.bank_actions_2026 PARTITION OF workcube_mikrolink.bank_actions FOR VALUES IN (2026);
CREATE TABLE workcube_mikrolink.bank_actions_2027 PARTITION OF workcube_mikrolink.bank_actions FOR VALUES IN (2027);
CREATE TABLE workcube_mikrolink.bank_actions_2028 PARTITION OF workcube_mikrolink.bank_actions FOR VALUES IN (2028);
CREATE TABLE workcube_mikrolink.bank_actions_default PARTITION OF workcube_mikrolink.bank_actions DEFAULT;

-- ========================================
-- 06 INDEXES
-- ========================================

CREATE INDEX idx_bank_actions_date ON workcube_mikrolink.bank_actions (source_year, action_date);
CREATE INDEX idx_bank_actions_hash ON workcube_mikrolink.bank_actions (content_hash);

-- ========================================
-- 07 CONSTRAINTS MINIMAL (FK NOT VALID)
-- ========================================

-- Codex iter-3 verdict: FK MINIMAL — sadece kritik parent-child, NOT VALID, runtime read-only
-- Reconciliation authoritative (16.3.5 gate)
-- TODO: generator output FK adaylarını flag eder, manuel review sonrası buraya eklenir

-- ========================================
-- 08 COMMENTS
-- ========================================

COMMENT ON TABLE workcube_mikrolink.bank_actions IS 'Workcube BANK_ACTIONS — parametric schema_mode=yearly, partition by source_year. Raporlar: fin-banka-hareketleri, fin-nakit-akis-ozet';
COMMENT ON COLUMN workcube_mikrolink.bank_actions.source_year IS 'Workcube fiscal year (workcube_mikrolink_N → year mapping, admin onayı)';
COMMENT ON COLUMN workcube_mikrolink.bank_actions.source_schema IS 'Audit trail: hangi MSSQL schema''dan geldi';
COMMENT ON COLUMN workcube_mikrolink.bank_actions.content_hash IS 'SHA-256 idempotency key (raw_payload normalized hash)';

COMMIT;

-- =============================================================================
-- POST-MIGRATION (manual)
-- =============================================================================
-- 1. ETL worker run: python -m mssql_etl_worker --mode=initial --run-id=<uuid>
-- 2. Reconciliation: python -m mssql_etl_worker --mode=reconcile_only --run-id=<uuid>
-- 3. FK validate (eğer eklenmişse): ALTER TABLE ... VALIDATE CONSTRAINT ...
-- 4. Cutover (16.5): REPORT_MSSQL_ENABLED=false flag rollout
