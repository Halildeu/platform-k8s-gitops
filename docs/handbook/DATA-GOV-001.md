# DATA-GOV-001 – Veri Gizlilik ve Etik Kurallar (Compact)

Bu doküman, proje kapsamındaki tüm veri işleme ve AI/ML çalışmalarında
uygulanacak gizlilik, etik ve data governance prensiplerini özetler.
Amaç: KVKK ve benzeri regülasyonlara uyumu ve sorumlu AI kullanımını
standart hale getirmektir.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Kişisel ve hassas verilerin korunmasını sağlamak.
- Veri yaşam döngüsü boyunca (toplama, saklama, işleme, silme) ortak kuralları tanımlamak.
- AI/ML modellerinde etik ve adil kullanım prensiplerini belirlemek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Tüm operasyonel veri kaynakları (DB, log, event, file storage).
- ETL/pipeline süreçleri ve data mart’lar.
- AI/ML eğitim, evaluation ve inference süreçleri.
- Data-card, model-card ve evaluation dokümanları.

-------------------------------------------------------------------------------
3. TANIMLAR
-------------------------------------------------------------------------------

- PII: Kişiyi doğrudan veya dolaylı tanımlayabilen bilgiler.
- Hassas veri: Finansal, sağlık, kimlik, lokasyon ve benzeri yüksek riskli alanlar.
- Anonimleştirme: Verinin kişiyle ilişkilendirilemeyecek hale getirilmesi.

-------------------------------------------------------------------------------
4. VERİ YAŞAM DÖNGÜSÜ (RAW → PROCESSED → FEATURES)
-------------------------------------------------------------------------------

- raw/ → Sadece yetkili ekip erişebilir; mümkünse maskelenmiş veri tutulur.
- processed/ → Temizlenmiş, minimum alan setine indirgenmiş veri.
- features/ → Model eğitiminde kullanılan öznitelikler; PII alanları tutulmaz.
- Tüm aşamalarda veri kaynağı, versiyonu ve erişim yetkileri dokümante edilir.

-------------------------------------------------------------------------------
5. GEREKSİNİMLER VE KURALLAR
-------------------------------------------------------------------------------

- Gereksiz veri toplanmaz; amaçla ilgisiz alanlar schema’dan çıkarılır.
- Mümkün olan her yerde pseudonymization/anonimleştirme uygulanır.
- Hassas alanlar için maskeleme/log redaksiyonu zorunludur.
- Erişim yetkileri “en az ayrıcalık” prensibine göre verilir.
- Data export, backup ve paylaşım süreçleri kayıt altına alınır.

-------------------------------------------------------------------------------
6. AI/ML ÖZEL KURALLAR
-------------------------------------------------------------------------------

- Eğitim setlerinde kullanılan hassas feature’lar model-card içinde açıkça belirtilir.
- Bias riski taşıyan alanlarda (cinsiyet, yaş, lokasyon vb.) ek evaluation yapılır.
- Model, kritik karar süreçlerinde (kredi, işe alım vb.) tek karar verici olarak kullanılmaz;
  insan onayı zinciri korunur.
- Drift ve performans düşüşleri monitoring ile takip edilir; gerektiğinde yeniden eğitim planlanır.

-------------------------------------------------------------------------------
7. RİSKLER / VARSAYIMLAR
-------------------------------------------------------------------------------

- Regülasyon değişiklikleri (KVKK, GDPR vb.) dokümantasyona yansıtılmalıdır.
- Üçüncü taraf servislerle veri paylaşımında ek sözleşme ve teknik kontrol gereklidir.
- Varsayımlar: Üretim ortamlarına erişim sınırlı, audit log’ları tutuluyor ve periyodik
  erişim incelemesi yapılıyor.

-------------------------------------------------------------------------------
8. REFERANSLAR
-------------------------------------------------------------------------------

- docs/00-handbook/AI-PROJECT-LAYOUT.md
- docs/00-handbook/STYLE-AI-001.md
- docs/05-ml-ai/DATA-CARDS/*
- docs/05-ml-ai/MODEL-CARDS/*

-------------------------------------------------------------------------------
9. ÖZET
-------------------------------------------------------------------------------

Bu doküman, veri gizliliği ve etik kuralları için tek referans noktasıdır.
Tüm data/AI işlemleri bu kurallara uyumlu tasarlanmalı ve dokümante edilmelidir.

