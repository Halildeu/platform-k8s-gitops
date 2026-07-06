# D29 Evidence Pipeline — Codex Sprint A P0 Item 3

> Codex retrospective Sprint A: "GitOps smoke gate workflow mandatory olmalı.
> #4 olmadan testte verified ledger statüsü güvenilmez. Promotion bot için
> central D30 gate."

## Problem

Mevcut promotion akışında prod overlay digest update'i için **D29 evidence
yokluğu** sessiz drift'e ve cutover-time outage'a yol açıyor:

- Backend CI digest yarat → manual `kubectl set image` direkt prod'a push
  edilebiliyor (deploy-backend-prod.yml)
- Test cluster'ında pod RUN bile edilmedi, prod'a "verify ettim" denmeden geçiyor
- D29 4-tier acceptance (Up / Functional / Secured / Zanzibar) hiçbiri
  zorunlu değil; evidence trail yok

**Codex 2026-05-04 retrospective**: cutover öncesi prod promotion'ı blokla
test smoke evidence olmadan. Single source of truth: `release-candidates/`
ledger entries.

## Mimari

```
[platform-backend kod değişim]
    ↓
[CI build + GHCR push (sha-<commit>)]
    ↓
[CI: scripts/promotion/generate-ledger.sh — TODO Sprint B]
    ↓ create release-candidates/<repo>/<sha>.json (status: built)
[CI: open gitops PR → test overlay digest update]
    ↓
[ArgoCD test sync → cluster'a yeni digest]
    ↓
[staging-sw systemd: smoke-test.timer (every 30min)]
    ↓
[d29-smoke-runner.sh test]
   ├── Tier 1: Up (pod Running + ready)
   ├── Tier 2: Functional (endpoint 200/401/403)
   ├── Tier 3: Secured (KC issuer matches expected)
   └── Tier 4: Zanzibar (allow + deny synthetic via OpenFGA)
    ↓
[/tmp/smoke-report-test-<ts>.json]
    ↓
[ledger-mark-verified.sh — auto-promotion PR]
    ↓ updates promotion.test.smoke_evidence + verified_at
[CI promotion-ledger-validate.yml — schema check]
    ↓ auto-merge
[release-candidates/ now has D29-GREEN entry]

⋯⋯⋯ (test → prod boundary) ⋯⋯⋯

[Operator: open prod-overlay digest update PR]
    ↓
[CI gate-d29-evidence-required.yml]
    ↓ enforce: each new prod digest has ledger.promotion.test.smoke_evidence GREEN
    ↓ FAIL → PR red → merge BLOCKED
    ↓ PASS → operator merges manually
[ArgoCD prod sync → strict rollout]
    ↓
[smoke-prod.timer (every 15min) — independent prod-side smoke]
    ↓ updates promotion.prod.smoke_evidence
```

## Bileşenler

### 1. Schema (committed)

**`schema/promotion-ledger-v1.schema.json`** — JSON Schema (Draft 2020-12)
defining ledger entry shape with strict `additionalProperties: false`,
required fields, regex patterns for digest/SHA/tag formats, and enum
constraints on status fields.

**`tests/promotion/fixtures/`** — Positive + negative test fixtures:
- `valid-test-ledger.json` — full GREEN entry (must validate)
- `invalid-bad-digest.json` — corrupted digest (must reject)

### 2. Smoke runner (host execution)

**`scripts/smoke/d29-smoke-runner.sh <env>`** — Runs against a deployed
cluster (test or prod), validates D29 4 tiers, emits JSON report at
`/tmp/smoke-report-<env>-<ts>.json`.

Tier outputs roll up into 3 ledger fields (Secured collapses into Up):
- `d29_up`: Tier 1 + Tier 3 status combined
- `d29_functional`: Tier 2 (endpoint shape)
- `d29_zanzibar`: Tier 4 (allow + deny synthetic)

**Why host execution, not GitHub Actions**: staging-sw clusters are on
private network (10.9.10.x); GitHub-hosted runners cannot reach them.
Self-hosted runner deferred until VPN tunnel available; host systemd
timer is the production-grade pattern.

### 3. Ledger updater

**`scripts/promotion/ledger-mark-verified.sh <smoke-report>`** — Reads
smoke JSON, finds matching ledger entries by digest match, updates
`promotion.<env>.smoke_evidence` + `verified_at`, opens auto-promotion PR.

Designed for `ExecStartPost=` integration with smoke-{test,prod}.service.

### 4. CI validation

**`.github/workflows/promotion-ledger-validate.yml`** — Triggered on
PRs touching `release-candidates/**` or schema/scripts. Runs:
- Positive fixture (must pass)
- Negative fixture (must fail)
- All changed PR ledger files
- Full directory scan on main push

### 5. CI gate (the central D30 enforcement)

**`.github/workflows/gate-d29-evidence-required.yml`** — Triggered on
PRs touching `kustomize/overlays/prod/**`. Runs
`scripts/promotion/gate-evidence-check.py`:

1. Compute new image digests (head − base)
2. For each new digest: require ledger entry with `promotion.test`:
   - `smoke_evidence.d29_up.status == GREEN`
   - `smoke_evidence.d29_functional.status == GREEN`
   - `smoke_evidence.d29_zanzibar.status` per **service policy** (B0b tightening):
     - For services with `jwt_validates: true` in services.yaml (default for
       backend Zanzibar consumers): **GREEN required** (AMBER → BLOCKED)
     - For services with `jwt_validates: false` (legacy core-data-service:
       gateway-validated, no own JWT decoder): GREEN or AMBER OK
   - `verified_at != null`
3. Missing or RED (or AMBER on Zanzibar-required service) → CI red → merge BLOCKED

This is **THE** D30 cutover gate that prevents:
- Manual `kubectl set image` style direct prod promotion
- Test-then-prod skip (ledger MUST have test verification first)
- Stale evidence (verified_at age can be additionally checked in future)

### 6. systemd integration

**`scripts/smoke/systemd/`**:
- `smoke-test.{service,timer}` — 30min cadence, test cluster
- `smoke-prod.{service,timer}` — 15min cadence, prod cluster

Both pull `origin/main` before running (selective checkout, D17 koruma)
and ExecStartPost runs `ledger-mark-verified.sh` for the produced report.

## Operasyonel akış

### Yeni servis digest test'e

1. platform-backend CI builds image, pushes GHCR `sha-<commit>`
2. (Sprint B) Auto-promotion bot: gitops PR opens with test overlay
   digest update + new `release-candidates/<repo>/<sha>.json` (status: built)
3. PR merges → ArgoCD test sync → cluster picks up new digest
4. Within 30min: `smoke-test.service` fires → `d29-smoke-runner.sh test`
5. If GREEN: `ledger-mark-verified.sh` opens auto-promotion PR with
   `promotion.test.smoke_evidence` filled
6. ledger-validate workflow auto-merges (schema-clean, evidence-truthful)
7. Now ledger entry shows `promotion.test.verified_at: <ts>`

### Prod promotion (operator-mediated)

1. Operator: branch from main, edit `kustomize/overlays/prod/kustomization.yaml`
   to bump digest to the test-verified one
2. Open PR
3. CI runs `gate-d29-evidence-required` →
   - Computes new prod digests (delta vs base)
   - For each digest: looks up ledger entry, checks D29 GREEN
   - If any digest lacks evidence → FAIL with detailed error
   - If all green → PASS
4. Operator reviews + merges (manual approval gate; not auto-merge)
5. ArgoCD prod sync → strict rollout
6. Within 15min: `smoke-prod.service` fires → updates
   `promotion.prod.smoke_evidence`

## Frontend profili — env-baked variant evidence (ADR-0022)

Yukarıdaki akış **backend** servisleri içindir: aynı image önce test'te sonra prod'da koşar. **Frontend** (platform-web) env-baked bir Vite SPA'dır — ortam config'i (API base URL, KC realm/issuer, feature-flag) build-time'da bundle'a gömülür. Her commit iki ayrı artifact üretir: `platform-web-frontend-testai` ve `platform-web-frontend` (prod). Test cluster'ı testai variant'ı koşar; prod variant hiçbir yerde koşmaz → normal test→prod ledger akışı uygulanamaz.

**Çözüm (ADR-0022 — `frontend-prod-variant-transient-smoke`)**: prod-variant artifact'ı k3d-test'te **transient** koşturulup smoke edilir.

- Script: `scripts/smoke/d29-frontend-variant-smoke.sh` — `d29-smoke-runner.sh`'a ek, dedicated runner.
- `platform-test` ns'de benzersiz etiketli (`evidence.platform/transient-smoke` + per-run id) Deployment+Service; `trap` cleanup; yönetilen `frontend` workload'ına dokunmaz.
- Tier eşlemesi:
  - `d29_up` GREEN — rollout + pod Ready + imageID digest match + `/build-info.json` source-sha.
  - `d29_functional` GREEN — `/` + entry/`remoteEntry.js` 200 + env-baking assertion (bundle'da `testai.acik.com`/`localhost:8080` host + `platform-test` realm YOK, `https://ai.acik.com` host + `serban` realm VAR) + `ai.acik.com` read-only public probe `2xx/401/403`.
  - `d29_zanzibar` **AMBER** (`allow_deny_synthetic: SKIP`) — statik SPA, Zanzibar düzlemi yok (`jwt_validates: false`).
- Gate uyumu: `gate-evidence-check.py` `jwt_validates:false` için `d29_zanzibar` GREEN/AMBER kabul eder → kod değişimi gerekmez. `SKIP` *status*'ü kabul edilmez; tier-status `AMBER`, alt-alan `allow_deny_synthetic` `SKIP`.
- Ledger **elle** doldurulur — `ledger-mark-verified.sh` her tier GREEN ister, dürüst AMBER'ı reddeder; frontend profili bu otomasyonun açık istisnasıdır.

## Hata senaryoları

### Smoke RED on test

- `ledger-mark-verified.sh` script detects exit_code != 0 and skips
  ledger update → `promotion.test.smoke_evidence` stays null → next
  prod-overlay PR will FAIL gate
- Operator investigates pod logs / endpoint, fixes the issue
- Re-runs smoke (manual: `bash d29-smoke-runner.sh test`) until GREEN

### Smoke can't reach cluster

- Exit code 2 (execution error)
- systemd marks unit as failed (TimeoutStartSec=300 + non-success exit)
- Operator: check kubectl context, pod state, network

### Stale ledger entry (digest replaced)

- New digest = new ledger entry (filename includes git_sha)
- Old entry is left as historical record (no GC during cutover phase)
- Renaming or modifying the entry post-write violates schema
  `additionalProperties: false` on key fields

### CI gate false negative

If gate-evidence-check.py is buggy and lets through unverified digest,
**runtime drift detector** is the second line of defense:
- It compares `pod imageID` ↔ `git/main overlay digest` independently
- Even if PR-time gate misses, runtime detector catches drift within
  5min and raises P1 alarm via alarm_receiver.sh

## Cutover yol haritası

| Aşama | Durum | Açıklama |
|---|---|---|
| **Schema + scripts + workflows committed** | this PR | Full ledger plumbing |
| **systemd units installed on staging-sw** | this PR (declarative) | Operator runs `systemctl enable smoke-{test,prod}.timer` |
| **First test smoke run** | post-merge | Verify smoke-test.service exits 0 (or detects real issue) |
| **First prod-overlay PR with gate** | post-cutover | Use a small no-op digest bump to verify gate works |
| **Auto-promotion bot** | Sprint B (separate PR) | platform-backend/web CI generates initial ledger entry |
| **Promotion ledger archival** | post-D30 (manual) | After 30 days, archive entries to `.archive/<year>/<month>/` |

## See also

- `docs/operations/promotion-ledger-design.md` — full architecture spec
- `scripts/drift-detection/check_env_drift.sh` — runtime drift detector
  (second line of defense)
- `scripts/drift-detection/alarm_receiver.sh` — pattern for systemd
  ExecStartPost integration
- `schema/promotion-ledger-v1.schema.json` — strict ledger entry shape
