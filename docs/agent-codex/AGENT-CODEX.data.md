# Data / Rapor / ETL Görevleri (Compact)

> Transition Durumu: Bu dosya transition-active rehber katmanındadır.
> Canonical kaynaklar:
> `standards.lock`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`,
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`.

Bu dosya, [DATA] tipindeki görevlerde agent’ın nasıl davranacağını tanımlar.
Amaç: SQL, rapor, ETL ve data-pipeline işlerinde tutarlı, performanslı ve güvenli
bir yaklaşım sağlamaktır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Data odaklı işlerde (SQL view, rapor sorgusu, ETL job, data mart, pipeline)
  ortak bir standart belirlemek.
- Gereksiz karmaşayı ve performans problemlerini azaltmak.
- Backend servis kodu ile data katmanının sınırlarını netleştirmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

[DATA] tipi aşağıdaki işleri kapsar:

- Yeni rapor SQL’i yazma veya mevcut sorguyu refaktör etme
- View / materialized view tasarımı
- ETL job / batch pipeline tasarımı (incremental/full load)
- Data mart tablosu tasarımı
- Büyük data işlemlerinde performans optimizasyonu

Eğer iş hem backend API hem data sorgusu içeriyorsa:
- Data ve backend transition rehberleri birlikte uygulanmalıdır.

-------------------------------------------------------------------------------
3. ZORUNLU OKUMA
-------------------------------------------------------------------------------

[DATA] işi alındığında agent aşağıdaki dokümanları dikkate almalıdır:

1. ÇEKİRDEK DAVRANIŞ
   - Çekirdek transition rehberi
   - AGENTS.md

2. DATA LAYOUT
   - DATA-PROJECT-LAYOUT.md

3. DATA STİL
   - STYLE-DATA-001.md

4. İLGİLİ DOMAIN / SERVİS DOKÜMANLARI
   - docs/02-architecture/services/<servis-adı>/DATA-MODEL-*.md
   - docs/02-architecture/services/<servis-adı>/TECH-DESIGN-*.md
   - docs/02-architecture/services/<servis-adı>/ADR/ADR-*.md

5. ÜRÜN / RAPOR DOKÜMANLARI (VARSA)
   - docs/01-product/PRD/PRD-*.md (özellikle raporlar için)
   - docs/03-delivery/STORIES/STORY-*.md (rapor story’leri)

6. KALİTE VE DATA-PIPELINE KONTROLLERİ

Data sorgusu veya pipeline değiştiren her [DATA] işinde agent, mümkünse
aşağıdaki script’leri kullanarak otomatik kalite kontrol çalıştırmalıdır:

- SQL stil kontrolleri:
  - `python3 scripts/check_data_sql_style.py`
- Pipeline exception / swallow kontrolleri:
  - `python3 scripts/check_data_pipelines.py`
- SQL + pipeline birlikte:
  - `python3 scripts/check_data_all.py`

Bu script’ler, STYLE-DATA-001 ve DATA-PROJECT-LAYOUT’daki kuralları
otomatik olarak kontrol etmeye yardımcı olur; nihai yorum ve düzeltme
her zaman data ekibi + agent işbirliğiyle yapılır.

-------------------------------------------------------------------------------
4. ÇALIŞMA MODELİ
-------------------------------------------------------------------------------

Agent [DATA] görevinde şu adımları izler:

1. Keşif
   - Hangi tablo / view / pipeline etkileniyor?
   - Amaç: performans (hız), doğruluk (sonuç), kapsam (filtre/sütun) nedir?
   - Mevcut sorgu/pipeline varsa yapısını inceler:
     - kaç join?
     - hangi filtreler?
     - index alanları nasıl kullanılmış?

2. Tasarım
   - Veri kaynağı: hangi tablolar, hangi ilişkiler?
   - Sorgu yapısı:
     - Mümkünse CTE (WITH) ile bölünmüş, adım adım okunabilir yapı önerilir.
     - Index-friendly filtre: range/date filtrelerinde >= AND < kullanımı.
     - SELECT * yerine sadece gerekli sütunlar.
   - Performans:
     - Gereksiz DISTINCT, ORDER BY, GROUP BY kullanımından kaçınma.
     - Filtreler join’den önce uygulanabiliyorsa o şekilde düzenleme.
   - ETL / pipeline varsa:
     - Full load mı incremental mi?
     - Incremental ise hangi kolon (update_date, id, batch_id) esas alınacak?
     - Silinen kayıt yönetimi (soft delete / hard delete stratejisi).

3. Uygulama Adımları
   - Her adım sadece “dosya yolu + yapılacak değişiklik” formatında yazılır.
   - Örnek format:
     - data/sql/views/GET_ACTION_MONEY.sql → CTE yapısına böl, date filtresini >= AND < şeklinde güncelle.
     - data/pipelines/incremental/load_accounts.py → incremental filtreyi last_update_date’e göre düzenle.
     - docs/02-architecture/services/account/DATA-MODEL-account.md → yeni kolonu dokümana ekle.

-------------------------------------------------------------------------------
5. CEVAP FORMATİ
-------------------------------------------------------------------------------

[DATA] tipindeki her cevap şu üç başlığı içermelidir:

- Keşif Özeti
  - Hangi tablo/view/pipeline etkilenecek?
  - Mevcut sorun ne? (yavaşlık, yanlış sonuç, karmaşa, bakım zorluğu)
  - Hangi dokümanlar okundu?

- Data Tasarımı
  - Sorgu/pipeline için önerilen yeni yapı
  - Önemli join/filtre kararları
  - Incremental vs full load stratejisi (varsa)
  - Dikkate alınan index / veri hacmi notları

- Uygulama Adımları
  - Dosya yolları + yapılacak değişiklikler
  - Gerekirse test senaryolarına dair kısa not (örn. “10 günlük veriyle test et”)

-------------------------------------------------------------------------------
6. SQL & SORGU KURALLARI (ÖZET)
-------------------------------------------------------------------------------

Agent, STYLE-DATA-001.md’ye göre en az şu kuralları gözetmelidir:

- SELECT * yasak; sadece gerekli alanlar seçilir.
- Tarih aralığı filtreleri:
  - start_date <= x < end_date şeklinde yazılır; BETWEEN kullanımı dikkatle ele alınır.
- CTE (WITH) kullanımı önerilir:
  - karmaşık sorgular okunabilir alt parçalara bölünür.
- WHERE filtreleri:
  - index’li kolonlar üzerinde uygun şekilde kullanılır.
- NULL handling:
  - COALESCE / IS NULL kontrolleri açık ve niyet belli olacak şekilde yazılır.
- DISTINCT sadece gerçekten gerekli ise kullanılır (yanlış modelin üstünü örtmek için değil).

-------------------------------------------------------------------------------
7. ETL / PIPELINE KURALLARI (ÖZET)
-------------------------------------------------------------------------------

- Incremental yüklemelerde:
  - Su kaynağı kolonu (örn. last_update_date) net olmalıdır.
  - Çakışma riskine karşı küçük bindirme (overlap) penceresi kullanılabilir (örn. son 5 dk / son 1 gün).
- Full load işlemleri ağırsa:
  - Planlı bakım zamanı veya batch window içinde koşturulmalıdır.
- Silinen kayıtlar:
  - Soft delete (is_deleted flag) kullanılıyorsa, tüm rapor sorguları bunu dikkate almalıdır.
  - Hard delete varsa, ETL stratejisi bununla uyumlu olmalıdır.

-------------------------------------------------------------------------------
8. MİKROSERVİS / BACKEND İLE İLİŞKİ
-------------------------------------------------------------------------------

- Backend servisi bir view veya pipeline’a dayanıyorsa:
  - Data değişiklikleri backend tarafındaki DTO/model/mapper’lara da yansıtılmalıdır.
- Agent, sadece data tarafını değiştiriyorsa bile:
  - İlgili TECH-DESIGN ve DATA-MODEL dokümanlarını kontrol edip, çelişki yaratmadığından emin olmalıdır.

-------------------------------------------------------------------------------
9. AGENT DAVRANIŞINDA SINIRLAR
-------------------------------------------------------------------------------

- Agent, production ortamında veri silme veya destructive DDL (DROP TABLE vb.)
  önermemeli; sadece migration / controlled change senaryolarında açıkça işaretlenmiş
  adımlar önerebilir.
- Büyük data setleri üzerinde “deneme yanılma sorguları” yerine, net ve test edilebilir
  tasarım önerileri sunmalıdır.

-------------------------------------------------------------------------------
10. ÖZET
-------------------------------------------------------------------------------

Bu doküman, [DATA] görevlerinde agent’ın:

- Hangi dokümanları okuyacağını,
- Nasıl keşif ve tasarım yapacağını,
- Sorgu ve ETL/pipeline tarafında hangi temel kurallara uyacağını,
- Nasıl dosya bazlı görev listesi üreteceğini

net şekilde tanımlar ve data/rapor geliştirme için referans davranış seti olarak
kullanılır.
