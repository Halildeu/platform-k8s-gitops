# Faz 23 Live Evidence Re-Sync — k3d-test Read-Only Smoke (2026-05-24)

> **Status**: 🟢 Read-only test-cluster signals show no drift for pod/env/health/metrics observed in §2
> **Scope (this sweep)**: Agent read-only smoke against **k3d-test cluster** (SSH+kubectl HARD RULE #7 pre-authorized). **No state mutation. No new closure claim issued.** Prod cluster, browser smoke, legal review, Vault canonical patch, and external/operator gates were NOT re-verified and remain explicitly scoped out — see §4.
> **Trigger**: Codex `019e599c` H recommendation — "read-only live evidence + docs drift notu". Continues Session 49+ doc-truth-sync sweep series (PR #1002 + #1003 + #1005 + #1006 + #1009 + #935); H sweep checks whether the **k3d-test runtime signals** currently agree with the canonical doc surfaces' claims about k3d-test state.

## 1. Bağlam

Session 49+ doc-truth-sync zincirinden (PR #1002→#1009) sonra Codex `019e599c` adversarial consult önerisi üzerine yazılmıştır: agent'ın **doğrudan smoke ile bakabildiği k3d-test sinyalleri** + canonical doc claim'leri arasında drift var mı kontrol. Amaç: trust-building re-verification; status authority bu dosya **DEĞİL** (canonical = milestones.md / sprint-plan.md / RB-faz-23-charter.md / risk-register.md / feature-matrix.md).

## 2. Yapılan (read-only smoke via SSH+kubectl, k3d-test only)

Tüm sorgular `kubectl --context k3d-test -n platform-test` üzerinden read-only. State mutation yok. Output sanitized (raw secret değerleri yerine `len` + `sha256` + comparison signal'leri kullanıldı).

### 2.1 Pod state (k3d-test)

```
notification-orchestrator-774544dbdd-7cbln:
  ready: 1/1 Running
  imageID: ghcr.io/halildeu/platform-backend-notification-orchestrator@sha256:f3f8c497df87fd3ee394c224d7209b67714b026152c92ae119b0d8c4c16fbaf6
  started: 2026-05-23T07:00:29Z
  restartCount: 0
  age: ~28h stable at sweep time 2026-05-24T~09:00Z

permission-service-6ccc8987d7-zf5jv:
  ready: 1/1 Running
  imageID: ghcr.io/halildeu/platform-backend-permission-service@sha256:a87b8c3959cd65581da95eca8cbec5662041935a5dbb85fc7b5f1ccf324fca26
  started: 2026-05-23T06:41:52Z
  restartCount: 0
  age: ~28h stable at sweep time
```

### 2.2 Critical env vars — presence + sanitized signal (notification-orchestrator)

```
NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER=jetsms                 # plaintext config value — non-secret
NOTIFY_SECURITY_DEFAULT_ORG_ID=                              # empty string → fail-closed mode
NOTIFY_AUTHZ_INTERNAL_API_KEY=<redacted, 44 chars, sha256 see §2.4>
NOTIFY_ADAPTERS_WEBPUSH_ENABLED=true                         # plaintext config flag — non-secret
```

### 2.3 Critical env vars — presence + sanitized signal (permission-service)

```
PERMISSION_SERVICE_INTERNAL_API_KEY=<redacted, 44 chars, sha256 see §2.4>
ERP_OPENFGA_MODEL_ID=01KS8QE8T1EJ2DF5CRS4VV9YX1               # ULID model identifier — non-secret
```

### 2.4 Internal API key match check (sanitized cryptographic comparison)

```
source: notification-orchestrator env NOTIFY_AUTHZ_INTERNAL_API_KEY
target: permission-service     env PERMISSION_SERVICE_INTERNAL_API_KEY
len:    44 chars (both)
sha256: equal (raw values redacted; identity verified by direct string-compare at smoke time, not stored)
equal:  true → PR #996 ESO re-align result holds at runtime (orchestrator → permission-service auth aligned, 401 fix path)
```

Raw value intentionally not transcribed to evidence artifact. Comparison signal sufficient to confirm PR #996 outcome at runtime.

### 2.5 `/actuator/health` (management port 8081, in-cluster)

```
notification-orchestrator → {"status":"UP","groups":["liveness","readiness"]}
permission-service        → {"status":"UP","groups":["liveness","readiness"]}
```

### 2.6 Prometheus metrics (`/actuator/prometheus`, notification-orchestrator)

```
# WebPush channel delivery counter
notify_dispatch_outcome_total{channel="push",status="DELIVERED"} 1.0

# Abuse guard counters (metric source LIVE; baseline 0.0 — no enforcement triggers fired in observation window)
notify_abuse_blocked_total{reason="rate_limit"} 0.0
notify_abuse_blocked_total{reason="webhook_fanout_cap"} 0.0
notify_abuse_bypassed_total{reason="critical_severity"} 0.0

# Audit retention worker signal
notify_audit_retention_last_success_timestamp_seconds 1.779588E9   # = 2026-05-24T02:00:00Z (~6h before sweep)
notify_audit_retention_partitions_detached_total 0.0
notify_audit_retention_partitions_dropped_total 0.0

# OpenFGA authz enforcement signal
notify_authz_disabled_state 0.0                                     # 0 = enforce mode active in orchestrator's view

# DLQ visibility metric
notify_dlq_unreplayed 4.0

# Intent processing latency histogram (populated, samples observed)
notify_intent_processing_duration_seconds_bucket{...}
```

## 3. Canonical claim cross-reference — k3d-test signal alignment

> **Marker discipline**: Canonical doc currently labels each row as shown in the canonical surface column; **this sweep only checked the k3d-test signal listed in the third column**. Legal review, prod cluster, browser smoke, and full activation chain re-verification are NOT in this sweep's scope — see §4.

| Canonical claim (per canonical surface) | Source surface | k3d-test signal observed this sweep | Aligned? |
|---|---|---|---|
| OpenFGA PR #995 cutover — `ERP_OPENFGA_MODEL_ID=01KS8QE8T1EJ2DF5CRS4VV9YX1` on permission-service | `2026-05-22-openfga-notification-model-extension.md` §5 + sprint-plan T1 row | permission-service env var matches exactly (§2.3) | ✓ aligned |
| PR #996 ESO re-align — orchestrator `NOTIFY_AUTHZ_INTERNAL_API_KEY` matches permission-service `PERMISSION_SERVICE_INTERNAL_API_KEY` | RB-webpush-activation §3.11 "TRUTH CORRECTION 2026-05-23" | Cryptographic match confirmed (§2.4); 44-char len both sides, sha256 equal | ✓ aligned |
| Faz 24 PR-5.5 strict identity cutover — `NOTIFY_SECURITY_DEFAULT_ORG_ID=""` (fail-closed) | charter sub-faz table + PLAN.md D44 | env var empty string (§2.2) | ✓ aligned |
| M4 23.3 SMS test-cluster cutover — `NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER=jetsms` (test overlay) | sprint-plan T3.1 + milestones M4 | env var `jetsms` (§2.2) | ✓ aligned — **test cluster only**; prod cluster sha-6307428 NOT re-verified this sweep |
| OP.1 WebPush ENABLED flag at test runtime — `NOTIFY_ADAPTERS_WEBPUSH_ENABLED=true` | milestones M7 T4.2 line 192-205 | env var `true` (§2.2) | ✓ aligned — **flag-level only**; full activation chain (Vault/ESO/frontend/browser) reverification in RB-webpush §3.10/§3.11 gates, not in this sweep |
| WebPush `notify_dispatch_outcome_total{channel="push",status="DELIVERED"}` counter ≥ 1 at test cluster | sprint-plan "Last update" cites the metric | Counter observed `1.0` (§2.6); JVM-in-memory since pod start 2026-05-23T07:00:29Z | ✓ aligned at signal level — **counter ≥ 1 only**; new push delivery within last 6h NOT observed in pod logs |
| M3 T1.6 AbuseGuardService metric source LIVE | sprint-plan T1.6 / milestones M3 / feature-matrix M1/M2 | `notify_abuse_blocked_total` counters populated (baseline 0.0 — no enforcement triggers in observation window); `notify_abuse_bypassed_total` populated | ✓ metric source aligned — **counter existence only**; no enforcement trigger smoke run this sweep (no synthetic abuse traffic injected) |
| D42 audit retention worker active | PLAN.md D42 (truth-sync PR #1009) | `notify_audit_retention_last_success_timestamp_seconds` = 2026-05-24T02:00:00Z (~6h before sweep) | ✓ aligned — retention worker ran recently |
| OpenFGA authz enforcement active at orchestrator | feature-matrix K5 + charter | `notify_authz_disabled_state 0.0` (orchestrator client view) | ✓ aligned at signal level — **orchestrator's own metric only**; full subscriber#can_receive enforce path = Layer-2 23.2 v2 rescope per Codex `019e3c74` verdict B |
| Pods stable; no restart events | implicit in M3/M4 LIVE claims | restartCount=0 both pods (§2.1); ~28h stable | ✓ aligned |

**What this sweep does NOT re-verify (intentionally scoped out)**:
- R2 KVKK legal closure — that is a `019e5189` legal verdict canonical doc fact, not a runtime signal
- Prod cluster state (k3d-prod) — only k3d-test was queried this sweep
- Browser end-to-end smoke (RB-webpush §3.10 subscribe + §3.11 push delivery acceptance gates) — those use Chrome MCP / Playwright headless, not in this read-only kubectl sweep
- AbuseGuard enforcement under synthetic abuse traffic — no traffic injected; only metric source presence checked
- Full WebPush activation chain — only the flag-level env var + a single in-memory counter were checked; Vault VAPID 3-key seed + ESO uncomment + frontend VITE rebuild + browser registration gates are RB-webpush §3.10/§3.11 separate evidence

## 4. Operator-bound items (this sweep did NOT touch)

The list below is **not exhaustive** — it lists operator-bound follow-ups currently surfaced in canonical docs whose status this sweep also cannot affect:

| Item | Why operator-bound (this sweep cannot touch) | Doc surface |
|---|---|---|
| Vault canonical patch — `vault kv patch kv/platform/openfga model_id=01KS8QE8…` + `vault kv patch kv/platform/notification-orchestrator authz_internal_api_key=<perm-svc value>` | Requires `$TEST_ROOT_TOKEN` Vault access (agent yetki dışı) | sprint-plan operator queue + `2026-05-22-openfga-notification-model-extension.md` §5 item 7 |
| Revert PR #995 + #996 overlay overrides (post Vault canonical align) | Sequenced after Vault canonical patch | Operator queue |
| Runtime-artifact ledger `runtime_selector: null` → `vault` selector | Sequenced after Vault canonical patch | `runtime-artifacts/openfga-model/<digest>.json` ledger |
| `platform-backend/backend/openfga/model.fga` canonical update + OpenFGA model-drift gate re-baseline | Separate governance PR (cross-repo) | Governance follow-up |
| R9 D43 drill execution — Slack `#alerts-d43-drill` real webhook + prod activation | Requires Slack workspace seed + prod Vault seed (#853 + #854) | sprint-plan R9 D43; milestones M3 T1.4 |
| FBL mailbox activation — IMAP credentials + mailbox cron | Requires mailbox setup + ops slot | RB-fbl-mailbox-activation |
| Per-template Grafana DB RO role activation | Requires PG role grant + Grafana datasource registration | T4.3.7 follow-up |
| R24 Biotekno OTP allowlist provisioning (VFO outbound) | External provider provisioning | sprint-plan M4 |
| Prod SMS functional canary — KC `org_id=default` claim setup | Requires Keycloak operator action (RB-prod-canary-kc-claim-setup) | milestones M4 line 127; charter line 51 |
| DKIM tenant enable + DNS CNAME publish (Office 365 admin + DNS publish) | Requires tenant admin + DNS operator action | feature-matrix H4 + L1; charter line 51 |
| Mobile FCM/APNS — Faz 22.2 dep, out of M7 v1 scope | Different faz scope; not this sweep | milestones M7 T4.2 line 206 |

## 5. Sonuç (this sweep only)

- §3 listed canonical claims and the k3d-test signals checked; **for each row checked this sweep, the k3d-test signal aligns with the canonical surface label**. No drift was observed in the §2 pod/env/health/metric snapshot.
- §3 also explicitly carves out what was NOT re-verified (legal, prod, browser, full chain, enforcement trigger, Layer-2 enforce) — those rows are still anchored to their canonical evidence path; this sweep does not advance them.
- §4 lists the operator-bound items the sweep could not touch.
- This artifact does NOT change any canonical status marker; canonical status authority remains [milestones.md](../notify/milestones.md) + [sprint-plan.md](../notify/sprint-plan.md) + [risk-register.md](../notify/risk-register.md) + [feature-matrix.md](../notify/feature-matrix.md) + [RB-faz-23-charter.md](../runbooks/RB-faz-23-charter.md).

## 6. Cross-AI peer review

- **Implementer**: Claude (Anthropic) — session `youthful-kapitsa-676d9f` (otonom doc-truth-sync sweep series)
- **Reviewer**: Codex (OpenAI) — H scope plan-time `019e599c` AGREE + this PR review thread `019e59b1` REVISE→absorb→AGREE chain
- **HARD RULE adherence**:
  - SSH+kubectl pre-authorized (HARD RULE #7) — used only for read-only smoke
  - No Fake Work — §3 distinguishes per-row what the k3d-test signal actually proves vs what remains scoped out; §4 separately lists operator-bound items
  - No State Mutation — sweep is read-only kubectl + Prometheus scrape
  - Cross-AI provider-different — review via Codex thread
  - Secret hygiene — raw secret values redacted, only `len` + sha256 equality signal + presence/absence captured (Codex `019e59b1` blocker #1 absorb)
  - Closure language scoping — when referencing canonical "CLOSED" / "FULL ACCEPTANCE" labels in upstream docs, those are quoted as labels in upstream surfaces, not asserted as this artifact's own closure claims

## Referanslar (canonical surfaces)

- Session 49+ doc-truth-sync chain: PR #1002 (OpenFGA evidence) + #1003 (M6/charter 23.4) + #1005 (feature-matrix) + #1006 (sprint-plan R2) + #1009 (PLAN.md Faz 23 + D-decisions) + #935 hijiene
- Canonical status authority: [milestones.md](../notify/milestones.md), [sprint-plan.md](../notify/sprint-plan.md), [risk-register.md](../notify/risk-register.md), [feature-matrix.md](../notify/feature-matrix.md), [RB-faz-23-charter.md](../runbooks/RB-faz-23-charter.md)
- WebPush activation gate authority: [RB-webpush-activation.md](../runbooks/RB-webpush-activation.md) §3.10 / §3.11
- M3 R2 KVKK evidence: `2026-05-21-m3-r2-kvkk-closure-evidence.md`
- M4 prod cutover evidence: `2026-05-20-m4-prod-cutover-closure-evidence.md`
- OpenFGA model extension evidence: `2026-05-22-openfga-notification-model-extension.md`
