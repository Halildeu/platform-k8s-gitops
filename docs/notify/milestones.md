# Notification Platform — Milestone Tracker

> **Status**: ACTIVE (Session 39 PM artifact bootstrap 2026-05-09)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)
> **Sprint plan**: [sprint-plan.md](sprint-plan.md)
> **Risk register**: [risk-register.md](risk-register.md)

Bu doküman **target dates + critical path + go/no-go gates** sağlar. Milestone slip görünürlüğü + dependency chain visualization.

> **Faz 2 — GitHub Project migration (2026-05-17)** — Aktif milestone durum takibi [platform Roadmap board](https://github.com/users/Halildeu/projects/2) (`Faz 23` view · `Kind=milestone`) üzerinde. Bu doküman DoD / critical path / slip detayının canonical kaynağı kalır. Board mapping: M0 #752 · M1 #753 · M2 #754 · M3 #755 · M4 #756 · M5 #757 · M6 #758 · M7 #759 · M8 #760 · M9 #761.

---

## Milestone Roadmap

### M0 — Faz 23.0 Charter (✅ done 2026-05-05)

- 5 artifact merged (ADR-0013 + event-contract + feature-matrix + must-have-checklist + RB-faz-23-charter)
- PLAN.md Faz 23 entry + D38-D47
- 2026-05-09 Session 39 truth alignment PR #439

### M1 — 23.9 Cutover Closure (🟡 in progress, target 2026-05-12)

**Definition of Done**:
- [ ] T2.3.1 72h observation completion (T+72h = 2026-05-11 19:42Z natural)
- [ ] T2.3.2 Rollback prova execution (drill mode)
- [ ] T2.3.3 Browser SSO verify testai.acik.com
- [ ] T2.3.4 Browser SSO verify ai.acik.com
- [ ] T2.3.5 Evidence document published
- [ ] Charter 23.9 marker 🟡 → 🟢
- [ ] Risk register: R7 closed, R8 confirmed mitigated

**Blockers**: R7 (browser verify user availability)
**Owner**: ops + user
**Dependencies**: T2.3 task chain

### M2 — 23.1 D29-NOTIFY-Functional Evidence (🟢 accepted 2026-05-14 — board #754)

> **Closure (2026-05-18, board #754)**: D29-Functional 3-channel evidence 2026-05-14'te toplandı (`docs/faz-23-evidence/2026-05-14-m2-d29-functional-3-channel-live.md`). M2 scope = D29-**Functional** 3-channel + D29-Authorized **Layer 1** org-boundary. Layer 2 channel-level OpenFGA authz Faz 23.2 v2 scope'unda — DoD'de `[~]` ile ayrı işaretli. Cross-AI: Codex `019e3c74` REVISE-absorb (DoD split = overclaim değil rescope; verdict B: charter 23.1 sub-faz marker'ı bu kapanışta 🟢'a çevrilmez).

**Definition of Done**:
- [x] T2.1.1 Email D29-Functional — Mailpit message metadata + PG delivery row INSERT (provider_msg_id)
- [x] T2.1.2 Slack D29-Functional — test cluster mock incoming-webhook receiver POST 200 + PG delivery row (gerçek Slack workspace screenshot DEĞİL — test cluster'da workspace yok)
- [x] T2.1.3 Webhook D29-Functional — HMAC-signed POST + webhook-receiver 200 + PG delivery row
- [x] D29-Authorized **Layer 1** org-boundary — JWT `org_id` claim: allow HTTP 202, missing `org_id` deny HTTP 403
- [~] D29-Authorized **Layer 2** channel-level OpenFGA (`subscriber#can_receive`) — Faz 23.2 v2 / `m3-supplement-openfga-model-extension-plan` ayrı takip
- [x] Evidence document `docs/faz-23-evidence/2026-05-14-m2-d29-functional-3-channel-live.md`
- [~] Charter 23.1 marker — D29-Functional + Layer-1 closure accepted; 23.1 sub-faz **🟡 kalır** (acceptance tablosundaki Layer-2 `subscriber#can_receive` kriteri 23.2 v2'ye taşınana/kanıtlanana dek — Codex `019e3c74` verdict B)

**Blockers**: None
**Owner**: ops
**Dependencies**: M1 (cluster stable)

### M3 — 23.2 Production MVP Dar Closure (🟡 ALMOST CLOSED — 2026-05-14 audit)

**Status update 2026-05-14 (Session 49)**: 7/8 task done. Tek blocker R2 KVKK legal review (external dependency).

**Status revision 2026-05-19 (Session 42, Codex `019e4234`)**: T1.4 D43 closure dili gözden geçirildi — test drill SMTP-only kanıt + Slack leg sentinel-only (NXDOMAIN `drill-slack-mock.local`) realitesi "first controlled drill mitigation"u overclaim haline getirmişti. T1.4 `[x]` → `[~]` partial; R9 `🟢` → `🟡` partial. Faz 23.2 M3 kabul sayısı **6/8** (T1.2 R2 + T1.4 D43 partial). External blocker'lar: (a) R2 KVKK legal review (legal), (b) Slack `#alerts-d43-drill` real webhook + prod Vault seed (operator).

**Status revision 2026-05-20 (Session 42, Codex `019e44b1` defer contract alignment)**: M3 mail delivery yüzeyi için ek netlik — **SMTP Office 365 path canonical confirmed** (`ai@acik.com` + App Password Vault'ta + `SmtpAdapter` LIVE); Microsoft Graph mail adapter (backend PR #153 + gitops PR #872 staged) **deferred, M3 blocker DEĞİL**. D49 strategy ([ADR-0024](../adr/0024-graph-mail-adapter-defer.md) + [RB-graph-mail-adapter-activation.md](../runbooks/RB-graph-mail-adapter-activation.md) + [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) P3 Backlog): Entra `acik-mail-graph-api` + Mail.Send + admin consent **asset olarak korunur**; client_secret + ApplicationAccessPolicy + Vault seed + flag flip reactivation chain trigger geldiğinde 5-adım atomic. M3 acceptance unchanged (still 6/8); R23 yeni risk entry (mitigation: Entra asset preserved + reactivation chain documented; aktif risk sıfır).

**Status revision 2026-05-21 (Session 47, Codex `019e4950` AI proxy review absorb)**: R2 KVKK için **Codex AI proxy review** yapıldı (`PARTIAL_COMPLIANT + RISK_FLAGGED` verdict). 7 risk (3 P0 + 3 P1 + 1 P2) identified; agent autonomous fix PR'ları açıldı: **PR-K2 + PR-K3** (provider propagation matrix + backup tombstone runbook) docs-only **2026-05-21 MERGED**; **PR-K4 + PR-K7** (log redaction + KVKK runbook refresh) **2026-05-21 MERGED**; **PR-K1** (erasure ledger + 30-gün SLA V18 migration backend — PR #274) **Codex `019e499c` iter-3 AGREE / `ready_to_merge: true`** (CI pending → auto-merge); **PR-K5 + PR-K6** (audit pseudonymize + tenant DPO authz) backlog (P1, R2 closure blokelemiyor). **5/7 risk MERGED veya AGREE merge pending**; implementation-side ~85% closure. **DPO/legal final onay**: Codex verdict "audit trail'e konabilir 'AI proxy review tamamlandı'; ama 'KVKK legal review tamamlandı' yerine geçmez". External blocker R2 final closure DPO sign-off bekliyor (SLA 2026-05-25). Evidence: [docs/faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md](../faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md).

**Definition of Done** (must-have #6 + #7 + #8 + #9 + #10 fully closed):
- [x] T1.1 23.2.A Preference API + critical bypass merged + LIVE — Session 41 acceptance evidence
- [~] T1.2 23.2.B KVKK erasure + right-to-information merged + LIVE — **subscriber self-service LIVE**; admin erasure source-ready, R2 legal review external pending
- [x] T1.3 23.2.C Provider config rollback merged — platform-backend PR #140 MERGED (2026-05-10, R12 mitigated FULL ACCEPTANCE evidence)
- [~] T1.4 23.2.D Outage fallback bypass D43 merged + **partial drill** executed — first controlled test drill 2026-05-10 (Mailpit SMTP receipt LIVE; Slack leg sentinel-only, NXDOMAIN `drill-slack-mock.local`); **prod activation source-incomplete** (helm-values direct-fallback receiver/route eksikti — PR #855 staged config kapatır; Vault prod seed + helm upgrade + dual-receipt smoke owner-gated). R9 **partial mitigation** (Codex thread `019e4234` Session 42 audit). Real test webhook + prod activation: board issues #853 + #854.
- [x] T1.5 23.2.E Data classification policy merged — 2026-05-10 LIVE acceptance
- [x] T1.6 23.2.F Abuse prevention guards merged — Session 41 FULL ACCEPTANCE (R13+R19 mitigated)
- [~] All Faz 23.2 kabul kriteri 🟡 (7/8 done, 1 external blocker)
- [~] Charter 23.2 marker 🟢 source-ready + acceptance candidate — final legal closure R2 sonrası
- [~] Risk register: R2 active (KVKK legal review), R9 🟡 partial (Codex `019e4234` Session 42 audit: test SMTP drill LIVE; Slack leg sentinel-only #853; prod activation source-incomplete → PR #855 staged config + #854 owner-gated), R12 🟢 mitigated, R13 🟢 mitigated, R19 🟢 mitigated, **R23 🟡 active monitored** (Graph mail adapter deferred; SMTP canonical; Entra asset preserved; reactivation chain documented in ADR-0024 + RB-graph-mail-adapter-activation.md + #892)

**Remaining blocker**: R2 (KVKK legal review external) — admin erasure compliance attestation. ETA 2026-05-25.
**Owner**: legal (R2 closure)
**Dependencies**: cluster stability dependency satisfied; M1 browser SSO/cutover closure tracked separately

### M4 — 23.3 SMS JetSMS primary + NetGSM secondary Activation (🟢 PROD LIVE 2026-05-20 — source-ready + acceptance candidate)

> **Provider kararı 2026-05-19 (kullanıcı)**: SMS primary JetSMS (canlı sözleşme), secondary NetGSM. Multi-provider 5-PR sequence (PR-0 docs + PR-1 SmsProvider abstraction + PR-2 JetSmsProvider send/failover + PR-3 JetSMS DLR polling + PR-4 gitops base configmap + PR-5 test overlay cutover) — Codex `019e3f82` AGREE.

> **Status revision 2026-05-20 (Session 42+, Codex `019e45db` REVISE)**: M4 5-PR sequence MERGED + **test cluster JetSMS LIVE acceptance** (full happy-path: ACCEPTED + DLR DELIVERED terminal state). Initial HTTP 5xx retry **transient** classify; SOAP transport ACCEPTED + DlrPollingWorker DELIVERED. Prod cutover **multi-blocker** (prod ESO Graph aggregate Ready=False + imageID bump + configmap primary=jetsms flip + egress NetworkPolicy gap) → child issue [#903](https://github.com/Halildeu/platform-k8s-gitops/issues/903) Codex 9-step acceptance smoke gates.

> **Status revision 2026-05-21 (Session 47, Codex `019e4965` AGREE PARTIAL absorb — prod canary 403 strict-mode evidence)**: M4 prod canary SMS attempt via browser MCP + M365 SSO session **strict-denied** (HTTP 403). Bu **canary fail değil**: D29-Authorized Layer-1 **strict isolation PASS** evidence (`NOTIFY_SECURITY_DEFAULT_ORG_ID=""` Faz 24 PR-5.5 cutover live + JWT'de tenant claim yoksa fail-closed + raw JWT log/audit'te yok). D29-Up + D29-Authorized Layer-1 prod evidence triplet 🟢; D29-Functional prod SMS+DLR pending (KC operator gate: `org_id=default` claim setup runbook `docs/runbooks/RB-prod-canary-kc-claim-setup.md`). M3 R2 KVKK closure dili bu evidence ile kullanılmaz (Codex `019e4950` PARTIAL_COMPLIANT verdict ayrı).

> **Status revision 2026-05-20 (Session 47, post PR-B4 cutover RE-ATTEMPT MERGED)**: **M4 prod cutover LIVE** — PR-B1 (platform-backend #268 notify.dkim.strategy enum) + PR-B2/B3 (gitops #914/#915 test+prod overlay DKIM relay) + PR-B4 (gitops #916 prod cutover RE-ATTEMPT JetSMS PRIMARY + netpol 587/443) zinciri MERGED 2026-05-20T20:14Z. Prod pod sha-6307428 Running 1/1 + SmtpAdapter `dkimEnabled=false` (relay strategy) + SmsAdapter `primary=jetsms secondary=(none)` + ProductionConfigValidator `all production guards PASSED` + JetSmsDlrPollingWorker `scheduling=true` + Started in 37.7s (önceki PR #911 crashloop strategy enum öncesi DKIM strict gate fail-closed — same-incident reconciliation revert PR #912 + strategy enum hardening ile resolve). **DKIM strategy architecture sealed (scope dar — sadece DKIM signing decision)** (Codex `019e44b1` AGREE B): DKIM = Office 365 Native CNAME pattern (provider-managed key rotation), app-side key Vault'ta dormant fallback. **M4 acceptance'ın tamamı NOT sealed**: canary smoke + 72h observation + R24 provider acceptance + R1 NetGSM contract ext-gated kalır. **R3 🟢 mitigated upgraded**; **R24 🟡 active monitored** (`NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS=` blank workaround prod'da); **R1 🟡 active** (NetGSM secondary contract ETA 2026-05-30). Evidence: [docs/faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md](../faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md).

> **Sub-Faz 23.3.2 routing/multipart closure 2026-05-20 (Session 47, Codex `019e4514` 11 iter)**: Multipart + context routing decision logic + actual_channel audit (VF accepted path) chain MERGED + test cluster LIVE. Backend chain PR #262/#263/#264/#265/#266/#267 + GitOps PR #903/#905/#908 (sha-6ed593e). 3-senaryo canary smoke: VFO routing-log proof (Scenario A) + VF default delivered (Scenario B) + VF explicit fallback overlength delivered (Scenario C) — Codex P2+P3 absorb. Real-world: kullanıcı +905551815564 multipart SMS DELIVERED (B: 1 seg, C: 2 segments). **VFO provider acceptance PENDING R24**: JetSMS Biotekno sender ID OTP allowlist provisioning gap (ErrorCode=04 reject); routing logic LIVE, provider config gap. Evidence: [docs/faz-23-evidence/2026-05-20-23-3-2-jetsms-multipart-context-routing-evidence.md](../faz-23-evidence/2026-05-20-23-3-2-jetsms-multipart-context-routing-evidence.md).

**Definition of Done**:
- [x] PR-1 `SmsProvider` interface + `SmsAdapter` facade + `NetGsmProvider` refactor (behavior-neutral) — platform-backend [#249](https://github.com/Halildeu/platform-backend/pull/249) MERGED
- [x] PR-2 `JetSmsProvider` HTTP API + failover matrix LIVE — platform-backend [#250](https://github.com/Halildeu/platform-backend/pull/250) MERGED
- [x] PR-3 JetSMS DLR polling worker + generic DlrIngest core LIVE — platform-backend [#252](https://github.com/Halildeu/platform-backend/pull/252) MERGED
- [x] PR-4 gitops base ConfigMap (JetSMS endpoint URL'leri) — gitops Codex thread `019e4022` MERGED (`kustomize/base/apps/notification-orchestrator/configmap.yaml` line 62-72)
- [x] PR-5 test overlay cutover (image digest sha-ab333c5 + `NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER=jetsms` ATOMİK flip) — gitops MERGED 2026-05-19 (`kustomize/overlays/test/kustomization.yaml` line 2533+)
- [x] **Test cluster JetSMS LIVE acceptance** (2026-05-20 live evidence):
  - `SmsAdapter activated: primary=jetsms secondary=(none) registered=[netgsm, jetsms]`
  - `JetSmsDlrPollingWorker activated: batchSize=100 pollInterval=PT1M`
  - `jetsms SOAP ACCEPTED (awaits DLR poll): msg_id=jetsms-260520174749808291`
  - `sms primary=jetsms result status=ACCEPTED class=NONE`
  - `dlr jetsms UPDATED: code=1 delivery_id=116 prior=ACCEPTED new=DELIVERED` (+ delivery_id 117 + ongoing)
- [~] **Sub-Faz 23.3.2 Multipart + Context Routing LIVE (test-live status revision; VFO provider acceptance pending R24)** (2026-05-20 PR-A1 → PR-A3.2 chain, Codex `019e4514`):
  - Backend PRs #262/#263/#264/#265/#266/#267 MERGED (test coverage 223/223 SMS + 769/769 unit)
  - GitOps PRs #903/#905/#908 MERGED (sha-6ed593e digest atomic)
  - 3-senaryo canary smoke yürütüldü:
    - Scenario A (auth.mfa-otp short, VFO): **routing-log proven**; provider acceptance FAIL (R24 ErrorCode=04)
    - Scenario B (marketing.campaign, VF): **DELIVERED** msg_id=jetsms-2605202027306017971
    - Scenario C (auth.mfa-otp overlength 209ch, VF fallback): **DELIVERED** 2 segments msg_id=jetsms-260520203006838196
  - actual_channel audit propagation (VF accepted path) LIVE (DELIVERY_ACCEPTED.details B + C kanıtı)
  - Codex P2+P3 absorb LIVE (actual_channel audit + explicit CHANNEL_VF config drift hardening)
  - **PENDING**: VFO provider acceptance (R24) + actual_channel=VFO audit (R24 sonrası)
  - Evidence doc: [2026-05-20-23-3-2-jetsms-multipart-context-routing-evidence.md](../faz-23-evidence/2026-05-20-23-3-2-jetsms-multipart-context-routing-evidence.md)
- [~] D29-NOTIFY 3-katman SMS evidence — TEST cluster ✅ (D29-Up + D29-Functional + D29-Multipart + D29-ContextRouting + D29-actualChannel); prod canary smoke ext-gated (real user M365 SSO UI flow)
- [ ] T3.1.8 4 workflow live test passed (admin invite, password reset, drift alarm, break-glass) — ext canary post-cutover
- [~] **Prod cutover** (issue [#903](https://github.com/Halildeu/platform-k8s-gitops/issues/903)) — **agent-actionable items LIVE 2026-05-20** (PR-B1+B2+B3+B4 zincir):
  - [x] A.1 prod ESO aggregate blocker resolution (Graph `graph_*` D49 defer-aware, PR #906 MERGED)
  - [x] A.2 prod overlay imageID + primary=jetsms flip PR (atomic, PR-B4 #916 MERGED)
  - [x] A.3 prod egress 443 NetworkPolicy gap close (`netpol-notification-egress-mail-providers.yaml`, PR-B4 #916)
  - [~] A.4 canary SMS smoke (provider=jetsms test) — **attempted 2026-05-21 via browser MCP + M365 SSO**; HTTP 403 strict-mode deny (Codex `019e4965` AGREE: D29-Authorized Layer-1 PASS evidence, functional canary ext-gated KC operator `org_id` claim setup gerek — RB-prod-canary-kc-claim-setup.md)
  - [ ] A.5 DLR terminal state evidence — **ext-gated** (A.4 functional canary sonrası natural; pipeline LIVE scheduling=true)
  - [x] A.6 rollback plan documented (evidence doc §7 + release-candidates ledger `rollback_to_digest: sha-70491543`)
- [x] **Charter 23.3 marker → 🟢 source-ready + acceptance candidate** (this PR-B5 #918) — qualified green: prod pod LIVE + source/desired-state hazır + ext residual acceptance bekliyor (NOT full closure; 23.2 PR-time pattern ile analog)
- [ ] Risk register: R1 — NetGSM secondary failover acceptance closed (JetSMS-primary live ayrı hüküm; R1 ETA 2026-05-30) — **ext-gated**

**Blockers**: R1 (NetGSM secondary contract delay — failover acceptance blocker; JetSMS primary activation blocker DEĞİL — JetSMS-only degraded mode acceptable per kullanıcı 2026-05-19); prod canary smoke ext-gated (real user M365 SSO UI flow); R24 ext (Biotekno OTP allowlist provisioning)
**Owner**: ops + dev + legal (NetGSM secondary contract); gitops/ops (prod cutover gates)
**Dependencies**: M3 (23.2 stable)

### M5 — 23.5 Preference UI (🟢 source-ready + acceptance candidate — Session 47 audit 2026-05-21)

> **Status revision 2026-05-21 (Session 47, Codex `019e472f` REVISE audit)**: M5 23.5 büyük ölçüde MERGED — daha önce yanlışlıkla 🔴 target olarak takip ediliyordu. Gerçek durum: platform-web PR #285 (Faz 23.5 PR3 preferences UI page + RTK Query client), #286 (PR4 bulk mark-all-read), #288 (PR5 docs operator guide), #291 (PR6 mfe-audit delivery logs tab), #296 (PR-hardening canonical subscriberId selector), #299 (Faz 23.6 PR-B1 richer preference editor with quiet hours), #301 (PR-C2 mute-channel UI two-stage confirm) MERGED. `NotificationPreferencesPage.tsx` + `NotificationPreferenceForm.tsx` + `quiet-hours.ts` canonical model + RTK Query API (`notify-prefs.api.ts`) + unit testler LIVE.
>
> **Gap-fill closure 2026-05-21**: G2 (Backend PreferenceTopicCatalog — platform-backend PR #269), G3 (Frontend public unsubscribe landing — platform-web PR #642), G4 (Playwright cluster smoke — platform-web PR #646) **3/3 MERGED**. Charter 23.5 marker `[~]` source-ready + acceptance candidate kalır; full 🟢 closure final board acceptance + live cluster smoke runtime evidence sonrası.

**Definition of Done**:
- [x] T3.2 mfe-shell preference settings page LIVE — `/settings/notifications` route (Faz 23.5 PR3 platform-web PR #285 MERGED)
- [x] Per-channel + per-topic + quiet hours + frequency limit UI — `NotificationPreferenceForm.tsx` drawer-based rich editor (Faz 23.6 PR-B1 platform-web PR #299 MERGED)
- [x] Bulk mute-channel + restore-defaults two-stage confirm — `NotificationPreferencesPage.tsx` (Faz 23.6 PR-C1+C2 platform-web PR #301 MERGED)
- [x] Operator guide docs LIVE — Faz 23.5 PR5 platform-web PR #288 MERGED
- [~] D29-NOTIFY UI flow evidence — Vitest unit testler + Playwright e2e smoke MERGED (`__tests__/notify-prefs.api.test.ts`, `__tests__/NotificationPreferencesPage.test.tsx`, PR #646 e2e); live cluster runtime acceptance pending
- [x] **G2 Backend PreferenceTopicCatalog endpoint** — platform-backend PR #269 MERGED 2026-05-20T21:37Z (`GET /api/v1/notify/topics/me` + TopicCatalogProperties + TopicCatalogService; 10/10 unit pass; sha-99df4f9b cumulative)
- [x] **G3 Frontend public unsubscribe landing** — platform-web PR #642 MERGED (`/notifications/unsubscribe` route + success/expired/invalid states)
- [x] **G4 Playwright cluster smoke** — platform-web PR #646 MERGED (preferences page + unsubscribe e2e smoke)
- [~] Charter 23.5 marker → 🟢 source-ready + acceptance candidate (this PR-G1; full closure final board acceptance + live cluster runtime evidence sonrası)

**Blockers**: None (T1.1 backend preference API LIVE; M3 stable)
**Owner**: dev (frontend + backend gap-fill)
**Dependencies**: T1.1 (preference API) ✅ LIVE, M3 ✅ source-ready

### M6 — 23.4 Closure (🟡 split into M6a + M6b — Codex iter-2 absorb)

> **Split rationale (2026-05-09)**: 23.4 closure iki bağımsız part'a bölündü; M6a (archive + history filter) M3 ile paralel, M6b (SMS DLR UI) M4 sonrası gate'lidir.

#### M6a — 23.4 Archive + History (🟡 target 2026-06-15, parallel with M3)

**Definition of Done**:
- [ ] T2.2.1 Archive UI button
- [ ] T2.2.2-3 30d notification history filter (FE + BE)
- [ ] T2.2.4 Integration test (archive + history)
- [ ] Charter 23.4 marker (archive/history portion) 🟡 → 🟢

**Blockers**: None (parallel with M3)
**Owner**: dev (frontend + backend)
**Dependencies**: M1 stable (cluster + auth)

#### M6b — 23.4 SMS DLR UI (🔴 target post-M4, ~2026-06-29)

**Definition of Done**:
- [ ] FE inbox SMS DLR badge (status: sent/delivered/failed)
- [ ] T3.1.7 DLR callback endpoint LIVE (M4 dep)
- [ ] Charter 23.4 marker (SMS DLR portion) ⏳ → 🟢
- [ ] Charter 23.4 fully 🟢 only when both M6a + M6b done

**Blockers**: M4 (SMS JetSMS primary + NetGSM secondary + DLR dual-mode)
**Owner**: dev (frontend)

### M7 — v1 Closure (🟡 target 2026-08-15)

**Definition of Done**:
- [x] T4.1 23.6 Teams + Slack threading LIVE (Slack Block Kit PR #271 + Teams Power Automate PR #272 — sha-f40aa82+)
- [ ] T4.2 23.7 Push (FCM + APNS + Web Push) LIVE
  - [x] **Web Push (browser-only) backend scaffold MERGED** (Faz 23.7 — sha-aaf5f09 deploy 2026-05-21 12:46Z; defer-aware ENABLED=false until Vault VAPID seed + UI button integration):
    - PR-W1 #277: V19 subscriber_push_endpoint + entity + repo
    - PR-W2.1 #278: WebPushConfig + VapidKeyService + nl.martijndwars:web-push lib
    - PR-W2.2 #279: WebPushAdapter + status mapping + endpoint cleanup
    - PR-W2.3 #280: DefaultWebPushSender real lib integration
    - PR-W2.4 #281: DefaultWebPushSenderHttpIntegrationTest WireMock 3.x end-to-end (Codex 019e4a2e AGREE)
    - PR-W2.5+W2.6 #282: IntentSubmissionService allow-list + DeliveryPlanService fan-out + DeliveryEligibilityService BLOCKED_NO_PUSH_ENDPOINT + V20 migration (Codex 019e4a3d iter-4 AGREE)
    - PR-W3 #283: PushSubscriptionController + Service + atomic upsert (Codex 019e4a57 iter-3 AGREE)
    - PR-W4 platform-k8s-gitops #939: ConfigMap WebPush 5 entries + ExternalSecret defer-aware + overlay digest bump (Codex 019e4a70 iter-2 AGREE)
    - PR-W5 platform-web #648: mfe-shell service worker + notify-push.api + helpers + usePushSubscription hook (Codex 019e4a87 iter-2 AGREE — bekleyen merge)
  - [ ] **Web Push activation pending** (operator action + UI integration follow-up):
    - Vault VAPID 3-key seed (vapid_public_key + vapid_private_key + vapid_subject) — kv/platform/notification-orchestrator
    - ExternalSecret WEBPUSH 3 remoteRef entries uncomment
    - Test overlay ConfigMap patch: NOTIFY_ADAPTERS_WEBPUSH_ENABLED=true
    - UI button integration + VAPID public key Vite env (VITE_NOTIFY_VAPID_PUBLIC_KEY)
    - Browser end-to-end smoke (Chrome MCP / Playwright)
  - [ ] **Mobile FCM/APNS** — Faz 22.2 dep, scope DIŞI (gelecek faz)
- [ ] T4.3 23.8 Tempo + bounce loop + per-tenant Grafana LIVE
  - [x] T4.3.a Tempo OTLP trace export LIVE (2026-05-21 09:17Z; 5 spans verified)
  - [x] T4.3.b email suppression core LIVE (PR #270 — sha-f40aa82)
  - [ ] Per-tenant Grafana dashboard (M7 closure scope)
- [ ] All v1 sub-faz kabul kriteri 🟢 (23.6, 23.7, 23.8)
- [ ] Charter markers all updated
- [ ] Risk register: R11, R16 closed

**Out of scope (v1 — future-proofing track):**
- Microsoft Graph mail adapter activation — **defer karar D49 / ADR-0024** (Session 42 2026-05-20, Codex `019e44b1`). SMTP Office 365 path canonical kalır; Graph adapter binary backend ready (PR #153) ve gitops staged (PR #872) ama activation trigger-driven future-only ([RB-graph-mail-adapter-activation.md](../runbooks/RB-graph-mail-adapter-activation.md) + [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) P3 Backlog). R23 active monitored.

**Blockers**: M5 done + M6a/M6b done (split closure) — M3 + M4 zaten önceki kapı
**Owner**: dev + ops + gitops

### M8 — Multi-tenant Trigger Gate (🔴 target 2026-09-01)

**Definition of Done** (Faz 21 multi-tenant öncesi):
- [ ] M7 v1 stable (≥30 day in production)
- [ ] R10 (multi-tenant migration risk) mitigation plan ready
- [ ] Pre-migration audit + dry-run + per-tenant isolation test
- [ ] Faz 21 charter draft

**Blockers**: M7 v1 stable + R10 mitigation
**Owner**: dev + arch (Codex strategic consultation)

### M9 — Faz 23.X v2 Trigger (🔴 deferred — gerekçe çıkarsa)

**Definition of Done**:
- v1 stable + müşteri/ops gerekçesi açık
- Codex strategic retrospective verdict
- 8-12 hafta planning

**Trigger condition**: Customer or ops requirement clearly identified.

---

## Critical Path Visualization

```
                             ┌─── M2 (D29 evidence)  ─── parallel
                             │
M0 ──▶ M1 ───────────────────┼──▶ M3 ─────▶ M4 ──┬──▶ M6b ──┐
(charter)  (cutover)         │   (23.2)   (SMS)  │  (DLR UI)│
                             │     │             ▼          │
                             │     ▼          M5 (UI)       ▼
                             │   Risk gates:                M7 ──▶ M8 ──▶ M9
                             │   R2 KVKK, R9 D43            (v1)  (mt)  (v2)
                             │   R13 abuse, R19 storm
                             │
                             └─── M6a (archive/history) ─── parallel with M3
```

**Critical path** (longest dependent chain):
**M0 → M1 → M3 → M4 → M5 → M7 → M8**

**Parallel tracks**:
- M2 (D29 evidence) parallel with M1 closure
- M6a (23.4 archive/history) parallel with M3 (23.2)
- M6b (23.4 SMS DLR UI) gated by M4 (post-SMS); not on critical path
- M5 (Preference UI) blocked by M3 backend (T1.1)
- M7 v1 sub-faz tracks (23.6/23.7/23.8) parallel after M5 unblocked

---

## Slip Detection

**Weekly review**:
- Compare actual vs target date
- Update milestone status
- If >7 day slip: trigger Codex strategic retrospective
- If >14 day slip: stakeholder notification + scope re-baseline

**Sub-faz acceptance gate**: NO milestone marked 🟢 unless ALL DoD items 🟢.

---

## Status Legend

- 🟢 **Done**: ALL DoD items closed; evidence path filled
- 🟡 **In Progress**: substantial work done, some DoD items pending
- 🔴 **Pending**: not started or blocked
- 🚧 **Blocked**: external dependency unmet (R1, R7 etc)

---

## Last Update

> **Historical snapshot kaldırıldı (Faz 2 migration 2026-05-17)** — Eski "Current state" 2026-05-09 (Session 39) dondurulmuş bir milestone kopyasıydı (M3-M9 🔴 pending) ve hem bu dosyanın M3 bölümüyle (2026-05-14 ALMOST CLOSED) hem board-canonical kuralıyla çelişiyordu. Güncel milestone durumu: **[platform Roadmap board](https://github.com/users/Halildeu/projects/2)** `Kind=milestone` (#752-761).
