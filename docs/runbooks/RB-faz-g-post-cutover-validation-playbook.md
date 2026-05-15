# Runbook — Faz G Post-Cutover Validation Playbook (T+5m → T+72h)

> **Belge kodu**: `RB-faz-g-post-cutover-validation-playbook`
> **Tarih**: 2026-05-15
> **Sahip**: Halil (owner) + agent autonomous chain
> **Sprint**: V2.1 9/9 closure → Faz G freeze gate UNLOCKED → D30 atomic cutover → Post-cutover validation
> **Codex strategic consult**: thread `019e2cbf` gap #1 absorb — "Post-cutover validation playbook eksik. Persona bazlı browser smoke pass/fail matrix gerekli"
> **Prerequisites**: D30 cutover runbook `RB-faz-g-d30-atomic-cutover.md` + V2.1 M2a1 auth-storage pattern (platform-web PR #527)

---

## 1. Bağlam

D30 atomic cutover runbook §6-§8 T+5min → T+72h ana çerçeveyi sağlıyor (curl + pod health + Prometheus + alertmanager). Codex `019e2cbf` strategic consult HIGH önemli gap tespit:

> "Curl + pod health yetmez. Persona bazlı browser smoke olmalı: login, `/home`, `/admin/users`, `/admin/access`, `/admin/reports/users`, auth refresh, logout/re-login. Cutover runbook browser smoke'u işaret ediyor ama bunu ayrı pass/fail matrise çevirmek iyi olur."

Bu playbook persona browser smoke pass/fail matrix + RUM/field telemetry acceptance + checkpoint cadence detay sağlar.

---

## 2. Persona Browser Smoke — Pass/Fail Matrix

### 2.1 Personas

| Persona | Email | Privilege | Use case |
|---|---|---|---|
| **perf-test** | perf-test@local | Standard user | Anonymous → /login navigation, basic auth flow |
| **d35-admin** | d35-admin@example.com | superAdmin (allowlist) | Admin route coverage (/admin/users, /admin/access, /admin/reports/*) |
| **(test only)** halil-test* | halil-test@example.com | Admin variant | Multi-persona test (if needed) |

> HARD RULE — Kullanıcı Aktif Credential'ına Dokunma YASAK: `admin@example.com` (kullanıcının login user'ı) test sırasında ASLA kullanılmaz. d35-admin separate test persona zorunlu.

### 2.2 Smoke matrix (5 ana flow × 4 checkpoint)

#### Flow A: Anonymous /login navigation
- A1: Navigate `https://ai.acik.com/login` → 200 + corporate-login-button visible
- A2: Click → Keycloak SSO redirect → realm `platform` login form visible
- A3: No console error (>1 error red), no broken asset (no 5xx in network)

#### Flow B: d35-admin login (standardFlow)
- B1: Keycloak form fill (username + password) → submit
- B2: Callback to app origin (`https://ai.acik.com/home`)
- B3: localStorage canonical keys populated (`token`, `user`, `tokenExpiresAt`)
- B4: User dropdown shows `d35-admin` + admin badge

#### Flow C: 4-route cold-authenticated render
- C1: `/home` → sentinel `h1, h2, [role="heading"]` visible <5s
- C2: `/admin/users` → sentinel `h1, h2, [role="heading"]` + user list rows
- C3: `/admin/access` → redirect to `/access/roles` + sentinel visible
- C4: `/admin/reports/users` → sentinel `.ag-root-wrapper` + AG Grid data rows

#### Flow D: Auth refresh
- D1: Wait token expiry approach (60min from B2)
- D2: Refresh token flow exchange (no re-login)
- D3: API call after refresh returns 200 (not 401)

#### Flow E: Logout / Re-login
- E1: Logout button click → redirect to /login
- E2: Cookie cleared (Keycloak session cookies removed)
- E3: localStorage `token`/`user` cleared
- E4: Re-login navigate flow successful (Flow B repeatable)

### 2.3 Pass/fail criteria per flow

| Flow | All steps PASS | Partial PASS | Any FAIL → action |
|---|---|---|---|
| A | Continue B | Investigate A3 console (allowlist or block?) | A1/A2 fail → ROLLBACK (login broken) |
| B | Continue C | B3 partial — investigate localStorage shape | B1/B2 fail → ROLLBACK (auth broken) |
| C | Continue D | C2-C4 partial — degraded admin only | C1 fail → ROLLBACK (home broken); C2-C4 fail post-cutover-watch (downgrade) |
| D | Continue E | D2 partial — re-login workaround | D3 fail → INVESTIGATE (token contract drift) |
| E | All smoke PASS | E3 partial — security risk note | E1/E2 fail → INVESTIGATE (logout broken) |

---

## 3. Checkpoint Cadence — T+5m → T+72h

### 3.1 T+5m — Smoke (post-atomic-switch)

```bash
# Agent autonomous browser smoke (local Mac via prod endpoint)
cd /Users/halilkocoglu/Documents/platform-web
PERF_AUTH_USERNAME=d35-admin \
PERF_AUTH_PASSWORD=$(ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod get secret test-personas-perf-auth -o jsonpath='{.data.password}' | base64 -d") \
PERF_AUTH_APP_ORIGIN=https://ai.acik.com \
PERF_AUTH_KEYCLOAK_BASE=https://ai.acik.com \
PERF_AUTH_REALM=platform \
node scripts/perf/auth-storage-setup.mjs

# Browser smoke quick (1 run, 4 routes)
PERF_AUTH_STORAGE=tests/perf/.auth-storage.json \
node scripts/ci/route-performance-budget.mjs \
  --target prod --runs 1 \
  --routes "/home,/admin/users,/admin/access,/admin/reports/users" \
  --auth-storage tests/perf/.auth-storage.json --warn-only
```

**Required PASS (T+5m smoke)**:
- [ ] Flow A pass
- [ ] Flow B pass (login successful, canonical localStorage)
- [ ] Flow C pass (4 routes render sentinel)
- [ ] No "VALIDITY ERROR" in last-run.json
- [ ] All measurement runs runs=1, measurementInvalid=false

### 3.2 T+1h — Stabilization smoke

Same as T+5m **plus**:
- [ ] Flow D (auth refresh) tested
- [ ] Compare metrics vs T+5m: latency p95 within ±10%
- [ ] No new alerts in alertmanager-bridge
- [ ] No GitHub Issues `alertmanager-P0/P1` opened

### 3.3 T+4h — First high-traffic window (Türkiye iş saati başlangıcı)

Real-traffic verify (varsa pre-prod kullanıcı yok ama scenario rehearsal):
- [ ] T+1h smoke chain repeat
- [ ] Prometheus query: `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[15m]))` <baseline+10%
- [ ] Error rate `rate(http_requests_total{code=~"5.."}[15m])` <1%
- [ ] Pod state stable (no Pending/CrashLoopBackOff)
- [ ] ABM-1 federation smoke fire post-cutover (≤6h ago, result=PASS)

### 3.4 T+24h — First day complete

- [ ] All previous checkpoints repeat
- [ ] **Flow E** (logout/re-login) — full session lifecycle test
- [ ] ABM-1 4 natural fire (06/12/18/00 UTC) all PASS post-cutover
- [ ] No GitHub Issues alertmanager-P0/P1 open
- [ ] Backup chain still fresh (PG hourly, Vault daily 02:00 UTC, KC weekly Sunday)
- [ ] Compose containers still ayakta (warm rollback window)

### 3.5 T+72h — Final stabilization checkpoint

- [ ] All previous checkpoints repeat
- [ ] 12-fire ABM-1 chain (every 6h × 72h = 12 fires) all PASS
- [ ] No regression in 72h (latency, error rate, CLS, LCP)
- [ ] **GO decision**: compose decommission (containers stop, 7-day grace before remove)
- [ ] **NO-GO**: investigate + rollback OR extend warm window

---

## 4. RUM / Field Telemetry Acceptance (Codex Gap #4)

### 4.1 Metrik kataloğu

| Metric | Source | Acceptance threshold (warn-only baseline) | Hard-fail threshold (post-ratification) |
|---|---|---|---|
| Transfer KB cold | RUM | ≤baseline + 15% | ≤baseline + 5% |
| Decoded KB cold | RUM | ≤baseline + 15% | ≤baseline + 5% |
| LCP p75 | RUM | ≤baseline + 200ms | ≤baseline + 50ms |
| TBT p75 | RUM | ≤baseline + 200ms | ≤baseline + 50ms |
| CLS p75 | RUM | ≤0.10 (target); current 0.36 — high priority backlog | ≤0.10 |
| FCP p75 | RUM | ≤2.0s | ≤1.8s |
| INP p75 | RUM | ≤200ms | ≤150ms |

### 4.2 Low-bandwidth/device segment

Codex G2 sliding-baseline-check pattern post-cutover'a genişletilmeli:
- Low-bandwidth segment (3G/4G simulation)
- Low-CPU device segment (slow mobile)
- Median vs P95 split (median user vs worst-case 5%)

### 4.3 Dashboard (post-cutover V3 setup)

Grafana dashboard skeleton (V3 backlog #4):
- Panel 1: 4-route median LCP/TBT/CLS overlay (testai baseline → prod cutover transition)
- Panel 2: Error rate per route (5xx + 4xx breakdown)
- Panel 3: Bundle size delivered (transferKB cold vs warm)
- Panel 4: ABM-1 federation smoke status (PASS/FAIL/uninit) timeseries
- Panel 5: GitHub Issues alertmanager (open count + age histogram)

### 4.4 Acceptance review (T+72h GO decision input)

T+72h compose decommission GO/NO-GO **RUM evidence** içerir:
- [ ] No P75 regression >15% across 4 routes
- [ ] CLS not worse than pre-cutover (acknowledged 0.36 baseline)
- [ ] Error rate <1% sustained
- [ ] Low-bandwidth segment functional (no broken render)
- [ ] No fresh customer complaints (if applicable; pre-prod context — internal only)

---

## 5. Pass/Fail Matrix — Full T+0 → T+72h Aggregate

| Checkpoint | Flow A | Flow B | Flow C | Flow D | Flow E | RUM | ABM-1 | Result |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| T+5m | ✓ | ✓ | ✓ | n/a | n/a | n/a | smoke | **GO** |
| T+1h | ✓ | ✓ | ✓ | ✓ | n/a | partial | <6h ago PASS | **GO** |
| T+4h | ✓ | ✓ | ✓ | ✓ | n/a | within ±10% | PASS | **GO** |
| T+24h | ✓ | ✓ | ✓ | ✓ | ✓ | <15% regression | 4-fire PASS | **GO** |
| T+72h | ✓ | ✓ | ✓ | ✓ | ✓ | clean | 12-fire PASS | **GO → decommission** |

Any **FAIL** at any checkpoint → §6.3 D30 cutover runbook rollback trigger evaluate.

---

## 6. Agent Autonomous vs Owner Explicit Split

### Agent autonomous (this playbook executable)

- T+5m → T+72h browser smoke (4-route × N=1 measurement repeated)
- Prometheus query checks
- ABM-1 status verify (kubectl)
- GitHub Issues alertmanager-P0/P1 check (gh issue list)
- Pod state verify (kubectl get pod)
- Backup freshness check
- Compose state verify

### Owner explicit decisions

- T+5m GO/NO-GO (smoke result review)
- T+1h GO/NO-GO
- T+24h GO/NO-GO
- T+72h compose decommission GO/NO-GO
- Rollback trigger pull (final authority)
- Comms execute (stakeholder notify per §7 comms playbook)

---

## 7. Incident Command Integration (Codex Gap #2 prep)

Bu playbook'taki her checkpoint için **rollback authority**:

| Checkpoint | Primary on-call | Rollback authority | Comms responsible |
|---|---|---|---|
| T+5m | Owner (Halil) | Owner | Owner |
| T+1h | Owner | Owner | Owner |
| T+4h | Owner | Owner | Owner |
| T+24h | Owner (eğer atanmış secondary varsa rotate) | Owner | Owner |
| T+72h | Owner | Owner | Owner |

**Pre-prod context note**: Single-owner setup (Halil) — escalation matrix dahili. Production go-live sonrası secondary on-call atama V3 scope.

---

## 8. Comms Integration (Codex Gap #3 prep)

Her checkpoint için stakeholder notification timing (templates ayrı `comms-templates.md` runbook'ta — V3 backlog):

| Time | Audience | Template ref |
|---|---|---|
| T+5m | Internal (Halil + platform ops varsa) | `T+5m-cutover-started` |
| T+1h | Internal | `T+1h-stable-confirm` |
| T+4h | Internal + business owner (varsa) | `T+4h-business-hours` |
| T+24h | Internal + stakeholders | `T+24h-day-1-summary` |
| T+72h | Internal + decommission decision | `T+72h-decommission-go` |
| Rollback | All stakeholders | `rollback-executed-template` |

Pre-prod context — eğer external customer yoksa: "internal only" stakeholder list explicit.

---

## 9. HARD RULE Compliance

- ✅ Pre-Production Full Authority: agent autonomous browser smoke + Prometheus + kubectl
- ✅ Continuous Autonomous Mode: cutover prep zinciri devam
- ✅ Kullanıcı Aktif Credential'ına Dokunma YASAK: d35-admin separate persona; admin@example.com test'te ASLA
- ✅ Cross-AI Peer Review: Codex `019e2cbf` gap #1 absorb (strategic consult)
- ✅ No Closure Language: "post-cutover validation" = checkpoint chain, not final closure
- ✅ No Fake Work: persona browser smoke gerçek render + canonical localStorage verify

---

## 10. V3 Backlog References

Bu playbook V3 backlog'u aktive eden noktalar:
- **#4 RUM + ABM-1 continuous** — §4 RUM acceptance matrix + dashboard skeleton
- **#3 M2a1 hard-flip** — §4.1 hard-fail threshold (post-ratification) önişlemi
- **Codex gap #3 comms templates** — §8 referans (ayrı runbook V3 scope)
- **Codex gap #2 incident command** — §7 prep (production scope expand V3)

---

## 11. Audit Trail

- V2.1 closure: PR #682 092f921861
- Faz G transition plan: PR #683 7b6ee46eb3
- O1/O3/O6 verify: PR #685 4572f0eb9e
- D30 cutover runbook: PR #687 0c6c19a4f5
- V3 hard-flip activation: PR #689 b437552cfd
- **This playbook**: post-cutover validation Codex `019e2cbf` gap #1 absorb
- Codex strategic consult: `019e2cbf` (V2.1 closure → Faz G readiness gap analysis)
- M2a1 measurement pattern: platform-web PR #527 e3922a37b3 + auth-storage-setup.mjs

---

## 12. Cross-AI Peer Review

Implementer AI:   Claude
Reviewer AI:      Codex
Codex thread:     019e2cbf-2731-7653-8b4a-d8844179801b
Verdict:          AGREE (strategic gap #1 absorb — V2.1 closure R8 inherited)
Same-provider exception: N/A
Verdict reason:   Codex strategic consult `019e2cbf` gap #1 "post-cutover validation playbook eksik" tespit edildi. Bu playbook 5 ana flow × 5 checkpoint (T+5m → T+72h) pass/fail matrix + RUM acceptance + agent/owner split + incident/comms prep entegrasyonu sağlar. Yeni implementation YOK; D30 cutover runbook §6-§8 ile complement.
