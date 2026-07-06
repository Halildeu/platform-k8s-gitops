# 0029 — Hibrit D: perf-alertmanager Teams Primary + Slack Dormant Asset-Preserved

> **Status**: Accepted
> **Tarih**: 2026-05-27
> **Karar otoritesi**: Codex thread `019e6b24` (Hibrit D strategic verdict — cross-AI peer review REVISE→AGREE iter-1)
> **Antecedent reviews**: `019e6abe` (Session 50 strategic A plan + B+C+D batch), `019e6ad9` (Session 50 closure batch absorb)
> **Öncüller**: [ADR-0013 — Notification orchestration](./0013-notification-orchestration.md), [ADR-0027 — D43 SMTP Primary + Teams Deferred](./0027-d43-teams-power-automate-defer.md) (mirror pattern reference — D43 incident channel ile bu perf-regression channel paralel pattern), [V2.1-perf-alert-receiver.md](../runbooks/V2.1-perf-alert-receiver.md) (refactor scope)
> **Implementation State (2026-05-27)**: **Decision/target canonical (this ADR, PR-1)**: Teams Power Automate workflow primary canlı path (helm-values `webhook_configs` + ESO `perf-alertmanager-teams-secrets` 1-key); Slack workspace path dormant (no active rendered config, no non-empty Vault secret, no Helm receiver block) asset-preserved tenant demand-reactivated.
> **Current rendered state**: helm-values + ESO **HÂLÂ Slack-canonical** (`slack_configs` receiver + `SLACK_WEBHOOK_URL` bekliyor). PR-1 sadece **decision/target state mühürler**; rendered state migration **PR-2 helm/ESO atomic** + **PR-3 operator activation** ile yapılır. PR-2 merge sonrası current rendered = target = Teams; Slack dormant.
> **Yürütür**: Faz 23.x notification platform — perf regression alert channel routing track (V2.1 Exit #4 closure dependency)
> **Reactivation runbook**: [RB-perf-alerts-slack-reactivation-chain.md](../runbooks/RB-perf-alerts-slack-reactivation-chain.md) (post-trigger atomic activation chain, tenant Slack workspace demand-driven)

---

## Context

`perf-alertmanager` use case (V2.1 Exit #4) için **alert delivery channel** kararı 2026-05-27'de iki yöne ayrıştı:

### Conflicting interpretation paths

**Path 1 — Original V2.1 runbook (`docs/runbooks/V2.1-perf-alert-receiver.md`, 2026-05-22)**:
- Yorum: Slack workspace `#perf-alerts` kanonik alert teslim hedefi; `slack_configs.api_url_file` Alertmanager pattern.
- Impl: Helm values `slack_configs` LIVE; ESO `perf-alertmanager-secrets` `SLACK_WEBHOOK_URL` Vault'tan bekliyor (`monitoring` ns).
- Owner-action: Slack workspace admin → Incoming Webhook URL üret → Vault `kv/platform/perf-alertmanager.SLACK_WEBHOOK_URL` seed.

**Path 2 — Kullanıcı 2026-05-27 direktifi (tekrarlanan)**:
- Yorum: "Slack kullanmıyorum, Teams kullanıyorum" (kullanıcının workspace tooling = Microsoft Teams; Slack workspace YOK).
- Önceki precedent: ADR-0027 + PR #1059 D43-TEAMS Hibrit C (D43 outage fallback için "SMTP primary + Teams future-trigger asset-preserved" pattern mühürlü).
- Pattern bu kez tersine çevrilir: **Teams primary (bizim canlı path) + Slack dormant (başka tenants demand-reactivated)**.
- Ek kullanıcı direktifi: **"Slack altyapısını bozma"** — başka firmalar Slack workspace'i kullanabilir (multi-tenant gelecek için asset-preserved); Slack manifest/config silinmez/revert edilmez.

### Codex `019e6b24` Hibrit D revize verdict (REVISE→AGREE)

> "Yüksek seviye karar doğru: bizim canlı path Teams, Slack asset-preserved, Slack silinmez/revert edilmez/yasaklanmaz. Ama önerideki iki teknik parça revize edilmeli: Slack'i şu an parallel delivery'ye sokma ve TEAMS + SLACK'i aynı required ExternalSecret içinde tutma."
>
> "Kabul edilebilir pattern: **Teams primary active rendered config, Slack dormant asset-preserved reactivation chain**. ADR-0027 emsali 'dormant asset' için active dependency yaratmamayı özellikle söylüyor: no active rendered config / no non-empty Vault secret / no Helm receiver block gibi sınırları var. Perf için bu tersine çevrilebilir, ama aynı disiplin korunmalı: Teams aktif, Slack dormant."

Bu çelişki resolution + hibrit yön normalizasyonu ayrı bir ADR ile kanıtlanır (mevcut V2.1 runbook + R27 üzerinde override yapmadan); ileride başka tenant Slack workspace'i için trigger gelirse [RB-perf-alerts-slack-reactivation-chain.md](../runbooks/RB-perf-alerts-slack-reactivation-chain.md) çalıştırılır.

---

## Decision

### D1 — Microsoft Teams Power Automate workflow perf-alertmanager primary canlı path olarak adopt edilir

Bizim (acik tenant) için canonical alert delivery path:

- `helm-values/kube-prometheus-stack/values-prod.yaml` `perf-alerts-teams` receiver `webhook_configs.url_file` tek leg (Power Automate workflow URL → raw Alertmanager v4 JSON POST → flow içinde Adaptive Card transform → Teams `#perf-alerts` channel)
- ExternalSecret `perf-alertmanager-teams-secrets` `monitoring` ns (1-key: `TEAMS_WEBHOOK_URL` ← Vault `kv/platform/perf-alertmanager.TEAMS_WEBHOOK_URL`)
- Vault path `kv/platform/perf-alertmanager` canonical key `TEAMS_WEBHOOK_URL` (active); `SLACK_WEBHOOK_URL` **NOT present** (dormant)
- Helm receiver `perf-alerts-teams` route matcher: `team=perf` veya `alertname=~PerfFederation*` (V2.1 runbook §4 throttle/dedupe policy korunur)
- Bridge trail (`alarm-receiver-bridge` GitHub Issues path) `continue: true` ile severity route'a düşmeye devam eder (ADR-0027 D43 helm-values pattern emsali)

### D2 — Slack workspace path dormant, asset-preserved başka tenants için

Mevcut Slack pattern (`slack_configs` referansları, V2.1 runbook Slack-canonical sections) **canlıya alınmaz** ama **asset olarak korunur**:

- Helm values `slack_configs` block dormant — receiver tanımı yok, route matcher yok, **no active rendered config**
- ExternalSecret `perf-alertmanager-slack-secrets` desired-state snippet olarak `RB-perf-alerts-slack-reactivation-chain.md` içinde fenced code block; kustomization'a dahil **DEĞİL** (no active dependency)
- Vault `kv/platform/perf-alertmanager.SLACK_WEBHOOK_URL` **not present** (no non-empty Vault secret); seed sadece reactivation trigger sonrası
- V2.1 runbook §"Slack reactivation chain" subsection — atomic reactivation pattern (tenant Slack workspace demand + admin webhook üret + Vault seed + ESO refresh + receiver activate + smoke alert receipt)
- Codex `019e6b24` warning: "active route active kalırsa her alertte notify failure/log noise; active dependency yaratmamayı özellikle söylüyor" → **Slack route ACTIVE değil**, sadece dormant snippet template

### D3 — ADR-0029 mirror ADR-0027 disiplini

| Pattern aspect | ADR-0027 (D43 outage fallback) | ADR-0029 (perf-alertmanager regression) |
|---|---|---|
| **Use case** | Notification orchestrator down → fallback channel | Perf regression alerts (PerfFederationSmoke*) |
| **Active path** | SMTP Office 365 + Mailpit drill | Teams Power Automate workflow + Adaptive Card |
| **Dormant path** | Teams Power Automate workflow (asset-preserved future trigger) | Slack workspace incoming webhook (asset-preserved tenant demand) |
| **Active disable disipline** | Teams no rendered config + no secret + no receiver | Slack no rendered config + no secret + no receiver |
| **Reactivation runbook** | RB-d43-teams-reactivation-chain.md | RB-perf-alerts-slack-reactivation-chain.md |
| **Reactivation atomicity** | helm-values + ESO + Vault seed + receipt smoke aynı window | helm-values + ESO + Vault seed + receipt smoke aynı window |
| **Owner-action scope** | ops + Microsoft Teams workspace admin | ops + Slack workspace admin (tenant-specific) |
| **Current rendered dependency** | helm-values + ESO active SMTP-only LIVE; Teams not rendered | helm-values + ESO active Slack-only (PR-2 öncesi); Teams will be rendered PR-2; Slack will become dormant PR-2 |
| **Activation evidence class** | SMTP receipt Mailpit + drill evidence (2026-05-24 BL-008) | Synthetic alert E2E → Teams Adaptive Card receipt + bridge trail evidence (PR-3 closure) |

### D4 — Risk register: R29 NEW (Teams Power Automate workflow lifecycle drift for perf-alertmanager)

ADR-0027 D43 use case'i için R27 NEW eklenmişti (Microsoft Teams Power Automate workflow lifecycle drift if D43 Teams fallback is activated). Bu ADR-0029 perf-alertmanager için yeni risk açar:

- **R29 — PR-1'de risk-register'a `pending activation` statüsüyle eklenmiştir** (PR-1 docs scope; risk becomes `active` PR-3 sonrası Teams receiver + Vault TEAMS_WEBHOOK_URL + synthetic Teams smoke receipt evidence kanıtlandığında).
- **R29 detayı**: Teams Power Automate workflow perf-alertmanager primary path **aktif olacağı için** (PR-3 sonrası) **active lifecycle drift risk** (R27'den farkı: R27 dormant idi, R29 PR-3 sonrası ACTIVE). Mitigation chain (RB-perf-alerts-slack-reactivation-chain.md §5 + R27 7-step mitigation chain reuse): service-account/team-owned flow + exported package backup + monthly synthetic Teams smoke + defense-in-depth (Teams+SMTP+GitHub Issue) + DLP/license/quota preflight + flow run-history failed-run monitoring + URL rotation rehearsal.
- **Status timeline**:
  - PR-1 (bu): R29 row `🔵 PENDING ACTIVATION` (Teams not yet rendered/active)
  - PR-2 helm/ESO atomic: status unchanged (rendered config aktif ama operator activation evidence yok)
  - PR-3 operator activation evidence sonrası: R29 row `🟡 Active` (live monitoring required)

### D5 — Per-tenant pattern: Hibrit D semantic for multi-tenant flexibility

acik tenant: Teams primary. Başka tenant (örn. başka firma Slack workspace'i ile gelir): aynı V2.1 receiver chain + Slack reactivation chain runbook + tenant-specific Vault path veya tenant-scoped overlay. Pattern multi-tenant ready:

- Vault path tenant-scoped (`kv/platform/perf-alertmanager` veya `kv/platform/tenants/<tenant>/perf-alertmanager`)
- ESO tenant-aware overlay (`kustomize/overlays/<env>-<tenant>/eso/alertmanager/`)
- Receiver tenant-aware route matcher (`tenant_id=<id>` + `team=perf`)
- Aynı reactivation runbook her tenant için kullanılabilir; tek değişiklik webhook URL kaynağı (Slack vs Teams) + flow setup

### D6 — Implementation scope split (3-PR chain)

Codex `019e6b24` revize: mega-PR riskli, ESO+helm atomik kalmalı:

- **PR-1** (BU ADR): docs scope — ADR-0029 + RB-perf-alerts-slack-reactivation-chain.md NEW + V2.1-perf-alert-receiver.md refactor + ADR README index update
- **PR-2**: helm-values + ESO desired-state atomic — Teams `webhook_configs` receiver + `perf-alertmanager-teams-secrets` ExternalSecret (`SLACK_WEBHOOK_URL` rendered config sıfırlama dahil); kustomize build sanity + render evidence
- **PR-3**: operator activation/evidence — Power Automate workflow URL seed + Vault put + ESO sync + Alertmanager config verify + synthetic alert E2E + bridge trail evidence (V2.1 Exit #4 closure)

---

## Consequences

### Pozitif

- **Kullanıcı kuralı kalıcı**: "Slack altyapısını bozma" + "Teams kullan" iki direktif tek pattern içinde mühürlü; gelecek session'larda agent bu kararı tekrarlamadan uygular
- **Multi-tenant ready**: Hibrit D pattern başka tenants için (Slack workspace'li firmalar) hazır asset
- **ADR-0027 mirror disiplini**: dormant asset disiplini (no active config/secret/receiver) ADR-0027 emsali ile bilinçli, dead-code riski mitigated
- **Failure isolation**: Teams primary fail olduğunda alert kaybı bridge trail (`alarm-receiver-bridge` GitHub Issues `continue:true`) ile defense-in-depth
- **No production-ready overclaim**: Teams primary path operator activation gerek; ADR-0029 sadece desired-state mühürler, "production-ready" iddiası kapalı
- **Codex Hibrit D verdict mühürlü**: Cross-AI peer review chain trace + reactivation runbook + ADR pattern aynı disiplin

### Negatif

- **R29 NEW**: Teams Power Automate workflow active path = active lifecycle drift risk (R27'den daha yüksek severity; R27 dormant idi). Active mitigation gerek (monthly synthetic Teams smoke + flow run-history monitoring).
- **3-PR chain governance overhead**: PR-1 (docs) + PR-2 (helm/ESO atomic) + PR-3 (operator) — her birinin kendi cross-AI peer review chain'i (her PR Codex AGREE şart)
- **Slack reactivation runbook ek bakım yükü**: ADR-0029 + V2.1 runbook + RB-perf-alerts-slack-reactivation-chain.md üç doc senkron tutulmalı
- **Owner-action 2 aşamalı**: PR-2 merge sonrası operator Power Automate workflow + Vault seed (5-10 dk); önce repo refactor gerek (V2.1 Exit #4 closure'ı bir adım uzaklaştırır)
- **Tenant Slack reactivation aktif test edilmiyor**: dormant snippet template-only; gerçek tenant trigger gelene kadar reactivation runbook semantically validated değil (R23/ADR-0024 + R27/ADR-0027 emsali aynı kabul edilebilir risk)

### Risks Mitigated by Asset-Preservation

- "Slack stale code temizleme" anti-pattern engellendi (Codex `019e6b24` D7 risk listesi item-3): ADR-0029 explicit "asset olarak korunur" + reactivation runbook = dokümante stale değil
- Parallel delivery alert fatigue engellendi: Codex revise sonrası "Slack route ACTIVE değil" → tek Teams kanalı (Hibrit C D43 SMTP-only parallel)
- Multi-tenant matcher yanlış kullanım engellendi: D5 tenant-scoped pattern (Vault path + ESO overlay + route matcher tenant-aware)

---

## Alternatives

### A1 — Slack pattern silme (REJECTED, kullanıcı kararı 2026-05-27)

V2.1 runbook + helm-values + ESO Slack referanslarını tamamen silmek. **Reddedildi** çünkü:
- Kullanıcı explicit "Slack altyapısını bozma" — multi-tenant gelecek için asset-preserved
- ADR-0027 dormant asset disiplini bu pattern'i destekliyor
- Dead-code temizliği "demand-reactivated future trigger" pattern'iyle çelişir

### A2 — Slack + Teams parallel delivery (REJECTED, Codex `019e6b24` REVISE)

Her alert hem Slack hem Teams kanalına gönderilir (`continue:true` ile). **Reddedildi** çünkü:
- Codex: "Alertmanager `continue:true` failure-aware fallback değildir; sadece additional receiver"
- Slack key empty → ESO `Ready=False` → Teams path da bozar
- Alert fatigue (her alert 2 kanal); multi-tenant yanlış matcher riski

### A3 — Tek ExternalSecret 2-key (Teams + Slack) (REJECTED, Codex `019e6b24` REVISE)

Aynı `perf-alertmanager-secrets` içinde `TEAMS_WEBHOOK_URL` + `SLACK_WEBHOOK_URL` required tutmak. **Reddedildi** çünkü:
- Codex: "biri property missing/empty olursa Ready=False zincir Teams'i de bozar"
- Doğru pattern: ayrı ExternalSecret + ayrı K8s Secret (Teams active, Slack dormant snippet kustomization dışında)

### A4 — Mega-PR (helm + ESO + ADR + runbook + memory tek PR) (REJECTED, Codex `019e6b24` REVISE)

Tek atomic PR'da tüm değişiklik. **Reddedildi** çünkü:
- Codex: "Mega PR riskli; cross-AI peer review chain her PR için gerekli; helm/ESO atomik ama ADR/runbook ayrı scope"
- Split önerisi: PR-1 docs (bu) + PR-2 helm/ESO atomic + PR-3 operator activation

### A5 — Defer (perf-alertmanager şimdi yapma, FBL + R9 ile beraber kuyruğa al) (REJECTED, kullanıcı direktif)

Kullanıcı explicit "Teams ile devam" — defer değil, immediate Hibrit D pattern. Owner-action 5-10 dk; PR chain ile birkaç saat scope. Diğer operator-bound iş (BL-014/R9 #854/BL-016) paralel kuyruk; bu pattern'i defer etmek HARD RULE Yarın YASAK ihlali olur.

---

## Implementation Plan (PR-1 scope — bu ADR)

PR-1 (docs-only — bu PR scope minimal-touch):

1. ✅ `docs/adr/0029-hibrit-d-perf-alerts-teams-primary.md` NEW (bu doc)
2. ✅ `docs/adr/README.md` index update — ADR-0029 row eklenir
3. ✅ `docs/runbooks/V2.1-perf-alert-receiver.md` **NOTICE-ONLY** edit — header'a "🔄 2026-05-27 Hibrit D Pivot Notice (ADR-0029)" subsection eklenir; Slack-canonical orig sections KORUNUR (historical reference + reactivation template) — **full Teams-canonical sweep PR-2 helm/ESO + PR-3 operator activation ile birlikte yapılır** (current-state drift önleme: helm/ESO rendered config Teams'e geçmeden runbook gövdesini Teams-canonical yapmak overclaim olur)
4. ✅ `docs/runbooks/RB-perf-alerts-slack-reactivation-chain.md` NEW (RB-d43-teams-reactivation-chain.md mirror — atomic 6-step reactivation: Slack workspace admin webhook üret + Vault seed + ESO refresh + helm route activate + receiver definition add + synthetic Slack alert receipt)
5. ✅ `docs/notify/risk-register.md` — R29 row `🔵 PENDING ACTIVATION` eklenir (PR-3 sonrası `🟡 Active`'e döner)

PR-2 + PR-3 ayrı (helm/ESO atomic + operator activation evidence + V2.1 runbook full sweep PR-2/PR-3'te).

---

## Cross-AI Peer Review

- **Plan-time (`019e6b24`)**: REVISE→AGREE ready_for_impl: true (this ADR design + 3-PR split)
- **Post-impl (PR-1 review)**: pending Codex iter
- **Implementer**: Anthropic Claude (HARD RULE 2026-05-05/14 — code yazan AI ≠ review AI)
