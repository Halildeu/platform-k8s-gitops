# Prod Cutover Runbook v2 — Atomic Same-Host Cutover

> **Interpretation gate:** Once [../AGENTS.md](../AGENTS.md), ardindan [context-priority-rules.md](./context-priority-rules.md), sonra live truth icin [state/current-state.md](./state/current-state.md) okunur.
> **Scope:** `ai.acik.com` compose backend → `k3d-prod` atomic switch
> **Pattern:** `cutover-freeze` → `rollback-window` (bkz ADR-0002 §5)
> **Strategy:** Weighted rollout YOK, tek switch + 72h warm rollback
> **Role:** Bu dokuman operasyon prosedurudur; canli durum kaniti tek basina bu dosyadan okunmaz.
> **Prereq:** ADR-0002 accepted + Faz A-F gate'leri `PLAN.md` ve `docs/state/current-state.md` uzerinden dogrulandi

## 0. Ortak Değişkenler

```bash
export EDGE_CONTAINER="<host-nginx-container-or-service>"
export PROD_CONF="<nginx-prod-conf-path>"
export COMPOSE_UPSTREAM="<legacy-compose-upstream>"
export K8S_UPSTREAM="http://127.0.0.1:30080"
export ACTIONS_RUNNER_SERVICE="<actions-runner-stage.service>"
export PROD_COMPOSE_FILE="<legacy-prod-compose-file>"
export CUTOVER_TS="$(date +%Y%m%d-%H%M%S)"
export SMOKE_CLIENT_ID="<client-id>"
export SMOKE_CLIENT_SECRET="<from-vault-prod>"
```

**Not:** Edge host-native ise `docker exec nginx -t` yerine `sudo nginx -t && sudo systemctl reload nginx`.

## 1. Global Rollback Trigger Set

Aşağıdaki sinyallerden biri oluşursa rollback değerlendirmesi bekletilmez:

- Edge 5xx ratio `> 1%` / 15 dakika
- Gateway p95 latency `> 2s` / 10 dakika
- Authz synthetic fail ardışık `3` kez
- `allow` probe başarısız
- Kritik business path başarısız
- Pod restart spike `> 3 / 15dk`
- Prod stateful servis unhealthy

## 2. T-24h — Cutover-Freeze Mode Activation

**Tetik:** Faz F PASS, cutover penceresi onaylandı
**Süre:** 30-60 dk

### Komut
```bash
# 1. Test workload'u minimize et (default zaten scale-to-zero — teyit)
kubectl --context k3d-test -n platform-test get deploy -o wide
kubectl --context k3d-test -n platform-test scale deployment --replicas=0 --all
kubectl --context k3d-test -n platform-test scale statefulset openfga --replicas=0

# 2. Actions runner throttle
sudo systemctl set-property --runtime "$ACTIONS_RUNNER_SERVICE" CPUQuota=50% MemoryMax=1G

# 3. Legacy compose observability kapat (ADR §3.8 zorunluluk)
docker ps --format '{{.Names}}' | grep -E 'observability|grafana|prometheus|loki|tempo' \
  | xargs -r docker stop

# 4. Disk / memory hızlı kontrol (400 GB limit — ADR §7.1)
df -h /srv /var/lib/docker /
free -h
docker system df
```

### Beklenen
- Test tüm replicas 0
- Runner throttled (CPU %50)
- Legacy observability durmuş
- `/` kullanım `< 75%` (300 GB altı)

### Fail sinyali
- Disk kullanım `≥ 75%` (300 GB+)
- Host free RAM `< 6 GiB`
- Legacy observability kapanmıyor

### Go / No-Go
Fail → **No-Go** (cutover erteleniyor). PASS → `cutover-freeze` mode aktif.

## 3. T-8h — Final Preflight Smoke

**Tetik:** `cutover-freeze` aktif
**Süre:** 45-90 dk

### Komut
```bash
# 1. Moving tag kontrolü (D30 ihlal — YASAK)
rg -n "main-stable" kustomize/overlays/prod && echo "❌ main-stable moving tag bulundu" || echo "✓ immutable"

# 2. Dry-run diff
kubectl --context k3d-prod diff -k kustomize/overlays/prod | head -50

# 3. Secret + ESO kontrolü
kubectl --context k3d-prod get clustersecretstore
kubectl --context k3d-prod get externalsecret -A
kubectl --context k3d-prod -n platform-prod get secret

# 4. Stateful health (prod AYRI instance — ADR §3.2)
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'platform-(pg|kc|vault)-prod'

# 5. Pod readiness + imageID digest (D30 immutable proof)
kubectl --context k3d-prod -n platform-prod get pods -o wide
kubectl --context k3d-prod -n platform-prod get pods \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].imageID}{"\n"}{end}'

# 6. Local host smoke (dış trafik yönlenmeden)
curl -sk -H "Host: ai.acik.com" http://127.0.0.1:30080/
curl -sk -i -H "Host: ai.acik.com" http://127.0.0.1:30080/auth/actuator/health
curl -sk -i -H "Host: ai.acik.com" http://127.0.0.1:30080/variants
```

### Beklenen
- `main-stable` yok (tüm overlay tag `sha-<7char>`)
- ESO + CSS Ready=True
- Prod stateful healthy
- Pod'lar Ready
- Local smoke `200/401/403` beklenen (500 YOK)

### Fail sinyali
- Mutable image varsa
- Secret sync eksik
- Pod Ready değil
- Local smoke 5xx / timeout

### Go / No-Go
Fail → **No-Go** (cutover iptal). PASS → T-2h adımına geç.

## 4. T-2h — Communication + Stakeholder Sign-Off

**Tetik:** T-8h preflight PASS
**Süre:** 15-30 dk

### Komut
```bash
cat <<EOF > /tmp/cutover-broadcast.txt
Prod cutover T-2h
Preflight: PASS
Freeze window: T-30m
Atomic switch: T-0
Rollback window: T → T+72h
EOF
cat /tmp/cutover-broadcast.txt
```

### Beklenen
- Teknik ekip + ops + karar sahibi aynı pencereyi biliyor
- T-30m sonrası değişiklik yasağı teyit edildi

### Fail sinyali
- Stakeholder onayı yok
- Eşzamanlı başka deploy planı var
- Freeze ihlali tespit edildi

### Go / No-Go
Onay yoksa **No-Go**.

## 5. T-30m — Freeze Gate (Gate 1)

**Tetik:** T-2h onay verildi
**Süre:** 20-30 dk

### Komut
```bash
# 1. Drift teyidi
git fetch origin && git status
kubectl --context k3d-prod diff -k kustomize/overlays/prod | head -20

# 2. Prod readiness
kubectl --context k3d-prod -n platform-prod get deploy,statefulset
kubectl --context k3d-prod -n platform-prod get pods

# 3. Runner daha da daraltılabilir (rollback-window hazırlık)
sudo systemctl set-property --runtime "$ACTIONS_RUNNER_SERVICE" CPUQuota=25% MemoryMax=768M

# 4. Rollback backup (nginx config + edge state)
cp "$PROD_CONF" "${PROD_CONF}.bak.${CUTOVER_TS}"
docker exec "$EDGE_CONTAINER" nginx -T > "edge-nginx-${CUTOVER_TS}.txt" 2>&1
```

### Beklenen
- Drift sürprizi yok
- Prod Ready
- Backup alındı
- Runner throttle uygulandı

### Fail sinyali
- Yeni commit / drift
- Prod Ready değil
- Backup alınamıyor

### Go / No-Go — **GATE 1**
Tek fail varsa **No-Go** (cutover iptal). PASS → T-0 atomic switch.

## 6. T-0 — Atomic Cutover

**Tetik:** Gate 1 PASS
**Süre:** 5-10 dk

### Komut (Host nginx container)
```bash
# 1. Upstream swap
sudo sed -i "s#${COMPOSE_UPSTREAM}#${K8S_UPSTREAM}#g" "$PROD_CONF"

# 2. Config test + reload
docker exec "$EDGE_CONTAINER" nginx -t
docker exec "$EDGE_CONTAINER" nginx -s reload
```

### Komut (Host-native nginx)
```bash
sudo sed -i "s#${COMPOSE_UPSTREAM}#${K8S_UPSTREAM}#g" "$PROD_CONF"
sudo nginx -t
sudo systemctl reload nginx
```

### Beklenen
- `ai.acik.com` artık `k3d-prod` ingress'e yönleniyor
- Nginx reload errorsuz

### Fail sinyali
- `nginx -t` başarısız
- Reload hata
- Edge 502/timeout

### Go / No-Go
`nginx -t` fail → **ANINDA** config backup restore (bkz §11.1 rollback):
```bash
sudo cp "${PROD_CONF}.bak.${CUTOVER_TS}" "$PROD_CONF"
sudo nginx -t && sudo systemctl reload nginx
```
Reload PASS → T+5m smoke.

## 7. T+5m — First Smoke (Up Gate)

**Tetik:** Atomic switch yapıldı
**Süre:** 10-15 dk

### Komut
```bash
curl -sk -o /tmp/ai-root.html -w 'root: %{http_code}\n' https://ai.acik.com/
curl -sk -i https://ai.acik.com/auth/actuator/health
curl -sk -i https://ai.acik.com/variants
kubectl --context k3d-prod -n platform-prod get pods
```

### Beklenen
- `/` → `200`
- `/auth/actuator/health` → `200` (veya tasarıma göre tutarlı kod)
- `/variants` unauth → `401/403` (DENY enforce)
- Prod pod'lar Ready, restart yok

### Fail sinyali
- Root 5xx
- Actuator timeout / 5xx
- Deny YERİNE 500
- Pod restart / CrashLoop

### Go / No-Go — `Up Gate`
Fail varsa rollback değerlendirmesi beklemez (bkz §11.2).

## 8. T+15m — Extended Smoke (Functional + Zanzibar-Ready Gate 2)

**Tetik:** T+5m PASS
**Süre:** 20-30 dk

### Komut
```bash
# 1. Allow token al
ALLOW_TOKEN=$(curl -sk -X POST \
  "https://ai.acik.com/auth/realms/serban/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=${SMOKE_CLIENT_ID}" \
  -d "client_secret=${SMOKE_CLIENT_SECRET}" | jq -r .access_token)

# 2. ALLOW probe (D29 Katman 3)
curl -sk -i -H "Authorization: Bearer ${ALLOW_TOKEN}" https://ai.acik.com/variants

# 3. DENY probe (authoritative)
curl -sk -i https://ai.acik.com/variants

# 4. Hub check (cluster-direct permission-service)
kubectl --context k3d-prod -n platform-prod port-forward svc/permission-service 18090:8090 \
  >/tmp/pf-permission.log 2>&1 &
PF_PID=$!
sleep 5
curl -sk -i http://127.0.0.1:18090/api/v1/authz/version
kill "$PF_PID"
```

### Beklenen
- Allow probe `2xx`
- Deny probe `401/403` (DENY enforce!)
- Hub `/api/v1/authz/version` healthy
- Kritik business path çalışıyor

### Fail sinyali
- Allow probe fail
- Deny enforce kayıp (authz bypass!)
- Hub check fail
- JWT/KC/Vault zinciri bozuk

### Go / No-Go — **GATE 2**
Gate 2 fail → **IMMEDIATE ROLLBACK** (bkz §11.2).
PASS → Mode transition: `cutover-freeze` → `rollback-window`.

## 9. T+60m — First Soak Checkpoint

**Tetik:** Gate 2 PASS
**Süre:** 20 dk

### Komut
```bash
# Prometheus port-forward
kubectl --context k3d-prod -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090 \
  >/tmp/pf-prom.log 2>&1 &
PF_PID=$!
sleep 3

# Recording rule sorgular
for q in 'platform:edge:5xx_ratio' 'platform:gateway:p95' \
         'platform:probe:success_ratio_5m' 'platform:pods:restart:rate15m'; do
  echo "--- $q ---"
  curl -sg 'http://127.0.0.1:9090/api/v1/query' --data-urlencode "query=${q}" | jq .data.result
done
kill "$PF_PID"
```

### Beklenen
- Edge 5xx ratio `< 0.01`
- Gateway p95 `< 2s`
- Probe success yüksek + stabil
- Restart rate ~0

### Fail sinyali (global trigger set)
- 5xx `> 1%`
- p95 `> 2s`
- Restart spike
- Authz synthetic kayıp

### Go / No-Go
Fail → rollback değerlendirmesi başlat. PASS → T+24h soak bekle.

## 10. T+24h — Soak Checkpoint

**Tetik:** T+60m PASS
**Süre:** 30-45 dk

### Komut
```bash
kubectl --context k3d-prod -n platform-prod get pods
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'platform-(pg|kc|vault)-prod'
curl -sk -o /dev/null -w 'root: %{http_code}\n' https://ai.acik.com/

# Allow probe sustain
ALLOW_TOKEN=$(curl -sk -X POST \
  "https://ai.acik.com/auth/realms/serban/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=${SMOKE_CLIENT_ID}" \
  -d "client_secret=${SMOKE_CLIENT_SECRET}" | jq -r .access_token)
curl -sk -i -H "Authorization: Bearer ${ALLOW_TOKEN}" https://ai.acik.com/variants

# Disk growth trend (400 GB limit)
df -h /srv /var/lib/docker
docker system df
```

### Beklenen
- Pod stabil
- Stateful healthy
- Allow/deny davranışı korunuyor
- Disk büyümesi kontrollü (`< 75%`)

### Fail sinyali
- Sağlık kaybı
- Stateful degrade
- Allow/deny drift
- Disk `≥ 85%` (critical — 340 GB+)
- Beklenmeyen restart artışı

### Go / No-Go
Fail → rollback hâlâ açık.

## 11. T+72h — Rollback Window Close

**Tetik:** 72 saat stabil prod
**Süre:** 20-40 dk

### Komut
```bash
# 1. Son karar kontrolü
curl -sk -o /dev/null -w 'root: %{http_code}\n' https://ai.acik.com/
kubectl --context k3d-prod -n platform-prod get pods
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'platform-(pg|kc|vault)-prod'

# 2. Warm compose backend kapat
docker compose -f "$PROD_COMPOSE_FILE" stop
docker compose -f "$PROD_COMPOSE_FILE" ps

# 3. Runner normal moda
sudo systemctl set-property --runtime "$ACTIONS_RUNNER_SERVICE" CPUQuota=150% MemoryMax=3G

# 4. Mode transition log
echo "$(date -u +%FT%TZ) rollback-window → normal (prod stabil, warm shutdown)" \
  >> docs/ops-mode-transition.log
```

### Beklenen
- Prod stabil (72h full soak)
- Warm rollback compose kapalı
- Sistem `normal` moda döndü

### Fail sinyali
- 72h sonunda stabilite bozuldu
- Warm backend kapatılamıyor
- Prod degrade

### Go / No-Go
Fail → rollback-window UZATILIR. PASS → Faz H Compose Decommission akışı.

## 12. Rollback Playbook

### 12.1 Edge Config Rollback (T-0 nginx fail)
```bash
sudo cp "${PROD_CONF}.bak.${CUTOVER_TS}" "$PROD_CONF"
docker exec "$EDGE_CONTAINER" nginx -t && docker exec "$EDGE_CONTAINER" nginx -s reload
# (veya host-native)
sudo nginx -t && sudo systemctl reload nginx
```

### 12.2 Full Traffic Rollback (T+5m veya T+15m veya T+24h+)
```bash
# 1. Host nginx upstream geri compose'a
sudo cp "${PROD_CONF}.bak.${CUTOVER_TS}" "$PROD_CONF"
sudo nginx -t && sudo systemctl reload nginx   # veya docker exec ... reload

# 2. Warm compose backend teyit
docker compose -f "$PROD_COMPOSE_FILE" ps
docker compose -f "$PROD_COMPOSE_FILE" up -d   # kapalıysa açıl (72h pencerede warm)

# 3. Mode transition log
echo "$(date -u +%FT%TZ) rollback-window → emergency-rollback (trigger: <sebep>)" \
  >> docs/ops-mode-transition.log

# 4. Post-rollback smoke (compose backend doğrulama)
curl -sk -i https://ai.acik.com/
curl -sk -i https://ai.acik.com/variants

# 5. Incident ticket aç (postmortem commitment)
```

### 12.3 Rollback Sonrası Mandatory
- Incident postmortem yazılı (max T+48h)
- Root cause + corrective action
- ADR-0002 review trigger: iki veya daha fazla rollback aktivasyonu → ADR revizyon değerlendirmesi (ADR §10)

## 13. Stakeholder Communication Template

```
[CUTOVER PROGRESS] T+<time>
Status: <freeze|live|rollback|stable>
Smoke: <PASS|FAIL>
Rollback: <OPEN|CLOSED>
Next checkpoint: T+<next>
```

## 14. Referanslar
- ADR-0002 §5 Operational Mode Contract
- PLAN.md §0 Faz G Atomic Prod Cutover
- `docs/S1-S2-acceptance-smoke-runbook.md` (D29 3 katman)
- `docs/day-2-governance.md` (post-cutover retention + rotation)
- Eski: `docs/prod-cutover-smoke-runbook.md` (v1, historical)
- Eski: `docs/S4-rollback-runbook.md` (warm rollback detay)
