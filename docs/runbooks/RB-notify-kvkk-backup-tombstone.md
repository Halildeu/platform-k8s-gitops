# RB — KVKK Madde 11 Backup Restore Tombstone + Re-erasure Prosedürü

> **Status**: ACTIVE (Codex `019e4950` P0 absorb 2026-05-21)
> **Tetik**: PG backup restore → silinmiş subject'lerin verilerinin geri gelmesi → KVKK Madde 11 ihlali
> **Owner**: ops (PG backup restore operator) + dev (re-erasure script trigger)
> **SLA**: backup restore tamamlanmasından sonra **24 saat içinde** re-erasure tamamlanmalı (KVKK 11.4 + Madde 13.2 spirit)

## Bağlam

PG backup restore senaryosu (disaster recovery, point-in-time recovery, schema migration rollback) sırasında **silinmiş subject'lerin verileri geri gelebilir**. KVKK Madde 11 gereği bu veriler **tekrar silinmeli** — backup integrity sağlanmalı + immutable retention policy uygulanmalı.

**Codex 019e4950 P0 finding**: Mevcut Day-2 governance backup retention (`day-2-governance.md`): PG logical dump 14 gün, base backup 4 hafta. **AMA**: backup restore prosedürü silinmiş subject'lerin yeniden purge edilmesini garantilemiyor. Bu **P0 gap**.

## Erasure Request Ledger (PR-K1 scope)

Bu runbook'un en kritik bağımlılığı PR-K1 ile gelen `notify.erasure_request_ledger` tablosu:

```sql
CREATE TABLE notify.erasure_request_ledger (
    request_id            UUID PRIMARY KEY,
    org_id                VARCHAR(64) NOT NULL,
    subject_ref_hmac      VARCHAR(128) NOT NULL,  -- HMAC-pseudonymized subject ref
    received_at           TIMESTAMPTZ NOT NULL,
    due_at                TIMESTAMPTZ NOT NULL,   -- received_at + 30d (KVKK Madde 13.2)
    status                VARCHAR(32) NOT NULL,
        CHECK (status IN ('pending', 'in_progress', 'closed', 'failed', 'legal_hold')),
    closed_at             TIMESTAMPTZ,
    legal_hold_reason     VARCHAR(256),
    idempotency_key       VARCHAR(128) UNIQUE NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Bu ledger tablosu **backup restore sonrası** kritik: `SELECT request_id FROM notify.erasure_request_ledger WHERE status='closed'` → bu request'leri **tekrar uygula**.

## Backup Restore Prosedürü

### 1. Pre-restore checklist

- [ ] **Backup restore gerekçesi** dokümante edildi (disaster recovery / point-in-time / migration rollback)
- [ ] Restore hedefi: tüm DB / sadece notify schema / sadece belirli table
- [ ] Restore zaman noktası (`xlog_LSN` veya timestamp)
- [ ] **Erasure request ledger snapshot** (restore öncesi closed status'taki request'lerin listesi):
  ```sql
  pg_dump --data-only --table=notify.erasure_request_ledger -h ... -U platform > erasure-ledger-pre-restore.sql
  ```

### 2. Restore execute

Standart pgbackrest / pg_basebackup restore prosedürü (`docs/day-2-governance.md` veya operator runbook'a göre).

### 3. Post-restore re-erasure execution

**T+0 (immediately)**: Restored DB üzerinde re-erasure script:

```bash
# 1. Mevcut closed erasure request'leri tekrar query et
psql -h $PG_HOST -U platform -d notify_db -t -c "
  SELECT request_id, org_id, subject_ref_hmac
  FROM notify.erasure_request_ledger
  WHERE status = 'closed'
  ORDER BY closed_at DESC;
" > erasure-requests-to-replay.txt

# 2. Pre-restore snapshot ile karşılaştır (paranoia check)
diff <(awk '{print $1}' erasure-requests-to-replay.txt) \
     <(grep -oE 'INSERT INTO.*request_id.*UUID' erasure-ledger-pre-restore.sql | grep -oE 'UUID.*' | awk '{print $2}')

# 3. Her closed request için ErasureService.erase tekrar trigger
# (admin scope token gerek — RB-prod-canary-kc-claim-setup.md operator chain ile)
while IFS='|' read -r request_id org_id subject_ref; do
  echo "Re-erasing request_id=$request_id org=$org_id"
  curl -X POST https://ai.acik.com/api/v1/admin/notify/erasure \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "X-Org-Id: $org_id" \
    -H "Content-Type: application/json" \
    -d "{\"subject_ref_hmac\":\"$subject_ref\",\"reason\":\"post_backup_restore_re_erasure\",\"idempotency_key\":\"replay-${request_id}\"}"
done < erasure-requests-to-replay.txt

# 4. Audit event yaz: POST_RESTORE_RE_ERASURE_BATCH
psql -h $PG_HOST -U platform -d notify_db -c "
  INSERT INTO notify.audit_event_v2 (org_id, event_type, details, created_at)
  VALUES ('default', 'POST_RESTORE_RE_ERASURE_BATCH',
    '{\"restore_time\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
      \"batch_size\":$(wc -l < erasure-requests-to-replay.txt),
      \"runbook\":\"RB-notify-kvkk-backup-tombstone.md\"}',
    NOW());
"
```

### 4. Verification

Re-erasure başarısı:
- Erasure request ledger: her `closed` request `closed_at` timestamp güncellenmiş (post-restore re-execution)
- notification_intent + notification_delivery + audit_event PII fields: yeniden nullify edilmiş
- Audit event: `POST_RESTORE_RE_ERASURE_BATCH` row mevcut

```sql
-- Re-erasure verify
SELECT
  l.request_id,
  l.closed_at,
  CASE WHEN i.payload IS NULL THEN '✓' ELSE '✗ payload still has PII' END AS intent_check,
  CASE WHEN d.recipient_id IS NULL THEN '✓' ELSE '✗ delivery recipient_id leaked' END AS delivery_check
FROM notify.erasure_request_ledger l
LEFT JOIN notify.notification_intent i ON i.org_id = l.org_id  -- coarse join
LEFT JOIN notify.notification_delivery d ON d.intent_id = i.intent_id
WHERE l.status = 'closed'
  AND l.closed_at > NOW() - INTERVAL '24 hours';
```

## Provider-side Re-erasure

PG re-erasure tamamlandıktan sonra **provider-side propagation** da tekrarlanmalı (`RB-notify-kvkk-provider-propagation.md` matrix):

- Email/Office 365: Graph API DELETE (eğer message geri geldiyse — restore window içinde sent items)
- SMS providers: DPA retention promise documented (provider-side immutable yedek varsayımı)
- Webhook egress: müşteri ticket re-notify (transitive)

## Backup Retention Policy Recommendation

Codex `019e4950` P0 recommendation absorb:

| Backup type | Mevcut | Önerilen |
|---|---|---|
| PG logical dump | 14 gün | **7 gün** (KVKK 30-gün cevap window içinde re-erasure mümkün; daha kısa retention KVKK-friendly) |
| PG base backup | 4 hafta | **2 hafta** (DR window yeterli; daha uzun retention KVKK risk) |
| Loki log retention | 7-14 gün | **7 gün** (PII filter ile birlikte; subscriber_id log'ta YOK olmalı PR-K4 sonrası) |
| Tempo trace retention | (currently disabled prod) | **3 gün** (activate olduğunda; tenant-level trace privacy) |

**Karar**: bu değerler operator/DPO onaylı; Day-2 governance.md update ayrı PR scope'unda.

## Legal hold istisnası

Eğer erasure request `legal_hold_reason` ile flagged ise (KVKK Madde 7 — hukuki yükümlülük gereği saklama):
- Re-erasure **execute edilmez**
- Audit event: `POST_RESTORE_RE_ERASURE_SKIPPED_LEGAL_HOLD`
- DPO/legal review trigger

## DPO/Legal final onay

Bu runbook **AI proxy review (Codex)** ile hazırlandı. **DPO/legal final onay** gereken kalemler:
- Backup retention policy (7/14/30 gün) müşteri/regulator beklentisi ile uyumlu mu?
- Re-erasure SLA (24 saat post-restore) yeterli mi yoksa daha agresif (1 saat) gerek mi?
- Legal hold dokümantasyon (Madde 7 saklama yükümlülüğü) — hangi kategoride hangi süre

## Cross-link

- Codex thread: `019e4950-d30e-7781-a50a-0ef619503e08`
- KVKK Madde 11.1.e + Madde 11.4 + Madde 13.2
- PR-K1: erasure request ledger (V18 migration; bu runbook'un ön koşulu)
- `RB-notify-kvkk-provider-propagation.md`: provider matrix (paralel runbook)
- `docs/day-2-governance.md`: PG backup retention policy (ileride update gerekebilir)
