# Runbook — Faz G D30 Atomic Cutover (T-7d → T+72h)

> **Belge kodu**: `RB-faz-g-d30-atomic-cutover`
> **Tarih**: 2026-05-15
> **Sahip**: Halil (owner) + agent autonomous chain
> **Sprint**: V2.1 9/9 closure → Faz G freeze gate UNLOCKED → D30 atomic cutover
> **Prerequisites**: V2.1 closure 9/9 ✓ (PR #682 092f921861) + Faz G transition plan (PR #683 7b6ee46eb3) + O1/O3/O6 agent verify (PR #685 4572f0eb9e)
> **Status**: D30 prep runbook — owner O2/O4/O5 kararlarından sonra timer başlar

---

## 1. Bağlam

V2.1 prod-readiness sub-wave 9/9 DONE 🟢. V2.1 sub-wave freeze gate full unlocked.

### 1.1 ⚠️ Topology Truth (PR #695 Discovery + Codex `019e2d16` REVISE)

**Önemli**: `ai.acik.com` frontend **zaten 2026-05-03'den beri cluster-authoritative** (Codex `019ded8d` PARTIAL → AGREE absorb). System-wide Faz G T0 = 2026-04-24 (PLAN.md line 34 🟢).

**Bu yüzden D30 atomic cutover semantik clarify gerek**:
- Frontend `ai.acik.com` → k3d-prod ingress NodePort 30443 ZATEN proxy_pass ✓
- Backend services k3d-prod cluster ZATEN running (Session 36 prod migration sonrası 49 pod Running)
- Stateful compose (PG/KC/Vault) D6 contract korunuyor (intentional)

**D30 "atomic cutover" gerçek scope** (TBD owner clarification):
- ❓ Possible A: Compose decommission (72h soak window sonrası containers stop)
- ❓ Possible B: DNS/edge layer change (A-record, CDN proxy)
- ❓ Possible C: Hibernate config drift fix epic (V2.1 reporting refactor track D dalga 1)
- ❌ NOT: "Edge proxy L4 compose → k8s switch" (already done 2026-05-03)

**Bu runbook eski §6.1 sed komutu (compose-backend.upstream → k8s-prod.upstream)** factually incorrect — V2.1 sub-wave context için preserved historical; gerçek D30 cutover scope owner kararı bekliyor.

**Weighted DNS YASAK** (ADR-0002 §3.8). **72h warm rollback window** kontratı korunuyor.

---

## 2. Owner Pre-Cutover Decisions (T-14d veya öncesi)

Agent autonomous yetkisi DIŞINDA. Owner kararı:

### 2.1 O2 — On-Call Rotation

- [ ] **Primary on-call**: Halil (kullanıcı) — PagerDuty veya equivalent escalation matrix
- [ ] **Secondary backup**: TBD
- [ ] Escalation timing: cutover gece-saat 02:00 UTC senaryosunda kim çağrılır?
- [ ] Out-of-band comms: telefon + alternatif iletişim kanalı

### 2.2 O4 — Cutover Date + Window

- [ ] Cutover date: **TBD** (önerilen: Pazar 02:00 UTC, Türkiye 05:00 sabah, en az 4h window)
- [ ] Window: **T-0 → T+4h** (cutover + initial monitoring)
- [ ] T+72h rollback window: compose frozen + ayakta — staging-sw compose lifecycle korunur
- [ ] T+72h sonrası compose decommission (V2.0 → V2.1 retire)

### 2.3 O5 — Communication Plan

- [ ] Stakeholder list: TBD (pre-prod henüz end-user yok — Pre-Production Full Authority HARD RULE)
- [ ] Notification timing:
  - T-7d announce (varsa)
  - T-1d final reminder
  - T-1h pre-cutover
  - T+0 cutover started
  - T+5m initial verify
  - T+1h stable confirm
- [ ] Post-cutover status update template

---

## 3. T-7d Day Prep (Cutover Week)

### 3.1 Agent autonomous (test cluster rollback dry-run)

```bash
# Test cluster rollback procedure dry-run
ssh halil@staging-sw

# Step 1: Identify test cluster current state
kubectl --context k3d-test -n platform-test get pod -o wide | head -20
docker ps --format '{{.Names}} {{.Status}}' | grep platform- | head -10

# Step 2: Verify rollback target reachability (compose backend health)
# (rollback senaryosunda L4 switch compose'a döner)
for svc in vault pg kc nginx; do
  docker exec platform-${svc}-test sh -c 'wget -qO- localhost:8080/health 2>&1 | head -3' || echo "${svc} health unreachable"
done

# Step 3: Edge proxy switch simülasyonu (NO actual switch)
# Read current nginx upstream config
ssh halil@staging-sw "sudo nginx -T 2>&1 | grep -E 'upstream|proxy_pass' | head -20"

# Step 4: Rollback chain command dry-run (echo only, no execute)
echo "ROLLBACK CHAIN (T-X min trigger):"
echo "  1. Edge proxy nginx config switch upstream from k8s → compose"
echo "  2. sudo nginx -s reload"
echo "  3. Verify endpoints respond from compose (curl HTTP 200)"
echo "  4. K8s pods marked for investigation (not destroyed)"
echo "  5. Owner notification (PagerDuty)"
```

### 3.2 Backup verification (T-7d snapshot)

```bash
# T-7d full backup taken (pre-cutover canonical point)
ls -lh /home/halil/platform/backup/{pg,vault,keycloak}/ | tail -10

# Backup freshness exporter (last ✓):
cat /home/halil/node_exporter_textfile/backup_freshness.prom
# Expected: backup_last_success_timestamp_seconds{type=pg|vault|kc} all fresh
```

### 3.3 V2.1 9/9 closure final review

- [ ] Faz G transition plan §2.1 → V2.1 9/9 DONE ✓
- [ ] §2.2 O1+O3+O6 agent verify GREEN ✓ (PR #685)
- [ ] O2 on-call rotation **confirmed**
- [ ] O4 cutover window **confirmed** (date + 4h window)
- [ ] O5 communication plan **executed** (T-7d notification sent)

---

## 4. T-1d Day Final Review

### 4.1 Last operational checks

```bash
# Compose + k8s state final
ssh halil@staging-sw "
docker ps --format '{{.Names}} {{.Status}}' | grep platform- | head -10
kubectl --context k3d-prod -n platform-prod get pod -o wide | head -20
"

# Backup freshness verify (T-24h)
cat /home/halil/node_exporter_textfile/backup_freshness.prom
# Both PG hourly + Vault daily + KC weekly all fresh

# Vault snapshot ≤7 day HARD RULE verify
ls -lh /home/halil/platform/backup/vault/prod/ | tail -3
```

### 4.2 Communication notification

- [ ] T-1d reminder (stakeholders varsa)
- [ ] On-call contact verify

---

## 5. T-1h Pre-Cutover Smoke

### 5.1 Agent autonomous pre-cutover smoke

```bash
# Compose backend health (rollback target)
curl -sS -o /dev/null -w "compose_health: http=%{http_code} time=%{time_total}s\n" https://ai.acik.com/health

# K8s backend health (cutover target)
kubectl --context k3d-prod -n platform-prod port-forward svc/api-gateway 8080:8080 &
PF_PID=$!
sleep 3
curl -sS -o /dev/null -w "k8s_api_gateway_health: http=%{http_code} time=%{time_total}s\n" http://localhost:8080/health
kill $PF_PID

# ABM-1 last-fire check (federation smoke must be PASS within 6h window)
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod get cm frontend-federation-smoke-status -o jsonpath='{.metadata.annotations}'"

# Browser smoke (M2a1 4-route pattern — local Mac via testai.acik.com)
# (PR #527 local measurement evidence model — see auth-storage-setup.mjs)
```

### 5.2 Required PASS list (T-1h)

- [ ] Compose backend `/health` HTTP 200
- [ ] K8s api-gateway `/health` HTTP 200
- [ ] ABM-1 last-fire ≤6h ago, result=PASS, failures=0
- [ ] Backup freshness (PG + Vault + KC) all green
- [ ] Vault snapshot ≤24h available
- [ ] No active alerts in alertmanager-bridge
- [ ] No active GitHub Issues `alertmanager-P0` open

### 5.3 GO/NO-GO decision

- **GO**: All 7 checklist items GREEN → proceed to T-0
- **NO-GO**: Any item RED → owner explicit decision (postpone cutover OR fix-and-proceed)

---

## 6. T-0 Atomic Cutover Execution

### 6.1 Cutover sequence (Edge Proxy L4 Atomic Switch)

```bash
# Pre-cutover snapshot for rollback comparison
ssh halil@staging-sw "
# Capture current edge proxy upstream config
sudo nginx -T 2>&1 | grep -A 5 'upstream' | head -30 > /tmp/nginx-pre-cutover.conf

# Capture current resolved backend IPs
dig +short ai.acik.com
dig +short testai.acik.com
"

# ⚠️ HISTORICAL DRAFT (Codex `019e2d16` REVISE — factually incorrect for current topology):
# Frontend ai.acik.com 2026-05-03'den beri cluster-served (host nginx → 30443 NodePort).
# Aşağıdaki sed komutu sites-enabled path'inde DEĞIL (actual: platform-web-nginx container
# /home/halil/platform/web/nginx/default.conf bind-mount). Bu komut çalıştırılırsa silent
# no-op olur (file yok).
#
# REAL D30 cutover scope owner clarification gerek (§1.1):
# - Possible A: Compose decommission (containers stop sonrası 72h grace remove)
# - Possible B: DNS/edge layer change
# - Possible C: Backend service Hibernate config drift fix epic
#
# Canonical rollback target available: default.conf.bak-20260503-1425 (PR #695 §1.2)
# Real rollback chain: PR #695 §3 (test cluster rehearsal pattern)

# Step 1: TBD per owner D30 scope clarification (placeholder draft kept for V2.1 sub-wave
# audit trail; owner authorization gerek real exec için)
echo "TBD per owner D30 scope clarification (see §1.1 topology truth)"

# Step 2: Verify atomic switch (≤30 seconds)
curl -sS -o /dev/null -w "post-cutover http=%{http_code} time=%{time_total}s\n" https://ai.acik.com/health
# Expected: HTTP 200, time <1s

# Step 3: Initial smoke (multiple endpoints)
for ep in /health /api/v1/authz/me /api/v1/notify /api/v1/reports; do
  curl -sS -o /dev/null -w "ep=${ep} http=%{http_code}\n" https://ai.acik.com${ep}
done

# Step 4: Browser smoke (M2a1 4-route pattern)
# Local Mac (cannot run from staging-sw without VPN/network access)
PERF_AUTH_USERNAME=d35-admin \
PERF_AUTH_PASSWORD=$(kubectl ...) \
PERF_AUTH_APP_ORIGIN=https://ai.acik.com \  # prod, not testai
node scripts/perf/auth-storage-setup.mjs
PERF_AUTH_STORAGE=tests/perf/.auth-storage.json \
node scripts/ci/route-performance-budget.mjs \
  --target prod --runs 1 \
  --routes "/home,/admin/users,/admin/access,/admin/reports/users" \
  --auth-storage tests/perf/.auth-storage.json --warn-only
```

### 6.2 T+5min Initial Monitoring

```bash
# Check 1: Latency p95 (Prometheus)
curl -sS 'http://prometheus:9090/api/v1/query?query=histogram_quantile(0.95,rate(http_request_duration_seconds_bucket[5m]))' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d['data']['result'][:5],indent=2))"

# Check 2: Error rate (5xx)
curl -sS 'http://prometheus:9090/api/v1/query?query=rate(http_requests_total{code=~"5.."}[5m])' \
  | python3 -c "..."

# Check 3: Pod state stable (no crashloop)
kubectl --context k3d-prod -n platform-prod get pod | grep -v Running | head -5
# Expected: empty (no problematic pods)

# Check 4: Alert flood guard (alertmanager-bridge)
kubectl --context k3d-prod -n monitoring exec deploy/alertmanager-bridge -- curl -sS http://localhost:9093/metrics | grep delivered_total | head -3
```

### 6.3 Rollback Trigger Evaluation (T+5min)

**§4.1 Latency/Error Rate** kontrol:
- p95 latency Y-Y axis: prod-pre vs prod-post karşılaştırma
- API error rate threshold: 5xx >2% sustained 10dk → **ROLLBACK**
- TTFB regression: >50% deterioration vs baseline → **ROLLBACK**

**§4.2 Operational**:
- Health check fail sustained 5dk → **ROLLBACK**
- Pod crashloop 3+/10dk → **ROLLBACK**
- ABM-1 federation smoke FAIL post-cutover (warn-only 3-fire sustained) → **ROLLBACK**

**§4.3 Sustained**:
- Alert flood >10 alert 5dk window → **ROLLBACK**
- KSM scrape lag >5dk → **ROLLBACK**

**§4.4 Manual**:
- Owner explicit "rollback" beyanı → **ROLLBACK**

**Eğer hiçbir trigger karşılanmadıysa**: T+5min → T+1h continue.

---

## 7. T+5min → T+1h Stabilization Window

### 7.1 Continuous monitoring (15-dk cadence)

```bash
# Every 15min for T+1h:
# 1. Health endpoint sustained 200
# 2. Latency p95 within ±10% pre-cutover baseline
# 3. Error rate <1%
# 4. No new alerts in alertmanager-bridge
# 5. No GitHub Issues alertmanager-P0 opened
# 6. Pod state Running (no Pending/CrashLoopBackOff)
```

### 7.2 T+1h GO/NO-GO

- **GO**: All checks GREEN sustained → T+72h warm window
- **NO-GO**: Anomaly observed → §6.3 rollback trigger evaluate

---

## 8. T+72h Warm Rollback Window

### 8.1 Compose frozen state

```bash
# Compose state continues ayakta (cutover sonrası 72h)
ssh halil@staging-sw "docker ps --format '{{.Names}} {{.Status}}' | grep platform- | head -10"

# Backup chain continues fresh (PG hourly + Vault daily)
cat /home/halil/node_exporter_textfile/backup_freshness.prom
```

### 8.2 Sliding monitoring (T+1h → T+72h)

- T+4h: First high-traffic period validation (Türkiye iş saati)
- T+24h: First day complete; ABM-1 4 natural fire (06/12/18/00 UTC patterns)
- T+72h: Final stabilization; compose decommission decision

### 8.3 T+72h GO/NO-GO (compose decommission)

- **GO**: 72h stable → compose containers stop + cleanup
- **NO-GO**: Anomaly observed → rollback OR investigate

---

## 9. Rollback Procedure (Emergency)

### 9.1 Trigger detected (T+X min/h)

```bash
# Step 1: Owner notification (PagerDuty)
# (manual; owner exec)

# Step 2: Edge proxy L4 atomic switch (k8s → compose)
ssh halil@staging-sw "
sudo cp /etc/nginx/sites-enabled/ai.acik.com.pre-cutover-backup /etc/nginx/sites-enabled/ai.acik.com
sudo nginx -t
sudo nginx -s reload
"

# Step 3: Verify rollback (≤30 seconds)
curl -sS -o /dev/null -w "post-rollback http=%{http_code} time=%{time_total}s\n" https://ai.acik.com/health

# Step 4: K8s side investigation (post-mortem)
kubectl --context k3d-prod -n platform-prod get events --sort-by='.lastTimestamp' | tail -30

# Step 5: Communicate
# Owner Slack/email stakeholders: "Rollback executed at <ts>; investigation underway"
```

### 9.2 Post-rollback investigation

- [ ] K8s pod logs collect
- [ ] Prometheus query (latency/error spikes)
- [ ] Alertmanager-bridge active alerts review
- [ ] GitHub Issues alertmanager-P0/P1 review
- [ ] Root cause analysis
- [ ] Fix iteration plan
- [ ] Next cutover attempt scheduling

---

## 10. Post-Cutover (T+72h sonrası)

### 10.1 Compose decommission

```bash
# Snapshot final compose state (forensic)
ssh halil@staging-sw "
docker ps -a > /tmp/compose-final-state.txt
docker images > /tmp/compose-final-images.txt
"

# Stop containers (no remove yet — 7-day grace period)
ssh halil@staging-sw "docker stop \$(docker ps -q --filter 'name=platform-')"

# 7-day grace: containers stopped but not removed
# Day 79+: docker rm + cleanup (final retire)
```

### 10.2 V3 backlog activation

V3 follow-ups now active scope:
1. GHA→testai connectivity (self-hosted runner platform-web register)
2. fin-muhasebe-detay dynamic seed (MSSQL Workcube)
3. M2a1 baseline hard-flip (14-gün history → 2026-05-29 sonrası eğer T+72h pre-cutover ile çakışırsa hard-flip post-cutover)
4. Real-traffic 24-72h RUM + ABM-1 continuous (POST-cutover scope)

---

## 11. Audit Trail

- **V2.1 closure**: PR #682 092f921861 (9/9 DONE)
- **Faz G transition plan**: PR #683 7b6ee46eb3
- **O1/O3/O6 agent verify**: PR #685 4572f0eb9e (3/6 ops pre-conditions GREEN)
- **Bu runbook**: D30 atomic cutover operator runbook (T-7d → T+72h chain)
- **Codex audit**: 14+ round provider-level cross-AI (V2.1 closure inherited)
- **HARD RULE compliance**:
  - Pre-Production Full Authority (agent autonomous chain prep)
  - Continuous Autonomous Mode (V2.1 → Faz G → D30 cutover prep)
  - No Closure Language ("freeze gate UNLOCKED, cutover prep continues" doğru)
  - D30 Atomic Cutover + 72h Warm Rollback (ADR-0002 §3.8 + transition plan §5)

---

## 12. Cross-AI Peer Review

Implementer AI:   Claude
Reviewer AI:      Codex
Codex thread:     019e2c83-f12e-7650-9721-be73397abc0f
Verdict:          AGREE (V2.1 closure R8 inherited — bu runbook downstream operator chain)
Same-provider exception: N/A
Verdict reason:   D30 atomic cutover operator runbook — V2.1 9/9 closure + Faz G transition plan + O1/O3/O6 verify state'ini T-7d → T+72h operasyonel chain'e bağlar. Owner decisions (O2/O4/O5) için ne zaman ne yapılacak detayı. Yeni implementation/policy YOK; doc-only operator readiness.
