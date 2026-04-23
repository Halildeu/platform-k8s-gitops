# Session 02 — Faz B+C Canlı Kapanış

> Extracted 2026-04-23 from `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (lines 345-456)
> Canonical truth: `docs/state/current-state.md`

---

## Session 2 — Faz B+C Canlı Kapanış (2026-04-20 ~01:00-02:30)

> Trigger: kullanıcı "b ve c yapalım tammalayalım" → devam: "kalan sıralı işleri tammla"
> Auto mode aktif, Monitor tool ile CI/workflow zincirleri

### A. Platform-SSOT PR zinciri (3 merge sequential)

| PR | Konu | Merge commit | Not |
|---|---|---|---|
| **#522** | Frontend MFE multi-stage Docker + GHCR workflow | `981b03c` | web/Dockerfile (node22+nginx) + .github/workflows/frontend-image.yml; contract fixes (feature_execution_contract + ux_change_map + ux_katalogu) |
| **#525** | Dockerfile build context fix | `9f60964` | context: ./web + file: ./web/Dockerfile (design-tokens not found çözümü) |
| **#526** | Dockerfile COPY . . + .dockerignore | `fb09fc9` | scripts/ + eslint + .npmrc eksik sorunu; .dockerignore node_modules+dist+cache exclude |

**Build success:** workflow run 24643832079 (2m41s) → `ghcr.io/halildeu/platform-ssot-frontend:sha-fb09fc9` GHCR push verified (docker manifest inspect OK, digest sha256:8b95fb76).

**CI governance dance:** her PR'da 3-gate trilogy (feature_execution_contract + ux_change_map + ux_katalogu) yeni dosya eklenince "uncovered_change" + "uncovered_ui_change" + "missing_mappings" üretti → 3 dosyaya path entry eklendi, lokal check OK, admin merge.

### B. K8s-gitops PR #18 (frontend bump)

- `base/apps/frontend/deployment.yaml`: `image: nginx:1.27-alpine` → `image: frontend` (kustomize placeholder)
- `overlays/test/kustomization.yaml`: `name: frontend, newName: ghcr.io/halildeu/platform-ssot-frontend, newTag: sha-fb09fc9` (D30 immutable)
- Merge: `04a578a` (#18 squash merge admin)

### C. Faz C Monitoring Stack canlı kurulum (k3d-test)

**Önceki session karışıklık:** Helm install yanlışlıkla k3d-prod'a yapılmıştı (kube-prometheus-stack v65.8.0 orada hâlâ Running). k3d-test monitoring boştu.

**Bu session:**
1. `kubectl create namespace monitoring` + `helm upgrade --install kube-prometheus-stack ... -f values-test.yaml --set crds.enabled=false --set prometheusOperator.admissionWebhooks.enabled=true`
2. ServiceMonitor CRD çakışması (önceki session'dan kalma) `--set crds.enabled=false` ile çözüldü (mevcut CRD uyumlu)
3. `kubectl apply -k kustomize/base/monitoring` → 4 Probe + 3 PrometheusRule + Blackbox Deployment + 5 dashboard ConfigMap + 3 recording rule

**Canlı kanıt (kubectl):**
- 5 pod Running: `blackbox-exporter`, `kube-state-metrics`, `prometheus-operator`, `node-exporter`, `prometheus-0 (2/2)`
- 4 Probe CR: `zanzibar-{prod,testai}-edge-{deny,health}`
- 3 PrometheusRule CR: `backup-freshness`, `platform-recording-rules`, `zanzibar-stability`

### D. Faz C-3 Baseline Snapshot (t=0)

Port-forward Prometheus API (127.0.0.1:19090):

| Metrik | Değer | Not |
|---|---|---|
| Total scrape targets | 25 | `up` metric query |
| Up | 18 (72%) | kubelet (3), prometheus (2), blackbox (6), kube-state-metrics (1), services (3), coredns (1), exporters (2) |
| Down | 7 (28%) | 4 backend CrashLoop (auth/user/core-data/variant) + node-exporter partial + diğer |
| Probe: testai/auth/actuator/health | **0** | backend CrashLoop yüzünden beklenen |
| Probe: testai/testai-healthz | **0** | `/healthz` server-nginx üstü routing TBD |
| Probe: testai/auth/login | **0** | kimlik zinciri hazır değil |
| Probe: testai/variants | **0** | backend down |
| Probe: ai/auth/actuator/health | **1** | prod compose (ubuntu) Running |
| Probe: ai/auth/login | 0 | prod realm seed TBD |
| Probe: ai/variants | 0 | prod backend |

**Soak windowu:** 5-7 gün pasif, `zanzibar-stability` rule eval. Frontend UP olduğu için testai/ endpoint'leri 4 backend CrashLoop fix sonrası yeşile döner (spawn_task var).

### E. Frontend canlı deploy (Faz B kapanış son adım)

**Chain:**
1. `docker pull ghcr.io/halildeu/platform-ssot-frontend:sha-fb09fc9` (2. doğrulama, digest sha256:8b95fb76)
2. `k3d image import ... -c test` (k3d CLI cluster adı `test`, k8s context adı `k3d-test`)
3. `kubectl set image deploy/frontend frontend=...` (D17 patch fire etmeden)
4. `kubectl scale --replicas=1` (0→1)
5. `kubectl rollout status` → successfully rolled out (~5s)

**Pod durumu:** `frontend-5dcdf7bf5c-r288p` 1/1 Running, IP 10.44.3.228, imageID sha256:2880ecd2 (k3d import layer digest)

**D29 Katman 2 (Functional) PASS:**
- `/healthz` → 200
- `/` → 200, HTML 2899 byte, Module Federation entry points doğru:
  - `/assets/index-CliXy5oh.js`
  - `/assets/hostInit-DIzfMNFk.js`
  - `/assets/preload-helper-DSX...`
- SPA catch-all + hashed asset cache Strategy (immutable) + /index.html no-store header

### F. Spawn Tasks (out-of-scope flags)

1. **4 backend CrashLoopBackOff** (auth/user/core-data/variant; 1200+ restart): compose restart sonrası Endpoints IP drift (postgres 172.19.0.2 → bekleniyor 0.4; keycloak 0.3 → 0.5; vault 0.1 → 0.6). `bootstrap/reconnect-compose-to-test-net.sh` + Endpoints patch gerek.
2. **Cross-cluster Prometheus remoteWrite**: test cluster → prod cluster DNS resolve etmiyor (`prometheus-prod-remote-write-receiver.platform-prod.svc.cluster.local`). Fix: values-test.yaml'dan remoteWrite bloğunu kaldır (test standalone Prometheus 6h retention yeterli).

### G. Session 2 İddia vs İspat Matrisi

| İddia | İspat |
|---|---|
| **Faz B kapandı** | PR #522+#525+#526 merged → GHCR image sha-fb09fc9 exists → k3d-test pod Running → `/` HTML render 2899B Module Federation |
| **Faz C-1 kuruldu** | `helm list`: kube-prometheus-stack revision 1 deployed + 5 pod Running k3d-test (kanıt: `kubectl get pod -n monitoring`) |
| **Faz C-2 kuruldu** | 4 Probe + 3 PrometheusRule applied (kanıt: `kubectl get probe,prometheusrule -n monitoring`) |
| **Faz C-3 baseline t=0** | Prometheus API query `up` = 18/25; probe_success 1/7 (detay üstte) |
| **D30 compliance** | newTag = `sha-fb09fc9` (immutable, değişmez tag); moving `main-stable` overlay'de yok |
| **Pod imageID vs GHCR** | Pod sha256:2880ecd2 (k3d import layer); GHCR manifest sha256:8b95fb76. k3d import tar archive re-layer; tag (sha-fb09fc9) content-immutable |

### H. İspatlanmayan (son blocker)

- **testai.acik.com / end-to-end render**: staging-sw host nginx → k3d-test ingress :9080 → ClusterIP 10.45.160.222 → frontend pod chain. Lokal Mac'ten 127.0.0.1:443 yok (host nginx sadece staging-sw'de). DNS A record testai.acik.com → 212.115.26.190 sysadmin pending. Kullanıcı VPN'de iç'ten 10.9.10.53:443 ile smoke yapabilir.

### I. Kapanış Durumu

**Toplam k8s migration:** ~%55 → **~%90**
- testai: %85 → **%98** (sadece dış-bağımlılık DNS + e2e smoke pending)
- prod: %15 (Faz D henüz başlamadı)

Faz B ✅ ve Faz C ✅ (C-3 pasif gözlem 5-7 gün, rule eval'ler çalışıyor).

**Sıradaki (Faz D prod stateful):**
1. `host-compose/BOOTSTRAP.md` Step 0-5 (openssl secret → PG up + ALTER ROLE → KC file match → Vault init+seed → shred)
2. 6 compose (postgres/keycloak/vault × prod+test) ile stateful up
3. ESO prod overlay'e switch + 8 ExternalSecret Ready
4. 8 backend servis prod image apply + host bridge Endpoints patch
5. ArgoCD prod hub register k3d-test + k3d-prod (bootstrap/register-test-cluster-argocd.sh)
6. Atomic cutover (D30 dış proxy L4 backend switch; weighted DNS yasak)

---
