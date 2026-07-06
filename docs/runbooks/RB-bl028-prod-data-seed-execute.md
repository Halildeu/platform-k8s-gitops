# RB-bl028-prod-data-seed-execute — Prod notify_db Functional Data Seed (B-with-lanes pattern)

> **Status**: ✅ **Lane A + Lane B LIVE EXECUTED 2026-05-25 — B-with-lanes complete + BL-011 LIVE DELIVERED**. Lane A evidence `docs/faz-23-evidence/2026-05-25-bl028a-lane-a-prod-data-seed-execute.md`; Lane B evidence `docs/faz-23-evidence/2026-05-25-bl028b-lane-b-prod-openfga-cutover-evidence.md`; BL-011 evidence `docs/faz-23-evidence/2026-05-25-bl011-prod-sms-canary-live.md` (new prod model `01KSFFK9K3V43DD211Z79K3FYA` 15 type; provider_msg_id `jetsms-2605251959362908914` DELIVERED 71s DLR).
> **Parent**: BL-028 (M4.5 / 23.3.3 — Prod notify functional data + authz preflight)
> **Pattern**: B-with-lanes (Codex 019e5ebe iter-2 PARTIAL + iter-3 AGREE)
> **Codex peer review chain**: thread `019e5ebe-2ec3-70e3-b408-37792c04f208` iter-1 REVISE → iter-2 PARTIAL → iter-3 AGREE
> **Cross-AI**: implementer Anthropic Claude / reviewer OpenAI Codex (HARD RULE 2026-05-05/14 compliance)
> **Recipient (Lane A seed)**: `+905551815564` (kullanıcı 2026-05-25 explicit)
> **No-SMS guarantee**: bu runbook'taki HİÇBİR adım SMS göndermez, `notification_intent` insert etmez, provider çağırmaz

---

## 1. Bağlam — Discovery 2026-05-25

2026-05-20'de M4 prod cutover INFRASTRUCTURE LIVE:
- Backend deploy ✅, pod ready ✅
- JetSMS prod creds ESO-injected ✅
- Vault paths canonical ✅
- BL-010 KC `serban` realm `notify-canary` client scope + `org_id` mapper LIVE (PR #1062 MERGED)

ANCAK BL-011 prod SMS canary execute preflight'ı sırasında keşfedildi (2026-05-25):

```
SELECT
  (SELECT COUNT(*) FROM notify.notification_template WHERE active=true) AS active_templates,    -- 0
  (SELECT COUNT(*) FROM notify.notification_template WHERE active=true AND body_text IS NOT NULL) AS sms_capable, -- 0
  (SELECT COUNT(*) FROM notify.subscriber_contact) AS subscribers,                              -- 0
  (SELECT COUNT(*) FROM notify.subscriber_contact WHERE phone_verified=true) AS verified_phones, -- 0
  (SELECT COUNT(*) FROM notify.notification_intent) AS intents,                                 -- 0
  (SELECT COUNT(*) FROM notify.notification_delivery) AS deliveries,                            -- 0
  (SELECT COUNT(*) FROM notify.audit_event_v2) AS audit_events;                                 -- 0
```

→ Prod notify_db **tamamen boş**; infrastructure LIVE ama functional data layer henüz seed edilmedi. Risk register R28 NEW (PR #1064 MERGED).

Ek olarak (Codex iter-2 absorb):
- **Prod OpenFGA model `01KS15PF531R1P99BMMM7SFMV1`** sadece D35 ERP types içeriyor (action/branch/company/module/organization/project/report/report_group/user/warehouse). **Notification types (subscriber, notification_topic, template) prod'a HİÇ cutover EDİLMEDİ**.
- Layer-2 fail-closed: backend `AuthzClient` non-200/exception → `deny("authz_<code>")`; permission-service notification types desteklemediği için `allowed=false` → notification `BLOCKED_BY_AUTHZ` → SMS gitmez.

Sonuç: BL-011 SMS canary execute için **iki gate** gerekiyor — DB seed VE OpenFGA notification model cutover. Bu yüzden **B-with-lanes** pattern.

---

## 2. Scope split — B-with-lanes

| Lane | ID | Scope | Doable by | Milestone | Status |
|---|---|---|---|---|---|
| **A** | BL-028a | DB-side functional seed (template + subscriber_contact) | Agent (SSH + psql via docker exec) | M4.5 / 23.3.3a | READY-FOR-EXECUTION post-merge |
| **B** | BL-028b | Prod OpenFGA notification model cutover + tuple write | Operator + architecture gate | M4.6 / 23.3.4 | DEFERRED — ayrı RB gerek |

**BL-011 unblock criterion**: Lane A + Lane B ikisi de PASS olmadan SMS POST YASAK. Lane A tek başına BL-011'i unblock ETMEZ (Layer-2 fail-closed).

---

## 3. Lane A execute — DB-side functional seed (post-merge live-action)

> **PRECONDITION**: Bu runbook MERGE edildikten sonra ayrı bir turda execute edilir. Board claim + live-action yetki notu ayrı kapı. Bu PR'da canlı SQL execute YOK.

### 3.0 Preflight — read-only state confirm

```bash
NS=platform-prod
POD=$(ssh halil@staging-sw "kubectl --context k3d-prod -n $NS get pod -l app=notification-orchestrator -o jsonpath='{.items[0].metadata.name}'")

# Backend env state (canonical 2026-05-25)
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec $POD -- env" | grep -E '^(NOTIFY_AUTHZ_ENABLED|NOTIFY_AUTHZ_PERMISSION_SERVICE_URL|NOTIFY_DISPATCH_ENABLED|NOTIFY_PREFERENCES_ENABLED)='
```

**Beklenen** (Codex iter-2 doğrulandı, canlı 2026-05-25):
- `NOTIFY_AUTHZ_ENABLED=true`
- `NOTIFY_AUTHZ_PERMISSION_SERVICE_URL=http://permission-service:8090` (port :8090 — :8094 drift fix BL-011 RB'de yapıldı)
- `NOTIFY_DISPATCH_ENABLED=true`
- `NOTIFY_PREFERENCES_ENABLED=true`

Eğer drift varsa: execute YASAK, önce env senkronu.

### 3.1 INSERT notify.notification_template

> **Drift fix 2026-05-25 Lane A live execute**: `template_no_update` rule (V1__init_notify_schema.sql:103) `INSERT ... ON CONFLICT` ile incompatible — PostgreSQL hata: `INSERT with ON CONFLICT clause cannot be used with table that has INSERT or UPDATE rules`. Doğru pattern: **direct INSERT** (idempotency `uq_template_version_locale` UNIQUE constraint ile sağlanır — duplicate denemesi 23505 unique violation fail; bu davranış idempotent guard rolü).

```sql
-- Direct INSERT (ON CONFLICT YOK — template_no_update rule incompatibility)
INSERT INTO notify.notification_template
  (template_id, version, locale, subject, body_html, body_text, external_allowed, active, created_by)
VALUES
  ('canary-prod-marketing-v1',
   1,
   'tr-TR',
   NULL,                                                                              -- subject (SMS-only)
   NULL,                                                                              -- body_html (SMS-only)
   'Test mesaji - kanal yapilandirma kontrolu. Lutfen dikkate almayiniz.',           -- body_text (PII yok, KVKK uyumlu)
   false,                                                                            -- external_allowed=false (subscriber path)
   true,                                                                             -- active=true
   'bl028-runbook')
RETURNING id, template_id, version, locale, active, external_allowed, length(body_text) AS body_len, created_by;
```

> **Immutability note**: `template_no_update` rule var (V1__init_notify_schema.sql:103). DO UPDATE yapılamaz. Rollback için: ya DELETE (zero referral guard sonrası) ya yeni version (v2 oluştur). Re-run YASAK (unique violation alır); idempotency için önce SELECT exact-match check, sonra INSERT pattern (Lane A re-execute durumunda).

### 3.2 INSERT notify.subscriber_contact

```sql
-- Idempotent via ON CONFLICT DO NOTHING (uq_subscriber_contact_org_subscriber: org_id+subscriber_id)
INSERT INTO notify.subscriber_contact
  (org_id, subscriber_id, email, phone, locale, email_verified, phone_verified, source)
VALUES
  ('default',
   'bl028-prod-canary-001',                  -- canonical (drift fix: bl011-prod-canary-001 → bl028-prod-canary-001)
   NULL,                                     -- email not used for SMS lane
   '+905551815564',                          -- E.164 format
   'tr-TR',
   false,                                    -- email_verified=false (no email)
   true,                                     -- phone_verified=true
   'canary')                                 -- source identifier for cleanup tracking
ON CONFLICT (org_id, subscriber_id) DO NOTHING;
```

> **Conflict guard**: Aynı `(org_id, subscriber_id)` farklı phone/verified/source ile varsa **kör update YOK** — fail edip remediation iste. Sadece aynı canary source için guarded update düşünülebilir (ayrı UPDATE sorgusu — bu runbook'ta YOK).

### 3.3 EXACT-MATCH post-verify SELECT

Post-execute kanıtı:

```sql
-- Template exact-match assertion
SELECT template_id, version, locale, active, external_allowed, length(body_text) AS body_len, created_by
FROM notify.notification_template
WHERE template_id='canary-prod-marketing-v1' AND version=1 AND locale='tr-TR';
-- Beklenen: 1 row, active=t, external_allowed=f, body_len=64, created_by='bl028-runbook'

-- Subscriber exact-match assertion
SELECT org_id, subscriber_id, phone, phone_verified, locale, email_verified, source
FROM notify.subscriber_contact
WHERE org_id='default' AND subscriber_id='bl028-prod-canary-001';
-- Beklenen: 1 row, phone='+905551815564', phone_verified=t, email_verified=f, source='canary'
```

Eğer assertion fail ederse: rollback (§5) + execute repeat.

### 3.4 Permission-service URL reachable check (no notification check)

> **Drift fix 2026-05-25 Lane A live execute**: Prod permission-service `/actuator/*` endpoint'leri **prod hardening sırasında kapalı** (Spring `NoResourceFoundException` → GlobalExceptionHandler 500). Bu **bilinçli production hardening**, sağlıksızlık değil. Reachability kanıtı asıl endpoint üzerinden (auth filter response).

```bash
# Permission-service service-level reachable kanıtı (actuator/health prod'da kapalı)
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/notification-orchestrator -- \
  curl -sS -o /dev/null -w 'HTTP=%{http_code}\n' \
  -X POST http://permission-service:8090/api/v1/internal/authz/check \
  -H 'Content-Type: application/json' -d '{}'"
# Beklenen: HTTP=401 (InternalApiKeyAuthFilter active, endpoint exists, service running)
```

**HTTP 401 = reachable + auth filter active + endpoint exists + service running**. Bu canonical reachability eşiği. `/actuator/health` kullanma — prod'da kapalı.

> **Notification check YAPILMAZ**: Prod OpenFGA model notification types desteklemiyor (BL-028b deferred). Eğer şimdi `POST /api/v1/internal/authz/check` valid auth + payload ile denenirse `allowed=false` veya `error` döner — bu BEKLENEN durumdur, Lane A acceptance'ı etkilemez. Bu sadece **reachability proof** (auth filter çalışıyor mu) için kullanılır.

---

## 4. Acceptance gate — Lane A (post-execute checklist, placeholder)

> **Bu doc-only PR'da kanıt YOK**. Aşağıdaki maddeler Lane A live execute turunda evidence doc PR'ında doldurulur.

- [ ] §3.0 preflight env state canonical (4 env var doğru) — kanıt: `kubectl exec env` output paste
- [ ] §3.1 template INSERT executed, post-verify SELECT (§3.3) 1 row exact-match
- [ ] §3.2 subscriber_contact INSERT executed, post-verify SELECT (§3.3) 1 row exact-match
- [ ] §3.4 permission-service `:8090/actuator/health` HTTP 200
- [ ] No SMS POST, no intent insert, no provider call — audit-level evidence:
  - `SELECT COUNT(*) FROM notify.notification_intent WHERE intent_id LIKE 'bl028%'` → 0
  - `SELECT COUNT(*) FROM notify.notification_delivery WHERE intent_id LIKE 'bl028%'` → 0
  - `SELECT COUNT(*) FROM notify.audit_event_v2 WHERE intent_id LIKE 'bl028%'` → 0

**R28 status post Lane A**: 🟡 **partial mitigation** — DB seed done; Layer-2 authz cutover (Lane B / BL-028b) pending. Auto-green YAPILMAZ.

**BL-011 status post Lane A**: 🔴 **still blocked by BL-028b** (Layer-2 fail-closed). BL-028b complete olmadan BL-011 execute YASAK.

---

## 5. Rollback (Lane A only — only if zero referral)

> **Pre-check**: Rollback öncesi referral guard zorunlu.

```sql
-- Template referral count
SELECT COUNT(*) AS template_intent_refs FROM notify.notification_intent WHERE template_id='canary-prod-marketing-v1';
SELECT COUNT(*) AS template_delivery_refs FROM notify.notification_delivery WHERE intent_id IN (
  SELECT intent_id FROM notify.notification_intent WHERE template_id='canary-prod-marketing-v1'
);

-- Subscriber referral count
SELECT COUNT(*) AS sub_intent_refs FROM notify.notification_intent
WHERE recipients_snapshot::text LIKE '%bl028-prod-canary-001%';
SELECT COUNT(*) AS sub_pref_refs FROM notify.subscriber_preference WHERE subscriber_id='bl028-prod-canary-001';
SELECT COUNT(*) AS sub_audit_refs FROM notify.audit_event_v2
WHERE intent_id IN (SELECT intent_id FROM notify.notification_intent WHERE recipients_snapshot::text LIKE '%bl028-prod-canary-001%');
```

**Zero referral ise** (template_no_update rule template için DELETE-then-INSERT pattern; subscriber için direct DELETE safe):

```sql
-- Rollback template (zero referral kanıtı sonrası)
DELETE FROM notify.notification_template
WHERE template_id='canary-prod-marketing-v1' AND version=1 AND locale='tr-TR';

-- Rollback subscriber_contact (zero referral kanıtı sonrası)
DELETE FROM notify.subscriber_contact
WHERE org_id='default' AND subscriber_id='bl028-prod-canary-001';
```

> **Referral > 0 ise**: DELETE YAPMA. Yeni version (template v2) veya yeni subscriber_id (`bl028-prod-canary-002`) yarat. Bu durum operator escalation gerektirir.

---

## 6. Lane B (BL-028b — DEFERRED, non-executable in this runbook)

**Scope** (high-level reference only):

1. Prod OpenFGA notification model cutover:
   - Source: `docs/notify/openfga-notification-model.dsl` (notification + ERP types)
   - Target: `POST http://openfga:8080/stores/01KPXCVBHCY2TQ6YHVK009NS1C/authorization-models` → yeni prod model_id ULID
   - ERP regression guard: 10 mevcut type aynı kalmalı

2. Permission-service runtime selector update:
   - Vault canonical patch (test/prod blast-radius topology kararı)
   - ESO sync + permission-service rollout restart + pod env verify

3. Tuple write (topic-inheritance):
   - `notification_topic:marketing.campaign#can_receive@subscriber:bl028-prod-canary-001`
   - `template:canary-prod-marketing-v1#topic@notification_topic:marketing.campaign`

4. Permission check kanıtı (direct OpenFGA + permission-service internal):
   - Direct: `POST /stores/{store_id}/check`
   - Internal: `POST permission-service:8090/api/v1/internal/authz/check` (X-Internal-Api-Key)
   - Final acceptance: `{"allowed": true}` via permission-service internal

5. Rollback strategy:
   - Tuple delete payload hazır
   - Permission-service env model_id geri alma (eski `01KS15PF531R1P99BMMM7SFMV1`)
   - OpenFGA model revision append-only kalır

**Triggers for activation**: M4.6 / 23.3.4 milestone start. Önkoşullar:
- BL-028a Lane A acceptance kanıtı LIVE
- Operator + architecture gate açıldı (Vault topology kararı, prod cutover yetkisi)
- ERP regression smoke seti hazır

**NOT executable here** — ayrı runbook **READY** (Codex 019e5ee5 iter-2 AGREE): [`docs/runbooks/RB-bl028b-prod-openfga-notification-model-cutover.md`](RB-bl028b-prod-openfga-notification-model-cutover.md) (READY-FOR-EXECUTION post M4.6 operator window). 12 section + 5 ExternalSecret consumer inventory + canonical JSON ERP semantic diff + 10 hard acceptance gate.

---

## 7. Evidence doc template (post-Lane-A live execute için placeholder)

> Lane A live execute turunda `docs/faz-23-evidence/<YYYY-MM-DD>-bl028a-prod-data-seed-execute.md` ile evidence doc yazılır. İçerik şablonu:

```markdown
# Evidence — BL-028a Lane A Live Execute — <YYYY-MM-DD>

## §1 Pre-execute state
[psql output: 7-line COUNT(*) — hepsi 0]

## §2 Execute output
[psql INSERT output: 2 row inserted, 0 conflict]

## §3 Post-execute exact-match assertion
[psql SELECT output: template 1 row, subscriber 1 row, all fields match]

## §4 Permission-service reachable
[curl :8090/actuator/health output: HTTP 200]

## §5 No-SMS guard
[psql intent/delivery/audit COUNT(*) for intent_id LIKE 'bl028%' = 0]

## §6 R28 partial mitigation declaration
[status: partial; Lane A done; Lane B pending]

## §7 BL-011 status post Lane A
[status: still blocked by BL-028b; SMS POST YASAK]

## §8 Cross-AI peer review
[Codex iter chain references]

## §9 Audit trail
[git commit, PR #, board issue, operator + agent split note]
```

---

## Referanslar

- BL-011 RB: `docs/runbooks/RB-bl011-prod-sms-canary-execute.md` — prereq #0 update post this merge
- Risk register R28: `docs/notify/risk-register.md`
- Closure handoff backlog: `docs/runbooks/RB-faz-23-v1-closure-operator-handoff.md`
- Charter: `docs/runbooks/RB-faz-23-charter.md`
- Sprint plan: `docs/notify/sprint-plan.md` (Tier 3 BL-028 two-lane note)
- OpenFGA notification model DSL: `docs/notify/openfga-notification-model.dsl`
- BL-028b future RB: `docs/runbooks/RB-bl028b-prod-openfga-notification-model-cutover.md` (NOT YET CREATED — M4.6 milestone start)
- BL-004 evidence: `docs/faz-23-evidence/2026-05-24-bl004-prod-authz-internal-api-key-align.md` (prod permission-service internal_api_key align)
- BL-010 evidence: `docs/faz-23-evidence/2026-05-25-bl010-prod-kc-org-id-mapper-serban.md` (prod KC `serban` realm mapper LIVE)
- Codex peer review thread: `019e5ebe-2ec3-70e3-b408-37792c04f208` (iter-1 REVISE → iter-2 PARTIAL → iter-3 AGREE)
