-- Faz 21.2 — Veri Erişimi Multi-Org Scope Layer (data_access schema).
-- Codex thread 019dc8b4 iter-1 REVISE absorbed:
--   * reports_db içinde ayrı `data_access` schema (lineage-locality wins).
--   * scope_source_schema/source_table explicit + CHECK constraint.
--   * `data_access.validate_scope_ref()` lineage existence guard
--     (PG'de N tablo çapraz FK natürel değil; trigger + function tercih).
--
-- User mandate (2026-04-26):
--   "Workcube MSSQL kurum olarak AÇIK kurumu olarak işaretleyelim."
--   "ayrı bir kurum gelirse ayrıca vereceğim. postsql de ekleyelim
--    kurum adını"
--
-- Multi-org tasarım korunur (N:N organization_company), ancak bu fazın
-- canlı verisi tek-org. Yeni kurum geldiğinde:
--   INSERT INTO data_access.organization (name, status) VALUES (...);
--   INSERT INTO data_access.organization_company (...);
-- yeterli; yeniden migration gerekmez.

BEGIN;

CREATE SCHEMA IF NOT EXISTS data_access;
COMMENT ON SCHEMA data_access IS
    'Multi-org veri erişimi scope layer. ETL canonical workcube_mikrolink.* '
    'ile lineage join üzerinden çalışır (source_pk).';

-- ============================================================================
-- organization
-- ============================================================================

CREATE TABLE data_access.organization (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('active','suspended','archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID,
    notes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_organization_status ON data_access.organization (status);

COMMENT ON TABLE data_access.organization IS
    'Platform üzerinde hizmet alan kurumlar. AÇIK = Workcube MSSQL '
    'kaynağındaki tüm Workcube COMPANY satırlarının ait olduğu seed kurum.';

-- ============================================================================
-- organization_company  (org → Workcube COMPANY many-to-many; bu fazda 1:N)
-- ============================================================================

CREATE TABLE data_access.organization_company (
    org_id BIGINT NOT NULL REFERENCES data_access.organization(id) ON DELETE CASCADE,
    workcube_company_source_pk TEXT NOT NULL,
    source_schema TEXT NOT NULL DEFAULT 'workcube_mikrolink'
        CHECK (source_schema = 'workcube_mikrolink'),
    source_table TEXT NOT NULL DEFAULT 'COMPANY' CHECK (source_table = 'COMPANY'),
    attached_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (org_id, workcube_company_source_pk)
);

CREATE INDEX idx_organization_company_org ON data_access.organization_company (org_id);
CREATE INDEX idx_organization_company_pk ON data_access.organization_company (workcube_company_source_pk);

COMMENT ON TABLE data_access.organization_company IS
    'Bir kurumun sahip olduğu Workcube COMPANY satırlarının lineage referansı. '
    'workcube_company_source_pk ↔ workcube_mikrolink.company.source_pk join.';

-- ============================================================================
-- scope  (kullanıcı bazlı veri erişimi atamaları)
-- ============================================================================

CREATE TABLE data_access.scope (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    org_id BIGINT NOT NULL REFERENCES data_access.organization(id) ON DELETE CASCADE,
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('company','project','depot','branch')),
    scope_source_schema TEXT NOT NULL DEFAULT 'workcube_mikrolink'
        CHECK (scope_source_schema = 'workcube_mikrolink'),
    scope_source_table TEXT NOT NULL,
    scope_ref TEXT NOT NULL,
    granted_by UUID,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    revoked_by UUID,
    notes JSONB NOT NULL DEFAULT '{}'::jsonb
    -- Codex 019dc8b4 iter-2: table-level UNIQUE removed; revoked rows
    -- otherwise block re-grant. Active-only partial UNIQUE INDEX below.
);

-- Active-only uniqueness — admin can re-grant a previously revoked scope.
CREATE UNIQUE INDEX uq_scope_active_assignment
    ON data_access.scope (user_id, org_id, scope_kind, scope_ref)
    WHERE revoked_at IS NULL;

-- Scope kind ↔ source_table consistency. Depot table is TBD per
-- docs/migration/depolar-source-decision.md (Faz 21.A); the CHECK leaves
-- a placeholder slot that must be tightened once the decision lands.
ALTER TABLE data_access.scope
    ADD CONSTRAINT scope_kind_source_table_consistent CHECK (
        (scope_kind = 'company'  AND scope_source_table = 'COMPANY') OR
        (scope_kind = 'project'  AND scope_source_table = 'PRO_PROJECTS') OR
        (scope_kind = 'branch'   AND scope_source_table = 'BRANCH') OR
        (scope_kind = 'depot'    AND scope_source_table = 'TBD_DEPOT_TABLE')
    );

CREATE INDEX idx_scope_user ON data_access.scope (user_id);
CREATE INDEX idx_scope_org ON data_access.scope (org_id);
CREATE INDEX idx_scope_kind_ref ON data_access.scope (scope_kind, scope_ref) WHERE revoked_at IS NULL;
CREATE INDEX idx_scope_active ON data_access.scope (user_id, org_id) WHERE revoked_at IS NULL;

COMMENT ON TABLE data_access.scope IS
    'Kullanıcı × organization × (company|project|depot|branch) → scope_ref '
    'atamaları. revoked_at NULL = aktif. Audit trail için satır silinmez.';

-- ============================================================================
-- validate_scope_ref()  (existence guard for scope_ref)
-- ============================================================================

-- N tablo çapraz FK doğal değil; bunun yerine scope_kind'a göre uygun
-- workcube_mikrolink tablosunda source_pk varlığını doğrulayan trigger.
CREATE OR REPLACE FUNCTION data_access.validate_scope_ref(
    p_kind TEXT,
    p_source_table TEXT,
    p_ref TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_count BIGINT;
BEGIN
    IF p_kind = 'company' AND p_source_table = 'COMPANY' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.company
        WHERE source_pk = p_ref AND source_schema = 'workcube_mikrolink';
    ELSIF p_kind = 'project' AND p_source_table = 'PRO_PROJECTS' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.pro_projects
        WHERE source_pk = p_ref AND source_schema = 'workcube_mikrolink';
    ELSIF p_kind = 'branch' AND p_source_table = 'BRANCH' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.branch
        WHERE source_pk = p_ref AND source_schema = 'workcube_mikrolink';
    ELSE
        -- depot TBD veya beklenmedik kombinasyon
        RETURN FALSE;
    END IF;
    RETURN v_count > 0;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION data_access.validate_scope_ref(TEXT,TEXT,TEXT) IS
    'Scope_ref ETL canonical tablosunda gerçekten var mı? Trigger '
    'tarafından çağrılır. depot kindi TBD_DEPOT_TABLE ile False döner; '
    'depo tablosu netleşince genişletilir.';

CREATE OR REPLACE FUNCTION data_access.scope_validate_trg() RETURNS TRIGGER AS $$
BEGIN
    IF NOT data_access.validate_scope_ref(NEW.scope_kind, NEW.scope_source_table, NEW.scope_ref) THEN
        RAISE EXCEPTION 'data_access.scope: invalid scope_ref % for kind % / source_table % '
                        '(no matching row in workcube_mikrolink.* with that source_pk)',
                        NEW.scope_ref, NEW.scope_kind, NEW.scope_source_table;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Codex 019dc8b4 iter-2: also fire on UPDATE that activates / changes the
-- scope target. Without this, an invalid scope can be smuggled in as
-- revoked, then activated via UPDATE (revoked_at = NULL) without
-- re-validation; or scope_kind/scope_ref/scope_source_table can be
-- mutated post-grant.
CREATE TRIGGER scope_validate_before_write
    BEFORE INSERT OR UPDATE OF
        scope_kind, scope_source_schema, scope_source_table, scope_ref, revoked_at
    ON data_access.scope
    FOR EACH ROW
    WHEN (NEW.revoked_at IS NULL)
    EXECUTE FUNCTION data_access.scope_validate_trg();

-- ============================================================================
-- AÇIK kurum seed
-- ============================================================================

INSERT INTO data_access.organization (name, status, notes)
VALUES (
    'AÇIK',
    'active',
    jsonb_build_object(
        'source', 'V19__data_access.sql seed',
        'mandate', 'Kullanıcı 2026-04-26: Workcube MSSQL kurum olarak AÇIK',
        'workcube_database', 'workcube_mikrolink'
    )
)
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- Bootstrap: AÇIK ↔ tüm landed Workcube COMPANY satırlarını otomatik bağla
-- ============================================================================

-- Idempotent: ETL ile yeni COMPANY satırı geldiğinde aynı SQL tekrar
-- çalıştırılırsa duplicate atılır (PRIMARY KEY).
INSERT INTO data_access.organization_company (
    org_id, workcube_company_source_pk, source_schema, source_table
)
SELECT
    o.id,
    c.source_pk,
    'workcube_mikrolink',
    'COMPANY'
FROM data_access.organization o
CROSS JOIN workcube_mikrolink.company c
WHERE o.name = 'AÇIK'
  AND c.source_schema = 'workcube_mikrolink'
ON CONFLICT (org_id, workcube_company_source_pk) DO NOTHING;

COMMIT;
