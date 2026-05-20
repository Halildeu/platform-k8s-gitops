# ADR-0025 — Enterprise Platform Charter: Process & Parameter Management Hub

> **Status**: Proposed (charter — vendor seçimleri MÜHÜRLENMEZ; bounded spike + guardrail. AGREE/ratify Codex thread `019e4626` iter-3 sonrası → Accepted)
> **Date**: 2026-05-20
> **Sprint**: Faz 24 (Enterprise Platform Charter)
> **Codex thread**: `019e4626-1c05-7c60-840a-c6b42a35e946` (REVISE iter-1 + REVISE iter-2 absorb; ready_for_adr_draft=true)
> **Predecessors**:
> - ADR-0002 (single-host dual-cluster, §7.1 PG-primary)
> - ADR-0013 (notification orchestration — process plane pattern; D38/D39/D43/D44/D46)
> - ADR-0015 (Our Company v25 transition — master-data refactor)
> - ADR-0021 (M365 SSO broker via Keycloak — authn-data boundary)
> - ADR-0023 (promotion pipeline test-overlay-authoritative + runtime-artifact ledger)
> **Related artifacts** (oluşturulacak; charter sonrası alt-faz'larda):
> - `docs/platform/capability-map.md` — 5-plane × capability matrix
> - `docs/platform/workcube-taxonomy.md` — 1509 tablo sınıflandırması (parameter/master/transaction/system-config/historical/report-only)
> - `docs/platform/differentiator-catalog.md` — "olmayanlar" early catalog
> - `docs/platform/non-goals.md` — bilinçli atılacaklar (table-per-screen CRUD, year-tenant runtime model, full low-code v0)
> - `docs/runbooks/RB-faz-24-charter-spike.md` — 4-hafta spike acceptance criteria + deliverable takip

## Bağlam

Kullanıcı 2026-05-20 stratejik direktifi:

> "Data driven sistem yapacağım — kurumsal uçtan uca yönetim sistemi, AI ile aktif. Kurumların ihtiyacı olan süreçler ve akışlar, bunlara bağlı tüm sistem ve parametrelerin buradan takibi yönetimi yapılacak."
>
> "Ana SQL'imiz burada olacak, her şeyi baştan tasarlayacağız ama önce diğer yerlerde olmayanları yapacağız — katma değeri yüksek olanları ve olmazsa olmazları; sonra mevcutları bu bakış açısı ile geliştirerek bu sisteme taşıyacağız."

Bu, `autonomous-orchestrator` platformunun **klasik Turkish enterprise stack (Workcube — `workcube_mikrolink` MSSQL kaynak; 1509 tablo, 26240 kolon, 1774 FK, 319+ tenant/year schema) replacement vizyonunun modern Spring/Java/PG/k8s + AI-first reinterpretasyonu**. Faz 23 notification orchestration tek bir kurumsal süreç (mesajlaşma); vizyon, **N × Faz-23-benzeri orchestrator + dynamic forms + parameter registry + AI conductor + governance native** anlamına gelir.

### Foundation (mevcut platform — Faz 0-23)

| Katman | Durum | Referans |
|---|---|---|
| GitOps + cluster (D30 atomic cutover, dual k3d-test/k3d-prod) | 🟢 LIVE | ADR-0002, PLAN.md Faz 0-15 |
| MSSQL → PG ETL (canonical workcube_mikrolink, 23 master-data done) | 🟢 LIVE (16.2.P parametric DEFERRED) | PLAN.md Faz 16 |
| Notification Orchestration Platform (10-must-have D46, 7/10 done) | 🟡 7/10 must-have | ADR-0013 |
| Auth/authz (OpenFGA + permission-service + M365 SSO) | 🟢 LIVE | ADR-0021 |
| Schema discovery (319+ schema canlı) | 🟢 LIVE | schema-service `/api/v1/schema/schemas` + `/snapshot?schema=` |
| Audit + governance (audit-service, ADR-0011 BG-1) | 🟢 LIVE | ADR-0011 |
| Observability (kube-prometheus-stack + Loki/Tempo) | 🟢 LIVE | PLAN.md Faz 8 |
| Promotion pipeline (runtime-artifact ledger) | 🟢 LIVE | ADR-0023 |
| Reporting (dual-datasource MSSQL+PG) | 🟢 LIVE | ADR-0005 |

### Gap (vizyon için yeni katmanlar)

| Katman | Workcube'da | Platform'da |
|---|---|---|
| Generic workflow engine | ✓ (legacy proprietary) | ✗ (Faz 23 sadece notification) |
| Dynamic form designer + runtime | ✓ (legacy proprietary) | ✗ (mfe-reporting/mfe-shell statik) |
| MDM / Parameter management UI | ✓ (legacy proprietary, year-tenant proliferation) | ✗ (schema-service read-only snapshot) |
| AI conductor (semantic search, anomaly, summary, suggestion) | ✗ | ✗ |
| Governance/control automation (evidence ledger, policy-as-code) | ✗ | Kısmi (CI gates; ürün tarafında yok) |
| Runtime artifact promotion (form schema, process def, AI prompts) | ✗ | Kısmi (ADR-0023 image artifact ledger var) |

### Codex plan-time istişare özeti (2 iter)

**Iter-1** (thread `019e4626`): 4-katman (workflow/forms/MDM/AI) proposal'ı kabul edildi yön olarak, fakat top-level decomposition **5-plane**'e revize edildi (Governance/Control plane eksikti). Build vs buy: tüm katmanlar **custom Spring PG-only + React MFE** (Camunda 8 / Temporal / Form.io / Pimcore / Akeneo / Budibase **reddedildi** — ADR-0002 §7.1 single-host 400GB + D39 PG-only disiplini). Sequencing: ADR-0025 charter → MDM-lite + workflow-kernel paralel spike → Forms runtime v0 → vertical slice MVP → AI conductor read-only. MVP: **Purchase Requisition** (PTO değil; MDM/parameter gücü göstermeye uygun).

**Iter-2** (kullanıcı stratejik direktifi absorb): "Foundation first" yanlış frame; doğru frame **"foundation-gated differentiator first"** — AI/Governance erken başlar (Faz 25A+25B) ama actioning yetkisi foundation gate'lerinden sonra açılır. Faz 28A/28B ayrı geç faz değil, Faz 25 differentiator seed olur. Cross-AI review ürün default'u değil — sadece **yüksek riskli advisory** (>500K TRY veya risky vendor). pgvector ile başla, ayrı vector store (Qdrant/Weaviate) yasak/deferred. MVP "AI-assisted Purchase Requisition": 4 capability (Semantic Policy Lookup + Budget Rule Explain + Local Anomaly Flag + Evidence Timeline). Workcube port sırası: PTO → masraf → doküman → müşteri onboarding → fatura.

## Karar

### D50 — 5-Plane Decomposition (atomik)

Enterprise platform **kurumsal yönetim sistemi** olarak 5 plane'e ayrılır:

1. **Data / Metadata Plane** — schema-service, Workcube taxonomy (parameter/master/transaction/system-config/historical/report-only), MDM/parameter registry, lineage, source-of-truth sınıflandırması, embedding store (pgvector).
2. **Process Plane** — workflow kernel, task/inbox, approval, SLA/timer, outbox/saga. Notification (Faz 23) **bunun bir kanalıdır**, process engine'in yerine geçmez. Process orchestrator `TaskAssigned`/`ApprovalDue`/`Rejected`/`Escalated` domain event üretir → notification-orchestrator provider çağrısını yapar. Workflow doğrudan SMTP/SMS/Slack çağırmaz.
3. **Experience Plane** — MFE shell, dynamic forms runtime, admin UI, task UI, reporting.
4. **Governance / Control Plane** — OpenFGA, audit, KVKK, promotion ledger, runtime-artifact ledger (form schema + process def + AI prompts + approval policies), config/secret policy, cross-AI review (high-risk only), policy-as-code.
5. **Intelligence Plane** — AI conductor (tool registry, semantic search, document summary, anomaly suggestion, evidence-cited output, cost/eval ledger, PII/KVKK redaction guard). Evaluation/cost guard zorunlu.

Capability-list (eski 4-katman proposal'ı) yerine plane-decomposition disiplini benimsenir. Top-level mimari değişiklikleri **plane** bazında yapılır; capability'ler plane'lere mapped.

### D51 — PG-Authoritative Seal (re-affirmation)

Platform PG (PostgreSQL, single-host k3d cluster üzerinde) **authoritative SQL store**. Kullanıcı 2026-05-20: "ana SQL'imiz burada olacak". MSSQL Workcube **source-of-truth değil**; ETL source (one-way; Faz 16 canonical 23 tablo done + parametric DEFERRED).

Bu karar ADR-0002 §7.1 (Postgres-primary single-host) + D31 (PG-primary, MSSQL secondary/optional) + D39 (notification stateful = PG-only) ile uyumlu **ve charter'da mühürlenir**. Tüm yeni plane'ler (Data/Process/Experience/Governance/Intelligence) PG-only stateful disiplinini izler.

Ek stateful sistem (Mongo, Redis, RabbitMQ, Qdrant, Weaviate, OpenSearch) **YASAK** — backup/restore + DR matrisi büyür, ADR-0002 §7.1 single-host 400GB disiplinine ters. İhtiyaç olursa **ayrı ADR** gerekir (ölçülmüş latency/recall/size + backup planı + resource budget + failover etkisi + test/prod isolation).

### D52 — Workcube Non-1:1 Modernization

Workcube replacement **1:1 replikasyon DEĞİL** — modern lens ile baştan tasarım.

**Bilinçli atılacaklar** (Workcube'da var ama yeni platformda **YOK**):
- Table-per-screen CRUD mantığı (1509 tabloyu form/CRUD ekranına çevirmek YASAK)
- Year/tenant schema proliferation'ı ürün runtime modeli yapmak (319 schema crawl'ı bir defalık ETL feature; runtime model değil)
- Inline SQL/business logic dağınıklığı
- Role string / local permission drift (OpenFGA-first)
- Provider/direct integration çağrıları (workflow → notification-orchestrator → provider)
- Full low-code workflow editor'ı v0 hedefi yapmak (designer Faz 28 v1, v0 sadece render)

**Modernize edilecekler** (Workcube core kurumsal işlem, yeni lens'le port):
- Master-data (şirket/departman/proje/cost center/customer/vendor/product)
- Approval, task, audit, reporting, notification (Faz 23 reuse)
- Parameter/lookup yönetimi (versioned, approval flow)
- ERP source import + reconciliation
- Tenant boundary: `OUR_COMPANY` explicit anchor (ADR-0015) — `COMPANY` directory drift yok

**Eklenecekler** ("olmayanlar" — Workcube'da YOK, differentiator):
- AI semantic search + process suggestion
- Data quality / anomaly scoring
- Evidence-ledger native UX
- Explainable workflow/audit timeline
- Policy-as-code + OpenFGA-first authorization
- Runtime artifact promotion (form schema, process def, AI prompts)
- Human-in-the-loop AI (otomatik karar değil)
- Automated KVKK redaction pipeline
- Data lineage UI
- Multi-tenant fork/template pattern
- Cross-AI review (high-risk advisory only)
- Governance drift detection (process/form/policy artifacts)

### D53 — Foundation-Gated Differentiator (Braided Sequence)

Kullanıcı stratejisi: "olmayanlar önce + katma değer + olmazsa olmazlar + sonra mevcut". Codex iter-2: "foundation first" yanlış frame; doğru frame **"foundation-gated differentiator first"**.

Uygulama:
- AI/Governance differentiator **erken başlar** (Faz 25) — read-only assist + governance read model + artifact ledger skeleton
- Actioning yetkisi **foundation gate'lerinden sonra açılır** (Faz 29 vertical slice'ta ilk kez 5 plane birleşir)
- 5 faz tam paralel **YASAK** — coordination overhead + Java ekibi capacity + single-host 400GB constraint
- Braided: Faz 25 differentiator seed paralel keşif olabilir; production actioning paralel olamaz

### D54 — Faz Numaralandırma (Charter Lock)

PLAN.md Faz 0-23 yapısı korunur. Faz 22 (Our Company v25 transition) altına gömülmez — kapsam farklı.

| Faz | Amaç | Süre tahmini |
|---|---|---|
| **24** | **Enterprise Platform Charter (ADR-0025)** — 5-plane lock, kullanıcı stratejisi, non-goals, PG-authoritative seal, Workcube taxonomy, build/buy criteria, resource budget, 4-hafta spike acceptance | 2 hafta |
| **25** | **Differentiator Seed** — 25A AI Conductor v0 read-only + 25B Governance/Control automation v0 | 4-6 hafta |
| **26** | **Parameter Registry / MDM v0** — 5 curated entity, versioning, OpenFGA, audit | 3-4 hafta |
| **27** | **Process Kernel + Task Inbox v0** — PG-only state machine, timer, outbox, Faz 23 notification integration | 4-6 hafta |
| **28** | **Dynamic Forms Runtime v0** — no designer; JSON-schema/UI-schema render + versioned artifact promotion | 3-4 hafta |
| **29** | **AI-assisted Purchase Requisition MVP** — 5-plane vertical slice; ilk gerçek ürün kanıtı | 4-6 hafta |
| **30+** | **Workcube Modernization Port Train** — PTO → masraf → doküman → müşteri onboarding → fatura | Süreç başına 3-6 hafta |

**Vendor seçimi mühürlenmemiş**: Faz 24 spike çıktısı vendor decision criteria; production seçimi Faz 25-28 implementation sırasında ayrı ADR.

### D55 — Faz 25A AI Conductor v0 — Read-Only (Sıkı Sınır)

**İzin** (read-only assist):
- Tool registry: sadece **read tools** (schema-service query, MDM entity lookup, policy lookup, report query, audit query)
- Semantic data dictionary: schema-service snapshot + MDM entity docs + policy docs + report definitions üstünden semantic search (pgvector)
- Document/process summary: policy, vendor note, approval history özetleme
- Anomaly suggestion: **flag/suggestion only**, otomatik karar YOK
- Evidence-cited output: AI her öneride hangi tablo/policy/audit kaydına dayandığını **göstermek zorunda**
- Cost ledger: model + token + latency + user + tenant + tool-call kaydı (her çağrı)
- PII/KVKK redaction guard: prompt/context'e giden veri **sınıflandırılır + redacted**

**YASAK** (actioning):
- Workflow state değiştirme
- Approval/reject kararı verme
- Vendor/blocklist yaratma
- Policy update etme
- Notification gönderme (notification-orchestrator çağırmak)
- OpenFGA tuple yazma
- Form schema değiştirme
- MDM entry CRUD

Read-only disiplin Faz 29 vertical slice'a kadar **gevşetilmez**. Faz 29'da process kernel üzerinden kullanıcı kabul → kayıtlı action'a dönüşür (AI'nin doğrudan execute hakkı yok; çift kayıt riski).

### D56 — Faz 25B Governance/Control Automation v0

**Scope**:
- **Runtime artifact ledger** — form schema + process definition + approval policy + AI prompt/tool manifest (ADR-0023 image artifact ledger paralleli; aynı promotion contract)
- **Policy-as-code** — "bu süreçte hangi AI tool hangi veri sınıfını okuyabilir?" deklaratif (YAML/JSON-schema)
- **Evidence timeline UI/API** — kim + hangi policy version + hangi form version + hangi AI suggestion + ne karar + audit event tek timeline
- **Cross-AI review = high-risk advisory only**:
  - `< 50K TRY`: AI yok veya tek model summary
  - `50K-500K TRY`: primary model advisory + evidence citations
  - `> 500K TRY` veya risky vendor: secondary AI review **opsiyonel**, cost cap içinde
  - "İki model de onayladı" hukuki/operasyonel kabul **değildir**; insan onayı authoritative kalır
- **Budget guard** — tenant/gün/işlem başına hard cap + high-risk threshold + sampling

**YASAK**:
- Cross-AI review ürün default'u olarak her süreçte koşturmak (cost explosion)
- AI'nın policy değiştirmesi (governance plane policy authoritative; AI sadece okur)
- Insan onayı bypass eden cross-AI consensus

### D57 — Faz 29 AI-Assisted Purchase Requisition MVP (4 Capability + Dışı Liste)

**4 capability** (vanilla approval'dan ayıran differentiator):

1. **Semantic Policy Lookup** (MVP) — Kullanıcı talep oluştururken "bu kategori/tutar/vendor/cost-center için onay matrisi nedir?" sorusuna policy kaynaklı cevap. External data gerektirmez, MVP'ye girer.
2. **Budget / Approval Rule Explain** (MVP) — MDM `approval_policy` + basit `budget_limit`/`remaining_budget` (canonical/mock table) ile "neden bu onaycıya gitti?" açıklaması. Gerçek ERP entegrasyon **DEĞİL**, MVP scope dışı.
3. **Local Anomaly Flag** (sınırlı MVP) — Aynı item_category + cost_center için son N talep veya seed/sample data üzerinden "normal aralık dışı" flag. **Karar değil, uyarı**.
4. **Evidence Timeline** (MVP'nin asıl ayırt edici yanı) — Talep form version + policy version + AI suggestion + user decision + notification intent + approval/reject + audit event tek timeline'da görünür.

**MVP minimum akış**:
`Create request → AI policy/anomaly suggestion → user submits → process kernel assigns task → approver sees evidence → approve/reject → notification intent → audit/evidence timeline → report/list`

**MVP dışı** (v1 veya v2):
- Vendor risk scoring with KAP/external feeds (external data, legal, freshness, false positive)
- Gerçek budget compliance with ERP/accounting actuals (finans entegrasyon scope patlatır)
- Otomatik onay/red (kesinlikle dışı; D55 read-only sınır)
- AI'nın vendor seçmesi veya satınalma önerisi (dışı)
- Multi-step procurement/PO/invoice lifecycle (dışı)

### D58 — pgvector ile Başla (Ayrı Vector Store Yasak/Deferred)

**Karar**: AI conductor embedding store **pgvector** (PostgreSQL extension).

**Gerekçe**:
- D51 PG-authoritative + D39 PG-only çizgisiyle uyumlu
- ADR-0002 single-host 400GB altında Qdrant/Weaviate/OpenSearch ek stateful servis = backup/restore + DR matrisi büyür
- İlk AI conductor read-only; yüksek ölçekli vector search gereksinimi kanıtlanmış değil
- Metadata embedding'leri authoritative SQL governance/backup çizgisinde

**İlk pgvector scope**:
```sql
CREATE SCHEMA ai;
CREATE TABLE ai.embedding_document (
  id              uuid PRIMARY KEY,
  source_type     text NOT NULL,  -- schema/table/column/policy/form/process/audit-doc/report
  source_ref      text NOT NULL,  -- e.g. "workcube_mikrolink.HR_EMPLOYEE.employee_id" or "approval_policy:v3:pr"
  tenant_id       uuid,
  org_id          uuid,
  classification  text,            -- public/internal/restricted/pii
  embedding_model text NOT NULL,
  content_hash    text NOT NULL,   -- idempotency
  embedding       vector(1536),    -- adjust per model
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ai.embedding_chunk (
  id              uuid PRIMARY KEY,
  document_id     uuid NOT NULL REFERENCES ai.embedding_document(id),
  chunk_index     int NOT NULL,
  content         text NOT NULL,
  embedding       vector(1536) NOT NULL,
  UNIQUE (document_id, chunk_index)
);
-- HNSW/IVFFlat index ölçüm sonrası (Faz 25 spike çıktısı)
```

**Yetmezse ayrı ADR gerek**: ölçülmüş latency/recall/size + backup planı + resource budget + failover etkisi + test/prod isolation. Bu ayrı ADR yoksa pgvector **mühürlü baseline**.

### D59 — Workcube Modernization Port Train Önceliklendirme (Faz 30+)

Faz 29 MVP'den sonra ilk port sırası (kriter: hızlı browser-visible değer + foundation reuse + düşük external dependency + Workcube decommission baskısı):

1. **İzin / PTO** (Faz 30) — Hızlı kazanım, düşük entegrasyon, process/forms/task inbox doğrulaması iyi. AI tarafı sınırlı; governance + timeline pattern tekrar eder.
2. **Masraf Yönetimi** (Faz 31) — Orta karmaşıklık; receipt/attachment, limit policy, cost center, approval. AI summary/anomaly anlamlı.
3. **Doküman Onayı** (Faz 32) — AI summary + policy lookup iyi; belge storage/versioning scope netleştirilmeli.
4. **Müşteri Onboarding** (Faz 33) — Değerli ama KYC + data quality + entegrasyon + müşteri master karmaşıklığı yüksek; sonra.
5. **Fatura Workflow** (Faz 34) — En sona yakın. Regülasyon + muhasebe + OCR/e-fatura + mutabakat + entegrasyon riski yüksek.

**Sıra değiştirici faktörler**: Workcube decommission baskısı belirli bir süreçte artarsa sıra değişir (örn. müşteri onboarding'in legacy sistemi 6 ay içinde EOL ise öne alınır). Karar **case-by-case** alt-faz ADR'ı ile.

## 5-Plane Capability Map (özet)

| Plane | Faz 25-28 v0 capabilities | Faz 29 MVP'de aktif | v1+ |
|---|---|---|---|
| Data/Metadata | MDM 5-entity (Faz 26), pgvector embedding store (Faz 25A) | ✓ | Workcube taxonomy 1509-table; lineage UI; data dictionary; KVKK redaction pipeline |
| Process | Process kernel + Task inbox (Faz 27); outbox + Faz 23 notification integration | ✓ | Multi-step procurement; SLA escalation; saga compensations |
| Experience | Forms runtime v0 (Faz 28; no designer) | ✓ | Form designer; multi-step wizard; mobile MFE |
| Governance | Runtime artifact ledger + policy-as-code skeleton (Faz 25B); evidence timeline | ✓ | Drift detection product-side; cross-tenant policy templates; KVKK retention automation |
| Intelligence | AI Conductor v0 read-only (Faz 25A): semantic search + summary + anomaly flag + evidence-cited | ✓ | Multi-modal (vision/voice); tool actioning gated; LLM-as-judge eval pipeline |

## Differentiator Catalog (Faz 25 implementation scope dışı; ADR-0025 stratejik liste)

ADR-0025 charter'ında "early differentiator catalog" mühürlenir; implementation Faz 25-30+ alt-faz'larında. **Faz 25 implementation = sadece semantic dictionary + evidence timeline + read-only AI + artifact ledger skeleton**.

Geniş liste:
- Semantic data dictionary (Faz 25A)
- Evidence-ledger native UX (Faz 25B)
- Explainable workflow timeline (Faz 25B + 27)
- AI policy lookup (Faz 25A)
- AI anomaly suggestion (Faz 25A)
- Runtime artifact promotion (Faz 25B)
- Policy-as-code (Faz 25B)
- Automated KVKK redaction pipeline (Faz 25A + v1)
- Data lineage UI (v1)
- Multi-tenant fork/template pattern (v1)
- Cross-AI review for high-risk advisory only (Faz 25B)
- Governance drift detection for process/form/policy artifacts (Faz 25B + v1)

## 4-Hafta Spike Deliverable (Faz 24 Charter Acceptance Criteria)

| Hafta | Çıktı |
|---|---|
| **H1** | ADR-0025 charter draft (bu doküman) + glossary + plane decomposition + non-goals + capability map + Workcube table taxonomy sample (50-100 tablo sınıflandırma) + vendor decision criteria |
| **H2** | Workflow spike: aynı basit approval flow custom Spring PG-only kernelde tasarla; Camunda 8 + Temporal için **sadece** footprint/fit matrix çıkar (production seçimi YOK) |
| **H3** | MDM/Form substrate: 5 entity seç (`department`, `cost_center`, `vendor`, `item_category`, `approval_policy`), versioned form schema + MFE runtime mock/prototype, OpenFGA/audit contract |
| **H4** | Purchase requisition vertical smoke: submit → task assign → approve/reject → notification intent → audit row → report/list view. Çıktı: D29/D35 evidence template + resource budget + runtime-artifact ledger proposal + ADR-0025 final recommendation |

**Acceptance**:
- ADR-0025 Codex thread `019e4626` iter-3 final AGREE (cross-AI peer review)
- 5 entity MDM mock runtime browser smoke (1 entity create/read/version)
- Workflow kernel skeleton: 1 state transition + 1 outbox event PG'de
- AI conductor stub: 1 semantic search query üzerine 1 evidence-cited cevap
- Evidence timeline mock: 5-row sample sequence

## Consequences

### Pozitif

- Vizyon stratejik mühür: kullanıcı stratejisi + Codex adversarial consensus + 5-plane discipline
- Workcube replacement yön net (1:1 değil, modernize + ekle)
- AI/Governance erken sezgisi; foundation discipline ile risk yönetimi
- PG-authoritative re-affirmation; ek stateful sistem genişlemesi engeli
- Vendor lock-in yok (custom Spring + React MFE; OSS extension'lar — pgvector, JSON-schema)
- 4-tier MVP pattern (charter → seed → foundation → vertical slice → port train) Faz 23 ADR-0013 pattern'iyle uyumlu (test edilmiş)

### Negatif

- Custom Spring kernel + custom form runtime + custom MDM + custom AI conductor = **çok katmanlı custom**. Vendor avantajı (Camunda BPMN UX, Form.io designer UX) atılır. v0'ın iş analisti memnuniyeti düşük olabilir
- 6 Faz (24-29) tahmini 22-30 hafta; Faz 23 ile paralel koşmak coordination yükü
- AI cost/eval ledger discipline ürün AI cost'unu görünür kılar (avantaj) ama optimization baskısı yaratır
- Workcube user migration UX riski: yeni platform "olmayanlar" odaklıyken legacy süreç port'u Faz 30+'a kalır → kullanıcı "neden eski şeyim yok" frustrasyonu olabilir; mitigation: clear roadmap + dual-write transition

### Riskler

- **Modern Workcube tuzağı** — table-per-screen CRUD'a evrilme; non-goals discipline gerek
- **AI hallucination on production data** — D55 read-only sınır + evidence-cited + cost cap
- **MDM compound complexity** — versioning + approval + tenant boundary compound; D57 5-entity scope sınırlı
- **In-flight versioning gap** — process schema değişikliğinde eski talepler kırılır; Faz 27 design'da explicit version pinning
- **OpenFGA/authn boundary drift** — ADR-0021 invariant ("authn ≠ data grant") platform genişledikçe ihlal riski; D56 policy-as-code disiplin
- **Single-host 400GB constraint** — Faz 25-28 paralel runtime workflow engine + form runtime + AI conductor + MDM resource budget aşımı; Faz 24 H4 spike çıktısı budget tablosu zorunlu

## Alternatives (Reddedilen)

### Alt-1: 4-katman capability list (workflow/forms/MDM/AI)

**Red**: Codex iter-1 PARTIAL — capability listesi top-level mimari değil; **Governance/Control plane eksikti**. Plane-decomposition disiplini benimsendi.

### Alt-2: Vendor stack (Camunda 8 + Form.io + Pimcore + LangChain)

**Red**: Codex iter-1 — Camunda 8 (Zeebe/Operate/Tasklist/OpenSearch footprint) ADR-0002 §7.1 disiplinine ters; Form.io/Budibase/ToolJet kendi auth + stateful + plugin + lisans riski; Pimcore/Akeneo PHP/MySQL/Elastic alien stack + Workcube parametre evreni için yanlış sınıf; LangChain production control plane değil prototip aracı. Tüm katmanlar **custom Spring PG-only + React MFE**.

### Alt-3: Foundation-first (Faz 25 MDM → 26 Process → 27 Forms → 28 MVP → 29 AI)

**Red**: Kullanıcı stratejisi 2026-05-20 — "olmayanlar önce, sonra mevcut". Foundation-first AI'yi en sona koyar; "olmayan" = AI/Governance differentiator. Codex iter-2 **"foundation-gated differentiator first"** revize: AI erken başlar, actioning foundation gate'lerinden sonra.

### Alt-4: Tam paralel 5-track (25 + 26 + 27 + 28 paralel)

**Red**: Codex iter-2 — single-host 400GB + Java ekibi capacity + Faz 23 paralel coordination overhead. **Braided sequence**: 25 differentiator seed paralel keşif olabilir; production actioning paralel olamaz.

### Alt-5: Cross-AI review ürün default'u

**Red**: Codex iter-2 — cost explosion + latency. Ürün cross-AI **sadece yüksek riskli advisory** (>500K TRY veya risky vendor); insan onayı authoritative.

### Alt-6: Ayrı vector store (Qdrant/Weaviate)

**Red**: D58 — ADR-0002 single-host + D39 PG-only; backup/DR yüzeyi artar. pgvector baseline; yetmezse ayrı ADR.

### Alt-7: Faz 22 (Our Company v25 transition) altına gömme

**Red**: Codex iter-2 — Faz 22 master-data transition hattı; vizyon platform capability hattı. Kapsam ayrı; numaralandırma ayrı (Faz 24-30+).

## Non-Goals (Bilinçli Atılacaklar)

1. **Workcube 1:1 replikasyon** — 1509 tabloyu form/CRUD ekranına çevirmek YASAK
2. **Full low-code workflow editor v0** — designer Faz 28 v1; v0 sadece render
3. **AI actioning before Faz 29** — D55 read-only sınır; gevşetilmez
4. **Otomatik onay/red kararları** — insan onayı authoritative
5. **Cross-AI review default product feature** — yüksek riskli advisory only
6. **Ek stateful sistem (Mongo/Redis/RabbitMQ/Qdrant/Weaviate)** — D51 PG-only; ayrı ADR olmadan yasak
7. **Vendor lock-in** — Camunda/Form.io/Pimcore/LangChain v0 hedefi DEĞİL
8. **Year-tenant schema runtime model** — 319 schema crawl ETL feature; runtime'da tek canonical
9. **External data feed dependencies in MVP** — vendor risk KAP feed, ERP budget actuals → v1
10. **Multi-step procurement/PO/invoice lifecycle in Faz 29 MVP** — vertical slice dar tutulur

## Open Questions (Faz 24 spike sırasında cevaplanır)

- **OQ-1**: Process kernel v0 PG-only state machine — Spring State Machine library vs custom? Idempotent transition + outbox + timer + saga support için kütüphane skor.
- **OQ-2**: Forms runtime — JSON-Forms (Eclipse) vs RJSF (Mozilla) vs custom JSON-schema renderer? React MFE + Tailwind + i18n + accessibility için.
- **OQ-3**: AI conductor LLM provider — Anthropic Claude API + MCP-style tool registry vs OpenAI Assistants vs Bedrock? Cross-AI review için secondary model seçimi (Codex/GPT primary vs Claude vs Gemini)? Cost cap policy.
- **OQ-4**: pgvector embedding model — `text-embedding-3-small` (1536-dim) vs `voyage-multilingual-2` (Turkish coverage) vs OpenAI `text-embedding-3-large`? Spike: 5 entity sample + Turkish content + recall@10.
- **OQ-5**: Faz 23 notification ile process kernel outbox entegrasyonu — domain event (`TaskAssigned`/`ApprovalDue`) shape; ADR-0013 D38 outbox pattern reuse mu, ayrı outbox mu?
- **OQ-6**: Runtime artifact ledger schema — ADR-0023 image artifact ledger schema (`promotion.artifact_ledger`) extend mi, ayrı `governance.artifact_ledger` mi?
- **OQ-7**: Workcube decommission timeline — bir Workcube süreç EOL deadline'ı varsa Faz 30+ port sırası nasıl ayarlanır?
- **OQ-8**: Multi-tenant fork pattern — tenant başına process/form/policy template override nasıl modellenir? Faz 26 MDM v0'da scope mu, v1+ mı?

## References

### Internal

- [PLAN.md](../../PLAN.md) — D-decision register (D50-D59 bu ADR'da)
- [ADR-0002](./0002-single-host-dual-cluster.md) — §7.1 PG-primary single-host
- [ADR-0013](./0013-notification-orchestration.md) — Faz 23 notification orchestration (process plane pattern)
- [ADR-0015](./0015-our-company-v25-transition.md) — Our Company v25 transition
- [ADR-0021](./0021-m365-sso-broker-keycloak.md) — M365 SSO + authn-data boundary
- [ADR-0023](./0023-promotion-pipeline-test-overlay-authoritative.md) — Runtime-artifact ledger pattern
- [CLAUDE.md](../../CLAUDE.md) — Repo-spezifik kurallar (D17 deprecated, scale-to-zero YASAK)

### External Codex iterations

- Thread `019e4626-1c05-7c60-840a-c6b42a35e946` — Vision adversarial review (iter-1 + iter-2 absorb)
- Thread `019e4629-7c65-7b63-98b3-2d1f9f9e0880` — PR #906 ratify (paralel; AGREE)

### Workcube source

- `docs/migration/workcube-schema.json` — 1509 tablo / 26240 kolon / 1774 FK canonical snapshot
- `docs/migration/mssql-inventory.md` — 40 tablo ETL allowlist
- schema-service `/api/v1/schema/schemas` + `/api/v1/schema/snapshot?schema=`

---

**Final ADR-0025 acceptance**: Codex thread `019e4626` iter-3 final AGREE + cross-AI peer review (HARD RULE — sağlayıcı farklılığı). Kabul sonrası Status → **Accepted**, PLAN.md Faz 24-30+ stub'ları eklenir, board issue umbrella'ları açılır.
