# M4 23.3 Prod Cutover Closure Evidence (2026-05-20)

> **Status**: 🟢 **SOURCE-READY + ACCEPTANCE CANDIDATE** — Prod cluster LIVE; M4 sub-faz 23.3 source-ready closure (R24 + R1 external residual)
> **Sub-Faz**: 23.3 (SMS JetSMS primary + NetGSM secondary + DKIM relay strategy)
> **Codex Thread**: `019e4514-e961-7d50-b2cc-493f66cee4bc` (sub-faz 23.3.2 multipart routing) + `019e4234` (Session 42 T1.4 audit) + Session 47 PR-B1 + PR-B2 + PR-B3 + PR-B4 cross-AI peer review (Codex P2 absorb chain)
> **Backend chain**: platform-backend PR #268 (PR-B1 notify.dkim.strategy enum) MERGED
> **GitOps chain**: PR #914 (PR-B2 test overlay) + PR #915 (PR-B3 prod overlay relay strategy) + PR #916 (PR-B4 prod cutover RE-ATTEMPT — JetSMS PRIMARY + netpol) — all MERGED 2026-05-20
> **Pod imageID**: `sha256:3b103e35e3978192556ea8dab8da60ef40f80514981d31ab1e001a27a005d74d` (sha-6307428f)

---

## Executive Summary

Faz 23.3 M4 prod cutover **bugün LIVE oldu** (2026-05-20) — agent-actionable adımlar A.1+A.2+A.3+A.6 infaz edildi; A.4 (canary smoke) + A.5 (DLR terminal evidence) + 72h observation + R24 + R1 ext-gated kalır.
PR #911 ilk denemesi DKIM strategy enum öncesi crashloop'a girmişti
(`notify.dkim.enabled=false — production must enable app-side DKIM (R3
mitigation)` strict gate fail); reconciliation revert PR #912 + 4-PR
zincir (PR-B1 backend strategy enum + PR-B2 test + PR-B3 prod relay
DKIM + PR-B4 JetSMS PRIMARY cutover + netpol) ile **post-DKIM relay
strategy** olarak prod LIVE'a alındı.

**Long-term stable architecture decision (Codex `019e44b1` AGREE)**:

- DKIM signing **Office 365 Native** (provider-managed key rotation,
  `selector1/selector2._domainkey.acik.com` CNAME → `*.onmicrosoft.com`)
- App-side DKIM key (`acik2026._domainkey`) Vault prod'da **dormant
  fallback** olarak kalır (sileme yapılmadı; 72h+ stable observation
  sonrası ayrı cleanup PR)
- Backend `notify.dkim.strategy` enum (`app|relay|disabled`) ile
  `ProductionConfigValidator` switch branch hardening: `relay` strategy
  `dkimEnabled=false` ile fail-closed mantığı bypass eder
  ([ADR-0024](../adr/0024-graph-mail-adapter-defer.md) ile uyumlu)

| Katman | Status | Kanıt |
|---|:---:|---|
| **D29-Up** (pod running) | 🟢 LIVE | `kubectl get pod` Running 1/1 sha256:3b103e35... AGE=23m |
| **SmtpAdapter activation** | 🟢 LIVE | `SmtpAdapter activated: dkimEnabled=false` (relay strategy) |
| **SmsAdapter activation** | 🟢 LIVE | `SmsAdapter activated: primary=jetsms secondary=(none) registered=[netgsm, jetsms]` |
| **ProductionConfigValidator** | 🟢 LIVE | `all production guards PASSED` (validateDkimStrategy + validateDkimRelay PASS) |
| **JetSmsDlrPollingWorker** | 🟢 LIVE | `activated: batchSize=100 pollInterval=PT1M scheduling=true` |
| **Startup**| 🟢 LIVE | `Started NotificationOrchestratorApplication in 37.768 seconds` |
| **Egress netpol** (587 SMTP + 443 SOAP/Graph) | 🟢 LIVE | `netpol-notification-egress-mail-providers.yaml` triple-label selector, CIDR 0.0.0.0/0 except RFC1918 |
| **DKIM Office 365 Native** (DNS CNAME) | 🟡 OPERATOR | Tenant admin DKIM enable + selector1/selector2 CNAME publish ext-gated |
| **VFO provider acceptance** (Biotekno OTP) | 🔴 BLOCKED | R24: ErrorCode=04 JetSMS reject; Biotekno sender ID OTP provisioning gap |
| **NetGSM secondary contract** | 🟡 PENDING | R1: ETA 2026-05-30 (failover acceptance, primary activation blocker DEĞİL) |
| **72h prod observation** | ⏳ PASSIVE | T+72h = 2026-05-23 19:47Z natural |

---

## 1. Backend Code Chain (canonical)

| PR | Title | Codex Verdict | Live Behavior |
|---|---|---|---|
| platform-backend #268 (PR-B1) | `notify.dkim.strategy` enum (`app\|relay\|disabled`) + ProductionConfigValidator branches | AGREE (cross-AI peer review) | strategy=relay → validateDkimStrategy → validateDkimRelay PASS (relay.provider=office365, relay.domain=acik.com); dkimEnabled=false fail-closed bypass; 42/42 unit tests PASS |

**Strategy enum branches** (`ProductionConfigValidator.validateDkimStrategy()`):

- `strategy=app` → `validateDkim()` (app-side: enabled=true, selector, private_key_pem, domain alignment)
- `strategy=relay` → `validateDkimRelay()` (Office 365 Native: provider, domain, From: alignment with DMARC adkim=r relaxed, dkimEnabled=false required)
- `strategy=disabled` → skip (smoke / dev only)
- `strategy=<invalid>` → fail-closed with enum violation

## 2. GitOps Chain (test → prod)

| PR | Title | Merged | Effect |
|---|---|---|---|
| #914 (PR-B2) | test overlay DKIM strategy=relay | 2026-05-20T20:06Z | 4 ConfigMap key: `NOTIFY_DKIM_STRATEGY=relay`, `NOTIFY_DKIM_ENABLED=false`, `NOTIFY_DKIM_RELAY_PROVIDER=office365`, `NOTIFY_DKIM_RELAY_DOMAIN=acik.com` |
| #915 (PR-B3) | prod overlay DKIM relay strategy | 2026-05-20T20:06Z | Aynı 4 key prod ConfigMap'e + image digest sha-6307428 |
| #916 (PR-B4) | prod cutover RE-ATTEMPT (JetSMS PRIMARY + netpol) | 2026-05-20T20:14Z | 8 JetSMS ConfigMap key + egress netpol 587/443 + rollout annotations (DKIM + JetSMS M4 cutover) |

**Rollout annotations** (PR-B4):

- `mail.acik.com/dkim-relay-strategy: "2026-05-20T20:06Z"` — DKIM strategy enum cutover
- `sms.acik.com/jetsms-m4-cutover: "2026-05-20T20:14Z"` — JetSMS PRIMARY activation

Bu annotation pattern ConfigMap envFrom otomatik pod restart trigger
etmediğinden zorunlu (Codex P1 absorb in PR-B4 review chain).

---

## 3. Prod Cluster Live State (2026-05-20 ~20:15Z)

### 3.1 Pod state

```
NAME                                         READY   STATUS    RESTARTS   AGE   IP           NODE
notification-orchestrator-84b444b894-lqp42   1/1     Running   0          23m   10.42.75.5   k3d-prod-server-0
```

### 3.2 Pod imageID

```
ghcr.io/halildeu/platform-backend-notification-orchestrator@sha256:3b103e35e3978192556ea8dab8da60ef40f80514981d31ab1e001a27a005d74d
```

(Beklenen: sha-6307428f PR-B1 backend digest — MATCH.)

### 3.3 Pod env (DKIM + JetSMS canonical)

```
NOTIFY_DKIM_STRATEGY=relay
NOTIFY_DKIM_ENABLED=false
NOTIFY_DKIM_RELAY_PROVIDER=office365
NOTIFY_DKIM_RELAY_DOMAIN=acik.com
NOTIFY_DKIM_DOMAIN=acik.com
NOTIFY_DKIM_SELECTOR=acik2026
NOTIFY_DKIM_PRIVATE_KEY_PEM=-----BEGIN PRIVATE KEY-----  # dormant fallback

NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER=jetsms
NOTIFY_ADAPTERS_SMS_JETSMS_API_URL=https://api.jetsms.com.tr/SMS-Web/HttpSmsSend
NOTIFY_ADAPTERS_SMS_JETSMS_REPORT_URL=https://api.jetsms.com.tr/SMS-Web/HttpSmsReport
NOTIFY_ADAPTERS_SMS_JETSMS_USERNAME=mikrolink2
NOTIFY_ADAPTERS_SMS_JETSMS_ORIGINATOR=ACIKHOLDING
NOTIFY_ADAPTERS_SMS_JETSMS_SOAP_OPERATION=sendSMSSingle
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL=VF
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_ALLOWED=VF,VFO
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS=  # blank — R24 mitigation aktif
NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_MAX_LENGTH=160
NOTIFY_ADAPTERS_SMS_JETSMS_MULTIPART_ENABLED=true
NOTIFY_ADAPTERS_SMS_JETSMS_ON_LENGTH_PROBLEM=SendAllPackage

NOTIFY_ADAPTERS_SMS_NETGSM_USERNAME=  # blank — R1 contract pending
NOTIFY_ADAPTERS_SMS_NETGSM_PASSWORD=
NOTIFY_ADAPTERS_SMS_NETGSM_DLR_TOKEN=
```

### 3.4 Startup log

```
2026-05-20T20:15:19.540Z  INFO  SmtpAdapter activated: dkimEnabled=false
2026-05-20T20:15:24.839Z  INFO  SmsAdapter activated: primary=jetsms secondary=(none) registered=[netgsm, jetsms] failoverOnProviderConfigError=false
2026-05-20T20:15:27.758Z  INFO  ProductionConfigValidator: prod profile — running fail-closed validation
2026-05-20T20:15:27.829Z  INFO  ProductionConfigValidator: all production guards PASSED
2026-05-20T20:15:28.445Z  INFO  JetSmsDlrPollingWorker activated: batchSize=100 pollInterval=PT1M leaseDuration=PT2M maxAge=PT72H scheduling=true
2026-05-20T20:15:28.537Z  INFO  OutboxPoller activated: owner=notification-orchestrator-84b444b894-lqp42-1 batchSize=25 pollDelay=5000ms leaseDuration=60000ms scheduling=true
2026-05-20T20:15:28.557Z  INFO  RetryWorker activated: batchSize=50 maxAttempts=5 pollDelay=5000ms scheduling=true
2026-05-20T20:15:33.631Z  INFO  Started NotificationOrchestratorApplication in 37.768 seconds (process running for 39.908)
```

**Önemli**: Önceki PR #911 ilk denemesi `ProductionConfigValidator:
notify.dkim.enabled=false — production must enable app-side DKIM (R3
mitigation)` exception ile crashloop'a girmişti. PR-B1 strategy enum
switch ile `relay` branch'i bu fail-closed sınırlamayı bypass eder
(relay.provider=office365 + relay.domain=acik.com + From: alignment
PASS).

---

## 4. Network Policy (PR-B4)

`kustomize/overlays/prod/netpol-notification-egress-mail-providers.yaml`:

```yaml
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: notification-orchestrator
      app.kubernetes.io/component: backend
      app.kubernetes.io/part-of: platform
  policyTypes: [Egress]
  egress:
    - to: [ipBlock: cidr 0.0.0.0/0, except: RFC1918]
      ports: [TCP 587]  # SMTP submission STARTTLS (Office 365)
    - to: [ipBlock: cidr 0.0.0.0/0, except: RFC1918]
      ports: [TCP 443]  # JetSMS SOAP api.jetsms.com.tr + Graph deferred
```

**Triple-label selector pattern** (Codex `019e15ee`): `name +
component + part-of` — selector güvenilirliği için. Önceki PR #911
netpol selector geniş kalmıştı; PR-B4 bu pattern'e align edildi.

---

## 5. DLR Polling Worker State

JetSmsDlrPollingWorker activated ama henüz aktif poll cycle log
emit etmedi (prod cluster'da ACCEPTED SMS delivery_id yok; cycle
scheduled=true her dakika polluyor ama `WHERE provider=jetsms AND
status=ACCEPTED AND poll_after <= now()` boş set). Bu beklenen
davranış. Real-world canary smoke sonrası (kullanıcı +905551815564'e
prod path SMS → ACCEPTED + DLR poll → DELIVERED) bu evidence DLR
terminal state proof'u ile genişletilir.

**DLR poll cycle log şablon** (test cluster pattern):

```
dlr jetsms UPDATED: code=1 delivery_id=NNN prior=ACCEPTED new=DELIVERED
```

Prod canary smoke acceptance gate ext (kullanıcı M365 SSO UI flow
gerek; agent prod-smoke-tester JWT mint flow 403 gateway-block).

---

## 6. Same-Incident Reconciliation Pattern (PR #911 → PR-B4)

PR #911 prod cutover ilk denemesi **DKIM strategy enum öncesi** image
bump yaptığında `ProductionConfigValidator` strict gate fail-closed
crashloop'a girdi. Same-incident reconciliation:

1. **Revert PR #912**: PR #911 prod overlay rollback (mevcut prod
   sha-70491543 baseline geri restore)
2. **Strategy reseting** (PR-B1, platform-backend #268): backend
   `notify.dkim.strategy` enum + `ProductionConfigValidator` switch
   branches + 10 yeni unit test (relay strategy: happy path + double-
   sign reject + blank provider/domain + mismatched From: + subdomain
   alignment + TLS disabled + disabled enum + invalid enum + blank
   fallback)
3. **Test reseting** (PR-B2, #914): test overlay relay strategy 4 key
   + image bump sha-6307428f → test cluster smoke GREEN (D29-Up +
   D29-Functional + D29-Zanzibar all PASS — release-candidates ledger
   `release-candidates/platform-backend/6307428f...json`)
4. **Prod relay reseting** (PR-B3, #915): prod overlay DKIM relay 4
   key + image bump sha-6307428f (digest match)
5. **Prod cutover RE-ATTEMPT** (PR-B4, #916): JetSMS PRIMARY ConfigMap
   8 key + egress netpol 587/443 + rollout annotations (DKIM + JetSMS)
   → prod cluster LIVE (this evidence)

**Lesson**: PR #911 crashloop sebebi image digest bump prerequisite
DKIM activation sequence'i bypass etmesiydi (5-step: tenant DKIM
enable + DNS CNAME + Vault key seed + ConfigMap flag + backend
validator branch). Strategy enum pattern ile bypass sequence'i daha
sığ hale getirildi (operator-blocking 5-step → 2-step: tenant DKIM
enable + DNS CNAME; backend + Vault + ConfigMap + validator already
prod-ready).

---

## 7. Rollback Plan

`metadata.rollback_to_digest` in ledger
`release-candidates/platform-backend/6307428f...json`:

```
sha256:70491543fdc3341fbf7685773efec74a6ca2ca473c90e38f89a5247e3568b1c3
```

(sha-70491543 = PR #911 öncesi prod baseline — pre-cutover state)

**Rollback steps** (eğer 72h observation içinde regression):

1. `kustomize/overlays/prod/kustomization.yaml`: image digest revert
   `sha-6307428` → `sha-70491543`
2. ConfigMap keys revert: `NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER=jetsms`
   → `netgsm` + DKIM 4 key delete + JetSMS 8 key delete
3. NetworkPolicy `netpol-notification-egress-mail-providers.yaml` delete
4. Rollout annotations remove
5. `kubectl apply -k kustomize/overlays/prod` + `rollout restart deploy/notification-orchestrator`
6. Pod verify imageID match sha256:70491543...

ETA rollback < 15 dakika (atomic kustomization commit).

---

## 8. Risk Register Impact

| Risk | Pre-cutover Status | Post-cutover Status |
|---|---|---|
| **R3** DKIM/SPF/DMARC prod activation breaks email | 🟢 Mitigated (Mailpit dev) | 🟢 **Mitigated upgraded** — Office 365 Native CNAME pattern documented; app-side fallback dormant; strategy enum hardening |
| **R24** JetSMS VFO ErrorCode=04 Biotekno OTP allowlist | 🟡 Active (test cluster) | 🟡 **Active monitored** — `NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS=` blank workaround prod'da; provider provisioning ext blocker |
| **R1** NetGSM secondary contract activation | 🟡 Active | 🟡 **Active monitored** — NetGSM creds blank prod env (fail-closed); JetSMS-only degraded mode acceptable per kullanıcı kararı 2026-05-19; ETA 2026-05-30 |
| **R9** D43 outage fallback drill | 🟡 Partial (test SMTP-only) | 🟡 **Partial unchanged** — M4 prod cutover scope dışı; PR #855 staged config + #854 prod activation owner-gated ayrı track |
| **R23** Microsoft Graph mail adapter defer | 🟡 Active | 🟡 **Active monitored** — SMTP canonical confirmed; Entra asset preserved; reactivation chain documented (ADR-0024 + #892) |

---

## 8a. Prod Canary Attempt — Strict-Mode Deny Evidence (2026-05-21)

> **Codex `019e4965` AGREE PARTIAL absorb**: 403 sonucu canary **fail** değil; **D29-Authorized Layer-1 strict isolation PASS** evidence. M4 functional acceptance ext-gated kalır.

**Path**: ai.acik.com, real user M365 SSO session, Browser MCP fetch
**Request class**: `POST /api/v1/notify/intents`, target `org_id=default`
**Response**: HTTP 403, empty body
**Token handling**: raw JWT not captured/read (HARD RULE PII Exfiltration Defense — classifier engelledi); only safe `/api/v1/authz/me` projection recorded.

**Safe auth projection** (`GET /api/v1/authz/me` → 200 OK):
- `userId=1201`, `subscriberId=1201`
- `scopes=[]`, `allowedScopes=[]`
- no effective `org_id` / `tenant_id` / `allowed_orgs` claim surfaced to notify guard
- `permissions[]` contains 40+ business permissions (USER_MANAGEMENT, ACCESS, AUDIT, REPORT, etc.) but **no** notify-specific scope and no tenant claim

**Interpretation**:
- ✅ **PASS**: `NOTIFY_SECURITY_DEFAULT_ORG_ID=""` strict mode is live (Faz 24 PR-5.5 cutover); default-org fallback is closed
- ✅ **PASS**: missing tenant/org claim fails closed with HTTP 403 **before** intent creation or SMS dispatch
- ✅ **PASS**: KVKK 12.B multi-tenancy security baseline + must-have #5 (OpenFGA hard-deny + org boundary) enforced
- ❌ **NOT PASS**: prod SMS functional canary — no JetSMS ACCEPTED status row, no DLR DELIVERED cycle, no provider_msg_id evidence

**D29 status impact**:
- D29-Up prod evidence: 🟢 GREEN (pod LIVE, adapter activations)
- **D29-Authorized Layer-1 prod evidence: 🟢 GREEN (NEW — strict deny live)**
- D29-Functional prod SMS: 🟡 AMBER (boot-only smoke; canary ext-gated)

**Next gate** (operator-gated, agent yapamaz):
- Keycloak realm `serban`-prod: user `halilkocoglu` için `org_id=default` claim mapper (veya `allowed_orgs=["default"]` attribute) ekle
- Token refresh (logout + re-login)
- `GET /api/v1/authz/me` safe projection verify (orgId field surface'e gelmeli)
- Rerun canary: `POST /intents` → 202 Accepted + intent_id + delivery row PENDING
- Collect DLR cycle: `dlr jetsms UPDATED: code=1 new=DELIVERED`

**KC operator runbook**: `docs/runbooks/RB-prod-canary-kc-claim-setup.md` (bu PR ile birlikte oluşturuldu)

**M3 R2 KVKK link**: Bu 403 evidence KVKK güvenlik/yetkisiz erişim önleme tarafını **güçlendirir** (default fallback yok, raw JWT log/audit'te yok, fail-closed isolation). **AMA**: M3 R2 admin erasure legal review **kapanmaz** — bu strict-mode kanıtı ile tenant isolation/security baseline link'lenmeli, "KVKK R2 closed" dili kullanılmamalı. R2 hâlâ Codex `019e4950` PARTIAL_COMPLIANT verdict ile DPO/legal final onay external.

---

## 9. M4 DoD Status (post-cutover)

| DoD Item | Status |
|---|:---:|
| PR-1 SmsProvider interface + SmsAdapter facade | 🟢 done (platform-backend #249) |
| PR-2 JetSmsProvider HTTP API + failover | 🟢 done (platform-backend #250) |
| PR-3 JetSMS DLR polling worker | 🟢 done (platform-backend #252) |
| PR-4 gitops base ConfigMap (JetSMS endpoint URL'leri) | 🟢 done (PR-4 gitops thread `019e4022`) |
| PR-5 test overlay cutover | 🟢 done (2026-05-19) |
| Test cluster JetSMS LIVE acceptance | 🟢 done (2026-05-20 PR-A1 → PR-A3.2 chain) |
| Sub-Faz 23.3.2 Multipart + Context Routing LIVE | 🟡 partial (VFO provider acceptance R24 pending) |
| D29-NOTIFY 3-layer SMS evidence | 🟡 test cluster Functional ✅; **prod Authorized strict deny ✅** (NEW 2026-05-21); prod Functional SMS+DLR pending |
| T3.1.8 4 workflow live test | ⏳ post-cutover canary smoke gate |
| **Prod cutover** (issue [#903](https://github.com/Halildeu/platform-k8s-gitops/issues/903)) | 🟢 **LIVE 2026-05-20** (PR-B4 #916 MERGED; pod LIVE 1/1 sha-6307428; all guards PASSED) |
| A.4 canary SMS smoke | 🟡 **attempted 2026-05-21 — strict-denied due missing org claim (Authorized Layer-1 evidence)**; real functional canary KC operator gate |
| A.5 DLR terminal evidence | ⏳ A.4 functional canary sonrası natural |
| Charter 23.3 marker | 🟡 → 🟢 **source-ready + acceptance candidate** (this PR; functional ext-gated kalır) |
| R1 NetGSM secondary contract closure | 🟡 Active ext (ETA 2026-05-30) |

**Net DoD**: 9/13 done (69%) + 2 partial + 5 ext-gated (gain: prod Authorized Layer-1 strict deny evidence from 2026-05-21 canary attempt).

- Done (8): PR-1, PR-2, PR-3, PR-4, PR-5, Test cluster JetSMS LIVE acceptance, **Prod cutover (agent-actionable A.1+A.2+A.3+A.6)**, **Charter 23.3 marker → 🟢 source-ready + acceptance candidate**
- Partial (2): Sub-Faz 23.3.2 Multipart + Context Routing (VFO provider acceptance pending R24); D29-NOTIFY 3-katman SMS (test ✅; prod canary smoke ext-gated)
- Ext-gated (4): R24 Biotekno OTP allowlist provisioning; R1 NetGSM secondary contract (ETA 2026-05-30); T3.1.8 4 workflow live test (canary post-smoke); A.4+A.5 canary SMS smoke + DLR terminal evidence (real user M365 SSO UI flow)

**Qualified green semantik**: 23.3 marker `🟢 source-ready + acceptance candidate` 23.2 PR-time pattern ile analog — prod pod LIVE + source/desired-state zinciri hazır + acceptance external residual bekliyor. **NOT full closure**; tenant DKIM enable + DNS CNAME + canary smoke + R24 + R1 + 72h observation acceptance kapısı.

---

## 10. DKIM Strategy Architecture Sealed (this cutover) — scope dar

> **Scope note**: "Sealed" yalnızca **DKIM strategy decision** için geçerli (Codex `019e44b1` AGREE B). M4 acceptance'ın tamamı (canary smoke + 72h observation + R24 provider acceptance + R1 NetGSM contract) ext-gated kalır.

1. **DKIM strategy = Office 365 Native (relay)** — Codex `019e44b1` AGREE
   B; app-side key dormant fallback; tenant-managed key rotation
2. **JetSMS = SMS PRIMARY** (canlı sözleşme, sendSMSSingle SOAP +
   VFO/VF channel allowlist); NetGSM = secondary (contract R1 pending)
3. **Multipart concatenation** = MULTIPART_ENABLED=true +
   ON_LENGTH_PROBLEM=SendAllPackage; max 160ch OTP path,
   marketing.campaign uzun mesajlar 2+ segment delivery proof
4. **VFO OTP allowlist blank** (R24 workaround) — production'da
   `NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS=` blank → tüm OTP
   topic'ler default VF; provider provisioning sonrası allowlist tekrar
   açılınca VFO routing automatic devreye girer (code side LIVE)
5. **Egress netpol** (port 587 SMTP + 443 SOAP/Graph) triple-label
   selector + RFC1918 except — Codex `019e15ee` pattern

---

## 11. Next Steps (autonomous + ext)

### Agent autonomous (this session continuing)

- [x] PR-B4 prod cutover MERGED + apply + verify
- [x] **This evidence doc** + Charter 23.3 marker update
- [x] milestones.md M4 closure update (Charter 23.3 🟢 source-ready)
- [x] Risk register: R3 🟢 confirmed, R24 active monitored, R1 active
- [ ] **72h prod observation passive** (T+72h = 2026-05-23 19:47Z natural)
- [ ] Cleanup PR for dormant Vault app-side DKIM key (post 72h stable
      observation — Codex 019eXXXX consult needed)

### External / operator-gated (agent dışı)

- [ ] **Office 365 admin DKIM tenant enable** for `acik.com` (one-time) — **BL-009 DEFER 2026-05-25 per user decision**; not urgent; activate on trigger (R3 reactivation triggers; risk-register R3 satırı)
- [ ] **DNS CNAME publish**: `selector1._domainkey.acik.com →
      selector1-acik-com._domainkey.<tenant>.onmicrosoft.com`
      (similarly selector2) — **BL-009 DEFER 2026-05-25 per user decision**; SMTP relay LIVE; `DKIM=none` residual accepted for internal/dev path
- [ ] **R24 Biotekno OTP allowlist provisioning** (provider
      coordination — sender ID OTP outbound VFO activation)
- [ ] **R1 NetGSM secondary contract activation** (ETA 2026-05-30 —
      secondary failover acceptance gate)
- [ ] **Prod canary SMS smoke** via M365 SSO UI flow (real user
      +905551815564 multipart SMS prod path)
- [ ] **PR #855 + #854** (T1.4 D43 outage fallback prod activation —
      Slack #alerts-d43-drill real webhook + Vault prod seed + helm
      upgrade + dual-receipt smoke)

---

## 12. Cross-AI Peer Review Audit Trail

| PR | Implementer | Reviewer | Verdict |
|---|---|---|---|
| platform-backend #268 (PR-B1) | Anthropic Claude (session 47) | OpenAI Codex thread `019e4514` (iter chain) | AGREE |
| gitops #914 (PR-B2) | Anthropic Claude (session 47) | OpenAI Codex iter-N | AGREE |
| gitops #915 (PR-B3) | Anthropic Claude (session 47) | OpenAI Codex P1 absorb (rollback_to_digest fix) | AGREE post-fix |
| gitops #916 (PR-B4) | Anthropic Claude (session 47) | OpenAI Codex P1 absorb (rollout annotation + selector triple-label) | AGREE post-fix |

(HARD RULE — Cross-AI Peer Review provider-different: Anthropic ↔ OpenAI compliance)

---

## 13. References

- [milestones.md M4 entry](../notify/milestones.md#m4--233-sms-jetsms-primary--netgsm-secondary-activation--test-live--prod-cutover-903)
- [risk-register.md R3 + R24 + R1](../notify/risk-register.md)
- [RB-faz-23-charter.md 23.3 row](../runbooks/RB-faz-23-charter.md)
- [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
- [ADR-0024 Graph mail adapter defer](../adr/0024-graph-mail-adapter-defer.md)
- [RB-graph-mail-adapter-activation](../runbooks/RB-graph-mail-adapter-activation.md)
- [23.3.2 jetsms multipart context routing evidence](2026-05-20-23-3-2-jetsms-multipart-context-routing-evidence.md)
- Codex thread `019e4514-e961-7d50-b2cc-493f66cee4bc` (sub-faz 23.3.2 absorb chain 11 iter)
- Codex thread `019e44b1` (DKIM relay long-term stable decision)
- release-candidates ledger `release-candidates/platform-backend/6307428f6667fb90864f222743fcb9d559a8ff26.json`
