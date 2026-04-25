# STYLE-AI-001 – AI/ML Kodlama Stili (Compact)

Bu doküman, `ai/` klasörü altında yazılan model eğitimi, feature engineering,
evaluation, inference ve monitoring kodlarının nasıl standartlaştırılacağını
tanımlar. Amaç: AI projelerinde tutarlı, izlenebilir, güvenli ve yeniden
üretilebilir (reproducible) geliştirme sağlamak.

-------------------------------------------------------------------------------
1. GENEL PRENSİPLER
-------------------------------------------------------------------------------

- Tüm AI kodu deterministik ve yeniden çalıştırılabilir olmalıdır.
- Eğitilen her model versiyonlanmalıdır (models/<model>/version_xxx).
- Config değerleri kod içine gömülmez; configs/ altından okunur.
- Veri gizliliği ve etik kurallar DATA-GOV-001’e uygun olmalıdır.
- Notebook sadece prototip içindir; üretim kodu notebooks/ içinde kalmaz.

-------------------------------------------------------------------------------
2. FEATURE ENGINEERING STANDARTLARI
-------------------------------------------------------------------------------

- Feature dönüşümleri tek yerde tutulur: features/ klasörü.
- Aynı feature pipeline hem eğitim hem inference sürecinde kullanılmalıdır.
- Feature logic notebook içinde bırakılmaz → temiz koda taşınır.
- Eksik değer yönetimi (imputation) açıkça belirtilmelidir.
- Kategorik değişkenler için encoding türü (one-hot, label, target) net olmalıdır.
- Tarih/zaman özellikleri (örn: hour_of_day, day_of_week) açık dokümante edilmelidir.

-------------------------------------------------------------------------------
3. MODEL EĞİTİMİ (TRAINING) STANDARTLARI
-------------------------------------------------------------------------------

- Eğitim script’leri pipelines/train.py içinde çalışır.
- Model seçimi:
  - baseline → lightweight model
  - final → performans + açıklanabilirlik dengesi
- Eğitim adımları:
  1. veri yükleme
  2. preprocessing
  3. feature engineering
  4. train/validation split
  5. model eğitimi
  6. metrik hesaplama
  7. model kayıt (save)
- Eğitim run’ında toplanması zorunlu bilgiler:
  - model versiyonu
  - kullanılan hyperparam’ler
  - veri seti versiyonu
  - eğitim süresi
  - metrikler (accuracy değil; F1, precision, recall, AUC kullanılmalıdır)

-------------------------------------------------------------------------------
4. MODEL KAYDI & VERSİYONLAMA
-------------------------------------------------------------------------------

- Eğitilen her model models/<model>/version_xxx/ klasörüne kaydedilir.
- Kaydedilmesi gereken artefact’lar:
  - model.bin veya eşdeğeri
  - config.json (hyperparam, seed, threshold bilgileri)
  - metrics.json (eval sonuçları)
  - model-card.md (zorunlu açıklama dokümanı)
- Model kayıt işlemi otomatik olmalıdır (train pipeline sonunda).

-------------------------------------------------------------------------------
5. EVALUATION & METRICS STANDARTLARI
-------------------------------------------------------------------------------

- Accuracy tek başına yeterli değildir; aşağıdaki metriklerden en az ikisi kullanılmalıdır:
  - precision, recall, F1-score, AUC
- Confusion matrix üretilmelidir.
- Evaluation raporu evaluation/ klasörüne kaydedilmelidir.
- Model karşılaştırması:
  - compare_<model>.py dosyasında versiyonlar arası metrik farkı hesaplanır.
- Threshold belirleme:
  - yalnızca ROC/PR eğrileri üzerinden karar verilir; keyfi sabit değer kullanılmaz.

-------------------------------------------------------------------------------
6. INFERENCE & SERVING STANDARTLARI
-------------------------------------------------------------------------------

- Inference server serving/ altında yaşar:
  - app.py → API entry
  - loader.py → model yükleme
  - schema.py → request/response şemaları
- Model hafızaya bir kez yüklenmeli (lazy load).
- Logging:
  - prediction_time
  - model_version
  - input_size
  - error_count
- Güvenlik:
  - Girdi validasyonu zorunludur.
  - Maksimum payload boyutu sınırlanmalıdır.

-------------------------------------------------------------------------------
7. MONITORING & DRIFT DETECTION
-------------------------------------------------------------------------------

- Drift detection:
  - Feature dağılımlarının training vs production karşılaştırması
  - p-value, population stability index veya kolmogorov-smirnov kullanılabilir
- Prediction monitoring:
  - inference latency, error rate, traffic volume takibi
- Model health checks:
  - model yüklenebilir mi?
  - response süresi normal mi?
- Drift tespit edilirse:
  - yeniden eğitim pipeline'ı (pipelines/train.py) tetiklenebilir.

-------------------------------------------------------------------------------
8. TEST STANDARTLARI
-------------------------------------------------------------------------------

- Unit test:
  - feature engineering fonksiyonları
  - preprocessing adımları
  - utility fonksiyonları
- Integration test:
  - end-to-end train → eval → serve flow
- Inference test:
  - prediction formatı
  - schema validasyonu
- Notebook test edilmez; production pipeline test edilir.

-------------------------------------------------------------------------------
9. RİSK VE ETİK KURALLARI (DATA-GOV-001 UYUMU)
-------------------------------------------------------------------------------

- Eğitim verisi gizlilik politikalarına uygun olmalıdır.
- Model kartında:
  - kullanım sınırları,
  - potansiyel bias kaynakları,
  - hassas feature kullanımı (örn: yaş, cinsiyet),
  açıkça belirtilmelidir.
- Hassas kategorilerde açıklanabilirlik (explainability) zorunludur.
- Model, kritik karar süreçlerinde insan denetimi olmadan tek başına kullanılmamalıdır.

-------------------------------------------------------------------------------
10. AGENT DAVRANIŞ REHBERİ
-------------------------------------------------------------------------------

[AI] görevinde agent aşağıdaki sırayla ilerler:

1. AGENT-CODEX.core.md  
2. AI-PROJECT-LAYOUT.md  
3. STYLE-AI-001.md (bu dosya)  
4. DATA-CARD + MODEL-CARD + EVALUATION-REPORT dökümanlarını okur  
5. Çıktı formatı:
   - Keşif Özeti
   - AI Tasarımı (veri akışı, model seçimi, pipeline, metrikler)
   - Uygulama Adımları (dosya yolu + yapılacak değişiklik)

-------------------------------------------------------------------------------
11. ÖZET
-------------------------------------------------------------------------------

Bu stil dokümanı:
- feature engineering,
- training, evaluation, serving,
- monitoring ve drift detection,
- risk & etik kurallarını

compact ve uygulanabilir şekilde tanımlar.  
AI/ML geliştirme için tek doğruluk kaynağı olarak kullanılmalıdır.