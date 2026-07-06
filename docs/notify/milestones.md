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

### M1 — 23.9 Cutover Closure (🟢 FULL CLOSURE — 2026-05-14 Session 49 evidence)

**Status revision 2026-05-23 (M1/23.9 doc reconciliation, Codex `019e53c1` AGREE A1)**: M1 DoD bütün maddeler 2026-05-14 Session 49'da kapatıldı (evidence: [docs/faz-23-evidence/2026-05-14-m1-23-9-cutover-closure-evidence.md](../faz-23-evidence/2026-05-14-m1-23-9-cutover-closure-evidence.md)) ama bu milestones M1 section + charter 23.9 section + sprint-plan T2.3 syncronize edilmemiş; bu reconciliation truth alignment yapıyor. Charter top table (line 57) "FULL CLOSURE Session 49 2026-05-14" zaten doğru; çekisirgan stale yalnız ikincil bölümlerde.

**Definition of Done**:
- [x] T2.3.1 72h observation completion (T+72h = 2026-05-11 19:42Z natural) — 0 ERROR, DLQ=0, alerts inactive/correctly-pending throughout 72h
- [x] T2.3.2 Rollback prova execution — ADR-0010 §2.5 + drill 2026-05-10 (R8 mitigated)
- [x] T2.3.3 Browser SSO verify **testai.acik.com** — Session 49 M2 evidence: `d29-evidence-tester` JWT mint + `/api/v1/authz/me` HTTP 200
- [x] T2.3.4 Browser SSO verify **ai.acik.com** — Session 49 evidence: `d29-prod-sso-tester` persona + JWT mint + `/api/v1/authz/me` HTTP 200 (Pre-Production Full Authority HARD RULE — agent headless tool, R7 mitigated)
- [x] T2.3.5 Evidence document published — `docs/faz-23-evidence/2026-05-14-m1-23-9-cutover-closure-evidence.md`
- [x] Charter 23.9 marker 🟡 → 🟢 — charter table line 57 reflects FULL CLOSURE
- [x] Risk register: R7 🟢 Closed (2026-05-14), R8 🟢 Mitigated

**Blockers**: None — M1 fully closed.
**Owner**: — (M1 closed)
**Dependencies**: T2.3 task chain ✅

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

### M3 — 23.2 Production MVP Dar Closure (🟢 CLOSED — 2026-05-23 Codex `019e5189` legal verdict)

**Status update 2026-05-14 (Session 49)**: 7/8 task done. Tek blocker R2 KVKK legal review (external dependency).

**Status revision 2026-05-19 (Session 42, Codex `019e4234`)**: T1.4 D43 closure dili gözden geçirildi — test drill SMTP-only kanıt + Slack leg sentinel-only (NXDOMAIN `drill-slack-mock.local`) realitesi "first controlled drill mitigation"u overclaim haline getirmişti. T1.4 `[x]` → `[~]` partial; R9 `🟢` → `🟡` partial. Faz 23.2 M3 kabul sayısı **6/8** (T1.2 R2 + T1.4 D43 partial). External blocker'lar: (a) R2 KVKK legal review (legal), (b) Slack `#alerts-d43-drill` real webhook + prod Vault seed (operator).

**Status revision 2026-05-20 (Session 42, Codex `019e44b1` defer contract alignment)**: M3 mail delivery yüzeyi için ek netlik — **SMTP Office 365 path canonical confirmed** (`ai@acik.com` + App Password Vault'ta + `SmtpAdapter` LIVE); Microsoft Graph mail adapter (backend PR #153 + gitops PR #872 staged) **deferred, M3 blocker DEĞİL**. D49 strategy ([ADR-0024](../adr/0024-graph-mail-adapter-defer.md) + [RB-graph-mail-adapter-activation.md](../runbooks/RB-graph-mail-adapter-activation.md) + [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) P3 Backlog): Entra `acik-mail-graph-api` + Mail.Send + admin consent **asset olarak korunur**; client_secret + ApplicationAccessPolicy + Vault seed + flag flip reactivation chain trigger geldiğinde 5-adım atomic. M3 acceptance unchanged (still 6/8); R23 yeni risk entry (mitigation: Entra asset preserved + reactivation chain documented; aktif risk sıfır).

**Status revision 2026-05-21 (Session 47, Codex `019e4950` AI proxy review absorb)**: R2 KVKK için **Codex AI proxy review** yapıldı (`PARTIAL_COMPLIANT + RISK_FLAGGED` verdict). 7 risk (3 P0 + 3 P1 + 1 P2) identified; agent autonomous fix PR'ları açıldı: **PR-K2 + PR-K3** (provider propagation matrix + backup tombstone runbook) docs-only **2026-05-21 MERGED**; **PR-K4 + PR-K7** (log redaction + KVKK runbook refresh) **2026-05-21 MERGED**; **PR-K1** (erasure ledger + 30-gün SLA V18 migration backend — PR #274) **Codex `019e499c` iter-3 AGREE / `ready_to_merge: true`** (CI pending → auto-merge); **PR-K5 + PR-K6** (audit pseudonymize + tenant DPO authz) backlog (P1, R2 closure blokelemiyor). **5/7 risk MERGED veya AGREE merge pending**; implementation-side ~85% closure. **DPO/legal final onay**: Codex verdict "audit trail'e konabilir 'AI proxy review tamamlandı'; ama 'KVKK legal review tamamlandı' yerine geçmez". External blocker R2 final closure DPO sign-off bekliyor (SLA 2026-05-25). Evidence: [docs/faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md](../faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md).

**Status revision 2026-05-23 (Codex `019e5189` final legal verdict — R2 CLOSED)**: Kullanıcı kararı "hukuk onaylarını Codex istişaresinde Codex'in verdiklerini kabul edeceğiz" uyarınca Codex final legal verdict (thread `019e5189`, model_reasoning_effort=high) **AGREE** — R2 KVKK uyumu M3 closure için kabul edilebilir; 3 P0 + Madde 12/13.2/11.4 riskleri 6/7 K-PR MERGED ile kapalı (K1-K5+K7). K6 tenant-scoped DPO authz P1 non-blocking follow-up (23.2.B). **M3 🟢 CLOSED**; R2 risk-register 🟢 Mitigated. Evidence: [docs/faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md](../faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md) §R2 FINAL CLOSURE.

**Definition of Done** (must-have #6 + #7 + #8 + #9 + #10 fully closed):
- [x] T1.1 23.2.A Preference API + critical bypass merged + LIVE — Session 41 acceptance evidence
- [x] T1.2 23.2.B KVKK erasure + right-to-information merged + LIVE — subscriber self-service + admin erasure LIVE; R2 legal review closed via Codex `019e5189` final verdict AGREE (kullanıcı kararı: Codex istişare verdict'i = kabul edilen hukuk onayı)
- [x] T1.3 23.2.C Provider config rollback merged — platform-backend PR #140 MERGED (2026-05-10, R12 mitigated FULL ACCEPTANCE evidence)
- [x] T1.4 23.2.D Outage fallback bypass D43 merged + **SMTP-only D43 v1 accepted** per user decision 2026-05-24 (Codex strategic thread `019e5b9c` REVISE absorb). D43 v1 acceptance = Alertmanager direct-fallback SMTP receiver. Historical drill evidence retained as drill audit only: first controlled drill 2026-05-10 Mailpit SMTP receipt 00:22:33Z + BL-008 mock-receipt drill 2026-05-24 16:14-16:26Z (webhook-receiver POST + Mailpit dual). **Slack adoption DEFER future trigger**. R9 🟢 Mitigated (SMTP-only D43 v1; Slack DEFER). Evidence: `docs/faz-23-evidence/2026-05-24-d43-slack-defer-smtp-only-acceptance.md`. **Prod activation** board [#854](https://github.com/Halildeu/platform-k8s-gitops/issues/854) rescope (SMTP-only direct fallback smoke + Operator v0.90.1 `auth_*_file` schema fix); original board [#853](https://github.com/Halildeu/platform-k8s-gitops/issues/853) + [#1012](https://github.com/Halildeu/platform-k8s-gitops/issues/1012) (Slack-dependent) → DEFER.
- [x] T1.5 23.2.E Data classification policy merged — 2026-05-10 LIVE acceptance
- [x] T1.6 23.2.F Abuse prevention guards merged — Session 41 FULL ACCEPTANCE (R13+R19 mitigated)
- [x] All Faz 23.2 kabul kriteri 🟢 (8/8 — R2 Codex `019e5189` legal verdict ile kapandı)
- [x] Charter 23.2 marker 🟢 done — R2 final legal closure Codex `019e5189` (2026-05-23)
- [x] Risk register: R2 🟢 Mitigated (Codex `019e5189` legal verdict 2026-05-23), R9 🟢 **Mitigated (SMTP-only D43 v1; Slack DEFER per user decision 2026-05-24)** (Codex `019e5b9c` REVISE absorb; historical BL-008 mock-receipt drill + 2026-05-10 first controlled drill = drill audit only, no longer v1 acceptance gate; prod SMTP-only activation board #854 rescope operator-external; #853 + #1012 Slack-dependent → DEFER), R12 🟢 mitigated, R13 🟢 mitigated, R19 🟢 mitigated, **R23 🟡 active monitored** (Graph mail adapter deferred; SMTP canonical; Entra asset preserved; reactivation chain documented in ADR-0024 + RB-graph-mail-adapter-activation.md + #892)

**Remaining blocker**: None — R2 closed via Codex `019e5189` final legal verdict (2026-05-23, kullanıcı kararı: Codex istişare verdict'i = kabul edilen hukuk onayı). K6 tenant-scoped DPO authz P1 non-blocking follow-up (23.2.B).
**Owner**: — (R2 closed; K6 follow-up dev 23.2.B)
**Dependencies**: cluster stability dependency satisfied; M1 browser SSO/cutover closure tracked separately

### M4 — 23.3 SMS JetSMS primary + NetGSM secondary Activation (🟢 FULLY DELIVERED 2026-05-25 — BL-011 LIVE)

> **Closure update 2026-05-25 iter-7 (B-with-lanes complete + BL-011 LIVE)**: M4 23.3 prod SMS lane v1 **fully delivered**. 5-PR chain MERGED:
> - PR #1066 B-with-lanes runbook + BL-011 drift fixes
> - PR #1067 BL-028a Lane A LIVE (prod DB seed: `canary-prod-marketing-v1` template + `bl028-prod-canary-001` subscriber +905551815564)
> - PR #1068 BL-028b Lane B runbook
> - PR #1069 BL-028b Lane B LIVE (prod OpenFGA notification model cutover; new model `01KSFFK9K3V43DD211Z79K3FYA` 15 types; permission ALLOW tuple_match)
> - PR #1071 BL-011 prod SMS canary LIVE DELIVERED (+905551815564 → JetSMS `jetsms-2605251959362908914` → DELIVERED 71s DLR)
>
> **R28 🟢 Mitigated + functional canary PROVEN**. BL-011 🟢 DONE. Charter 23.3 4-state complete: 🟢 infra + 🟢 functional data + 🟢 Layer-2 authz + 🟢 prod SMS canary delivered.

> **Marker daraltma history 2026-05-25 iter-2..iter-6 (Codex `019e5e76` + `019e5ebe` + `019e5ee5`)**: M4 prod cutover initial state "infrastructure-only LIVE" idi (backend pod sha-6307428 + SmsAdapter active); BL-011 preflight no-SMS query prod `notify_db` boş data state ortaya çıkarttı (R28 NEW Lane A/Lane B blocker chain); B-with-lanes pattern ile resolve edildi (Lane A immediate + Lane B M4.6 trigger + BL-011 unblock + LIVE delivered). Bu daraltma chain historical reference olarak kalır.

> **Provider kararı 2026-05-19 (kullanıcı)**: SMS primary JetSMS (canlı sözleşme), secondary NetGSM. Multi-provider 5-PR sequence (PR-0 docs + PR-1 SmsProvider abstraction + PR-2 JetSmsProvider send/failover + PR-3 JetSMS DLR polling + PR-4 gitops base configmap + PR-5 test overlay cutover) — Codex `019e3f82` AGREE.

> **Status revision 2026-05-20 (Session 42+, Codex `019e45db` REVISE)**: M4 5-PR sequence MERGED + **test cluster JetSMS LIVE acceptance** (full happy-path: ACCEPTED + DLR DELIVERED terminal state). Initial HTTP 5xx retry **transient** classify; SOAP transport ACCEPTED + DlrPollingWorker DELIVERED. Prod cutover **multi-blocker** (prod ESO Graph aggregate Ready=False + imageID bump + configmap primary=jetsms flip + egress NetworkPolicy gap) → child issue [#903](https://github.com/Halildeu/platform-k8s-gitops/issues/903) Codex 9-step acceptance smoke gates.

> **Status revision 2026-05-21 (Session 47, Codex `019e4965` AGREE PARTIAL absorb — prod canary 403 strict-mode evidence)**: M4 prod canary SMS attempt via browser MCP + M365 SSO session **strict-denied** (HTTP 403). Bu **canary fail değil**: D29-Authorized Layer-1 **strict isolation PASS** evidence (`NOTIFY_SECURITY_DEFAULT_ORG_ID=""` Faz 24 PR-5.5 cutover live + JWT'de tenant claim yoksa fail-closed + raw JWT log/audit'te yok). D29-Up + D29-Authorized Layer-1 prod evidence triplet 🟢; D29-Functional prod SMS+DLR pending (KC operator gate: `org_id=default` claim setup runbook `docs/runbooks/RB-prod-canary-kc-claim-setup.md`). M3 R2 KVKK closure dili bu evidence ile kullanılmaz (Codex `019e4950` PARTIAL_COMPLIANT verdict ayrı).

> **Status revision 2026-05-20 (Session 47, post PR-B4 cutover RE-ATTEMPT MERGED)**: **M4 prod cutover LIVE** — PR-B1 (platform-backend #268 notify.dkim.strategy enum) + PR-B2/B3 (gitops #914/#915 test+prod overlay DKIM relay) + PR-B4 (gitops #916 prod cutover RE-ATTEMPT JetSMS PRIMARY + netpol 587/443) zinciri MERGED 2026-05-20T20:14Z. Prod pod sha-6307428 Running 1/1 + SmtpAdapter `dkimEnabled=false` (relay strategy) + SmsAdapter `primary=jetsms secondary=(none)` + ProductionConfigValidator `all production guards PASSED` + JetSmsDlrPollingWorker `scheduling=true` + Started in 37.7s (önceki PR #911 crashloop strategy enum öncesi DKIM strict gate fail-closed — same-incident reconciliation revert PR #912 + strategy enum hardening ile resolve). **DKIM strategy architecture sealed (scope dar — sadece DKIM signing decision)** (Codex `019e44b1` AGREE B): DKIM = Office 365 Native CNAME pattern (provider-managed key rotation), app-side key Vault'ta dormant fallback. **M4 acceptance'ın tamamı NOT sealed**: canary smoke + 72h observation + R24 provider acceptance + R1 NetGSM contract ext-gated kalır. **R3 🟢 mitigated upgraded**; **R24 🟡 active monitored** (`NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS=` blank workaround prod'da); **R1 🟡 active** (NetGSM secondary contract ETA 2026-05-30). Evidence: [docs/faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md](../faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md).

> **Sub-Faz 23.3.2 routing/multipart closure 2026-05-20 (Session 47, Codex `019e4514` 11 iter)**: Multipart + context routing decision logic + actual_channel audit (VF accepted path) chain MERGED + test cluster LIVE. Backend chain PR #262/#263/#264/#265/#266/#267 + GitOps PR #903/#905/#908 (sha-6ed593e). 3-senaryo canary smoke: VFO routing-log proof (Scenario A) + VF default delivered (Scenario B) + VF explicit fallback overlength delivered (Scenario C) — Codex P2+P3 absorb. Real-world: kullanıcı +905551815564 multipart SMS DELIVERED (B: 1 seg, C: 2 segments). **VFO provider acceptance PENDING R24**: JetSMS Biotekno sender ID OTP allowlist provisioning gap (ErrorCode=04 reject); routing logic LIVE, provider config gap. Evidence: [docs/faz-23-evidence/2026-05-20-23-3-2-jetsms-multipart-context-routing-evidence.md](../faz-23-evidence/2026-05-20-23-3-2-jetsms-multipart-context-routing-evidence.md).

> **Status revision 2026-05-23 (kullanıcı kararı — R1 NetGSM secondary DEFER)**: NetGSM secondary provider sözleşmesi **kısa vadede yapılmayacak**. R1 🟡 Active → **⏳ DEFER** (risk-register güncel; severity Medium→Low). JetSMS-only degraded mode = M4'ün **kabul edilen kalıcı işletim durumu** (JetSMS canlı sözleşme + HTTP API + DLR LIVE prod sha-6307428). NetGSM secondary failover acceptance kriteri sözleşme imzalanana kadar ertelendi — **M4 closure blocker DEĞİL**. `NetGsmProvider` + `SmsAdapter` failover facade + Vault/ESO NetGSM altyapısı **asset-preserved dormant** (R23/ADR-0024 "deferred but asset-preserved" pattern; kaldırılmaz/revert edilmez). Reactivation: sözleşme imzalanırsa Vault NetGSM keys seed → ConfigMap secondary enable → digest bump → failover acceptance test.

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
- [x] T3.1.8 4 workflow live test **TEST CLUSTER LIVE 2026-05-24** (PR #1030 MERGED — Codex iter-1 AGREE thread `019e5a87`): admin invite + password reset + drift alarm + break-glass 4 senaryo D29 3-layer disiplin proven (Up + Functional Layer 1 `notify_org_access_match_total=11` + Layer 2 OpenFGA enforce 4× DENY `no_tuple` + 2× ALLOW SMTP delivered). WorkerMetrics counter LIVE: `notify_authz_denied_total{reason_class=no_tuple} 4.0` + `notify_dispatch_outcome_total{BLOCKED_BY_AUTHZ=4, DELIVERED=2}`. Evidence: [docs/faz-23-evidence/2026-05-24-bl013-t318-4workflow-smoke.md](../faz-23-evidence/2026-05-24-bl013-t318-4workflow-smoke.md). **Prod canary ✅ FULLY DELIVERED 2026-05-25**: BL-010 prod KC `serban` realm LIVE (PR #1062) + BL-028a Lane A LIVE (PR #1067) + BL-028b Lane B LIVE (PR #1069) + BL-011 prod SMS canary LIVE DELIVERED (PR #1071 — `+905551815564` JetSMS `jetsms-2605251959362908914` DELIVERED 71s DLR). R24 Biotekno OTP allowlist external (~1-2 hafta); R1 NetGSM DEFER asset-preserved
- [~] **Prod cutover** (issue [#903](https://github.com/Halildeu/platform-k8s-gitops/issues/903)) — **agent-actionable items LIVE 2026-05-20** (PR-B1+B2+B3+B4 zincir):
  - [x] A.1 prod ESO aggregate blocker resolution (Graph `graph_*` D49 defer-aware, PR #906 MERGED)
  - [x] A.2 prod overlay imageID + primary=jetsms flip PR (atomic, PR-B4 #916 MERGED)
  - [x] A.3 prod egress 443 NetworkPolicy gap close (`netpol-notification-egress-mail-providers.yaml`, PR-B4 #916)
  - [x] A.4 canary SMS smoke (provider=jetsms prod) — ✅ **LIVE DELIVERED 2026-05-25 16:58:45 UTC** (PR #1071): kullanıcı "kalan işi tamamla" trigger sonrası 1 SMS `+905551815564` → JetSMS `jetsms-2605251959362908914` → DELIVERED 71s DLR. 7/7 acceptance gate PASS (intent COMPLETED + delivery DELIVERED + audit 4-event chain + metric `notify_org_access_match_total{source="org_id"} 0→1` + VF channel + DLR <120s + zero retry). Evidence: [docs/faz-23-evidence/2026-05-25-bl011-prod-sms-canary-live.md](../faz-23-evidence/2026-05-25-bl011-prod-sms-canary-live.md). 2026-05-21 attempted browser MCP 403 strict-mode deny D29-Authorized Layer-1 evidence historical (Codex `019e4965`).
  - [ ] A.5 DLR terminal state evidence — **ext-gated** (A.4 functional canary sonrası natural; pipeline LIVE scheduling=true)
  - [x] A.6 rollback plan documented (evidence doc §7 + release-candidates ledger `rollback_to_digest: sha-70491543`)
- [x] **Charter 23.3 marker → 🟢 4-state FULLY DELIVERED 2026-05-25** (B-with-lanes complete + BL-011 LIVE): 🟢 infrastructure LIVE + 🟢 functional data seed (Lane A) + 🟢 Layer-2 authz cutover (Lane B) + 🟢 prod SMS canary DELIVERED (BL-011). Codex chain `019e5e76` + `019e5ebe` + `019e5ee5` AGREE; 5 PR series MERGED (#1066+#1067+#1068+#1069+#1071).
- [~] Risk register: R1 — NetGSM secondary failover acceptance **⏳ DEFERRED** (kullanıcı kararı 2026-05-23: sözleşme kısa vadede yapılmayacak; JetSMS-only degraded mode = kabul edilen işletim durumu; NetGsmProvider + Vault/ESO asset-preserved). **M4 closure blocker DEĞİL** — sözleşme imzalanırsa reactivation.

**Blockers**: None (M4 23.3 fully delivered 2026-05-25). NetGSM secondary 📦 Out of plan / demand-reactivated (ADR-0028 2026-05-25; asset-preserved; aktif blocker değil). DKIM CNAME 📦 Out of plan / demand-reactivated (ADR-0028; SMTP relay LIVE without DKIM CNAME). R24 Biotekno OTP allowlist external (~1-2 hafta; OTP path için optional)
**Owner**: gitops/ops (prod cutover gates); R1 NetGSM ⏳ DEFER (sözleşme imzalanırsa reactivation — asset-preserved)
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

### M6 — 23.4 Closure (🟢 LIVE 2026-05-20 board #758 — both M6a + M6b done)

> **Split rationale (2026-05-09)**: 23.4 closure iki bağımsız part'a bölündü; M6a (archive + history filter) M3 ile paralel, M6b (SMS DLR UI) M4 sonrası gate'lidir.

> **Status revision 2026-05-23 (M6 reconciliation truth-sync)**: M6a + M6b 6/6 sprint-plan T2.2.1-T2.2.6 tasks **2026-05-20 board #758 accepted** (sprint-plan satır 184 "M6a + M6b 6/6 LIVE"). Milestones M6 section + charter 23.4 archive/history sub-portion bu kapanışa kadar stale `[ ]` ile takip ediliyordu; bu reconciliation truth-sync yapıyor. Backend evidence: V16 inbox history index + tests MERGED (sprint-plan task #8), FE history filter UI MERGED (task #9), archive UI MERGED (PR #626 + M6a chain task #12), SMS DLR badge UI MERGED (task #36); T3.1.7 DLR callback endpoint **🟢 Session 44 LIVE** (charter satır 52 — backend PR #85 + api-gateway PR #154 + gitops PR #514 MERGED + live smoke pipeline 5/5 gates PASS).

#### M6a — 23.4 Archive + History (🟢 LIVE 2026-05-20 board #758)

**Definition of Done**:
- [x] T2.2.1 Archive UI button — platform-web PR #626 + M6a chain MERGED (sprint-plan task #12)
- [x] T2.2.2-3 30d notification history filter (FE + BE) — Backend V16 inbox history index + tests MERGED (task #8); FE inbox Geçmiş tab + listHistory RTK MERGED (task #9)
- [x] T2.2.4 Integration test (archive + history) — tasks #8 + #9 IT MERGED
- [x] Charter 23.4 marker (archive/history portion) 🟡 → 🟢 — board #758 acceptance + sprint-plan T2.2.1-T2.2.4 LIVE

**Blockers**: None
**Owner**: — (M6a closed)
**Dependencies**: M1 stable ✅ (cluster + auth)

#### M6b — 23.4 SMS DLR UI (🟢 LIVE 2026-05-20 board #758)

**Definition of Done**:
- [x] FE inbox SMS DLR badge (status: sent/delivered/failed) — platform-web inbox SMS DLR badge MERGED (sprint-plan task #36, T2.2.5)
- [x] T3.1.7 DLR callback endpoint live-verified — backend PR #85 + api-gateway PR #154 + gitops PR #514 MERGED + **mock provider** 5/5 acceptance gates PASS Session 44 test cluster (evidence `docs/faz-23-evidence/2026-05-11-t3-1-7-dlr-live-smoke-pass.md`); JetSMS-primary prod path + `JetSmsDlrPollingWorker scheduling=true` LIVE prod sha-6307428 (M4 evidence). NetGSM webhook leg dormant per R1 ⏳ DEFER. Prod SMS functional canary / DLR terminal status evidence ext-gated (KC operator gate `org_id=default` claim setup — `docs/runbooks/RB-prod-canary-kc-claim-setup.md`).
- [x] Charter 23.4 marker (SMS DLR portion) ⏳ → 🟢 — T3.1.7 callback endpoint test/mock live-verified + JetSMS-primary prod path + DLR polling worker live; NetGSM secondary R1 ⏳ DEFER asset-preserved (kullanıcı kararı 2026-05-23)
- [x] Charter 23.4 fully 🟢 only when both M6a + M6b done — both LIVE board #758

**Blockers**: None — M4 SMS JetSMS primary LIVE prod (sha-6307428) + DLR worker scheduling=true. NetGSM secondary 📦 Out of plan / demand-reactivated (ADR-0028 2026-05-25; asset-preserved; M6b closure blocker DEĞİL; JetSMS-only DLR pipeline kabul edilen işletim durumu).
**Owner**: — (M6b closed)
**Dependencies**: M4 SMS JetSMS primary LIVE ✅

### M7 — v1 Closure (🟡 target 2026-08-15)

**Definition of Done**:
- [x] T4.1 23.6 Teams + Slack threading LIVE (Slack Block Kit PR #271 + Teams Power Automate PR #272 — sha-f40aa82+)
- [x] T4.2 23.7 Push — **Web Push (browser) LIVE end-to-end 2026-05-23** (subscribe + delivery proven); mobile FCM/APNS deferred to Faz 22.2 (out of v1)
  - [x] **Web Push (browser) FULLY LIVE 2026-05-23** — RB-webpush-activation.md §3.10 (subscribe end-to-end ✅) + §3.11 (push delivery SUCCESS ✅ `notify_dispatch_outcome_total{channel="push",status="DELIVERED"} 1.0` + FCM 201 msg_id). 12 PR chain MERGED + deployed:
    - PR-W1 #277: V19 subscriber_push_endpoint + entity + repo
    - PR-W2.1 #278: WebPushConfig + VapidKeyService + nl.martijndwars:web-push lib
    - PR-W2.2 #279: WebPushAdapter + status mapping + endpoint cleanup
    - PR-W2.3 #280: DefaultWebPushSender real lib integration
    - PR-W2.4 #281: DefaultWebPushSenderHttpIntegrationTest WireMock 3.x end-to-end (Codex 019e4a2e AGREE)
    - PR-W2.5+W2.6 #282: IntentSubmissionService allow-list + DeliveryPlanService fan-out + DeliveryEligibilityService BLOCKED_NO_PUSH_ENDPOINT + V20 migration (Codex 019e4a3d iter-4 AGREE)
    - PR-W3 #283: PushSubscriptionController + Service + atomic upsert (Codex 019e4a57 iter-3 AGREE)
    - PR-W4 platform-k8s-gitops #939: ConfigMap WebPush 5 entries + ExternalSecret defer-aware + overlay digest bump (Codex 019e4a70 iter-2 AGREE)
    - PR-W5 platform-web #648: mfe-shell service worker + notify-push.api + helpers + usePushSubscription hook (Codex 019e4a87 iter-2 AGREE)
    - PR-W6 platform-web #649: PushSubscriptionCard UI + VAPID env build chain
    - PR-W7 platform-web #652: notify RTK `unwrapRequestFetchFn` shim — Request-object header drop fix (cross-domain pattern; later replicated for endpoint-admin in #658)
    - Activation chain (operator-completed 2026-05-23): Vault VAPID 3-key seed + ESO uncomment + ConfigMap `NOTIFY_ADAPTERS_WEBPUSH_ENABLED=true` + frontend `VITE_NOTIFY_VAPID_PUBLIC_KEY` rebuild + OpenFGA `model_id` cutover. **Evidence authority**: RB-webpush-activation §3.10 (subscribe) + §3.11 (push delivery SUCCESS). **Supporting ledger**: gitops #976/#977 (ConfigMap WebPush enable + VAPID env wiring) + #986/#987 (frontend digest bump + browser smoke) + #990/#995/#996/#997 (OpenFGA model_id cutover + internal-auth ESO + delivery-success closure chain).
  - [ ] **Mobile FCM/APNS** — Faz 22.2 dep, scope DIŞI (planned v1.1 / 23.7.b patch milestone post-Faz 22.2; M7.b subsection below; canonical wording per ADR-0013 / sprint-plan T4.2.7-10 row "DEFER Faz 22.2 dep"; Codex strategic verdict thread `019e5a59` REVISE → Opsiyon C 2026-05-24 absorb; R25 tracks DEFER governance)
- [~] T4.3 23.8 Tempo + bounce loop + per-tenant Grafana + FBL + federation — **9/9 sub-task source-side closed 2026-05-22** (operator activation pending)
  - [x] T4.3.a Tempo OTLP trace export LIVE (2026-05-21 09:17Z; 5 spans verified)
  - [x] T4.3.b email suppression core LIVE (PR #270 — sha-f40aa82)
  - [x] T4.3.6 Per-tenant Grafana dashboard MERGED (PR #951 — 8 panel; + B.1 org_id Counter Tag retrofit PR #289)
  - [x] T4.3.7 Per-template analytics MERGED (PR #966 Grafana PG datasource + Top 20 panel + PR #296 V21 index — Codex 019e4ee2; **BL-015-A prod activation source-ready 2026-05-24 PR #1035 MERGED** — helm-values envValueFrom NOTIFY_PG_RO_PASSWORD optional:true + ESO remoteRef uncomment — Codex `019e5a75` strategic iter-3 + `019e5aad` post-impl iter-3 AGREE; operator B step PG role + Vault seed + helm upgrade BL-004 Vault chain dep)
  - [x] T4.3.8 Federation design-artifact MERGED (PR #964 ADR-0026 phased — bounded operator-only; production federation Faz 24+/M8; R16 design-managed — Codex 019e4ee7)
  - [x] T4.3.5 Spam complaint FBL source-ready (PR #298 core ArfReportParser+FblService+V22 + PR #299 FblMailboxPollingWorker IMAP — Codex 019e4edd/019e4fc6/019e4ffd; 28 unit test; operator activation pending — RB-fbl-mailbox-activation)
- [ ] All v1 sub-faz kabul kriteri 🟢 (23.6, 23.7, 23.8)
- [ ] Charter markers all updated
- [ ] Risk register: R11, R16 closed

**Out of scope (v1 — future-proofing track):**
- Microsoft Graph mail adapter activation — **defer karar D49 / ADR-0024** (Session 42 2026-05-20, Codex `019e44b1`). SMTP Office 365 path canonical kalır; Graph adapter binary backend ready (PR #153) ve gitops staged (PR #872) ama activation trigger-driven future-only ([RB-graph-mail-adapter-activation.md](../runbooks/RB-graph-mail-adapter-activation.md) + [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) P3 Backlog). R23 active monitored.

**Blockers**: M5 done + M6a/M6b done (split closure) — M3 + M4 zaten önceki kapı
**Owner**: dev + ops + gitops

### M7.b — 23.7.b Mobile Push Patch (🔵 DEFER post-Faz 22.2)

**Status**: DEFER planned patch milestone — Faz 22.2 (Mobile shell) production-ready olmadan implementasyona başlanamaz. v1 closure semantik açısından **WebPush browser-only v1'i kapatır** (M7 DoD); Mobile FCM/APNS ayrı patch milestone olarak v1.1 release-line altında izlenir.

**Definition of Done** (post-Faz 22.2 trigger):
- [ ] Faz 22.2 Mobile shell production LIVE (FCM project + APNS bundle id provisioning ops/mobile tarafı)
- [ ] Backend FCM adapter (Android) — channel `mobile-push`, status mapping, retry policy
- [ ] Backend APNS adapter (iOS) — bundle id, key id, p8 key Vault seed
- [ ] DeliveryEligibilityService BLOCKED_NO_PUSH_TOKEN guard parity (web push pattern)
- [ ] IntentSubmissionService fan-out mobile-push channel + WorkerMetrics counter Tag
- [ ] PR-W4 pattern uyarınca GitOps ConfigMap + ExternalSecret defer-aware Vault seed
- [ ] Frontend mobile shell push token registration (Faz 22.2 dep)
- [ ] Audit + WorkerMetrics `notify_dispatch_outcome_total{channel="mobile-push",status="DELIVERED"}` 1.0 proof
- [ ] Charter 23.7 marker 🟢 done (partial → full)
- [ ] R25 status → 🟢 Mitigated (DEFER → activated)

**Blockers**: Faz 22.2 production-ready (Android + iOS shell deployment)
**Owner**: dev (backend) + mobile (Faz 22.2 shell) + ops (FCM/APNS provisioning)
**Trigger**: Faz 22.2 cutover LIVE — agent re-activation chain (Codex consult + plan-time iter + impl + cross-AI review + cluster apply)
**Strategic context**: Codex strategic verdict thread `019e5a59` REVISE → Opsiyon C absorb 2026-05-24 — browser-only v1 closure + Mobile separate v1.1/23.7.b patch (BL-021 strategic decision sealed).

### M8 — Multi-tenant Trigger Gate (🔴 target 2026-09-01)

> **Authority pointer (2026-06-03)**: M8 = "Faz 21 production migration başlatma izni gate". Faz 21 v1 tenant model + scope canonical authority [docs/faz-21/charter.md](../faz-21/charter.md) + [ADR-0032 — Faz 21 tenant model v1](../adr/0032-faz-21-tenant-model.md). Bu satır pointer; semantik canonical orada.

**Definition of Done** (Faz 21 multi-tenant öncesi):
- [ ] M7 v1 stable (≥30 day in production) — observation harness PR #1234 (Faz 23 M8 PR-1 D Codex `019e8c24`)
- [ ] R10 (multi-tenant migration risk) mitigation plan ready — board #766 [Done]; execution PR-3 A (sprint plan)
- [ ] Pre-migration audit + dry-run + per-tenant isolation test — Faz 21.0 sub-faz scope
- [ ] Faz 21 charter draft — MERGED in PR-2 B (this PR)

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
