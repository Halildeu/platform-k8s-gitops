# On-Call Triage Playbook — Alert → Action Mapping

> **Interpretation gate:** Once [../AGENTS.md](../AGENTS.md), ardindan [context-priority-rules.md](./context-priority-rules.md), sonra live truth icin [state/current-state.md](./state/current-state.md) okunur.
> **Source:** K8s-6 S3-A PrometheusRule 8 alert (Codex iter-7 tespit — day-2 ops)
> **Hedef:** Alert geldiğinde 2 dk içinde karar — ROLLBACK vs INVESTIGATE vs OBSERVE
> **Ölçü:** D29 HARD RULE (authoritative entrypoint + up ≠ functional ≠ Zanzibar-ready)
> **Role:** Bu dokuman alert → aksiyon matrisi verir; aktif rollback komutlari icin primary referans `docs/prod-cutover-runbook-v2.md` §12'dir.

---

## 1. Karar Matrisi

| Alert | Severity | Triage | Aksiyon |
|---|---|---|---|
| `ZanzibarHubDown` | critical | **ROLLBACK** | permission-service 2dk+ DOWN. D30 trigger. `docs/prod-cutover-runbook-v2.md` §12. |
| `OpenFGADown` | critical | **ROLLBACK** | Authz plane engine DOWN. `docs/prod-cutover-runbook-v2.md` §12. |
| `ZanzibarEdgeSyntheticFail` | warning | **INVESTIGATE** (3× fail → ROLLBACK) | External edge probe 5 dk fail. 3× peş peşe → immediate rollback. 1-2× → edge nginx + cert + k3d serverlb teşhis. |
| `EdgeHigh5xxRatio` | critical | **ROLLBACK** (sustained 15dk) | Prod 5xx > 1% sustained. D30 trigger. Rollback + fix plan. |
| `EdgeHighLatency` | warning | **INVESTIGATE** | Gateway p95 > 2s 10dk. PG slow query + pod CPU throttle + network teşhis. |
| `PlatformPodRestartSpike` | warning | **INVESTIGATE** | 15dk'da 1+ pod restart. `kubectl logs` + memory/OOM + disk full check. |
| `PlatformPodNotReady` | warning | **INVESTIGATE** (5dk+ → ROLLBACK candidate) | 5dk+ pod Not Ready. `kubectl describe pod` Events + Deployment spec. |
| `CNINodeNotReady` | critical | **INVESTIGATE** (2dk+) | Calico CNI DOWN. 2026-04-17 recovery pattern (typha scale=0 + node recycle). |
| `KyvernoPolicyViolation` | warning/critical | **INVESTIGATE** (policy tipine göre) | Admission policy fail. audit mode → log; enforce mode → deploy reject. Violation detay: `kubectl get policyreport -A`. |
| `BackupPGStale` | warning | **INVESTIGATE** | >24h PG backup yok → cron kontrol + disk full + permission audit. |
| `BackupPGCritical` | critical | **ROLLBACK** (DR perspektifi) | >48h PG backup yok → DR RPO ihlali. Ops acil + backup script fix. |
| `BackupVaultStale` | warning | **INVESTIGATE** | >24h Vault snapshot yok (RPO risk). |
| `BackupExporterDown` | critical | **INVESTIGATE** | node_exporter textfile collector okumuyor (monitoring körlüğü). |

---

## 2. Her Alert için 5 Dakika Checklist

### 2.1 ZanzibarHubDown (critical, ROLLBACK)

**Neden rollback:** permission-service Zanzibar authz hub. DOWN = tüm authz plane çalışmaz. D29 authoritative edge 401 yerine 500 dönebilir.

**5 dk aksiyon:**
1. **T+0 (30s)** — Slack oncall notify + deploy freeze (ArgoCD manuel sync)
2. **T+1 (1m)** — `kubectl -n platform-prod get pod -l app.kubernetes.io/name=permission-service`
   - `CrashLoopBackOff` → Rollback kararı net (`docs/prod-cutover-runbook-v2.md` §12)
   - `Running ama up=0` → Liveness probe fail; 1 dk daha bekle (pod restart beklenir)
3. **T+3 (3m)** — Trafik geri alma başla (dış proxy backend `staging-sw-2 → staging-sw`)
4. **T+5 (5m)** — ai.acik.com compose backend edge smoke doğrulama

**Teşhis sonra (post-rollback):**
- `kubectl logs permission-service --tail=500`
- `kubectl describe pod permission-service` Events
- PG bağlantı ve Vault Secret erişimi

### 2.2 OpenFGADown (critical, ROLLBACK)

**Neden rollback:** Authz engine DOWN → permission-service OpenFGA check çağrıları fail. Hub ayakta görünse de effective authz çalışmaz.

**5 dk aksiyon:** ZanzibarHubDown ile aynı pattern (rollback + teşhis).

**Teşhis sonra:**
- `kubectl -n platform-prod get statefulset openfga`
- OpenFGA DB bağlantı + StoreID/ModelID env

### 2.3 ZanzibarEdgeSyntheticFail (warning, 3× = rollback)

**Neden:** External edge probe (testai veya prod) başarısız. Edge zinciri kopuk.

**5 dk aksiyon (1× fail):**
1. **T+0 (30s)** — Probe target manuel test: `curl -sk -o /dev/null -w "%{http_code}\n" 'https://testai.acik.com/api/v1/variants?gridId=1204'`
   - 401 bekliyoruz (deny); 200/timeout/503 = sorun. `https://testai.acik.com/variants` artık SPA/public yüzey olduğu için burada referans değildir
2. **T+1 (1m)** — Edge zinciri çöz:
   - DNS: `dig testai.acik.com` → doğru IP
   - Nginx: `docker exec platform-web-nginx nginx -t`
   - k3d serverlb: `curl -sk http://127.0.0.1:9080/ -H "Host: testai.acik.com"`
3. **T+3 (3m)** — Cert kontrolü: `echo | openssl s_client -servername testai.acik.com -connect testai.acik.com:443 2>/dev/null | openssl x509 -noout -dates`
4. **T+5 (5m)** — Teşhis sonucu → observe (bir sonraki probe beklet) veya rollback karar

**3× peş peşe fail (15 dk):** `docs/prod-cutover-runbook-v2.md` §12 (immediate trafik geri alma).

### 2.4 EdgeHigh5xxRatio (critical, sustained = rollback)

**Neden:** Prod ingress-nginx 5xx > 1% 15dk. Kullanıcı deneyimi bozuk.

**5 dk aksiyon:**
1. **T+0 (30s)** — Grafana dashboard "Edge Synthetic" 5xx ratio trend bak (son 1h)
2. **T+1 (1m)** — `kubectl -n platform-prod get pods` — pod crash/NotReady var mı
3. **T+3 (3m)** — Hangi route? `sum by (path) (rate(nginx_ingress_controller_requests{ingress="platform",status=~"5.."}[5m]))` query
4. **T+5 (5m)** — Rollback karar (sustained 15dk = EVET) veya investigate (tek servis spike = fix)

### 2.5 EdgeHighLatency (warning, OBSERVE/INVESTIGATE)

**Neden:** Gateway p95 > 2s 10dk. Tek servis veya chain sorun.

**5 dk aksiyon:**
1. `histogram_quantile(0.95, sum by (le, uri) (rate(http_server_requests_seconds_bucket{application="api-gateway"}[5m])))` — hangi uri
2. Downstream servisler p95: `histogram_quantile(0.95, sum by (le, application) (rate(http_server_requests_seconds_bucket[5m])))`
3. PG slow query: `pg_stat_activity` veya Hikari timeout metric
4. Observe (kendine gelir mi) veya fix plan (PG index, CPU limit)

### 2.6 PlatformPodRestartSpike (warning, INVESTIGATE)

**Neden:** 15dk'da 1+ unexpected restart.

**5 dk aksiyon:**
1. `kubectl -n platform-<env> get pod --sort-by='.status.containerStatuses[0].restartCount'` — hangi pod
2. `kubectl -n platform-<env> logs <pod> --previous --tail=200` — önceki crash nedeni
3. `kubectl -n platform-<env> describe pod <pod>` — Events (OOMKilled / liveness fail / image pull)
4. Teşhis sonuç:
   - OOMKilled → memory limit arttır (`docs/S5-capacity-expansion-runbook.md`)
   - Liveness timeout → probe ayarı (initialDelaySeconds arttır)
   - ImagePullBackOff → ghcr-pull Secret (Vault ESO sorunu)

### 2.7 PlatformPodNotReady (warning, 5dk+ → candidate)

**Neden:** 5dk+ pod Not Ready.

**5 dk aksiyon:** PodRestartSpike ile benzer pattern, ama Ready durumuna odak.

- Readiness probe fail → endpoint response 200 değil (Spring Boot startup, DB bekliyor)
- Init container fail → migration veya prereq

### 2.8.1 KyvernoPolicyViolation (warning/critical, INVESTIGATE)

**Neden:** Admission controller policy ihlali (D30 immutable + non-root + resource limits + pull policy).

**5 dk aksiyon:**
1. **T+0 (30s)** — `kubectl get policyreport -A` — hangi pod hangi policy fail
2. **T+1 (1m)** — Policy adı + violation detay:
   ```bash
   kubectl get policyreport <report-name> -o json | jq '.results[] | select(.result == "fail")'
   ```
3. **T+3 (3m)** — Policy tipine göre:
   - `require-sha-image-tag` → Pod moving tag kullanıyor (latest/main-stable) → overlay tag fix + rollout
   - `require-non-root` → securityContext.runAsNonRoot eksik → deployment patch
   - `require-resource-limits` → resources.limits eksik → D22 overlay patch
   - `disallow-privileged-pods` → container escape şüphesi (kritik)
4. **T+5 (5m)** — Audit mode'da loglanır (deploy PASS); enforce mode'da reject → deploy fail → CI/CD cluster alerts

**Enforce mode'da Policy fail → Rollback DEĞİL, Fix DEPLOY:**
- Eğer prod'da policy enforce aktif ve yeni deploy fail olduysa, eski image Running kalır (sorun yok)
- Fix: policy uyumlu manifest düzelt + re-deploy

### 2.8 CNINodeNotReady (critical, INVESTIGATE)

**Neden:** Calico CNI DOWN. Pod network etkilenebilir. 2026-04-17 recovery pattern:

**5 dk aksiyon:**
1. `kubectl --context k3d-prod get tigerastatus` — DEGRADED=True mu?
2. `kubectl -n calico-system get pods` — calico-node + calico-typha Running mu?
3. Bilinen fix (BIRD down / typha watch cache bozuk):
   ```bash
   kubectl -n calico-system scale deploy calico-typha --replicas=0
   kubectl -n calico-system delete pod -l k8s-app=calico-node
   # 2 dk bekle
   kubectl -n calico-system scale deploy calico-typha --replicas=1
   ```
4. Yeniden tigerastatus check — DEGRADED=False

---

## 3. Escalation Tree

```
Alert gelir
  ├─ Critical + Rollback → 5 dk içinde prod-cutover-runbook-v2 §12
  │     └─ Rollback PASS → 72h warm window + Codex adversarial review
  │     └─ Rollback FAIL → Stakeholder escalate + incident commander
  ├─ Critical + Investigate → 5 dk checklist
  │     └─ Root cause tespit → Fix + post-mortem
  │     └─ Root cause bilinmiyor → 15 dk daha veya rollback
  ├─ Warning + Investigate → 5 dk checklist
  │     └─ Observe (kendine gelir) veya Fix plan
  │     └─ Sustained (45 dk+) → Rollback candidate re-evaluate
  └─ Warning + Observe → Grafana dashboard kontrol, trend izle
```

---

## 4. Post-Mortem Zorunluluğu

**Her Critical alert (rollback veya investigate) sonrası:** Codex adversarial post-mortem (thread ayrı):

- Neden oldu? (root cause)
- Hangi HARD RULE ihlali / gözden kaçma?
- Fix ne? (repo commit)
- Monitoring eksik mi? (yeni alert / threshold revize)
- Prevention (test coverage, CI gate, runbook update)

**Çıktı:** `docs/post-mortem-<YYYY-MM-DD>-<short-id>.md`

---

## 5. Referanslar

- `kustomize/base/monitoring/zanzibar-stability-rule.yaml` — 8 alert tanımı
- `docs/prod-cutover-runbook-v2.md` — aktif same-host cutover ve rollback mekaniği
- `docs/S4-rollback-runbook.md` — historical companion / diagnostic reference
- `docs/S1-S2-acceptance-smoke-runbook.md` — post-rollback smoke template
- `docs/S5-capacity-expansion-runbook.md` — memory/CPU/disk revize
- `docs/promql-query-pack.md` — günlük ops PromQL sorguları
- PLAN.md D29 (authoritative entrypoint) + D30 (atomic cutover + rollback)
