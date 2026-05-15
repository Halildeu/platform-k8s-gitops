# Runbook — V3 M2a1 Baseline Hard-Flip Activation (Warn-Only → Hard-Fail)

> **Belge kodu**: `RB-v3-m2a1-baseline-hard-flip-activation`
> **Tarih**: 2026-05-15
> **Sahip**: Halil (owner) + agent autonomous chain
> **Sprint**: V3 backlog — V2.1 M2a1 closure'dan sonra baseline hardening
> **Trigger date**: **2026-05-29** (14-gün history accumulation tamamlandığında)
> **Prerequisites**: V2.1 9/9 closure ✓ + M2a1 4-route chain LIVE (PR #527) + Faz G freeze gate UNLOCKED

---

## 1. Bağlam — M2a1 Warn-Only Baseline Seed → Hard-Fail Flip

V2.1 M2a1 closure (platform-web PR #527 e3922a37b3 2026-05-15) "baseline seed warn-only" fazıyla LIVE oldu. PMD v9.1 §138 + Codex Option B birebir:

> "M2a1 ilk ölçüm warn-only baseline seed (G2 sliding baseline pattern). Sonuçlar iyi/kötü diye değil — ölçüm zinciri kuruldu diye kapat."

Bu doğru semantik. Şimdi 14-gün history accumulation tamamlandıktan sonra **hard-fail flip** zorunlu — aksi takdirde ölçüm zinciri kurulu ama threshold breach gerçek regression yakalayamıyor (warn-only sustained = false-green riski).

### 1.1 Mevcut state (2026-05-15 cutover-prep)

| Aspect | Current | Hard-Flip Target |
|---|---|---|
| Phase | warn-only baseline seed | hard-fail |
| History entries | 1 ölçüm (2026-05-15 first run) | 30+ entries (FIFO 30, 14-gün) |
| Threshold action | breach → exit 0 (mask) | breach → exit 1 (block) |
| FP rate | TBD | ≤1/last 20 + ≤3/last 100 (Codex G2 pattern) |
| Owner activation | warn-only default | explicit `_phase=hard-fail` flip |

### 1.2 4 measured routes (M2a1 baseline)

```
✅ /home cold-authenticated         (sentinel: h1, h2, [role="heading"])
✅ /admin/users cold-authenticated  (sentinel: h1, h2, [role="heading"])
✅ /admin/access cold-authenticated (sentinel: h1, h2, [role="heading"]; expectedPath: /access/roles)
✅ /admin/reports/users cold-authenticated (sentinel: .ag-root-wrapper, .ag-root)
```

Plus advisory `/home warm-fresh` skipped (PR-G1 territory).

---

## 2. Trigger Conditions (Hard-Flip Activation Gate)

Codex G2 sliding-baseline-check pattern + tests/perf/baseline.json `_phase` field. Hard-flip için **3 koşul birlikte**:

### 2.1 (a) 14-day history accumulation

```bash
# Verify history entries count per route key
python3 -c "
import json
b = json.load(open('tests/perf/baseline.json'))
for key, entry in b['routes'].items():
    if not key.endswith('::cold-authenticated'):
        continue
    h = entry.get('history', [])
    print(f'{key}: {len(h)} history entries')
"
```

**Hard-flip requires**: Her 4 cold-authenticated key için **≥10 history entries** (10+ measurement runs accumulated 14 gün boyunca = ~daily-ish + extra runs için).

### 2.2 (b) False-positive rate (FP gate)

Codex `019e26f9` G2 pattern:
- **≤1 FP / last 20 measurements**
- **≤3 FP / last 100 measurements**

```bash
# Compute FP rate per route (FP = warn-only fail that wouldn't fail in hard-flip)
node scripts/perf/sliding-baseline-check.mjs --compute-fp-rate
# Output: fp_rate_per_route per_route median/p95/stdDev
```

### 2.3 (c) Owner explicit activation

Manual flip — `_phase: warn-only` → `_phase: hard-fail` in `tests/perf/baseline.json`:

```diff
- "_phase": "warn-only",
+ "_phase": "hard-fail",
+ "_hardFailActivationDate": "2026-05-29T00:00:00Z",
+ "_hardFailActivation": {
+   "owner": "Halil",
+   "fp_rate_last_20": "<auto-fill from sliding-check>",
+   "fp_rate_last_100": "<auto-fill>",
+   "history_count_min": "<auto-fill>",
+   "codex_thread": "019e2b00 (R7 conditions met retrospectively)"
+ }
```

---

## 3. Agent Autonomous Steps (T-Trigger -1 day)

### 3.1 History accumulation check

```bash
cd /Users/halilkocoglu/Documents/platform-web
git checkout main && git pull

# Check baseline.json history per route
python3 << 'EOF'
import json
b = json.load(open('tests/perf/baseline.json'))
keys = [
    '/home::cold-authenticated',
    '/admin/users::cold-authenticated',
    '/admin/access::cold-authenticated',
    '/admin/reports/users::cold-authenticated',
]
ready = True
for key in keys:
    h = b.get('routes', {}).get(key, {}).get('history', [])
    status = '✓' if len(h) >= 10 else '✗'
    print(f'{status} {key}: {len(h)} entries (target ≥10)')
    if len(h) < 10:
        ready = False
print()
print(f'History accumulation gate: {"READY" if ready else "NOT READY — keep accumulating"}')
EOF
```

### 3.2 Continuous measurement runs (T-Trigger -14d → T-Trigger -1d)

```bash
# Daily measurement run via:
# Option A: Self-hosted runner (platform-gha-runner-testai-deploy on staging-sw) + cron
# Option B: workflow_dispatch manual daily
# Option C: Local Mac periodic cron (developer machine)

# Each run appends to history via --update-baseline
node scripts/perf/auth-storage-setup.mjs
PERF_AUTH_STORAGE=tests/perf/.auth-storage.json \
node scripts/ci/route-performance-budget.mjs \
  --target testai --runs 3 \
  --routes "/home,/admin/users,/admin/access,/admin/reports/users" \
  --auth-storage tests/perf/.auth-storage.json \
  --update-baseline
```

### 3.3 FP rate computation

```bash
# Run G2 sliding-baseline-check FP computation
node scripts/perf/sliding-baseline-check.mjs --analyze-fp-rate

# Expected output:
# Route: /home::cold-authenticated  fp_rate_last_20=X  fp_rate_last_100=Y
# Route: /admin/users::cold-authenticated  fp_rate_last_20=X  ...
# ...
# Overall: ≤1/20 + ≤3/100 → READY for hard-flip
```

---

## 4. Owner Activation Steps (T-Trigger Day)

### 4.1 Pre-flip review

- [ ] Agent §3.1 history accumulation gate passed ≥10 entries per route
- [ ] Agent §3.3 FP rate gate passed (≤1/20 + ≤3/100)
- [ ] No active regression alerts (sliding-baseline-check output clean)
- [ ] Codex peer review (round 9 — provider-level cross-AI HARD RULE)

### 4.2 Flip execution

```bash
cd /Users/halilkocoglu/Documents/platform-web
git checkout -b feat/v3-m2a1-baseline-hard-flip-activation

# Manual edit tests/perf/baseline.json
# (or via script that reads FP rate + history count)
python3 scripts/perf/activate-hard-flip.mjs --owner "Halil"

# Commit + push + open PR
git add tests/perf/baseline.json
git commit -m "feat(perf-v3-m2a1): baseline hard-flip activation — warn-only → hard-fail"
git push -u origin feat/v3-m2a1-baseline-hard-flip-activation
gh pr create --repo Halildeu/platform-web ...
```

### 4.3 Workflow update (warn-only flag remove)

`.github/workflows/gate-m2a-auth-route-budget.yml`:

```yaml
env:
  PERF_WARN_ONLY: '0'  # Önceki '1' — hard-flip activation
```

OR if owner wants gradual:
```yaml
env:
  PERF_WARN_ONLY: ${{ inputs.warn_only || '0' }}  # Default flip; owner can override per-PR
```

---

## 5. Hard-Flip Post-Activation Behavior

### 5.1 What changes

| Before (warn-only) | After (hard-fail) |
|---|---|
| Budget threshold breach → exit 0 | Budget threshold breach → **exit 1 (block)** |
| FP regression → noise but mergeable | FP regression → **PR blocked until fix** |
| History entries grow infinitely | FIFO 30 entries / route (sliding window) |

### 5.2 What stays same

- **Validity hard-fail**: Auth/redirect/sentinel/no-valid-runs → exit 1 (warn-only does NOT mask) — Codex R4 split korunuyor
- **4 measured routes**: same routes, same budgets initially
- **N≥3 measurement**: per-run methodology unchanged

### 5.3 Regression handling

PR breaks budget threshold → CI fail → developer:
1. Fix code regression OR
2. Update budget (justified threshold increase with Codex peer review) OR
3. Owner explicit waiver (HARD RULE governance debt — follow-up fix PR required)

---

## 6. Activation Date Calculation

```
M2a1 first measurement: 2026-05-15
+ 14 days = 2026-05-29 minimum
```

**Earliest activation**: 2026-05-29.

**Realistic activation**: After 14-day window + FP rate verify + Codex peer review. Expected **2026-06-01 → 2026-06-05** range.

**Note**: D30 atomic cutover (Faz G) may happen 2026-05-29 ↔ 2026-06-05 range too. **Hard-flip activation post-cutover ideal** (cutover sırasında baseline volatility breaks).

---

## 7. Risk Register

| Risk | Probability | Impact | Mitigation |
|---|:-:|:-:|---|
| FP rate > threshold | Medium | High | Continuous measurement → tune budgets before flip |
| Cutover-window collision | Medium | Medium | Defer hard-flip to T+72h post-cutover |
| Real regression masked | Low | High | Validity hard-fail catches actual outages; threshold is performance only |
| Owner activation delayed | Medium | Low | Documentation explicit; manual flip simple JSON edit |

---

## 8. V3 Backlog Item Cross-Reference

This runbook activates **V3 Backlog Item #3** (per Faz G transition plan §7 V3 follow-ups):
- ✓ #3 M2a1 baseline hard-flip (14-gün history + threshold ratification)

Related V3 items:
- #1 GHA→testai connectivity (self-hosted runner) — required for CI-gated continuous measurement
- #2 fin-muhasebe-detay dynamic seed — when seeded, baseline.json adds fin-muhasebe-detay entry
- #4 Real-traffic 24-72h post-cutover — informs prod baseline (vs current testai baseline)

---

## 9. HARD RULE Compliance

- ✅ Pre-Production Full Authority: agent autonomous history accumulation + FP computation
- ✅ Continuous Autonomous Mode: V2.1 closure → V3 hard-flip prep zinciri
- ✅ Cross-AI Peer Review: round 9 expected when activation PR opened
- ✅ No Closure Language: "hard-flip activation" = next phase activation, not closure
- ✅ No Fake Work: FP rate gate prevents premature flip (would be fake-green)
- ✅ Plan Consensus Autonomy: Codex AGREE on flip → no user re-approval

---

## 10. Audit Trail

- V2.1 M2a1 closure: platform-web PR #527 e3922a37b3 (2026-05-15)
- V2.1 9/9 closure: gitops PR #682 092f921861 (2026-05-15)
- Faz G transition plan: gitops PR #683 7b6ee46eb3
- O1/O3/O6 agent verify: gitops PR #685 4572f0eb9e
- D30 cutover runbook: gitops PR #687 (this commit chain)
- This runbook: V3 backlog item #3 prep
- Codex chains: `019e2a4f` (V2.1 strategic) + `019e2b00` (M2a1 8-round) + `019e2c83` (R8 AGREE) + `019e26f9` (G2 sliding-baseline-check pattern)

---

## 11. Cross-AI Peer Review

Implementer AI:   Claude
Reviewer AI:      Codex
Codex thread:     019e2c83-f12e-7650-9721-be73397abc0f
Verdict:          AGREE (V2.1 M2a1 R8 inherited — bu runbook V3 hard-flip prep downstream)
Same-provider exception: N/A
Verdict reason:   V3 M2a1 hard-flip activation runbook — V2.1 M2a1 closure'dan 14-gün sonra warn-only → hard-fail flip için kriterler + agent autonomous steps + owner activation. Yeni implementation YOK; doc-only V3 prep. Activation PR sırasında Codex round 9 cross-AI review zorunlu.
