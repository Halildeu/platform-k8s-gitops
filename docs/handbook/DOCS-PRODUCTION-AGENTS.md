# DOCS-PRODUCTION – Direct-Gen Doküman Üretim Akışı (Agent Rolleri) v0.1

Bu doküman, **doküman üretim akışını** (BM → BENCH → TRACE → Delivery Pack) agent rolleriyle
standartlaştırır. `PROJECT-FLOW` tablosu bu dokümanın konusu değildir.

## 1. SSOT Referansları

- Üretim kontratı: `docs/03-delivery/SPECS/SPEC-0012-m3-direct-gen-production-system-v1.md`
- Template map: `docs-ssot/00-handbook/DOC-TEMPLATE-MAP-SSOT.json`
- Şablonlar: `docs/99-templates/*.template.md`

## 2. Üretim Kontratı (Girdi → Çıktı)

### 2.1 Girdiler (minimum)

- Topic (konu):
  - Topic klasörü: `docs/01-product/BUSINESS-MASTERS/<TOPIC>/` (canonical: UPPERCASE)
  - Topic slug: `kebab-case` (örn. `ethics`)
- ID seti (kural: aynı konu için tutarlı ve benzersiz):
  - BM pack: `BM-0001`
  - BENCH pack: `BENCH-0001`
  - TRACE: `TRACE-0001`
  - PB/PRD: `PB-0004`, `PRD-0004`
  - Delivery: `SPEC-00XX`, `STORY-0XXX`, `AC-0XXX`, `TP-0XXX`

Not: ID üretimi bu dokümanın kapsamı değildir; ID standardı için `NUMARALANDIRMA-STANDARDI.md` ve
repo’daki mevcut ID registry/kurallar referans alınır.

### 2.2 Çıktılar (minimum)

Bu üretim hattı aşağıdaki seti hedefler (SSOT: SPEC-0012):

- BM Pack:
  - `docs/01-product/BUSINESS-MASTERS/<TOPIC>/BM-0001-<topic>-core-*.md`
  - `docs/01-product/BUSINESS-MASTERS/<TOPIC>/BM-0001-<topic>-controls-*.md`
  - `docs/01-product/BUSINESS-MASTERS/<TOPIC>/BM-0001-<topic>-metrics-*.md`
- BENCH Pack:
  - `docs/01-product/BENCHMARKS/<TOPIC>/BENCH-0001-<topic>-capability-matrix.md`
  - `docs/01-product/BENCHMARKS/<TOPIC>/BENCH-0001-<topic>-gaps-trends-ai.md`
- TRACE Pack:
  - `docs/03-delivery/TRACES/TRACE-0001-<topic>-bm-to-delivery.tsv`
- Delivery Pack (minimum):
  - `docs/01-product/PROBLEM-BRIEFS/PB-0004-<topic>-*.md`
  - `docs/01-product/PRD/PRD-0004-<topic>-*.md`
  - `docs/03-delivery/SPECS/SPEC-00XX-<topic>-*.md`
  - `docs/03-delivery/STORIES/STORY-0XXX-<topic>-*.md`
  - `docs/03-delivery/ACCEPTANCE/AC-0XXX-<topic>-*.md`
  - `docs/03-delivery/TEST-PLANS/TP-0XXX-<topic>-*.md`
- Operations Pack (koşullu ama önerilen):
  - `docs/04-operations/RUNBOOKS/RB-<servis>.md`

## 3. Agent Rolleri (MVP)

Bu bölümdeki roller, aynı işin farklı parçalarını **ayrı sorumluluklarla** üretir. Her rol:
- kendi çıktısını “tamamlanmış” saymak için net bir Done kriterine sahiptir,
- bir sonraki role deterministik girdi bırakır.

### 3.1 DP-01 – Intake & Scoping Agent

Amaç: konuyu netleştirir ve üretim sınırlarını kilitler.

- Okur:
  - `docs/03-delivery/SPECS/SPEC-0012-m3-direct-gen-production-system-v1.md`
  - (varsa) ilgili PB/PRD/SPEC/STORY seti
- Yazar (çıktı):
  - “Topic + ID seti + scope/out-of-scope” kararı (PB/PRD/SPEC için upstream notu)
- Done:
  - Topic klasörü ve ID seti net; “kapsam dışı” maddeleri yazılı.

### 3.2 DP-02 – BM Pack Agent

Amaç: BM karar/guardrail/ölçüm sinyallerini **ID’li** şekilde üretir.

- Okur: DP-01 çıktısı + domain bağlamı
- Yazar:
  - BM core/controls/metrics dokümanları (pack bütünlüğü)
  - (Opsiyonel) Hızlı başlangıç generator:
    - `python3 scripts/doc_production_generate.py bm-pack --topic <TOPIC> --slug <slug> --bm <0001> --title "<Başlık>"`
- Done:
  - Her BM maddesi ID’li (DEC/GRD/KPI/RSK/ASM/VAL) ve “Top 10 sürpriz önleyici” dolu.

### 3.3 DP-03 – BENCH Pack Agent

Amaç: capability matrix + trend/gap/AI yapılabilirlik çıktısını üretir.

- Okur: BM pack (minimum) + mevcut ürün/mimari bağlam
- Yazar:
  - BENCH capability matrix
  - BENCH gaps/trends/AI
  - (Opsiyonel) Hızlı başlangıç generator:
    - `python3 scripts/doc_production_generate.py bench-pack --topic <TOPIC> --slug <slug> --bench <0001> --title "<Başlık>"`
- Done:
  - En az 3–7 trend + net gap listesi (her gap: etki + risk + öneri).

### 3.4 DP-04 – TRACE Pack Agent

Amaç: BM item’ları delivery hedeflerine izlenebilir şekilde bağlar.

- Okur: BM + BENCH + Delivery hedef ID seti
- Yazar:
  - TRACE TSV (header + mapping_quality dahil)
  - (Opsiyonel) Hızlı başlangıç generator:
    - `python3 scripts/doc_production_generate.py trace-pack --topic <TOPIC> --slug <slug> --trace <0001> --bm <0001> --default-target-type PRD --default-target-id PRD-0004`
- Done:
  - `BM_ITEM_ID` → `TARGET_TYPE/TARGET_ID` bağlantıları mevcut; “coarse/refined” seçimi tutarlı.

### 3.5 DP-05 – Delivery Pack Agent

Amaç: PB/PRD/SPEC/STORY/AC/TP setini template’lere göre üretir ve zinciri bağlar.

- Okur: TRACE + BM/BENCH özetleri
- Yazar:
  - PB/PRD (Discover/Shape)
  - SPEC (kontrat/SSOT)
  - STORY/AC/TP (delivery zinciri)
  - (koşullu) ADR/RUNBOOK
  - (Opsiyonel) Hızlı başlangıç generator:
    - `python3 scripts/doc_production_generate.py delivery-pack --topic <TOPIC> --slug <slug> --pb <0004> --prd <0004> --spec <0013> --story <0306> --trace <0001> --trace-slug <ethics> --owner @team/platform --risk-level medium --title "<Başlık>" --dry-run`
- Done:
  - STORY “LİNKLER” bölümü zinciri doğru path’lerle bağlıyor.
  - TP, risk seviyesine göre subset/strict kurallarıyla uyumlu.

### 3.6 DP-06 – Doc-QA & Repair Agent

Amaç: kalite gate’lerini koşar, ihlali raporlar ve deterministik repair uygular.

- Okur: tüm üretilen doküman seti
- Çalıştırır (default):
  - `python3 scripts/run_doc_qa_execution_log_local.py --out-dir .autopilot-tmp/execution-log`
- Done:
  - Gate PASS ve evidence pointer seti mevcut (`.autopilot-tmp/execution-log/`).

## 4. Orkestrasyon (BM → BENCH → TRACE → Delivery)

Önerilen sıra:

1) DP-01 (Intake) → Topic + ID seti + scope kilitle
2) DP-02 (BM Pack) → karar/guardrail/ölçüm (ID’li)
3) DP-03 (BENCH Pack) → matrix + gaps/trends/AI
4) DP-04 (TRACE Pack) → BM item → hedef mapping
5) DP-05 (Delivery Pack) → PB/PRD/SPEC/STORY/AC/TP
6) DP-06 (Doc-QA) → gate + deterministik repair

### 4.1 Tek komut (Default tam set)

Bu repo’da “uçtan uca doküman zinciri üret” komutu şu seti üretir:
- BM Pack (3 dosya)
- BENCH Pack (2 dosya)
- TRACE Pack (1 dosya, `.tsv`)
- Delivery Pack (6 dosya: PB/PRD/SPEC/STORY/AC/TP)
- Runbook (1 dosya: `RB-*`, varsayılan açık)
- Auto-Optional Pack (koşullu; sinyal varsa):
  - ADR (`ADR-*`)
  - TECH-DESIGN (`TECH-DESIGN-*`)
  - GUIDE (`GUIDE-*`)
  - INTERFACE-CONTRACT (`INTERFACE-CONTRACT-*`)
  - DATA-CARD (`DATA-CARD-*`)
  - MODEL-CARD (`MODEL-CARD-*`)

Generator (tek komut):

- `python3 scripts/doc_production_generate.py e2e-pack --topic <TOPIC> --delivery-slug <slug> --bm <0001> --bench <0001> --trace <0001> --pb <0004> --prd <0004> --spec <0013> --story <0306> --owner @team/platform --risk-level medium --dry-run`
- Runbook üretimini kapatmak için: `--no-runbook`
- Auto-optional üretimi kapatmak için: `--no-auto-optional`
- Mevcut zincirde yalnız auto-optional üretmek için: `--only-auto-optional` (BM/BENCH/TRACE/Delivery yazmaz)

### 4.2 Auto-Optional (Sinyal Sözleşmesi)

Amaç: Bazı şablonlar her işte zorunlu değildir; yalnız “gerektiğinde” üretilir. Bu ihtiyaç
deterministik bir sinyalle ifade edilir (LLM tahmini yok).

Sinyal kaynakları:

1) **STORY meta `Downstream:`**
   - Format: `Downstream: AC-0XXX, TP-0XXX, <opsiyonel-tokenler>`
   - Desteklenen token örnekleri:
     - `ADR-0003` veya `ADR-0003-<kebab-slug>`
     - `TECH-DESIGN` veya (paylaşımlı tasarım için) `TECH-DESIGN=<kebab-slug>`
     - `GUIDE` (ID otomatik seçilir) veya `GUIDE-0001` / `GUIDE-0001-<kebab-slug>`
     - `INTERFACE-CONTRACT` veya (çoklu/paylaşımlı kontrat için) `INTERFACE-CONTRACT=<kebab-slug>`
     - `DATA-CARD` veya `DATA-CARD=<kebab-slug>`
     - `MODEL-CARD` veya `MODEL-CARD=<kebab-slug>`
   - Service-scoped dokümanlar için opsiyonel service sinyali:
     - `svc=<service>` veya `service=<service>` (kebab-case)

2) **Seed JSON (`--seed`)**
   - `optional.generate`: yukarıdaki token’ların listesi
   - `optional.service`: service-scoped dokümanlar için `docs/02-architecture/services/<service>/` klasör adı

Önemli kurallar:
- ADR ve TECH-DESIGN “service-scoped” olduğu için `optional.service` (veya `Downstream: svc=<service>`) olmadan üretim hataya düşer.
- GUIDE token’ı ID içermiyorsa generator mevcut guide’ları tarar ve bir sonraki `GUIDE-XXXX` numarasını seçer.

Auto-optional çıktılarının kanonik yolları:
- ADR: `docs/02-architecture/services/<service>/ADR/ADR-0001-*.md`
- TECH-DESIGN: `docs/02-architecture/services/<service>/TECH-DESIGN-<delivery-slug>.md`
- GUIDE: `docs/03-delivery/guides/<delivery-slug>/GUIDE-0001-*.md`
- INTERFACE-CONTRACT: `docs/03-delivery/INTERFACE-CONTRACTS/INTERFACE-CONTRACT-<delivery-slug>.md`
- DATA-CARD: `docs/05-ml-ai/DATA-CARDS/DATA-CARD-<delivery-slug>.md`
- MODEL-CARD: `docs/05-ml-ai/MODEL-CARDS/MODEL-CARD-<delivery-slug>.md`

### 4.3 Ürün Odaklı Çoklu Story (PRD Delivery Items SSOT)

Amaç: “kaç STORY olacak?” kararını LLM tahminiyle değil, **PRD içindeki deterministik SSOT** ile vermek.

SSOT kaynağı:
- PRD içinde `10. DELIVERY ITEMS (SSOT)` bölümündeki JSON (`ssot=PRD_DELIVERY_ITEMS_V1`).

Kural seti:
- Default: `1 delivery_item -> 1 STORY` (vertical slice).
- `split_by=stream` verilirse: `streams` başına STORY üretilir (örn. `web/backend/mobile`).
- Paylaşımlı doküman bağlama yok: her STORY kendi slug’ı ile kendi setini üretir (gerekliyse).

JSON alanları (minimum):
- `id`, `title`, `slug` (kebab-case)
- `split_by`: `none|stream`
- `streams`: `split_by=stream` için dolu olmalı
- `services`: (opsiyonel) `svc=<service>` sinyali için; ADR/TECH-DESIGN üretiminde gerekir
- `optional_docs`: (opsiyonel) `ADR|TECH-DESIGN|GUIDE|INTERFACE-CONTRACT|DATA-CARD|MODEL-CARD`

Opsiyonel deterministik alanlar:
- `story_id`: `0306` gibi 4 hane (item tek story ise)
- `story_ids`: `{ "web": "0310", "backend": "0311" }` (stream split varsa)
- `spec`: `0013` veya `SPEC-0013` (item bazlı SPEC override)
- `risk_level`: `low|medium|high` (item bazlı override)

İdempotency / drift kuralı:
- İlk üretimden sonra `story_id` / `story_ids` pinlenmelidir (SSOT stabilitesi için).
- Generator, `story_id/story_ids` yoksa önce slug’dan mevcut dosyayı arar: `STORY-????-<story-slug>.md`.
  - Bulursa aynı ID’yi reuse eder (idempotent).
  - Bulamazsa yeni STORY ID allocate eder (duplicate riski).
- `slug` değişirse arama eşleşmeyebilir → duplicate STORY üretimini engellemek için pinleme zorunludur.

Generator:
- `python3 scripts/doc_production_generate.py delivery-items-pack --prd <0004> --spec <0013> --dry-run`
- PB otomatik bulunur (PRD meta `Problem Brief:` satırından); istersen override: `--pb <0004>`
- STORY ID otomatik seçilir; istersen başlangıç: `--story-start <0310>`

Çıktılar (her story için):
- `docs/03-delivery/STORIES/STORY-0XXX-<story-slug>.md`
- `docs/03-delivery/ACCEPTANCE/AC-0XXX-<story-slug>.md`
- `docs/03-delivery/TEST-PLANS/TP-0XXX-<story-slug>.md`
- (koşullu) Auto-Optional seti (ADR/GUIDE ID otomatik, diğerleri story slug ile)

## 5. Guardrails (üretim kalitesi)

- Varsayım uydurulmaz: bilinmeyenler “açık soru” + doğrulama planı olarak yazılır (hard gate olan dokümanlarda `TBD` token’ı kullanılmaz).
- Dokümanlar canonical klasörlerinden taşınmaz (lokasyon/routing gate’leri kırılır).
- Şablon başlıkları korunur; agent sadece başlık altını doldurur.
- İzlenebilirlik: BM_ITEM_ID → TRACE → Delivery hedefleri zinciri korunur.
