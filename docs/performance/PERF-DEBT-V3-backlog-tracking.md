# V3 Perf Debt Backlog — Discrete Tracking (PMD §2.2/§2.3 ↔ M2a1 Actual)

> **Belge kodu**: `PERF-DEBT-V3-backlog-tracking`
> **Tarih**: 2026-05-15
> **Sahip**: Halil
> **Sprint**: V2.1 closure sonrası → V3 perf debt wave
> **Trigger**: M2a1 4-route LIVE measurement (testai N=3, d35-admin) ↔ PMD §2.3 leader-target referans matrisi karşılaştırması
> **Audit**: `docs/performance/m2a1-local-measurement-2026-05-15-v2-4routes.json` (PR #527 e3922a37b3) + `performance-budgets.json` (platform-web)

---

## 0. ⚠️ Codex `019e2d16` REVISE Absorb (Enforcement Source vs Target Tracker)

**Bu doc enforcement source DEĞİL** — V3 perf debt targets'in **discrete trackable owner/PR/wave mapping**'idir.

**Enforcement sources** (gerçek runtime gate'leri):
- `platform-web/performance-budgets.json` — route-level fail thresholds (flat schema + nested `regressionGuard`/`targetBudget` profiles, Phase 3)
- `platform-web/tests/perf/baseline.json` — sliding history pattern (FIFO 30)
- `platform-web/scripts/ci/route-performance-budget.mjs` + `scripts/ci/lib/route-budget-evaluate.mjs` — runner + extracted `evaluate()` reader (flat schema default; `--budget-profile` selects a nested profile)
- `platform-web/scripts/perf/sliding-baseline-check.mjs` — G2 regression gate (TRACKED_METRICS: transferKB, decodedKB, resourceCount, tbtMs, longTaskTotalMs, lcpMs, fcpMs + **cls** + **inpMs** — platform-web PR #535 e60c9667 ile extended Phase 1 functional)

**Dual budget code-compat status** (Codex `019e2d16` → `019e2f6c` chain — ✅ resolved):
- ✅ **Phase 2 DONE** (platform-web PR #549): `route-performance-budget.mjs` gained a `--budget-profile regressionGuard|targetBudget` reader; `evaluate()` extracted into the dependency-free `scripts/ci/lib/route-budget-evaluate.mjs`. Profile objects MUST use the suffixed flat key names (`transferFailKB`/`decodedFailKB`/`lcpFailMs`/`clsFail`); un-suffixed metric-key traps are fail-closed rejected.
- ✅ **Phase 3 DONE** (platform-web PR #550): `performance-budgets.json` 4 cold-authenticated routes carry nested `regressionGuard` + `targetBudget` objects (§5.1/§5.2 values, suffixed keys).
- ⏳ **Phase 4 pending**: hard-flip activation (`_phase` flip + activation evidence) — NOT immediate.

**Activation roadmap**:
1. ✅ **Code PR** — runner `--budget-profile` reader (Phase 2, platform-web PR #549).
2. ✅ **Schema extend PR** — `performance-budgets.json` dual budget format (Phase 3, platform-web PR #550).
3. ⏳ **Hard-flip activation PR** — `_phase: warn-only` → `_phase: hard-fail-regression-guard-only` (Phase 4; needs daily history + flake budget + owner activation).

---

## 1. Bağlam — Neden Bu Doc?

PMD §2.2 (KPI Tiered Hedefler) + §2.3 (Leader-Target referans matrisi) formal hedefleri tanımlı. Ama:

- ✅ **Var olan tracking**: `tests/perf/baseline.json` (sliding history) + `performance-budgets.json` (route budgets) + M2a1 measurement artifact
- ❌ **Eksik tracking**: M2a1 LIVE measurement sonucu **leader-target gap analizinin** discrete trackable item olarak — kim sahibi, ne zaman fix, hangi PR

Bu doc PMD §2.3 ↔ M2a1 actual karşılaştırmasından çıkan **9 discrete perf debt item** + priority + V3 wave mapping + tracking metadata.

---

## 2. Leader-Target ↔ M2a1 Actual Karşılaştırma Özeti

### 2.1 /home cold-authenticated

| Metrik | Leader Target | Actual (M2a1) | Delta | Status |
|---|:-:|:-:|:-:|:-:|
| LCP | ≤1,200 ms | **2,176 ms** | +976ms / +81% | ❌ |
| TBT | ≤50 ms | **77 ms** | +27ms / +54% | ❌ |
| **CLS** | <0.10 | **0.362** | +0.262 / +362% | ❌❌ **KRİTİK** |
| FCP | ≤1,800 ms (CWV) | 2,176 ms | +376 / +21% | ❌ |
| Transfer | ≤3,000 KB | **9,276 KB** | +6,276 / +209% | ❌ |
| Decoded | ≤12,000 KB | **34,544 KB** | +22,544 / +188% | ❌ |
| Resources | ≤80 | 116 | +36 / +45% | ❌ |

### 2.2 /admin/users cold-authenticated

| Metrik | Leader Target | Actual | Delta | Status |
|---|:-:|:-:|:-:|:-:|
| LCP | ≤1,500 ms | **4,916 ms** | +3,416 / +228% | ❌❌ KRİTİK |
| TBT | ≤50 ms | 75 ms | +25 / +50% | ❌ |
| CLS | <0.10 | **0.016** | -0.084 | ✅ |
| Transfer | ≤6,000 KB | 9,323 KB | +3,323 / +55% | ❌ |
| Decoded | ≤18,000 KB | 34,676 KB | +16,676 / +93% | ❌ |
| Resources | ≤80 | 132 | +52 / +65% | ❌ |

### 2.3 /admin/access (→ /access/roles)

| Metrik | Leader Target | Actual | Delta | Status |
|---|:-:|:-:|:-:|:-:|
| LCP | ≤1,500 ms | **4,512 ms** | +3,012 / +201% | ❌❌ |
| TBT | ≤50 ms | 75 ms | +25 / +50% | ❌ |
| CLS | <0.10 | **0.007** | -0.093 | ✅ Mükemmel |
| Transfer | ≤6,000 KB | 9,557 KB | +3,557 / +59% | ❌ |
| Decoded | ≤18,000 KB | 36,001 KB | +18,001 / +100% | ❌ |
| Resources | ≤80 | 128 | +48 / +60% | ❌ |

### 2.4 /admin/reports/users cold-authenticated (fin-muhasebe-detay yerine proxy)

| Metrik | Leader Target | Actual | Delta | Status |
|---|:-:|:-:|:-:|:-:|
| LCP | ≤1,500 ms | **4,632 ms** | +3,132 / +209% | ❌❌ |
| TBT | ≤70 ms | 74 ms | +4 / +6% | ❌ |
| **CLS** | <0.10 | **0.161** | +0.061 / +61% | ❌ |
| Transfer | ≤5,000 KB | 9,333 KB | +4,333 / +87% | ❌ |
| Decoded | ≤16,000 KB | 34,711 KB | +18,711 / +117% | ❌ |
| Resources | ≤80 | 134 | +54 / +68% | ❌ |

### 2.5 /login cold-anonymous (4-canary baseline korunuyor)

✅ Leader CWV (LCP 1016ms ✓, FCP 1000ms ✓, CLS 0.004 ✓); byte ❌ 3× üstü (2343 KB transfer / 9068 KB decoded).

---

## 3. Discrete Perf Debt Items — V3 Backlog Trackable

### Item #1 — /home CLS 0.362 KRİTİK UX

| Field | Value |
|---|---|
| ID | `V3-perf-debt-#1` |
| Title | `/home cold-authenticated CLS 0.362 (3.6× leader) — layout shift fix` |
| Priority | **P0 — kritik UX + V3 target debt** (NOT hard-flip seed blocker per PMD §138: M2a1 ilk ölçüm "iyi/kötü değil, ölçüm zinciri kuruldu"; hard-flip activation regressionGuard baseline ratification ile, CLS 0.362 V3-B2 target — Codex `019e2d16` REVISE absorb) |
| V3 Wave | **V3-B2 — CLS Optimization** (PMD V2 Wave B2 ≠ V3-B2 namespace collision avoid) |
| Owner | TBD (frontend engineer + UX) |
| Target | CLS ≤0.10 (Web Vitals + leader target) |
| Effort | TBD (~16-32h initial) |
| Dependencies | M2a1 measurement chain (PR #527) LIVE ✓ |
| Investigation | Browser screenshot/trace + LCP/CLS chunks attribution; bundle taxonomy + lazy-load suspects (chart, image, font) |
| Acceptance | /home CLS p75 ≤0.10 sustained 5 measurements; UX visual verification |
| Risk | Hard-flip 2026-05-29 sonrası baseline ratification gate; CLS gerçek user impact |

### Item #2 — Auth Routes LCP Critical (3× Leader)

| Field | Value |
|---|---|
| ID | `V3-perf-debt-#2` |
| Title | `/admin/* LCP 4,500-4,900ms (3-3.3× leader 1,500ms) — critical path optimization` |
| Priority | **P0** (sektör 3× altında, user-perceived) |
| V3 Wave | **V3-B1 — LCP Critical Chain** (PMD V2 Wave B1 closed ≠ V3-B1 namespace) |
| Owner | TBD (frontend + backend) |
| Target | LCP p75 ≤1,500ms (admin routes leader target) |
| Effort | TBD (~40-80h estimated) |
| Investigation | LCP chunk attribution (mfe-users/mfe-access/mfe-reporting bootstrap), auth FSM critical path, MFE remote loadShare timing, AG Grid Enterprise initial render |
| Acceptance | All 3 admin routes LCP p75 ≤1,500ms sustained; rendered sentinel <2s |
| Sub-items | a) Auth FSM transportReady chain audit; b) MFE remote loadShare warm path; c) AG Grid lazy-init |

### Item #3 — /home LCP 2,176ms (1.8× Leader 1,200ms)

| Field | Value |
|---|---|
| ID | `V3-perf-debt-#3` |
| Title | `/home cold-authenticated LCP 2,176ms (leader 1,200ms +%81)` |
| Priority | **P0** (CWV + hard-flip blocker) |
| V3 Wave | **V3-B1 — LCP Critical Chain** (PMD V2 Wave B1 closed ≠ V3-B1 namespace) |
| Owner | TBD |
| Target | LCP p75 ≤1,200ms |
| Effort | TBD (~24-40h) |
| Investigation | Shell bootstrap + MFE remote loadShare + home dashboard render chain |
| Acceptance | LCP p75 ≤1,200ms sustained; CWV mükemmel ✅ |

### Item #4 — Auth Routes Transfer 9-9.5 MB (1.5-3× Leader)

| Field | Value |
|---|---|
| ID | `V3-perf-debt-#4` |
| Title | `Auth routes cold transfer 9-9.5 MB (leader 3-6 MB)` |
| Priority | **P1** (bandwidth, mobile/3G zayıf) |
| V3 Wave | **V3-B1 — Bundle Size Wave** (PMD V2 Wave B1 closed ≠ V3-B1 namespace) |
| Owner | TBD (frontend) |
| Target | /home ≤3,000 KB, /admin/* ≤6,000 KB |
| Effort | TBD (~40-60h initial + ongoing) |
| Investigation | Bundle taxonomy + duplicate-package-detector + source-map-explorer per route; MFE remote dedup; Brotli/gzip ratio verify |
| Acceptance | Route-level cold transfer leader target altında sustained 5 measurements |
| Sub-items | a) Bundle taxonomy live PR; b) Duplicate dedup; c) Critical path tree-shake; d) Module Federation dedup |

### Item #5 — Auth Routes Decoded 34-36 MB (1.9-3× Leader)

| Field | Value |
|---|---|
| ID | `V3-perf-debt-#5` |
| Title | `Auth routes decoded 34-36 MB (leader 12-18 MB)` |
| Priority | **P1** (parse/exec cost; main thread block) |
| V3 Wave | **V3-B1 — Bundle Size Wave** (PMD V2 Wave B1 closed ≠ V3-B1 namespace) |
| Owner | TBD (frontend) |
| Target | /home ≤12 MB, /admin/* ≤18 MB |
| Effort | Item #4 ile birlikte |
| Investigation | Item #4 ile birlikte |
| Acceptance | Item #4 ile birlikte |

### Item #6 — /admin/reports/users CLS 0.161

| Field | Value |
|---|---|
| ID | `V3-perf-debt-#6` |
| Title | `/admin/reports/users CLS 0.161 (leader ≤0.10 +%61)` |
| Priority | **P1** (mfe-reporting AG Grid render layout shift) |
| V3 Wave | **V3-B2 — CLS Optimization** (PMD V2 Wave B2 ≠ V3-B2 namespace collision avoid) |
| Owner | TBD (mfe-reporting team) |
| Target | CLS p75 ≤0.10 |
| Effort | TBD (~12-20h) |
| Investigation | AG Grid Enterprise init render layout reservation; skeleton/placeholder pattern |
| Acceptance | CLS p75 ≤0.10 sustained |

### Item #7 — All Routes TBT 71-77ms (1.5× Leader 50ms)

| Field | Value |
|---|---|
| ID | `V3-perf-debt-#7` |
| Title | `All cold-authenticated routes TBT 71-77ms (leader 30-50ms)` |
| Priority | **P2** (main thread block; less critical than LCP) |
| V3 Wave | **V3-B3 — Long Task / Critical Path** (PMD V2 Wave B3 closed ≠ V3-B3 namespace) |
| Owner | TBD |
| Target | TBT p75 ≤50ms |
| Effort | TBD (~20-40h) |
| Investigation | Long task analyzer + main thread profile per route; React render schedule + JS bundle hydration |
| Acceptance | TBT p75 ≤50ms across 4 routes |

### Item #8 — All Routes FCP 2.1-2.4s (CWV Target 1.8s)

| Field | Value |
|---|---|
| ID | `V3-perf-debt-#8` |
| Title | `All cold-authenticated routes FCP 2.1-2.4s (CWV good ≤1.8s, leader ≤1.0s)` |
| Priority | **P2** (CWV good zone üstünde) |
| V3 Wave | **V3-B1 — Critical Path** (PMD V2 Wave B1 closed ≠ V3-B1 namespace) |
| Owner | TBD |
| Target | FCP p75 ≤1.8s (CWV good) |
| Effort | Item #2/#3 ile birlikte |
| Investigation | Critical CSS extract + font preload + above-fold render priority |
| Acceptance | FCP p75 ≤1.8s sustained |

### Item #9 — Auth Routes Resources 116-134 (Leader ≤80)

| Field | Value |
|---|---|
| ID | `V3-perf-debt-#9` |
| Title | `Auth routes resource count 116-134 (leader ≤80, +%45-68)` |
| Priority | **P3** (request count, less impact than byte) |
| V3 Wave | **V3-B3 — Lazy / Chunk Split** (PMD V2 Wave B3 closed ≠ V3-B3 namespace) |
| Owner | TBD |
| Target | Resource count ≤80 per route |
| Effort | TBD (~20-30h) |
| Investigation | Per-route resource inventory; route-based code split + dynamic import + Module Federation remote consolidation |
| Acceptance | Cold-authenticated routes resource count ≤80 |

---

## 4. V3 Wave Mapping

### Wave V3-B1 — LCP + Bundle Size Critical (P0+P1)

Items: #2, #3, #4, #5, #8

**Strategic order**:
1. **B1a Bundle taxonomy LIVE** — duplicate analyzer + tree-shake + Module Federation dedup (Items #4, #5)
2. **B1b LCP critical path** — auth FSM + MFE bootstrap + AG Grid lazy-init (Items #2, #3)
3. **B1c FCP optimization** — critical CSS + font preload (Item #8)

**Estimated effort**: 80-160h (~2-4 hafta full-time frontend)
**Wave gate**: All 5 routes leader target byte + LCP sustained

### Wave V3-B2 — CLS Optimization (P0+P1)

Items: #1, #6

**Strategic order**:
1. **B2a /home CLS 0.362 critical** (Item #1) — KRİTİK UX
2. **B2b /admin/reports CLS 0.161** (Item #6) — AG Grid skeleton pattern

**Estimated effort**: 28-52h
**Wave gate**: All 4 routes CLS p75 ≤0.10 sustained

### Wave V3-B3 — Long Task / Lazy Chunk (P2+P3)

Items: #7, #9

**Strategic order**:
1. **B3a Long task profile** (Item #7)
2. **B3b Resource count + chunk split** (Item #9)

**Estimated effort**: 40-70h
**Wave gate**: TBT p75 ≤50ms + Resource ≤80

---

## 5. Hard-Flip Activation Dual Budget Approach (Codex `019e2cbf`)

Codex strategic verdict tehlikesi:

> "Aspirational threshold (3MB/12MB/CLS 0.1) hard-flip'te kalırsa gate sürekli kırmızı → değersizleşir."

### 5.1 Regression Guard Budget (hard-flip aktif olduğunda)

Mevcut baseline + tolerans (örn. +%10):

| Route | Transfer guard | Decoded guard | LCP guard | CLS guard |
|---|:-:|:-:|:-:|:-:|
| /home | ≤10,000 KB | ≤38,000 KB | ≤2,400 ms | ≤0.40 |
| /admin/users | ≤10,500 KB | ≤38,000 KB | ≤5,400 ms | ≤0.10 (current 0.016 ✓) |
| /admin/access | ≤10,500 KB | ≤40,000 KB | ≤5,000 ms | ≤0.10 (current 0.007 ✓) |
| /admin/reports/users | ≤10,500 KB | ≤38,000 KB | ≤5,100 ms | ≤0.20 |

**Hard-flip = exit 1 on regression** (mevcut baseline'dan +%10 kötü).

### 5.2 Target Budget (V3 perf debt aspirational)

Leader target korunur — V3 B1/B2/B3 wave acceptance criteria:

| Route | Transfer target | Decoded target | LCP target | CLS target |
|---|:-:|:-:|:-:|:-:|
| /home | ≤3,000 KB | ≤12,000 KB | ≤1,200 ms | ≤0.10 |
| /admin/users | ≤6,000 KB | ≤18,000 KB | ≤1,500 ms | ≤0.10 |
| /admin/access | ≤6,000 KB | ≤18,000 KB | ≤1,500 ms | ≤0.10 |
| /admin/reports/users | ≤5,000 KB | ≤16,000 KB | ≤1,500 ms | ≤0.10 |

**Target = V3 wave acceptance gate**, not hard-flip regression guard.

### 5.3 Hard-Flip Activation Decision

Hard-flip PR (Phase 4) için iki ayrı eşik:
- `regressionGuard`: 5.1 mevcut baseline ratification
- `targetBudget`: 5.2 V3 wave acceptance (issue tracker)

`performance-budgets.json` nested schema (Phase 3, platform-web PR #550 — LIVE).
Profile objects use the **suffixed** flat threshold keys; the Phase 2 reader
(`route-budget-evaluate.mjs`) fail-closed rejects un-suffixed metric names
(`transferKB`/`lcpMs`/...):
```json
{
  "route": "/home",
  "mode": "cold-authenticated",
  "regressionGuard": { "transferFailKB": 10000, "decodedFailKB": 38000, "lcpFailMs": 2400, "clsFail": 0.4 },
  "targetBudget":   { "transferFailKB":  3000, "decodedFailKB": 12000, "lcpFailMs": 1200, "clsFail": 0.1 }
}
```

The `_phase` field is added by Phase 4 (hard-flip activation), not Phase 3 — see roadmap §0.
Hard-flip gate evaluates **regressionGuard** (current baseline +tolerans). Target budget V3 wave tracker.

---

## 6. KPI Tier Status (PMD §2.2)

| Tier | Tanım | Pre-V2 | V2.1 Closure | V3 Target |
|---|---|:-:|:-:|:-:|
| **Hard regression gate** | Baseline'dan +%5 üstü değil | n/a | 🟡 Warn-only seed | 🟢 Hard-flip 2026-05-29 sonrası |
| **Improvement milestone** | /home decoded ≤25-32MB, transfer ≤5MB | ❌ | ❌ FAİL (34/9 actual) | 🎯 V3-B1 wave target |
| **Leader target** | 12-aylık aspirational | /login partial | /login partial; auth 3× üstü | 🎯 V3-B1+V3-B2+V3-B3 wave |

---

## 7. Acceptance Criteria — V3 Perf Debt Wave Done

V3 perf debt wave **COMPLETE** kriterleri:

### V3-B1 Wave Done
- [ ] All 4 cold-authenticated routes transfer ≤leader target (sustained 5 measurements)
- [ ] All 4 routes decoded ≤leader target
- [ ] All 4 routes LCP p75 ≤leader target
- [ ] All 4 routes FCP p75 ≤1.8s (CWV good)

### V3-B2 Wave Done
- [ ] All 4 routes CLS p75 ≤0.10 (CWV good)

### V3-B3 Wave Done
- [ ] All 4 routes TBT p75 ≤50ms
- [ ] All 4 routes resource count ≤80

### Hard-Flip Wave Done
- [ ] M2a1 hard-flip aktivasyon PR (Codex round 9 AGREE)
- [ ] Regression guard budget (current baseline + tolerans) production
- [ ] Target budget V3 wave tracker

---

## 8. Audit Trail

- PMD v9.1 §2.2 KPI Tiered Hedefler
- PMD v9.1 §2.3 Leader-target referans matrisi
- M2a1 measurement artifact: `docs/performance/m2a1-local-measurement-2026-05-15-v2-4routes.json` (PR #527 e3922a37b3)
- `performance-budgets.json` route budget definitions (platform-web)
- `tests/perf/baseline.json` sliding history pattern
- V3 hard-flip activation runbook: `RB-v3-m2a1-baseline-hard-flip-activation.md` (PR #689)
- Codex strategic consult: `019e2cbf` — dual budget yaklaşımı warning
- Cross-AI peer review HARD RULE: 14+ round V2.1 closure inherited

---

## 9. HARD RULE Compliance

- ✅ Pre-Production Full Authority: agent autonomous discrete item tracking
- ✅ Continuous Autonomous Mode: V2.1 closure → V3 perf debt zinciri
- ✅ Cross-AI Peer Review: M2a1 measurement chain Codex 8-round inherited
- ✅ No Closure Language: "V3 wave" = next phase, not closure
- ✅ No Fake Work: actual measurement values (M2a1 LIVE artifact) baseline
- ✅ Plan Consensus Autonomy: Codex `019e2cbf` strategic verdict inherited

---

## 10. Cross-AI Peer Review

Implementer AI:   Claude
Reviewer AI:      Codex
Codex thread:     019e2cbf-2731-7653-8b4a-d8844179801b
Verdict:          AGREE (strategic dual budget warning + V2.1 closure inherited)
Same-provider exception: N/A
Verdict reason:   V3 perf debt backlog doc — PMD §2.2/§2.3 leader-target ↔ M2a1 actual karşılaştırma sonucu 9 discrete trackable item + V3 wave mapping (B1+B2+B3) + dual budget yaklaşımı (regression guard vs target budget). Codex `019e2cbf` "aspirational hard-flip değersizleşir" warning birebir absorb.
