# Etik Speak — Retention + Erasure Policy

> **Scope:** Faz 35 Etik Speak whistleblowing kanalı için veri saklama süreleri, silme prosedürleri, legal hold + WORM enforcement. Yasal dayanak: **KVKK Md.7 silme/yok etme/anonimleştirme + Md.28 açıklama istisnası**, **GDPR Art.5(1)(e) storage limitation**, **EU 2019/1937 Art.18 record-keeping + Sarbanes-Oxley Sec.802 records retention**, **ISO 37002:2021 §8.6 record retention**.

## 1. Retention süre tablosu

| Veri kategorisi | Saklama süresi | Trigger | Yasal dayanak | Silme yöntemi |
|---|---|---|---|---|
| **Case: bildirim içeriği (subject + description)** | 5 yıl | Case CLOSED sonrası (`closed_at + 5y`) | ISO 37002 §8.6 + KVKK Md.7 | Row-level DELETE + PG vacuum (crypto-erasure değil — WORM audit için yeter) |
| **Case: kategori + mode + timestamp (metadata)** | 5 yıl | Case CLOSED sonrası | Aynı | Aynı |
| **Case: ekler (attachments)** | Case ile aynı süre | Case DELETE trigger | Aynı | S3 Object Lock retention + full delete |
| **Access-secret hash (bcrypt/argon2)** | Case retention süresi + 1 yıl | Case CLOSED + 1 yıl | Operasyonel (fallback mailbox recovery) | Hash-only, raw secret zaten hiç saklanmıyor |
| **Reveal grant log** | 10 yıl (WORM immutable) | Reveal grant issue tarihi + 10 yıl | KVKK Md.28 + hukuki takip zamanaşımı (TBK/TCK) | **DELETE YOK** — WORM append-only; retention sonrası sink migration (S3 Glacier) |
| **WORM audit log** (case create + mailbox login + staff reply + reveal) | 10 yıl | Event kayıt tarihi + 10 yıl | Sarbanes-Oxley Sec.802 + KVKK Md.7(2) hukuki yükümlülük | **DELETE YOK** — WORM append-only; retention sonrası archived sink |
| **Basic-auth gate cookie** | Session süresi (15 dakika TTL) | Session end | Operasyonel | Cookie expire (client) + Redis-backed session store TTL |
| **Rate-limit IP hash** | 24 saat | Rate-limit window kayması | Operasyonel + GDPR minimization | Redis / in-memory expire |
| **SLO/observability metrik** (Prometheus) | 90 gün | Prometheus retention config | Operasyonel | Automatic (Prometheus retention) |
| **Alertmanager alert log** | 1 yıl | Alert firing zamanı | Operasyonel + audit | Structured log rotation + archive |
| **Access log (ingress-nginx)** | 90 gün | Log rotation | Operasyonel + IDS forensics | Log rotation + archive |
| **Backup snapshot (PG + Vault + OpenFGA)** | 90 gün (rolling) + 1 yearly annual | Snapshot tarihi | Disaster recovery + RPO | Automated + off-site encryption key rotation |
| **Legal hold data** | Hold süresi + 6 yıl (varsayılan zamanaşımı) | Legal hold trigger | KVKK Md.28 + TBK zamanaşımı | Hold sonrası standart retention süresine ekle |

## 2. Silme prosedürleri

### 2.1 Otomatik silme (batch cron)

**Case retention (case closure + 5 yıl)**:
```bash
# scripts/faz35/retention/purge-closed-cases.sh (test cluster only)
# Cron: aylık ilk gün 03:00 UTC
# Query: SELECT id FROM ethics_cases WHERE status='CLOSED'
#          AND closed_at < NOW() - INTERVAL '5 years'
#          AND NOT EXISTS (legal_hold WHERE case_id = ethics_cases.id AND released_at IS NULL)
# Row-level DELETE + WORM audit append (case_purged event)
# ArgoCD CronJob: kustomize/base/apps/etik-speak/retention-cron.yaml
```

### 2.2 Manual silme (data subject request — KVKK Md.11(1)(e))

Whistleblower **kendi bildirimini** silmek isteyebilir (unutulma hakkı):

1. `Bildirimi takip et` → `Bildirimimi sil` action (backend endpoint `DELETE /api/v1/public/ethics/reports/{id}?accessSecret=...`).
2. Backend validation:
   - Case status ≠ IN_LEGAL_HOLD.
   - Case status ≠ IN_REVEAL_GRANT (aktif reveal grant varsa reddet).
   - Access-secret exact match.
3. Onay: reporter'a "geri alınamaz, emin misiniz?" prompt.
4. Silme:
   - Case content DELETE.
   - Case metadata retention flag `PURGED_BY_REPORTER`.
   - Access-secret hash 30 gün fallback recovery + auto-purge.
   - WORM audit: `case_purged_by_reporter` event (immutable).
5. Staff bildirim: silinmiş case'in ID + timestamp (içerik yok) staff'a "silindi" olarak gösterilir; staff yanıt yazamaz.

### 2.3 Legal hold override

Legal counsel talep ederse **retention süresi askıya alınır**:

1. `POST /api/v1/ethics/cases/{id}/legal-hold` (Reveal Officer + Legal 2-of-2 imza).
2. Backend: `legal_hold` table entry (case_id + reason + held_by + held_at + released_at NULL).
3. Retention batch cron **skip** — legal_hold entry aktif olan case'ler silinmez.
4. Legal hold release: Legal counsel + Reveal Officer 2-of-2 imza + `PATCH .../legal-hold released_at=NOW()`.
5. Retention süresi hold-release tarihinden itibaren yeniden başlar (+ 6 yıl zamanaşımı puffer).

## 3. WORM audit log — immutable append

### 3.1 Storage strategy

- **PostgreSQL append-only table** (`ethics_worm_audit`) — INSERT-only trigger, UPDATE/DELETE 403.
- **Hash chain** — her satır `sha256(prev_row_hash || current_row_content)` — tampering tespit edilir.
- **DSSE signature** — her append event'i Reveal Officer'ın (ceremony) veya sistem service account'unun (routine) private key ile signed.
- **Off-site sink**: S3-compatible Object Lock (compliance mode) — 10 yıl retention.

### 3.2 Audit event kategorileri

- `case_created` — reporter POST /reports
- `case_viewed_by_staff` — staff GET /cases/{id}
- `case_status_changed` — staff transition
- `case_assigned` — atama değişimi
- `staff_reply_sent` — REPORTER_VISIBLE veya INTERNAL
- `reporter_reply_sent` — mailbox POST
- `reveal_grant_requested` — Reveal Officer başlatır
- `reveal_grant_issued` — 3-of-3 imza tamamlanır
- `reveal_grant_used` — Reveal Officer identity görüntüler
- `reveal_grant_expired` — TTL sonrası auto-reseal
- `case_purged_by_reporter` — data subject request
- `case_purged_by_retention` — batch cron
- `legal_hold_placed` / `legal_hold_released`

### 3.3 Verify

`scripts/faz35/verify-worm-audit.sh` — hash chain doğrulama + DSSE signature check + Object Lock retention check.

## 4. Crypto-erasure (isteğe bağlı, gelecek dilim)

**Şu an aktif değil** — case content plaintext DELETE ile silinir. Gelecek geliştirme (ES-4 commercial):

- Her case için ayrı encryption key (KMS / Vault Transit).
- DELETE trigger'ında key silinir → veri math olarak inaccessible.
- WORM audit log key silinmez (attribution korunur).

## 5. Compliance kontrol

### 5.1 Aylık self-audit

- Retention batch cron run status (last successful, deleted count, errors).
- Legal hold aktif entry sayısı.
- WORM audit hash chain integrity.
- Backup snapshot rotation.

### 5.2 Yıllık external audit

- Bağımsız denetim firması (SOC2 Type 2 / ISO 27001 auditor) — retention + erasure + reveal + audit chain.
- Bulgular → board issue (Project #8) + fix PR + follow-up audit.

## 6. İhlal durumu

Retention veya erasure süresi aşımı tespit edilirse:

1. **On-call notification** (SEV2 alert).
2. **Post-mortem** (`docs/postmortems/faz35-YYYY-MM-DD-retention-breach.md`).
3. **KVKK / EU DPA bildirimi** (72 saat içinde, GDPR Art.33 uyumlu).
4. **Root cause fix** — batch cron / manuel silme akışında hangi noktada arıza.
5. **Compensating control** — geciken silme derhal manual.

## 7. Yönetim

Bu policy `docs/legal/faz35-retention-policy.md` canonical — Legal counsel + DPO tarafından yıllık review + revize edilir. Değişiklikler:

- Board issue Project #8'de dokümante edilir.
- PR review Legal counsel + DPO (2-of-2 imza).
- Değişiklik log bu doküman sonunda.

## 8. Değişiklik log

- **v1.0** (2026-07-21) — İlk yayın; Faz 35 test-only phase sonrası (ES-313 öncesi hazırlık).

## Referanslar

- `docs/legal/faz35-privacy-notice-tr.md` — reporter-facing aydınlatma metni
- `docs/runbooks/RB-faz35-legal-reveal-request.md` — reveal ceremony
- `docs/runbooks/RB-faz35-incident-response.md` — retention breach severity
- Backend implementation: `ethics-service/src/main/java/com/example/ethics/model/AuditOutbox.java` (WORM sink), `ethics-service/src/main/java/com/example/ethics/service/RetentionService.java` (Codex spawn task #378f775d ile).
- Board: [Project #8](https://github.com/users/Halildeu/projects/8) — ES-006, ES-208, ES-302, ES-303
