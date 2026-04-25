# AI/ML Görevleri (Compact)

> Transition Durumu: Bu dosya transition-active rehber katmanındadır.
> Canonical kaynaklar:
> `standards.lock`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`,
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`.

Bu dosya, [AI] tipindeki görevlerde agent’ın nasıl davranacağını tanımlar.
Amaç: AI/ML geliştirme, model eğitimi, evaluation, inference ve monitoring
işlerinde tutarlı ve izlenebilir bir yaklaşım sağlamaktır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Training, evaluation ve inference pipeline’larını tek bir mimari çerçeveye oturtmak.
- Veri hazırlama, feature engineering, model seçimi ve metrik değerlendirmelerinde
  standardizasyon sağlamak.
- AI modellerinin risk, etik ve veri gizliliği çerçevesinde geliştirilmesini sağlamak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

[AI] iş tipi şunları kapsar:

- Yeni model geliştirme veya mevcut modeli yeniden eğitme
- Training pipeline tasarımı
- Evaluation & metrics çalışmaları
- Inference servisi geliştirme (serving/)
- Model drift takibi ve monitoring düzenlemeleri
- Data-card, model-card, evaluation raporu üretimi veya güncellemesi

Eğer iş data engineering ağırlıklıysa data transition rehberi ile birlikte
değerlendirilir.

-------------------------------------------------------------------------------
3. ZORUNLU OKUMA
-------------------------------------------------------------------------------

[AI] işi alındığında agent aşağıdaki dokümanları dikkate almalıdır:

1. ÇEKİRDEK DAVRANIŞ  
   - Çekirdek transition rehberi  
   - AGENTS.md  

2. AI LAYOUT  
   - AI-PROJECT-LAYOUT.md  

3. AI STİL  
   - STYLE-AI-001.md  

4. DATA VE MODEL DOKÜMANLARI  
   - docs/05-ml-ai/DATA-CARDS/*.md  
   - docs/05-ml-ai/MODEL-CARDS/*.md  
   - docs/05-ml-ai/EVALUATION-REPORTS/*.md  

5. ETİK VE GİZLİLİK  
   - DATA-GOV-001.md  

Bu dokümanlar okunmadan agent pipeline, model, inference veya training hakkında
öneri sunamaz.

-------------------------------------------------------------------------------
4. ÇALIŞMA MODELİ
-------------------------------------------------------------------------------

Agent [AI] görevinde şu düşünme sırasını izler:

1. Keşif  
   - Hangi model/domain etkileniyor?  
   - Ne tür iş? (training, yeni feature engineering, serving, monitoring)  
   - DATA-CARD → veri kaynağı, kalite, boyut, kısıtlar  
   - MODEL-CARD → model amacı, metrikler, riskler  
   - EVALUATION raporları → önceki versiyon performansı  

2. AI Tasarımı  
   - Veri akışı (raw → processed → features → train → eval → serve)  
   - Feature engineering stratejisi (hangi script’ler kullanılacak?)  
   - Model seçimi (baseline mı, advanced mı?)  
   - Eğitim pipeline tasarımı:  
     load → preprocess → feature → train → eval → save  
   - Metrik stratejisi (F1, precision, recall, AUC)  
   - Inference tasarımı:
     - serving/app.py  
     - loader (model versiyonu nasıl yüklenecek?)  
     - schema (request/response)  
   - Monitoring: drift detection, latency, error rate  

3. Uygulama Adımları  
   - Her satır: dosya yolu + yapılacak değişiklik  
   - Örnekler:  
     ai/features/build_features.py → yeni feature ekle  
     ai/pipelines/train.py → hyperparameter güncelle  
     ai/serving/app.py → yeni prediction endpoint’i ekle  
     ai/evaluation/eval_modelX.py → F1-score hesaplaması ekle  

-------------------------------------------------------------------------------
5. CEVAP FORMATİ
-------------------------------------------------------------------------------

[AI] görevlerinde agent her zaman şu üçlü formatı kullanır:

- Keşif Özeti  
  - Okunan dokümanlar  
  - Etkilenen model/domain  
  - Veri kaynağı ve mevcut model versiyonu  

- AI Tasarımı  
  - Feature engineering  
  - Model seçimi / hyperparams  
  - Training pipeline  
  - Evaluation stratejisi  
  - Serving tasarımı (opsiyonel)  
  - Monitoring & drift  

- Uygulama Adımları  
  - Dosya yolu + yapılacak değişiklik  
  - Kod değil → görev listesi  

-------------------------------------------------------------------------------
6. SINIRLAR
-------------------------------------------------------------------------------

- Training veya evaluation kodu tam gövde şeklinde yazılmaz; sadece tasarım ve görev listesi verilir.
- Agent notebook içine üretim kodu yerleştirmez; production pipeline’a taşır.
- Gizli veriler (PII, hassas kolonlar) DATA-GOV-001’e göre korunur.
- Model sadece güvenli ve doğrulanabilir kullanım için önerilir; kritik kararlarda tek başına kullanılacağı varsayılmaz.

-------------------------------------------------------------------------------
7. ÖZET
-------------------------------------------------------------------------------

Bu dosya, AI görevlerinde agent’ın:
- hangi dokümanları okuyacağını,
- nasıl keşif yapacağını,
- nasıl AI tasarımı çıkaracağını,
- nasıl dosya bazlı görev listesi üreteceğini

net ve minimal bir formatta tanımlar.

AI geliştirme için resmi davranış standardıdır.
