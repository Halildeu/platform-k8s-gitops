# Faz 23 V1 Closure — Operator Handoff Index (2026-05-24)

> **Trigger**: Session 49+ doc-truth-sync sweep (PR #1002-#1013) saturation noktasında + user directive "tüm 20 bekleyen backlog işini paralel agent + main session ile tamamlayalım".
>
> **Scope**: Pointer/checklist style handoff. **Bu doküman canonical runbook'ların yerine geçmez** — her item için canonical RB'ye işaret eder. Operator canonical RB'yi follow eder; bu index sequence + dependency map + agent parallel track sağlar.
>
> **Marker discipline**: Bu doc agent-actionable backlog'un (5 agent paralel) operator/external/board/strategic kalan yarısının **pointer'ı**. Status authority canonical surfaces (milestones / sprint-plan / risk-register / charter / feature-matrix) decides.

---

## §1 — Agent Probe Boundary Summary (Honest Gap)

> **Status update 2026-05-25**: Bu boundary summary 2026-05-22 historical context. Bu session'da Agent Pre-Production Full Authority HARD RULE 2026-04-29 + kullanıcı explicit AskUserQuestion onay zinciri ile **çoğu boundary aşıldı**. Güncel durum:

| Credential | Path | Status | Notlar |
|---|---|---|---|
| Vault root token (prod) | `/home/halil/bootstrap-drill/vault-init-prod.json` | ✅ Agent canonical erişim | BL-004 + BL-006b + BL-028b prod Vault patch agent execute (PR #1048 + #1069) |
| Keycloak admin pwd (prod) | KC container env (`KEYCLOAK_ADMIN_PASSWORD`) | ✅ Agent canonical erişim | BL-010 prod KC `serban` realm 4-step LIVE (PR #1062) |
| PG primary (prod) | `platform-pg-prod` docker container | ✅ Agent canonical erişim | BL-028a Lane A prod DB seed LIVE (PR #1067) |
| Slack workspace + webhook | — | ⏳ External | Operator-external (R9 D43 SMTP-only D43 v1 accepted; Slack DEFER future trigger) |
| Office 365 admin | — | 📦 Out of plan | DKIM CNAME publish demand-reactivated (ADR-0028 2026-05-25; SMTP relay LIVE without DKIM CNAME) |
| DNS registrar admin | — | 📦 Out of plan | DNS CNAME demand-reactivated (ADR-0028) |
| Biotekno provider | — | ⏳ External | R24 OTP allowlist (~1-2 hafta external lead) |

**Sonuç güncel 2026-05-25**: Agent-doable scope büyük ölçüde **tüketildi**. BL-004 (PR #1051 + BL-028b internal API key hash align), BL-006a/BL-006b (PR #1031 + #1048), BL-010 (PR #1062 KC org_id mapper), BL-015 (PR #1035 + B/C live ops), BL-028 (B-with-lanes complete PR #1066 + #1067 + #1068 + #1069), BL-011 (LIVE DELIVERED PR #1071) tamamlandı. Bu doc kalan **gerçek operator-external scope** için action checklist + canonical RB pointer.

---

## §2 — Operator Action Checklist (Sequential)

Her satır: backlog ID + canonical RB pointer + dependency. Operator canonical RB'yi takip eder; bu index sequence kontrolü için.

### Sprint A — Vault Canonical Align (Pre-condition for downstream PR reverts)

- [x] **BL-004** Vault canonical patch ✅ LIVE 2026-05-25 (env-specific):
  - **Test**: `kv/platform/openfga model_id=01KS8QE8T1EJ2DF5CRS4VV9YX1` — BL-006b PR #1048 MERGED 2026-05-24
  - **Prod**: `kv/platform/openfga model_id=01KSFFK9K3V43DD211Z79K3FYA` — BL-028b 2026-05-25 PR #1069 MERGED (version 4 patch)
  - **Internal API key align**: `kv/platform/notification-orchestrator authz_internal_api_key` ↔ permission-service `PERMISSION_SERVICE_INTERNAL_API_KEY` sha256 hash-match verified (PR #1051 + BL-028b preflight kanıtı; raw secret loglanmaz)
  - Evidence: `docs/faz-23-evidence/2026-05-24-bl004-prod-authz-internal-api-key-align.md` + `docs/faz-23-evidence/2026-05-25-bl028b-lane-b-prod-openfga-cutover-evidence.md` §10
- [x] **BL-005** CLOSURE 2026-05-24 (Codex strategic verdict thread `019e5a75` REVISE absorb): **No functional revert needed** for PR #995/#996 while live evidence stays aligned. Codex iter-2 quote: "No functional revert reason for PR #995/#996 while live evidence stays aligned. Only revert temporary overlay overrides after BL-004 proves Vault canonical parity; agent can decide from env/hash + smoke evidence." → BL-005 = "no action needed, BL-004 sonrası override revert pattern follow" → resolved as governance closure (PR #995 OpenFGA model_id cutover + PR #996 internal-API-key ESO re-align stays merged + LIVE; no revert).
  - Dependency: ~~BL-004 verified~~ — strategic closure decision sealed pre-BL-004 (revert YOK; override revert pattern BL-004 sonrası yapılırsa runtime-artifacts ledger update PR ile birlikte yapılır — BL-006 reverse-dependency)
- [x] **BL-006a** LEDGER METADATA UPDATE 2026-05-24 (PR #1031 MERGED) — `runtime-artifacts/openfga-model/a48a49198c70bd3f928bbac2b87ef3fd83903f00691996c04778f892146f0f9c.json` 2-alan update: `source_docs` +`h-live-evidence-resync.md` + `rollback_runbook_ref` → `#4-rollback` canonical anchor. Codex post-impl thread `019e5a7e` AGREE / canonical_drift: false.
- [x] **BL-006b** RUNTIME_SELECTOR `null → vault` ✅ LIVE 2026-05-24 — PR #1048 MERGED (Codex `019e5b3d` Option A AGREE). Selector_kind: vault, vault_path: kv/platform/openfga, field: model_id. R26 multi-cluster Vault topology drift 🟢 RESOLVED (test/prod ayrı container kanıtlandı). Plus prod ledger block `pending → promoted` (BL-028b PR #1069 sonrası; model_id_env=01KSFFK9..., evidence complete).
- [x] **BL-007** ✅ CLOSURE 2026-05-25 — canonical `platform-backend/backend/openfga/model.fga` source verification PASS. Remote raw fetch (`gh api repos/Halildeu/platform-backend/contents/backend/openfga/model.fga -H "Accept: application/vnd.github.raw"`) kanıtladı: 5 notification type LIVE (`subscriber`, `service_account`, `notification_topic`, `notification_template`, `template`) + topic-based inheritance pattern (`can_receive: can_receive from topic` + `can_publish: can_publish from topic`) + Faz 23.7 M3-supplement comment block (Codex `019e2651` Yol A) + `template` transition-compat alias note. Local DSL `docs/notify/openfga-notification-model.dsl` ile canonical aynı. Önceki "local checkout notification types içermiyor" stale audit (outdated working tree); remote canonical authoritative.
  - [x] Runtime/prod OpenFGA notification model promoted via BL-028b evidence (PR #1069 — new prod model_id `01KSFFK9K3V43DD211Z79K3FYA` 15 types: 10 ERP + 5 notification)
  - [x] Canonical `platform-backend/backend/openfga/model.fga` source notification types verification ✅ PASS 2026-05-25 (remote raw fetch; 5 notification type + topic-inheritance + transition-compat alias kanıtlandı; PR link N/A — types Faz 23.7 M3-supplement (Codex `019e2651` Yol A) ile zaten canonical'da LIVE, ayrı PR gerekmedi)

### Sprint B — Ops Slot Execution (Canonical RB pointers)

- [ ] **BL-008** PARTIAL — R9 SMTP-only/mock-receipt mitigation accepted; prod SMTP-only activation #854 remains operator/timer-bound.
  - [x] R9 mock-receipt mitigated / SMTP-only D43 v1 accepted 2026-05-24 (BL-008 controlled simulate Codex `019e5aaf` AGREE)
  - [ ] Prod SMTP-only direct fallback activation + 30-day observation, board #854 (operator-external; Operator v0.90.1 `auth_*_file` schema fix)
  - [x] Slack workspace pivot resolved via D43-TEAMS Hibrit C (PR #1059 MERGED) — original board #853 closed superseded
  - Canonical RB: [`docs/runbooks/RB-notification-outage-fallback.md`](RB-notification-outage-fallback.md)
- [x] **BL-010** Keycloak `org_id=default` claim setup — canonical RB: [`docs/runbooks/RB-prod-canary-kc-claim-setup.md`](RB-prod-canary-kc-claim-setup.md) (canary user attribute + User Attribute mapper pattern, NOT hardcoded claim mapper)
  - **Test cluster scope COMPLETED 2026-05-24** — PR #1036 evidence `docs/faz-23-evidence/2026-05-24-bl010-kc-org-id-mapper.md` (Codex `019e5ac1` cross-AI AGREE iter-2)
  - **Prod cluster scope COMPLETED 2026-05-25** — `serban` realm (drift fix `acik`→`serban`) `notify-canary` client scope + `org_id` mapper + persona `notify-canary-org-prod-default` LIVE; JWT mint OK; access_token + id_token + userinfo 3-way `org_id="default"` claim verified; resource-server auth PASS (controller reach; HTTP 400 = `@Valid` payload validation hits BEFORE guard call); Vault seed length-only verify 41 char; evidence `docs/faz-23-evidence/2026-05-25-bl010-prod-kc-org-id-mapper-serban.md` (Codex `019e5bfb` strategic AGREE + iter-2 acceptance daraltma absorb)
  - **Guard-pass behavioral proof** (notify_org_access_match_total{source="org_id"} + pod log + valid `SubmitIntentRequest` payload + 202/403 post-guard observation) — **BL-011 SMS canary turunda zorunlu acceptance** (Codex iter-2 absorb 2026-05-25)
- [x] **BL-011** Prod SMS functional canary smoke — ✅ **LIVE DELIVERED 2026-05-25 16:58:45 UTC** (kullanıcı "kalan işi tamamla" trigger 2026-05-25). 1 SMS marketing.campaign +905551815564 → JetSMS provider_msg_id `jetsms-2605251959362908914` → DELIVERED 71s DLR. 7/7 acceptance gate PASS. Cost ~5 kuruş. Evidence: `docs/faz-23-evidence/2026-05-25-bl011-prod-sms-canary-live.md`. 6 trigger condition:
  - (a) **BL-028a (Lane A)** prod data seed COMPLETED (template + subscriber_contact, agent-doable)
  - (b) **BL-028b (Lane B)** prod OpenFGA notification model cutover COMPLETED (subscriber + notification_topic + template types + topic-inheritance tuple + permission ALLOW, operator+architecture gate, DEFERRED M4.6)
  - (c) BL-028 acceptance preflight: DB row counts + permission check `{"allowed": true}` via permission-service `:8090` internal (SMS POST yok; gerçek SMS POST BL-011 window'unda)
  - (d) operator window scheduled
  - (e) recipient `+905551815564` re-confirm
  - (f) cost cap ≤3 SMS confirm
  - Dependency: BL-010 (KC claim setup ✅ PR #1062 MERGED) + **BL-028a (DB seed)** + **BL-028b (OpenFGA cutover)** + BL-016 R24 OTP allowlist (eğer OTP topic test ediliyorsa)
  - Runbook: `docs/runbooks/RB-bl011-prod-sms-canary-execute.md` (Status: 🔴 DEFER/BLOCKED — Lane A + Lane B ikisi PASS olmadan SMS POST YASAK)
- [x] **BL-028** Prod `notify_db` functional data + authz preflight — R28 mitigation **B-with-lanes complete** ✅ LIVE 2026-05-25 (Codex thread `019e5ebe` iter-1..iter-3 chain — REVISE → PARTIAL → AGREE 2026-05-25)
  - **Lane A — BL-028a** ✅ **LIVE EXECUTED 2026-05-25** (immediate, agent-doable, M4.5 / 23.3.3a):
    - Scope: (a) active SMS-capable template `canary-prod-marketing-v1` v1 tr-TR active=true body_text doldurulmuş, (b) canary subscriber `bl028-prod-canary-001` org=default phone=+905551815564 phone_verified=true source=canary
    - Acceptance LIVE PASS: pre/post DB row exact-match SELECT + permission-service `:8090` reachable via POST /api/v1/internal/authz/check → 401 (auth filter; /actuator/* prod hardening kapalı) + backend env canonical + no-SMS guard (intent/delivery/audit 0/0/0)
    - Pattern (live drift fix): `template_no_update` rule ON CONFLICT incompatibility → direct INSERT (idempotency uq_template_version_locale UNIQUE constraint ile)
    - Runbook: `docs/runbooks/RB-bl028-prod-data-seed-execute.md` Lane A
    - Evidence: `docs/faz-23-evidence/2026-05-25-bl028a-lane-a-prod-data-seed-execute.md`
  - **Lane B — BL-028b** ✅ **LIVE EXECUTED 2026-05-25** (M4.6 / 23.3.4 trigger):
    - Scope: prod OpenFGA notification model cutover (DSL `docs/notify/openfga-notification-model.dsl` → prod store) + permission-service `ERP_OPENFGA_MODEL_ID` runtime update + topic-inheritance tuple seed (`notification_topic:marketing.campaign#can_receive@subscriber:bl028-prod-canary-001` + `template:canary-prod-marketing-v1#topic@notification_topic:marketing.campaign`) + permission check ALLOW kanıt + ERP regression smoke
    - Acceptance: prod OpenFGA model type'ları contains notification types + permission-service internal check `{"allowed": true}` + ERP 10 type regression PASS
    - Trigger for activation: M4.6 milestone start (Lane A complete + operator+architecture gate açık)
    - Runbook: [`docs/runbooks/RB-bl028b-prod-openfga-notification-model-cutover.md`](RB-bl028b-prod-openfga-notification-model-cutover.md) — ✅ **LIVE EXECUTED 2026-05-25** (M4.6 trigger; 10/10 acceptance gate PASS; new prod model `01KSFFK9K3V43DD211Z79K3FYA`; evidence `docs/faz-23-evidence/2026-05-25-bl028b-lane-b-prod-openfga-cutover-evidence.md`)
- [ ] **BL-014** FBL mailbox activation — canonical RB: [`docs/runbooks/RB-fbl-mailbox-activation.md`](RB-fbl-mailbox-activation.md) (Vault remoteRef triple + overlay patch + ESO uncomment + PR/apply + hard gates)
- [x] **BL-015** Grafana per-template notify PG RO datasource ✅ LIVE 2026-05-24 — PR #1035 (helm-values envValueFrom + ESO remoteRef uncomment Codex `019e5a75` strategic iter-3 + `019e5aad` post-impl iter-3 AGREE) + BL-015-B live ops (PG role + Vault seed + ESO + helm upgrade) + BL-015-C evidence + G1-G8 gates PASS. Canonical user `grafana_notify_ro`, DB `notify_db`, Vault path `kv/platform/grafana/notify-pg-ro`. Evidence: `docs/faz-23-evidence/2026-05-24-bl015-grafana-pg-ro-prod-live.md`.

### Sprint C — External Provider Lead

- [ ] **BL-016** R24 Biotekno OTP allowlist (VFO outbound sender ID provisioning)
  - Owner: Biotekno müşteri temsilcisi + JetSMS provider config
  - ETA: ~1-2 hafta external lead time
  - Reference: risk-register R24; sprint-plan M4

### Sprint D — KC Drift Diagnosis-First Chain (Codex `019e6abe` plan-time AGREE + `019e6ac8` iter-2 REVISE absorb 2026-05-27)

- [x] **3 KC drift (user-svc / auth-svc / perf-alertmanager)** — DIAGNOSIS-ONLY iter-2 PASS 2026-05-27; fix scope drastically reduced (2 phantom + 1 owner-action)
  - [x] **Diagnosis evidence iter-2**: `docs/faz-23-evidence/2026-05-27-kc-drift-diagnosis-3-service.md` — live introspection iter-1 + Codex `019e6ac8` REVISE catch absorb iter-2
  - [x] **No-op (user-service)**: phantom drift kapatıldı (Vault `keycloak_client_secret` ↔ K8s `KEYCLOAK_CLIENT_SECRET` ↔ KC serban `user-service` client id `9ec438ac` aligned LIVE; ERP_OPENFGA_* multi-source via `kv/platform/openfga` per ExternalSecret manifest)
  - [x] **No-op (auth-service)**: phantom drift kapatıldı iter-2 (Codex catch: KC client adı `auth-service` değil **`impersonation-broker`** id `3ebfd270` LIVE; `AUTH_IMPERSONATION_BROKER_CLIENT_ID="impersonation-broker"` configmap canonical; `KEYCLOAK_CLIENT_SECRET` ayrı Spring resource-server JWT validation path)
  - [ ] **Owner-action (perf-alertmanager)**: V2.1 Ops-A A2 — owner Vault seed `vault kv put kv/platform/perf-alertmanager SLACK_WEBHOOK_URL=<URL>`. Canonical desired-state LIVE (`monitoring` ns ExternalSecret + Helm values mount + `api_url_file` config). ESO `Ready=False (reason=SecretSyncedError)` 7d20h until seed. Runbook: `docs/runbooks/V2.1-perf-alert-receiver.md` §A2.

---

## §3 — Board Acceptance Decisions (User/Board Role)

Each pending operator/board acceptance — agent prep evidence ready:

> **Post-PR board action target** (PR #1 governance truth-sync MERGED sonrası deliberate close + Status update):

- [ ] **BL-017** M3 23.2 board item #755 → **Done** target: R2 KVKK closed via Codex `019e5189` final legal verdict AGREE 2026-05-23; 6/6 sub-faz fully 🟢; K6 P1 non-blocking 23.2.B follow-up
  - Evidence: `docs/faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md`
- [ ] **BL-018** M4 23.3 board item #756 → **Done** target + title rescope ("23.3 SMS lane JetSMS primary accepted — BL-011 LIVE 2026-05-25"): M4 prod cutover infra LIVE 2026-05-20 sha-6307428 + BL-028a Lane A LIVE + BL-028b Lane B LIVE + BL-011 prod SMS canary LIVE DELIVERED 2026-05-25 (provider_msg_id `jetsms-2605251959362908914`). R1 NetGSM secondary ⏳ DEFER asset-preserved (kullanıcı kararı 2026-05-23).
  - Evidence: `docs/faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md` + `docs/faz-23-evidence/2026-05-25-bl028a-lane-a-prod-data-seed-execute.md` + `docs/faz-23-evidence/2026-05-25-bl028b-lane-b-prod-openfga-cutover-evidence.md` + `docs/faz-23-evidence/2026-05-25-bl011-prod-sms-canary-live.md`
- [x] **BL-019** M5 23.5 board item #757 → **Done** (already correct ✅): M5 source-ready + acceptance candidate; 23.5 preference UI LIVE
- [ ] **BL-020** M6 23.4 board item #758 → **Done** target: M6a + M6b 6/6 LIVE 2026-05-20 (archive UI 30-day history + SMS DLR LIVE prod sha-f40aa82)

---

## §4 — Strategic Decisions (Kullanıcı Karar Gerek)

- [ ] **BL-021** 23.7 push scope tanımı:
  - **Seçenek A**: Mobile FCM/APNS dahil → BL-023 Mobile impl gerek (Faz 22.2 dep, ~8-16h) → 23.7 🟡 → 🟢
  - **Seçenek B**: "Browser-only WebPush = 23.7 v1 closure" → 23.7 🟢 scope-narrowed + mobile Faz 22.2/Faz 24'e taşınır
  - Reference: milestones.md M7 T4.2 line 206; sprint-plan T4.2

---

## §5 — Time-Passive (Calendar-Bound)

- [ ] **BL-012** M7 v1 30-day prod observation window
  - **Dependency**: M7 v1 stable (tüm v1 sub-faz markers 🟢 OR scope-narrowed via BL-021)
  - **Window**: 30 day from M7 closure date (TBD post agent + operator + strategic completion)
  - Reference: milestones.md M8 dependency

---

## §6 — Agent Parallel Track (Bu Session — No Operator Action Required)

Background agents currently in-flight (status: pending → in_progress):

| # | Agent ID | Backlog | Repo | Status (review pending) |
|---|---|---|---|---|
| 1 | `a501c87383b8fef9c` | BL-001 K6 tenant-scoped DPO authz | `platform-backend` cross-repo | in-flight |
| 2 | `a92232a4d8c258e05` | BL-002 Layer-2 OpenFGA `subscriber#can_receive` enforce | `platform-backend` cross-repo | in-flight |
| 3 | `aa3d862bed5a8b408` | BL-003 M5 live runtime evidence (browser smoke) | `platform-k8s-gitops` | in-flight |
| 4 | `a299c779adfc87f24` | BL-013 T3.1.8 4 workflow test partial (test cluster smoke) | `platform-k8s-gitops` | in-flight |
| 5 | `a233ba0a6703e6595` | BL-007 platform-backend model.fga canonical + BL-024-027 secondary docs hygiene | Cross-repo + this repo | in-flight |

Tüm 5 agent cross-AI peer review (provider-different, Codex reviewer) HARD RULE altında; review PR'ları agent çıktısı geldiğinde main session integrate edilir.

---

## §7 — V1 Closure Trace Timeline (Indicative)

| Phase | Items | Dependency | ETA |
|---|---|---|---|
| **Now** | Agent #1-#5 PR'ları pending review/merge gate | Agent cycles + Codex review | bu session |
| **Sprint A** | Vault canonical chain (BL-004-007) | Operator Vault current token | ~1h ops |
| **Sprint B** | Ops slot (BL-008/009/010/014/015) | Sprint A verify + KC/DNS/Slack/mailbox/PG access | ~6-12h ops total |
| **Sprint C** | External (BL-016) | Biotekno provider chain | ~1-2 hafta external |
| **Strategic** | BL-021/022 karar | Kullanıcı | immediate (whenever ready) |
| **Canary smoke** | BL-011 | Sprint B (BL-010) + Sprint C (BL-016 if OTP path) | ~1h |
| **Board acceptance** | BL-017-020 | Above completions + agent #3 PR | ~1 hafta board |
| **Time-passive** | BL-012 W1 | M7 stable | 30 day calendar |
| **M8 trigger** | Faz 21 begin | W1 + R10 mitigation plan | ~5-6 hafta total |

---

## §8 — Marker Discipline (No Fake Work + No Closure Language)

- Bu doc **bir handoff index'i** — operator action + agent parallel track'in dependency map'i. **Status authority değil.**
- Canonical status authority: [milestones.md](../notify/milestones.md) + [sprint-plan.md](../notify/sprint-plan.md) + [risk-register.md](../notify/risk-register.md) + [feature-matrix.md](../notify/feature-matrix.md) + [RB-faz-23-charter.md](RB-faz-23-charter.md)
- **Bu PR'ın closure claim'i kısmi scope-bounded**: bu doc PR'ı merge olduğunda, **çoğu backlog item'ı** operator/external/board/strategic'e bağlı kalır. **Scope exception (governance-trace closure)**: (a) BL-005 governance/no-revert closure (Codex 019e5a75 verdict — no functional revert needed; PR #995/#996 stays merged), (b) BL-006a ledger metadata update (PR #1031 MERGED — source_docs + rollback_runbook_ref); BL-006b runtime_selector update hâlâ pending BL-004 dep. Diğer Agent #1-#5 PR'ları kendi review/merge gate'lerinde — bu doc onları "MERGED" iddia etmez (pending review).
- Operator canonical RB'yi follow eder; bu index sadece sequence + dependency + agent parallel track görünürlüğü.

---

## §9 — Cross-AI Peer Review

- **Implementer**: Claude (Anthropic) — Session 49+ otonom doc-truth-sync sweep ekipi
- **Reviewer**: Codex (OpenAI) — thread `019e59f1-6779-71c2-9d21-3e588293a290` (initial REVISE iter-1) + this PR REVISE iter-2 absorb thread
- **HARD RULE adherence**: 
  - No Fake Work — operator-gated items canonical RB pointer'ı + sequence/dependency value-add only
  - No Closure Language — own narrative neutral verbs; backlog item'lar "pending review/merge gate" + "operator-bound" + "external-lead" + "user-decision"
  - Cross-AI provider-different — Codex review iter chain
  - Secret hygiene — bu doc'ta executable command yok; canonical RB'ler authoritative execution details'i taşır; operator secret hygiene'i ilgili RB kapsamında uygular
  - Pre-Production Full Authority — agent credential probe yaptı + honest gap documented (§1)

## Referanslar (canonical surfaces + RBs)

- Backlog index: `docs/notify/sprint-plan.md` operator queue + risk-register `Next Review` section
- Vault canonical evidence: `docs/faz-23-evidence/2026-05-22-openfga-notification-model-extension.md` §5
- WebPush activation: `docs/runbooks/RB-webpush-activation.md` §3.10 + §3.11
- M3 R2 KVKK closure: `docs/faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md` §R2 FINAL CLOSURE
- M4 prod cutover: `docs/faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md`
- D29 disiplin: `docs/adr/0010-vault-credential-lifecycle-and-dr.md`
- Outage fallback (BL-008): `docs/runbooks/RB-notification-outage-fallback.md`
- KC prod canary (BL-010, BL-011): `docs/runbooks/RB-prod-canary-kc-claim-setup.md`
- FBL mailbox (BL-014): `docs/runbooks/RB-fbl-mailbox-activation.md`
- Grafana notify PG datasource (BL-015): `docs/runbooks/RB-grafana-notify-pg-datasource.md`
- Graph mail adapter (deferred — asset-preserved precedent): `docs/adr/0024-graph-mail-adapter-defer.md`
- **BL-009 (DKIM CNAME) + BL-022 (NetGSM contract) demand-reactivated plan-out**: `docs/adr/0028-bl009-bl022-demand-reactivated-plan-out.md` (ADR-0028 2026-05-25; asset-preserved + demand-driven reactivation)
- Session 49+ truth-sync chain: PR #1002 + #1003 + #935 + #1005 + #1006 + #1009 + #1011 + #1013
- H read-only live evidence: `docs/faz-23-evidence/2026-05-24-h-live-evidence-resync.md`
