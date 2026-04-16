# Session Handoff — 2026-04-16 (v2, Prod Cluster Platform Kurulumu)

> v1 (session-handoff-2026-04-16.md) Codex follow-up'larını ve Faz 11-12'yi kapattı.
> Bu session (v2) **prod cluster platform kurulumunu** yaptı. 6/7 follow-up'ın fiili
> tamamlanması: Dilim 1+2 merged (PR #413), compose Eureka fix (diğer session),
> PG max_conn compose kalıcılığı (PR #412), bridge persistence (PR #414).

---

## 🎯 Şu Anki Durum (live)

### K8s testai (k3d-test) — TAM YEŞİL
```
9/9 pod Ready, 0 restart
7/7 backend: ghcr.io/halildeu/platform-ssot-*:main-stable (CI-built AMD64)
Smoke: /auth, /users, /variants, /core, /reports, /schemas -> 200 (health)
testai-healthz -> 200
NetworkPolicy enforce (8 policy aktif)
Hikari pool 5/min 2 + graceful shutdown + minReadySeconds 10 + terminationGrace 45
Vault disabled (SPRING_CLOUD_VAULT_ENABLED=false)
RSA key auto-generate (SECURITY_SERVICE_JWT_PRIVATE_KEY="")
```

### K8s prod (k3d-prod) — YENİ KURULDU (bu session)
```
Cluster:                 Running, node Ready
Calico CNI:              3/4 pod Running (csi-node-driver bekliyor)
ingress-nginx:           Running (externalTrafficPolicy fix commit c56f8de)
Monitoring (namespace=monitoring):
  - alertmanager:         2/2 ✅
  - Grafana:              3/3 ✅
  - kube-state-metrics:   1/1 ✅
  - Prometheus operator:  1/1 ✅
  - node-exporter:        1/1 ✅
  - Prometheus:           2/2 ✅
  - Loki:                 2/2 ✅
  - Loki canary:          1/1 ✅
  - Tempo:                1/1 ✅
  - Promtail:             ❌ CrashLoopBackOff (3 restart) — INVESTIGATION GEREKLİ
ArgoCD:                  ❌ HENÜZ KURULMADI
Backend workload:        ❌ HENÜZ DEPLOY EDİLMEDİ
RAM:                     11Gi / 23Gi (12 GB boş)
```

### Compose (ai.acik.com)
```
frontend:                200 ✅
API (/api/users):        503 (diğer session Eureka dependency restore ediyor)
PG:                      max=200 (permanent via PR #412)
Bridge persistence:      PR #414 merged (platform-test-net kalıcı)
```

---

## 🔨 Bu Session'da Yapılanlar

**Gitops commits (main):**
- `c56f8de` — ingress-nginx `externalTrafficPolicy: Local` → kaldırıldı (ClusterIP uyumsuz)

**Ana repo commits (main):**
- `5929c6b8` (PR #407) — actuator permit hardening 7 servis
- `c2aaf19d` (PR #410) — auth /env 404 handler
- Merge PR #413 — Dilim 1+2 K8s migration
- PR #412 merged — PG max_connections=200
- PR #414 merged — compose platform-test-net kalıcı bridge
- (diğer session) PR #411 — STORY-0319 staging prod-like profile
- (diğer session) PR #415+ — Eureka dependency restore (devam)

**Prod cluster bootstrap:**
- k3d-prod cluster (port 6443 API, 30080 ingress)
- Calico tigera-operator
- ingress-nginx DaemonSet + hostPort 80/443
- kube-prometheus-stack (Prometheus + Grafana + Alertmanager + node-exporter + kube-state-metrics)
- Loki (single replica, filesystem)
- Tempo (single replica, filesystem)

---

## ⚠️ Açık Sorunlar (sonraki session ilk işler)

### 🔴 Promtail CrashLoopBackOff (prod)
```
kubectl --context k3d-prod -n monitoring logs promtail-m7ntj
```
Sebep bilinmiyor. Loki bağlantısı, RBAC, DaemonSet mount points ihtimalleri var.

### 🔴 ArgoCD henüz kurulmadı
```bash
ssh staging-sw 'cd /home/halil/platform-k8s-gitops && bash bootstrap/install-argocd.sh prod'
```

### 🟡 Prod backend deploy yapılmadı
K8s-test'teki pattern:
1. `docker pull --platform linux/amd64 ghcr.io/halildeu/platform-ssot-<svc>:main-stable`
2. `docker save → scp staging-sw → k3d image import -c prod`
3. Prod overlay yaz (platform-prod namespace, Endpoints prod PG/KC/Vault)
4. Apply + rollout + smoke

### 🟡 E2E JWT test yapılamadı
Keycloak `frontend` client "direct access grants" disabled (SPA). 
`admin-cli` veya confidential client ile token alınmalı.
Compose henüz Eureka fix bitmemiş → API 503, E2E için compose da hazır olmalı.

### 🟡 testai stabilite gözlemi başlamadı
Monitoring kuruldu (prod'da), ama testai cluster'dan scrape yapılmıyor.
Codex: "cross-cluster monitoring MVP'de ertele" — testai için manuel smoke yeterli.

---

## 🚀 Sonraki Session İlk Komutlar

```bash
# 1. Durum
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git log --oneline -5
ssh staging-sw 'export PATH=$HOME/.local/bin:$PATH; \
  kubectl --context k3d-prod -n monitoring get pods; \
  kubectl --context k3d-test -n platform-test get pods; \
  curl -sk -o /dev/null -w "testai: %{http_code}\n" https://testai.acik.com/testai-healthz; \
  curl -sk -o /dev/null -w "ai: %{http_code}\n" https://ai.acik.com/'

# 2. Promtail debug (varsa)
ssh staging-sw 'kubectl --context k3d-prod -n monitoring logs -l app.kubernetes.io/name=promtail --tail=30'

# 3. ArgoCD kurulum
ssh staging-sw 'cd /home/halil/platform-k8s-gitops && bash bootstrap/install-argocd.sh prod'
```

---

## 📋 Kalan İşler (öncelik sırasıyla)

| # | İş | Süre |
|---|---|---|
| 1 | Promtail crash fix | 15 dk |
| 2 | ArgoCD install (prod) | 30 dk |
| 3 | ArgoCD Applications yaz + apply | 45 dk |
| 4 | Prod overlay yaz (platform-prod ns, prod host bridge) | 1 saat |
| 5 | Prod backend deploy (main-stable image import) | 1 saat |
| 6 | E2E JWT test (compose + K8s) | 30 dk |
| 7 | testai stabilite gözlemi | 3-7 gün (PLAN) |
| 8 | Host nginx route: ai.acik.com → k3d-prod :30080 | 15 dk |
| 9 | Compose prod decommission (72h paralel sonrası) | - |

**Aktif iş toplam: ~5 saat**  
**Gözlem: min 3 gün (PLAN stabilite kapısı)**  
**Cutover'a kadar: 4-7 gün takvim**

---

## 🔑 Kritik Kararlar (Codex tur-5 istişaresi, thread 019d93fe-4745)

1. **ingress-nginx**: `externalTrafficPolicy` ClusterIP'te yok, kaldırıldı ✅
2. **ArgoCD**: MVP'de sadece prod cluster yönetsin (multi-cluster ertele)
3. **Monitoring**: Cross-cluster scrape MVP'de gereksiz (prod sadece kendi metriklerini toplasın)
4. **Host nginx route**: ai.acik.com route cutover ÖNCESİ değişmemeli
5. **Stabilite kapısı**: Platform 24 saat, cutover 3-7 gün (ideal 1 hafta)

---

## 🛡️ Güvenlik / Mimari Durumu

- Compose prod (ai.acik.com) çalışmaya devam — backend API Eureka fix bekliyor
- testai intranet-only (A kaydı 10.9.10.53, dış DNS yok)
- NetworkPolicy enforce aktif (k3d-test)
- Sectigo wildcard `*.acik.com` — ai + testai paylaşıyor
- GHCR SSH deploy key read-only
- Vault K8s'te disable (ESO Faz 3'te gelecek)

---

## 🌙 Son Söz

**Platform kurulumu %85 tamam**:
- Tüm K8s-ready backend image'lar CI-built (`main-stable`)
- testai 9/9 Ready, gerçek health 200
- Prod cluster + monitoring kuruldu
- Bridge kalıcı fix (compose restart dayanıklı)

**Kalan: ArgoCD + prod backend deploy + stabilite gözlemi + cutover.**

Tüm iş Codex review'dan geçirildi (kural gereği), thread `019d93fe-4745-7c10-a572-b865a44d30bb` (plan) + `019d92c6-eff5-7351-ad56-d299269a40b1` (follow-up review).
