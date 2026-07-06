# RB Faz 22.5 M6 — 50-PC Capacity Baseline + Wave Abort Evidence

> **Status**: SOURCE DRAFT
> **Runtime mutation**: NONE
> **Operator gate**: REQUIRED (50 PC IT pilot wave allocation + ring config + capacity metrics + Mavis ops on-call rotation + throttling guardrails)
> **Closure claim**: NO (source-side draft; M6 acceptance evidence operator + telemetry collects)
> **Tracked by**: [#1378](https://github.com/Halildeu/platform-k8s-gitops/issues/1378) Faz 22.5 M6 — 50-PC capacity baseline + wave abort evidence
> **Evidence template**: §6 capacity baseline + §7 wave abort drill format
> **Codex thread**: `019ea922` plan-time AGREE (pattern from RB-bl028b-prod-openfga-notification-model-cutover.md preflight + impact inventory)
> **Prerequisite**: M5 #1377 board-authoritative pilot closure (2-PC per owner 2026-06-10 amendment) + Mavis ops sign-off
> **Companion preflight**: `scripts/faz22-mass-deployment/wave-preflight.ps1` — per-device read-only health before each ring ramp (`-Mode preinstall-readiness` pre-push, `-Mode enroll-health` post-enroll). `overall=FAIL` holds the ring.
> **METRIC RECONCILIATION (2026-06-13, [#1493](https://github.com/Halildeu/platform-k8s-gitops/issues/1493) — Codex `019ebffb`)**: the PromQL identifiers in §3.1/§5 were PROPOSED names that did **not** exist as live series. They are now reconciled against what `endpoint-admin-service` actually exposes at `/actuator/prometheus` (Spring Boot `http_server_requests_seconds_*` + HikariCP `hikaricp_connections_*` auto-metrics) plus **one** instrumented counter. Three prerequisites are wired by the companion PRs and MUST be confirmed live before the wave:
> 1. **Scrape exists** — endpoint-admin-service had **no ServiceMonitor**, so `/actuator/prometheus` (mgmt port 8081) was never scraped. Added in this PR (`kustomize/base/apps/endpoint-admin-service/ops` via `ops-bundle`, test+prod). Confirm the target is **UP** in Prometheus before ring A.
> 2. **COLLECT_INVENTORY counter** — `endpoint_admin_agent_command_results_total{command_type,status}` is instrumented in platform-backend (the command type is not an HTTP `uri` label, so it is the one metric that cannot be mapped to an existing series). Requires the endpoint-admin-service image carrying it to be **deployed** before the wave; it is pre-registered at 0 so the series is present immediately on deploy.
> 3. **SQL** — device `status` enum is `PENDING_ENROLLMENT|ONLINE|STALE|OFFLINE|DECOMMISSIONED` (there is **no** `active`).
>
> **Hard gate**: if any abort-formula series below resolves **empty** (scrape down, image not yet deployed) the wave is **BLOCKED** — never treat a missing series as 0 (see §6 metric-absence gate). Run the §3.1 discovery query first to freeze the live label set (`uri` templates, the `service` label value, pod regex).

---

## 1. Scope

**M6** = 50-PC wave deploy (post M5 #1377 board-authoritative pilot closure; 2-PC per owner amendment). Hedef: ring-based rollout (group A 10 + group B 20 + group C 20) ile capacity baseline measure + wave abort formula validate + throttling/ring config LIVE.

**Source-side scope (this runbook)**:
- Capacity baseline runbook (PromQL queries + Grafana dashboard pointers + SQL queries)
- Wave abort formula (failure_rate + heartbeat_loss + queue_depth thresholds at scale)
- Synthetic/existing telemetry rehearsal pattern (HALILKOOLUB735 + Parallels VM data)
- Throttling/ring config (kubectl/ConfigMap pattern + Mavis ops on-call format)
- Ring rollout sequencer script template
- Mavis ops coordination (board issue cross-link + sign-off format)

**Out-of-scope** (operator-bound):
- 50 PC IT pilot wave allocation (asset tag + AD object + ring assignment)
- Ring config decision (group A/B/C size + sequence + delay between rings)
- Mavis ops on-call rotation (24/7 coverage for wave duration)
- Physical 50-PC ramp execution + capacity measurement + abort decision

## 2. Hard Constraints / Non-Goals

- **No M6 closure without 50/50 PC enrollment + capacity baseline measured + 1+ controlled wave abort drill + throttling LIVE** — partial PASS YASAK
- **No expansion to M7 rollback drill without M6 PASS + Mavis ops sign-off**
- **No ring skip without explicit Mavis on-call decision** — each ring acceptance gate sequential
- **No throttling bypass** — ring concurrent install limits enforced (kubectl/ConfigMap)
- **No capacity measurement without baseline reference** — pre-M6 baseline (HALILKOOLUB735 + Parallels VM) zorunlu

## 3. Pre-Flight Snapshot (24h before wave kickoff)

### 3.1 Backend Capacity Baseline

```bash
# PromQL (Prometheus / Grafana — endpoint-admin scraped via the ServiceMonitor
# added in this PR; mgmt port 8081 /actuator/prometheus).
#
# Selector note (Codex 019ebffb E): app-level series (hikaricp_*,
# http_server_requests_*, the instrumented counter) carry the
# Prometheus-Operator-added `namespace` + `service` + `pod` labels — NOT
# app.kubernetes.io/name. Select by service="endpoint-admin-service" (the
# Service name); pod=~"endpoint-admin-service-.*" is an equivalent fallback.
# cAdvisor container_* series carry only `pod`.

# (0) DISCOVERY — run FIRST to freeze the live label set (uri templates, the
#     `service` label value, pod regex) before trusting the queries below.
sum by (uri, method, status) (rate(http_server_requests_seconds_count{namespace="platform-prod", service="endpoint-admin-service"}[5m]))

# Heartbeat ingest rate (req/s) — POST /api/v1/agent/heartbeat is a 1:1 HTTP
# endpoint, so the Spring Boot auto-metric IS the heartbeat counter (no custom
# metric needed). Drop status= for total load; add outcome="SUCCESS" for OK-only.
rate(http_server_requests_seconds_count{namespace="platform-prod", service="endpoint-admin-service", uri="/api/v1/agent/heartbeat", method="POST"}[5m])
# Pre-wave baseline: ~5-10 heartbeat/min per device active

# COLLECT_INVENTORY rate — instrumented counter (command type is not a uri label,
# so this is the one series that had to be added; see platform-backend PR).
rate(endpoint_admin_agent_command_results_total{namespace="platform-prod", service="endpoint-admin-service", command_type="COLLECT_INVENTORY"}[5m])
# Add status="SUCCEEDED" for ingested-OK only; omit for all agent-reported outcomes.
# Pre-wave baseline: ~1-2 collect/hour per device

# Backend CPU/mem (cAdvisor — already real; container_* carry only `pod`)
container_cpu_usage_seconds_total{namespace="platform-prod", pod=~"endpoint-admin-service.*"}
container_memory_working_set_bytes{namespace="platform-prod", pod=~"endpoint-admin-service.*"}

# DB connection pool (HikariCP auto-metric; sum() over replicas; max default 10)
sum(hikaricp_connections_active{namespace="platform-prod", service="endpoint-admin-service"})
  / sum(hikaricp_connections_max{namespace="platform-prod", service="endpoint-admin-service"})
# Pre-wave baseline: <50% utilization
```

### 3.2 Pre-Wave Device State

```sql
-- PG query (platform-prod endpoint-admin DB):
SELECT
  source,
  status,
  COUNT(*) AS device_count
FROM endpoint_devices
GROUP BY source, status
ORDER BY source, status;

-- Pre-wave baseline: existing source breakdown (status enum:
--   PENDING_ENROLLMENT|ONLINE|STALE|OFFLINE|DECOMMISSIONED -- NOT "active")
-- "auto-enroll" status=ONLINE → M5 pilot devices reporting
-- "manual" status=ONLINE/OFFLINE → SRB-AIDENETIMPC + HALILKOOLUB735 + Parallels VMs
```

### 3.3 Backend HPA + Resource State

```bash
kubectl --context k3d-prod -n platform-prod get hpa endpoint-admin-service -o yaml
kubectl --context k3d-prod -n platform-prod top pod -l app=endpoint-admin-service
kubectl --context k3d-prod -n platform-prod get pdb endpoint-admin-service -o yaml
```

## 4. Ring Configuration

### 4.1 Ring Allocation Template

| Ring | PC Count | Wait Window | Concurrent Install Limit | Accept Criteria |
|---|---|---|---|---|
| **A** (canary) | 10 | 2h | 3 concurrent | 9/10 success (90%) |
| **B** (early adopters) | 20 | 6h | 5 concurrent | 18/20 success (90%) |
| **C** (broad) | 20 | 24h | 10 concurrent | 18/20 success (90%) |

### 4.2 ConfigMap Throttling Pattern

```yaml
# kustomize/base/apps/endpoint-admin-service/configmap-ring-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: endpoint-admin-ring-config
  namespace: platform-prod
data:
  rings.json: |
    {
      "active_ring": "A",
      "ring_a_concurrent_max": 3,
      "ring_b_concurrent_max": 5,
      "ring_c_concurrent_max": 10,
      "ring_a_pc_ids": [],
      "ring_b_pc_ids": [],
      "ring_c_pc_ids": []
    }
```

Backend reads ConfigMap → enforces concurrent install cap per ring.

### 4.3 Ring Sequencer Pattern (operator-driven)

```
1. Operator allocates 50 PC to rings (manually populate ring_a/b/c_pc_ids)
2. kubectl apply ConfigMap → backend reads → ring A throttling active
3. Mavis ops kicks off ring A wave (GPO push to ring A computers)
4. Wait 2h soak; collect ring A metrics
5. If acceptance PASS (9/10): kubectl patch ConfigMap active_ring=B
6. Mavis ops kicks off ring B wave
7. Wait 6h soak; collect ring B metrics
8. If acceptance PASS (18/20): kubectl patch ConfigMap active_ring=C
9. Mavis ops kicks off ring C wave
10. Wait 24h soak; collect ring C metrics
11. If acceptance PASS (18/20): M6 closure gate
```

## 5. Wave Abort Formula (50-PC scale)

### 5.1 Failure Modes (ring-aware)

| Mode | Detection | Ring A Threshold | Ring B Threshold | Ring C Threshold | Action |
|---|---|---|---|---|---|
| **Install fail** | Event 102 msiexec exit != 0 | ≥2/10 (20%) | ≥3/20 (15%) | ≥3/20 (15%) | Pause + investigate |
| **Heartbeat loss sustained** | >30min ping gap | ≥1/10 (10%) | ≥2/20 (10%) | ≥3/20 (15%) | Pause + network probe |
| **Backend CPU spike** | >80% sustained 5min | always | always | always | Throttle ring active reduce 50% |
| **Backend DB pool** | >80% sustained 5min | always | always | always | Throttle ring active reduce 50% |
| **Heartbeat ingest rate** | >2x baseline sustained 10min | warn | warn | warn | Monitor; throttle if persists |
| **Enrollment fail** | edge mTLS 5xx | ≥1/10 (10%) | ≥2/20 (10%) | ≥3/20 (15%) | M2 edge mTLS re-verify |

> **Reconciled series (§3.1, #1493)**: *Backend DB pool* = `sum(hikaricp_connections_active{service="endpoint-admin-service"}) / sum(hikaricp_connections_max{...})`; *Heartbeat ingest rate* = `rate(http_server_requests_seconds_count{…,uri="/api/v1/agent/heartbeat"}[5m])`; *Enrollment fail* app-5xx = `http_server_requests_seconds_count{…,uri="/api/v1/endpoint-agent/endpoint-enrollments/auto",status=~"5.."}`. **Caveat**: the "edge mTLS 5xx" detection is **edge/nginx-level** — a client-cert TLS handshake rejected at the edge never reaches endpoint-admin-service, so the app metric counts only enrollment requests that *did* reach the backend. Pair it with the nginx/edge error rate for full mTLS-failure coverage.

### 5.2 Abort Decision Tree (per ring)

```
For each active ring:
  every 15 min during wave window:
    metrics_collect:
      install_status: Event 102 + enrollment record
      heartbeat_age: now - last_ping (P95 across ring)
      backend_cpu: container_cpu_usage_seconds_total{pod=~"endpoint-admin-service.*"} (avg over 5m)
      db_pool: sum(hikaricp_connections_active{service="endpoint-admin-service"})
               / sum(hikaricp_connections_max{service="endpoint-admin-service"})
      enrollment_5xx: sum(rate(http_server_requests_seconds_count{service="endpoint-admin-service", uri="/api/v1/endpoint-agent/endpoint-enrollments/auto", status=~"5.."}[5m]))
                      / sum(rate(http_server_requests_seconds_count{service="endpoint-admin-service", uri="/api/v1/endpoint-agent/endpoint-enrollments/auto"}[5m]))
                      # app-surface 5xx only; edge/nginx mTLS rejections never reach the app (see §5.1 note)
    
    if (install_fail >= ring_threshold):
      pause ring + investigate root cause
      Mavis notify ABORT decision
    elif (heartbeat_loss >= ring_threshold):
      pause ring + network probe
      Mavis notify HOLD + investigate
    elif (backend_cpu > 80% sustained 5m):
      throttle ring concurrent_max /= 2
      Mavis notify THROTTLE
    elif (db_pool > 80% sustained 5m):
      throttle ring concurrent_max /= 2
      Mavis notify THROTTLE
    elif (enrollment_5xx > 1%):
      pause ring + M2 cert chain re-verify
      Mavis notify HOLD + investigate
    else:
      ring continues
```

### 5.3 Controlled Wave Abort Drill (acceptance gate)

```
M6 acceptance requires 1+ controlled abort drill — proof formula works:

Drill scenario (operator + agent):
  1. Mid-ring B wave (after 10/20 install success):
     Operator intentionally inject backend CPU spike (e.g., synthetic load)
  2. PromQL alert fires at >80% threshold
  3. Backend reads ConfigMap; reduces ring B concurrent_max from 5 → 2
  4. Mavis ops receives THROTTLE notification
  5. Inject load lifted
  6. ConfigMap restored to ring B concurrent_max = 5
  7. Wave resumes
  
Evidence:
  - PromQL alert firing screenshot
  - ConfigMap change applied + propagated to backend pods
  - Mavis CLI message log (THROTTLE notification + restore)
  - Wave completion delta (additional install records post-restore)
```

## 6. Capacity Baseline Acceptance

```
Pre-wave (metric-name freeze — RECONCILED 2026-06-13, #1493 / Codex 019ebffb):
  - The PromQL identifiers are reconciled (§3.1) against the real
    endpoint-admin-service exposition. Re-confirm live before ring A:
      curl -s <mgmt:8081>/actuator/prometheus \
        | grep -E 'endpoint_admin_agent_command_results_total|hikaricp_connections_(active|max)|http_server_requests_seconds_count'
      \d endpoint_devices   # status enum, no "active"
  - Reconciliation map:
      heartbeat ingest        -> http_server_requests_seconds_count{uri="/api/v1/agent/heartbeat"}   (Spring auto)
      COLLECT_INVENTORY rate  -> endpoint_admin_agent_command_results_total{command_type="COLLECT_INVENTORY"}  (INSTRUMENTED, platform-backend PR)
      db pool                 -> hikaricp_connections_active / hikaricp_connections_max   (HikariCP auto)
      enrollment 5xx          -> http_server_requests_seconds_count{uri=".../endpoint-enrollments/auto",status=~"5.."}  (Spring auto, app-surface)
      backend cpu/mem         -> container_* (cAdvisor, unchanged)

  - METRIC-ABSENCE WAVE-BLOCK GATE (Codex 019ebffb E): a missing series is NOT
    zero. Before ring A, assert each abort-formula series resolves to >0 samples;
    if any is empty (ServiceMonitor target down / image not yet carrying the
    counter), BLOCK the wave. Do NOT paper over absence with `or vector(0)`:
      count(hikaricp_connections_max{service="endpoint-admin-service"}) == 0                       -> BLOCK
      absent(endpoint_admin_agent_command_results_total{service="endpoint-admin-service"})         -> BLOCK
      absent(http_server_requests_seconds_count{service="endpoint-admin-service", uri="/api/v1/agent/heartbeat"}) -> BLOCK

For ring C closure:
  - 50/50 PC enrollment + GPO install LIVE
  - Backend CPU < 60% baseline (no sustained 80% breach)
  - DB pool < 60% baseline (no sustained 80% breach) — sum(hikaricp_active)/sum(hikaricp_max)
  - Heartbeat ingest rate scaled linearly against the 2-PC M5 pilot baseline (normalize per-device, then project 50 PC) — http_server_requests heartbeat uri
  - COLLECT_INVENTORY rate scaled linearly — endpoint_admin_agent_command_results_total{command_type="COLLECT_INVENTORY"}
  - 0 backend OOM event
  - 0 backend pod restart unrelated to image rollout
  - 1+ controlled wave abort drill PASS
  - Throttling/ring config ConfigMap LIVE
```

## 7. Evidence Pack Template

Layout:
```
evidence/m6-50pc-capacity-baseline-YYYYMMDD/
├── README.md                          # wave context (date, 50 PC IDs, ring allocation, on-call schedule)
├── 01-pre-wave-baseline.md            # §3.1 PromQL + §3.2 PG + §3.3 HPA snapshot
├── 02-ring-config-applied.yaml        # ConfigMap rings.json initial state
├── 03-ring-a-wave/
│   ├── ring-a-pc-list.txt
│   ├── ring-a-install-timeline.csv
│   ├── ring-a-heartbeat-timeline.csv
│   ├── ring-a-backend-metrics.png     # Grafana screenshot
│   └── ring-a-acceptance-result.md    # 9/10 PASS or actual count
├── 04-ring-b-wave/ ... (same structure)
├── 05-ring-c-wave/ ... (same structure)
├── 06-abort-drill/
│   ├── drill-scenario.md
│   ├── drill-promql-alert.png
│   ├── drill-configmap-patch.txt
│   ├── drill-mavis-log.txt
│   └── drill-restore-evidence.md
├── 07-final-capacity-baseline.md      # post-50PC baseline measurements
├── 08-ring-config-final.yaml          # ConfigMap rings.json closure state
└── mavis-signoff.txt                  # Mavis ops M6 closure sign-off
```

## 8. Mavis Ops Coordination Format

### 8.1 Wave Kickoff per Ring

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M6 Ring A wave kickoff YYYY-MM-DD HH:MMZ:
  - Ring A: 10 PC (asset tags: ...)
  - Concurrent install limit: 3
  - Wait window: 2h
  - Acceptance: 9/10 PASS
  - Abort thresholds: install_fail ≥2 OR heartbeat_loss ≥1 sustained OR backend CPU >80% 5m
  - On-call: <ops contact>
  - Tracked by: #1378"
```

### 8.2 Periodic Status (15 min interval during wave)

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M6 Ring A status +15min:
  - Install success: X/10
  - Backend CPU: Y%
  - DB pool: Z%
  - Heartbeat ingest: <rate>/min
  - Action: <CONTINUE | THROTTLE | HOLD | ABORT>"
```

### 8.3 Throttle / Hold / Abort

```
# THROTTLE (auto + Mavis confirm):
"M6 Ring B THROTTLE: backend CPU 82% sustained 5min; reducing concurrent_max 5 → 2"

# HOLD (manual investigation):
"M6 Ring B HOLD: install_fail 3/20; investigating MSI / GPO; ETA 30 min"

# ABORT (escalation):
"M6 Ring C ABORT: <reason>; rollback to ring B closure state; #1378 incident"
```

### 8.4 Closure Sign-off

```
mavis communication send \
  --to <ops-peer> \
  --command prompt \
  --content "M6 closure sign-off YYYY-MM-DD:
  - 50/50 PC enrollment + GPO install LIVE
  - Capacity baseline: backend CPU peak X%, DB pool peak Y%, heartbeat ingest <rate>/min
  - 1+ controlled wave abort drill PASS (scenario: <name>)
  - Throttling/ring config ConfigMap LIVE
  - Evidence bundle: evidence/m6-50pc-capacity-baseline-YYYYMMDD/
  - Mavis ops sign-off: APPROVED for M7 rollback drill gate
  - Tracked by: #1378"
```

## 9. Closure Acceptance Checklist (M6 #1378)

- [ ] 50/50 PC enrollment + backend record + cert subject SAN URI valid
- [ ] 50/50 PC GPO Software Installation Event 102 success
- [ ] Ring A 9/10 (90%) + Ring B 18/20 (90%) + Ring C 18/20 (90%) acceptance PASS
- [ ] Capacity baseline measured: backend CPU peak <80%, DB pool peak <80%, heartbeat ingest scaled linearly
- [ ] 1+ controlled wave abort drill PASS (formula validated)
- [ ] Throttling/ring config ConfigMap LIVE + backend reads + concurrent install enforcement
- [ ] 0 backend OOM event (50-PC ramp duration)
- [ ] 0 backend pod restart unrelated to image rollout
- [ ] Evidence bundle archived to `evidence/m6-50pc-capacity-baseline-YYYYMMDD/`
- [ ] Mavis ops sign-off comment on #1378 with APPROVED for M7 gate
- [ ] M7 #1379 rollback drill pre-flight readiness check kicked off

## 10. Closure Provenance

Cross-AI peer review:
- Implementer: Claude (Anthropic) — Session 51 Faz 22 otonom chain (single-PR scope)
- Reviewer (plan-time): Codex (OpenAI GPT-5.2) thread `019ea922` AGREE pattern (RB-bl028b-prod-openfga-notification-model-cutover.md preflight + impact inventory inspiration)
- Verdict: AGREE source-side draft + capacity baseline + ring config + abort formula + 1+ drill requirement + Mavis coordination

**Closure ≠ runbook merge**: Bu PR runbook MERGED ≠ M6 #1378 closed. Closure operator 50-PC physical wave + capacity measurement + drill PASS + 11-item acceptance checklist + Mavis sign-off sonra.
