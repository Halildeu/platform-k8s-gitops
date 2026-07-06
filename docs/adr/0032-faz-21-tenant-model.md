# ADR-0032 — Faz 21 tenant model v1

> **Status**: Draft / Proposed v1 — 2026-06-03
> **Sister document (canonical scope/program)**: [docs/faz-21/charter.md](../faz-21/charter.md)
> **Codex consult**: thread `019e8c3e-93c0-7793-a552-1643df88191d` (plan-time AGREE 2026-06-03)
> **Sprint plan reference**: Faz 23 M8 PR-2 B (Codex `019e8c24` order D→B→A→C)
> **Builds on**: Faz 23 M2 Layer-1 `org_id` org-boundary canonical (board #754)

---

## 1. Context and existing contracts

Faz 23 M2 (D29-Authorized Layer-1) **org-boundary semantics** zaten yazılı + production'da: JWT `org_id` claim allow HTTP 202; missing `org_id` deny HTTP 403. Bu Layer-1 boundary mevcut single-org deployment için doğru çalışıyor.

Faz 21 multi-tenant migration **bu Layer-1'i daha iyi kullanır** — multi-org instance'a ölçeklenir. Açık soru: v1 multi-tenant tenant model **mevcut `org_id` boundary'sini devam mı ettirir**, **yoksa yeni `tenant_id` introduce mu eder**?

### 1.1 Existing contract carry-in

- **JWT claim shape**: `org_id` (Faz 23 M2 canonical)
- **OpenFGA**: tek model, tek store; tenant namespace tuple seviyesinde değil
- **Vault path**: `kv/platform/<service>/...` (service-flat)
- **DB persistence**: tek `org_id` column'lı tablo set; constraint not uniform across services
- **Metric/log label**: `org_id` Counter Tag retrofit Faz 23.8 M7 T4.3 sırasında yapıldı (PR #289)

### 1.2 Predecessor architectural decisions

- ADR-0011 §2.3 — boundary declaration (carrying)
- ADR-0013 — Notification charter (Faz 23 M2 Layer-1 canonical org_id)
- ADR-0010 §2.5 — boundary matrix

---

## 2. Decision: v1 tenant authority model

**Decision**: Faz 21 v1 tenant authority model = **`tenant == org`**.

- JWT claim `org_id` **canonical** v1 tenant pointer (Faz 23 M2 Layer-1 ile uyumlu)
- Yeni `tenant_id` claim/column introduce **EDİLMEZ** v1'de (alias/compat olabilir, second source-of-truth olmaz)
- Tüm tenant context propagation `org_id` üzerinden gerçekleşir
- Reversal trigger (§5): "tenant" semantik "org" semantik'ten genişlerse (örn. one org → multiple tenants), ADR-0037 ile re-charter

### 2.1 Decision rationale

- **Single source-of-truth**: iki ayrı tenant pointer (`org_id` + `tenant_id`) drift riski yaratır
- **Backward compat**: mevcut Faz 23 M2 D29-Functional org-boundary kanıtı + Layer-1 enforcement tüm code path'lerde aktif
- **Migration cost**: yeni `tenant_id` introduce + backfill + claim renaming yüksek maliyet; payoff Faz 21 v1 için yok
- **Codex strategic verdict** (`019e8c3e` 2026-06-03): "v1 tenant == org; ADR'de yaz"

---

## 3. Decision: authz, persistence, Vault, JWT boundaries

### 3.1 AuthZ — OpenFGA tenant boundary

**Decision**: aynı Zanzibar plane + tek OpenFGA store/model + **tenant-namespaced object/tuple contract**.

- Object id pattern: `<resource_type>:<org_id>/<resource_id>` (örn. `endpoint_device:org_a/dev_123`)
- Tuple subject/object'inde tenant namespace zorunlu
- Deny-default: tenant namespace mismatch → fail-closed
- Authz query: `check(user:<id>, can_<verb>, <resource_type>:<org_id>/<resource_id>)` — tenant namespace explicit

Ayrı store/model **yalnız reversal trigger** (§5) sonrası — örn. tenant-X kendi authz model'i ister.

### 3.2 Persistence — PG `org_id` column boundary

**Decision (v1 lock)**: tüm tenant-scoped table'lar `org_id NOT NULL` constraint.

- Mevcut single-tenant table'lar `org_id` column eklenir; backfill: pre-migration audit (Faz 21.0) snapshot data ile fill (org_a default)
- Migration backfill orphan/mixed row YASAK (R10 invariant Inv-2)
- Service-layer DTO mapper: `entity.setOrgId(securityContext.getOrgId())` zorunlu

> **Live state (2026-06-03 test cluster dry-run)**: `notify` schema persists `org_id` canonically (4 discovered tables on test cluster). `endpoint_admin_service` schema currently persists **`tenant_id`** (7 discovered tables on test cluster). Faz 21.1 sub-faz binding rename: endpoint backend `tenant_id → org_id` column + service-layer DTO mapper update + Flyway V<N> migration. Pre-migration audit script accommodates the drift via tenant_id fallback chain so Faz 21.0 audit completes; rename is the binding lock-in deliverable. Evidence: [`docs/faz-23-evidence/2026-06-03-faz-21-dryrun-on-test-cluster.md`](../faz-23-evidence/2026-06-03-faz-21-dryrun-on-test-cluster.md) §3.

**Deferred (Faz 21.2 ADR-0037)**: physical isolation — single schema vs schema-per-tenant vs DB-per-tenant. Pre-migration audit + dry-run evidence consumed sonrası karar.

### 3.3 Vault — tenant secret namespace

**Decision**: tenant secrets root altında dağılmaz; canonical path **`kv/platform/tenants/<tenant>/<service>/...`**.

- Tenant-scoped secret: `kv/platform/tenants/<org_id>/<service>/<key>` (örn. `kv/platform/tenants/org_a/notify/smtp_password`)
- Legacy service secrets: `kv/platform/<service>/...` kalabilir (org-flat secrets, infra-shared)
- Per-tenant provider credential (örn. notification provider): `kv/platform/tenants/<org_id>/<provider>/...` ZORUNLU; shared global credential **implicit** fallback YASAK (R10 Inv-3 anti-pattern); explicit platform-shared provider class gerekirse ayrı ADR/gate ile açılır.
- **Reserved segment** (Codex iter-1 minor absorb): `tenants` Vault path'inde reserved segment'tir; service adı `tenants` YASAK (path discovery collision guard).

ExternalSecret + ESO config: per-tenant `ExternalSecret` resource veya tenant-aware templating; runtime'da secret discovery `org_id` ile namespace'lenir.

### 3.4 JWT claim boundary

**Decision**: `org_id` **authoritative**. İleride `tenant_id` eklenirse:

- Alias/compat claim olur (`tenant_id == org_id`)
- Request body/query üzerinden `tenant_id` ile JWT `org_id` override **YASAK** (R10 Inv-1 + forbidden patterns)
- AuthN filter `tenant_id` claim ignore eder if `org_id` mevcut (org_id authoritative)
- Service-to-service header: `X-Org-Id: <org_id>` (canonical); `X-Tenant-Id` deprecated alias **yalnız** kabul edilir ve JWT `org_id` ile mismatch ise **fail-closed** (Codex iter-1 P1 absorb — charter §2.1 align)

---

## 4. Consequences and migration gates

### 4.1 Consequences

- **Pozitif**:
  - Tek truth source (no `org_id` vs `tenant_id` drift)
  - Mevcut Faz 23 M2 D29-Functional Layer-1 boundary enforcement direkt taşınır
  - Backend `securityContext.getOrgId()` mevcut wiring üzerine inşa edilebilir
  - Migration backfill mevcut single-tenant data'yı `org_id=org_a` ile mark eder; mass renaming yok

- **Negatif / risk**:
  - "Tenant" semantik "org" semantik'ten gelecekte ayrılırsa (örn. business request: one org → multiple workspace) reversal gerek (ADR-0037 veya yeni ADR)
  - `org_id` zaten Faz 23'ten geliyor; legacy semantik kararı v1'i bağlar (tenant ≡ org constraint kullanıcıya iletilir)
  - OpenFGA object namespace tüm tuple'larda update — migration boyutu büyük; pre-migration audit (Faz 21.0) cost-benefit hesabı yapar

### 4.2 Migration gates

| Gate | Trigger | Outcome |
|---|---|---|
| **Faz 21.0 Pre-migration audit** | This ADR merged + charter merged + Codex AGREE | R10 invariant test harness + audit script + dry-run on prod snapshot evidence |
| **Faz 21.1 Tenant model code lock-in** | Faz 21.0 evidence accepted | platform-backend + platform-k8s-gitops + platform-web + platform-ai PR'larında 4 R10 invariant enforced |
| **Faz 21.2 Physical isolation decision** | Faz 21.1 source-side ready + audit/dry-run evidence consumed | ADR-0037 single schema vs schema-per-tenant vs DB-per-tenant decision lock-in |
| **Faz 21.3 Migration execution** | ADR-0037 merged + Faz 21.1 cross-AI review + acceptance gate (D29) | Live multi-tenant evidence: 2+ tenant'larda isolation kanıtlanır + cross-leak smoke test green |
| **Faz 21.4 Operational closure** | Faz 21.3 evidence accepted | Per-tenant Grafana + per-tenant alert + tenant onboarding runbook + SLA observable |

---

## 5. Alternatives, deferred decisions, reversal triggers

### 5.1 Considered alternatives

- **Alt-A: New `tenant_id` claim/column** — REJECTED (drift risk, migration cost, Codex strategic verdict 2026-06-03)
- **Alt-B: Per-tenant OpenFGA store/model** — REJECTED v1 (operational complexity; deferred to reversal trigger)
- **Alt-C: Vault path `kv/<tenant>/platform/...`** — REJECTED (operator mental model + legacy compat preference)
- **Alt-D: Physical isolation = DB-per-tenant default** — DEFERRED Faz 21.2 ADR-0037 (audit + dry-run evidence sonrası)

### 5.2 Deferred decisions (NOT in this ADR)

- Physical isolation (single schema vs schema-per-tenant vs DB-per-tenant) — Faz 21.2 ADR-0037
- Tenant onboarding self-service flow — post-Faz-21 v1.1
- Tenant switcher UI shape (platform-web) — Faz 21.4 veya post-v1
- Cross-tenant analytics platform (read-only aggregated) — post-Faz-21

### 5.3 Reversal triggers

This ADR's v1 tenant authority model = `tenant == org` MUST be re-charterized if:

- Business request: one org → multiple tenant/workspace (e.g., parent company + subsidiaries each with isolated authz)
- Cross-tenant inheritance/parent-child tenant model required (e.g., MSP managing multi-tenant client orgs)
- Per-tenant OpenFGA model isolation explicitly demanded (e.g., tenant-X regulated workload + custom authz model)
- Per-tenant cluster physical isolation requirement (e.g., compliance: tenant data MUST live in tenant-controlled cluster)
- Faz 23 M2 Layer-1 `org_id` semantik **truly tenant'tan ayrılırsa** (yalnız Layer-2 channel-level authz Faz 23.2 v2 → bu reversal **DEĞİL**, Layer-2 tenant namespace'i `notification_topic:<org_id>/<topic>` gibi aynı plane içinde genişler; reversal ancak Layer-2 tenant semantiğini gerçekten ayrı bir dimension haline getirirse — Codex iter-1 minor absorb)
- **`org_id` global immutable/unique olamazsa** veya tenant-specific IdP/realm/issuer dış tenant ID zorunlu olursa (Codex iter-1 minor absorb)
- **Tenant-controlled KMS/Vault namespace/data residency** şartı gelirse (Codex iter-1 minor absorb)

Reversal trigger fires → new ADR (ADR-00XX) re-charterizes Faz 21 v2 tenant model + migration plan.

---

## 6. References

- [docs/faz-21/charter.md](../faz-21/charter.md) — canonical scope/sub-faz/repo ownership/R10 invariants/M8 acceptance
- [Faz 23 M2 D29-Authorized Layer-1 (board #754)](https://github.com/Halildeu/platform-k8s-gitops/issues/754)
- [R10 Multi-tenant migration risk (board #766)](https://github.com/Halildeu/platform-k8s-gitops/issues/766)
- [M8 Multi-tenant Trigger Gate (board #760)](https://github.com/Halildeu/platform-k8s-gitops/issues/760)
- ADR-0011 §2.3 — boundary declaration
- ADR-0013 — Notification charter
- Codex strategic consult: `019e8c3e-93c0-7793-a552-1643df88191d`
- Sprint plan: M8 readiness — Codex order D→B→A→C (thread `019e8c24`)
