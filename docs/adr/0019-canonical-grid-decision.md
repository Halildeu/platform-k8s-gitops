# ADR-0019: Canonical Grid Decision — @mfe/x-data-grid vs EntityGridTemplate

**Status**: Proposed
**Date**: 2026-05-15
**Author**: Claude (implementer) + Codex (cross-AI review thread `019e2a83`)
**Plan reference**: Reporting refactor §7 Adım 14 PR-4/5

## Context

Platform şu an iki paralel grid component'i kullanıyor:

1. **`@mfe/x-data-grid`** (`packages/x-data-grid/`):
   - AG Grid wrapper (community + enterprise license)
   - Server-side row model (SSRM) support
   - 4 modülde aktif kullanım (mfe-reporting hub + audit + users-report + variant grid)
   - Lisans: AG-128070 (expiry 2 June 2026)

2. **`EntityGridTemplate`** (`apps/mfe-reporting/src/components/EntityGridTemplate.tsx`):
   - Custom React table wrapper (TanStack Table backbone)
   - Server-side pagination + filtering
   - Daha basit; karmaşık AG Grid feature'ları yok (pivot, group, aggregate)
   - 3 modülde kullanım (dashboard + simple list views)

Adım 14 FE kozmetik dalga reporting refactor §7'nin son adımı. Yeni hook + preset + wrapper (PR-1/2/3) ile birlikte kullanılacak canonical grid kararı gerek — yoksa iki grid coexistence devam eder, adoption sample inconsistent olur.

## Decision

**`@mfe/x-data-grid` canonical kabul edilir.** EntityGridTemplate gradual migration ile retire edilir.

### Sebepler

1. **Feature coverage**: AG Grid SSRM + pivot + group + aggregate + Excel-style filter + column virtualization. EntityGridTemplate sadece basic table.
2. **Reporting refactor §7 ile uyum**: Workcube adapter `executeData(... page, pageSize)` + `executeCount` SSRM pattern'i; AG Grid native destekli.
3. **Lisans available**: AG-128070 expiry 2 June 2026; uzun vadeli sözleşme.
4. **Test ecosystem**: AG Grid SSRM için yazılı test framework (mfe-reporting'de mevcut Vitest + Playwright entegrasyon).
5. **Operator UX**: Excel-style filter + multi-column sort + row group AG Grid'de native; custom implementation çok pahalı.

### Migration path

| Modül | Mevcut Grid | Hedef | Effort |
|---|---|---|---|
| mfe-reporting/hub | `@mfe/x-data-grid` ✓ | (mevcut) | 0 |
| mfe-reporting/dashboards | EntityGridTemplate | `@mfe/x-data-grid` | 1-2 saat |
| mfe-reporting/dynamic-report | `@mfe/x-data-grid` ✓ | (mevcut) | 0 |
| mfe-audit/audit-report | EntityGridTemplate | `@mfe/x-data-grid` | 2-3 saat |
| mfe-users/users-report | EntityGridTemplate | `@mfe/x-data-grid` | 2-3 saat |
| Variant grid | `@mfe/x-data-grid` ✓ | (mevcut) | 0 |

**Toplam migration**: ~5-8 saat (3 modül).

### Retire path

1. **Phase 1** (Adım 14 PR-5): 4 modül adoption sample içinde EntityGridTemplate kullanan modülleri `@mfe/x-data-grid`'e migrate et.
2. **Phase 2** (sonraki sprint): `EntityGridTemplate` import sayısını CI gate ile sıfıra düşür.
3. **Phase 3** (90 gün sonra): `EntityGridTemplate.tsx` dosyasını sil + import audit.

## Consequences

### Positive

- ✅ Tek grid pattern: developer onboarding kolaylaşır
- ✅ AG Grid full feature set kullanılabilir (pivot/group/aggregate)
- ✅ useReportData (Adım 14 PR-3) AG Grid SSRM uyumlu zaten
- ✅ Test ecosystem konsolidasyonu
- ✅ Reporting refactor §7'nin son adımının canonical kararı

### Negative

- ⚠️ EntityGridTemplate kullanan 3 modül için migration effort (~5-8 saat)
- ⚠️ Bundle size: AG Grid Enterprise daha ağır (mitigation: tree-shaking + lazy import)
- ⚠️ Lisans bağımlılığı: AG-128070 yenilenmeli (expiry 2 June 2026); kalıcı paket alındı (sürekli destek)

### Risks

| Risk | Mitigation |
|---|---|
| AG Grid license expiry | Kalıcı paket; yenilenme planı operator | 
| Bundle size artışı | Tree-shaking + lazy import; ölçüm: bundle-size-check CI |
| Migration regression | Phase 1 önce test cluster smoke; Phase 2 CI gate |

## Alternatives Considered

### A. EntityGridTemplate'i canonical yap
- ❌ Reject: feature coverage çok dar (no pivot/group/aggregate)
- ❌ AG Grid lisansı boşa gider

### B. İki grid coexist devam
- ❌ Reject: inconsistent UX + developer confusion + test fragmentation

### C. Yeni custom grid yaz
- ❌ Reject: ~3-5 ay effort; AG Grid kalıcı paket + lisans elde mevcut

## Implementation Status

- [ ] Phase 1: 3 modül migration (Adım 14 PR-5 kapsamında)
- [ ] Phase 2: CI gate (`EntityGridTemplate import = 0`)
- [ ] Phase 3: File deletion + import audit

## Reversal Conditions

ADR-0019 ters yöne döner eğer:
- AG Grid Enterprise lisansı yenilenemez (kalıcı paket geçersiz olur)
- AG Grid bundle size SLO ihlal eder (>500KB gzipped)
- 6 ay içinde yeni grid feature'ı (örn. spreadsheet mode) production'da gerekir ve AG Grid karşılamaz

## References

- Plan §7 Adım 14 DoD (`docs/plan-reporting-refactor-2026-05-14.md`)
- Codex thread `019e2a83` plan-time istişare (canonical grid karar önerisi)
- AG Grid Enterprise lisans: AG-128070 (expiry 2 June 2026)
- Session 36 handoff: "AG Grid lisans bytes fix" — kalıcı paket alındı
- Sister PRs: useReportFormatter (#521), FilterFormStyle (#522), useReportData (#523)

## Cross-AI Review

\`\`\`yaml
implementer_ai: Claude
implementer_thread: session-58-continuation
reviewer_ai: Codex
reviewer_thread: 019e2a83 (plan-time istişare; canonical grid karar önerisi)
verdict: pending-governance-review
\`\`\`
