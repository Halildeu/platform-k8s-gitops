# Faz 21.A — Depolar Kaynak Tablo Kararı

> **Status**: DECIDED 2026-04-26
> **Karar verici**: Kullanıcı + Codex thread `019dc8b4` iter-1/2/3, kullanıcı UI ekran kanıtı (Workcube `w3.acik.com/index.cfm` "Depo ve Alan Planlama → Depolama Alanları").
> **İlgili PR'lar**: PR #163 (V19 data_access seed), bu doc, sonraki Faz 21.1 manifest enrichment.

## Sonuç (TL;DR)

| Soru | Cevap |
|---|---|
| UI'daki "Depolar" sekmesinin kaynak tablosu | **`DEPARTMENT`** (43 kolon) |
| Lookup tablosu (Tür enum: Depo / Lokasyon / Raf) | **`SETUP_DEPARTMENT_TYPE`** (9 kolon) |
| Idempotency key | `DEPARTMENT_ID` (int IDENTITY PK) |
| Hiyerarşi | Self-referencing aynı tablo, `HIERARCHY_DEP_ID` parent FK + `LEVEL_NO` derinlik |
| `scope_kind` | Tek `'depot'` — 3 seviye (Depo/Lokasyon/Raf) ayrı ayrı atanabilir; **üst seviye alt seviyeyi otomatik açmaz** |
| `data_access.scope_kind_source_table_consistent` CHECK güncellemesi | `depot → DEPARTMENT` (V20 ALTER) |

## Saptama yöntemi

UI canlı kanıtı (`w3.acik.com/index.cfm` "Depo ve Alan Planlama → Depolama Alanları"):
- Sütunlar: Kod, **Tür** (Depo/Lokasyon/Raf), Depo/Lokasyon/Raf adı, Şube, Açıklama, Boyut, Hacim, Yönetici, Durum.
- Kayıt örnekleri:
  - 3667 — Depo — "Çanakkale Hilton Deposu" — Şube: "Serban İnşaat Çanakkale Hilton"
  - 3667-1 — Lokasyon — "Çanakkale Hilton Serban Lokasyonu"
  - 3792 — Depo — "ADC Deposu" — Şube: "Serban İnşaat Ankara Turkcell" — Yönetici: "Bahri Orhan"
  - 3792-01 / 3792-02 / 3792-03 / 3792-04 — Lokasyon (parent: 3792)

Snapshot kolon eşleştirmesi (`docs/migration/workcube-schema.json`):

| UI sütunu | `STOCKS_LOCATION` (26 kol) | `DEPARTMENT` (43 kol) | Saptama |
|---|---|---|---|
| Ad ("ADC Deposu") | yok (DEPARTMENT_LOCATION = adres) | **`DEPARTMENT_HEAD`** (200) | DEPARTMENT |
| Tür (Depo/Lokasyon/Raf) | yok | **`DEPARTMENT_TYPE`** (int) → SETUP_DEPARTMENT_TYPE lookup | DEPARTMENT |
| Şube (FK) | yok | **`BRANCH_ID`** → `BRANCH.BRANCH_ID` | DEPARTMENT |
| Açıklama (adres) | DEPARTMENT_LOCATION (1000) | **`DEPARTMENT_ADDRESS`** (1000) + `DEPARTMENT_DETAIL` (300) | DEPARTMENT |
| Yönetici (Bahri Orhan vs.) | yok | **`ADMIN1_POSITION_CODE`** + `ADMIN2_POSITION_CODE` → POSITION → EMPLOYEE join | DEPARTMENT |
| Durum (Aktif) | STATUS bit | **`DEPARTMENT_STATUS`** bit | DEPARTMENT |
| Boyut/Hacim | WIDTH/HEIGHT/DEPTH | **WIDTH/HEIGHT/DEPTH** + X/Y/Z_COORDINATE | DEPARTMENT (aynı kolonlar) |
| Kod (3792, 3792-01) | yok | **`HIERARCHY_DEP_ID`** + `HIERARCHY` (path) + `LEVEL_NO` | DEPARTMENT (3-seviye self-referencing) |

**STOCKS_LOCATION ne yapıyor?** Yine kullanılan ama farklı görev: 26 kolonlu **ürün-içi konum tablosu**. `LOCATION_TYPE`, `IS_COST_ACTION`, `IS_END_OF_SERIES`, `IS_SCRAP`, `IS_RECYCLE_LOCATION`, `PRESSURE`, `TEMPERATURE`, X/Y/Z_COORDINATE. FK: `STOCKS_LOCATION.DEPARTMENT_ID → DEPARTMENT`. Yani **STOCKS_LOCATION = depo içindeki rafa ürün konumu/koşulları atama**, UI'daki "Depolar" listesinin değil.

## DEPARTMENT — Workcube'da multi-purpose

`DEPARTMENT` tablosu Workcube'da çift amaçlı:
1. **İK/Org departmanları** (genel "departman" semantiği — `IS_ORGANIZATION` flag).
2. **Fiziksel lokasyonlar** (Depo/Lokasyon/Raf — `IS_STORE > 0` veya `DEPARTMENT_TYPE` belirli enum).

Faz 21'de `'depot'` scope listesi DEPARTMENT'ın **sadece fiziksel lokasyon satırları**. Filtre kuralı kesinleşene kadar manifest seviyesinde 2 yaklaşım var:

- **A) PG-side filter**: tüm DEPARTMENT satırlarını ETL'le, `data_access` listing query'si `WHERE department_type IN (...) OR is_store > 0` filter uygular.
- **B) ETL filter**: extract sırasında SQL WHERE clause ile sadece fiziksel lokasyonlar gelir.

Önerilen **A**. Sebepler:
- DEPARTMENT'in tüm satırları başka raporlar için de gerekebilir (HR raporları İK departmanını kullanır).
- Filter PG-side daha esnek; SETUP_DEPARTMENT_TYPE değişirse SQL düzeltmesi yetebilir, ETL rerun gerekmez.
- ETL idempotent + content_hash ile zaten "tüm satırlar" minimum kost.

## SETUP_DEPARTMENT_TYPE lookup — Faz 21.4'e defer

Workcube `DEPARTMENT.DEPARTMENT_TYPE` (int) → `SETUP_DEPARTMENT_TYPE.DEPARTMENT_TYPE_ID` lookup. Lookup içindeki 200-char `DEPARTMENT_TYPE` string ile UI'daki "Depo / Lokasyon / Raf" görünür.

**Faz 21.1 kapsam ayrımı** (Codex 019dc8b4 iter-1 PR #165 absorb):
- Scope assignment için lookup **gerekli değil**: `data_access.scope` `DEPARTMENT.source_pk` üzerinden lineage existence guard kullanır; tür adı (`Depo / Lokasyon / Raf`) sadece görüntüleme amaçlı.
- Listing UI'da tür adını gösterme **Faz 21.4 backend repo işi**: read-model olarak ya backend ETL'le ya da JOIN ile çözülür.
- Bu nedenle Faz 21.1 manifest'e `PRO_PROJECTS + DEPARTMENT` eklendi; `SETUP_DEPARTMENT_TYPE`/`SETUP_DEPARTMENT_NAME`/`SETUP_DEPARTMENT_CAT` **dahil edilmedi**.

İleride Faz 21.4'te lookup gerekirse iki yol:
1. ETL ile workcube_mikrolink şemasına `setup_department_type` eklenmesi (V21 generator extension).
2. Backend (platform-web) tarafında MSSQL doğrudan lookup veya cache.

Karar Faz 21.4'te.

## scope_kind ve V19 etkisi

V19 (PR #163, commit `f311c52`) `data_access.scope` tablosunda `scope_kind_source_table_consistent` CHECK constraint'i V20 (Faz 21.1, PR #165) ile genişletildi:
- V19 başlangıç: `(scope_kind = 'depot' AND scope_source_table = 'TBD_DEPOT_TABLE')` (fail-closed placeholder).
- V20 sonrası: `(scope_kind = 'depot' AND scope_source_table = 'DEPARTMENT')`.

V20 ALTER migration özeti:
```sql
ALTER TABLE data_access.scope DROP CONSTRAINT scope_kind_source_table_consistent;
ALTER TABLE data_access.scope ADD CONSTRAINT scope_kind_source_table_consistent CHECK (
  (scope_kind = 'company' AND scope_source_table = 'COMPANY')      OR
  (scope_kind = 'project' AND scope_source_table = 'PRO_PROJECTS') OR
  (scope_kind = 'branch'  AND scope_source_table = 'BRANCH')       OR
  (scope_kind = 'depot'   AND scope_source_table = 'DEPARTMENT')
);
```

Plus `data_access.validate_scope_ref()` function `'depot' / 'DEPARTMENT'` branch'i kazanır:
```sql
ELSIF p_kind = 'depot' AND p_source_table = 'DEPARTMENT' THEN
    SELECT count(*) INTO v_count
    FROM workcube_mikrolink.department
    WHERE source_pk = p_ref AND source_schema = 'workcube_mikrolink';
```

Bu V20 migration **Faz 21.1a manifest+contract PR'ı**nda gelir (PR #165). DEPARTMENT ETL koşumu ve reconcile evidence **Faz 21.1b** ayrı user-gated PR'ı (agent sandbox shared PG erişemiyor).

## 3-seviye atama semantiği

Kullanıcı kararı (2026-04-26): "üçü birden atanabilir ama depo üst seviye, deponun altında lokasyon, lokasyonun altında raf var".

Yorum:
- Veri Erişimi UI'da operatör user'a `DEPARTMENT_ID = 3792` (Depo "ADC Deposu") atayabilir → user sadece o satırı görür, alt-Lokasyon (3792-01..04) **otomatik açılmaz**.
- Operatör ayrıca user'a `DEPARTMENT_ID = 3792-01` (Lokasyon "ADC3 Lokasyonu") atayabilir → user sadece o lokasyonu görür.
- **Kademeli/transitive grant Faz 21.3 OpenFGA modelinde de yok** (Codex iter-2 onayı: parent_org/parent_dep auto-grant üretmez; explicit assignment).

Eğer ileride "alt seviyelerin de açılması" ürün kararı olursa:
- Ya UI tarafında "ADC Deposu seç → tüm lokasyonları otomatik atama" toplu işlem.
- Ya OpenFGA'da `define viewer: [user] or viewer from parent_dep` + DEPARTMENT.HIERARCHY_DEP_ID → parent_dep tuple'ları yazılır.

Bu fazda **explicit-only**. Karar değişirse ayrı ADR.

## Faz 21.1 manifest enrichment için yön

Tables.yaml manifest'e eklenecek **4 entity** (`SETUP_DEPARTMENT_TYPE` Faz 21.4'e defer):

| Manifest entry | Tablo | Kolon adedi (full) | Min kolon (Veri Erişimi listing için) |
|---|---|---|---|
| (var) COMPANY | `COMPANY` | 113 | id, name, status |
| (var) BRANCH | `BRANCH` | 107 | id, name, status, company_id |
| **YENİ** PRO_PROJECTS | `PRO_PROJECTS` | 75 | id, number, status, head, emp_id, agreement_no |
| **YENİ** DEPARTMENT | `DEPARTMENT` | 43 | id, head, type, status, branch_id, our_company_id, hierarchy_dep_id, hierarchy, level_no, dept_cat, address, admin1/2_position_code |
| ~~SETUP_DEPARTMENT_TYPE~~ | (Faz 21.4'e defer; scope assignment için gerekli değil) | — | — |
| ~~SETUP_DEPARTMENT_NAME~~ | (Faz 21.4'e defer) | — | — |

**Faz 21.1a PR'ı (PR #165)**:
1. `tables.yaml` manifest enrichment.
2. V20 migration: scope CHECK + validate_scope_ref function genişletme.
3. `data_access.scope` üzerinde gerçek `'depot'` scope ataması test (insert + trigger doğrulama; canlı dev-pg evidence).

**Faz 21.1b PR'ı (next, user-gated)**:
1. ETL koşum (PR #162 runbook ile, kullanıcı onaylı).
2. Reconcile artifact 4 entity ile: COMPANY, BRANCH, PRO_PROJECTS, DEPARTMENT.

## Kararı kapatan referanslar

- Snapshot: `docs/migration/workcube-schema.json` (3.4 MB, 1509 tablo, 1774 ilişki)
- DEPARTMENT FK ilişkileri (snapshot'tan):
  - `DEPARTMENT.BRANCH_ID → BRANCH.BRANCH_ID` (conf 0.97)
  - `DEPARTMENT.OUR_COMPANY_ID → OUR_COMPANY.OUR_COMPANY_ID` (conf 0.97)
  - `STOCKS_LOCATION.DEPARTMENT_ID → DEPARTMENT.DEPARTMENT_ID` (conf 0.97) — depo-içi ürün konumu
- Codex thread `019dc8b4` iter-1/2/3 (PR #163 plan-time + post-impl review)
- Kullanıcı UI kanıtı (Workcube `w3.acik.com/index.cfm`, "Depo ve Alan Planlama → Depolama Alanları")
- Kullanıcı netleştirmesi (2026-04-26): "tür depo olanlar depo, tür lokasyon olan lokasyon... üçü birden atanabilir ama depo üst seviye"
