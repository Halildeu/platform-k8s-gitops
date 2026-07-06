# Runbook — Frontend Synthetic Probes (`/settings/notifications`)

> **Belge kodu**: `RB-synthetic-frontend-probes`
> **Tarih**: 2026-05-21
> **Sahip**: Halil
> **Sprint**: DiD-2 (PR #923) defense-in-depth follow-up — 2026-05-21 PermissionProvider stale-token incident
> **Tetik**: `FrontendSettingsNotificationsProbeFailing` veya `FrontendSettingsNotificationsProbeStale` alert açıldığında

---

## 1. Bağlam

DiD-2 (PR #923) MERGED 2026-05-21 — `kustomize/base/monitoring/blackbox-exporter.yaml` üzerine 2 Probe CR eklendi:

| Probe | Endpoint | Edge | Module |
|---|---|---|---|
| `frontend-prod-settings-notifications` | `https://ai.acik.com/settings/notifications` | `ai-prod` | `http_200` |
| `frontend-testai-settings-notifications` | `https://testai.acik.com/settings/notifications` | `testai` | `http_200` |

Her iki Probe **60s scrape** + **15s timeout**. Alert window **5m sustained fail**.

**Neden bu monitör var**: 2026-05-21'de `ai.acik.com/settings/notifications` sayfası PermissionProvider AuthNotReadyError loop ile "Tercihler yüklenemedi" göstermeye başladı. Sebep: AuthBootstrapper stale localStorage token rehydration race + silent-SSO fail. HTTP-level 200 dönüyordu ama JS-side broken. **HTTP probe bu özel bug'ı yakalayamaz** — bu monitor `nginx down`, `5xx`, `TLS expiry`, `DNS fail`, `ingress proxy fail` sınıflarını kapatır. Client-side stuck-UI için ayrı browser-based synthetic gerekli (follow-up scope, henüz yok).

**Bağlantılı PR'lar**:
- PR #640 (platform-web): AuthBootstrapper stale-token fix (LIVE on prod, BUILD_SHA `3f56f6b`)
- PR #917 (gitops): prod frontend digest bump → 3f56f6b LIVE
- PR #923 (gitops, BU PR): synthetic probe + alert

---

## 2. Alert `FrontendSettingsNotificationsProbeFailing` (CRITICAL)

### 2.1 Anlamı

5 dakikadır kesintisiz `probe_success{job=~"blackbox-(testai|prod)-settings-notifications"} == 0`. Yani:
- Probe HTTP GET attı
- Response 200 ALMADI (302/4xx/5xx, ya da timeout, ya da TLS error, ya da DNS NXDOMAIN)

Alert annotation hangi edge için olduğunu söyler (`$labels.edge` = `ai-prod` veya `testai`, `$labels.host` = literal hostname).

### 2.2 Anlık triage (60 saniye)

```bash
# 1. Edge hangi? Alert label'ından bul (örn. edge=ai-prod, host=ai.acik.com)

# 2. Aynı sayfayı manuel HTTP GET et — probe doğru mu görüyor?
curl -I -s -o /dev/null -w "code=%{http_code} ssl_verify=%{ssl_verify_result} dns_ms=%{time_namelookup} connect_ms=%{time_connect} ttfb_ms=%{time_starttransfer}\n" \
  https://ai.acik.com/settings/notifications

# 3. Frontend pod state (k3d-prod platform-prod ns)
kubectl --context k3d-prod -n platform-prod get pod -l app.kubernetes.io/name=frontend -o wide

# 4. Frontend pod recent logs
kubectl --context k3d-prod -n platform-prod logs -l app.kubernetes.io/name=frontend --tail=50

# 5. Ingress controller state
kubectl --context k3d-prod -n ingress-nginx get pod -o wide
kubectl --context k3d-prod -n ingress-nginx logs -l app.kubernetes.io/name=ingress-nginx --tail=30 | grep -E "ai.acik.com|5[0-9][0-9]"
```

### 2.3 Olası kök sebepler

| Symptom | Olası kök sebep | Doğrulama | Remediation |
|---|---|---|---|
| `curl` 5xx döner | Frontend pod CrashLoop veya nginx config drift | `kubectl get pod` Ready != 1/1 | `kubectl rollout restart deploy/frontend`; eğer ImagePullBackoff → digest doğrula |
| `curl` 502/503 döner | Ingress upstream connection refused | Ingress controller log "no endpoints available" | Frontend Service endpoint check; pod readiness probe path |
| `curl` 4xx döner (404 vb.) | Nginx route config sorunu, SPA fallback bozuk | `kubectl exec ... cat /etc/nginx/conf.d/default.conf` SPA fallback `index.html` doğrula | nginx ConfigMap revert / digest pin geri al |
| `curl` timeout (~30s) | Network policy block, ingress LB down, DNS resolve fail | `dig ai.acik.com` ile DNS, `traceroute` ile LB ulaşılabilirliği | NetworkPolicy/Service troubleshoot |
| TLS error | Cert expiry, cert-manager fail | `openssl s_client -connect ai.acik.com:443 -servername ai.acik.com </dev/null \| openssl x509 -enddate` | cert-manager re-issue: `kubectl -n cert-manager delete certificaterequest <name>` ve trigger renewal |

### 2.4 Rollback yolu (deploy regression şüphesi)

Frontend digest son **24 saat** içinde bump edildiyse rollback ilk hipotez. **`main^` KULLANMA** — bu son merge'i geri alır ama unrelated GitOps değişikliklerini de toplar (notify-23.x docs, başka servis bump'ı, vb.). Doğru pattern: SON BİLİNEN İYİ revision'ı `prod-sync-result.json` artifact'ından veya `kustomize/overlays/prod/kustomization.yaml` git history'sinden seç.

```bash
# Yol 1 — PR #929 sonrası: prod-sync-result.json artifact ile son iyi revision'ı bul
# Son 10 deploy-prod-gitops success run
gh run list --repo Halildeu/platform-k8s-gitops --workflow deploy-prod-gitops.yml --status success --limit 10 \
  --json databaseId,createdAt,headSha,conclusion | jq

# Bir bilinen-iyi run id seç (örn. probe yeşilken son deploy)
RUN_ID=<id-from-above>
TMP=$(mktemp -d)
gh run download $RUN_ID --repo Halildeu/platform-k8s-gitops --name prod-sync-result --dir $TMP
cat $TMP/prod-sync-result.json | jq '.revision, .sync_mode, .conclusion'
LAST_GOOD_REV=$(jq -r '.revision' $TMP/prod-sync-result.json)
echo "Last-good revision: $LAST_GOOD_REV"

# Yol 2 — PR #929 öncesi run veya artifact yoksa: kustomization.yaml frontend digest tarihçesinden seç
git log --oneline -10 kustomize/overlays/prod/kustomization.yaml
# Frontend digest bump'tan önceki commit'i bul (örn. PR #917 öncesi)
LAST_GOOD_REV=$(git log -2 --oneline --format=%H kustomize/overlays/prod/kustomization.yaml | tail -1)

# Rollback dispatch (revision = last good gitops main commit)
gh workflow run deploy-prod-gitops.yml --repo Halildeu/platform-k8s-gitops --ref main \
  --field revision=$LAST_GOOD_REV \
  --field sync_mode=full \
  --field allow_prune=false \
  --field confirm=SYNC-PROD-ROLLBACK
```

Owner GitHub `production` environment gate'ini approve etmeli. Rollback sonrası probe'un yeşilenmesi beklenir (5dk içinde).

**Önemli**: `sync_mode=full` rollback unrelated kaynakları da geri sync eder; eğer yalnız frontend Deployment geri alınmak isteniyorsa `sync_mode=resources --resources=apps:Deployment:frontend` tercih edilir. Trade-off: `resources` mode'da revision MAIN HEAD olmalı (workflow guard), `full` mode'da daha eski revision çalışır. Rollback hedefi gerçekten daha eski revision ise `full + SYNC-PROD-ROLLBACK` doğru seçim.

### 2.5 Escalation

10 dakika içinde rollback / restart fix etmediyse:
- Slack `#platform-incidents` kanalına post
- Owner'a SMS (`#critical-fix` label'lı PR'lar için DiD-1 SLA monitor 4 saat sonra otomatik issue açar)

---

## 3. Alert `FrontendSettingsNotificationsProbeStale` (WARNING)

### 3.1 Anlamı

5 dakikadır kesintisiz `absent_over_time(probe_success{job="blackbox-prod-settings-notifications"}[10m]) == 1` veya testai için aynı. Yani:
- Probe HİÇ örnek üretmedi (10 dakika boyunca)
- Bu monitör fail durumunu görmez — probe'un kendisi çalışmıyor

Alert vector label `$labels.job` taşımaz (per-job `absent_over_time` collapse'i); description text'inde hangi edge için olduğunu okuyun.

### 3.2 Anlık triage

> Not: `monitoring.coreos.com/v1` `Probe` CR'ı Prometheus Operator tarafından
> DOĞRUDAN discovery'ye alınır — `ServiceMonitor` intermediate'i YOKTUR.
> Triage `kubectl get probe` + Prometheus `/targets` UI + Prometheus
> Operator log üzerinden gider; `serviceMonitorSelector` bu monitor için
> alakasız.

```bash
# 1. blackbox-exporter Deployment + Pod state
kubectl --context k3d-prod -n monitoring get deploy,pod -l app.kubernetes.io/name=blackbox-exporter

# 2. Probe CR'lar mevcut + spec doğru mu
kubectl --context k3d-prod -n monitoring get probe frontend-prod-settings-notifications frontend-testai-settings-notifications -o wide
kubectl --context k3d-prod -n monitoring describe probe frontend-prod-settings-notifications | head -40

# 3. Prometheus Operator log (Probe CR'ı discovery'ye almıyorsa burada görünür)
kubectl --context k3d-prod -n monitoring logs -l app.kubernetes.io/name=kube-prometheus-stack-operator --tail=80 | grep -iE "frontend-(prod|testai)-settings|probe"

# 4. Prometheus aktif scrape target durumu — Probe → blackbox-* job
kubectl --context k3d-prod -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090 &
PF_PID=$!
sleep 2
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job | contains("blackbox-")) | {job: .labels.job, health: .health, lastError: .lastError}'
kill $PF_PID

# 5. Prometheus spec'ın Probe CR'ı discovery'ye nasıl aldığını gör
kubectl --context k3d-prod -n monitoring get prometheus -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{.spec.probeSelector}{"\n"}{.spec.probeNamespaceSelector}{"\n---\n"}{end}'
```

### 3.3 Olası kök sebepler

| Symptom | Olası kök sebep | Remediation |
|---|---|---|
| blackbox-exporter pod NotReady | Container restart, OOM, config error | `kubectl describe pod` + `kubectl logs --previous`; ConfigMap revert |
| Probe CR mevcut değil | Kustomize render drift, ArgoCD sync fail | `kubectl kustomize kustomize/base/monitoring` ile lokal render kontrol; ArgoCD UI'da `platform-system` app sync |
| Probe CR var ama Prometheus discovery'ye almıyor | `probeSelector` / `probeNamespaceSelector` mismatch, Operator down | Operator log + `kubectl get prometheus -o yaml` selector ile Probe CR `metadata.labels` karşılaştır |
| Probe CR + discovery OK ama scrape target görünmüyor | Prometheus Operator generated config drift, prometheus-operator restart gerekebilir | `kubectl rollout restart deploy/<prometheus-operator-deploy>`; bekle 30s; `/targets` UI tekrar bak |
| Scrape target görünüyor ama probe_success metric yok | blackbox-exporter target endpoint'i çağrılamıyor (NetworkPolicy, DNS, port-forward sorunu) | blackbox-exporter pod log: `kubectl logs deploy/blackbox-exporter --tail=50` — probe URL erişim hatalarını gör |

### 3.4 Remediation pattern

90% kez **blackbox-exporter Deployment restart** çözer:

```bash
kubectl --context k3d-prod -n monitoring rollout restart deploy/blackbox-exporter
kubectl --context k3d-prod -n monitoring rollout status deploy/blackbox-exporter --timeout=120s

# 2-3 dakika içinde probe_success metric'i yeniden gelir; alert auto-resolve.
```

---

## 4. Bağlantı: PermissionProvider stale-token incident (2026-05-21)

Bu monitor 2026-05-21 incident'ından ilham aldı ama o incident'i yakalayamazdı (client-side JS bug, HTTP 200 dönüyor). Bunu yakalamak için **browser-based synthetic** (Playwright headless CronJob) ayrı follow-up scope. Codex thread `019e4946` iter-2'de plan REVISE alındı — multi-PR dedicated session work.

**Şu anki bu monitor'ün yakaladıkları (sınır)**:
- ✅ Frontend nginx pod CrashLoop
- ✅ Frontend Deployment ImagePullBackoff (digest yanlış)
- ✅ Ingress controller 5xx
- ✅ TLS cert expiry (ai.acik.com)
- ✅ DNS NXDOMAIN

**Yakalamadıkları**:
- ❌ PermissionProvider AuthNotReadyError loop
- ❌ "Tercihler yüklenemedi" client-side render hatası
- ❌ JS console error (TypeError, ReferenceError)
- ❌ AG Grid `ensureColumnMeta` race
- ❌ MFE federation `loadShare` failure

Bu sınıflar için browser-based synthetic gerekli — bu runbook'a `RB-browser-synthetic-frontend.md` follow-up referans olarak eklenecek.

---

## 5. Test mode (alert dışı manuel verify)

DiD-2 deploy etti mi? Probe çalışıyor mu? Manual smoke:

```bash
# Probe CR'lardan birini manuel tetikle (Prometheus scrape ile değil, blackbox-exporter'a doğrudan):
kubectl --context k3d-prod -n monitoring port-forward svc/blackbox-exporter 9115:9115 &
sleep 2
curl -s "http://localhost:9115/probe?target=https://ai.acik.com/settings/notifications&module=http_200" | grep -E "probe_success|probe_http_status_code|probe_ssl_earliest_cert_expiry"
kill %1

# Beklenen:
# probe_success 1
# probe_http_status_code 200
# probe_ssl_earliest_cert_expiry <unix-epoch-future>
```

---

## 6. Bağlantılı runbook'lar

> Repo iki runbook dizini taşıyor — operasyonel/cluster operations runbook'ları
> `docs/operations/RUNBOOKS/` altında, monitoring/alerting + faz-bazlı
> runbook'lar `docs/runbooks/` altında. Cross-reference'larda **tam path**
> ver (relative link bozulabilir).

- [docs/operations/RUNBOOKS/RB-prod-gitops-sync.md](../operations/RUNBOOKS/RB-prod-gitops-sync.md) — deploy-prod-gitops.yml manual dispatch (rollback için)
- [docs/operations/RUNBOOKS/RB-prod-rbac-least-privilege.md](../operations/RUNBOOKS/RB-prod-rbac-least-privilege.md) — restricted prod-deploy-smoke kubeconfig setup
- [docs/runbooks/RB-alertmanager-bridge-gh-token-seed.md](RB-alertmanager-bridge-gh-token-seed.md) — alert → GitHub issue dispatch (alert delivery)
- [docs/runbooks/RB-critical-fix-sla-monitor.md](RB-critical-fix-sla-monitor.md) — DiD-1 SLA tracking issues (process-level lag, complementary to this monitor)

---

## 7. Değişiklik geçmişi

| Tarih | Değişiklik | Bağlantı |
|---|---|---|
| 2026-05-21 | İlk yazım — DiD-2 (PR #923) follow-up | PR #-tba- (this PR) |
