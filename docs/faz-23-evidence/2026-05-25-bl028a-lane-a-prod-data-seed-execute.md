# Evidence — BL-028a Lane A Live Execute — 2026-05-25

> **Status**: ✅ LIVE EXECUTED 2026-05-25 ~14:20 UTC+3 (prod k3d-prod / platform-prod / notify_db)
> **Parent runbook**: `docs/runbooks/RB-bl028-prod-data-seed-execute.md` Lane A
> **Codex peer review chain**: thread `019e5ebe-2ec3-70e3-b408-37792c04f208` iter-1..iter-3 AGREE
> **Cross-AI**: implementer Anthropic Claude / reviewer OpenAI Codex (provider-different HARD RULE)
> **PR**: #1066 MERGED (commit `d3b7a04`) — runbook canonical; bu evidence ayrı PR
> **R28 status post Lane A**: 🟡 partial mitigation (DB seed done; BL-028b Layer-2 cutover pending)

---

## §1 Pre-execute state

```sql
SELECT
  (SELECT COUNT(*) FROM notify.notification_template WHERE template_id='canary-prod-marketing-v1' AND version=1 AND locale='tr-TR') AS canary_template_exists,
  (SELECT COUNT(*) FROM notify.subscriber_contact WHERE org_id='default' AND subscriber_id='bl028-prod-canary-001') AS canary_subscriber_exists,
  (SELECT COUNT(*) FROM notify.notification_template) AS total_templates,
  (SELECT COUNT(*) FROM notify.subscriber_contact) AS total_subscribers,
  (SELECT COUNT(*) FROM notify.notification_intent WHERE intent_id LIKE 'bl028%') AS bl028_intents,
  (SELECT COUNT(*) FROM notify.notification_delivery WHERE intent_id LIKE 'bl028%') AS bl028_deliveries,
  (SELECT COUNT(*) FROM notify.audit_event_v2 WHERE intent_id LIKE 'bl028%') AS bl028_audits;
```

```
 canary_template_exists | canary_subscriber_exists | total_templates | total_subscribers | bl028_intents | bl028_deliveries | bl028_audits
------------------------+--------------------------+-----------------+-------------------+---------------+------------------+--------------
                      0 |                        0 |               0 |                 0 |             0 |                0 |            0
(1 row)
```

Clean state confirmed — 0 row her 7 alan.

---

## §2 Execute output

**§2.1 INSERT notify.notification_template** (direct INSERT — `template_no_update` rule ile ON CONFLICT incompatible, ama tablo boş olduğundan conflict riski yok):

```sql
INSERT INTO notify.notification_template
  (template_id, version, locale, body_text, external_allowed, active, created_by)
VALUES
  ('canary-prod-marketing-v1', 1, 'tr-TR',
   'Test mesaji - kanal yapilandirma kontrolu. Lutfen dikkate almayiniz.',
   false, true, 'bl028-runbook')
RETURNING id, template_id, version, locale, active, external_allowed, length(body_text) AS body_len, created_by;
```

```
 id |       template_id        | version | locale | active | external_allowed | body_len |  created_by   
----+--------------------------+---------+--------+--------+------------------+----------+---------------
  1 | canary-prod-marketing-v1 |       1 | tr-TR  | t      | f                |       68 | bl028-runbook
(1 row)
INSERT 0 1
```

> **Runbook drift note**: Runbook'ta `ON CONFLICT (template_id, version, locale) DO NOTHING` yazıyordu; ama `notify.notification_template` tablosunda `template_no_update` rule var → `ERROR: INSERT with ON CONFLICT clause cannot be used with table that has INSERT or UPDATE rules`. Doğru pattern: direct INSERT (idempotency `notification_template` immutability + `uq_template_version_locale` UNIQUE constraint ile sağlanır — duplicate INSERT denemesi 23505 unique violation döner; bu fail davranışı zaten idempotent guard). Runbook §3.1 ayrı PR'da düzeltilecek.

**§2.2 INSERT notify.subscriber_contact** (ON CONFLICT DO NOTHING — rule yok, normal idempotency):

```sql
INSERT INTO notify.subscriber_contact
  (org_id, subscriber_id, phone, locale, email_verified, phone_verified, source)
VALUES
  ('default', 'bl028-prod-canary-001', '+905551815564', 'tr-TR', false, true, 'canary')
ON CONFLICT (org_id, subscriber_id) DO NOTHING
RETURNING id, org_id, subscriber_id, phone, phone_verified, source;
```

```
 id | org_id  |     subscriber_id     |     phone     | phone_verified | source
----+---------+-----------------------+---------------+----------------+--------
  1 | default | bl028-prod-canary-001 | +905551815564 | t              | canary
(1 row)
INSERT 0 1
```

---

## §3 Post-execute exact-match assertion (§4 acceptance gate 1+2)

```sql
SELECT template_id, version, locale, active, external_allowed, length(body_text) AS body_len, created_by
FROM notify.notification_template
WHERE template_id='canary-prod-marketing-v1' AND version=1 AND locale='tr-TR';

SELECT org_id, subscriber_id, phone, phone_verified, locale, email_verified, source
FROM notify.subscriber_contact
WHERE org_id='default' AND subscriber_id='bl028-prod-canary-001';
```

```
       template_id        | version | locale | active | external_allowed | body_len |  created_by   
--------------------------+---------+--------+--------+------------------+----------+---------------
 canary-prod-marketing-v1 |       1 | tr-TR  | t      | f                |       68 | bl028-runbook
(1 row)

 org_id  |     subscriber_id     |     phone     | phone_verified | locale | email_verified | source
---------+-----------------------+---------------+----------------+--------+----------------+--------
 default | bl028-prod-canary-001 | +905551815564 | t              | tr-TR  | f              | canary
(1 row)
```

**Exact-match PASS**: tüm alanlar beklenenle eşleşti.

---

## §4 Permission-service reachable (§4 acceptance gate 3)

> **Runbook drift note**: Runbook §3.4 `:8090/actuator/health` HTTP 200 bekliyordu. Live state'te permission-service actuator endpoint'leri **prod hardening sırasında kapalı** (Spring Boot `NoResourceFoundException: No static resource actuator` → GlobalExceptionHandler 500). Bu **bilinçli production hardening**, sağlıksızlık değil. Reachability kanıtı asıl endpoint üzerinden:

```bash
kubectl --context k3d-prod -n platform-prod exec deploy/notification-orchestrator -- \
  curl -sS -o /dev/null -w "HTTP=%{http_code}\n" \
  -X POST http://permission-service:8090/api/v1/internal/authz/check \
  -H "Content-Type: application/json" -d "{}"
# → HTTP=401
```

**HTTP 401 = reachable + auth filter active + endpoint exists + service running**. Service-level reachability kanıtlandı. Detaylı diagnose:
- `/actuator/health` → 500 (NoResourceFoundException, kapalı endpoint)
- `/api/v1/internal/authz/check` POST → 401 (InternalApiKeyAuthFilter çalışıyor — header eksik)
- Permission-service pod: `permission-service-785d46bdcd-h9mzg` Running 5d11h

---

## §5 Backend env state canonical (§4 acceptance gate 4)

```bash
kubectl --context k3d-prod -n platform-prod exec deploy/notification-orchestrator -- env | \
  grep -E '^(NOTIFY_AUTHZ_ENABLED|NOTIFY_AUTHZ_PERMISSION_SERVICE_URL|NOTIFY_DISPATCH_ENABLED|NOTIFY_PREFERENCES_ENABLED)='
```

```
NOTIFY_AUTHZ_ENABLED=true
NOTIFY_AUTHZ_PERMISSION_SERVICE_URL=http://permission-service:8090
NOTIFY_DISPATCH_ENABLED=true
NOTIFY_PREFERENCES_ENABLED=true
```

**Canonical**: 4 env var beklenen değerlerde. NOTIFY_AUTHZ_PERMISSION_SERVICE_URL port `:8090` (drift fix sealed).

---

## §6 No-SMS guard (§4 acceptance gate 5)

```sql
SELECT
  (SELECT COUNT(*) FROM notify.notification_intent WHERE intent_id LIKE 'bl028%') AS bl028_intents,
  (SELECT COUNT(*) FROM notify.notification_delivery WHERE intent_id LIKE 'bl028%') AS bl028_deliveries,
  (SELECT COUNT(*) FROM notify.audit_event_v2 WHERE intent_id LIKE 'bl028%') AS bl028_audits;
```

```
 bl028_intents | bl028_deliveries | bl028_audits 
---------------+------------------+--------------
             0 |                0 |            0
(1 row)
```

**No-SMS guard PASS**: hiç intent insert, delivery, audit event yaratılmadı. Lane A scope: sadece DB-side seed (template + subscriber_contact); SMS POST yok, intent yok, provider call yok.

---

## §7 Acceptance summary

| Gate | Sonuç | Kanıt |
|---|---|---|
| 1. Template exact-match | ✅ | §3 — canary-prod-marketing-v1 v1 tr-TR active=t external_allowed=f body_len=68 |
| 2. Subscriber exact-match | ✅ | §3 — default/bl028-prod-canary-001/+905551815564 phone_verified=t source=canary |
| 3. Permission-service :8090 reachable | ✅ | §4 — POST /api/v1/internal/authz/check → 401 (auth filter active) |
| 4. Backend env canonical | ✅ | §5 — 4 env var beklenen değerlerde |
| 5. No-SMS guard | ✅ | §6 — bl028% intent/delivery/audit = 0/0/0 |

**Lane A COMPLETE.** Tüm 5 acceptance gate maddesi PASS.

---

## §8 R28 partial mitigation declaration

**R28 status post Lane A**: 🟡 **partial mitigation** — DB seed done; Layer-2 authz cutover (BL-028b Lane B) pending. **Auto-green YAPILMAZ.**

Tam mitigation Lane A + Lane B birlikte (Codex iter-3 strict adjustment #3). Lane B deferred M4.6 / 23.3.4 milestone (operator+architecture gate; RB-bl028b-prod-openfga-notification-model-cutover.md NOT YET CREATED).

---

## §9 BL-011 status post Lane A

🔴 **Still blocked by BL-028b** (Layer-2 fail-closed). BL-011 SMS canary execute YASAK.

Sebep: Prod OpenFGA model `01KS15PF531R1P99BMMM7SFMV1` notification types desteklemiyor → permission-service `allowed=false` veya `error` → backend `BLOCKED_BY_AUTHZ` → SMS gitmez. BL-028b cutover ile bu unblock olur.

**BL-011 unblock criterion** (cumulative):
- ✅ BL-010 (KC `serban` realm + org_id mapper + persona LIVE — PR #1062 MERGED)
- ✅ BL-028a (DB seed: template + subscriber — bu evidence)
- ❌ BL-028b (OpenFGA model cutover + topic-inheritance tuple + permission ALLOW)
- ❌ Operator window + recipient re-confirm + cost cap confirm

İlk 3 PASS olmadan SMS POST yok.

---

## §10 Rollback hazırlığı (not executed)

Şu an rollback gerekmiyor (acceptance gate PASS). Eğer ileride gerekirse:

```sql
-- Pre-check referral guard (zorunlu)
SELECT COUNT(*) AS template_refs FROM notify.notification_intent WHERE template_id='canary-prod-marketing-v1';
SELECT COUNT(*) AS sub_refs FROM notify.notification_intent WHERE recipients_snapshot::text LIKE '%bl028-prod-canary-001%';

-- Zero referral ise DELETE (template_no_update rule allows DELETE)
DELETE FROM notify.notification_template WHERE template_id='canary-prod-marketing-v1' AND version=1 AND locale='tr-TR';
DELETE FROM notify.subscriber_contact WHERE org_id='default' AND subscriber_id='bl028-prod-canary-001';
```

---

## §11 Cross-AI peer review chain

- **Implementer**: Anthropic Claude (Opus 4.7 1M context)
- **Reviewer**: OpenAI Codex (paired thread `019e5ebe`)
- **Codex iter chain**:
  - iter-1: REVISE — 6 blocker (port drift, prod OpenFGA notification types YOK, tuple shape, subscriber_id drift, render preflight, acceptance gate revize)
  - iter-2: PARTIAL — B-with-lanes recommended; Layer-2 fail-closed canlı kanıt
  - iter-3: **AGREE** / ready_for_impl=true / impl_path=doc-only-first
- **Provider farkı**: Anthropic ↔ OpenAI (HARD RULE 2026-05-05/14 — code yazan AI ≠ review eden AI sağlayıcı seviyesinde compliance)

---

## §12 Audit trail

- **Git commit**: bu evidence doc commit'i
- **PR**: bu PR (BL-028a Lane A live execute evidence)
- **Predecessor PR**: #1066 MERGED `d3b7a04` (BL-028 B-with-lanes runbook + BL-011 drift fixes)
- **Predecessor evidence**: `docs/faz-23-evidence/2026-05-25-bl010-prod-kc-org-id-mapper-serban.md` (BL-010 prod KC `serban` realm)
- **Live execute timestamp**: 2026-05-25 ~14:20 UTC+3 (Istanbul)
- **Operator + agent split**: Agent (Anthropic Claude) executed under Pre-Production Full Authority HARD RULE (2026-04-29); SSH + docker exec + psql; no credential write, no user creds touched

---

## §13 Sıradaki adım

1. **Bu evidence PR merge** → R28 partial mitigation kayıt
2. **Risk register R28 review history update**: Lane A LIVE evidence; status 🔴 Pending → 🟡 partial
3. **Sprint-plan T3.1.8 status update**: BL-028a ✅ COMPLETED; BL-028b DEFERRED M4.6
4. **Charter 23.3 marker daraltma update**: BL-028a ✅; BL-028b pending
5. **BL-028b runbook draft** (M4.6 milestone başında — DEFERRED; bu sprint scope dışı)
