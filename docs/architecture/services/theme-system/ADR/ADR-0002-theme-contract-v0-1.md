# ADR-0002 – Theme Contract v0.1 (Single-Chain)

ID: ADR-0002  
Status: Proposed  
Tarih: 2025-12-15  
Sahip: @team/frontend

## Context

Tema sistemi şu an iki farklı katmanda bilgi taşıyor:
- Figma/design tokens → CSS var üretimi (build-time).  
- DB’de global/user theme + registry + overrides (runtime).  

Bu iki katman aynı “mode/alias/mapping” bilgisini farklı yerlerde tekrar
tanımladığında drift oluşuyor:
- serban-* / light-dark mapping kopyaları,  
- UI’da hardcoded css var listeleri (surface.default.bg vb.),  
- fallback’ler (var(--x, fallback)) ve hardcode renkler.

Hedef: “tek kaynak + tek zincir” kontratını kalıcı olarak kilitlemek.

## Decision

1) Theme Contract v0.1 SSOT
- SSOT: `web/design-tokens/figma.tokens.json` içinde `meta.themeContract`.  
- Build-time output: `web/design-tokens/generated/theme-contract.json`.  
- Runtime consumer’lar generated JSON okur; tokens JSON runtime’da parse edilmez.

Minimum alanlar:
- `version`  
- `defaultMode`  
- `modes` (modeKey → label/appearance/isHighContrast)  
- `aliases` (appearanceKey → modeKey)  
- opsiyonel: `deprecatedModes`, `migrationMap`

2) High Contrast (HC) politikası
- Contract’ta HC mode yoksa: UI’da HC seçeneği gösterilmez (build fail değil).  
- Contract’ta HC mode varsa ama theme.css’te gerekli var’lar yoksa: build-time FAIL.

3) Derived mapping (registry cssVars[])
- Theme Registry entry’leri `cssVars[]` alanı ile semantic key → CSS var listesi
  mapping’ini tek kaynaktan taşır.  
- UI’da hardcoded “targetVars listesi” yasaktır; apply mapping runtime katmanda
  registry’den okunarak yapılır.

4) Fallback yasak (single-chain)
- `var(--x, fallback)` yasaktır.  
- Tailwind token map yalnız `var(--...)` değerlerini kullanır (fallback yok).  
- Eksik CSS var: build-time FAIL (kontrat drift’ini erken yakalamak için).

## Consequences

Artılar:
- Mode/alias/mapping tek kaynaktan okunur; drift azalır.  
- Admin tema özelleştirme ekranı “tek giriş” olur.  
- Guardrail’ler deterministik hale gelir.

Eksiler/Riskler:
- Contract değişiklikleri build pipeline’a bağlanır; “küçük değişiklik” bile
  CSS üretimini etkileyebilir.  
- Strict “fallback yok” politikası, eksik token durumunda build’i kırar
  (ama amaç drift’i erken yakalamaktır).

## Mapping Removal Checklist

Aşağıdaki dosyalarda mode/alias/mapping kopyaları kaldırılmalı ve tek API
üzerinden okunmalıdır:
- `web/packages/ui-kit/src/runtime/theme-controller.ts`  
- `web/apps/mfe-shell/src/app/theme/theme-context.provider.tsx`  
- `web/apps/mfe-shell/src/app/ShellApp.ui.tsx`  
- `web/apps/mfe-shell/src/pages/admin/ThemeAdminPage.tsx`  
- `web/apps/mfe-shell/src/features/theme/theme-matrix.constants.ts`

## Linkler

- Story: docs/03-delivery/STORIES/STORY-0044-theme-ssot-single-chain-v1.md  
- Acceptance: docs/03-delivery/ACCEPTANCE/AC-0044-theme-ssot-single-chain-v1.md  
- API: docs/03-delivery/api/theme-registry.api.md

