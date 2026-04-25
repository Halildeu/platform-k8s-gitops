# DATA-PROJECT-LAYOUT

Bu doküman, `data/` klasörü altındaki SQL, rapor, view, ETL ve data-pipeline
geliştirmeleri için klasör yapısını ve mimari düzeni tanımlar. Amaç: data
tarafında tek tip, okunabilir ve sürdürülebilir bir yapı oluşturmak; agent’ın
data görevlerinde doğru klasöre dokunmasını sağlamaktır.

-------------------------------------------------------------------------------
1. ÜST DÜZEY DİZİN YAPISI
-------------------------------------------------------------------------------

data/
 ├── sql/                  → View'lar, rapor sorguları, transform adımları
 ├── views/                → Tekil veya birleşik view tanımları (read-only layer)
 ├── models/               → Veri modeli tanımları (tablo yapıları, şema dokümanları)
 ├── pipelines/            → ETL / batch pipeline adımları
 ├── incremental/          → Incremental yükleme scriptleri
 ├── full-load/            → Full refresh yükleme scriptleri
 ├── transforms/           → Dönüşüm logic’i (temizleme, normalizasyon)
 ├── scripts/              → Operasyon scriptleri (cron, scheduler, helper)
 ├── tests/                → SQL + pipeline testleri
 └── docs/                 → Model, lineage, data dictionary dökümanları

-------------------------------------------------------------------------------
2. SQL KATMANI (sql/)
-------------------------------------------------------------------------------

Bu klasör saf SQL logic’i içerir:

sql/
  report_<name>.sql
  view_<name>.sql
  join_<name>_transform.sql
  common_filters.sql

Kurallar:
- SELECT * yasaktır; gerekli sütunlar seçilir.
- Karmaşık sorgular CTE (WITH) ile bölünür.
- Filtre ve join sırası index-friendly olacak şekilde tasarlanır.
- Tüm rapor SQL’leri isimlendirme standardına uyar:
  report_<domain>_<purpose>.sql

-------------------------------------------------------------------------------
3. VIEWS KATMANI (views/)
-------------------------------------------------------------------------------

views/
  vw_<name>.sql
  mv_<name>.sql  (materialized view)

Kurallar:
- View’lar backend ve BI ekiplerinin ortak okuma katmanıdır.
- İsimlendirme:
  vw_ → normal view
  mv_ → materialized view
- View mantığı business logic içermez; sadece data hazırlama / join layer’dır.

-------------------------------------------------------------------------------
4. DATA MODELS (models/)
-------------------------------------------------------------------------------

models/
  <table>.schema.md
  <table>.lineage.md

İçerik:
- Tablo kolonları, tipler, null policy
- Primary key, foreign key
- Index yapıları
- Lineage: Hangi kaynaktan besleniyor?

Bu dosyalar, backend modelleri ile tutarlı olmalıdır.

-------------------------------------------------------------------------------
5. PIPELINES (pipelines/)
-------------------------------------------------------------------------------

pipelines/
  daily/
    load_<table>.py
    refresh_<model>.py
  hourly/
    load_<events>.py
  realtime/
    stream_consumer.py

Kurallar:
- Her pipeline tek sorumluluk içerir.
- Pipeline adımları:
  extract → transform → load
- Pipeline config sabit kodlanmaz; ayrı config dosyasında tanımlanır.
- Tekil job’lar bağımsız test edilebilir olmalıdır.

-------------------------------------------------------------------------------
6. INCREMENTAL YÜKLEME (incremental/)
-------------------------------------------------------------------------------

incremental/
  inc_<table>.sql
  inc_<table>.py

Kurallar:
- Incremental strateji:
  - last_update_date, updated_at veya id aralıklarına göre yapılır.
- Silinen kayıtlar:
  - soft delete (is_deleted) varsa tüm sorgular bunu dikkate alır.
- Overlap (bindirme) kullanımı önerilir:
  - Son 1 dk / son 1 gün veri tekrar okunabilir.

-------------------------------------------------------------------------------
7. FULL LOAD (full-load/)
-------------------------------------------------------------------------------

full-load/
  full_<table>.sql
  full_<table>.py

Kurallar:
- Büyük tablolarda paralel okuma yapılabilir.
- Full load’lar çoğunlukla nightly veya maintenance window’da koşturulur.

-------------------------------------------------------------------------------
8. TRANSFORMS (transforms/)
-------------------------------------------------------------------------------

transforms/
  clean_<domain>.sql
  normalize_<domain>.sql
  enrich_<domain>.sql

Bu klasör data quality ve business cleaning logic'leri içerir.

-------------------------------------------------------------------------------
9. TEST STANDARTI (tests/)
-------------------------------------------------------------------------------

tests/
  test_<view>.sql
  test_<pipeline>.py

Kurallar:
- Kritik view’lar için test SQL’i zorunludur.
- Pipeline testleri:
  - küçük sample dataset + expected output karşılaştırması
- Null handling, join quality ve row count doğrulaması yapılmalıdır.

-------------------------------------------------------------------------------
10. DOKÜMANTASYON (docs/)
-------------------------------------------------------------------------------

docs/
  dictionary.md       → data sözlüğü (her kolonun anlamı)
  lineage.md          → data akışı
  constraints.md      → iş kuralları + veri kuralları
  business-rules.md   → rapor hesabı formülleri

Bu dokümanlar data mühendisliği → backend → raporlama ekipleri arasında
ortak dil sağlar.

-------------------------------------------------------------------------------
11. AGENT DAVRANIŞ REHBERİ
-------------------------------------------------------------------------------

[DATA] görevinde agent:

1. AGENT-CODEX.core.md ve AGENTS.md’yi dikkate alır.
2. Önce DATA-PROJECT-LAYOUT.md (bu dosya) ile doğru klasörü belirler.
3. STYLE-DATA-001.md’ye göre SQL/ETL tasarım kurallarını uygular.
4. Eğer ilgili domain bir backend servisi içeriyorsa:
   - DATA-MODEL
   - TECH-DESIGN
   - ADR  
   dokümanlarını okur.
5. Sonra üçlü formatta cevap verir:
   - Keşif Özeti
   - Data Tasarımı
   - Uygulama Adımları (dosya yolu + yapılacak değişiklik)

-------------------------------------------------------------------------------
12. ÖZET
-------------------------------------------------------------------------------

Bu layout dokümanı:
- data klasör yapısını,
- SQL/view/pipeline yerleşimini,
- incremental/full-load ayrımını,
- cleaning/transforms katmanlarını,
- test & documentation yaklaşımını

tek ve tutarlı bir standart olarak tanımlar.
Agent ve ekipler için referans mimari kaynağıdır.