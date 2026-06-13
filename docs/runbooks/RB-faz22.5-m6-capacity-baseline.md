# RB Faz 22.5 M6 — 50-PC Capacity Baseline + Wave Abort Evidence

> **Status**: SOURCE DRAFT
> **Runtime mutation**: NONE
> **Operator gate**: REQUIRED (50 PC IT pilot wave allocation + ring config + capacity metrics + Mavis ops on-call rotation + throttling guardrails)
> **Closure claim**: NO (source-side draft; M6 acceptance evidence operator + telemetry collects)
> **Tracked by**: [#1378](https://github.com/Halildeu/platform-k8s-gitops/issues/1378) Faz 22.5 M6 — 50-PC capacity baseline + wave abort evidence
> **Evidence template**: §6 capacity baseline + §7 wave abort drill format
> **Codex thread**: `019ea922` plan-time AGREE (pattern from RB-bl028b-prod-openfga-notification-model-cutover.md preflight + impact inventory)
> **Prerequisite**: M5 #1377 5-PC GPO pilot closure + Mavis ops sign-off
> **Companion preflight**: `scripts/faz22-mass-deployment/wave-preflight.ps1` — per-device read-only health before each ring ramp (`-Mode preinstall-readiness` pre-push, `-Mode enroll-health` post-enroll). `overall=FAIL` holds the ring.
> **VERIFY-BEFORE-WAVE (2026-06-13)**: the PromQL/SQL identifiers below are illustrative and MUST be reconciled against the live catalogs before the wave. Confirmed corrections: device `status` values are `PENDING_ENROLLMENT|ONLINE|STALE|OFFLINE|DECOMMISSIONED` (there is **no** `active`); confirm any `endpoint_admin_*` Prometheus metric exists in `/actuator/prometheus` (e.g. `endpoint_admin_enrollments_5xx_total` is a PROPOSED name — instrument or replace before relying on the abort formula).

---

## 1. Scope

**M6** = 50-PC wave deploy (post M5 5-PC closure). Hedef: ring-based rollout (group A 10 + group B 20 + group C 20) ile capacity baseline measure + wave abort formula validate + throttling/ring config LIVE.

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
# PromQL (Grafana endpoint-admin dashboard):

# Heartbeat ingest rate (per minute, per device)
rate(endpoint_agent_heartbeats_total[5m])
# Pre-wave baseline: ~5-10 heartbeat/min per device active

# COLLECT_INVENTORY frequency
rate(endpoint_agent_collect_inventory_total[5m])
# Pre-wave baseline: ~1-2 collect/hour per device

# Backend CPU/mem
container_cpu_usage_seconds_total{namespace="platform-prod", pod=~"endpoint-admin-service.*"}
container_memory_working_set_bytes{namespace="platform-prod", pod=~"endpoint-admin-service.*"}

# DB connection pool
endpoint_admin_db_connections_active / endpoint_admin_db_connections_max
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

### 5.2 Abort Decision Tree (per ring)

```
For each active ring:
  every 15 min during wave window:
    metrics_collect:
      install_status: Event 102 + enrollment record
      heartbeat_age: now - last_ping (P95 across ring)
      backend_cpu: container_cpu_usage_seconds_total (avg over 5m)
      db_pool: endpoint_admin_db_connections_active / max
      enrollment_5xx: rate(endpoint_admin_enrollments_5xx_total[5m])
    
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
For ring C closure:
  - 50/50 PC enrollment + GPO install LIVE
  - Backend CPU < 60% baseline (no sustained 80% breach)
  - DB pool < 60% baseline (no sustained 80% breach)
  - Heartbeat ingest rate scaled linearly (50 PC ~ 50x 5-PC pilot)
  - COLLECT_INVENTORY rate scaled linearly
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
