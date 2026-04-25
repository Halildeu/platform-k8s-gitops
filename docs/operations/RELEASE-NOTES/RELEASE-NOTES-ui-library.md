# UI Library Release Notes

ID: RN-ui-library
Status: Active
Owner: @team/platform

## Scope

- `mfe-ui-kit` package release ozetleri icin canonical notes dosyasidir.
- Sayisal katalog metrikleri icin primary truth:
  - `web/apps/mfe-shell/src/pages/admin/design-lab.index.json`
  - `web/test-results/releases/ui-library/latest/ui-library-release-manifest.v1.json`
  - `web/test-results/releases/ui-library/latest/ui-library-release-notes.v1.md`
  - `web/test-results/releases/ui-library/latest/ui-library-changelog.v1.md`
  - `web/test-results/releases/ui-library/latest/ui-library-upgrade-checklist.v1.json`
  - `web/test-results/releases/ui-library/latest/ui-library-upgrade-recipes.v1.json`
  - `web/test-results/releases/ui-library/latest/ui-library-upgrade-recipes.audit.v1.json`
  - `web/test-results/releases/ui-library/latest/ui-library-codemod-candidates.v1.json`
  - `web/test-results/releases/ui-library/latest/ui-library-codemod-candidates.audit.v1.json`
  - `web/test-results/releases/ui-library/latest/ui-library-codemod-prototypes.v1.json`
  - `web/test-results/releases/ui-library/latest/ui-library-codemod-prototypes.audit.v1.json`
- Bu dosya narrative release notu, rollout notu ve operator guidance tutar.

## Latest Release

- Version: `1.1.0`
- Release date: `2026-03-08`
- Package: `mfe-ui-kit`

## Highlights

- Public export surface, API catalog ve Design Lab manifest-first hat uzerinden hizalandi.
- Module Federation `./library` expose yuzeyi release kontratina baglandi.
- Adoption cockpit ile release, docs ve consumer surface ayni sayfada okunabilir hale geldi.
- Visual regression contract ve Storybook harness seti release gate'e dahil edildi.

## Operator Notes

- Katalog metrikleri, API coverage ve visual harness sayilari elle degistirilmez; generated artefactlardan okunur.
- Semver guidance, owner-aware rollout checklist ve changelog artik `latest` release artefact'larindan uretilir.
- Release narrative veya migration guidance gerekiyorsa bu dosyada guncellenir.
- Drift suphelerinde once `ui-library-release-manifest.v1.json` ve `design-lab.index.json` kontrol edilir.
