# WEB-ARCH – Web Frontend Mimari Üst Bakış

Bu doküman, web frontend kod tabanının (apps, packages, module federation,
routing, theme, security, test stratejileri) **yüksek seviye mimari özetini**
sunmak için kullanılır.

Amaç: İnsanlar ve AI agent’ların, ayrıntılı `web/docs/**` rehberlerine
gitmeden önce tek bir yerden genel resmi görebilmesi.

-------------------------------------------------------------------------------
## 1. UYGULAMA VE PAKET YAPISI (ÖZET)
-------------------------------------------------------------------------------

- Uygulamalar (apps): shell, admin, access vb.  
- Paylaşılan paketler (packages): shared-ui, shared-http, auth, mf-router vb.  
- Module Federation yapısı: shell host, remote MFE’ler, shared dep’ler.

Detaylar ve klasör ağaçları için:
- `web/docs/architecture/frontend/frontend-project-layout.md`

-------------------------------------------------------------------------------
## 2. ROUTING & MF-ROUTER
-------------------------------------------------------------------------------

- Shell uygulaması ana routing katmanını barındırır.  
- MFE’ler MF Router üzerinden bağlanır; shared router config kullanılır.  
- Version pinning ve MF audit için QLTY-FE-VERSIONS-01 (STORY-0025) ve
  QLTY-MF-ROUTER-01 (STORY-0035) ile uyumlu yapı kullanılır.

Detaylı rehberler:
- `web/docs/mf-check.md`  
- `web/docs/mf-troubleshooting.md`  
- `web/docs/architecture/frontend/grid-template-roadmap.md`

-------------------------------------------------------------------------------
## 3. THEME & UX SİSTEMİ
-------------------------------------------------------------------------------

- Tema sistemi E03-S01 Theme & Layout System v1.0 kararlarına dayanır.  
- Accent/focus, header nav, personalization ve overlay/grid tone için
  ayrı Story zincirleri mevcuttur (STORY-0020..0022, STORY-0037..0039).

Detaylı rehberler:
- `web/docs/theme/**`  
- `docs/03-delivery/STORIES/STORY-0020-theme-accent-and-focus.md`  
- `docs/03-delivery/STORIES/STORY-0037-theme-layout-system-v1.md`

-------------------------------------------------------------------------------
## 4. AUTH & GÜVENLİK
-------------------------------------------------------------------------------

- Frontend auth Keycloak/OIDC entegrasyonu ile yönetilir (QLTY-FE-KEYCLOAK-01,
  QLTY-FE-SHELL-AUTH-01, QLTY-FE-SPA-LOGIN-01).  
- Shell auth merkezi, shared-http ile entegredir; multi-tab oturum
  senkronizasyonu BroadcastChannel ile yapılır.

Detaylı rehberler:
- `web/docs/02-security/01-auth/01-frontend-vault-integration.md`  
- `docs/03-delivery/STORIES/STORY-0009-fe-spa-login-standardization.md`  
- `docs/03-delivery/STORIES/STORY-0034-fe-keycloak-oidc.md`  
- `docs/03-delivery/STORIES/STORY-0036-fe-shell-auth-centralization.md`

-------------------------------------------------------------------------------
## 5. TEST STRATEJİSİ
-------------------------------------------------------------------------------

- FE için unit, integration ve e2e testler; Playwright/axe, jest/testing-library
  kombinasyonları kullanılır.  
- Kritik flows için e2e senaryolar `web/docs/tests/**` altında belgelenmiştir.

Detaylı rehberler:
- `web/docs/tests/variant-manager-e2e.md`  
- `docs/03-delivery/TEST-PLANS/TP-0101-fe-spa-login-standardization.md`

-------------------------------------------------------------------------------
## 6. LİNKLER
-------------------------------------------------------------------------------

- Legacy FE mimari rehberi:  
  - `web/docs/architecture/frontend/frontend-project-layout.md`  
- Yeni docs sistemiyle ilgili ana referanslar:  
  - `WEB-PROJECT-LAYOUT.md`  
  - `STYLE-WEB-001.md`  
  - `DOCS-PROJECT-LAYOUT.md`  
  - `docs/03-delivery/PROJECT-FLOW.md`  
  - `docs/03-delivery/guides/GUIDE-0003-fe-docs-migration-guide.md`  
