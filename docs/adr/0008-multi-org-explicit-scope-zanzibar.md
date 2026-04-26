# 0008 — Multi-Org Explicit-Scope Zanzibar Contract

## Status

**Accepted** (2026-04-26) — Faz 21.3.

Related:
- ADR-0013 (Zanzibar plane / permission-service hub) — extends, does NOT replace.
- ADR-0005 (dual datasource reporting) — `data_access` schema lives in
  `reports_db` for lineage-locality.
- PLAN.md Faz 21 (Veri Erişimi Multi-Org Scope Layer)
- `docs/migration/depolar-source-decision.md` (Faz 21.A — depot=DEPARTMENT)

## Context

UI'da "Veri Erişimi → Şirketler / Projeler / Depolar / Şubeler" paneli
explicit-scope contract gerektiriyor: **kullanıcı scope atanmadan hiçbir
veri göremez**. Hizmet kurum-bazlı (multi-org); bir kurumun birden fazla
Workcube COMPANY'si olabilir. Şu anki tek kurum: AÇIK (V19 seed).

### Naming convention (PG ↔ OpenFGA)

PG-side `data_access.scope.scope_kind` ENUM:
- `'company' | 'project' | 'depot' | 'branch'`

V19 + V20 immutable migrations PG-side `'depot'` kullanıyor (Türkçe
"depo" UI sekmesi karşılığı). OpenFGA model'de eşdeğer tip ismi
`warehouse` (Faz 19 öncesi yazılan model). Bu naming farkı kalır;
tuple writer mapping yapar:

| PG `scope_kind` | OpenFGA object type | UI sekmesi (TR) |
|---|---|---|
| `company` | `company` | Şirketler |
| `project` | `project` | Projeler |
| `depot` | **`warehouse`** | Depolar |
| `branch` | `branch` | Şubeler |

### Current model.fga state (`bootstrap/local-fixtures/openfga/model.fga`)

Faz 19.11 residual migration: model dosyası bu repoya çekildi
(platform-ssot upstream'den read-only fetch). **Mevcut tipler ZATEN var**
(organization + company + project + warehouse + branch + module + action +
report). Faz 21.3 için boş slate değil; aşağıdaki **explicit-scope
düzeltmeleri gerekiyor** (Faz 21.3 backend PR'ında):

```fga
# Mevcut (auto-grant DAHİL — explicit-scope contract'a aykırı)
type company
  relations
    define org: [organization]
    define admin: [user] or admin from org    # ← auto-grant YASAK
    define manager: [user]
    define member: [user] or manager or admin
    define viewer: [user] or member            # ← transitive grant
```

Faz 21.3 explicit-scope eksikleri:
1. `admin from org`, `admin from company` auto-grant relations kaldırılmalı.
2. `viewer: [user] or member`, `viewer: [user] or operator` gibi
   transitive view zincirleri kaldırılmalı.
3. `organization#member` data visibility grant değildir (UI mandate).
4. Hiyerarşik containment relation (parent_org/_company) **ownership**
   metadata kalır, ama `viewer` auto-grant ÜRETMEZ.

## Decision

### Target type model (Faz 21.3 backend PR — `bootstrap/local-fixtures/openfga/model.fga`)

```fga
type user

type organization
  relations
    define member: [user]    # tenant binding only — NO data grant
    define admin: [user]     # scope assignment authority

type company
  relations
    define org: [organization]                   # ownership/containment
    define viewer: [user]                        # explicit assignment only
    # NO `admin from org` — explicit-scope contract

type project
  relations
    define company: [company]                    # ownership/containment
    define viewer: [user]                        # explicit assignment only
    # NO `admin from company`, NO `viewer: [user] or manager or admin`

type warehouse
  relations
    define company: [company]                    # ownership/containment
    define parent_warehouse: [warehouse]         # 3-level hierarchy
                                                  # (Depo→Lokasyon→Raf)
    define viewer: [user]                        # explicit-only; NO transitive
                                                  # parent_warehouse YOK

type branch
  relations
    define company: [company]                    # ownership/containment
    define viewer: [user]                        # explicit assignment only
    # NO `admin from company`, NO `viewer: [user] or member`

# module/action/report types unchanged (existing model)
```

**Naming**: OpenFGA tip adı `warehouse`; PG `scope_kind = 'depot'`. Tuple
writer mapping yapar (yukarıdaki PG↔FGA tablosu).

### Explicit-scope kontrat noktaları

1. **`organization#member` data visibility grant DEĞİLDİR**.
   Tenant binding (kurum üyeliği) sadece. UI'da "scope atanmadan kullanıcı
   hiçbir veri göremez" kuralı bunu enforce eder.

2. **`organization#admin` scope atama yetkisidir** (kullanıcı VEYA rol
   bazlı). Backend `data_access.scope` INSERT API call'unu admin yapar.

3. **`company|project|warehouse|branch#viewer@user` explicit assignment'tan
   gelir**. Tuple writer source-of-truth: `data_access.scope` tablosu
   (V19, PR #163). INSERT → tuple write; UPDATE revoked_at=now() → tuple
   delete.

4. **`org`/`company` ownership/containment relations'dır**. Auto-grant
   ÜRETMEZ. Yani user `organization:acik#member` ise içerideki company'leri
   otomatik göremez.

5. **Depo hiyerarşisi de explicit-only**. `parent_warehouse` relation
   tutulur (Depo→Lokasyon→Raf navigation için), ama `viewer from
   parent_warehouse` model edilmez. `DEPARTMENT_ID = 3792` (Depo "ADC
   Deposu") atayan, altındaki `3792-01` (Lokasyon "ADC3") otomatik açmaz;
   ayrı atama gerek. (Kullanıcı Faz 21.A kararı: "üçü birden atanabilir
   ama").

6. **Backend enforcement direct OpenFGA SDK** (ADR-0013/C-008). Backend
   servisleri permission-service HTTP üzerinden değil, doğrudan
   `OpenFgaAuthzService` kullanır. permission-service tuple writer + user-
   facing authz hub.

### Object id encoding

DB'de `data_access.scope.scope_ref` canonical JSON form
(`["1001"]`). OpenFGA object id API-safe representation gerektirir;
deterministic encoding:

| DB scope_kind | DB scope_ref | OpenFGA object id |
|---|---|---|
| `company` | `["1001"]` | `company:wc-company-1001` |
| `project` | `["1204"]` | `project:wc-project-1204` |
| `depot` | `["3792"]` | `warehouse:wc-department-3792` |
| `branch` | `["7"]` | `branch:wc-branch-7` |

Encoding kuralları:
- prefix: `wc-` (workcube source)
- entity tip: `company`/`project`/`department`/`branch` (lowercase, plural→singular)
- pk: `scope_ref` JSON array'inden ilk element (string olarak); composite pk için `-` ile birleştir.

Mapping deterministic; backend tuple writer bu fonksiyonu paylaşmalı.

### Tuple writer flow

```
1. Admin "Atama" UI üzerinden POST /api/v1/access/scope
2. Backend handler:
   a. data_access.scope INSERT (V19 trigger validate_scope_ref guard)
   b. tuple write: company:wc-company-1001 viewer user:<sub>
3. Backend response: {scope_id, openfga_tuple_id}

Revoke:
1. Admin DELETE /api/v1/access/scope/{id}
2. Backend handler:
   a. data_access.scope UPDATE revoked_at=now() (Codex iter-2 safe re-grant)
   b. tuple delete
```

Outbox pattern preferred (durability); direct write kabul edilebilir
ancak retry + idempotency açık planlanırsa (backend repo iş).

## Consequences

### Pozitif

- UI mandate ("scope atanmadan hiçbir veri göremez") model seviyesinde
  enforce.
- Multi-org tek model değişikliğiyle çözülür; AÇIK kurumu seed'i + yeni
  kurum eklenmesi tuple migration gerektirmez.
- D29 Zanzibar-ready disiplini korunur; permission-service hub
  ADR-0013 sözleşmesi etkilenmez.
- Lineage-locality (ADR-0005): `data_access.scope` ↔
  `workcube_mikrolink.*.source_pk` join tek SQL ile reconcile edilebilir.

### Negatif / dikkat

- 3-seviye depo hiyerarşisi explicit-only olduğu için admin UX baskısı:
  "ADC Deposu seç → tüm 4 lokasyonu otomatik atama" toplu işlem UI'da
  gerekecek (backend ayrı endpoint).
- N tuple per scope INSERT: data_access.scope satır sayısı OpenFGA tuple
  store boyutunu yansıtır. Tuple sync metrics + cache invalidation
  (ADR-0013 AuthzVersionService) altyapısı yeterli.
- `parent_org`/`parent_company`/`parent_branch` ilişkileri ownership için
  yazılır ama viewer auto-grant üretmez. İleride **rol-bazlı** auto-grant
  isteği gelirse ayrı ADR (ADR-0009?) ile tartışılır.

### Rollout etkisi

- Backend repo (platform-ssot veya yeni platform-web) PR:
  - `openfga-authorization-model.fga`'da `organization` + `depot` ekle.
  - permission-service tuple writer.
  - REST API.
- k8s-gitops repo:
  - Bu ADR (THIS PR).
  - `docs/openfga-multi-org-rollout.md` runbook.
  - `bootstrap/local-fixtures/openfga/tuples.json` aktif tuple **backend
    model merge edildikten sonra** ayrı PR'da güncellenir (Codex
    019dc8b4 iter-1: dev-seed.sh tüm tuple'ları tek payload yazıyor;
    backend model hazır olmadan eklemek 400 üretir).
- Frontend (platform-web) PR:
  - Veri Erişimi atama UI.
  - permission-service authz API call'ları.

## Alternatives Considered

### A. organization#member auto-grants viewer

```fga
type company
  define viewer: [user] or member from parent_org
```

**Reddedildi**. UI mandate "scope atanmadan hiçbir veri göremez" ile
çelişir; org member olur olmaz tüm company görünür. Kullanıcı 2026-04-26
("üçü birden atanabilir ama").

### B. Single scope_kind='resource', polymorphic

OpenFGA tek tip `resource` + ayrı kolon ile entity ayrımı.

**Reddedildi**. Tip ayrımı domain semantiğini kaybeder; query/check'lerde
filter karmaşıklığı + UI listing harder.

### C. Hiyerarşik auto-grant (parent_depot transitive)

```fga
type depot
  define viewer: [user] or viewer from parent_depot
```

**Reddedildi (bu fazda)**. Kullanıcı 2026-04-26: "üçü birden atanabilir
ama" — kademeli grant ürün kararı değil. İleride ürün kararı değişirse
ayrı ADR (ADR-0009?) ile değerlendirilir.

## Doğrulama (Faz 21.3 acceptance criteria)

- [ ] Backend repo: `openfga-authorization-model.fga` Codex AGREE alınmış
      type definition + permission-service tuple writer entegre.
- [ ] k8s-gitops: bu ADR + `docs/openfga-multi-org-rollout.md` merged
      (PR #166 — bu PR).
- [ ] Backend repo PR sonrası: k8s-gitops fixture extension PR (active
      multi-org tuples + smoke checks).
- [ ] Backend tuple writer integration test: `data_access.scope INSERT
      → OpenFGA tuple write → check pass`.
- [ ] D29 Zanzibar-ready üçüncü seviye disiplini korundu: synthetic
      allow + deny enforce kanıtlı (yeni tipler için negatif testler).

## References

- Codex thread `019dc8b4` iter-1/2/3 (Faz 21.A + 21.1 + 21.3)
- `decisions/topics/zanzibar-openfga.v1.json` (D-001..D-008 + C-008 final)
- `bootstrap/local-fixtures/openfga/tuples.json` (current dev fixture)
- `kustomize/base/apps/openfga/` (StatefulSet + migrate-job + ESO)
- `kustomize/base/apps/permission-service/` (Zanzibar PEP/hub)
- `tests/k6/zanzibar-load.js` (load test baseline)
