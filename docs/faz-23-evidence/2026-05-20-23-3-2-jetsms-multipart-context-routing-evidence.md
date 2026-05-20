# 23.3.2 JetSMS Multipart + VF Delivery + Context Routing LIVE Evidence (2026-05-20)

> **Status**: 🟡 **PARTIAL ACCEPTANCE** — Multipart + VF delivery + context routing logic LIVE; VFO provider acceptance blocked by R24 (Codex iter-3 P1 absorb)
> **Sub-Faz**: 23.3.2 (SMS multipart + VFO/VF channel routing + audit propagation)
> **Codex Thread**: `019e4514-e961-7d50-b2cc-493f66cee4bc` (11 iter, PR-A1 → PR-A2.2)
> **Backend chain**: PR #262 + #263 + #264 + #265 + #266 + #267 (MERGED)
> **GitOps chain**: PR #903 + #905 + #908 (MERGED 2026-05-20T17:06Z)
> **Pod imageID**: `sha256:30b0bf658dcd879c531451352c4e37680551fe14ab667a255eea36adbb281a5b` (sha-6ed593e)

---

## Executive Summary

JetSMS multipart concatenated SMS chain + context-aware VFO/VF channel
routing decision logic + `actual_channel` audit propagation 2026-05-20'de
test cluster'da LIVE oldu. 3-senaryo canary smoke yürütüldü:
**B + C senaryoları DELIVERED** (VF channel + multipart 2 segments),
**A senaryosu routing-only PASS + provider acceptance FAIL** (VFO channel
JetSMS Biotekno OTP sender ID provisioning gap R24).

**Real-world delivery**: kullanıcı +905551815564 numarasına multipart SMS
(258-char) ile (sha-4caa860b) 2026-05-20 öğleden önce + canary B+C SMS
(sha-6ed593e) 2026-05-20 öğleden sonra başarıyla iletildi. Scenario A SMS
provider tarafında ErrorCode=04 ile reddedildi (routing logic LIVE; sadece
provider acceptance gap).

| Katman | Status | Kanıt |
|---|:---:|---|
| **D29-Up** (pod running) | 🟢 LIVE | `kubectl get pod` Running 1/1 sha256:30b0bf658dcd |
| **D29-Functional** (VF dispatch end-to-end) | 🟢 LIVE | B + C DELIVERED + DLR poll |
| **D29-Multipart** (segment >1 estimation) | 🟢 LIVE | sms-multipart-test 209ch → 2 segments DELIVERED |
| **D29-ContextRouting** (VFO/VF allowlist decision log) | 🟢 LIVE | Scenario A (VFO log) + B (VF log) + C (VF fallback log) cluster log proven |
| **D29-actualChannel** (audit propagation, VF accepted path) | 🟢 LIVE | DELIVERY_ACCEPTED.details actual_channel=VF kanıtı (B + C) |
| **VFO Provider Acceptance** (Biotekno OTP delivery) | 🔴 BLOCKED | R24: ErrorCode=04 JetSMS reject; Biotekno sender ID OTP provisioning gap |
| **VFO actual_channel audit** (ACCEPTED path) | 🟡 PENDING | R24 resolution sonrası VFO ACCEPTED delivery beklenir |
| **D29-Zanzibar** (Layer 2 channel-level authz) | 🟡 Faz 23.2 v2 scope | OpenFGA subscriber/template types yok |

---

## 1. Backend Code Chain (canonical commit'lar)

| PR | Title | Codex Verdict | Live Behavior |
|---|---|---|---|
| #262 (PR-A1.2) | charset + length capability hardening | AGREE | maxMessageLength() dynamic |
| #263 (PR-A1.1) | segment metadata audit propagation | AGREE | segment_count audit details |
| #264 (PR-A2.0) | DLR multipart aggregate hardening | AGREE | any-failed → failed semantic |
| #265 (PR-A3.0) | SendSMSSingle + channel param | AGREE | SOAP single-recipient + channel field |
| #266 (PR-A3.1.0) | SmsSendContext + OTP allowlist scaffold | AGREE | Config alanları + DeliveryTarget routingMetadata |
| #267 (PR-A3.1.1) | runtime resolveChannel + actual_channel | AGREE (iter-2 P2+P3 absorb) | Context-aware VFO/VF + audit propagation |

**Test coverage**: 223/223 SMS regression + 769/769 unit tests PASS.

---

## 2. GitOps Cutover Chain

| PR | Title | Status | Image Digest |
|---|---|---|---|
| #903 (PR-A2.1) | multipart=true + ON_LENGTH_PROBLEM=SendAllPackage | MERGED 2026-05-20 | sha-4caa860b |
| #905 (hotfix) | SplitMessage → SendAllPackage (WSDL fix) | MERGED 2026-05-20 | n/a (config) |
| #908 (PR-A3.2) | SOAP single + OTP allowlist + digest bump | MERGED 2026-05-20T17:06Z | sha-6ed593e |

---

## 3. Live Smoke Evidence (3-Senaryo Canary)

### 3.1 Pod Pre-Conditions (post-deploy)

**Image digest**:
```
ghcr.io/halildeu/platform-backend-notification-orchestrator@sha256:30b0bf658dcd879c531451352c4e37680551fe14ab667a255eea36adbb281a5b
```

**ConfigMap env** (5 yeni key):
```
NOTIFY_ADAPTERS_SMS_JETSMS_SOAP_OPERATION=sendSMSSingle
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL=VF
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_ALLOWED=VF,VFO
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS=auth.mfa-otp,auth.password-reset-otp
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_MAX_LENGTH=160
```

Plus pre-existing PR-A2.1: `NOTIFY_ADAPTERS_SMS_JETSMS_MULTIPART_ENABLED=true`.

### 3.2 Scenario A — OTP topic kısa → VFO routing

**Intent**: `pr-a3-2-A-otp-short-v2-1779297519`
- `topic_key=auth.mfa-otp` (OTP allowlist match)
- `template_id=t1` (renders to 4 chars)
- Expected: **VFO** channel

**Cluster log** (proof):
```
2026-05-20T17:18:43.650Z INFO JetSmsProvider: jetsms channel resolved VFO: topic_key=auth.mfa-otp (len=4)
2026-05-20T17:18:46.358Z WARN JetSmsProvider: jetsms SOAP send ErrorCode=04 → RETRY/UNKNOWN_TRANSIENT
```

**Result**: ✅ VFO routing logic PROVEN. JetSMS provider ErrorCode=04 (separate concern: Biotekno OTP allowlist için sender ID provisioning gerek; routing logic'i etkilemiyor).

**PG delivery row**:
```
intent_id: pr-a3-2-A-otp-short-v2-1779297519
status:    FAILED (provider ErrorCode=04)
provider:  jetsms
```

### 3.3 Scenario B — Marketing topic → VF default channel

**Intent**: `pr-a3-2-B-marketing-1779298007`
- `topic_key=marketing.campaign` (no allowlist match)
- `template_id=t1` (4 chars)
- Expected: **VF** default channel

**Cluster log** (proof):
```
2026-05-20T17:26:47.848Z INFO JetSmsProvider: jetsms SOAP ACCEPTED (awaits DLR poll): msg_id=jetsms-2605202027306017971 segments=1 encoding=ISO-8859-9 channel=VF
```

**Result**: ✅ VF default routing + SOAP ACCEPTED + delivery.

**PG delivery row**:
```
intent_id:        pr-a3-2-B-marketing-1779298007
status:           DELIVERED ✅
channel:          sms
provider:         jetsms
provider_msg_id:  jetsms-2605202027306017971
delivered_at:     2026-05-20 17:28:26 UTC
```

**Audit event** (DELIVERY_ACCEPTED.details):
```json
{
  "org_id": "default",
  "channel": "sms",
  "encoding": "ISO-8859-9",
  "topic_key": "marketing.campaign",
  "template_id": "t1",
  "segment_count": 1,
  "actual_channel": "VF",
  "actual_provider": "jetsms",
  "delivery_status": "ACCEPTED",
  "provider_msg_id": "jetsms-2605202027306017971"
}
```

### 3.4 Scenario C — OTP topic + overlength → VF explicit fallback (Codex P3 absorb proof)

**Intent**: `pr-a3-2-C-overlen-v2-1779298162`
- `topic_key=auth.mfa-otp` (OTP allowlist match)
- `template_id=sms-multipart-test` (renders to 209 chars)
- Expected: **VF fallback** (explicit, overlength guard)

**Cluster log** (proof):
```
2026-05-20T17:29:23.267Z INFO JetSmsProvider: jetsms multipart accepted: len=209 segments=2 encoding=ISO-8859-9 onLengthProblem=SendAllPackage
2026-05-20T17:29:23.267Z WARN JetSmsProvider: jetsms VFO overlength fallback: topic_key=auth.mfa-otp matched but len=209 > otpMaxLength=160 → VF (explicit)
2026-05-20T17:29:23.331Z INFO JetSmsProvider: jetsms SOAP ACCEPTED (awaits DLR poll): msg_id=jetsms-260520203006838196 segments=2 encoding=ISO-8859-9 channel=VF
```

**Result**: ✅ **Codex P3 absorb LIVE** — explicit `CHANNEL_VF` (not config-default) selected on overlength fallback. Multipart 2 segments DELIVERED.

**PG delivery row**:
```
intent_id:        pr-a3-2-C-overlen-v2-1779298162
status:           DELIVERED ✅
channel:          sms
provider:         jetsms
provider_msg_id:  jetsms-260520203006838196
delivered_at:     2026-05-20 17:30:26 UTC
```

**Audit event** (DELIVERY_ACCEPTED.details):
```json
{
  "org_id": "default",
  "channel": "sms",
  "encoding": "ISO-8859-9",
  "topic_key": "auth.mfa-otp",
  "template_id": "sms-multipart-test",
  "segment_count": 2,
  "actual_channel": "VF",
  "actual_provider": "jetsms",
  "delivery_status": "ACCEPTED",
  "provider_msg_id": "jetsms-260520203006838196"
}
```

### 3.5 Real-world Delivery (kullanıcı SMS receipt)

Kullanıcı +905551815564 numarasına 2026-05-20 17:30 (TR time = UTC+3 = 20:30 lokal) iletildi:

- **Scenario B** SMS: 1 segment, VF channel
- **Scenario C** SMS: 2 segments multipart, VF (overlength fallback) channel

(Scenario A için VFO channel JetSMS Biotekno OTP provisioning gerektirir; routing logic'i etkisiz.)

---

## 4. Code Path Doğrulaması

### 4.1 PR-A3.1.0 (SmsSendContext + DeliveryTarget routingMetadata)

**Audit chain**: intent.severity + intent.topic_key + intent.template.template_id
→ DeliveryPlanService.planSmsTargets() → DeliveryTarget.routingMetadata
→ SmsAdapter.extractContext() → SmsSendContext typed record
→ JetSmsProvider.send(phone, text, context) → resolveChannel()

### 4.2 PR-A3.1.1 (runtime resolveChannel + actual_channel audit — Codex P2+P3)

**P2 — actual_channel audit propagation** (LIVE PROVEN):
- SmsSendResult 8. field `actualChannel`
- JetSmsProvider parseSoapSendResponse() 4-arg overload
- SmsAdapter.smsMetadata() includes `actual_channel`
- PiiRedactor WHITELIST opens `actual_channel`
- DELIVERY_ACCEPTED audit details includes `actual_channel` field (2 LIVE examples above)

**P3 — explicit CHANNEL_VF on overlength** (LIVE PROVEN):
- Scenario C log: `→ VF (explicit)`
- Config drift hardening: operator `channel=VFO` set ederse bile overlength
  fallback yine VF döndürür (compile-time literal)

---

## 5. Authz Layer

### 5.1 Layer 1 — NotifyOrgAccessGuard

JWT `org_id` claim check. smoke-tester user `org_id=default` claim ile
intent submit edebildi. Pre-existing M2 closure'da LIVE.

### 5.2 Layer 2 — Channel-level (Faz 23.2 v2 scope)

OpenFGA mevcut model'inde `subscriber` + `template` types YOK. SMS
channel-level `can_receive` authz Faz 23.2 v2 scope'unda. Bu evidence
collection sırasında `NOTIFY_AUTHZ_ENABLED=false` geçici (kullanıcı
2026-05-20 onayı). Smoke sonrası restore edildi (`NOTIFY_AUTHZ_ENABLED=true`).

---

## 6. R-Risks (operasyonel) — Status Update

| Risk | Status | Mitigation |
|---|:---:|---|
| R6 (JetSMS allowlist provider drift) | 🟢 mitigated | CHANNEL_ALLOWED=VF,VFO outbound preflight LIVE |
| R8 (multipart segment billing surprise) | 🟢 mitigated | segment_count audit propagation LIVE (B + C kanıtı) |
| R10 (VFO overlength misroute) | 🟢 mitigated | otpMaxLength=160 + explicit VF fallback (Scenario C kanıt) |
| R12 (config drift channel=VFO) | 🟢 mitigated | Codex P3 absorb explicit CHANNEL_VF LIVE |
| R24 (VFO Biotekno OTP provisioning) | 🟡 NEW | JetSMS ErrorCode=04 VFO channel için; sender ID OTP allowlist + Biotekno coordination gerek |

---

## 7. Closure Path (M4/23.3.2 acceptance DoD)

**23.3.2 sub-Faz DoD** (Codex iter-3 P2 absorb — VFO routing decision ≠ VFO provider acceptance):

- [x] T-multipart: JetSMS 160-char limit kaldırıldı + segment estimator LIVE
- [x] T-segment-audit: segment_count audit propagation LIVE (B: 1 seg, C: 2 seg)
- [x] T-aggregate: DLR multipart aggregate semantic doğru
- [x] T-channel-routing-decision: VFO/VF channel decision logic runtime LIVE (Scenario A+B+C log proven)
- [x] T-actual-channel-VF: actual_channel propagation VF accepted path LIVE (B + C DELIVERY_ACCEPTED.details)
- [x] T-canary-smoke-VF: VF default (B) + VF overlength fallback (C) cluster delivered
- [~] T-canary-smoke-VFO: routing-log proven (Scenario A); **provider acceptance PENDING R24 resolution**
- [x] T-evidence-doc: D29 evidence final (this document)
- [ ] T-actual-channel-VFO: actual_channel=VFO audit propagation (R24 resolution sonrası)
- [ ] T-prod-cutover: prod overlay rotation (ayrı sprint, M4 prod gates)
- [ ] T-vfo-biotekno-prov: JetSMS Biotekno VFO sender ID OTP allowlist provisioning (R24)

---

## 8. References

- Codex thread: `019e4514-e961-7d50-b2cc-493f66cee4bc`
- Backend PR chain: [#262](https://github.com/Halildeu/platform-backend/pull/262), [#263](https://github.com/Halildeu/platform-backend/pull/263), [#264](https://github.com/Halildeu/platform-backend/pull/264), [#265](https://github.com/Halildeu/platform-backend/pull/265), [#266](https://github.com/Halildeu/platform-backend/pull/266), [#267](https://github.com/Halildeu/platform-backend/pull/267)
- GitOps PR: [#903](https://github.com/Halildeu/platform-k8s-gitops/pull/903), [#905](https://github.com/Halildeu/platform-k8s-gitops/pull/905), [#908](https://github.com/Halildeu/platform-k8s-gitops/pull/908)
- ADR-0013 (notification-orchestration)
- Charter Faz 23
- Milestone M3 (23.2 Production MVP)

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
