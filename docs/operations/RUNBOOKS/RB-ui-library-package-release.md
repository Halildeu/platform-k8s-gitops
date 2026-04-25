# RB-ui-library-package-release

ID: RB-ui-library-package-release
Status: Active
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `mfe-ui-kit` icin package release, visual contract ve publish bundle hattinin operator runbook'udur.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

Canonical Inputs:

- `docs/02-architecture/context/ui-library-package-release.contract.v1.json`
- `docs/02-architecture/context/ui-library-consumer-owner-registry.v1.json`
- `docs/02-architecture/context/ui-library-consumer-upgrade-recipes.contract.v1.json`
- `docs/02-architecture/context/ui-library-consumer-codemod-candidates.contract.v1.json`
- `docs/02-architecture/context/ui-library-consumer-codemod-prototypes.contract.v1.json`
- `docs/02-architecture/context/ui-library-visual-review.contract.v1.json`
- `web/apps/mfe-shell/src/pages/admin/design-lab.index.json`
- `web/test-results/releases/ui-library/latest/ui-library-release-manifest.v1.json`
- `web/test-results/releases/ui-library/latest/ui-library-release.summary.v1.json`
- `web/test-results/releases/ui-library/latest/ui-library-release-gate.summary.v1.json`
- `web/test-results/releases/ui-library/latest/ui-library-release-notes.v1.md`
- `web/test-results/releases/ui-library/latest/ui-library-changelog.v1.md`
- `web/test-results/releases/ui-library/latest/ui-library-upgrade-checklist.v1.json`
- `web/test-results/releases/ui-library/latest/ui-library-upgrade-recipes.v1.json`
- `web/test-results/releases/ui-library/latest/ui-library-upgrade-recipes.audit.v1.json`
- `web/test-results/releases/ui-library/latest/ui-library-codemod-candidates.v1.json`
- `web/test-results/releases/ui-library/latest/ui-library-codemod-candidates.audit.v1.json`
- `web/test-results/releases/ui-library/latest/ui-library-codemod-prototypes.v1.json`
- `web/test-results/releases/ui-library/latest/ui-library-codemod-prototypes.audit.v1.json`

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

Required Gates:

- (1) `npm -C web run build:ui-kit`
- (2) `npm -C web run build-storybook`
- (3) `npm -C web run publish:bundle`
- (4) `npm -C web run release:ui-library:manifest`
- (5) `npm -C web run audit:ui-library-upgrade-recipes`
- (6) `npm -C web run audit:ui-library-codemod-candidates`
- (7) `npm -C web run audit:ui-library-codemod-prototypes`
- (8) `npm -C web run gate:ui-library-visual`
- (9) `npm -C web run gate:ui-library-wave -- --wave wave_11_recipes`
- (10) `npm -C web run doctor:frontend -- --preset ui-library`
- (11) `npm -C web run gate:ui-library-release`

Success Criteria:

- Public export surface ile API catalog sayisi hizali olmali.
- `Design Lab` adoption backlog listeleri bos olmali.
- Storybook static artefact uretilmeli ve core visual harness dosyalari mevcut olmali.
- Hosted review secret'i yoksa artifact-only visual review fallback'i acik olmali.
- Publish bundle artefact'lari release manifest icinde `exists=true` olarak gorunmeli.
- Consumer app owner resolution ve upgrade checklist artefact'lari latest release turunda uretilmeli.
- Single-app upgrade recipe audit artefact'i latest release turunda uretilmeli ve `failCount=0` olmali.
- Codemod candidate artefact ve audit artefact'i latest release turunda uretilmeli; `failCount=0` olmali.
- Codemod prototype artefact ve audit artefact'i latest release turunda uretilmeli; `failCount=0` olmali.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Release artefact'lari `web/test-results/releases/ui-library/latest/` altinda uretilir.
- Gate sonuclari `ui-library-release-gate.summary.v1.json` icinde toplanir.

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- Coverage drift: `component-api-catalog.v1.json` ve `component-manifest.v1.json` farkini incele.
- Visual contract fail: Storybook harness dosyalari, `storybook-static/index.html` ve `_chromatic-trigger.ts` kontrol et.
- Review channel drift: `ui-library-visual-review.contract.v1.json`, release manifest `visualContract.reviewChannel` ve `CHROMATIC_PROJECT_TOKEN` hazirlik durumunu birlikte kontrol et.
- Release metadata drift: `design-lab.index.json` icindeki `release` ve `adoption` bloklarini yeniden uret.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Bu runbook, `mfe-ui-kit` package release hattinin operator adimlari, gate'leri ve failure triage surecini tanimlar.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- `docs/02-architecture/context/ui-library-package-release.contract.v1.json`
