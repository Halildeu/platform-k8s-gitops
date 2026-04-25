# Web Frontend Görevleri (Compact)

> Transition Durumu: Bu dosya transition-active rehber katmanındadır.
> Canonical kaynaklar:
> `standards.lock`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`,
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`.

Bu dosya, [WEB] tipindeki görevlerde agent’ın nasıl davranacağını tanımlar.
Amaç: Web MFE geliştirmede tutarlı, öngörülebilir ve standardize edilmiş bir
çalışma modeli oluşturmaktır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Web mikro frontend (MFE) geliştirmelerinde tek tip mimari yaklaşım sağlamak.
- apps/** içinde MFE’lerin, packages/** içinde ortak modüllerin doğru kullanımı.
- Design tokens, theme sistemi, state modeli ve API kullanımını standardize etmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

Aşağıdaki görevler [WEB] tipine girer:

- Yeni sayfa / ekran / component geliştirme
- Yeni feature geliştirme (entities → features → pages → widgets modeli)
- UI Kit entegrasyonları
- API entegrasyonu (shared-http kullanarak)
- State yönetimi, navigation, liste/detail akışları
- design-tokens / theme ile ilgili UI düzenlemeleri

-------------------------------------------------------------------------------
3. ZORUNLU OKUMA
-------------------------------------------------------------------------------

[WEB] işi alındığında agent aşağıdaki dokümanları sırasıyla dikkate almalıdır:

1. ÇEKİRDEK DAVRANIŞ  
   - Çekirdek transition rehberi  
   - AGENTS.md  

2. WEB LAYOUT  
   - WEB-PROJECT-LAYOUT.md  

3. WEB STİL  
   - STYLE-WEB-001.md  

4. DOKÜMAN & ID KURALLARI  
   - NUMARALANDIRMA-STANDARDI.md  
   - DOCS-PROJECT-LAYOUT.md  

5. ÜRÜN DOKÜMANLARI  
   - docs/01-product/PRD/PRD-*.md  
   - docs/01-product/UX/UX-*.md  

6. MİMARİ DOKÜMANLAR (VARSA)  
   - docs/02-architecture/clients/WEB-ARCH.md  

Bu dokümanlar yüklenmeden agent herhangi bir mimari karar vermez.

7. KOD KALİTESİ, TEST VE GÜVENLİK (LINT / BUILD / TEST / SECURITY)
   - Lint / Build:
     - Web kodu değiştiren her [WEB] işinde:
       - Tercihen tek komut:
         - `python3 scripts/run_lint_all.py`  (backend compile + WEB lint)
       - veya yalnız web tarafı için:
         - `cd web && npm run lint:style lint:semantic lint:tailwind lint:no-antd`
   - Testler:
     - Web unit testleri:
       - `./scripts/run_tests_web.sh`  veya `./scripts/run_tests_web.sh unit`
     - Web e2e testleri:
       - `./scripts/run_tests_web.sh e2e`
     - Web kalite turu (bundle/perf/a11y):
       - `./scripts/run_tests_web.sh quality`
     - Backend + Web unit testleri birlikte:
       - `python3 scripts/run_tests_all.py`
   - Security:
     - Web security kontrolleri (SRI + CSP özeti):
       - `./scripts/check_security_web.sh`
     - Backend + Web security kontrolleri birlikte:
       - `python3 scripts/check_security_all.py`
   - Layout:
     - MFE iç yapı standardı (WEB-PROJECT-LAYOUT):
       - `python3 scripts/check_web_mfe_layout.py`
   - Bu komutlar, DEV-GUIDE içindeki “Validate” aşamasının otomatik
     kalite kontrol adımı olarak kabul edilir.

-------------------------------------------------------------------------------
4. ÇALIŞMA MODELİ
-------------------------------------------------------------------------------

Agent [WEB] görevinde aşağıdaki düşünme sırasını izler:

1. Keşif  
   - Görevin ilgili olduğu MFE nedir? (apps/<mfe>)  
   - Etkilenen klasör hangisi? (pages / features / widgets / shared / entities)  
   - PRD ve UX dökümanlarında davranış tanımı var mı?

2. Tasarım (FE Tasarım)  
   - Component hiyerarşisi: hangi component nereye yazılacak?  
   - State modeli: local state mi, feature hook mu, global store mu?  
   - API çağrısı: packages/shared-http üzerinden mi yapılacak?  
   - Theme & design tokens: hangi token’lar kullanılacak?  
   - Reuse: Bu MFE’de shared/** mi uygun, yoksa packages/ui-kit mi?  
   - MFE sınırı: diğer MFE’den doğrudan import yasaktır → packages üzerinden paylaşım önerilir.

3. Uygulama Adımları  
   - Her adım sadece “dosya yolu + yapılacak değişiklik” formatında yazılır.  
   - Örnek format:
       apps/mfe-users/src/features/user-list/useUserList.ts → yeni filter parametresi ekle  
       apps/mfe-users/src/pages/UserListPage.tsx → filtre bileşenini UI’ya ekle  
       packages/ui-kit/src/Table/Table.tsx → token tabanlı padding düzelt  

-------------------------------------------------------------------------------
5. CEVAP FORMATİ
-------------------------------------------------------------------------------

Agent [WEB] tipindeki görevlerde daima şu formatta cevap üretir:

- Keşif Özeti  
  - Okunan dokümanlar  
  - Etkilenen MFE ve klasör  
  - Varsayımlar / sınırlar  

- FE Tasarım  
  - Component yapısı  
  - State modeli  
  - API / data flow  
  - Theme / tokens kullanımı  
  - MFE boundary notları  

- Uygulama Adımları  
  - Dosya yolları + yapılacak değişiklikler  
  - Gereksiz kod üretimi olmadan sadece görev listesi  

-------------------------------------------------------------------------------
6. MFE SINIRI KURALİ
-------------------------------------------------------------------------------

- Bir MFE başka bir MFE’den doğrudan import edemez.  
- Ortak kod sadece packages/** altından gelir.  
- design-tokens/** sadece tema/tasarım için kullanılmalıdır.  
- UI Kit kullanımı, STYLE-WEB-001’e göre yapılmalıdır.

-------------------------------------------------------------------------------
7. NOTLAR
-------------------------------------------------------------------------------

- Eski (legacy) klasörler (components/, hooks/, services/) yeni geliştirmelerde kullanılmaz.  
- Yeni geliştirme mutlaka şu hiyerarşiyi takip eder:  
  entities → features → pages → widgets → shared  
- Component içinde side-effect (fetch, storage, timers) yasaktır.  

-------------------------------------------------------------------------------
8. ÖZET
-------------------------------------------------------------------------------

Bu dosya, web görevlerinde agent’ın:
- hangi dokümanları okuyacağını,
- nasıl düşüneceğini,
- nasıl tasarım çıkaracağını,
- nasıl görev listesi üreteceğini

net şekilde tanımlar ve web geliştirme için tek doğruluk kaynağıdır.
