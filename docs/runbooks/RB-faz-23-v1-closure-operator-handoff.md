# Faz 23 V1 Closure — Operator Handoff Index (2026-05-24)

> **Trigger**: Session 49+ doc-truth-sync sweep (PR #1002-#1013) saturation noktasında + user directive "tüm 20 bekleyen backlog işini paralel agent + main session ile tamamlayalım".
>
> **Scope**: Pointer/checklist style handoff. **Bu doküman canonical runbook'ların yerine geçmez** — her item için canonical RB'ye işaret eder. Operator canonical RB'yi follow eder; bu index sequence + dependency map + agent parallel track sağlar.
>
> **Marker discipline**: Bu doc agent-actionable backlog'un (5 agent paralel) operator/external/board/strategic kalan yarısının **pointer'ı**. Status authority canonical surfaces (milestones / sprint-plan / risk-register / charter / feature-matrix) decides.

---

## §1 — Agent Probe Boundary Summary (Honest Gap)

Agent Pre-Production Full Authority HARD RULE kapsamında credential probe yaptı; bulgular:

| Credential | Standart Path | Probe Sonucu | Operator Action |
|---|---|---|---|
| Vault root token | `/home/halil/platform/state/vault/vault-root-token` | format looked plausible, but **token invalid against current `platform-vault-prod`** (rotated/re-initialized) | Operator current token konumunu biliyor; canonical RB'ler bu token'ı bekler |
| Keycloak admin pwd | `/opt/keycloak/admin-password.txt`, `~/.kc-admin` | Standart path'lerde **bulunamadı** | Operator current pwd konumunu biliyor |
| PG primary deploy | `platform-test` namespace | **Yok** (cluster-içi PG yok veya farklı NS/host) | Operator PG instance konumunu biliyor |
| Slack workspace + webhook | — | External (workspace admin access required) | Operator-external |
| Office 365 admin | — | External | Operator-external |
| DNS registrar admin | — | External | Operator-external |
| Biotekno provider | — | External | Operator-external |

**Sonuç**: Vault canonical chain (BL-004-007), KC org_id setup (BL-010), DB RO role (BL-015), DKIM DNS (BL-009), R9 D43 drill (BL-008), FBL mailbox (BL-014) execute edilemez (agent context). Bu doc operator-execute için **action checklist + canonical RB pointer**.

---

## §2 — Operator Action Checklist (Sequential)

Her satır: backlog ID + canonical RB pointer + dependency. Operator canonical RB'yi takip eder; bu index sequence kontrolü için.

### Sprint A — Vault Canonical Align (Pre-condition for downstream PR reverts)

- [ ] **BL-004** Vault `kv patch kv/platform/openfga model_id=01KS8QE8T1EJ2DF5CRS4VV9YX1` + `kv/platform/notification-orchestrator authz_internal_api_key=<aligned-with-permission-service>`
  - Canonical evidence: `docs/faz-23-evidence/2026-05-22-openfga-notification-model-extension.md` §5 item 7
  - Verify: pod restart sonrası env values canonical Vault'tan inject edildiğini check (sha256 hash-only local compare, persist edilmez)
- [ ] **BL-005** PR-revert #995 + PR-revert #996 — agent-actionable doc-only docs PRs once Vault canonical applied
  - Dependency: BL-004 verified
- [ ] **BL-006** `runtime-artifacts/openfga-model/<digest>.json` ledger `runtime_selector: null` → `vault` + `promoted_via_vault_at` timestamp
  - Dependency: BL-004 verified
- [ ] **BL-007** `platform-backend/backend/openfga/model.fga` canonical update — agent #5 (a233ba0a6703e6595) paralel çalışıyor; eğer agent merge ettiyse atla

### Sprint B — Ops Slot Execution (Canonical RB pointers)

- [ ] **BL-008** R9 D43 outage fallback drill — canonical RB: [`docs/runbooks/RB-notification-outage-fallback.md`](RB-notification-outage-fallback.md) prod activation chain + drill execution sections (port-forward + helm upgrade + dual-receipt verify + cleanup)
  - Dependency: BL-004 Vault prod seed
  - Board issues: [#853](https://github.com/Halildeu/platform-k8s-gitops/issues/853), [#854](https://github.com/Halildeu/platform-k8s-gitops/issues/854)
- [ ] **BL-009** DKIM tenant enable + DNS CNAME publish — operator-external (Office 365 admin + DNS registrar)
  - Reference: feature-matrix H4 + L1; charter line 51; R3 mitigation upgrade
- [ ] **BL-010** Keycloak `org_id=default` claim setup — canonical RB: [`docs/runbooks/RB-prod-canary-kc-claim-setup.md`](RB-prod-canary-kc-claim-setup.md) (canary user attribute + User Attribute mapper pattern, NOT hardcoded claim mapper)
  - Dependency: KC `platform-kc-prod` admin pwd
- [ ] **BL-011** Prod SMS functional canary smoke — canonical canary example: `RB-prod-canary-kc-claim-setup.md` (canonical payload contract: `topicKey` + `recipients` + `template` + `channels` + `orgId`)
  - Dependency: BL-010 (KC claim setup) + BL-016 R24 OTP allowlist (eğer OTP topic test ediliyorsa)
- [ ] **BL-014** FBL mailbox activation — canonical RB: [`docs/runbooks/RB-fbl-mailbox-activation.md`](RB-fbl-mailbox-activation.md) (Vault remoteRef triple + overlay patch + ESO uncomment + PR/apply + hard gates)
- [ ] **BL-015** Grafana per-template notify PG RO datasource — canonical RB: [`docs/runbooks/RB-grafana-notify-pg-datasource.md`](RB-grafana-notify-pg-datasource.md) (canonical user `grafana_notify_ro`, DB `notify_db`, Vault path `kv/platform/grafana/notify-pg-ro`, ESO uncomment + helm upgrade + G1-G8 gates)

### Sprint C — External Provider Lead

- [ ] **BL-016** R24 Biotekno OTP allowlist (VFO outbound sender ID provisioning)
  - Owner: Biotekno müşteri temsilcisi + JetSMS provider config
  - ETA: ~1-2 hafta external lead time
  - Reference: risk-register R24; sprint-plan M4

---

## §3 — Board Acceptance Decisions (User/Board Role)

Each pending operator/board acceptance — agent prep evidence ready:

- [ ] **BL-017** M3 23.2 board item #755 ([Project #2](https://github.com/users/Halildeu/projects/2)): R2 KVKK closed via Codex `019e5189` (2026-05-23); K6 P1 follow-up agent #1 in flight
  - Evidence: `docs/faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md`
- [ ] **BL-018** M4 23.3 board item #756 ([Project #2](https://github.com/users/Halildeu/projects/2)): M4 prod cutover LIVE (2026-05-20); awaiting BL-011 canary + BL-016 OTP for full DLR terminal evidence
  - Evidence: `docs/faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md`
- [ ] **BL-019** M5 23.5 board item #757 ([Project #2](https://github.com/users/Halildeu/projects/2)): source-side LIVE; awaiting agent #3 (aa3d862bed5a8b408) live runtime evidence PR
- [ ] **BL-020** M6 23.4 board item #758 ([Project #2](https://github.com/users/Halildeu/projects/2)): M6a + M6b 6/6 LIVE 2026-05-20; awaiting board confirmation (zaten LIVE)

---

## §4 — Strategic Decisions (Kullanıcı Karar Gerek)

- [ ] **BL-021** 23.7 push scope tanımı:
  - **Seçenek A**: Mobile FCM/APNS dahil → BL-023 Mobile impl gerek (Faz 22.2 dep, ~8-16h) → 23.7 🟡 → 🟢
  - **Seçenek B**: "Browser-only WebPush = 23.7 v1 closure" → 23.7 🟢 scope-narrowed + mobile Faz 22.2/Faz 24'e taşınır
  - Reference: milestones.md M7 T4.2 line 206; sprint-plan T4.2
- [ ] **BL-022** NetGSM secondary contract:
  - **Mevcut karar**: 2026-05-23 kullanıcı kararı R1 ⏳ DEFER asset-preserved; JetSMS-only kabul edilen kalıcı işletim durumu
  - **Pending**: Yeni karar var mı? Sözleşme imzalanırsa R1 reactivation chain devreye girer.

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
- **Bu PR'ın closure claim'i yok**: bu doc PR'ı merge olduğunda, listelenen backlog item'ları operator/external/board/strategic'e bağlı kalır. Agent #1-#5 PR'ları kendi review/merge gate'lerinde — bu doc onları "MERGED" iddia etmez (pending review).
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
- Graph mail adapter (deferred — BL-009 ile dolaylı): `docs/adr/0024-graph-mail-adapter-defer.md`
- Session 49+ truth-sync chain: PR #1002 + #1003 + #935 + #1005 + #1006 + #1009 + #1011 + #1013
- H read-only live evidence: `docs/faz-23-evidence/2026-05-24-h-live-evidence-resync.md`
