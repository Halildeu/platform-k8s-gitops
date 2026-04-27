-- Faz 21.3 PR-F (C3c) bulgusu — scope_ref kontrat uyumlama (Codex 019dcfb0 BLOCKER #2).
--
-- ADR-0008 § Object id encoding canonical scope_ref formatını JSON array string olarak
-- tanımlar (örn. `'["1001"]'`). Encoder (DataAccessScopeTupleEncoder.parseFirstRef) ve
-- UI (ScopeAssignModal.buildScopeRef) bu kontrata uygun veri üretir/tüketir.
--
-- Ancak V19 `validate_scope_ref()` fonksiyonu raw PK karşılaştırması yapıyordu:
--   WHERE source_pk = p_ref
-- Bu UI'dan gelen `'["1001"]'` değeri için workcube_mikrolink.company source_pk='1001'
-- ile asla eşleşmez → P0001 RAISE EXCEPTION → ScopeValidationException → 422.
--
-- D35 first evidence smoke'unda bu bug yakalanırdı; PR-F (Testcontainers) Codex iter-1
-- review'unda statik tespit edildi. V21 fix:
--   - validate_scope_ref() JSONB cast + ->>0 ile ilk element extraction
--   - Malformed JSON için exception PG-side fail-closed (encoder davranışına paralel)
--
-- Idempotent: CREATE OR REPLACE FUNCTION + IF NOT EXISTS test (function definition tek
-- shape'e gelir — V19 ve V20'in birikimi V21 final state).
--
-- Backward compat:
--   - Şu an staging-sw cluster'larında data_access.scope tablosu boş (D35 evidence
--     henüz koşmadı, REPORTS_DB_ENABLED=false). V21 öncesi insert edilmiş row yok.
--   - Eğer ileride raw PK formatında row migrate edilmesi gerekirse ayrı backfill
--     migration gerek; V21 sadece function definition günceller.

BEGIN;

-- ============================================================================
-- validate_scope_ref() — JSON array first-element extraction
-- ============================================================================

CREATE OR REPLACE FUNCTION data_access.validate_scope_ref(
    p_kind TEXT,
    p_source_table TEXT,
    p_ref TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_count BIGINT;
    v_pk TEXT;
BEGIN
    -- ADR-0008 canonical: scope_ref = JSON array string (örn. `'["1001"]'`).
    -- İlk element string olarak extract edilir; composite PK desteği için
    -- ADR rules.pk = scope_ref ilk element (composite ise '-' join — bu V21
    -- single-element kontratını single PK için karşılar; composite future PR).
    --
    -- p_ref geçerli JSON array değilse PG cast hatası fırlatır (PSQLException
    -- SQLState 22P02 invalid_text_representation). Bu davranış encoder'ın
    -- IllegalArgumentException("not valid JSON") fail-closed semantiği ile
    -- aynıdır — geçersiz scope_ref reject edilir, ScopeValidation 422 döner.
    BEGIN
        v_pk := p_ref::jsonb->>0;
    EXCEPTION
        WHEN OTHERS THEN
            -- JSON cast fail veya null first element → invalid scope_ref
            RETURN FALSE;
    END;

    IF v_pk IS NULL THEN
        -- jsonb->>0 null → empty array veya null first → invalid
        RETURN FALSE;
    END IF;

    IF p_kind = 'company' AND p_source_table = 'COMPANY' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.company
        WHERE source_pk = v_pk AND source_schema = 'workcube_mikrolink';
    ELSIF p_kind = 'project' AND p_source_table = 'PRO_PROJECTS' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.pro_projects
        WHERE source_pk = v_pk AND source_schema = 'workcube_mikrolink';
    ELSIF p_kind = 'branch' AND p_source_table = 'BRANCH' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.branch
        WHERE source_pk = v_pk AND source_schema = 'workcube_mikrolink';
    ELSIF p_kind = 'depot' AND p_source_table = 'DEPARTMENT' THEN
        SELECT count(*) INTO v_count
        FROM workcube_mikrolink.department
        WHERE source_pk = v_pk AND source_schema = 'workcube_mikrolink';
    ELSE
        RETURN FALSE;
    END IF;
    RETURN v_count > 0;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION data_access.validate_scope_ref(TEXT,TEXT,TEXT) IS
    'Faz 21.3 V21: scope_ref ADR-0008 canonical JSON array kontratına hizalandı. '
    'V19 raw PK karşılaştırması encoder/UI ile çelişiyordu (Codex 019dcfb0 BLOCKER). '
    'jsonb->>0 ile ilk element extraction; malformed JSON fail-closed (FALSE).';

COMMIT;
