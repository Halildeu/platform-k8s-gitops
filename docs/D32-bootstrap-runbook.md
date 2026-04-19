# D32 Bootstrap Runbook — staging-sw-2 Prod Host Kurulumu

> **Source:** PLAN.md Bölüm 1.5 D32 Bootstrap Kontrat F1-F9
> **Script:** `bootstrap/install-on-staging-sw-2.sh`
> **Prereq:** staging-sw-2 fiziksel sunucu hazır (kurumsal ağ, ops koordinasyon)
> **Pattern:** F1→F9 sıralı, her adım doğrulama + fail sinyali + "buradan sonra devam etme" eşiği
> **Codex iter-4/iter-5 uyumu:** Tam adım-adım runbook; partial unwind dahil (tam prod rollback değil, step-wise geri dönüş)

---

## 1. Pre-flight Kontrol

### P1 — Donanım + Ağ

- [ ] staging-sw-2 kurumsal IP atanmış (sysadmin)
- [ ] DNS kaydı `ai.acik.com` şu an staging-sw (eski host) — cutover bu runbook'un F9 adımı
- [ ] Dış proxy L4 backend panel'de staging-sw-2 eklenmiş ama **INACTIVE** (sysadmin önceden)
- [ ] Git deploy key staging-sw-2 `~/.ssh/k8s-gitops-deploy` kopyalandı (port 443 alternatif)
- [ ] `~/.ssh/config` SSH config git@github.com → port 443 override (kurum firewall)

### P2 — Kaynak Gereksinimleri

| Kaynak | Min | Hedef |
|---|---|---|
| RAM | 16 GB | 24 GB |
| vCPU | 4 | 8 |
| Disk | 200 GB | 200 GB |
| Docker | 24+ | 24+ |
| Docker Compose | v2.20+ | v2.20+ |

### P3 — DRY_RUN Prova (zorunlu)

```bash
cd /home/halil/platform-k8s-gitops
DRY_RUN=true bash bootstrap/install-on-staging-sw-2.sh
```

**Beklenen çıktı:** her F-adımı print, hiçbir `run()` aktif değil. Hata = bu runbook'a geri dön.

---

## 2. F1 — Pre-flight

**Süre:** ~5 dk

**İçerik:**
- Disk + RAM + Docker sürüm kontrol
- Git clone platform-k8s-gitops (SSH key)

**Doğrulama:**
```bash
docker version | grep "Server Version"           # 24+
docker compose version | grep "Docker Compose"   # v2.20+
df -h /home                                      # 200 GB+
free -g                                          # 16 GB+
ls -la /home/halil/platform-k8s-gitops/PLAN.md   # clone PASS
```

**Fail sinyali:**
- `Permission denied (publickey)` → deploy key yok veya SSH config hatalı
- `disk full` → disk temizle (`docker system prune -a`)
- `docker: command not found` → Docker kur (apt install docker-ce)

**Devam eşiği:** 4 check PASS → F2

---

## 3. F2 — Host OS + Docker

**Süre:** ~15 dk (paket kurulum + sysctl)

**İçerik:**
- sysctl params: `fs.inotify.max_user_watches=524288` (k3d+promtail)
- Docker daemon.json: log-driver (json-file rotate) + storage driver (overlay2)

**Doğrulama:**
```bash
sysctl fs.inotify.max_user_watches                # >= 524288
sysctl fs.file-max                                # >= 65536
cat /etc/docker/daemon.json | jq .                # json-file + overlay2
docker info | grep "Storage Driver"               # overlay2
docker info | grep "Logging Driver"               # json-file
```

**Fail sinyali:**
- `sysctl: cannot stat` → systemd sysctl unit yok; `echo "fs.inotify.max_user_watches=524288" >> /etc/sysctl.d/99-k8s.conf && sysctl -p`
- Docker storage `devicemapper` → overlay2'ye geçiş (daemon.json + systemctl restart docker)

**Devam eşiği:** sysctl + docker info tam → F3

---

## 4. F3 — k3d Cluster

**Süre:** ~10 dk (image pull + cluster up + Calico)

**İçerik:**
- `k3d cluster create prod --config bootstrap/k3d-prod.yaml`
- `bash bootstrap/install-calico.sh prod`

**Doğrulama:**
```bash
kubectl --context k3d-prod get nodes
# Beklenen: 1 node Ready (age: <1min)

kubectl --context k3d-prod -n calico-system get pods
# Beklenen: calico-node + calico-typha + calico-kube-controllers Running

kubectl --context k3d-prod get tigerastatus
# Beklenen: calico + calico-apiserver + nonprivileged-calico AVAILABLE=True DEGRADED=False
```

**Fail sinyali (bilinen pattern 2026-04-17):**
- `calico-typha` watch cache bozuk → BIRD DOWN → Tigera DEGRADED=True

**Fix:**
```bash
kubectl -n calico-system scale deploy calico-typha --replicas=0
kubectl -n calico-system delete pod -l k8s-app=calico-node
kubectl -n calico-system scale deploy calico-typha --replicas=1
# 2 dk bekle + re-doğrulama
```

**Devam eşiği:** TigeraStatus 3/3 AVAILABLE + DEGRADED=False → F4

---

## 5. F4 — Host Compose (PG/KC/Vault/nginx)

**Süre:** ~10 dk (image pull + up + healthcheck)

**İçerik:**
- `host-compose/data/docker-compose.yml up -d` (postgres + keycloak + vault)
- `host-compose/proxy/docker-compose.yml up -d` (nginx reverse proxy 443 SNI)
- `docker exec host-nginx-proxy nginx -t` syntax test

**Doğrulama:**
```bash
docker compose -f host-compose/data/docker-compose.yml ps
# Beklenen: postgres + keycloak + vault Up (healthy)

docker compose -f host-compose/proxy/docker-compose.yml ps
# Beklenen: host-nginx-proxy Up (healthy)

docker exec host-nginx-proxy nginx -t
# Beklenen: "syntax is ok" + "test is successful"

curl -sk https://<staging-sw-2-ip>/testai-healthz
# Beklenen: 200 "healthy" (host nginx sentinel)
```

**Fail sinyali:**
- `nginx -t` syntax fail → config revert + up tekrar
- PG bind port çakışma → compose down + netstat kontrol + up tekrar
- KC start fail → env vars eksik (docker-compose.yml check)

**Devam eşiği:** 4 container healthy + nginx -t PASS → F5

---

## 6. F5 — Network + Dış Proxy (sysadmin)

**Süre:** değişken (ops takvim)

**İçerik:**
- staging-sw-2 kurumsal IP atanmış (P1 zaten)
- Dış proxy L4 backend'e staging-sw-2 ekleme (INACTIVE — cutover F9'a kadar bekler)

**Doğrulama:**
```bash
# staging-sw-2'den dış proxy'e ping/telnet
ping -c 3 <proxy-vip>
telnet <proxy-vip> 443   # L4 TCP connectivity

# Dış proxy panel: backend health (sysadmin panel)
# Beklenen: staging-sw-2 "healthy" ama INACTIVE (trafik almıyor)
```

**Fail sinyali:**
- `ping: Network unreachable` → kurumsal firewall L3 kural eksik
- Dış proxy health NACT → L4 health check endpoint ayarı

**Fix:** sysadmin ticket + firewall kural
**Devam eşiği:** Dış proxy staging-sw-2 INACTIVE backend listeye alınmış → F6

---

## 7. F6 — ESO Secret Flow

**Süre:** ~10 dk

**İçerik:**
1. `bash bootstrap/install-eso-helm.sh prod` — ESO Helm install
2. `vault-approle-secret` manuel create (ilk bootstrap)
3. `kubectl apply -k kustomize/overlays/prod/eso` — ClusterSecretStore + ghcr-pull (W1 Opsiyon B)
4. Per-service ExternalSecret overlay apply ile F8+'de gelir

**Doğrulama:**
```bash
kubectl --context k3d-prod -n external-secrets get deploy
# Beklenen: external-secrets + external-secrets-webhook + external-secrets-cert-controller Available

kubectl --context k3d-prod get clustersecretstore vault-platform-gitops
# Beklenen: Status=Ready, Message=store validated

kubectl --context k3d-prod -n platform-prod get externalsecret ghcr-pull
# Beklenen: Synced=True (W1 workload ns)

kubectl --context k3d-prod -n platform-prod get secret ghcr-pull
# Beklenen: type=kubernetes.io/dockerconfigjson
```

**Fail sinyali:**
- `ClusterSecretStore Status=NotReady` → Vault FQDN yanlış veya AppRole secret-id geçersiz
- `ExternalSecret Synced=False` → Vault path eksik (`kv/gitops/ghcr-token` yok)
- `Secret/ghcr-pull not found` → overlay apply eksik veya namespace drift

**Fix:**
```bash
kubectl describe clustersecretstore vault-platform-gitops
kubectl describe externalsecret -n platform-prod ghcr-pull
# Log + Vault policy audit
```

**Devam eşiği:** ghcr-pull Secret var + type doğru + cache-busting pull kanıt (F8 smoke) → F7

---

## 8. F7 — GitOps (ArgoCD)

**Süre:** ~15 dk

**İçerik:**
- `bash bootstrap/install-argocd.sh prod` (ArgoCD Helm install)
- `argocd repo add` (SSH deploy key)
- `kubectl apply -f argocd/applications/root.yaml` (app-of-apps)
- Platform-prod Application manual sync (D30 atomic cutover, auto-sync YOK)

**Doğrulama:**
```bash
kubectl --context k3d-prod -n argocd get pods
# Beklenen: argocd-server + repo-server + application-controller Running

argocd --server argocd.prod.local login --sso   # veya admin password
argocd --server argocd.prod.local repo list
# Beklenen: platform-k8s-gitops listed (SSH deploy key)

argocd --server argocd.prod.local app list
# Beklenen: root + platform-prod + platform-system + platform-eso-prod
#         (platform-eso-test ve platform-test ayrı cluster, burada YOK)

argocd --server argocd.prod.local app sync platform-eso-prod
# Beklenen: ClusterSecretStore + ghcr-pull Synced (F6 zaten apply olduysa idempotent)
```

**Fail sinyali:**
- `argocd repo add` SSH key reject → ssh -T git@github.com -p 443 test + config doğrula
- `Application root OutOfSync` → git push pending, ArgoCD refresh

**Devam eşiği:** 4 Application healthy + platform-prod manuel sync edilebilir → F8

---

## 9. F8 — Pre-Cutover Smoke

**Süre:** ~20 dk (smoke koşumu + No-Go gate)

**İçerik:**
- 8 pod Ready kontrol (platform-prod ns)
- imageID == GHCR digest kontrol (D30 HARD RULE)
- Intra-cluster Zanzibar smoke (Hub /authz/version + /authz/me)
- Localhost edge smoke (serverlb proxy 9080)
- 6/6 No-Go blocker 🟢 verify

**Doğrulama:** `docs/prod-cutover-smoke-runbook.md` Adım 1-3 aynen.

**Fail sinyali:**
- 8 pod eksik → Deployment spec, ConfigMap, Secret eksik (overlay apply kontrol)
- Pod CrashLoopBackOff → Pod log incele, ImagePullBackOff ise F6 tekrar (ghcr-pull)
- ImageID drift (overlay tag ≠ pod imageID) → CI pipeline veya tag drift

**Devam eşiği:** 6/6 No-Go blocker 🟢 → F9

---

## 10. F9 — Atomic Cutover (S4-D)

**Süre:** ~5 dk atomic switch + T+5/T+30/T+60 observation

**İçerik:**
- `docs/prod-cutover-smoke-runbook.md` tam — atomic switch
- Dış proxy staging-sw → staging-sw-2 (sysadmin iş)
- T+5 edge smoke (ai.acik.com k3d-prod backend'e)
- T+30/T+60 hot observation (5xx ratio, p95 latency, restart count)
- T+72h warm rollback window başlar (`docs/S4-rollback-runbook.md`)

**Doğrulama:** `docs/prod-cutover-smoke-runbook.md` Adım 3-6 aynen.

**Fail sinyali (immediate rollback):**
- T+5 edge smoke fail (5xx veya timeout)
- T+30 5xx ratio >1%
- Authz synthetic 3× fail
- Critical bug rapor

**Fix:** `docs/S4-rollback-runbook.md` — immediate 5 dk trafik geri alma.

**Devam eşiği:** T+72h stabil → decommission gate (ayrı karar).

---

## 11. Partial Unwind (Bootstrap-sırasında-rollback)

Codex iter-5 uzlaşı: tam prod rollback DEĞİL — step-wise geri dönüş.

| Fail Noktası | Unwind Aksiyonu | Not |
|---|---|---|
| **F1 Pre-flight** | Host state snapshot (log + disk) + sysadmin ticket | Gerçek donanım/ağ sorun — yeniden kur gerekmez |
| **F2 Docker/sysctl** | Docker uninstall + sistem reboot + F1 tekrar | sysctl değerleri persistent (/etc/sysctl.d/) |
| **F3 k3d cluster** | `k3d cluster delete prod` + volume clean + F3 tekrar | Calico bilinen recovery pattern (scale typha=0) |
| **F4 compose** | `docker compose down -v` (volume wipe) + F4 tekrar | DB seed compose up ile geri gelir |
| **F5 network** | staging-sw-2 off-server olarak kal, sysadmin ticket | Ops bekleme — F6+ bloke |
| **F6 ESO** | **Namespace/object FREEZE (DELETE YAPMA)**, AppRole secret-id rotate + F6.1-F6.4 tekrar | Vault AppRole policy audit önce |
| **F7 ArgoCD** | ArgoCD uninstall + F7 tekrar | CR'lar git'te, kayıp YOK |
| **F8 smoke** | Fix ana repoda + yeni image + F8 tekrar | Cutover başlamadı → prod rollback gerek YOK |
| **F9 cutover** | **ROLLBACK RUNBOOK** (`docs/S4-rollback-runbook.md`) | Immediate 5 dk trafik geri alma |

**Prensip:** F6-F7 için DELETE yerine FREEZE (namespace/object korumak). F1-F5 için tam tekrar (host state idempotent).

---

## 12. Referanslar

- `bootstrap/install-on-staging-sw-2.sh` (script kaynağı, F1-F9 otomatize)
- `bootstrap/install-eso-helm.sh` (F6 alt-script)
- `bootstrap/install-calico.sh` (F3 alt-script)
- `bootstrap/install-argocd.sh` (F7 alt-script)
- `docs/prod-cutover-smoke-runbook.md` (F9 detay)
- `docs/S4-rollback-runbook.md` (F9 fail sonrası + 72h warm window)
- `docs/S2-B1-vault-property-matrix.md` (F6 preflight)
- PLAN.md Bölüm 1.5 D32 Bootstrap Kontrat Listesi
- Codex thread `019d9a75` iter-4/iter-5 scope uzlaşı
