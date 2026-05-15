# Schema-Service + SchemaLens (Şema Gezgini) Guide

> **Tek-stop rehber.** Backend `schema-service` (port 8096) ve frontend `SchemaLens` (Şema Gezgini, `/admin/schema-explorer`) için ne işe yarar, nasıl kullanılır, hangi endpoint ne döner, hangi sekme ne yapar.
>
> **Tarih**: 2026-05-15 (PR #680 v2 validation + PR #681 docs-truth + PR #684 domain decision packet sonrası konsolide rehber).

---

## 1. Tek satırla

Workcube MSSQL'in canlı şema kaşifi. Backend Spring Boot servisi (`schema-service`) MSSQL `INFORMATION_SCHEMA`'sını okuyup REST endpoint'lere çevirir; frontend MFE (`SchemaLens`) bu endpoint'leri ER graph, ilişki, etki analizi, AI-yardımlı tarama gibi görsellerle gösterir.

**Birlikte ne yapar**:
- DBA / backend lead için **tablo + kolon + ilişki keşfi**
- Reporting team için **sourceQuery cross-check** (R15 user-visible repair, Adım 13 SEAL)
- Migration team için **decommission impact analysis** (Faz 17 Workcube cutover)
- Agent için **canlı schema evidence** (no-fake-work kuralı — sentetik tablo/kolon yasak)

---

## 2. Mimari

```
┌────────────────────────────────────────────────────────────────┐
│ MFE (SchemaLens)                                                │
│ /admin/schema-explorer                                          │
│ ER Graph · Columns · Find Path · Hubs · Dead Tables · Health   │
│ Impact · Drift · AI Chat · Export                              │
└──────────────────────────┬─────────────────────────────────────┘
                           │ JWT (audience: schema-service)
                           ▼
┌────────────────────────────────────────────────────────────────┐
│ schema-service (Spring Boot, port 8096)                         │
│ /api/v1/schema/*    /api/v1/schema/master-data/*                │
│ /api/v1/schema/ai-descriptions    /api/v1/schema/annotations    │
│ /api/v1/schema/lineage     /api/v1/schema/chat                  │
└──────────────────────────┬─────────────────────────────────────┘
                           │ NTLM (read-only, applicationIntent=ReadOnly)
                           ▼
┌────────────────────────────────────────────────────────────────┐
│ Workcube MSSQL (workcube-mssql:11433)                           │
│ 319+ schema · workcube_mikrolink_(canonical|<id>|<year>_<id>)   │
│ ~30k tablo · ~500k kolon · ~50k FK ilişki                       │
└────────────────────────────────────────────────────────────────┘
```

### Deployment

- Cluster: `k3d-test` namespace `platform-test` (Deployment `schema-service`)
- Container port 8096 (http API), 8081 (management/actuator)
- Service: ClusterIP, internal
- MSSQL bağlantı NTLM, `domain=boreas`, `applicationIntent=ReadOnly` (write koruması)

### Auth

İki yol:
1. **JWT** — `Authorization: Bearer <token>`, audience `schema-service` (Keycloak realm `platform-test`)
2. **Internal API key** — `X-Internal-Api-Key: <key>` header (test/dev'de boş bırakılabilir, prod'da Vault/ESO)

---

## 3. Schema kategorileri (319+ schema)

`GET /api/v1/schema/schemas` ile keşfedilir. Üç kategori:

| Pattern | Adet | Örnek | Tablo sayısı | İçerik |
|---|---|---|---|---|
| `workcube_mikrolink` | 1 | canonical | 1512 | Static master + HR + product (cross-tenant, paylaşımlı) |
| `workcube_mikrolink_<id>` | 43 | `_1` (660), `_35` (607), `_43` (607) | 426-660 | Tenant başına yıllık-bağımsız master |
| `workcube_mikrolink_<year>_<id>` | ~276 | `_2026_1` (222), `_2025_35` (258) | 208-258 | Yıl + tenant başına **transactional** (ACCOUNT_CARD, INVOICE, CARI_ACTIONS, vb.) |

**`tableCount` SQL sorgusu**:
```sql
SELECT s.name AS schema_name, COUNT(t.object_id) AS table_count
FROM sys.schemas s
LEFT JOIN sys.tables t ON s.schema_id = t.schema_id
WHERE s.name LIKE 'workcube_mikrolink%' OR s.name = 'dbo'
GROUP BY s.name
HAVING COUNT(t.object_id) > 0
ORDER BY COUNT(t.object_id) DESC
```

### Tablo-schema pattern özet

| Tablo ailesi | Schema | Örnek |
|---|---|---|
| Master / HR (yıl-bağımsız) | `workcube_mikrolink` (canonical) | `COMPANY`, `BRANCH`, `EMPLOYEES`, `EMPLOYEES_PUANTAJ`, `MONEY_HISTORY` |
| Tenant master | `workcube_mikrolink_<id>` | Lookup tabloları, yıl-bağımsız tenant config |
| Transactional yıl-tenant | `workcube_mikrolink_<year>_<id>` | `ACCOUNT_CARD`, `ACCOUNT_CARD_ROWS`, `INVOICE`, `INVOICE_ROW`, `CARI_ACTIONS`, `STOCK_FIS`, `BANK_ACTIONS`, `EXPENSE_*` |

---

## 4. Backend API yüzeyi

7 controller, 22+ endpoint. Hepsi `/api/v1/schema/*` namespace altında.

### `SchemaController` (canonical)

| Endpoint | Açıklama |
|---|---|
| `GET /api/v1/schema/schemas` | Tüm aktif schema'ları listeler (`workcube_mikrolink%` LIKE), 319+ schema döner |
| `GET /api/v1/schema/snapshot?schema=<name>` | Belirli schema'nın full snapshot'ı (tables + columns + relationships + domains) |
| `GET /api/v1/schema/tables/{tableName}?schema=<name>` | Tek tablo detayı + outgoing/incoming FK + domain |
| `GET /api/v1/schema/search/columns?q=<query>&schema=<name>` | Kolon arama — hangi tablolarda var |
| `GET /api/v1/schema/impact/{tableName}` | Decommission impact analizi — bu tablo silinirse hangi tablolar etkilenir |
| `GET /api/v1/schema/domains` | 22 domain (EMPLOYEES, COMPANY, BRANCH, vb.) ve içerdiği tablolar |
| `GET /api/v1/schema/hubs` | Yüksek bağlantılı hub tablolar (FK count desc) |
| `GET /api/v1/schema/path?from=A&to=B` | İki tablo arası en kısa FK path |
| `GET /api/v1/schema/health-score` | Schema kalite skoru (orphan tables, missing FKs, vb.) |
| `GET /api/v1/schema/drift` | Yeni/silinmiş/değişen tablolar (baseline ile karşılaştırma) |
| `GET /api/v1/schema/drift/history` | Drift olaylarının zaman serisi |
| `GET /api/v1/schema/suggestions/{tableName}` | "Bu tabloya benzer tablolar" öneri |
| `GET /api/v1/schema/lookup?q=<query>` | Genel arama (tablo + kolon + ilişki) |

### `MasterDataReadController` / `MasterDataDiagnosticController`

| Endpoint | Açıklama |
|---|---|
| `GET /api/v1/schema/master-data/{kind}` | Master data (departments, branches, vb.) read |
| `GET /api/v1/schema/master-data/diagnostic/departments` | Master tabloların diagnostic durumu |

### `AnnotationController`

| Endpoint | Açıklama |
|---|---|
| `GET /api/v1/schema/annotations` | Manuel annotation listesi (DBA notları) |
| `GET /api/v1/schema/annotations/table/{tableName}` | Belirli tablonun annotation'ı |
| `POST /api/v1/schema/annotations/import` | Annotation toplu yükleme |
| `GET /api/v1/schema/annotations/stats` | Annotation kapsamı istatistik |

### `AiDescriptionController`

| Endpoint | Açıklama |
|---|---|
| `GET /api/v1/schema/ai-descriptions/table/{tableName}` | Bir tablonun AI üretilmiş açıklaması |
| `GET /api/v1/schema/ai-descriptions/batch` | Batch açıklama |

### `AiChatController`

| Endpoint | Açıklama |
|---|---|
| `POST /api/v1/schema/chat` | Schema-aware AI chat (kullanıcı doğal dilde sorgu, AI tablo/kolon önerir) |

### `LineageController`

| Endpoint | Açıklama |
|---|---|
| `GET /api/v1/schema/lineage/{tableName}/{columnName}` | Bir kolonun upstream/downstream lineage |

---

## 5. Frontend SchemaLens — UI sekmeleri

**URL**: `/admin/schema-explorer` (production'da `testai.acik.com/admin/schema-explorer`)

**Header**: Schema selector dropdown (320 option) + canlı sayaçlar (`1512 tables · 26326 columns · 1777 rels · 22 domains`)

**Sekmeler**:

| Sekme | Ne yapar |
|---|---|
| **ER Graph** | Tabloları + FK ilişkilerini interaktif graph'ta gösterir. Domain map + neighborhood navigation. |
| **Columns** | Belirli tabloların kolon detayları (type, nullable, FK target) |
| **Find Path** | İki tablo arası en kısa FK path |
| **Hubs** | En çok referans alan tablolar (FK in/out count) |
| **Dead Tables** | Hiç referans almayan veya tüm referansları kopuk tablolar |
| **Health** | Schema kalite skoru — orphan, missing FK, naming inconsistency |
| **Impact** | "Bu tabloyu silersem ne etkilenir" analizi |
| **Drift** | Schema değişim tarihçesi (yeni/silinen tablo + kolon) |
| **AI Chat** | Doğal dil sorgu → schema-aware cevap |
| **Export** | Snapshot'ı JSON/CSV/Mermaid olarak dışa aktarma |

**Sol panel**: Tablo listesi + tablo başına FK in/out count + kategori filter (`ALL`, `OTHER`, `EMPLOYEES`, `EMPLOYEES_2`, `SETUP`, `TRAINING`, `WRK`, `MEMBER`, `CONTENT`, vb.).

**Arama**: Üst search bar (`Search tables...`) ile tablo adına göre filter.

---

## 6. Tipik kullanım senaryoları

### 6.1 Sourcequery DBA review (Adım 13 SEAL)

```bash
# 8 sourceQuery'nin tablolarını canlı schema ile cross-check
# (Annex 2A v2 validation PR #680)

# 1. Schema listesini al
curl -H "Authorization: Bearer $JWT" \
  http://schema-service:8096/api/v1/schema/schemas

# 2. Bir transactional tenant snapshot'ı çek
curl -H "Authorization: Bearer $JWT" \
  "http://schema-service:8096/api/v1/schema/snapshot?schema=workcube_mikrolink_2026_1" \
  > /tmp/snap.json

# 3. Belirli tabloyu detaylı incele
curl -H "Authorization: Bearer $JWT" \
  "http://schema-service:8096/api/v1/schema/tables/ACCOUNT_CARD?schema=workcube_mikrolink_2026_1"
```

### 6.2 Decommission impact analizi (Faz 17 Workcube cutover)

```bash
# Bu tabloyu Postgres'e migrate ederken hangi tabloları da migrate etmeliyim?
curl -H "Authorization: Bearer $JWT" \
  http://schema-service:8096/api/v1/schema/impact/CARI_ACTIONS
# → FK chain'i izleyerek transitive dependency listesi döner
```

### 6.3 UI: ER Graph'ta tablonun komşuluğunu görmek

1. `/admin/schema-explorer`'a git
2. Sol panel'den tablo seç (örn. `ACCOUNT_CARD`)
3. ER Graph sekmesinde **Neighborhood** modu ile sadece komşu tabloları görüntüle

### 6.4 AI Chat ile sorgu üretmek

`/admin/schema-explorer` → AI Chat sekmesi:

> "Müşteri başına aylık ortalama fatura tutarını veren bir sorgu yazar mısın?"

AI doğru tabloları (`INVOICE`, `INVOICE_ROW`, `CUSTOMER`) önerip JOIN şemasıyla SQL çıkarır.

### 6.5 Drift takibi (regular cron)

```bash
# Workcube schema'sında yeni eklenen / silinen tablolar
curl -H "Authorization: Bearer $JWT" \
  http://schema-service:8096/api/v1/schema/drift?schema=workcube_mikrolink

# Drift tarihçesi
curl -H "Authorization: Bearer $JWT" \
  http://schema-service:8096/api/v1/schema/drift/history?schema=workcube_mikrolink
```

---

## 7. Agent için kullanım kuralları

CLAUDE.md drift guard'ları:

- ✅ Agent **read-only endpoint'leri JWT ile kullanabilir** (canonical + parametric snapshot, drift, hubs, vb.)
- ✅ Cross-check / validation için canlı endpoint'i tercih et (PR #680 8/8 PASS örneği)
- ❌ **Sentetik tablo/kolon/FK üretme** (no-fake-work kural #9). Snapshot canlıdan gelir, manuel uydurulmaz.
- ❌ Yeni feature olarak yearly-schema crawl tool yazma — endpoint zaten var (`/snapshot?schema=<name>`)
- ❌ Credential / DSN artefakt commit etme (env var'lar pod-içi kalır)

### Browser MCP üzerinden agent erişimi

```js
// Kullanıcının session JWT'siyle
const token = localStorage.getItem('token');
const schemas = await fetch('/api/v1/schema/schemas', {
  headers: { Authorization: `Bearer ${token}` }
}).then(r => r.json());

// Specific schema snapshot
const snap = await fetch('/api/v1/schema/snapshot?schema=workcube_mikrolink_2026_1', {
  headers: { Authorization: `Bearer ${token}` }
}).then(r => r.json());
```

---

## 8. Committed snapshot vs canlı endpoint

| Kaynak | Konum | Boyut | İçerik |
|---|---|---|---|
| **Canonical static dump** | `docs/migration/workcube-schema.json` (3.4 MB) | 1509 tablo, 26240 kolon | Sadece `workcube_mikrolink` canonical, master + HR |
| **Live API** | `schema-service` `/api/v1/schema/snapshot?schema=<name>` | dinamik | Her schema için tam snapshot (319+ schema dahil) |

**Hangi kaynağı kullan**:
- Tablo/kolon/FK gereksinimi **canonical** ise → `workcube-schema.json` (hızlı, committed, agent prefer)
- Year-tenant / parametric / transactional ise → canlı API (`/snapshot?schema=workcube_mikrolink_<year>_<id>`)
- Cross-schema cross-check için → ikisini birden kullan (örn. PR #680 v2 validation)

---

## 9. Referans bağlantılar

| Konu | Referans |
|---|---|
| Backend kaynak | `platform-backend/schema-service/src/main/java/com/example/schema/controller/*.java` |
| Frontend kaynak | `platform-web/apps/mfe-schema-explorer/` |
| Drift guard | `CLAUDE.md` "Hızlı Bağlam — MSSQL Şema Gezgini" |
| PLAN faz | `PLAN.md` Faz 16.2.P (parametric ETL deferred; crawl tool mevcut) |
| ADR | `platform-backend/docs/adr/0008-schema-truth-integration.md` |
| Spec | `platform-backend/docs/plans/2026-05-reporting-phase-2-program-8-schema-truth-integration-spec.md` |
| Snapshot kullanım örneği | Annex 2A v2 (PR #680), Adım 13 SEAL validation |

---

## 10. Sınırlamalar + bilinen boşluklar

- **Yearly-schema crawl ETL pipeline** hâlâ deferred (Faz 16.2.P). `/snapshot?schema=` endpoint mevcut ama ETL runner parametric expansion yok (1 manifest → N TableMeta).
- **Drift baseline** schema-service kendi cache'inde saklar; cluster restart'ta sıfırdan başlar (henüz Postgres'e persist edilmiyor).
- **AI Chat** kullanıcının LLM key'ini değil, schema-service'in dahili AI integration'ını kullanır (`schema.ai.api-key` config). Cevap kalitesi bu key'in modeline bağlı.
- **Annotation import** manuel; otomatik discovery yok. DBA notları elle yüklenir.
