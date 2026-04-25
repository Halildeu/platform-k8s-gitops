# AI-PROJECT-LAYOUT

Bu doküman, `ai/` klasörü altında geliştirilen tüm AI/ML modelleri, eğitim
pipeline’ları, inference servisleri ve değerlendirme süreçleri için standart
klasör yapısını tanımlar. Amaç: AI geliştirmede tutarlı, izlenebilir ve
yeniden üretilebilir bir yapı oluşturmaktır.

AI ile ilgili dokümanların konumu ve ID formatları için:
- docs/00-handbook/DOCS-PROJECT-LAYOUT.md  
- NUMARALANDIRMA-STANDARDI.md  
dokümanlarıyla birlikte değerlendirilmelidir.

-------------------------------------------------------------------------------
1. ÜST DÜZEY DİZİN YAPISI
-------------------------------------------------------------------------------

ai/
 ├── data/                → ham veri, temiz veri, feature setleri
 ├── notebooks/           → keşif, prototip, hızlı deneme çalışmalarının alanı
 ├── features/            → feature engineering script’leri
 ├── models/              → eğitilmiş modeller, model versiyonları
 ├── pipelines/           → model eğitim ve değerlendirme pipeline’ları
 ├── evaluation/          → metrik hesaplamaları, karşılaştırma raporları
 ├── serving/             → inference server, API gateway, model yükleme kodu
 ├── monitoring/          → drift detection, model health, telemetry
 ├── utils/               → yardımcı fonksiyonlar
 ├── configs/             → hyperparameter, environment, dataset config’leri
 ├── scripts/             → train / eval / deploy script’leri
 └── docs/                → DATA-CARD, MODEL-CARD, EVAL raporları

-------------------------------------------------------------------------------
2. VERİ YAPISI (data/)
-------------------------------------------------------------------------------

data/
  raw/           → ham veri kaynakları
  processed/     → temizlenmiş veri
  features/      → feature engineering sonrası dataset’ler
  samples/       → küçük test dataset’leri

Kurallar:
- raw → processed → features aşamaları açık olmalıdır.
- Veri versiyonlaması (örn. etiketli dataset v1.0, v1.1) docs veya configs altında tanımlanır.
- Gizlilik kısıtları DATA-GOV-001’e göre yönetilir.

-------------------------------------------------------------------------------
3. NOTEBOOKS
-------------------------------------------------------------------------------

notebooks/ sadece keşif amaçlıdır:
- quick prototype
- metrik testleri
- data exploration

Üretim kodu notebooks içinde tutulmaz; pipelines ve features içine taşınır.

-------------------------------------------------------------------------------
4. FEATURE ENGINEERING (features/)
-------------------------------------------------------------------------------

features/
  build_features.py  
  encode_<domain>.py  
  normalize_<domain>.py  

Kurallar:
- Tüm feature’lar merkezi bir pipeline içinde yeniden üretilebilir olmalıdır.
- Feature logic notebook’ta kalmaz.

-------------------------------------------------------------------------------
5. MODEL DEPOSU (models/)
-------------------------------------------------------------------------------

models/
  <model-name>/
    version_001/
      model.bin
      config.json
      metrics.json
    version_002/
      ...

Kurallar:
- Her eğitim run’ı bir versiyon oluşturur.
- MODEL-CARD dokümanı versiyonla eşleşir.
- Model artefact’ları tek klasörde tutulmalıdır.

-------------------------------------------------------------------------------
6. PIPELINES (pipelines/)
-------------------------------------------------------------------------------

pipelines/
  train.py        → eğitim pipeline’ı
  eval.py         → değerlendirme pipeline’ı
  preprocess.py   → data hazırlama pipeline’ı
  batch_infer.py  → batch inference
  schedule/       → cron/task scheduler akışları

Kurallar:
- pipeline = adım adım fonksiyonlar: load → preprocess → train → eval → save-model
- Config ve hyperparameter değerleri hard-coded olmamalıdır (configs/ üzerinden okunur).
- Pipeline her zaman yeniden çalıştırılabilir ve deterministik olmalıdır.

-------------------------------------------------------------------------------
7. MODEL EVALUATION (evaluation/)
-------------------------------------------------------------------------------

evaluation/
  eval_<model>.py
  compare_<version>.py
  metrics/
    auc.json
    f1.json
    precision.json

Gereksinimler:
- Metri̇kler açıkça tanımlanmalı: accuracy yeterli değildir; F1, precision, recall, AUC tercih edilir.
- Evaluate → Compare → Approve akışı uygulanır.
- Evaluation sonuçları MODEL-CARD ile eşleştirilir.

-------------------------------------------------------------------------------
8. MODEL SERVING (serving/)
-------------------------------------------------------------------------------

serving/
  app.py                 → inference API
  router.py              → prediction endpoints
  loader.py              → model yükleme mantığı
  schema.py              → request/response şemaları
  Dockerfile

Kurallar:
- Servis lightweight olmalıdır; model hafızaya bir kez yüklenir.
- request/response schema docs/ altında tanımlı olmalıdır.
- Logging: prediction_time, model_version, input_size gibi metrikler kaydedilir.

-------------------------------------------------------------------------------
9. MONITORING & DRIFT DETECTION (monitoring/)
-------------------------------------------------------------------------------

monitoring/
  drift_detector.py
  data_quality.py
  model_health.py
  dashboards/

Kurallar:
- Drift tespiti için feature distribution karşılaştırması yapılır.
- Model sağlığı için inference error rate, latency, accuracy-tracking izlenir.
- Operasyonel metrikler backend telemetry ile uyumlu olmalıdır.

-------------------------------------------------------------------------------
10. CONFIGS
-------------------------------------------------------------------------------

configs/
  hyperparams.yaml
  dataset.yaml
  training.yaml
  model-registry.json

Prensip:
- Hyperparameter ve dataset seçimleri pipeline içinde hard-coded olmamalıdır.
- Config dosyaları versiyonlamaya uygundur.

-------------------------------------------------------------------------------
11. DOKÜMANLAR (docs/)
-------------------------------------------------------------------------------

docs/
  DATA-CARDS/
  MODEL-CARDS/
  EVALUATION-REPORTS/

Bu dokümanlar:
- DATA-CARD → veri kaynağı, kalite, sınırlamalar
- MODEL-CARD → model amacı, metrikler, riskler, kullanım sınırları
- EVALUATION-REPORT → karşılaştırmalı sonuçlar  
şeklinde yapılandırılır.

-------------------------------------------------------------------------------
12. AGENT DAVRANIŞ REHBERİ
-------------------------------------------------------------------------------

[AI] görevinde agent:

1. AGENT-CODEX.core.md  
2. AI-PROJECT-LAYOUT.md (bu dosya)  
3. STYLE-AI-001.md  
4. DATA-CARD + MODEL-CARD + EVALUATION raporlarını  
okur ve aşağıdaki formatta cevap üretir:

- Keşif Özeti  
  - model/domain/pipeline hakkında temel bilgi  
- AI Tasarımı  
  - veri akışı, feature engineering, model seçimi, metrikler  
  - training pipeline / inference pipeline  
- Uygulama Adımları  
  - dosya yolu + yapılacak değişiklik

-------------------------------------------------------------------------------
13. ÖZET
-------------------------------------------------------------------------------

Bu layout dokümanı:
- AI/ML pipeline’larını,
- model versiyonlamayı,
- evaluation ve serving yapısını,
- monitoring ve drift detection standartlarını

compact ama net biçimde tanımlar ve AI geliştirme için tek doğruluk kaynağıdır.
