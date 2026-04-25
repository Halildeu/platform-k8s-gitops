# Mobil Frontend Görevleri

> Transition Durumu: Bu dosya transition-active rehber katmanındadır.
> Canonical kaynaklar:
> `standards.lock`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`,
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`.

Bu dosya, [MOB] (Mobil) tipindeki görevler için geçerlidir.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Mobil uygulama geliştirme işlerinde (React Native, Flutter, native fark etmeksizin)
  tutarlı bir mimari ve UX yaklaşımı sağlamak.
- Offline/online senaryoları ve cihaz yeteneklerini (kamera, bildirim, lokasyon vb.)
  sistematik ele almak.
- Mobil tarafta dosya yapısı, state, API ve theme kullanımını standartlaştırmak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

Bu kurallar aşağıdaki görevler için uygulanır:

- Yeni mobil ekran / feature geliştirme
- Offline cache / sync mekanizmaları
- Push notification, deep link, navigation akışları
- Mobil spesifik form ve input davranışları
- Device API (kamera, konum, storage vb.) kullanımı

-------------------------------------------------------------------------------
3. ZORUNLU OKUMA
-------------------------------------------------------------------------------

[MOB] işi alındığında agent aşağıdaki dokümanları dikkate almalıdır:

1. KÖK DAVRANIŞ
   - Çekirdek transition rehberi
   - AGENTS.md

2. MOBİL LAYOUT
   - MOBILE-PROJECT-LAYOUT.md

3. MOBİL STİL
   - STYLE-MOB-001.md

4. MİMARİ (VARSA)
   - docs/02-architecture/clients/MOBILE-ARCH.md

5. ÜRÜN DOKÜMANLARI
   - docs/01-product/PRD/PRD-*.md
   - docs/01-product/UX/UX-*.md

Bu dokümanlar yüklenmeden agent tasarım veya dosya önerisi yapmamalıdır.

-------------------------------------------------------------------------------
4. ÇALIŞMA ŞEKLİ
-------------------------------------------------------------------------------

Agent, [MOB] tipindeki bir görevde şu adımları izler:

1. Keşif
   - Görevin hangi feature’a/ekrana ait olduğunu belirler.
   - PRD ve UX dokümanlarından davranış beklentisini çıkarır.
   - MOBILE-PROJECT-LAYOUT’a göre ilgili klasör (screens, features, services, store, theme) seçilir.

2. Tasarım (Mobil Tasarım)
   - Navigation flow (hangi screen’den nereye gidilir?) tarif edilir.
   - State stratejisi:
     - Global (store) mi, feature-level hook mu, yoksa local UI state mi?
   - Offline/online davranış:
     - Offline queue, retry, sync mekanizması gerekiyorsa services katmanında kurgulanır.
   - API ve device access:
     - API çağrıları services/api altında,
     - Device erişimi services/device altında tasarlanır.
   - Theme:
     - Hard-coded değer olmadan, theme/tokens ile uyumlu tasarım yapılır.

3. Uygulama Adımları
   - Sadece “dosya yolu + yapılacak değişiklik” formatında net bir liste üretir.
   - Örnek:
     - mobile/features/login/useLogin.ts → offline queue desteği ekle.
     - mobile/screens/LoginScreen.tsx → yeni hata mesajı göster.
     - mobile/services/api/login.api.ts → yeni endpoint’i kullan.

-------------------------------------------------------------------------------
5. CEVAP FORMATİ
-------------------------------------------------------------------------------

[MOB] tipindeki her cevap aşağıdaki üç başlığı içermelidir:

- Keşif Özeti
  - Okunan dokümanlar
  - Hangi ekran/feature’ı etkilediği
  - Varsayılanlar / sınırlamalar

- Mobil Tasarım
  - Navigation akışı
  - State modeli (store vs feature hook)
  - Offline/online stratejisi
  - API/device/theme kullanımı

- Uygulama Adımları
  - Her satır: hedef dosya + yapılacak değişiklik
  - Örnek:
    - mobile/features/user-profile/useUserProfile.ts → profil güncelleme için yeni field ekle.
    - mobile/screens/UserProfileScreen.tsx → yeni field’i forma ekle.

-------------------------------------------------------------------------------
6. NOTLAR
-------------------------------------------------------------------------------

- Offline gereksinimi varsa bu mutlaka Tasarım bölümünde açıkça ele alınmalıdır.
- Device izinleri (kamera, lokasyon vb.) için platform spesifik gereksinimler
  (Android manifest, iOS plist) ayrıca belirtilmelidir.
- UI bileşenleri içinde fetch/localStorage/device API çağrısı yapılmaması kuralı
  bozulmamalıdır; tüm IO işlemleri services katmanından geçer.
