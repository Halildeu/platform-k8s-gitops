-- Faz 21.3 PR-G iter-2 — Codex 019dd0e0 BLOCKER 2 absorb.
--
-- V22 outbox table'ında ordering guard `WHERE older.scope_id = scope_outbox.scope_id`
-- üstüne kuruluydu. Sorun: V19 partial UNIQUE allows revoke+re-grant cycle ile
-- AYNI FGA tuple farklı scope.id'lerden geliyor:
--
--   user U grant COMPANY/1001  → scope_id=10, outbox(GRANT, scope_id=10)
--   user U revoke scope_id=10  → outbox(REVOKE, scope_id=10)
--   user U grant AGAIN         → scope_id=11 (yeni), outbox(GRANT, scope_id=11)
--   AYNI FGA tuple: user:U#viewer@company:wc-company-1001
--
-- Mevcut guard scope_id'ye baktığı için outbox(GRANT, scope_id=11) outbox(REVOKE,
-- scope_id=10)'dan ÖNCE process edilebilir → final FGA "deleted" iken DB scope_id=11
-- ACTIVE → invariant break.
--
-- Codex iter-2 verdict (Yol β typed columns):
-- "Bu ordering guard güvenlik/correctness primitive'i. JSONB path expression ile
--  saklı sözleşme kurmak yerine tuple identity'yi schema'da açık kolon yapmak daha
--  doğru. Performans asıl argüman değil; asıl argüman invariant görünürlüğü."
--
-- V23 fix:
--   1. ADD COLUMN tuple_user, tuple_relation, tuple_object (TEXT NOT NULL)
--   2. Backfill from JSONB payload (V22 sonrası mevcut row varsa)
--   3. SET NOT NULL constraint
--   4. DROP V22 idx_scope_outbox_scope_ordering (scope_id-based, artık eski)
--   5. CREATE idx_scope_outbox_tuple_ordering (tuple_*, id) WHERE PENDING/PROCESSING
--
-- tuple_object format: "objectType:objectId" (örn. "company:wc-company-1001")
-- — encoder.encode(scope) FgaTuple çıktısının {objectType, objectId} concat'i.
-- Tek kolon olarak tutulur (Codex önerisi); ayrı objectType + objectId gerekli
-- olursa expression index ile derive edilebilir.
--
-- Backward compat:
--   - V22 sonrası test/staging cluster'larda data_access.scope_outbox boş olabilir
--     (D35 evidence henüz koşmadı, REPORTS_DB_ENABLED=false default)
--   - Boş tablo durumunda backfill 0 row, NOT NULL constraint hemen aktif
--   - Eğer V22'den sonra row varsa (örneğin gelecek smoke), backfill JSONB
--     payload'dan tuple_* kolonlarını doldurur

BEGIN;

-- ============================================================================
-- 1. ADD COLUMN (initially nullable, backfill öncesi)
-- ============================================================================

ALTER TABLE data_access.scope_outbox
    ADD COLUMN IF NOT EXISTS tuple_user TEXT,
    ADD COLUMN IF NOT EXISTS tuple_relation TEXT,
    ADD COLUMN IF NOT EXISTS tuple_object TEXT;

-- ============================================================================
-- 2. Backfill from JSONB payload (idempotent — only fills NULL rows)
-- ============================================================================

UPDATE data_access.scope_outbox
SET tuple_user = payload->'tuple'->>'user',
    tuple_relation = payload->'tuple'->>'relation',
    tuple_object = COALESCE(
        (payload->'tuple'->>'objectType') || ':' || (payload->'tuple'->>'objectId'),
        payload->'tuple'->>'object'  -- fallback: legacy single-key form
    )
WHERE tuple_user IS NULL
   OR tuple_relation IS NULL
   OR tuple_object IS NULL;

-- ============================================================================
-- 3. NOT NULL constraints (post backfill)
-- ============================================================================

ALTER TABLE data_access.scope_outbox
    ALTER COLUMN tuple_user SET NOT NULL,
    ALTER COLUMN tuple_relation SET NOT NULL,
    ALTER COLUMN tuple_object SET NOT NULL;

-- ============================================================================
-- 4. DROP old scope_id-based ordering index (V22, no longer correctness-correct)
-- ============================================================================

DROP INDEX IF EXISTS data_access.idx_scope_outbox_scope_ordering;

-- ============================================================================
-- 5. CREATE new tuple-key ordering index
-- ============================================================================
-- Composite: (tuple_user, tuple_relation, tuple_object, id) WHERE PENDING/PROCESSING.
-- Poller's NOT EXISTS subquery against this index guarantees same-tuple ordering
-- across scope_id boundaries. Partial index keeps it small (only active rows).

CREATE INDEX IF NOT EXISTS idx_scope_outbox_tuple_ordering
    ON data_access.scope_outbox (tuple_user, tuple_relation, tuple_object, id)
    WHERE status IN ('PENDING', 'PROCESSING');

COMMENT ON COLUMN data_access.scope_outbox.tuple_user IS
    'Faz 21.3 V23: OpenFGA tuple user identity (e.g., "user:<uuid>"). '
    'Used by poller ordering guard to serialize same-tuple GRANT/REVOKE.';

COMMENT ON COLUMN data_access.scope_outbox.tuple_relation IS
    'Faz 21.3 V23: OpenFGA tuple relation (e.g., "viewer").';

COMMENT ON COLUMN data_access.scope_outbox.tuple_object IS
    'Faz 21.3 V23: OpenFGA tuple object as "type:id" composite '
    '(e.g., "company:wc-company-1001"). Single column for index simplicity.';

COMMENT ON INDEX data_access.idx_scope_outbox_tuple_ordering IS
    'Faz 21.3 V23: same-tuple ordering guard. Replaces V22 scope_id-based '
    'idx_scope_outbox_scope_ordering (incorrect under revoke+re-grant cycle '
    'producing different scope.id targeting same FGA tuple). '
    'Codex 019dd0e0 BLOCKER 2 absorb.';

COMMIT;
