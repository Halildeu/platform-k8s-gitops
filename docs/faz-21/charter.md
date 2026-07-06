# Faz 21 — Multi-Tenant Migration Charter

> **Status**: Draft v1 — 2026-06-03
> **Canonical authority**: this document for scope, sub-faz, repo ownership, R10 invariants, M8 acceptance.
> **Predecessor architectural decision**: [ADR-0032 — Faz 21 tenant model v1](../adr/0032-faz-21-tenant-model.md).
> **Codex consult**: thread `019e8c3e-93c0-7793-a552-1643df88191d` (plan-time AGREE 2026-06-03).
> **Sprint plan reference**: Faz 23 M8 PR-2 B (Codex `019e8c24` order D→B→A→C).

---

## 1. Purpose, authority, predecessor contracts

Faz 21 multi-tenant migration is the program scope under which the platform pivots from a **single-tenant (v1 tenant == org)** authority model to a **multi-tenant authority model where one platform instance can host multiple isolated organization tenants** without cross-tenant data leak, blast radius, or operational entanglement.

This charter is the canonical scope/sub-faz/repo-ownership/invariant document. The architectural decision record [ADR-0032](../adr/0032-faz-21-tenant-model.md) is the canonical source for the v1 tenant model decisions (authz/persistence/Vault/JWT boundaries). Other proxies (sprint plan, milestones, runbooks) cite back to this charter + ADR-0032; they do not redefine.

### 1.1 Predecessor contracts (carry into Faz 21)

- [HARD RULE — Pre-Production Full Authority (2026-04-29)](../../CLAUDE.md): pre-prod boundary; tenant migration kararları cutover öncesi alınabilir.
- [HARD RULE — No Fake Work / No Cosmetic Operations](../../CLAUDE.md): tenant migration adımları doğrulanmadan accepted sayılmaz.
- [HARD RULE — TEST Cluster Scale-to-Zero YASAK](../../CLAUDE.md): test cluster paralel-multi-session model bozulmaz.
- [HARD RULE — Mavis CLI (2026-05-29)](../../CLAUDE.md): tenant-aware multi-session koordinasyon Mavis kanalında; secret-redaction.
- [ADR-0011 §2.3](../adr/0011-drift-detection-audit-cadence-boundary-governance.md): PR boundary declaration; tenant-touching PR boundary ZORUNLU.
- [ADR-0013 — Notification Charter](../adr/0013-notification-orchestration.md): Faz 23 charter, M2 D29-Authorized Layer-1 `org_id` boundary canonical.
- Faz 23 M2 D29-Authorized Layer-1 `org_id` org-boundary kararı (PR — board #754): JWT `org_id` claim canonical org authority; Faz 21 v1 tenant model bunu **devam ettirir**.

> **Live state drift (2026-06-03 test cluster dry-run)**: Notify backend persistence uses `org_id` ✓ (charter §1 lock holds). Endpoint-admin backend **currently uses `tenant_id`** column on 7/7 discovered tables (`endpoint_devices`, `endpoint_software_inventory_state_history`, `endpoint_outdated_software_snapshots/packages`, `endpoint_install_audit`, `endpoint_compliance_evaluations`, `endpoint_app_control_snapshots`). Faz 21.1 sub-faz **MUST** rename endpoint backend `tenant_id → org_id` to honor §1 / ADR-0032 §3.2 lock. Evidence: [`docs/faz-23-evidence/2026-06-03-faz-21-dryrun-on-test-cluster.md`](../faz-23-evidence/2026-06-03-faz-21-dryrun-on-test-cluster.md) §3. Pre-migration audit script (PR-3 A) accommodates the drift via `tenant_id` fallback chain so audit still completes; charter §1 / ADR-0032 §3.2 contract remains canonical and the rename is the binding requirement.

### 1.2 What this charter NOT do

- Faz 21 charter execution roadmap'tir; **migration trigger izni değil**. Bu izin M8 (Multi-tenant Trigger Gate) DoD ile gelir.
- Bu charter **physical isolation** (single schema vs schema-per-tenant vs DB-per-tenant) **kararını kilitlemez** — defer to pre-migration audit + dry-run evidence (Faz 21.0 sub-faz altında).

---

## 2. Tenant vocabulary + M8 trigger/deploy/runtime/migration gate semantics

### 2.1 Vocabulary

- **Tenant** — bir organizational instance; v1 itibarıyla `tenant == org` (mevcut Faz 23 M2 Layer-1 `org_id` claim'i ile aynı).
- **Tenant context** — bir request/job/event'in hangi tenant'a ait olduğunu taşıyan canonical pointer. JWT `org_id` (request flow), persistence row `org_id` column (write/read), OpenFGA tuple `tenant:<org_id>` namespace (authz), Vault path `kv/platform/tenants/<tenant>/...` (secrets), metric/log label `tenant=<org_id>` (telemetry), service-to-service header `X-Org-Id: <org_id>` canonical (ADR-0032 §3.4).
- **Cross-tenant** — birden çok tenant context'i kapsayan operasyon. Platform-level cron, multi-tenant analytics, operator-driven migration scripts. **Always tenant-aware**, **never tenant-blind**.
- **Tenant-isolated** — bir operation'ın sadece tek tenant context'i içinde kalması ve diğer tenant data'sına erişim üretememesi (read or write).
- **Tenant-blind** — anti-pattern; tenant context taşımayan operasyon. **YASAK**.

### 2.2 M8 — Multi-tenant Trigger Gate semantics

M8 (Faz 23 milestone #760) **Faz 21 migration başlatma izni gate**'dir. Yani:

- M8 **DoD blocker'ları geçilmedikçe** Faz 21 production migration başlatılmaz.
- M8 == "runtime invariant" değil; M8 == "deploy gate" + "migration phase entry gate".
- M8 == "we are permitted to begin executing Faz 21 v1 against production" anlamı.

M8 DoD (canonical): `docs/notify/milestones.md §M8` — M7 v1 ≥30 day stable + R10 mitigation plan ready + pre-migration audit + Faz 21 charter draft (this document).

**M8 ≠ runtime invariant enforcement.** Runtime invariant enforcement = R10 invariants (§4) — tenant context invariant, persistence invariant, side-effect isolation invariant, AI boundary invariant. Bu invariant'lar **her zaman aktif**, M8 ile başlamaz.

---

## 3. Repo ownership: platform-backend, platform-k8s-gitops, platform-web, platform-ai

Faz 21 multi-tenant migration cross-repo iş paketidir. Ownership map:

| Repo | Faz 21 sorumluluk |
|---|---|
| `platform-backend` | Tenant model code: JWT claim wiring + persistence `org_id` column + DTO tenant context propagation + AuthN/AuthZ filter + service-to-service tenant header. Migration backfill scripts. |
| `platform-k8s-gitops` (this repo) | Migration ops: kustomize overlays per-tenant config; Vault path migration (kv/platform/tenants/<tenant>/...); ESO ExternalSecret per-tenant; Prometheus tenant label injection; runbook (RB-faz-21-tenant-migration.md); observation harness (similar to M7 PR-1 D pattern). |
| `platform-web` | Frontend tenant context propagation: RTK Query interceptor tenant-aware; MFE-shell `org_id` claim render; UI tenant switcher (deferred to later sub-faz); tenant-scoped i18n. |
| `platform-ai` | Cross-tenant AI boundary: retrieval/inference context tenant partition; shared embedding/index'lerin tenant-aware filter'ı; prompt context tenant-scoped (NEVER cross-tenant context leak). Faz 21 trigger gate yine M8 ile aynı semantik. |

Cross-repo coordination: Mavis CLI agent dispatch (HARD RULE 2026-05-29) + board claim-before-work + PR boundary declaration ADR-0011 §2.3.

---

## 4. R10 invariants, forbidden patterns, acceptance evidence

### 4.1 R10 invariant set (minimum)

R10 (Faz 23 risk register: "Multi-tenant migration data drift / cross-tenant leak") mitigation execution (PR-3 A — Codex `019e8c24` order) **bu invariant'ları test eder + raporlar**.

#### Inv-1: Tenant context invariant

Her user-facing read/write **exactly-one** tenant context taşır.

- Request akışı: JWT `org_id` claim mevcut + valid; missing veya invalid → AuthN fail-closed (403 / 401)
- OpenFGA tuple check: subject `user:<id>` vs object `tenant:<org_id>/<resource>` — tenant namespace **deny-default**
- Service-to-service header: `X-Org-Id: <org_id>` **canonical** (ADR-0032 §3.4); `X-Tenant-Id` deprecated alias yalnız (JWT `org_id` ile mismatch ise fail-closed); missing canonical → service-layer fail-closed

#### Inv-2: Persistence invariant

Tenant-scoped row/event/outbox/audit/delivery kayıtları **`org_id` column olmadan** create/update **EDİLEMEZ**.

- DB CHECK constraint: `org_id IS NOT NULL` per-tenant table
- Service layer DTO mapper: `entity.setOrgId(securityContext.getOrgId())` zorunlu
- Migration backfill: orphan/mixed rows YASAK; pre-migration audit (PR-3 A) backfill plan canonical
- Outbox + audit + delivery: aynı invariant

#### Inv-3: Side-effect isolation invariant

Cache key, dedupe key, cron batch, provider credential, OpenFGA tuple, metric/audit correlation **tenant scope** içerir. Background job tenant başına **izole transaction/audit** üretir.

- Cache key pattern: `cache:<service>:<tenant>:<resource-id>` (tenant prefix ZORUNLU)
- Dedupe key: `dedupe:<tenant>:<event-hash>` (tenant prefix ZORUNLU)
- Cron batch: tenant başına ayrı transaction/loop; tek transaction tüm tenant'lar YASAK
- Provider credential: per-tenant Vault path `kv/platform/tenants/<tenant>/<provider>/...`; shared global credential implicit fallback **YASAK** (explicit platform-shared provider class gerekirse ayrı ADR/gate ile açılır)
- OpenFGA tuple: `tenant:<org_id>/<resource>` namespace
- Metric/log label: `tenant=<org_id>` label injection (Prometheus relabel + log MDC)
- **External callback correlation** (Codex iter-1 P1 absorb): provider DLR/webhook/inbound callback updates **exactly-one tenant** resolve etmeli; persistence update WHERE clause **org_id + external_id** çiftini birlikte taşır. Tenant predicate olmadan `WHERE provider_message_id = ?` YASAK.

#### Inv-4: AI boundary invariant

`platform-ai` retrieval/inference context tenant partition olmadan shared index/prompt context **kullanamaz**.

- Vector index: per-tenant partition veya tenant-filtered query
- Prompt context: NEVER cross-tenant context leak (one user's data → another user's response)
- Embedding cache: tenant-scoped key
- Inference audit: `tenant=<org_id>` label

### 4.2 Forbidden patterns (cross-tenant leak vectors)

| Anti-pattern | Niye yasak |
|---|---|
| Cross-tenant JOIN (`SELECT ... FROM org_a JOIN org_b`) | Tenant context invariant ihlali; query üzerinden data sızar |
| Cache/pubsub/dedupe key tenant prefix YOK | Side-effect isolation invariant ihlali; tenant A'nın cache hit tenant B'ye gelir |
| Body/query `tenant_id` ile JWT `org_id` override | Tenant context invariant ihlali; user'a tenant escalation izni |
| Missing tenant'ta fail-open | AuthN fail-closed kuralı ihlali; tenant context invariant ihlali |
| Cron tüm tenant'ları tek transaction'da işle | Side-effect isolation ihlali; bir tenant'ın hatası diğerlerini etkiler |
| OpenFGA object id'de tenant namespace YOK | Authz boundary erodes; allowed `user:x` herkesi denetler |
| Per-tenant provider secret shared global credential'a implicit fallback | Multi-tenant provider quota + audit boundary ihlali |
| AI shared embedding/prompt context tenant-blind | AI boundary invariant ihlali; prompt injection cross-tenant |
| **Provider callback/message id tenant predicate olmadan update** (Codex iter-1 P1) | External callback correlation cross-tenant leak; `WHERE provider_message_id = ?` tek başına YASAK |
| **Tenant-blind export/search/list endpoint** (Codex iter-1 minor) | Multi-tenant data scope erodes; admin report tenant predicate ZORUNLU |
| **Callback update by external id only** (Codex iter-1 minor) | Yukarıdaki callback predicate kuralının tek satırlık özeti — UPDATE statement WHERE clause tenant + external pair |

### 4.3 Acceptance evidence (R10 mitigation execution PR-3 A scope)

R10 mitigation execution PR'ı (Codex `019e8c24` order A) bu invariant'ların **her birini** test ederek:

- Inv-1 test: AuthN filter unit test + integration test (missing org_id 403, valid 200); `X-Org-Id` canonical header + `X-Tenant-Id` mismatch fail-closed test
- Inv-2 test: DB schema CHECK constraint test + service layer mapper test + migration backfill dry-run on snapshot
- Inv-3 test: cache key pattern unit test + cron tenant isolation integration test + Vault path discovery test + **DLR/webhook/inbound callback isolation test** (provider_message_id reused across tenants → update isolated by org_id + external_id pair; tenant-blind UPDATE rejected — Codex iter-1 P1)
- Inv-4 test: vector partition query test + prompt context tenant-filter test (platform-ai scope)

Acceptance evidence document: `docs/faz-23-evidence/<YYYY-MM-DD>-r10-invariant-test-evidence.md`.

---

## 5. Faz 21 sub-faz roadmap + DoD + deferred decisions

### 5.1 Sub-faz roadmap

| Sub-faz | Scope | DoD |
|---|---|---|
| **Faz 21.0 — Pre-Migration Audit** | R10 invariant test harness (PR-3 A); pre-migration audit script; dry-run on prod snapshot; per-tenant isolation test corpus | Audit script produces evidence; 4 invariants tested green; orphan/mixed row count==0 on snapshot |
| **Faz 21.1 — Logical Isolation Lock-In** | Tenant model code (platform-backend); persistence `org_id` constraint; service layer DTO mapper; AuthN filter wiring; OpenFGA tenant namespace; Vault path migration | All 4 R10 invariants enforced in code + tests; PR boundary declaration ADR-0011 §2.3 |
| **Faz 21.2 — Physical Isolation Decision Gate** | Pre-migration audit + dry-run evidence consumed; ADR-0037 (physical isolation: single schema vs schema-per-tenant vs DB-per-tenant); decision lock-in | ADR-0037 merged with explicit rationale + alternatives + reversal triggers |
| **Faz 21.3 — Migration Execution** | Per-tenant migration runbook + cutover; tenant data backfill; per-tenant cluster overlay; cross-tenant smoke test | Live multi-tenant evidence: 2+ tenant org_id'lerinin isolation kanıtlanır (no cross-leak) |
| **Faz 21.4 — Operational Closure** | Per-tenant Grafana dashboard; per-tenant alert; tenant onboarding runbook; SLA per-tenant tracking | Operational runbook canonical; tenant SLA observable |

### 5.2 DoD (canonical Faz 21)

- [ ] Faz 21.0 — Pre-migration audit evidence + R10 4 invariant test green
- [ ] Faz 21.1 — Tenant model code MERGED + cross-AI review + acceptance gate (D29 Up/Functional/Secured)
- [ ] Faz 21.2 — ADR-0037 physical isolation decision merged
- [ ] Faz 21.3 — Live multi-tenant evidence: 2+ tenant'larda isolation kanıtlanır + cross-leak smoke test green
- [ ] Faz 21.4 — Per-tenant ops runbook + per-tenant SLA observable
- [ ] All 4 R10 invariants enforced + tested (not just declared)
- [ ] No cross-tenant leak vector observed in 30-day post-cutover window

### 5.3 Deferred decisions (NOT locked in this charter)

| Decision | Reason | Resolution gate |
|---|---|---|
| Physical isolation: single schema vs schema-per-tenant vs DB-per-tenant | Pre-migration audit + dry-run evidence ihtiyacı | Faz 21.2 (ADR-0037) |
| Tenant switcher UI shape (platform-web) | Frontend scope sub-faz; v1 acceptance için kritik değil | Faz 21.4 veya post-Faz-21 v1.1 |
| Cross-tenant analytics platform (read-only aggregated) | v1 scope dışı; operator-only platform-level | Post-Faz-21 (Faz 22+ sub-faz) |
| Tenant-isolated AI fine-tuning | platform-ai capacity + business decision | Faz 22+ (Codex strategic consult required) |
| Tenant onboarding self-service (vs operator-manual) | v1 operator-manual; self-service v1.1+ | Post-Faz-21 v1.1 sub-faz |

---

## 6. References

- [ADR-0032 — Faz 21 tenant model v1 (sister doc)](../adr/0032-faz-21-tenant-model.md)
- [docs/notify/milestones.md §M8 — Multi-tenant Trigger Gate](../notify/milestones.md)
- [Faz 23 M2 D29-Authorized Layer-1 (board #754)](https://github.com/Halildeu/platform-k8s-gitops/issues/754)
- [R10 Multi-tenant migration risk (board #766)](https://github.com/Halildeu/platform-k8s-gitops/issues/766)
- [M8 Multi-tenant Trigger Gate (board #760)](https://github.com/Halildeu/platform-k8s-gitops/issues/760)
- [ADR-0011 §2.3 boundary declaration](../adr/0011-drift-detection-audit-cadence-boundary-governance.md)
- [ADR-0013 — Notification Charter](../adr/0013-notification-orchestration.md)
- Codex strategic consult: `019e8c3e-93c0-7793-a552-1643df88191d` (plan-time AGREE 2026-06-03)
- Sprint plan: Faz 23 M8 readiness — Codex order D→B→A→C (thread `019e8c24`)
