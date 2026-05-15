# Schema-Service — Detected vs Inferred vs Missing

> **Net truth dokümanı.** Schema-service'in Workcube MSSQL'den **gerçekten ne bilgi çıkardığı**, neyi **çıkarsadığı** (heuristic), neyi **hiç sorgulamadığı** — kaynak koddan (commit referansıyla) kanıtlı.
>
> **Tarih**: 2026-05-15  
> **Kaynak**: `platform-backend/schema-service/src/main/java/com/example/schema/`

---

## TL;DR

| Soru | Cevap |
|---|---|
| **Primary Key** tespit ediliyor mu? | ✅ Evet, gerçek (`sys.indexes WHERE is_primary_key=1`) |
| **Identity column** tespit ediliyor mu? | ✅ Evet, gerçek (`sys.columns.is_identity`) |
| **Nullable / data type / max length** | ✅ Evet, gerçek |
| **Row count** | ✅ Evet, gerçek (`sys.partitions`) |
| **View definitions** | ✅ Evet, gerçek (`sys.sql_modules type='V'`) |
| **Foreign Key (gerçek constraint)** | ❌ Hayır — `sys.foreign_keys` sorgulanmıyor |
| **FK ilişkileri** | ⚠️ Inferred — 5 heuristic teknik, confidence score 0.80-0.92 |
| **Unique constraint** | ❌ Hayır — `sys.indexes WHERE is_unique=1` filter yok |
| **Check constraint** | ❌ Hayır |
| **Default values** | ❌ Hayır |
| **Non-PK indexes** | ❌ Hayır |
| **Stored procedures** | ❌ Hayır (sadece View) |
| **Triggers** | ❌ Hayır |
| **Computed columns** | ❌ Hayır |
| **GRANT/permissions** | ❌ Hayır |

---

## 1. ✅ Gerçek tespit — sys.* tablolarından

### 1.1 Column metadata extraction

**Kaynak**: `SchemaExtractService.java:33-50`

```sql
SELECT t.name AS table_name, c.name AS column_name, ty.name AS data_type,
       c.max_length, c.is_nullable, c.is_identity,
       CASE WHEN pk.column_id IS NOT NULL THEN 1 ELSE 0 END AS is_pk,
       c.column_id AS ordinal
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
JOIN sys.columns c ON c.object_id = t.object_id
JOIN sys.types ty ON c.user_type_id = ty.user_type_id
LEFT JOIN (
    SELECT ic.object_id, ic.column_id
    FROM sys.index_columns ic
    JOIN sys.indexes i ON i.object_id = ic.object_id AND i.index_id = ic.index_id
    WHERE i.is_primary_key = 1
) pk ON pk.object_id = t.object_id AND pk.column_id = c.column_id
WHERE s.name = :schema
ORDER BY t.name, c.column_id
```

**Çıktı modeli** (`ColumnInfo.java`):
```java
public record ColumnInfo(
    String name,
    String dataType,
    int maxLength,
    boolean nullable,
    boolean identity,    // c.is_identity
    boolean pk,           // PK index'inden CASE WHEN
    int ordinal
) {}
```

**Notlar**:
- `boolean pk` field'ı VAR
- `boolean fk` field'ı **YOK**
- `boolean unique` field'ı **YOK**

### 1.2 Row count

**Kaynak**: `SchemaExtractService.java:82-88`

```sql
SELECT t.name, SUM(p.rows) AS row_count
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0, 1)
WHERE s.name = :schema
GROUP BY t.name
```

**index_id IN (0, 1)** → heap (0) + clustered (1). Yaklaşık değer; gerçek COUNT(*) değil ama yeterli.

### 1.3 View definitions

**Kaynak**: `SchemaExtractService.java:101-105`

```sql
SELECT o.name, m.definition
FROM sys.sql_modules m
JOIN sys.objects o ON m.object_id = o.object_id
JOIN sys.schemas s ON o.schema_id = s.schema_id
WHERE o.type = 'V' AND s.name = :schema
```

Sadece **View** (`o.type = 'V'`). Stored procedure (`'P'`), function (`'FN', 'TF', 'IF'`), trigger (`'TR'`) **yok**.

### 1.4 Schema list

**Kaynak**: `SchemaExtractService.java:127-135`

```sql
SELECT s.name AS schema_name, COUNT(t.object_id) AS table_count
FROM sys.schemas s
LEFT JOIN sys.tables t ON s.schema_id = t.schema_id
WHERE s.name LIKE 'workcube_mikrolink%' OR s.name = 'dbo'
GROUP BY s.name
HAVING COUNT(t.object_id) > 0
```

---

## 2. ⚠️ Inferred — heuristic FK discovery

**Kaynak**: `RelationshipDiscoveryService.java`

Workcube **gerçek FK constraint kullanmıyor** (Workcube tipik ERP gibi performans/dev-velocity için uygulama-level FK). Schema-service `sys.foreign_keys` **sorgulamıyor**. Bunun yerine 5 heuristic teknik.

### 2.1 Teknik 1-2: Name match

**Code**: `RelationshipDiscoveryService.java:95-112`

```java
if (!col.name().endsWith("_ID") || col.name().equals("ID")) continue;
String base = col.name().substring(0, col.name().length() - 3);
if (tableNames.contains(base)) {
    rels.add(new Relationship(tableName, col.name(), base, col.name(), 0.85, "name_match_exact"));
} else if (tableNames.contains(base + "S")) {
    rels.add(new Relationship(tableName, col.name(), base + "S", col.name(), 0.80, "name_match_plural"));
}
```

**Confidence**: 0.85 (exact) / 0.80 (plural)

**Örnek**: `BRANCH_ID` → `BRANCH` (varsa) veya `BRANCH_ID` → `BRANCHS` (yoksa "BRANCH")

### 2.2 Teknik 3: Alias map (predefined)

**Code**: `RelationshipDiscoveryService.java:22-46`

40+ alias kombinasyon. Workcube spesifik naming:

```java
"COMP_ID" → "COMPANY",
"CMP_ID" → "COMPANY",
"ACC_COMPANY_ID" → "COMPANY",
"SALES_COMPANY_ID" → "COMPANY",
"TO_COMPANY_ID" → "COMPANY",
"CARRIER_COMPANY_ID" → "COMPANY",
"FUEL_COMPANY_ID" → "COMPANY",
"FROM_CMP_ID" → "COMPANY",
"TO_CMP_ID" → "COMPANY",
"EMP_ID" → "EMPLOYEES",
"ACC_EMPLOYEE_ID" → "EMPLOYEES",
"MANAGER_ID" → "EMPLOYEES",
"SECOND_BOSS_ID" → "EMPLOYEES",
"THIRD_BOSS_ID" → "EMPLOYEES",
"FOURTH_BOSS_ID" → "EMPLOYEES",
"FIFTH_BOSS_ID" → "EMPLOYEES",
"FIRST_BOSS_ID" → "EMPLOYEES",
"DEPT_ID" → "DEPARTMENT",
"ACC_DEPARTMENT_ID" → "DEPARTMENT",
"ACC_BRANCH_ID" → "BRANCH",
"RELATED_BRANCH_ID" → "BRANCH",
"ACC_PROJECT_ID" → "PRO_PROJECTS",
...
```

**Confidence**: 0.90

### 2.3 Teknik 4: Common FK map (standart pattern)

**Code**: `RelationshipDiscoveryService.java:49-63`

25 yaygın FK pattern:

```java
"COMPANY_ID" → "COMPANY",
"EMPLOYEE_ID" → "EMPLOYEES",
"OUR_COMPANY_ID" → "OUR_COMPANY",
"BRANCH_ID" → "BRANCH",
"PROJECT_ID" → "PRO_PROJECTS",
"CONSUMER_ID" → "CONSUMER",
"DEPARTMENT_ID" → "DEPARTMENT",
"PARTNER_ID" → "COMPANY_PARTNER",
"PERIOD_ID" → "SETUP_DUTY_PERIOD",
"EXPENSE_ITEM_ID" → "EXPENSE_ITEMS",
"EXPENSE_CENTER_ID" → "EXPENSE_CENTER",
"PAYMETHOD_ID" → "SETUP_PAYMETHOD",
"COMMETHOD_ID" → "SETUP_COMMETHOD",
"ACTIVITY_TYPE_ID" → "SETUP_ACTIVITY_TYPES",
"TRAINING_ID" → "TRAINING",
"PROCESS_CAT_ID" → "SETUP_PROCESS_CAT",
"PRODUCT_ID" → "PRODUCTS",
"UNIT_ID" → "SETUP_UNIT",
"BRAND_ID" → "SETUP_BRAND",
"MONEY_ID" → "SETUP_MONEY",
...
```

**Confidence**: 0.92 (en yüksek)

### 2.4 Teknik 5: View parsing

**Code**: `RelationshipDiscoveryService.java:142-169`

View tanımlarındaki SQL'i regex ile parse eder:

```java
private static final Pattern JOIN_PATTERN = Pattern.compile(
    "(\\w+)\\.(\\w+)\\s*=\\s*(\\w+)\\.(\\w+)", Pattern.CASE_INSENSITIVE
);
```

`SELECT a.X FROM A JOIN B ON A.X = B.Y` → ilişki çıkar.

**Confidence**: 0.88

**Sınır**: Sadece basit `JOIN ... ON A.X = B.Y` pattern'i. Karmaşık JOIN (subquery, CTE, function call) parse edilmez.

### 2.5 Relationship modeli

**Code**: `Relationship.java`

```java
public record Relationship(
    String fromTable,
    String fromColumn,
    String toTable,
    String toColumn,
    double confidence,      // 0.80 - 0.92
    String source,          // "name_match_exact", "alias_pattern", "common_fk", "view_parse:<view>"
    boolean multiSource     // birden fazla teknikten geldi mi?
) {}
```

Multi-source ilişkiler (örn. hem alias hem common_fk'de bulunmuş) **daha güvenilir**. `multiSource: true` flag'i.

---

## 3. ❌ Eksik — kod sorgulamıyor

### 3.1 Unique constraint / unique index

**MSSQL'de var** (`sys.indexes WHERE is_unique = 1`).

**Schema-service'te yok**. PK extraction'da `is_primary_key = 1` filter; `is_unique` ayrıca alınmıyor.

**Etki**: 
- "Bu kolon unique mi?" cevabı yok
- Business key tespiti elle yapılmalı (örn. `COMPANY_CODE` unique mi?)
- Migration için unique constraint Postgres'te tekrar yaratılmalı

### 3.2 Check constraints

**MSSQL'de var** (`sys.check_constraints`).

**Schema-service'te yok**.

**Etki**: 
- Validation rules görünmez (örn. `AMOUNT >= 0`)
- Migration'da elle çıkartılmalı

### 3.3 Default values

**MSSQL'de var** (`sys.default_constraints`).

**Schema-service'te yok**.

**Etki**: 
- INSERT statement'ında hangi kolonların default değeri var bilinmez
- `RECORD_DATE DEFAULT GETDATE()` gibi pattern'ler kayıp

### 3.4 Non-PK indexes

**MSSQL'de var** (`sys.indexes` PK filter'ı kaldırılınca).

**Schema-service'te yok**.

**Etki**: 
- Performans indeksleri görünmez
- "Bu sorgu yavaş mı?" tahmin zorlaşır

### 3.5 Stored procedures, functions, triggers

**MSSQL'de var** (`sys.sql_modules` type='P', 'FN', 'TF', 'IF', 'TR').

**Schema-service sadece View** alıyor (`type = 'V'`).

**Etki**:
- Business logic stored procedure'larda gizli olabilir, görünmez
- Trigger'lar (örn. audit insert) görünmez
- Function-based computed kolonlar görünmez

### 3.6 Computed columns

**MSSQL'de var** (`sys.computed_columns`).

**Schema-service'te yok**.

**Etki**: Computed alan (örn. `TOTAL AS QUANTITY * UNIT_PRICE`) `ColumnInfo`'da normal kolon gibi görünür ama davranış farklı.

### 3.7 GRANT/permissions

**MSSQL'de var** (`sys.database_permissions`).

**Schema-service'te yok**.

**Etki**: "Bu tabloya kim okuyabilir?" cevabı yok. Workcube auth tarafından zaten user-level yapıldığı için kritik değil.

---

## 4. 🎯 Decision tree — neye güveneceğim?

```
İhtiyaç: "Bu kolon X tablosuna FK mi?"
  │
  ├─ snapshot.relationships[] içinde mi?
  │    ├─ Var → confidence 0.80-0.92 (inferred)
  │    │       ├─ 0.92 (common_fk) → güvenilir, doğrulama opsiyonel
  │    │       ├─ 0.90 (alias) → güvenilir
  │    │       ├─ 0.88 (view_parse) → orta, view SQL'i kontrol et
  │    │       └─ 0.80-0.85 (name_match) → düşük, manuel doğrula
  │    │
  │    └─ multiSource: true → çok güvenilir (multiple technique)
  │
  └─ Yok → real FK constraint var mı?
       ↓ Workcube'da YOK (sys.foreign_keys boş)
       ↓ Schema-service de sorgulamıyor
       → Heuristic'in dışında bir FK var, manuel keşfet

İhtiyaç: "Bu kolon unique mi?"
  → Schema-service cevap veremez
  → MSSQL doğrudan sorgu: SELECT * FROM sys.indexes WHERE object_id = OBJECT_ID('X') AND is_unique = 1

İhtiyaç: "Bu tablonun trigger'ı var mı?"
  → Schema-service cevap veremez
  → MSSQL doğrudan sorgu: SELECT * FROM sys.triggers WHERE parent_id = OBJECT_ID('X')

İhtiyaç: "Bu kolonun default değeri ne?"
  → Schema-service cevap veremez
  → MSSQL: SELECT * FROM sys.default_constraints dc JOIN sys.columns c ...
```

---

## 5. 📌 Pratik etkiler

### 5.1 Adım 13 SEAL validation (PR #680)

**Kapsanan**: 8 sourceQuery'nin tabloları + kolonları + PK'leri ✓

**Kapsanmayan**: Unique constraint'ler. `INVOICE.INVOICE_NO` unique mi? Schema-service'ten **bilinmez**, manuel verify lazım.

### 5.2 Float semantic class (PR #684)

**Kapsanan**: Kolon adı + UI type ✓

**Kapsanmayan**: SQL DECIMAL precision/scale (`max_length` var ama precision/scale ayrı `sys.columns` field'ı). Domain decision packet'te **DBA manuel doğrulama** gerek.

### 5.3 Migration impact (Faz 17)

**Kapsanan**: Inferred FK chain (confidence 0.80-0.92) ✓

**Kapsanmayan**:
- Real FK'ler (Workcube'da zaten yok)
- Check constraint'ler (validation rules kayıp)
- Trigger'lar (business logic kayıp)
- Stored procedure dependencies

**Mitigation**: Migration sırasında **manuel cross-check** lazım — schema-service tek başına yeterli değil.

### 5.4 Reporting team

**Kapsanan**: Tablo + kolon + heuristic ilişki ✓ (yeterli sourceQuery yazımı için)

**Kapsanmayan**: Default değer (INSERT için), trigger (side-effect bilmek için).

---

## 6. 🛠️ Eksikleri kapatma planı (roadmap)

| Eksik | Eklemek için | Effort | Etki |
|---|---|---|---|
| Unique constraint | `sys.indexes WHERE is_unique=1` extract + `ColumnInfo.unique` field | Düşük (1-2 saat) | Yüksek (business key tespiti) |
| Default values | `sys.default_constraints` extract | Düşük (1 saat) | Orta |
| Non-PK indexes | PK filter kaldır, separate `IndexInfo` model | Orta (2-4 saat) | Düşük-orta (performans analizi) |
| Check constraints | `sys.check_constraints` extract | Düşük (1 saat) | Orta |
| Stored procedures | `sys.sql_modules type IN ('P','FN','TF','IF')` | Orta (1-2 saat) | Yüksek (business logic visibility) |
| Triggers | `sys.triggers` extract | Düşük (1 saat) | Orta (audit/side-effect) |
| Computed columns | `sys.computed_columns` + flag | Düşük (1-2 saat) | Düşük |
| Real FK (if Workcube adds) | `sys.foreign_keys` extract, confidence=1.0 | Düşük (1-2 saat) | N/A (Workcube'da yok) |

**Toplam**: ~10-15 saat geliştirme — schema-service kapsamı 2x'e çıkar.

---

## 7. ⚠️ Önemli uyarı — agent için

CLAUDE.md kural #9 (no-fake-work) çerçevesinde:

- ✅ Agent `snapshot.relationships[]` heuristic FK'lere **güvenebilir** (confidence score'a göre)
- ❌ Agent "bu kolon unique" iddiası yapmaz — schema-service vermiyor → manuel doğrula
- ❌ Agent "bu tablonun trigger'ı yok" iddiası yapmaz — schema-service bakmıyor
- ✅ Agent sınırı bilirse drift guard ihlal etmez

**Boşlukları kapatan operasyon**: Eksik bilgi için doğrudan MSSQL sorgu (DBA yapar, agent script tasarlar).

---

## 8. Referans

- Kaynak kod: `platform-backend/schema-service/src/main/java/com/example/schema/service/SchemaExtractService.java`
- Discovery: `.../service/discovery/RelationshipDiscoveryService.java`
- Model: `.../model/ColumnInfo.java`, `TableInfo.java`, `Relationship.java`
- Genel rehber: `docs/schema-service-and-schemalens-guide.md` (PR #688)
- Capability map: `docs/schema-service-capability-map.md` (PR #690)
- Cross-AI: Codex thread `019e2c59`
