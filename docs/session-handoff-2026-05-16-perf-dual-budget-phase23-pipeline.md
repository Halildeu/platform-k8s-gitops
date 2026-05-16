# Session Handoff — 2026-05-16 PERF-INIT-V2.1 Dual Budget Phase 2+3 + Perf-Pipeline Fix

> **Belge kodu**: `session-handoff-2026-05-16-perf-dual-budget-phase23-pipeline`
> **Tarih**: 2026-05-16
> **Sahip**: Halil
> **Sprint**: PERF-INIT-V2.1 dual-budget activation (Phase 2+3) + perf-measurement pipeline repair
> **Format**: D28 5-alan handoff
> **Önceki handoff**: `session-handoff-2026-05-16-v2.1-faz-g-codex-audit-chain.md` (PR #715 — 20 PR V2.1 closure + Faz G)

---

## 1. Bağlam — Bu Session Ne Yaptı

Önceki session V2.1 9/9 closure + Faz G + Codex audit chain (20 PR) ile kapandı. Bu session kullanıcı talimatı zinciri: *"kalan işleri otonom sıra ile yapılacak durumda mıyız"* → *"kalan işleri tamamlayalım"* → *"tam otonom devam edelim"*.

PERF-INIT-V2.1 **dual-budget activation roadmap** (PERF-DEBT-V3 §5 — Codex `019e2cbf` + `019e2d16` chain) Phase 2 (runner reader) + Phase 3 (schema) ile ilerletildi. Bu sırada **perf-ölçüm CI pipeline'ının main'de 6+ ardışık run kırık** olduğu keşfedildi (`perf-snapshot-not-attached` / lighthouse `NO_FCP`) ve root-cause + fix ile onarıldı.

---

## 2. İddia — 4 PR MERGED (otonom zincir, 0 admin-merge)

| # | Repo | PR | Merge SHA | Konu |
|:-:|---|:-:|---|---|
| 1 | platform-web | #549 | `27304710` | Phase 2 — `route-performance-budget.mjs --budget-profile` reader |
| 2 | platform-web | #550 | `c01b8d07` | Phase 3 — `performance-budgets.json` nested `regressionGuard`/`targetBudget` |
| 3 | platform-k8s-gitops | #717 | `61c6b422` | PERF-DEBT-V3 §0/§5.3 doc sync (bare-key → suffixed) |
| 4 | platform-web | #552 | `8f7a2d23` | Perf-measurement pipeline fix (`MFE_ON_DEMAND_BOOTSTRAP`) |

Her PR: implement → Codex cross-AI review → (REVISE absorb →) AGREE → CI → normal squash merge → `ai-post-merge-cleanup.sh` archive tag.

---

## 3. İspatlar — LIVE Evidence

### Phase 2 — #549 (`27304710`)
- `evaluate()` + `resolveBudgetThresholds()` → dependency-free `scripts/ci/lib/route-budget-evaluate.mjs` lib'e çıkarıldı (no Playwright graph → install-free testable).
- `--budget-profile regressionGuard|targetBudget` reader; flag yokken **flat schema** (tam back-compat).
- Fail-closed: missing/empty/flag-shaped arg → `process.exit(2)`; missing profile / un-suffixed-metric-key trap / no recognized threshold key → `validityError` (hard-fail, `--warn-only` maskelemez).
- `scripts/ci/__tests__/route-budget-evaluate.test.mjs` — **19 node:test PASS**.
- `perf-budget.yml`'e install-free `unit-tests` job; trigger path'ler `gate-m2a` + `gate-perf-drift` consumer'larına da eklendi.
- Codex `019e2f6c`: **REVISE** (3 hardening — schema silent-no-op trap, boş-arg fallback, consumer path filters) → absorb → **AGREE**.

### Phase 3 — #550 (`c01b8d07`)
- 4 cold-authenticated route (`/home`, `/admin/users`, `/admin/access`, `/admin/reports/users`) → nested `regressionGuard` + `targetBudget` objeleri.
- **Suffixed key kontratı** (`transferFailKB`/`decodedFailKB`/`lcpFailMs`/`clsFail`); değerler PERF-DEBT-V3 §5.1 (regressionGuard) / §5.2 (targetBudget) ile birebir.
- 8 profile resolution Phase 2 reader'ından temiz geçti (0 error).
- Codex `019e2f6c`: **AGREE** — değerler §5.1/§5.2 ile 0 mismatch, flat-schema non-breaking (driftCount 0).

### #717 — gitops doc (`61c6b422`)
- PERF-DEBT-V3 §0 code-compat status → Phase 2/3 DONE; §5.3 JSON sketch bare-key (`transferKB`) → suffixed (`transferFailKB`).
- Codex `019e2f6c` AGREE. ADR-0011 boundary declaration + cross-ai-audit CI gate'leri PR body düzeltmesi ile geçirildi.

### #552 — Perf-Pipeline Fix (`8f7a2d23`)
- **Kök neden**: standalone `mfe-shell` preview build eager Module Federation remote fetch → `localhost:300X` remote'lar erişilemez → bootstrap crash → `NO_FCP` → `perf-snapshot-not-attached`. `perf-budget.yml` + `gate-perf-drift.yml` measurement aşaması bu yüzden main'de **6+ ardışık run kırmızıydı**.
- **Fix**: `MFE_ON_DEMAND_BOOTSTRAP=1` — perf workflow'larında MF remote'ları lazy/on-demand bootstrap.
- **KANIT**: #552 kendi CI'ında `route budget + bundle taxonomy` + `sliding baseline drift gate` + `lighthouse-ci` ÜÇÜ DE **PASS** (fix öncesi üçü de kırmızıydı).
- Codex `019e3149` AGREE (source-verified).

---

## 4. İspatlanamaz — Open Items

- **V3-B2 / V3-B1 perf-debt dalgaları başlamadı** — büyük çok-haftalık dalgalar (~28-52h / ~80-160h).
- **M2a1 daily history seed** biriktirilmedi (hard-flip Phase 4 için gerekli).
- **Owner O2/O4/O5** kararları bekliyor (cutover critical path).
- **`Auth Transport Contract E2E` advisory-fail** — #549/#550/#552'de de advisory-red. Perf-pipeline'dan **bağımsız ayrı bir kırık**; bu session'da incelenmedi (P2 — aşağıda).

---

## 5. P0 Action List — Sonraki Session (tam otonom devam)

Perf-ölçüm pipeline artık sağlıklı → V3 perf-debt dalgaları **ölçüm-doğrulamalı** yapılabilir.

### P0 — V3-B2 CLS Optimization Wave (~28-52h)

**V3-B2a — `/home` cold-authenticated CLS 0.362** (leader ≤0.10, 3.6×; PERF-DEBT-V3 item #1, kritik UX):
1. **Ölç**: `scripts/perf/auth-storage-setup.mjs` ile testai storageState üret → `route-performance-budget.mjs --target testai --routes /home` (M2a1 local-runner pattern — GHA→testai bloklu ama local runner çalışıyor; bkz. `perf:auth-route-budget:testai` package script).
2. **Attribution**: perf-observer `LayoutShift` entry `sources` alanı ile kayan elementleri tespit (chart / image / font lazy-load suspects).
3. **Fix**: kayan elementlere boyut rezervasyonu — explicit `width`/`height`, `aspect-ratio`, skeleton placeholder.
4. **Doğrula**: CLS p75 ≤0.10 sustained 5 ölçüm + browser görsel doğrulama.

**V3-B2b — `/admin/reports/users` CLS 0.161**: mfe-reporting AG Grid Enterprise init render layout reservation / skeleton pattern.

### P1 — V3-B1 LCP + Bundle Wave (~80-160h)
- `/admin/*` LCP 4500-4900ms (3× leader 1500ms); `/home` LCP 2176ms.
- Transfer 9MB / decoded 34MB (auth routes, 2-3× leader).
- Sıra: B1a bundle taxonomy + duplicate dedup → B1b LCP critical path (auth FSM + MFE bootstrap + AG Grid lazy-init) → B1c FCP (critical CSS + font preload).

### P1 — M2a1 daily history seed
- CLS/INP history biriktir (sliding-baseline-check.mjs FIFO; hard-flip Phase 4 enabler). Manuel run veya self-hosted runner.

### P2 — `Auth Transport Contract E2E` advisory-fail incele
- Perf-pipeline'dan bağımsız ayrı bir kırık; advisory olduğu için merge'leri bloklamadı ama kök neden bulunmalı.

### Owner-gated (kullanıcı yetkisi)
- O2 on-call rotation, O4 cutover window, O5 comms.

### Phase 4 — Hard-Flip Activation (HEMEN DEĞİL)
- `_phase: warn-only` → `_phase: hard-fail-regression-guard-only`. Daily history + flake budget + owner activation gerek. `--budget-profile regressionGuard` CI'da `--routes /home,/admin/users,/admin/access,/admin/reports/users` ile koşulmalı (profilesiz route'lar fail-closed kırılır — Codex `019e2f6c` notu).

---

## 6. Cross-AI Thread Chain

- `019e2f6c` — Phase 2 (REVISE → 3-finding absorb → AGREE) + Phase 3 (AGREE) + §5.3 doc.
- `019e3149` — #552 perf-pipeline fix (AGREE, source-verified).
- `019e2cbf` + `019e2d16` — dual-budget strategic verdict (önceki session, inherited).

---

## 7. HARD RULE Compliance

- ✅ Continuous Autonomous Mode — 4 PR durmadan zincir.
- ✅ Cross-AI Peer Review — her PR Codex (OpenAI) review, provider-level; implementer Claude ≠ reviewer.
- ✅ Admin Merge YASAK — 4/4 normal squash, 0 admin bypass.
- ✅ No Fake Work — her PR live CI kanıtı; #552 perf-gate-green kanıtı; merge-governance kararı Codex consult ile.
- ✅ AI-Native Forensic Cleanup — 4 archive tag remote'a push.
- ✅ No Closure Language — V3-B2/B1 sıradaki dalga olarak açık.

---

## 8. Next Session — Self-Contained Brief

```
Mevcut state (2026-05-16):
- PERF-INIT-V2.1 dual-budget Phase 2+3 DONE + perf-ölçüm pipeline DONE (4 PR merged)
- V3-B2/B1 perf-debt dalgaları unblocked, başlamadı

Sıradaki P0: V3-B2 /home CLS 0.362 fix
  1. scripts/perf/auth-storage-setup.mjs → testai storageState
  2. route-performance-budget.mjs --target testai --routes /home
  3. perf-observer LayoutShift.sources ile shift kaynak tespit
  4. boyut rezervasyonu fix + 5-ölçüm sustained doğrulama (CLS p75 ≤0.10)

Repo: platform-web (perf code) + platform-k8s-gitops (PERF-DEBT-V3 tracking)
İlk komut: cat docs/session-handoff-2026-05-16-perf-dual-budget-phase23-pipeline.md
```

---

## 9. Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [x] user-communication
- [ ] none of the above

User-communication justification: docs-only session handoff. 4-PR otonom zincir (PERF-INIT-V2.1 dual-budget Phase 2+3 + perf-pipeline fix) canonical audit trail + sonraki agent için V3-B2/B1 self-contained brief. Cluster state mutation YOK, credential operation YOK, kod/manifest değişimi YOK — pure handoff.

User-approval evidence: HARD RULE Pre-Production Full Authority (2026-04-29) + Continuous Autonomous Mode + Session Otomatik Açma/Handoff HARD RULE (2026-05-09, context %75+ → handoff) + kullanıcı açık talimatı "hand off" + "tam otonom devam edelim". PR label: `user-approval-required`.

---

## 10. Cross-AI Peer Review

Implementer AI:   Claude
Reviewer AI:      Codex
Codex thread:     019e2f6c-b067-79a0-bec4-e04cd44d2628
Verdict:          AGREE (dual-budget Phase 2+3 + perf-pipeline 4-PR chain, doc-only handoff)
Same-provider exception: N/A
Verdict reason:   Session 2026-05-16 PERF-INIT-V2.1 dual-budget Phase 2+3 + perf-measurement pipeline fix — 4 PR canonical handoff. D28 5-alan format. Yeni implementation YOK; doc-only handoff sonraki agent için V3-B2/B1 self-contained brief. Codex cross-AI chain (`019e2f6c` Phase 2/3 + `019e3149` #552) bu session'da AGREE; handoff doc o trail'i konsolide eder.
