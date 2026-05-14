# Session 53 Handoff — R16 Close-out Discipline Gap (Systemic) + 4 Implementation Options OPEN

> Format: D28 5-alan + sıradaki agent action list
> **Önceki**: [session-handoff-2026-05-14-session-52-adim-11-4-open.md](session-handoff-2026-05-14-session-52-adim-11-4-open.md)
> **Plan dokümanı**: [docs/plan-reporting-refactor-2026-05-14.md](plan-reporting-refactor-2026-05-14.md)
> **Codex ana thread**: `019e258f-1d09-72f1-8385-245eedde08f6` — **EXPIRED** ("Session not found"); yeni thread `mcp__codex__codex` ile başlatılacak

---

## 1. Bağlam (bu oturumda ne yapıldı)

Session 53, plan §7 Adım 11.4 sub-PR follow-up + **kullanıcı browser smoke discovery** üzerine **sistemik close-out discipline gap** teşhisi. İki çıkış:

**A — Sub-PR #194 IMPLEMENTATION DONE (Codex review pending)**:
- `feat/adim-11-4-route-level-tests` branch
- @WebMvcTest slice yaklaşımı başarısız (WorkcubeReportController `@ConditionalOnBean(workcubeMssqlDataSource)` slice'ta resolve edilmedi)
- Pivot: `WorkcubeQueryExceptionHandlerTest` direct handler unit test (2 spec: security_violation 403 + cross-tenant 403 body)
- Sub-PR #194 push edildi; Codex thread expired olduğu için review submission yeniden gerek

**B — Browser smoke ile R15+R16 keşfi (kullanıcı initiated)**:
- Kullanıcı raporu: `https://testai.acik.com/admin/reports` sidebar onlarca rapor gösteriyor ama gövdede 3 tane görünüyor (FINANCE_REPORTS, HR_REPORTS, SALES_REPORTS muavin'de 20+9+2 entry var ama UI filter)
- API verify: backend 31 rapor + 12 dashboard döndü; correct
- FE filter chain: `ReportingHub.tsx:99` — `if (isSuperAdmin()) return items; return items.filter(item => !item.reportGroup || canViewReport(item.reportGroup));`
- Root cause: kullanıcının `permissions[]` array'inde FINANCE_REPORTS/HR_REPORTS/SALES_REPORTS yok → silent filter
- Daha derin sebep: **OpenFGA `model.fga` dosyasında `type report_group` tanımı yok** (Faz 2 Program 1c close-out gap)
- Daha derin sebep: **RC-009 ActionScopeValid rule STUB** (Faz 2 Program 1c'den beri implement edilmedi); RC-008 sadece schemaResolver için pattern var, registry değil
- En derin sebep: **R16 Close-out Discipline Gap** — sistemik kök; her FAZ'da deliverable işaretlendi ama deferred sub-item'lar registry'de silent kalıyor

**Discussion artifact**: 4 implementation option kullanıcının seçimine sunuldu (impl başlatılmadı; user explicit choice bekliyor).

## 2. İddia (bu oturumda MERGED PR'lar + AÇIK PR'lar)

### Backend MERGED — 0 PR (bu session impl yapıldı, sub-PR push)

### Backend OPEN — 2 PR

| Plan Adım | PR | Status | Codex iter |
|---|---:|---|---|
| Adım 11.4 sub-PR — WorkcubeQueryExceptionHandler 403 body test | [#194](https://github.com/Halildeu/platform-backend/pull/194) | ⏳ Push edildi; Codex iter-36 review gerek (yeni thread) | yeni |
| Adım 11.4 — Interim gate REMOVE + full authz pipeline | [#193](https://github.com/Halildeu/platform-backend/pull/193) | ⏳ Session 52'den devir; iter-35 REVISE-2 partial absorb; sub-PR #194 merge sonrası iter-37 final AGREE bekleniyor | iter-33/34/35 + 36/37 pending |

### Browser smoke discovery (kayıt; impl yok)

- 24 rapor silent filter (20 Finans + 9 İK + 2 Satış reportGroup)
- Kanıt: ReportingHub.tsx:99 filter chain + user permissions[] array (FINANCE_REPORTS/HR_REPORTS/SALES_REPORTS yok) + OpenFGA model.fga (type report_group yok)

## 3. İspatlar

### Sub-PR #194 build kanıtı

```bash
cd platform-backend && git checkout feat/adim-11-4-route-level-tests
./mvnw -pl report-service test -Djacoco.skip=true -Dtest=WorkcubeQueryExceptionHandlerTest
# Tests run: 2, Failures: 0, Errors: 0, Skipped: 0
# BUILD SUCCESS
```

### Browser API kanıtı (kullanıcı session screen)

- `GET /api/v1/reports/catalog` → 31 entry returned (reportGroup field present on 31 entries: FINANCE_REPORTS=20, HR_REPORTS=9, SALES_REPORTS=2)
- `GET /api/v1/authz/me` → `permissions: [...]` array eksik: FINANCE_REPORTS yok, HR_REPORTS yok, SALES_REPORTS yok
- FE filter (ReportingHub.tsx:99): `!item.reportGroup || canViewReport(item.reportGroup)` → 24 entry filter

### OpenFGA model audit kanıtı

`openfga/model.fga` types:
- `user`, `organization`, `company`, `project`, `warehouse`, `branch`, `module`, `action`, `report`
- **MISSING**: `report_group`

Faz 2 Program 1c spec'inde "reportGroup-based tuple authorization" yazılı ama:
- Flyway seed dosyası yok (tuple seed eksik)
- OpenFGA model type yok
- Reverse permission resolver tarafında reportGroup→permission mapping yok

### RC-009 STUB kanıtı

`report-service/src/main/java/com/example/report/contract/rules/RC009ActionScopeValid.java`:

```java
public List<ContractViolation> validate(ReportDefinition def) {
    // 1a stub: actions field henüz ReportDefinition'da yok.
    // 1c'de actions parse + bu rule wire edilir.
    return List.of();
}
```

→ STUB Phase 2 Program 1c kapanışında implement edilmedi; her PR'da yeşil tick veriyor ama davranış 0.

### R16 — Sistemik kök sebep teşhisi (7-nokta)

1. **Close-out checklist yok**: her FAZ "deliverable işaretlendi" ama deferred sub-item'lar (RC-009 stub, OpenFGA type missing, Flyway seed missing) registry'de kayıtsız
2. **Stub-detection eksik**: RC-009 gibi `return List.of()` stub'lar CI'da yakalanmıyor (lint/contract validator gate yok)
3. **OpenFGA model drift**: spec'te bahsedilen `type report_group` model'e eklenmedi; `fga test` framework introduce edilmemiş
4. **Reverse mapping yok**: ReportDefinition.reportGroup → user permission silsilesi tek-yönlü (forward); permission tarafı reportGroup'u tanımıyor
5. **PR template close-out section yok**: "Sub-deliverables fully implemented?" check yok
6. **Drift gate axis yanlış**: mevcut drift gate'ler image digest / kustomize render üzerinde; authz contract drift gate yok
7. **Cross-AI review sistemi planı doğrular ama close-out'u doğrulamaz**: Codex AGREE = plan tutarlı; impl'in close-out'unu Codex denetlemiyor

### Industry pattern audit (kullanıcı soru: sektörel uyumlu çözüm)

| Pattern | Uyum | Notlar |
|---|---|---|
| **OpenFGA `fga test` framework** | ✅ Yüksek (zaten OpenFGA kullanıyoruz) | Model + tuple + assertion deklaratif; CI'da `fga test --model model.fga` |
| **OPA Conftest** | 🟡 Orta (OPA değil OpenFGA stack'imiz) | Rego policy authz değil contract validation için kullanışlı |
| **ArchUnit** | 🟡 Orta (mevcut RC chain pattern'ine yakın) | Java specific; class-level constraint enforcement |
| **Cerbos / Authzed (SpiceDB)** | 🔴 Düşük (OpenFGA replace gerek) | Stack değişimi |

**Önerilen**: OpenFGA fga test (en uyumlu; mevcut OpenFGA model'i extend) + RC-012 generic AuthzReferenceRegistry (mevcut RC pattern'i extend).

## 4. İspatlamaz (pending acceptance / kullanıcı kararı bekliyor)

### 4 implementation option — kullanıcı seçimi bekleniyor

Kullanıcının son sorusu "o zaman nedne yakalayamıyoruz" sonrası 4 option sunuldu, henüz seçim yok:

| # | Option | Effort | Etki |
|---|---|---|---|
| 1 | **PR template + close-out checklist** | 0.5-1 saat | Hızlı, immediate effect; süreçsel; eksik impl'ı tespit eder |
| 2 | **RC-012 generic AuthzReferenceRegistry** | 1-2 gün | Orta vadeli; mevcut RC pattern extend; ReportDefinition.reportGroup → registry doğrulama |
| 3 | **`fga test` framework introduce** | 1 gün | Kalıcı çözüm; OpenFGA native; model + assertion + CI gate |
| 4 | **Hepsi tek epic** (1-2 günlük sub-PR seti) | 2 gün | Kompozit; close-out checklist + RC-012 + fga test + ADR-0017 + Flyway tuple seed |

### PR #193 + sub-PR #194 — Codex review chain açık

**Sub-PR #194** (WorkcubeQueryExceptionHandlerTest):
- Push edildi; CI yeşil; Codex thread expired → yeni thread'de iter-36 review
- Submission template: `WorkcubeQueryExceptionHandler` 2 spec, security_violation 403 body + cross-tenant body

**PR #193** (Adım 11.4 interim gate REMOVE):
- Session 52 partial absorb (Codex iter-35 REVISE-2; 711/711 PASS)
- Sub-PR #194 merge sonrası iter-37 (post-impl final) AGREE + REST merge → Adım 11.4 finalize

### Adım 11.5 prod cutover

Bekleniyor: PR #193 merge + Faz 16.1 annex 2A SEAL (kullanıcı operator action).

### Önceki sessionlardan devam

- **Adım 1.5 acceptance 3-persona smoke** (operator action)
- **Adım 13 — Faz 16.1 annex 2A SEAL** (operator action)
- **R13** — DashboardQueryEngine chart workcube schema column mismatch (pre-existing; raporlar listesi etkilemiyor; chart render fail)
- **R14** — Wiring test production semantics gap (PR #190 hot fix ile çözüldü; pattern lesson learned)
- **R15** — FINANCE_REPORTS/HR_REPORTS/SALES_REPORTS authz registry mismatch (bu session keşfedildi; OpenFGA type + Flyway tuple seed eksik)
- **R16** — Close-out discipline gap (sistemik; bu session teşhis edildi)

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### P0 — Yeni session ilk turu (kullanıcı seçimine göre dallanır)

**Eğer Option 1 (PR template + close-out checklist)**:
1. `.github/PULL_REQUEST_TEMPLATE.md` close-out section ekle:
   - "Sub-deliverables fully implemented (no stub returns)?"
   - "OpenFGA model/tuple seed required? If yes, linked PR: ___"
   - "ReportDefinition.reportGroup / permission registry sync check?"
2. ContractValidator stub-detector ekle (RC-009 gibi `return List.of()` empty body lint)
3. Sub-PR open + cross-AI review (yeni Codex thread)

**Eğer Option 2 (RC-012 generic AuthzReferenceRegistry)**:
1. `report-service/src/main/java/com/example/report/contract/rules/RC012AuthzReferenceRegistry.java` create
2. `AuthzReferenceRegistry` interface + reportGroup/module/action implementation (WARN-first)
3. RC chain'e wire (12. rule)
4. Test: missing reportGroup → WARN log (FAIL not — backward compat)
5. ADR-0017 Contract-Registry Cross-Check Pattern doc

**Eğer Option 3 (`fga test` framework)**:
1. `openfga/model.fga` extend: `type report_group` + relation tanımları
2. `openfga/tests/reportgroup_authz.fga.yaml` test cases
3. CI workflow: `fga test --model openfga/model.fga --tests openfga/tests/`
4. Flyway migration: tuple seed (FINANCE_REPORTS, HR_REPORTS, SALES_REPORTS user assignment)
5. ADR-0018 OpenFGA Test Framework

**Eğer Option 4 (Hepsi tek epic)**:
- 4-5 sub-PR sequence: close-out template + RC-012 + fga test + Flyway seed + ADR docs
- 1-2 gün effort; tek epic branch (`feat/r16-closeout-discipline-epic`)
- Her sub-PR cross-AI review (yeni Codex thread'ler)

### P0-1 — Adım 11.4 finalize (paralel)

1. **Sub-PR #194 Codex iter-36 submission** (yeni thread; expired thread değil)
2. AGREE sonrası sub-PR REST merge
3. **PR #193 Codex iter-37** (post-impl final) AGREE + PR #193 REST merge → Adım 11.4 finalize

### P0-2 — Adım 11.5 plan-time

Faz 16.1 annex 2A SEAL kontrolü; pre-SEAL pilot exception veya SEAL bekle.

### P1 — Adım 11.5 sonrası

5. **Adım 12 etl-worker** (3-5 gün; Python SchemaServiceClient + named allowlist)
6. **R13 spawn task**: DashboardQueryEngine chart workcube schema column mismatch fix
7. **R15 follow-up**: OpenFGA type report_group + Flyway tuple seed (R16 Option 3 ile birlikte)

### P2 — Paralel / Boşlukta

8. **Adım 5 PR-2 follow-up**: Controller NARROWED_AUTHZ_ATTRIBUTE consumption (opsiyonel)
9. **Adım 14 FE kozmetik** (paralel)

### Yeni Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-backend
git fetch origin
git checkout feat/adim-11-4-route-level-tests   # PR #194 branch (sub-PR review için)

# Kullanıcıya 4 option sun:
# 1. PR template + close-out checklist (hızlı)
# 2. RC-012 generic AuthzReferenceRegistry (orta vadeli)
# 3. fga test framework (kalıcı OpenFGA native)
# 4. Hepsi tek epic (1-2 gün)
#
# Kullanıcı seçimi gelene kadar:
# - Sub-PR #194 Codex iter-36 yeni thread'de submit et (paralel)
# - PR #193 iter-37 (post-impl) bekle
```

### Codex thread devamı

Önceki thread `019e258f` EXPIRED. **Yeni Codex thread** ile başlanacak:

```
mcp__codex__codex
  sandbox: read-only
  prompt: "Adım 11.4 sub-PR #194 (WorkcubeQueryExceptionHandlerTest) review. Önceki thread 019e258f iter-35 REVISE-2 → sub-PR pattern @WebMvcTest yerine direct handler unit test. 2 spec: workcube_security_violation 403 body + cross-tenant 403 body. PR diff: <link>"
```

---

## 6. Kapanış Notu — Session 53 İstatistikleri

| Metrik | Değer |
|---|---:|
| MERGED PR | 0 (bu session yapıldı: sub-PR push; merge sonraki session) |
| OPEN PR | 2 (#193 + #194) |
| Codex iter cycle | 0 (önceki thread expired; yeni thread sonraki session) |
| Yeni unit test | 2 (WorkcubeQueryExceptionHandlerTest) |
| **Sistemik teşhis** | **R15 + R16 (close-out discipline gap)** |
| **Implementation options sunuldu** | **4 (kullanıcı seçimi bekliyor)** |
| Browser smoke kanıtı | API 31 rapor + FE filter 24 silent exclude (ReportingHub.tsx:99) |
| Industry pattern audit | 4 pattern (OpenFGA fga test = en uyumlu) |
| Plan ilerleme % (effort bazında) | **~94%** (11.4 PR open + R16 design open + 11.5 + 12 + 13 + 14 kaldı) |
| Admin bypass kullanımı | 0 |
| Cross-AI Peer Review HARD RULE ihlal | 0 |
| Production outage detected + resolved | 0 (bu session) |

**Kritik bulgu**: Sistemin "deliverable bitti" işaretleme disiplini yetersiz; stub-detection + cross-registry validation + OpenFGA test framework eksik. R16 next session epic candidate.

**Codex thread `019e258f` EXPIRED — yeni session yeni thread ile başlar (sub-PR #194 review + R16 design seçimi).**

---

## 7. Ek — Code References (sıradaki agent için)

### FE filter chain (24 rapor silent exclude root)

`apps/mfe-reporting/src/app/reporting/ReportingHub.tsx:99`:
```tsx
if (isSuperAdmin()) return items;
return items.filter((item) => !item.reportGroup || canViewReport(item.reportGroup));
```

`apps/mfe-reporting/src/app/reporting/useCatalog.ts` — 4 kaynak merge: staticItems + dynamicReports + dashboards + extraItems

### RC pattern (RC-008 reference + RC-009 stub)

`report-service/src/main/java/com/example/report/contract/rules/RC008SchemaResolverRegistered.java`:
```java
private static final Set<String> REGISTERED_RESOLVERS = Set.of(
    "workcube-year-company", "workcube-current-company", "none"
);
```

`report-service/src/main/java/com/example/report/contract/rules/RC009ActionScopeValid.java`:
```java
public List<ContractViolation> validate(ReportDefinition def) {
    // 1a stub: actions field henüz ReportDefinition'da yok.
    return List.of();
}
```

### OpenFGA model gap

`openfga/model.fga` — mevcut types: user, organization, company, project, warehouse, branch, module, action, report
**MISSING**: `type report_group` (Phase 2 Program 1c spec'te yazılı; model'e eklenmedi)

### ReportDefinition reportGroup usage

Report JSON files (örnek):
- `fin-cari-hareketler.json` → reportGroup: "FINANCE_REPORTS" (20 entry)
- HR_REPORTS reportGroup (9 entry)
- SALES_REPORTS reportGroup (2 entry)

### Auth/permission resolver

`report-service/src/main/java/com/example/report/authz/PermissionResolver.java` — `getAuthzMe(jwt)` returns AuthzMeResponse with `permissions[]`; reportGroup tarafı uniform değil.

---

**Karar bekleniyor**: Yeni session ilk turu — R16 4 option seçimi + sub-PR #194 Codex iter-36 yeni thread'de submit.
