# STYLE-DATA-001 – SQL / ETL / Data Pipeline Kodlama Stili (Compact)

Bu doküman, data katmanında yazılan SQL sorguları, view’lar, ETL job’ları,
incremental yükler ve pipeline kodları için zorunlu stil kurallarını tanımlar.
Amaç: Performanslı, güvenli, okunabilir ve bakım kolaylığı sağlayan bir standart
oluşturmaktır.

-------------------------------------------------------------------------------
1. SQL GENEL KURALLARI
-------------------------------------------------------------------------------

- SELECT * yasaktır. Her zaman gerekli kolonlar seçilir.
- Karmaşık sorgular CTE (WITH) ile bölünmeli; tek parça 300 satırlık SQL yasaktır.
- Tarih filtreleri:
  start <= x < end formatında yazılır. BETWEEN dikkatle kullanılır.
- WHERE filtreleri index-friendly yazılmalıdır.
- Gereksiz DISTINCT kullanılmaz; modelleme hatasını gizlemek için DISTINCT yasaktır.
- JOIN kuralları:
  - Önce filtre, sonra join yapılabilir.
  - NULL safe join mantığı açık belirtilmelidir.
- Aggregation:
  - COUNT(*) yerine COUNT(1) tercih edilir.
  - SUM(NULL) → COALESCE ile yönetilir.
- NULL handling:
  - COALESCE, IS NULL, IS NOT NULL açık kullanılmalıdır.
- ORDER BY yalnızca UI veya paging gerektiriyorsa kullanılmalıdır.

-------------------------------------------------------------------------------
2. VIEW STANDARTLARI
-------------------------------------------------------------------------------

- İsimlendirme:
  vw_<domain>_<purpose>.sql  
  mv_<domain>_<purpose>.sql  (materialized view)
- View’lar:
  - business logic içermez,
  - sadece data hazırlama/join/temizleme yapar.
- View içinde kompleks hesaplamalar değil, staging/transform aşamaları kullanılır.
- Materialized view’lar yazma sıklığı az, okuma sıklığı çok olan modeller için tercih edilir.

-------------------------------------------------------------------------------
3. RAPOR SQL KURALLARI
-------------------------------------------------------------------------------

- Rapor SQL’leri adım adım CTE yapısına bölünür:
  source → filtered → joined → enriched → final
- Tüm domain mantığı PRD ve business-rules dokümanına uygun olmalıdır.
- Büyük datasetlerde LIMIT kullanımı geçici debugging içindir; final sorguda olmaz.
- Raporlar:
  - soft delete (is_deleted) işaretini dikkate almalıdır.
  - para/kdv hesaplarında yuvarlama stratejisi açıkça belirtilmelidir.

-------------------------------------------------------------------------------
4. ETL / PIPELINE STANDARTLARI
-------------------------------------------------------------------------------

- ETL job’ları extract → transform → load adımlarına ayrılır.
- Kod yapısı:
  pipelines/<frequency>/<job>.py  
  incremental/<table>.py  
  full-load/<table>.py  
- Config hard-coded olmamalıdır; ayrı config dosyasından okunmalıdır.
- Exception:
  - ETL job’larında exception swallow yasaktır.
  - Tüm hatalar loglanmalı ve stop/continue stratejisi net olmalıdır.
- Logging:
  - her adımda “start + finish + row count” loglanmalıdır.

-------------------------------------------------------------------------------
5. INCREMENTAL LOAD KURALI
-------------------------------------------------------------------------------

- Incremental yüklemeler her zaman tek bir referans kolona dayanır:
  - last_update_date  
  - updated_at  
  - id aralığı (sadece append-only tablolarda)
- Overlap (bindirme) stratejisi önerilir:
  - Son 1 dakika / son 1 saat / son 1 gün veri tekrar okunabilir.
- Deleted row strategy:
  - soft delete varsa (is_deleted), incremental view’ler bu bayrağı her zaman
    filtrelemelidir.
  - hard delete varsa, ETL job’ı “not exists” kontrolü yapmalıdır.

-------------------------------------------------------------------------------
6. DATA MODELLEME KURALLARI
-------------------------------------------------------------------------------

- models/ altında tablo ve şema dokümanları bulunur.
- Her kolon için:
  - tip,
  - null policy,
  - default,
  - açıklama,
  - index bilgisi yazılır.
- Primary key net olmalıdır; composite key gerekmedikçe önerilmez.
- Foreign key ilişkileri business domain’e uygun şekilde modellenmelidir.

-------------------------------------------------------------------------------
7. PERFORMANS KURALLARI
-------------------------------------------------------------------------------

- Büyük tablolarda gereksiz ORDER BY yasaktır.
- JOIN sırası veri hacmine göre belirlenmelidir (small → big).
- Filtreler mümkünse JOIN’den önce uygulanmalıdır.
- COUNT DISTINCT gibi ağır işlemler gerekiyorsa:
  - pre-aggregation tablosu
  - materialized view  
  düşünülmelidir.
- Gereksiz CAST kullanımı yasaktır.

-------------------------------------------------------------------------------
8. TEST STANDARTLARI
-------------------------------------------------------------------------------

- SQL testleri test_<name>.sql olarak yazılır.
- Pipeline testleri:
  - küçük sample input + expected output karşılaştırması içerir.
- Testlerde kontrol edilmesi gerekenler:
  - row count,
  - null logic,
  - join integrity,
  - date filter correctness,
  - duplicate row detection.

-------------------------------------------------------------------------------
9. AGENT DAVRANIŞ REHBERİ
-------------------------------------------------------------------------------

[DATA] görevinde agent:

1. AGENT-CODEX.core.md  
2. DATA-PROJECT-LAYOUT.md  
3. STYLE-DATA-001.md  
4. İlgili DATA-MODEL, TECH-DESIGN, ADR dokümanlarını  
okur ve aşağıdaki formatta cevap verir:

- Keşif Özeti  
  - etkilenen tablo/view/pipeline  
  - mevcut sorun (performans, yanlış sonuç, karmaşa vs.)

- Data Tasarımı  
  - CTE yapısı, filtre mantığı, join modeli  
  - incremental/full load stratejisi  

- Uygulama Adımları  
  - dosya yolu + yapılacak değişiklik

-------------------------------------------------------------------------------
10. ÖZET
-------------------------------------------------------------------------------

Bu dosya:
- SQL standardını,
- ETL/pipeline kurallarını,
- data modelleme ilkelerini,
- test ve performans rehberlerini

compact ama net bir şekilde tanımlar.
Data işlerinde agent ve ekipler için tek doğruluk kaynağıdır.