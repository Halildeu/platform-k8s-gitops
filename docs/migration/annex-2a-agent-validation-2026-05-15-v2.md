# Annex 2A — Agent Schema Validation v2 (2026-05-15)

> **v1 update.** Kullanıcı keşfetti: `schema-service` zaten **319+ schema** taraması yapıyor (`workcube_mikrolink` canonical + 43 tenant-only schema + 276 year-tenant schema). Yani parametric snapshot **agent için canlı erişilebilir**, ayrı bir operator crawl scripti gerek değil.
>
> v1 verdict'i (8/8 needs_review) iptal — yeni v2 sonucu: **8/8 PASS** (schema cross-check kapsamı tamamlandı).
>
> SEAL flip **yine YAPILMAMIŞ**. Domain karar gerektiren imzalar (float `semantic_class`, timezone, `migration_action_default`) hâlâ pending.

---

## 1. Yeni keşif: schema-service `/api/v1/schema/schemas` + `/snapshot?schema=<name>`

`SchemaController.java` zaten 13 endpoint expose ediyor; ikisi parametric crawl için kritik:

| Endpoint | Davranış |
|---|---|
| `GET /api/v1/schema/schemas` | Tüm aktif schema'ları listeler (`workcube_mikrolink%` LIKE + `dbo`) — 319+ schema |
| `GET /api/v1/schema/snapshot?schema=<name>` | Belirli bir schema'nın full snapshot'ı (tablo + kolon + ilişki + domain) |

Auth: JWT (audience: `account, frontend, schema-service`) veya internal API key (`X-Internal-Api-Key`).

### Schema kategorileri (319+ total)

| Pattern | Adet | Örnek | İçerik |
|---|---|---|---|
| `workcube_mikrolink` | 1 | canonical (1512 tablo) | static cross-tenant master + HR + product |
| `workcube_mikrolink_<id>` | 43 | `_1` (660), `_35` (607), `_43` (607) | tenant başına yıllık-bağımsız master |
| `workcube_mikrolink_<year>_<id>` | ~276 | `_2026_1` (222), `_2025_35` (258) | yıl + tenant başına **transactional** |

## 2. 8 sourceQuery cross-check — v2 sonucu

| # | Report | Verdict | Canonical | Year-tenant | Unresolved |
|---|---|---|---|---|---|
| 1 | `fin-cari-islemler` | ✅ pass | 2 | 1 | 0 |
| 2 | `fin-fatura-satirlari` | ✅ pass | 2 | 2 | 0 |
| 3 | `fin-kaynak-eslesme` | ✅ pass | 1 | 2 | 0 |
| 4 | `fin-masraf-detay` | ✅ pass | 2 | 2 | 0 |
| 5 | `fin-muhasebe-detay` | ✅ pass | 8 | 4 | 0 |
| 6 | `fin-stok-fis-detay` | ✅ pass | 1 | 2 | 0 |
| 7 | `fin-tutar-mutabakat` | ✅ pass | 1 | 6 | 0 |
| 8 | `hr-compensation-detay` | ✅ pass | 9 | 0 | 0 |

**Toplam: 8/8 PASS, 0/8 needs_review.**

## 3. Pattern teyidi (canonical + year-tenant)

8 sourceQuery'nin SQL'leri iki schema türünü kullanıyor:

```sql
-- Year-tenant (parametric, runtime'da `workcube_mikrolink_<year>_<tenant_id>` resolve):
FROM [{schema}].[CARI_ACTIONS] CA WITH (NOLOCK)
LEFT JOIN [{schema}].[INVOICE_ROW] IR ...
LEFT JOIN [{schema}].[ACCOUNT_CARD] AC ...

-- Canonical static (hard-coded `workcube_mikrolink`):
LEFT JOIN [workcube_mikrolink].[COMPANY] C ...
LEFT JOIN [workcube_mikrolink].[EMPLOYEES_PUANTAJ_ROWS] epr ...
LEFT JOIN [workcube_mikrolink].[BRANCH] BR ...
```

Year-tenant tabloları (`workcube_mikrolink_2026_1` testinde 12/12 mevcut):

```
ACCOUNT_CARD, ACCOUNT_CARD_ROWS, ACCOUNT_CARD_MONEY, ACCOUNT_PLAN,
BANK_ACTIONS, CARI_ACTIONS,
EXPENSE_ITEM_PLANS, EXPENSE_ITEMS,
INVOICE, INVOICE_ROW,
STOCK_FIS, STOCK_FIS_ROW
```

Canonical tablolar (`workcube_mikrolink` testinde mevcut):

```
COMPANY, PRO_PROJECTS, OUR_COMPANY, BRANCH, DEPARTMENT,
EMPLOYEES, EMPLOYEES_DETAIL, EMPLOYEES_IDENTY, EMPLOYEES_IN_OUT,
EMPLOYEES_PUANTAJ, EMPLOYEES_PUANTAJ_ROWS, EMPLOYEE_POSITIONS,
SETUP_DOCUMENT_TYPE, CONSUMER, MONEY_HISTORY, ACCOUNT_CARD_MONEY
```

## 4. Statik SQL kalite profili (v1 ile aynı, 8/8 uyumlu)

| Property | Tipik Profil |
|---|---|
| `[{schema}].[TABLE]` parametric placeholder | 8/8 ✓ |
| `[workcube_mikrolink].[TABLE]` static placeholder | 8/8 ✓ |
| `WITH (NOLOCK)` hint sayısı | 2–13 per query; production read-only paterni |
| `LEFT JOIN` sayısı | 2–13 per query; cardinality risk yok |
| `INNER JOIN` sayısı | 0 (hr-compensation-detay 4 hariç) |
| `CASE WHEN` / `ISNULL` kullanımı | type-aware default'lar |

## 5. CLAUDE.md drift guard etkisi

CLAUDE.md `Hızlı Bağlam — MSSQL Şema Gezgini` notu:

> Parametric (yıllık) tablolar canonical snapshot'ta YOK; `workcube_mikrolink_<yıl>` schema'larında. 17 parametric tabloyu çekmek için schema-service'in yearly schema crawl'ı gerekiyor (Faz 16.2.P sprint).

Bu not **revize edilmeli**. Faz 16.2.P sprint'i schema-service'in yearly crawl tool'unu deferred tutmuş; ama **endpoint zaten mevcut** (`/api/v1/schema/snapshot?schema=<name>`). Sprint formal olarak deferred ama özellik canlı.

Önerilen update: CLAUDE.md notunda "yearly schema crawl gerekli" yerine "schema-service `/snapshot?schema=<name>` ile her parametric schema canlı çekilebilir; canonical snapshot'tan ayrı"  ifadesi.

## 6. Hâlâ Pending — Domain Decisions (operator imzası)

v2 schema cross-check kapanışı SEAL gate'inin sadece **bir kapısını** açar. Üç kapı daha açık:

### 6.1 Migration action default (DBA + PO)

31 report için `migrate / exclude / keep_workcube` kararı.

**Agent önerisi (yine proposal-only)**:
- Faz 17 Workcube decommission niyetli → tüm 31 → `migrate` default
- İstisna: legacy/deprecated raporlar `exclude`
- Cross-tenant master ref'ler `keep_workcube`

Bu karar DBA + PO içeriği biliyor. Agent canonical alan flip etmez.

### 6.2 Float semantic class (DBA + backend lead double sign-off)

Heuristic gözlem v1'deki gibi geçerli (M1-M12 analytical, *_AMOUNT currency, *_COUNT counter). Ama:

> `unknown_float_class` → SEAL BLOCKER (kontrak `docs/migration/mssql-pg-data-contract.md` §471)
> Workcube admin + backend lead **çift onay** ister.

Agent heuristic önerir, **çift onay olmadan SEAL flip yok**.

### 6.3 Timezone (ERP DBA yazılı onay)

> `docs/migration/mssql-pg-data-contract.md` §493: ERP DBA yazılı onay acceptance criterion.

Agent `Europe/Istanbul` proposal yapar, ERP DBA imzası SEAL gate'inde gerekli.

## 7. Geriye dönük — v1 vs v2

| Soru | v1 (2026-05-15) | v2 (2026-05-15) |
|---|---|---|
| 8 sourceQuery cross-check | ❌ 8/8 needs_review | ✅ 8/8 pass |
| Sebep | parametric schema drift guard (snapshot eksik sanılmıştı) | schema-service `/snapshot?schema=<name>` canlı endpoint kullanıldı |
| Static SQL profile | ✓ uyumlu | ✓ uyumlu |
| Operator chain açık mı? | yes (parametric crawl + 3 imza) | yes (sadece 3 imza — parametric crawl ihtiyacı YOK) |

v1'in operator-loop önerisi **iptal**: kullanıcının manuel parametric crawl koşturma adımına gerek yok, schema-service zaten canlı yapıyor. Operator zinciri **sadece domain decisions**.

## 8. Acceptance ileri adımı

> ⚠️  SEAL flip yine YAPILMAMIŞ. Aşağıdaki acceptance ayrı PR'da olur.

1. DBA — 31 report `migration_action_default` karar matrisi (PO ile birlikte)
2. DBA + backend lead — float semantic class her column sign-off
3. ERP DBA — timezone yazılı onay
4. Three signatures hazır olunca:
   - Annex YAML canonical alanları flip (`status: SEALED`, `seal_state: SEALED`, `manually_validated: true`, `migration_action_default` per report)
   - ADR-0005 §6 amendment merge
   - Adım 11.5 prod cutover unblock (`REPORT_MSSQL_ENABLED=true`)

## 9. CLAUDE.md/PLAN.md güncellemesi (ayrı PR önerisi)

- CLAUDE.md `Hızlı Bağlam — MSSQL Şema Gezgini` parametric crawl notu güncelle
- PLAN.md Faz 16.2.P "schema-service yearly crawl tool" excluded scope satırı: artık dahil — endpoint mevcut

Bu PR scope'unda değil; sonraki bir paket'te.

## Cross-AI

```yaml
implementer_ai: Claude
reviewer_ai: Codex
codex_thread: 019e2c59-1cdb-7ea3-a8e6-bf3fcabc62b2
prior_verdict_iter_2: B-prime (pre-SEAL validation packet, parametric crawl operator-loop)
v2_revision_trigger: kullanıcı schema-service /schemas endpoint'inin zaten 319+ schema'yı taradığını gözlemledi
v2_agent_action: 8/8 cross-check pass (canonical + year-tenant)
v2_seal_status: NOT FLIPPED (domain decisions pending — float, timezone, migration_action)
```
