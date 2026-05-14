# PERF-INIT-V2 — Prod-Readiness Sub-Wave v9.1

> **Belge kodu**: `PERF-INIT-V2-prod-readiness-v9.1`
> **Tarih**: 2026-05-14
> **Sahip**: Halil
> **AI Orchestration**: Claude (implementer default) + Codex (reviewer default)
> **Status**: Onay bekliyor (AI consensus tur-2 absorb sonrası tur-3 AGREE bekleniyor)
> **Codex thread**: `019e2650` (3-tur plan-time istişare)
> **Baseline plan**: [PERF-INIT-V2-plan.md](./PERF-INIT-V2-plan.md) (v1.0, 2026-05-11 onaylı)
> **Cross-repo mirror**: `platform-web/docs/performance/PERF-INIT-V2-plan.md` §11 Roadmap revision history v9 (2026-05-14)

---

## §1. V2.0 Anonymous Optimization Acceptance

**Codex tur-2 dil disiplini**: HARD RULE No-Closure Language → "CLOSED" kelimesi YASAK; aşağıdaki ifade authoritative:

> **V2.0 optimization tranche**: accepted for anonymous `/login` scope; V2.1 prod-readiness gates pending.

### §1.1 V2.0 Anonymous Measurement Snapshot

Testai `BUILD_SHA=2a59704` 4-canary post-B5b2 admin on-demand, median-of-3 Playwright runs, `/login` cold-anonymous:

| Metric | Pre-V2 (est.) | V2.0 son | Delta | Sektör konum |
|---|---|---|---|---|
| transfer | 49 MB | 2,344 KB | **-95.2%** | 🟡 "iyi"; leader 800 KB **3× uzak** |
| decoded JS | 49 MB | 9,088 KB | **-81.5%** | 🟡 "iyi"; leader 3 MB **3× uzak** |
| LCP | 3,208 ms | **1,016 ms** | **-68.3%** | 🏆 **LEADER** (<1,500 ms) |
| FCP | 3,188 ms | 1,000 ms | -68.6% | 🟢 good (<1,800 ms) |
| TBT | n/a (proxy 96 ms) | 71 ms | -25 ms | 🟢 iyi (leader 50 ms 21 ms uzakta) |
| CLS | n/a | 0.004 | — | 🏆 **LEADER** (<0.05) |
| heap | 242 MB | 40 MB | -83.5% | 🟢 mükemmel |
| resources | 171 | 64 | -62.6% | 🏆 **LEADER** (≤80) |
| TTFB | 44 ms | 40 ms | -4 ms | 🟢 excellent |
| protocol | 171× HTTP/1.1 | 64× h2 (100%) | -107 req | 🟢 multiplexed |

**Sonuç**: 8 KPI'nın 6'sı **leader/mükemmel içeride**; 2'si (transfer + decoded byte) "iyi" tier'inde leader'a 3× uzakta → **accepted residual** (V3 PERF-ARCH initiative scope, §3).

### §1.2 V2.0 Authenticated Route Coverage Gap

`/home` + `/admin/users` + `/admin/access/roles` + `/admin/reports/fin-muhasebe-detay` ölçülemedi → **M2a auth-storage seed yok**. V2.0 anonymous slice acceptance prod-readiness eşiği için **yetersiz**; V2.1 P0 M2a measurement bu gap'i kapatır (§2.1).

---

## §2. V2.1 Prod-Readiness Sub-Wave

**Tanım**: V2.0 optimization tranche'i prod-ready hale getir. Faz G prod cutover öncesi gate. Authenticated route evidence + pager-backed monitoring + truth alignment + governance formal gate.

### §2.1 V2.1 P0 PR'ları (sequence)

| Sıra | PR-ID | Konu | Repo | Bağımlılık |
|:---:|---|---|---|---|
| 1 | **PR-PMD-v9.1** | Truth alignment | platform-k8s-gitops (canonical) + platform-web (mirror sync) | — |
| 2 (paralel) | **PR-V2.1-B3c-prod** | B3c prod long-cache promote + stale bundle smoke | platform-k8s-gitops | — (spawn chip absorb) |
| 2 (paralel) | **PR-V2.1-Ops-A** | Alert receiver (native Slack veya OSS GitHub receiver) | platform-k8s-gitops | — |
| 3 | **PR-V2.1-M2a0** | Test persona + Vault contract | platform-k8s-gitops (Vault seed) + Keycloak admin REST | — |
| 4 | **PR-V2.1-M2a1** | Playwright auth-storage runtime-gen + authenticated route budget | platform-web | M2a0 |

**P0 exit order** (uygulama sırası paralel olabilir, acceptance sırası):
- B3c prod PASS (natural cron fire `result=PASS`)
- Ops-A synthetic alert delivery proof
- M2a authenticated measurement raporu

### §2.2 PR-PMD-v9.1 DoD

- (a) Plan v1 baseline'ı dokunulmaz; bu v9.1 doc'u **ayrı patch**
- (b) Plan v1 hedef matrisi (§2.2 v1) sektör-tier semantiği ile **drift YOK** olarak işaretlensin (`hard fail` vs `improvement milestone` vs `leader target` vs `accepted residual` 4-tier explicit)
- (c) `current-state.md` Session 50 status writer LIVE + prod B3c FAIL reflect
- (d) Cross-repo: platform-web tarafındaki PMD §11 Roadmap revision history v9.1 entry eklendi
- (e) Codex thread `019e2650` 3-tur audit trail bu doc'un §6'sında yazılı

### §2.3 PR-V2.1-B3c-prod DoD

- (a) `kustomize/overlays/prod/api-gateway/nginx-cache.configmap.yaml` — test pattern'ine (`overlays/test/...`) eşit (PR #558 baseline)
- (b) Selective apply + smoke verify (`curl -I` hashed asset `Cache-Control: max-age=31536000.*immutable`)
- (c) **Stale bundle recovery contract** (Codex tur-2 EXPAND):
  - Hashed asset (`/assets/*.js`, `*.css`, fonts) → `Cache-Control: public, max-age=31536000, immutable`
  - `remoteEntry.js` → `Cache-Control: no-store` veya kısa revalidate
  - HTML (`index.html`) → `Cache-Control: no-cache, must-revalidate`
  - 404 stale asset → long-cache **almıyor** doğrulama
  - Bundle rollover smoke (Section §4.7 plan): yeni image deploy sonrası eski hashed asset 404'lerse `installStaleBundleRecovery()` hard-reload tetikliyor
- (d) Prod status CM `result=PASS` natural cron fire sonrası (≥1 natural fire `30 */6` Europe/Istanbul)
- (e) Codex peer review thread (yeni)

### §2.4 PR-V2.1-Ops-A DoD (Codex tur-2 D27 upstream-first absorb)

**Tercih sırası**:
1. **Preferred A** — `SLACK_PERF_WEBHOOK_URL` secret varsa → AlertManager native Slack receiver (en düşük risk, sıfır custom)
2. **Preferred B** — Secret yoksa → **`alertmanager-github-receiver`** OSS image (digest-pinned, token Vault/ESO, labels/throttle config) — kendi receiver yazma
3. **Fallback C** — GHA scheduled poller (en zayıf, K8s token taşıma sorunu)

**DoD**:
- (a) Receiver image digest-pinned (moving tag YASAK)
- (b) Synthetic alert üretilir (test cluster intentional CrashLoop deploy veya `failures>0` simüle)
- (c) Mesaj/issue gözlenir
- (d) **Dedupe key**: `alertname + cluster + namespace + route/status-cm-name`
- (e) Resolved → issue comment veya close lifecycle tanımlı
- (f) Runbook `docs/runbooks/V2.1-alert-receiver.md`: owner + throttle (`group_interval: 5m`, `repeat_interval: 6h`)
- (g) Token Vault path: **`kv/platform/governance/github-bridge`** (canonical governance/automation credential, test persona DEĞİL); test/prod ayrımı için subpath: `kv/platform/governance/github-bridge/test` ve `.../prod` (Codex tur-3 polish absorb)

### §2.5 PR-V2.1-M2a0 DoD (Codex tur-2 Vault path absorb)

**Vault path**: `kv/platform/test-personas/perf-auth` (NOT `kv/platform/<service>` — runtime secret + fixture credential karıştırma önle)

**Contract**:
- (a) Keycloak admin API ile `test-perf-persona@local` user oluştur
- (b) Vault `kv/platform/test-personas/perf-auth` yaz: `username`, `password`, `persona_id`, `rotation_due`, `kc_user_id?`
- (c) K8s Secret `perf-auth-test-persona` (namespace `platform-test` only, prod overlay YOK)
- (d) ESO sadece `platform-test`, RBAC yalnız perf smoke / Playwright job okuyabilir
- (e) **HARD RULE** doğrulama: Kullanıcının login user şifresi YASAK — ayrı persona ✓
- (f) Test persona browser smoke `/home` + `/admin/users` 200 dönüyor

### §2.6 PR-V2.1-M2a1 DoD (Codex tur-2 storageState hygiene absorb)

**Credential hygiene**:
- (a) `storageState.json` **committed fixture DEĞİL** — runtime-generated from Vault-backed test persona
- (b) Artifact short-lived (CI run sırasında üretilir, ephemeral)
- (c) `.gitignore` altında `tests/perf/storageState*.json`
- (d) **GitHub Actions OIDC → Vault short-lived token**; long-lived Vault token GitHub secret olarak tutulmaz (Codex tur-3 polish absorb: credential hygiene sertleştirme)

**Route budget matrix**:
- (a) `/home` + `/admin/users` + `/admin/access/roles` + `/admin/reports/fin-muhasebe-detay`
- (b) Rendered-sentinel guard her route için (Codex iter-2 PMD §2.4 measurement validity)
- (c) `BUILD_SHA` recorded
- (d) Median of N runs (N≥3, ideal 5)
- (e) İlk authenticated measurement raporu commit

### §2.7 V2.1 P1 PR'ları (parallel after P0 ladder)

| PR-ID | Konu | DoD özet |
|---|---|---|
| **PR-V2.1-Ops-B** | Status writer monotonic alert | PrometheusRule: `failures>0` / `result=FAIL` / `lastFire` stale → **auto-issue** (auto-PR YASAK — root cause değişken); throttle 6h; issue dedupe/close lifecycle (Codex tur-2 NARROW absorb) |
| **PR-V2.1-B3b1** | Brotli edge | `fholzer/nginx-brotli:mainline` **digest pin** (Codex tur-2: moving tag YASAK); ya da mevcut nginx imajda Brotli module availability ÖNCE araştır; `nginx -V` proof; testai canary first; `Content-Encoding: br` hashed asset proof; rollback config; no-double-compression check |
| **PR-V2.1-B3d0** | CSS attribution audit | source-map-explorer CSS bundle breakdown; AG Grid + chart CSS payı dolar (ölçüm-driven) |
| **PR-V2.1-B3d1** | AG Grid + chart CSS route-lazy | Critical CSS plugin DEĞİL — sadece route-lazy import |
| **PR-V2.1-B3d2** | Critical extract plugin (conditional) | **Ölçüm kanıtı varsa**: critters/vite-plugin-critical FOUC riski + layout drift mitigation |
| **PR-V2.1-G2** | Sliding baseline drift gate | `tests/perf/baseline.json` 7/14 günlük median + variance band; live-vs-CI ayrımı; warn-only 2 hafta → hard gate (Codex tur-2 EXPAND: **flake budget şartı** — son N run false positive rate < threshold) |
| **PR-V2.1-ABM-1** | 4-canary reproducibility soak | Measurement **artifact + runbook** (CI workflow DEĞİL — Codex tur-2 absorb: lab vs live karışmasın); 24-72h veya min 3 doğal cron fire kanıt; budget delta variance < %5 |
| **PR-V2.1-GOV-1** | Cross-AI enforcement + branch protection | PR template field enum (Codex tur-2: regex YASAK); CI check `pr-cross-ai-audit.mjs`; 10 must-pass required (§2.10); emergency override policy açık |
| **PR-V2.1-M2a2** | Auth-storage rotation policy | Rotation cadence doc (90 gün); Vault rotation runbook; negative test (expired session → redirect-to-login measurement reject) |
| **PR-V2.1-B5b3e-Phase3** | Grafana panel + auto-issue automation | `frontend-federation-smoke-status` ConfigMap Grafana panel (failures sparkline, last fire timestamp, result heatmap); auto-issue formatting (Ops-A pattern reuse); synthetic drill |

### §2.8 V2.1 P2 (advisory, Faz G blocker DEĞİL)

| PR-ID | Konu |
|---|---|
| **PR-V2.1-M2c** | Lighthouse-CI cluster-side (advisory, long-tail) |
| **PR-V2.1-S2-rehome** | Spring config root-cause → runtime config/drift backlog'a re-home (ayrı owner, PERF critical path DEĞİL) |
| **PR-V2.1-B4c-conditional** | i18n async — analyzer >300 KB i18n payı + M2a hard fail trigger |
| **PR-V2.1-B4d-appendix** | Fonts N/A documented (active row'dan çıkar) |
| **PR-V2.1-B5d-decision-record** | B5d0 negatif / B5d1-B5d2 CANCELLED decision record (aktif backlog'dan kaldır) |

### §2.9 V2.1 Closure 9-Madde Exit Criteria (Codex tur-2 final)

1. **PMD/current-state truth aligned** — v9.1 PMD, current-state, roadmap revision aynı status'u söylüyor; no overclaim
2. **Prod B3c status writer PASS** — B3c prod promoted, stale bundle contract smoke PASS, **≥1 natural cron fire `result=PASS`**
3. **Authenticated route matrix measured** — 4 route + rendered-sentinel + Vault-backed seed runtime-generated + BUILD_SHA recorded
4. **Alert receiver synthetic proof** — Slack veya GitHub issue receiver gerçek synthetic alert'i aldı; throttle/dedupe/runbook
5. **Baseline ratchet active** — 7/14 gün median (veya başlangıç için min 3-run median); warn-only tarihi + hard-fail activation tarihi yazılı
6. **Status writer observation clean** — **24-72h veya 3 natural fire clean** (7 gün YOK; Faz G freeze öncesi gerekirse ayrıca soak)
7. **Branch protection + cross-AI audit live** — 10 required checks, PR template/CI audit çalışıyor, emergency override policy açık
8. **Artifact traceability** — Her ölçümde BUILD_SHA + frontend image digest + route + auth persona + browser version + cache mode kaydedilmiş
9. **Accepted residuals explicit** — Byte leader gap V3'e taşınmış; M2c/Lighthouse/S2/B4c blocker değil

### §2.10 V2.1-GOV-1 Branch Protection 10 Must-Pass Required

Conservative tier (Codex tur-2: 13 hard gate → 10 must-pass + advisory ayrımı):

| # | Required check | Why required |
|:---:|---|---|
| 1 | `lint` | Always-on, deterministic, repo-local |
| 2 | `unit-tests` | Always-on |
| 3 | `build` | Always-on |
| 4 | `gitleaks` (secret scan) | Security |
| 5 | `CodeQL` | Security (repo'da stable ise) |
| 6 | `drift-pr-time-render` (kustomize render + boundary check) | Drift gate |
| 7 | `on-demand-federation-guard` | B5b3 hard gate (30 invariants) |
| 8 | `bundle-size` / `size-limit` | Performance budget |
| 9 | `perf-budget` (warn-only mode while M2a pending; hard mode after M2b live) | Performance regression |
| 10 | `cross-ai-audit` | Governance (V2.1-GOV-1 introduces) |

**Advisory / scheduled / non-required**:
- `Visual Invariant Matrix` (flaky/browser-heavy)
- `a11y` (ilk faz advisory, stabilse later required)
- `D29 evidence` (live evidence, PR-time required DEĞİL — post-merge/runbook gate)
- `No-Closure Language` (docs lint advisory; false positive üretirse required değil)
- `Lighthouse-CI` (P2 advisory)
- Natural cron / status writer (scheduled signal, branch protection check DEĞİL)

**Emergency override**:
- `enforce_admins: false` (operator emergency override için)
- Bypass list: NONE (audit immutable)
- Override sonrası: aynı gün follow-up PR + audit log entry

---

## §3. V3 Deferred Initiative — PERF-ARCH-V3

**Tanım**: Architecture-level perf push; V2 scope DEĞİL.

**Açılış koşulu** (en az 1):
- V2.1 closure sonrası kullanıcı/SLA byte hedeflerine push gerektirirse
- Auth route hard fail kalırsa (M2a hard gate sonrası ölçülen `/home`/`/admin/*` budget'ı aşıyorsa)

**Scope** (Codex tur-2 NARROW absorb):

| Item | Description | Risk |
|---|---|---|
| Root shared retirement | Remove root `@mfe/design-system` shared entry; force consumers to subpaths | Untested, high blast-radius |
| DS multi-package split | `@mfe/ds-light`, `@mfe/ds-primitives`, `@mfe/ds-components` (5+ share-scopes) | Architecture initiative, separate planning |
| Build-time DS surgery | Custom Vite plugin manually split root barrel pre-MF | Reject unless no alternative |
| Accept DS root cost | Current PERF-INIT-V2 path: do not attempt | **LIVE — accepted** |

**Status**: V2.1 closure'a kadar **açma YASAK** (Codex tur-1: "B5d-arch açtıracak kadar acil değil").

---

## §4. KPI Tier Semantik Ratchet (v9.1)

Codex tur-2 §15 absorb: 4-tier explicit (3-tier yetmiyor — `accepted residual` ayrı).

| Tier | Semantik | Enforcement |
|---|---|---|
| **Hard regression gate** | Same route + same mode + **same auth state** + same BUILD_SHA class + browser profile koşulu altında, current measurement +5% baseline'dan kötü DEĞİL | CI hard fail (M2b authenticated matrix live olunca) |
| **Improvement milestone** | Per-wave target; stepping stone | PR acceptance signal |
| **Leader target** | 12-ay aspirational; sektör mükemmel | Directional polestar, NOT hard gate |
| **Accepted residual** | V2 scope dışı, V3'e taşınmış kabul edilmiş gap | Explicit accepted; rapor edilecek (no overclaim) |

**Yeni v9.1 entries**:
- `/login` `transfer 2.34 MB` → **accepted residual** (leader 800 KB 3× uzak, V3 PERF-ARCH-V3 root shared retirement açılana kadar)
- `/login` `decoded 9.09 MB` → **accepted residual** (leader 3 MB 3× uzak, aynı V3 dependency)
- LCP/FCP/CLS/heap/resources → 🏆 **LEADER içeride** (mevcut V2.0 measurement authoritative)

---

## §5. Risk Register Updates (Codex tur-1 + tur-2 absorb)

### §5.1 Yeni risk eklendi (R20-R23)

| # | Risk | Mitigation |
|---|---|---|
| **R20** | Target drift — PMD v9 hard hedefleri ile v9.1 tier semantiği çelişirse yanlış acceptance | §4 4-tier explicit ratchet; PR-PMD-v9.1 truth alignment §2.2 |
| **R21** | Alert noise — `failures>0` flood | Group_interval 5m + repeat_interval 6h + stale/fail ayrımı + synthetic drill |
| **R22** | Test credential exposure — M2a seed hassas | Dedicated persona `kv/platform/test-personas/perf-auth` + Vault only + rotation doc + kullanıcı login YASAK |
| **R23** | CSS regression — critical plugin FOUC | B3d0 audit-first → B3d1 route-lazy first → B3d2 plugin conditional |

### §5.2 Materially mitigated (NOT closed — Codex tur-2 absorb)

| # | Risk | Status |
|---|---|---|
| **R8** | Federation version skew | **materially mitigated** (B5b3 guard chain S1-S6 + auxiliary patterns + on-demand-federation-guard CI hard gate); B5b2-hostfix lesson — guard yokken measurement bile yanıltabilir |
| **R9** | Semver mismatch | **materially mitigated** (aynı guard chain) |

### §5.3 Accepted residual

| # | Risk | Decision |
|---|---|---|
| **R24** | Byte leader gap (transfer 2.34 MB + decoded 9.09 MB hâlâ leader 3× uzak) | V3 PERF-ARCH-V3 initiative scope; V2 içinde açılmaz |

---

## §6. Codex Plan-Time Audit Trail (thread `019e2650`)

| Tur | Verdict | Önemli karar |
|---|---|---|
| 1 | REVISE | V2.0 anonymous + V2.1 prod-readiness + V3 deferred 3-katman ayrımı; M2a 3-tier (M2a0/M2a1/M2a2); B5d-arch V2 dışı; PR-S2 re-home |
| 2 | REVISE with `ready_for_impl: true` (15 düzeltme koşuluyla) | No-closure language fix; storageState hygiene; Ops-A D27 upstream-first; M2a0 Vault path ayrı namespace; 10 must-pass branch protection; 9-madde exit criteria; flake budget G2; field enum cross-AI gov |
| 3 | **AGREE** `ready_for_impl: final_true` (2 küçük polish §2.4(g) + §2.6(d) absorb edildi) | Plan-time artifact merge-ready; PR-PMD-v9.1 → B3c-prod ‖ Ops-A → M2a0 → M2a1 sequence onaylı |

---

## §7. Cross-AI Governance Formalization (v9.1)

### §7.1 PR Template Field Enum (Codex tur-2 absorb: regex DEĞİL)

Her PR'da zorunlu:

```markdown
## Cross-AI

Implementer AI:   [Claude | Codex | Gemini | Other]
Reviewer AI:      [Codex | Claude | Gemini | Other]
Codex thread:     019eXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
Verdict:          [AGREE | REVISE | PARTIAL]
Verdict reason:   <1-2 cümle>
Same-provider exception: [N/A | user-explicit-approval (`exception_reason: ...`)]
```

### §7.2 CI Check `pr-cross-ai-audit.mjs`

- Implementer + Reviewer **farklı provider** doğrula (HARD RULE Cross-AI Peer Review)
- Same-provider exception varsa: `user-explicit-approval` field dolu + commit/comment'ta açık beyan
- Thread ID UUID format
- Verdict enum

### §7.3 Branch Protection Live

- 10 must-pass required (§2.10)
- `enforce_admins: false` (operator emergency override)
- Bypass list: NONE (audit immutable)
- Conservative tier (Faz G öncesi acceptance)

---

## §8. Faz G Interaction

| Phase | Scope | Status |
|---|---|---|
| **V2.0** Anonymous Optimization | `/login` 4-canary measurement | accepted-anonymous-slice |
| **V2.1** Prod-Readiness | P0/P1 §2 — auth measurement + monitoring + governance | sıradaki sprint |
| **Faz G** Cutover Initiative | D30 atomic cutover, 72h rollback, browser smoke | AYRI initiative; V2.1 artifact'lerini giriş kanıtı tüketir |

**Faz G'yi PERF-INIT içine yutma**. V2.1 closure (§2.9 9-madde) sonrası Faz G triggered.

---

## §9. Onay

| Rol | Ad | Tarih | İmza |
|---|---|---|---|
| Owner | Halil | 2026-05-14 | ☐ |
| AI Consensus | Claude (synth) + Codex 3-tur (REVISE → REVISE-with-`ready_for_impl: true` → **AGREE `final_true`**) thread `019e2650` | 2026-05-14 | ✅ |

---

## §10. Codex Tur-3 Cevapları (resolved)

### §10.1 §1-§8 AGREE
**Codex**: AGREE. En önemli kazanım V2.0 anonymous acceptance ile V2.1 prod-readiness gate'in ayrılması.

### §10.2 Ops-A OSS receiver image
**Codex**: Native Slack receiver hâlâ Preferred A. GitHub issue fallback için `fluxcd/notification-controller` ÖNERİLMEZ (Flux event domain'i; AlertManager receiver doğal değil). `m-lab/alertmanager-github-receiver` veya benzer aday OK ama implementation PR'da şu **zorunlu checklist**:
- Aktif bakım durumu (son commit/release tarihi)
- Digest pin (moving tag YASAK)
- Non-root / container hardening
- GitHub issue dedupe + close lifecycle desteği
- Token Vault/ESO'dan geliyor
- Image provenance verify (Sigstore/Cosign varsa)

**Uygun OSS receiver doğrulanamazsa**: P0'da custom receiver yazma YASAK; iki yol:
- Slack secret external blocker olarak raporla (Sprint 2 A continuation)
- "Receiver selection spike" açıp 1-2 günlük araştırma + decision record

### §10.3 G2 flake budget tanımı
**Codex**: Sadece yüzde KULLANMA. Erken faz hybrid kural:
- `<=1 false positive in last 20 comparable runs` (cumulative window)
- `<3 false positives / 100 runs` (100-run window oluşunca)
- `Budget delta variance < %5` (ayrı metrik — variance tracking için)

**False positive tanımı**: aynı route + mode + auth + BUILD_SHA class içinde rerun geçiyor, source/deploy değişmemiş, status writer veya browser sentinel fail yok.

### §10.4 perf-budget warn → hard trigger
**Codex**: M2a1 ilk authenticated measurement **hard mode için YETERSİZ**. M2a1 = `warn-only baseline seed` başlatır. Hard mode kriteri:
- G2/ABM stabilizasyon sonrası (M2b)
- Min 3 ayrı zaman penceresi veya 20 comparable run
- Flake budget §10.3 sağlanmış
- Baseline JSON review edilmiş
- Accepted residual / hard fail ayrımı PMD'de net

### §10.5 V3 açılma koşulu (R24 accepted residual)
**Codex**: Sadece SLA byte hedefi değil — **3 trigger**, en az 1 yeterli:
1. Auth route hard fail kalırsa (M2a hard gate sonrası `/home`/`/admin/*` budget aşıyor)
2. Kullanıcı/SLA byte hedefi P0 derse
3. Faz G sonrası RUM/field feedback düşük ağ/cihaz segmentlerinde byte kaynaklı gerçek problem gösterirse (LCP iyi ama transfer/decoded şikayet)

### §10.6 Faz G transition (9-madde hard gate)
**Codex**: 2-aşama transition:
- **Faz G planning/discovery**: 9/9 beklemeden açılabilir
- **D30 cutover-freeze + cutover sign-off**: 9 madde **hard gate** — owner waiver olmadan değil
- 7/9 ile ilerlemek istenirse: **owner waiver** gerekli + hangi 2 gap'in cutover riskine dönüşmediği açık yazılmalı
- **Silent soft gate olmasın** (audit trail explicit)

---

## §11. Ready For Impl Decision

**Codex tur-3 final verdict**: **AGREE** `ready_for_impl: final_true` (thread `019e2650`).

> "Bu doküman plan-time artifact olarak merge'e uygun. Sonraki uygulama sırası da doğru: `PR-PMD-v9.1` → `B3c-prod` ve `Ops-A` paralel → `M2a0` → `M2a1`. Implementation PR'larında özellikle Ops-A receiver seçimi ve M2a Vault/OIDC sınırı tekrar review edilmeli; bu doc o işlere yeterli kontratı veriyor."

**V2.1 sprint başlatma sequence** (AGREE'li):
1. Bu doc PR olarak aç + merge (cross-AI peer review chain audit footer'lı)
2. PR-V2.1-B3c-prod (spawn chip absorb) ‖ PR-V2.1-Ops-A (paralel başla)
3. PR-V2.1-M2a0 (test persona Vault `kv/platform/test-personas/perf-auth`)
4. PR-V2.1-M2a1 (auth-storage runtime-gen + authenticated route budget)
5. V2.1 P1 wave (Ops-B + B3b1 + B3d + G2 + ABM-1 + GOV-1 + M2a2 + B5b3e-Phase3)
6. V2.1 closure 9-madde exit → Faz G transition

---

🤖 Generated by Claude (Anthropic) + Codex (OpenAI) cross-AI peer review chain. Thread `019e2650` tur-1+tur-2 absorb; tur-3 confirm bekleniyor.
