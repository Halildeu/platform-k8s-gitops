# Schema-Service + SchemaLens — Uçtan Uca Yetenek Haritası

> **Bu belge yetenek katalogudur.** [schema-service-and-schemalens-guide.md](./schema-service-and-schemalens-guide.md) genel rehber; bu dosya **AI/agent + DBA + reporting + migration team** için "şu sorum varsa hangi endpoint'i kullanırım" decision tree'sidir. Her yetenek için: amaç, girdi, çıktı şeması, örnek, tipik karar.

---

## 0. Hızlı seçim (decision tree)

> **Önce kendi sorunu sınıflandır, sonra ilgili bölüme atla.**

| Sorum | Bölüm | Endpoint |
|---|---|---|
| Hangi schema'lar var? | [§1.1](#11-schema-listesi) | `GET /api/v1/schema/schemas` |
| Bir schema'nın tüm tablolarını + ilişkilerini gör | [§1.2](#12-schema-full-snapshot) | `GET /api/v1/schema/snapshot?schema=<name>` |
| Tek bir tablo ne içeriyor, kime referans veriyor? | [§1.3](#13-tek-tablo-detay) | `GET /api/v1/schema/tables/{name}?schema=<>` |
| Kolon adı ile arama (hangi tablolarda var?) | [§1.4](#14-kolon-arama) | `GET /api/v1/schema/search/columns?q=<>` |
| Bir tablo silinirse hangi tablolar etkilenir? | [§1.5](#15-decommission-impact) | `GET /api/v1/schema/impact/{name}` |
| Tabloların domain dağılımı? | [§1.6](#16-domain-map) | `GET /api/v1/schema/domains` |
| Yüksek bağlantılı hub tablolar (FK refs)? | [§1.7](#17-hub-tablolar) | `GET /api/v1/schema/hubs` |
| İki tablo arası FK path? | [§1.8](#18-tablo-aras%C4%B1-path) | `GET /api/v1/schema/path?from=A&to=B` |
| Schema kalite skoru? | [§1.9](#19-health-score) | `GET /api/v1/schema/health-score` |
| Schema'da yeni/silinen tablo var mı? | [§1.10](#110-drift) | `GET /api/v1/schema/drift` |
| Bir kolonun upstream/downstream lineage'ı? | [§2.1](#21-column-lineage) | `GET /api/v1/schema/lineage/{table}/{column}` |
| Master data verisi (departments, branches)? | [§3.1](#31-master-data-read) | `GET /api/v1/schema/master-data/{kind}` |
| Master data sağlık tanılaması? | [§3.2](#32-master-data-diagnostic) | `GET /api/v1/schema/master-data/diagnostic/*` |
| AI'a doğal dilde sor (sorgu, tablo önerisi)? | [§4.1](#41-ai-chat) | `POST /api/v1/schema/chat` |
| Bir tablonun AI üretilmiş açıklaması? | [§4.2](#42-ai-table-descriptions) | `GET /api/v1/schema/ai-descriptions/table/{name}` |
| DBA notları / annotation? | [§5.1](#51-annotations) | `GET /api/v1/schema/annotations` |
| Tablo annotation'ı toplu yükle | [§5.2](#52-annotation-import) | `POST /api/v1/schema/annotations/import` |
| Tablo benzerlik önerisi? | [§1.11](#111-similar-tables-suggestion) | `GET /api/v1/schema/suggestions/{name}` |
| Genel arama (tablo + kolon)? | [§1.12](#112-genel-lookup) | `GET /api/v1/schema/lookup?q=<>` |

---

## 1. Schema Discovery (SchemaController)

### 1.1 Schema Listesi

**Amaç**: Workcube MSSQL'de aktif tüm schema'ları (canonical + tenant + year-tenant) listele.

**Endpoint**: `GET /api/v1/schema/schemas`

**Girdi**: yok

**Çıktı şeması**:
```typescript
Array<{
  name: string;        // örn. "workcube_mikrolink", "workcube_mikrolink_2026_1"
  tableCount: number;  // o schema'daki tablo sayısı
}>
```

**Örnek**:
```bash
curl -H "Authorization: Bearer $JWT" \
  https://testai.acik.com/api/v1/schema/schemas | jq '.[0:3]'
# [
#   {"name": "workcube_mikrolink", "tableCount": 1512},
#   {"name": "workcube_mikrolink_1", "tableCount": 660},
#   {"name": "workcube_mikrolink_2026_1", "tableCount": 222}
# ]
```

**Tipik karar**: "8 sourceQuery'nin tabloları hangi schema'da?" → kategorileri görüp `_2026_<tenant>` veya `_<tenant>` pattern'ini seç.

---

### 1.2 Schema Full Snapshot

**Amaç**: Belirli bir schema'nın tüm tabloları + kolonları + FK ilişkileri + domain map'i tek istek.

**Endpoint**: `GET /api/v1/schema/snapshot?schema=<name>`

**Girdi**: `schema` query param (default `workcube_mikrolink`)

**Çıktı şeması**:
```typescript
{
  version: string;
  metadata: {
    dbType: string;       // "mssql"
    host: string;
    database: string;
    schema: string;
    capturedAt: string;
    tableCount: number;
    columnCount: number;
    relationshipCount: number;
  };
  tables: {
    [tableName: string]: {
      name: string;
      columns: { [colName: string]: { type: string; nullable: boolean; isPrimaryKey: boolean; isForeignKey: boolean } };
      primaryKey: string[];
      foreignKeys: Array<{ column: string; targetTable: string; targetColumn: string }>;
      rowCount?: number;
    }
  };
  relationships: Array<{ fromTable: string; fromColumn: string; toTable: string; toColumn: string }>;
  domains: { [domainName: string]: string[] };  // domain → tablo listesi
  analysis: {
    deadTables: Array<{ table: string; reason: string; rowCount: number }>;
    hubTables: Array<{ table: string; incomingRefs: number }>;
  };
}
```

**Cache**: `maxAge=cacheTtlMinutes` (default config'e bağlı). Schema-service kendi internal cache'inde de tutar.

**Örnek**:
```bash
curl -H "Authorization: Bearer $JWT" \
  "https://testai.acik.com/api/v1/schema/snapshot?schema=workcube_mikrolink_2026_1" \
  | jq '{tableCount: .metadata.tableCount, tables: .tables | keys | .[0:5]}'
```

**Tipik karar**: 
- "Bu yıl-tenant'ta ACCOUNT_CARD var mı?" → snapshot.tables['ACCOUNT_CARD']
- "FK chain'i traverse et" → snapshot.relationships üzerinde graph algoritması

---

### 1.3 Tek Tablo Detay

**Amaç**: Bir tablo + outgoing FK + incoming references + domain.

**Endpoint**: `GET /api/v1/schema/tables/{tableName}?schema=<name>`

**Çıktı**:
```typescript
{
  table: TableInfo;
  outgoingFks: Relationship[];  // bu tablodan başlayan FK'ler
  incomingRefs: Relationship[];  // bu tabloya gelen FK'ler
  domain: string;
}
```

**Tipik karar**: "Sourcequery'de `JOIN COMPANY C ON E.COMPANY_ID = C.COMPANY_ID` doğru mu?" → tabloyu çek, `outgoingFks` içinde `targetTable: 'COMPANY'` var mı kontrol et.

---

### 1.4 Kolon Arama

**Amaç**: Bir kolon adı hangi tablolarda var?

**Endpoint**: `GET /api/v1/schema/search/columns?q=<query>&schema=<name>`

**Çıktı**:
```typescript
{
  query: string;
  matches: Array<{ table: string; column: string; type: string }>;
}
```

**Tipik karar**: 
- "ACTION_DATE hangi tablolarda var?" → timezone proposal için scope tespiti
- "COMPANY_ID kaç tabloda FK olarak kullanılıyor?" → cardinality risk değerlendirmesi

---

### 1.5 Decommission Impact

**Amaç**: Bir tablo silinirse hangi tablolar etkilenir (FK chain).

**Endpoint**: `GET /api/v1/schema/impact/{tableName}`

**Çıktı**:
```typescript
{
  table: string;
  directlyAffected: string[];   // 1 hop (incoming FK)
  transitivelyAffected: string[];  // N hop transitive closure
  totalCount: number;
}
```

**Tipik karar**: 
- "ACCOUNT_CARD'ı Postgres'e migrate ederken hangi tabloları da migrate etmeliyim?" → transitive list
- "Bu tabloyu drop edebilir miyim?" → directlyAffected boş ise OK

---

### 1.6 Domain Map

**Amaç**: 22 domain (EMPLOYEES, COMPANY, BRANCH, vb.) ve içerdiği tablolar.

**Endpoint**: `GET /api/v1/schema/domains`

**Çıktı**:
```typescript
{
  [domainName: string]: {
    tables: string[];
    tableCount: number;
  };
}
```

**Tipik karar**: "Reporting team için HR domain tabloları?" → `domains.EMPLOYEES.tables`

---

### 1.7 Hub Tablolar

**Amaç**: Yüksek bağlantılı tablolar (FK referans count desc).

**Endpoint**: `GET /api/v1/schema/hubs`

**Çıktı**:
```typescript
Array<{
  table: string;
  incomingRefs: number;
  domain: string;
}>
```

**Tipik karar**:
- "Migration sırasında önce hangi tabloları taşımalıyım?" → en yüksek hub önce
- "Hangi tablolar `dimension table` candidate?" → top hub tabloları

---

### 1.8 Tablo Arası Path

**Amaç**: İki tablo arası en kısa FK path.

**Endpoint**: `GET /api/v1/schema/path?from=A&to=B`

**Çıktı**:
```typescript
{
  from: string;
  to: string;
  path: Array<{ table: string; via: string }>;
  hopCount: number;
}
```

**Tipik karar**: "EMPLOYEES → INVOICE_ROW yolu var mı?" → JOIN chain için path

---

### 1.9 Health Score

**Amaç**: Schema kalitesi (orphan, missing FK, naming).

**Endpoint**: `GET /api/v1/schema/health-score`

**Çıktı**: Skor + breakdown (orphan tables, naming inconsistencies, undocumented tables count).

**Tipik karar**: "Faz 17 öncesi schema kalitesi baseline?" → ilk skor, sonra periyodik karşılaştırma.

---

### 1.10 Drift

**Amaç**: Yeni/silinen/değişen tablolar (baseline ile karşılaştırma).

**Endpoint**: 
- `GET /api/v1/schema/drift` (current state)
- `GET /api/v1/schema/drift/history` (zaman serisi)

**Çıktı**:
```typescript
{
  newTables: string[];
  removedTables: string[];
  modifiedTables: Array<{ table: string; changes: string[] }>;
  lastChecked: string;
}
```

**Tipik karar**: "Son hafta Workcube'da yeni tablo eklenmiş mi?" → drift kontrolü.

---

### 1.11 Similar Tables Suggestion

**Amaç**: Verilen tabloya benzer tablolar (kolon adı / pattern üzerinden).

**Endpoint**: `GET /api/v1/schema/suggestions/{tableName}`

**Tipik karar**: "ACCOUNT_CARD'a benzer başka tablo var mı?" → duplicate / shard detection.

---

### 1.12 Genel Lookup

**Amaç**: Tek arama bar — tablo + kolon + ilişki.

**Endpoint**: `GET /api/v1/schema/lookup?q=<query>`

**Çıktı**:
```typescript
{
  tables: Array<{ name: string; matchScore: number }>;
  columns: Array<{ table: string; column: string; matchScore: number }>;
}
```

---

## 2. Column Lineage (LineageController)

### 2.1 Column Lineage

**Amaç**: Bir kolonun upstream/downstream lineage'ı (view definition'ları tarayarak).

**Endpoint**: `GET /api/v1/schema/lineage/{tableName}/{columnName}?schema=<>`

**Çıktı**:
```typescript
{
  targetTable: string;
  targetColumn: string;
  nodes: Array<{ table: string; column: string; type: "source" | "transform" | "target" }>;
  edges: Array<{ from: Node; to: Node; transformation: string }>;
}
```

**Tipik karar**: "ACCOUNT_CARD.AMOUNT kolonu hangi view'larda kullanılıyor?" → migration impact

---

## 3. Master Data (MasterDataReadController + MasterDataDiagnosticController)

### 3.1 Master Data Read

**Amaç**: Master data (departments, branches, vb.) okuma.

**Endpoint**: `GET /api/v1/schema/master-data/{kind}`

**`{kind}` örnekleri**: `departments`, `branches`, `companies`, `employees`...

**Çıktı**: O master data tablosunun satırları.

**Tipik karar**: "Hangi departman ID'leri canlı?" → reporting filter dropdown'ı

---

### 3.2 Master Data Diagnostic

**Amaç**: Master tabloların sağlık tanılaması.

**Endpoint**: `GET /api/v1/schema/master-data/diagnostic/departments`

**Çıktı**: Orphan satırlar, eksik FK'ler, duplicate'lar.

---

## 4. AI Capabilities (AiChatController + AiDescriptionController)

### 4.1 AI Chat

**Amaç**: Doğal dil sorgu → schema-aware cevap (gerekirse SQL üretir).

**Endpoint**: `POST /api/v1/schema/chat`

**Girdi**:
```json
{
  "message": "Müşteri başına aylık ortalama fatura tutarını veren bir sorgu yazar mısın?",
  "schema": "workcube_mikrolink_2026_1"
}
```

**Çıktı şeması**:
```typescript
{
  answer: string;            // human-readable Markdown
  sql: string | null;        // önerilen SQL (varsa)
  referencedTables: string[]; // sorguda kullanılan tablolar
  aiGenerated: boolean;       // true = LLM, false = local heuristic
}
```

**Önemli davranış**:
- Önce **local logic** dener (LLM çağırmaz, ücretsiz):
  - "X kolonu hangi tablolarda var?" → search columns
  - "Bu veritabanı kaç tablo / kolon / ilişki?" → metadata summary
- Local cevap yoksa **LLM**'e gider (config `schema.ai.api-key` + `schema.ai.enabled=true` lazım).
- LLM disabled ise helpful fallback (mevcut tool listesi).

**Tipik kararlar**:
- "DBA olarak schema'yı tanımıyorum, ACCOUNT_CARD ne işe yarar?" → AI Chat doğal dil cevap
- "Reporting team olarak 'haftalık satış trendi' sorgusu lazım" → AI SQL üretir
- "Migration impact için 'CARI_ACTIONS'a bağımlı tablolar?" → AI list verir + endpoint linkler

**SQL üretiminin sınırı**: AI sadece schema'yı bilir, üretilen SQL **canlı veride çalıştırılmamış** olabilir. SQL preview için ayrı sandbox kullanın.

---

### 4.2 AI Table Descriptions

**Amaç**: Tablonun AI üretilmiş açıklaması.

**Endpoint**: 
- `GET /api/v1/schema/ai-descriptions/table/{tableName}` (tek tablo)
- `GET /api/v1/schema/ai-descriptions/batch` (toplu)

**Çıktı**:
```typescript
{
  table: string;
  description: string;      // AI üretilmiş açıklama
  generatedAt: string;
  confidence: "high" | "medium" | "low";
}
```

**Tipik karar**: Reporting team / yeni katılan DBA için tablo öğrenme.

---

## 5. Annotation (AnnotationController)

### 5.1 Annotations

**Amaç**: DBA notları (manuel açıklama, business glossary).

**Endpointler**:
- `GET /api/v1/schema/annotations` (tümü)
- `GET /api/v1/schema/annotations/table/{tableName}` (belirli tablo)
- `GET /api/v1/schema/annotations/stats` (kapsam)

**Çıktı**:
```typescript
{
  table: string;
  column?: string;
  note: string;
  author: string;
  updatedAt: string;
}
```

**Tipik karar**: 
- "Bu tablo legacy mi, neden?" → annotation kontrol
- AI Chat'e ek context (annotation'lar AI'a injected)

---

### 5.2 Annotation Import

**Amaç**: Toplu annotation yükleme.

**Endpoint**: `POST /api/v1/schema/annotations/import`

**Tipik akış**: DBA Excel'den CSV → import → AI Chat artık business glossary'yi biliyor.

---

## 6. 12 Uçtan Uca Use Case

### UC-1 — DBA: "Migrate edilebilir mi?" (Faz 17 cutover)

```
1. GET /impact/ACCOUNT_CARD → directlyAffected + transitiveAffected
2. GET /annotations/table/ACCOUNT_CARD → DBA notları, deprecated mi?
3. GET /lineage/ACCOUNT_CARD/AMOUNT → kolon hangi view'larda?
4. GET /tables/ACCOUNT_CARD → row count + FK chain
→ Karar: migrate / keep_workcube / exclude
```

### UC-2 — Reporting: "Sourcequery cross-check" (Adım 13 SEAL)

```
1. GET /schemas → uygun year-tenant + canonical bul
2. GET /snapshot?schema=workcube_mikrolink_2026_1 → 222 tablo
3. GET /snapshot?schema=workcube_mikrolink → 1512 canonical
4. SQL'deki [{schema}].[TABLE] referansları → 2'yi cross-check
5. SQL'deki [workcube_mikrolink].[TABLE] → 3'ü cross-check
→ Karar: 8/8 PASS veya needs_review
```

### UC-3 — Reporting team: "Hangi tablolar lazım?"

```
1. POST /chat { message: "müşteri başına aylık ortalama fatura", schema }
   → AI doğal cevap + SQL + referencedTables
2. SQL'i sandbox'ta test et
3. Tabloları sourceQuery'ye koy
```

### UC-4 — Migration: "Decommission planı"

```
1. GET /hubs → en yüksek bağlantılı tablolar
2. Her hub için GET /impact/{name}
3. Transitive list ile migration order (dep depth desc)
4. GET /domains → domain başına grup migration
```

### UC-5 — DBA: "Sorgu performans optimizasyonu"

```
1. GET /tables/{name} → rowCount
2. GET /path?from=INVOICE&to=COMPANY → FK chain depth
3. Hop count yüksekse → denormalize / materialized view öner
```

### UC-6 — DBA: "Yeni schema değişimi var mı?"

```
1. GET /drift → newTables + removedTables + modifiedTables
2. Yeni tablolar için annotation gerek mi?
3. Removed tablolar için downstream impact (UC-1)
```

### UC-7 — Reporting team: "Hangi kolon `X` benziyor?"

```
1. GET /search/columns?q=AMOUNT → tüm `*AMOUNT*` kolonlar
2. GET /search/columns?q=TUTAR → Türkçe alias
3. AI Chat: "AMOUNT ve TUTAR'ı eşleştir"
→ Semantic mapping for float_semantic_class
```

### UC-8 — Migration: "Cross-tenant master keep_workcube karar"

```
1. GET /schemas → tenant başına dağılım
2. GET /tables/COMPANY?schema=workcube_mikrolink → canonical mi
3. Her tenant'ta aynı kayıt var mı? → cross-tenant master ise keep_workcube
```

### UC-9 — DBA onboarding: "Bu sistem ne işe yarar?"

```
1. GET /domains → 22 domain overview
2. GET /hubs → kritik tablolar
3. POST /chat { message: "kısaca bu veritabanını özetle" }
4. GET /annotations → mevcut DBA notları
```

### UC-10 — Reporting: "Bir kolon kim tarafından güncelleniyor?"

```
1. GET /lineage/{table}/{column}
2. Trace nodes → kaynak tablo bulun
3. AI Chat: "{ kolon } write-only mı yoksa derived mi?"
```

### UC-11 — Quality: "Orphan tablolar"

```
1. GET /health-score → schema kalitesi
2. GET /snapshot?schema=<> → analysis.deadTables
3. GET /impact/{name} her bir orphan için → silinebilir mi?
```

### UC-12 — Agent: "Sentetik fixture yasak, canlı evidence şart"

```
HARD RULE: agent INFORMATION_SCHEMA manuel sorgulamaz, schema-service kullanır:

1. GET /schemas (cache)
2. GET /snapshot?schema=<name>
3. Cross-check sourceQuery / migration target
4. JSON output → repo'da committed evidence (örn. PR #680)
NO synthetic table/column/FK creation.
```

---

## 7. Agent (AI) Kullanım Decision Tree

```
İhtiyaç başı
  │
  ├─ Schema discovery?
  │    ├─ Tüm schema'lar → /schemas
  │    ├─ Belirli schema'nın yapısı → /snapshot?schema=<>
  │    └─ Tek tablo → /tables/{name}
  │
  ├─ İlişki / impact?
  │    ├─ Tablo silme analizi → /impact/{name}
  │    ├─ İki tablo arası path → /path?from=A&to=B
  │    └─ Hub tabloları → /hubs
  │
  ├─ Kolon-level inceleme?
  │    ├─ Hangi tablolarda kullanılır → /search/columns?q=<>
  │    └─ Upstream/downstream → /lineage/{table}/{column}
  │
  ├─ Kalite / drift?
  │    ├─ Sağlık skoru → /health-score
  │    └─ Yeni/silinen tablolar → /drift
  │
  ├─ Doğal dil sorgu?
  │    ├─ Tablo açıklaması → /ai-descriptions/table/{name}
  │    └─ SQL üretimi / tablo önerisi → POST /chat
  │
  ├─ Master data?
  │    └─ /master-data/{kind}
  │
  └─ Annotation?
       └─ /annotations/table/{name}
```

### Agent kuralları (CLAUDE.md kural #9 alt-not)

1. **Önce committed snapshot** dene (`docs/migration/workcube-schema.json`, 3.4 MB, canonical)
2. Snapshot yetmezse → canlı endpoint (`/snapshot?schema=<>`)
3. **Sentetik tablo/kolon/FK üretme** (drift guard)
4. JWT token kullanıcının session'ından alınır; agent kendi credentials commit etmez
5. Cross-AI peer review için Codex ile validation (Codex thread `019e2c59`)

---

## 8. Frontend SchemaLens — Hangi sekme hangi endpoint

| UI sekme | Backend endpoint(s) |
|---|---|
| **ER Graph** (Domain Map + Neighborhood) | `/snapshot?schema=<>` + `/domains` |
| **Columns** | `/tables/{name}` + `/search/columns?q=<>` |
| **Find Path** | `/path?from=A&to=B` |
| **Hubs** | `/hubs` |
| **Dead Tables** | `/snapshot.analysis.deadTables` |
| **Health** | `/health-score` |
| **Impact** | `/impact/{name}` |
| **Drift** | `/drift` + `/drift/history` |
| **AI Chat** | `POST /chat` |
| **Export** | `/snapshot?schema=<>` (JSON download) |

---

## 9. Auth Modelleri

### 9.1 JWT (default, user/agent)

```http
Authorization: Bearer <jwt>
```
- Issuer: Keycloak realm `platform-test` (testai) / `platform-prod` (prod)
- Audience: `account, frontend, schema-service`
- User browser session veya agent (browser MCP üzerinden)

### 9.2 Internal API Key (service-to-service)

```http
X-Internal-Api-Key: <key>
```
- Test/dev'de boş bırakılabilir (passthrough)
- Production'da Vault/ESO ile inject edilir
- `schema.snapshot.internal-api-key` config

### 9.3 Auth flow

```
internalOk = configuredKey.isBlank() OR configuredKey == providedKey
jwtOk      = jwt != null

allow = internalOk OR jwtOk
```

---

## 10. Performans + Cache

- `@Cacheable("schemas")` — `/schemas` endpoint cache'li (Schema-service kendi memory)
- Snapshot cache: HTTP `Cache-Control: max-age=<cacheTtlMinutes>` (config)
- MSSQL bağlantısı `applicationIntent=ReadOnly` (write koruması)
- Heavy snapshot (canonical 1512 tablo, ~3 MB) → ilk fetch 1-2 saniye, sonra cache hit

**Rate limit**: explicit yok ama cluster ingress üzerinden rate limited.

---

## 11. Sınırlamalar + Roadmap

| Sınırlama | Etki | Mitigation |
|---|---|---|
| Drift baseline cluster restart'ta sıfırlanır | Drift history kaybı | (gelecek) Postgres'e persist |
| AI Chat key kalitesi modele bağlı | SQL üretimi değişken | LLM provider seçimi config'de |
| Annotation otomatik discovery yok | Manuel yükleme | (gelecek) JIRA / Confluence sync |
| Yearly-schema ETL pipeline deferred | Parametric ETL yok ama crawl var | Faz 16.2.P deferred |
| Internal API key prod'da Vault gerekiyor | Misconfig riski | ESO renewal otomatik |

---

## 12. Hızlı bakım

```bash
# Pod sağlığı
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test get pod -l app=schema-service'

# Loglar
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test logs deploy/schema-service --tail=100'

# Cache flush (restart)
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test rollout restart deploy/schema-service'

# MSSQL bağlantı test
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test exec deploy/schema-service -- \
  curl -sS http://localhost:8081/actuator/health'
```

---

## 13. Referans

- Genel rehber: [schema-service-and-schemalens-guide.md](./schema-service-and-schemalens-guide.md)
- ADR: `platform-backend/docs/adr/0008-schema-truth-integration.md`
- Spec: `platform-backend/docs/plans/2026-05-reporting-phase-2-program-8-schema-truth-integration-spec.md`
- Drift guard: `CLAUDE.md` "Hızlı Bağlam — MSSQL Şema Gezgini"
- Canlı kullanım kanıtı: PR #680 v2 validation (8/8 PASS schema cross-check)
- Cross-AI Codex thread: `019e2c59-1cdb-7ea3-a8e6-bf3fcabc62b2`
