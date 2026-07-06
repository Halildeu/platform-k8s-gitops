# Evidence — BL-011 Prod SMS Canary LIVE — 2026-05-25

> **Status**: ✅ LIVE EXECUTED 2026-05-25 16:58:45 UTC (prod k3d-prod / platform-prod)
> **Outcome**: 🎉 **Gerçek SMS DELIVERED** to `+905551815564` via JetSMS (provider_msg_id `jetsms-2605251959362908914`); DLR cycle 71 saniye
> **Parent runbook**: `docs/runbooks/RB-bl011-prod-sms-canary-execute.md`
> **Predecessor chain**: BL-010 ✅ + BL-028a ✅ + BL-028b ✅ (all LIVE 2026-05-25)
> **Codex peer review chain**: Lane B context inheritance — `019e5ee5` iter-2 AGREE (BL-028b runbook); BL-011 unblock criterion karşılandı
> **Cross-AI**: implementer Anthropic Claude / reviewer OpenAI Codex (HARD RULE 2026-05-05/14)
> **PR series**: #1066 (B-with-lanes) + #1067 (Lane A) + #1068 (Lane B RB) + #1069 (Lane B LIVE) MERGED; bu PR = BL-011 LIVE evidence

---

## §1 Bağlam — BL-011 unblock criterion

| Prereq | Status | PR |
|---|---|---|
| BL-010 (KC `serban` realm + org_id mapper + persona) | ✅ LIVE | #1062 |
| BL-028a (DB seed: template + subscriber) | ✅ LIVE | #1067 (commit `aa84d0a`) |
| BL-028b (Prod OpenFGA notification model cutover) | ✅ LIVE | #1069 (commit `de6c369`) |
| Operator window scheduled | ✅ Kullanıcı explicit "kalan işi tamamla" | AskUserQuestion 2026-05-25 |
| Recipient re-confirm | ✅ `+905551815564` | Daha önce kullanıcı 2026-05-25 onay |
| Cost cap ≤3 (max_count=1) | ✅ 1 SMS hard cap | RB §2 Q6 |

Tüm 6 trigger condition PASS. BL-011 execute scope açıldı.

---

## §2 Pre-execute prereq verify (5/5 PASS)

### §2.1 Backend env canonical
```
NOTIFY_AUTHZ_ENABLED=true
NOTIFY_DISPATCH_ENABLED=true
NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER=jetsms
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL=VF
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_ALLOWED=VF,VFO
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS=  (blank — R24 workaround)
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_MAX_LENGTH=160
```

### §2.2 Template canary ready
```
template_id              | version | locale | active | body_len
-------------------------+---------+--------+--------+----------
canary-prod-marketing-v1 |       1 | tr-TR  | t      |       68
```

### §2.3 Canary subscriber ready
```
org_id  | subscriber_id         | phone         | phone_verified | source
--------+-----------------------+---------------+----------------+--------
default | bl028-prod-canary-001 | +905551815564 | t              | canary
```

### §2.4 Permission-service internal ALLOW (Layer-2 LIVE post BL-028b)
```json
POST /api/v1/internal/authz/check (X-Internal-Api-Key)
→ {"reason":"tuple_match","allowed":true}
```

### §2.5 Pre-execute metric baseline
```
notify_org_access_match_total{source="none"} 1166.0
notify_org_access_match_total{source="org_id"}  — not present (baseline)
```

---

## §3 Execute (1 SMS Senaryo B — marketing.campaign)

### §3.1 JWT mint (canary persona)

```bash
# First attempt — JWT expired during diagnostic probe (5dk Keycloak default)
# Second attempt: fresh mint @ 16:58:45 UTC

JWT len: 1627
Claims:
{
  "iss": "https://ai.acik.com/realms/serban",
  "aud": ["user-service","variant-service","permission-service","account"],
  "sub": "2063e0e9-3f2d-4016-b348-4416e99acaed",
  "preferred_username": "notify-canary-org-prod-default",
  "org_id": "default",                            // ← BL-010 mapper LIVE kanıt
  "scope": "openid notify-canary profile email"
}
```

> **Lesson learned**: Keycloak default access token lifespan 5 dakika; canary execute için fresh mint → immediate POST disipline gerek.

### §3.2 POST /api/v1/notify/intents

```bash
POST https://ai.acik.com/api/v1/notify/intents
Authorization: Bearer <fresh JWT>
Content-Type: application/json

{
  "intentId": "bl011b-20260525-165845",
  "idempotencyKey": "bl011b-20260525-165845",
  "orgId": "default",
  "topicKey": "marketing.campaign",
  "severity": "info",
  "dataClassification": "commercial",
  "recipients": [{"type": "subscriber", "subscriberId": "bl028-prod-canary-001"}],
  "template": {"templateId": "canary-prod-marketing-v1", "version": 1, "locale": "tr-TR"},
  "channels": ["sms"],
  "payload": {"body": "BL-011 prod canary. Test mesajidir, gormezden geliniz."},
  "correlationId": "bl011b-20260525-165845"
}

→ HTTP 202 ACCEPTED
{"intentId":"bl011b-20260525-165845","status":"ACCEPTED","trackingUrl":"/api/v1/notify/intents/bl011b-20260525-165845"}
```

---

## §4 Observe (90s) + Acceptance Gates

### §4.1 Intent state — COMPLETED

```
intent_id              | status    | channels | topic_key          | recipients_snapshot
-----------------------+-----------+----------+--------------------+---------------------
bl011b-20260525-165845 | COMPLETED | {sms}    | marketing.campaign | [{"type":"subscriber","subscriberId":"bl028-prod-canary-001"}]

processing_started_at  | created_at          | updated_at          
2026-05-25 16:58:46    | 2026-05-25 16:58:45 | 2026-05-25 16:59:56
```

Processing duration: 71 saniye (queue → dispatch → provider ACCEPT → DLR DELIVERED).

### §4.2 Delivery row — DELIVERED

```
id | intent_id              | provider | provider_msg_id            | status    | channel
---+------------------------+----------+----------------------------+-----------+---------
 1 | bl011b-20260525-165845 | jetsms   | jetsms-2605251959362908914 | DELIVERED | sms
```

✅ **First prod SMS delivery row** (id=1 — clean prod database confirmed).

### §4.3 Audit chain — 4 event

```
event_type             | occurred_at         | actual_channel | provider | dstatus
-----------------------+---------------------+----------------+----------+---------
INTENT_CREATED         | 16:58:45.841       |                |          | 
DELIVERY_ATTEMPTED     | 16:58:47.034       |                |          | 
DELIVERY_ACCEPTED      | 16:58:47.266       | VF             | jetsms   | ACCEPTED
DELIVERY_DLR_RECEIVED  | 16:59:56.932       |                |          | 
```

DLR detail (jsonb):
```json
{
  "org_id": "default",
  "channel": "sms",
  "provider": "jetsms",
  "topic_key": "marketing.campaign",
  "template_id": "canary-prod-marketing-v1",
  "template_version": 1,
  "provider_code": "1",                  // ← success
  "correlation_id": "bl011b-20260525-165845",
  "recipient_hash": "526649be088b3a...",
  "delivery_id_long": 1,
  "dlr_state_mutated": true              // ← DELIVERED state update done
}
```

### §4.4 Metric — notify_org_access_match_total

```
notify_org_access_match_total{source="none"}    1223.0   (was 1166.0; +57 other reqs)
notify_org_access_match_total{source="org_id"}     1.0   ← NEW (BL-011 increment)
```

✅ **`source="org_id"` counter ortaya çıktı** — BL-010 org_id mapper effective kanıt.

### §4.5 Channel routing — VF (R24 workaround active)

`actual_channel=VF` (not VFO) — `marketing.campaign` topic OTP allowlist'te yok + `OTP_TOPIC_KEYS=""` blank → tüm topic'ler VF'den çıkıyor. JetSMS provider VF channel'i kabul etti (provider_code=1 success).

### Acceptance summary

| Gate | Sonuç |
|---|---|
| 1. Intent ACCEPTED + COMPLETED | ✅ |
| 2. Delivery row + provider_msg_id + DELIVERED status | ✅ `jetsms-2605251959362908914` |
| 3. Audit 4-event chain (CREATED → ATTEMPTED → ACCEPTED → DLR_RECEIVED) | ✅ |
| 4. Metric `notify_org_access_match_total{source="org_id"}` increase | ✅ 0 → 1 |
| 5. Provider VF channel + provider_code=1 success | ✅ |
| 6. DLR cycle <120s | ✅ 71s |
| 7. No retry/failure logs | ✅ direct ACCEPTED + DELIVERED |

7/7 acceptance gate PASS.

---

## §5 Cost + Recipient evidence

- **Recipient**: `+905551815564` (kullanıcı 2026-05-25 explicit re-confirm)
- **SMS count**: 1 (max_count=1 hard cap, cost cap ≤3 confirme)
- **Estimated cost**: ~5 kuruş (JetSMS VF rate)
- **No unexpected duplicate**: 1 delivery row + 1 ACCEPTED + 1 DLR_RECEIVED (zero retry)

---

## §6 R28 final state + BL-011 closure

**R28 status** (sequential progression):
- 2026-05-25 11:30 — 🔴 Pending (post BL-010; Lane A + Lane B blocker)
- 2026-05-25 11:51 — 🟡 Partial Mitigated (BL-028a LIVE; Lane A done)
- 2026-05-25 12:01 — 🟢 Mitigated (BL-028b LIVE; Lane B done; severity High → Low)
- 2026-05-25 16:59 — 🟢 Mitigated + **functional canary PROVEN** (BL-011 LIVE)

**BL-011 status**:
- 🔴 Blocked → 🟢 **DONE** (LIVE 2026-05-25)

**Faz 23 v1 D29-NOTIFY-Functional 4-channel (SMS lane)**:
- ✅ Source code complete
- ✅ Live runtime prod (LIVE since M4 cutover 2026-05-20)
- ✅ Functional canary acceptance (BL-011 SMS DELIVERED 2026-05-25 — this evidence)
- ✅ Authorization layer (Layer-1 + Layer-2 LIVE)

---

## §7 Charter 23.3 final marker

🟢 infra LIVE + 🟢 functional data seed LIVE + 🟢 Layer-2 authz cutover LIVE + 🟢 **prod SMS canary DELIVERED** (BL-011)

**B-with-lanes complete + BL-011 closure** = Faz 23.3 prod SMS lane v1 fully delivered.

---

## §8 Sıradaki adımlar (post-BL-011)

| BL | Status | Owner | ETA |
|---|---|---|---|
| BL-012 M7 30-day prod observation window | ⏳ Active timer-bound | ops | 30 gün |
| BL-014 FBL mailbox activation | ⏳ Operator IMAP credentials | ops | Operator iş |
| R9 #854 SMTP prod observation | ⏳ Operator drill | ops | 30 gün |
| 3 KC drift fix (user-svc ?, auth-svc 11char, perf-alertmanager orphan) | ⏳ Operator | ops | Operator iş |
| BL-016 R24 Biotekno OTP allowlist | ⏳ External provider | ops + Biotekno | 1-2 hafta |
| BL-017-020 M3/M4/M5/M6 board acceptance | ⏳ PM | PM | PM scope |
| BL-022 NetGSM contract | ⏳ DEFER (kullanıcı kararı 2026-05-23) | ops + legal | Kalıcı DEFER |
| BL-023 Mobile FCM/APNS | ⏳ Faz 22.2 dependency | Mobile | Faz 22.2 sonrası |

Agent-doable scope tamamlandı. Kalan tüm açık konular operator/external/timer-bound.

---

## §9 Cross-AI peer review chain (full series)

| Codex thread | Scope | Final verdict |
|---|---|---|
| `019e5e76` | R28 NEW discovery (BL-028 yeni backlog) | iter-2 REVISE → docs-only PR #1064 MERGED |
| `019e5ebe` | B-with-lanes pattern | iter-1 REVISE → iter-2 PARTIAL → iter-3 AGREE |
| `019e5ee5` | BL-028b runbook | iter-1 PARTIAL → iter-2 AGREE |
| Lane B context | BL-011 unblock criterion | inheritance from `019e5ee5` (Q5 acceptance criteria) |

Provider farkı: implementer Anthropic Claude / reviewer OpenAI Codex (HARD RULE 2026-05-05/14 compliance — code yazan AI ≠ review eden AI).

---

## §10 Audit trail

- **Git commit**: bu evidence doc commit'i
- **PR series**: #1066 + #1067 + #1068 + #1069 MERGED; bu PR = BL-011 LIVE evidence (closure final)
- **Live execute timestamp**: 2026-05-25 16:58:45 UTC (POST) → 16:59:56 UTC (DLR DELIVERED)
- **Operator + agent split**:
  - Agent (Anthropic Claude) executed under Pre-Production Full Authority HARD RULE 2026-04-29
  - SSH + Vault root token (canary persona password) + curl Keycloak token + curl backend POST
  - Kullanıcı explicit "kalan işi tamamla" (2026-05-25 final session message)
- **No-fake-work compliance**: gerçek SMS gönderildi prod env'den (DELIVERED + DLR_RECEIVED) — HARD RULE No Fake Work uyumlu

---

## §11 Lessons learned

1. **JWT lifespan disipline**: Keycloak access token 5 dakika; canary execute için fresh mint → immediate POST. Mint ↔ POST arası >5 dakika geçerse expired (16:46 expire, 16:58 retry'da fresh mint).
2. **Backend `actuator/health` prod hardening**: kapalı; reachability kanıtı asıl endpoint (POST → 401 auth filter response) ile.
3. **Schema drift safety**: `notification_delivery` tablosunda `channel_used` kolonu yok (BL-011 RB §4.4 yanlış varsayım); canonical kolon `channel` + audit `actual_channel` jsonb field. Drift fix BL-011 RB ayrı PR'da yapılabilir.
4. **VF vs VFO routing**: `marketing.campaign` non-OTP topic + OTP_TOPIC_KEYS=blank → default VF. R24 Biotekno OTP allowlist provisioning hâlâ external lead.
5. **Provider DLR fast**: 71 saniye (ACCEPTED → DELIVERED). JetSMS VF channel responsive.

---

## Referanslar

- BL-011 runbook: `docs/runbooks/RB-bl011-prod-sms-canary-execute.md`
- BL-010 evidence: `docs/faz-23-evidence/2026-05-25-bl010-prod-kc-org-id-mapper-serban.md`
- BL-028a Lane A evidence: `docs/faz-23-evidence/2026-05-25-bl028a-lane-a-prod-data-seed-execute.md`
- BL-028b Lane B evidence: `docs/faz-23-evidence/2026-05-25-bl028b-lane-b-prod-openfga-cutover-evidence.md`
- Risk register R28: `docs/notify/risk-register.md`
- Charter: `docs/runbooks/RB-faz-23-charter.md`
- Closure handoff: `docs/runbooks/RB-faz-23-v1-closure-operator-handoff.md`
- Codex thread Lane B: `019e5ee5-4da5-7713-9dbe-8567d83e1ef2`
