# platform-k8s-gitops — Canlı Geçiş Planı

**Repo amacı:** Bu repo `autonomous-orchestrator` platformunun Kubernetes GitOps manifest'lerini tutar. Docker Compose üzerinden k3s cluster'a tam geçiş için **tek doğruluk kaynağıdır**. Bu repo'dan geliştirilen yapı, testler yeşil olduğunda **doğrudan canlıya alınır** — deneysel/atılabilir yapı değildir.

**Son güncelleme:** 2026-04-14
**Durum:** İskelet klasörler hazır, manifest yazımı başlamadı

---

## 1. Kilitli Kararlar (FINAL)

| # | Karar | Değer |
|---|---|---|
| D1 | Deployment hedefi | k3s (staging-sw sunucusu), tek cluster |
| D2 | Namespace stratejisi | **5 ns**: `platform-prod`, `platform-test`, `ingress-nginx`, `argocd`, `external-secrets`, `monitoring` (+ kube-system). Tek cluster, namespace izolasyonu + PriorityClass + NetworkPolicy |
| D3 | Lokal dev | k3d (Docker Desktop üzerinde) |
| D4 | GitOps motoru | ArgoCD (app-of-apps pattern) |
| D5 | Manifest yönetimi | Kustomize (base + overlays) + Helm (3. parti chart'lar için) |
| D6 | Host-level servisler | PG + Keycloak + Vault → **Kubernetes DIŞINDA** Docker Compose ile host'ta çalışır, test+prod ayrı instance |
| D7 | Service discovery | **Eureka KALDIRILDI** — K8s native DNS (`<svc>.<ns>.svc.cluster.local`). Backend'de `@EnableEurekaClient` ve `@LoadBalanced` RestTemplate'ler temizlenir. Discovery-server pod'u yok → ~400 MB RAM tasarruf |
| D8 | Ingress + TLS | ingress-nginx; wildcard Sectigo cert (`*.acik.com` + `acik.com`, SAN'de test de kapsanır) manuel K8s Secret olarak; cert-manager **DEFER** (renewal 2026-10-01 öncesi değerlendirilir) |
| D9 | Secret | External Secrets Operator + Vault (mevcut Vault source-of-truth kalır) |
| D10 | Observability | kube-prometheus-stack + Loki + Tempo (Helm) |
| D11 | Image registry | GHCR (mevcut `deploy-backend.yml` push akışı korunur) |
| D12 | Git stratejisi | Lokal `.git` aktif, remote YOK. Canlıya geçerken `halildeu/platform-k8s-gitops` (private) repo oluşturulacak |
| D13 | Yaklaşım | Doğrudan canlı-ready yapı — atılabilir/deney değil |
| D14 | Ana repo paralel | `application-k8s.yml` profili + Dockerfile probe'ları K8s manifest yazımıyla **eş zamanlı** yazılır |
| D15 | CNI | **Calico** (başlangıçtan) — NetworkPolicy garantisi. Flannel değil. +200 MB RAM kabul |
| D16 | Cluster topolojisi | **2 k3d cluster aynı host'ta** (staging-sw): `prod` ve `test`. Docker-in-Docker ile izole (ayrı control plane, etcd, CNI). Gerekçe: "birini bozunca diğeri etkileniyor" tecrübesinin tekrarlamaması — kontrol düzlemi fiziksel ayrım. Lokal geliştirici makinede de aynı yaklaşım (2 k3d cluster) |
| D17 | Test ortamı çalışma modeli | **Scale-to-zero workload**: test cluster control plane açık (~2 GB sabit), workload'lar default `replicas: 0`. Yoğun saatlerde backend+openfga+frontend kapalı (~0 GB). İhtiyaç halinde `test-toggle.sh up`. Host-level test PG/KC/Vault de kapalı varsayılan |
| D18 | İngress + TLS termination | **Host-level nginx SNI reverse proxy** (mevcut `platform-web-nginx` yerine) 80/443 alır, Sectigo wildcard cert'i termine eder. Hostname'e göre backend: `ai.acik.com` → prod k3d HTTP :30080, `test.acik.com` → test k3d HTTP :31080. Cluster'ların içindeki ingress-nginx HTTP-only (cert'i host handle ediyor) |
| D19 | Host servis köprüsü | **Service + Endpoints** (IP pin `10.9.10.53`). ExternalName yerine; CoreDNS rewrite kırılgan |
| D20 | Host port ataması | **Mevcut portlar = PROD (`5432, 8081, 8200`)**, yeni portlar = TEST (`5433, 8082, 8201`). Prod verisi migrasyonu YOK |

**HARD RULES:**
- `platform-test` ve `platform-prod` namespace'leri aynı cluster'ı paylaşır ama **ayrı host-level PG/KC/Vault** instance'ı kullanır
- OpenFGA K8s içinde (StatefulSet), PostgreSQL host'ta
- Mevcut `decisions/topics/zanzibar-openfga.v1.json` kuralları K8s'te de geçerlidir (port 8090 yok, ScopeContextFilter order, vb.)
- Cron deploy DISABLED kalır stabilizasyon bitene kadar
- **Prod dış + iç, test sadece iç**: prod `ai.acik.com` dış proxy (`212.115.26.190`, L4 pass-through) üzerinden kurum ağı/VPN'den erişilir; test `test.acik.com` yalnız intranet (A kaydı `10.9.10.53`, dış proxy'e yazılmaz)
- **Admin UI'lar path altında**: ArgoCD, Grafana, Prometheus dahil her admin endpoint `ai.acik.com/<path>` şemasını kullanır — ayrı subdomain yok (DNS yükü minimum, tek cert yeter)

---

## 2. Mimari

### 2.1 Fiziksel Topoloji

```
┌────────────────────────── staging-sw (Ubuntu sunucu) ──────────────────────────┐
│                                                                                 │
│   ┌──────────── k3s cluster ────────────┐   ┌──── Host-Level (Docker) ────┐   │
│   │                                      │   │                              │   │
│   │  ns: platform-test                   │   │  postgres-test (port 5432)   │   │
│   │    ├── user-service                  │   │  keycloak-test  (port 8081)  │   │
│   │    ├── auth-service                  │   │  vault-test     (port 8200)  │   │
│   │    ├── variant-service               │   │                              │   │
│   │    ├── core-data-service             │   │  postgres-prod (port 5433)   │   │
│   │    ├── report-service                │   │  keycloak-prod  (port 8082)  │   │
│   │    ├── schema-service                │   │  vault-prod     (port 8201)  │   │
│   │    ├── permission-service            │   │                              │   │
│   │    ├── api-gateway                   │   └──────────────────────────────┘   │
│   │    ├── discovery-server (Eureka)     │                                      │
│   │    ├── openfga (StatefulSet)         │   Host servisleri k8s içinden        │
│   │    └── frontend (nginx + MFE)        │   ExternalName Service + Endpoints   │
│   │                                      │   ile erişilir                       │
│   │  ns: platform-prod                   │                                      │
│   │    └── (aynı 10 workload)            │                                      │
│   │                                      │                                      │
│   │  ns: platform-system                 │                                      │
│   │    ├── ingress-nginx                 │                                      │
│   │    ├── cert-manager                  │                                      │
│   │    ├── external-secrets              │                                      │
│   │    ├── argocd                        │                                      │
│   │    └── monitoring (prom+loki+tempo)  │                                      │
│   └──────────────────────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Network Akışı

```
Internet → ingress-nginx → api-gateway.platform-prod.svc → backend services
                         → frontend.platform-prod.svc    → MFE shell
                         → argocd-server.platform-system → ArgoCD UI
```

### 2.3 Hostname & TLS (FINAL)

**Hostname şeması — path-based routing:**

```
PROD (platform-prod)                     TEST (platform-test)
ai.acik.com/                             test.acik.com/
├── /            → frontend (MFE)        ├── /            → frontend
├── /api         → api-gateway           ├── /api         → api-gateway
├── /auth        → keycloak (XName)      ├── /auth        → keycloak (XName)
├── /argocd      → argocd-server         ├── /argocd      → argocd-server
├── /grafana     → grafana               ├── /grafana     → grafana
└── /prometheus  → prometheus            └── /prometheus  → prometheus
```

- `ai.acik.com`: **mevcut**, prod. Erişim yolu: internet/VPN → dış proxy `212.115.26.190` (L4 pass-through, kurum yönetiminde) → `10.9.10.53:443` (k3s ingress-nginx)
- `test.acik.com`: **YENİ**, intranet-only. A kaydı `10.9.10.53` — sadece iç Windows AD DNS'e (`acikdc01.acik.local`) eklenir, dış proxy'e yazılmaz.
- Path-based seçiminin gerekçesi: sadece 1 yeni DNS kaydı (test.acik.com) + tek wildcard cert, admin UI'lar için subdomain yok.

**TLS stratejisi — wildcard manuel Secret:**

| Namespace | Secret | Cert | Kaynak |
|---|---|---|---|
| `ingress-nginx` | `wildcard-acik-com-tls` | Sectigo `*.acik.com` + `acik.com` | mevcut PEM (`STAR_acik_com.crt` + `.key`, Nginx bundle) |

- Hem `ai.acik.com` hem `test.acik.com` aynı Secret ile servis edilir (wildcard SAN kapsıyor).
- **cert-manager kurulmaz** (MVP). Renewal manuel — 2026-10-01 expiry öncesi (Faz 14 civarı) tekrar değerlendirilir: yeni Sectigo cert mi, LE HTTP-01 otomasyonu mu.
- Compose nginx hâlâ Vault self-signed servis ediyor — K8s cutover'a kadar kalabilir ya da araya sıkıştırılır (opsiyonel quick-win, Faz 1 içinde).

**Cert dosyaları:**
- Local path: `/Users/halilkocoglu/Downloads/STAR_acik_com1/Nginx/STAR_acik_com.{crt,key}`
- Issuer: Sectigo Public Server Authentication CA DV R36
- Validity: 2026-03-17 → **2026-10-01 (P0 renewal reminder)**

### 2.4 Kapasite & Aşamalı Cutover (FINAL — sabit kaynak)

**Sunucu kaynağı (staging-sw):** 4 vCPU · 24 GiB RAM · 97 GiB disk → **200 GiB (ETA: 2026-04-16, sysadmin onayl\u0131)**. RAM ve CPU sabit, sadece disk büyür. Tasarım disk 200 GB sonrasını varsayar; geçiş döneminde 97 GB ile başlayıp 200 GB'a geçilir.

**RAM bütçesi (2 k3d cluster + scale-to-zero test):**

| Bileşen | Prod cluster | Test cluster | Not |
|---|---|---|---|
| k3s control plane (etcd+apiserver+kubelet+kube-proxy) | ~1.5 GB | ~1.5 GB | **Her cluster ayrı** |
| Calico (node + kube-controllers) | ~180 MB | ~130 MB | Test'te Typha skip |
| CoreDNS | ~100 MB | ~80 MB | |
| ingress-nginx | ~250 MB | ~250 MB | |
| External Secrets Operator | ~200 MB | ~150 MB | |
| ArgoCD (server+repo+controller+redis+dex) | ~1 GB | **0** | Sadece prod'da, test uzaktan yönetilir |
| Monitoring stack (prom+grafana+loki+tempo+promtail+alertmanager) | ~2.5 GB | **0** | Sadece prod'da, test federate/scrape |
| **Cluster overhead (alt toplam)** | **~5.7 GB** | **~2.1 GB** | |
| Backend prod (8 × 384 MB heap) | ~3 GB | - | `-Xmx384m -XX:MaxRAMPercentage=75` |
| Backend test (KAPALI — r=0) | - | 0 GB | Yoğun saat |
| Backend test (AÇIK) | - | ~2 GB | 8 × 256 MB heap |
| OpenFGA + Frontend | ~130 MB | 130 MB (açık) / 0 (kapalı) | |
| **Cluster workload (alt toplam)** | **~3.1 GB** | 0 / ~2.1 GB | |
| **K3d Docker overhead (container OS)** | ~300 MB | ~300 MB | |
| **TOPLAM cluster başına** | **~9.1 GB** | **~2.4 GB (kapalı) / ~4.5 GB (açık)** | |
| Host-level Compose prod (PG+KC+Vault) | 0.97 GB | - | sürekli açık |
| Host-level Compose test (PG+KC+Vault) | - | 0 / 0.97 GB | test açılırken up |
| Host OS + Docker daemon | 1.0 GB | shared | |
| **TÜM SİSTEM — test KAPALI** | | | **~13.5 GB → 10.5 GB yedek ✓** |
| **TÜM SİSTEM — test AÇIK** | | | **~16.5 GB → 7.5 GB yedek ✓** |

**Optimizasyonlar (opsiyonel, gerekirse):**
- Test cluster Typha skip → -150 MB
- Test backend `-Xmx192m` → -500 MB
- Test cluster minimal admission → -80 MB
- **Toplam tasarruf:** ~730 MB (test açık → 15.8 GB'a iner)

**ResourceQuota (FINAL — per cluster):**

Prod cluster:

| Namespace | RAM cap | CPU cap |
|---|---|---|
| `ingress-nginx` | 512 MiB | 0.2 vCPU |
| `external-secrets` | 256 MiB | 0.1 vCPU |
| `argocd` | 1.5 GiB | 0.5 vCPU |
| `monitoring` | 3 GiB | 0.7 vCPU |
| `platform-prod` | 6 GiB | 2 vCPU |

Test cluster:

| Namespace | RAM cap | CPU cap |
|---|---|---|
| `ingress-nginx` | 256 MiB | 0.1 vCPU |
| `external-secrets` | 150 MiB | 0.05 vCPU |
| `platform-test` | 3 GiB | 1 vCPU |

**Pod default LimitRange:** `requests=128Mi/100m, limits=512Mi/500m` (servis bazında override).

**Scale-to-zero test toggle:**
- `scripts/test-toggle.sh up` → `kubectl scale -n platform-test deploy --all --replicas=1` + `docker compose -f host-compose/*/test/docker-compose.yml up -d`
- `scripts/test-toggle.sh down` → tersi
- ArgoCD sync policy test namespace için `ignoreDifferences: [spec.replicas]` (scale manuel yönetilir)

**Aşamalı cutover (disk darlığı yüzünden zorunlu sıralama):**

```
Adım 1  → Hafif docker prune (sadece dangling, kullanıma dokunma)         ~5-10 GB serbest
Adım 2  → k3s kur (containerd ayrı image store; Docker compose ayakta)    +10 GB ihtiyaç
Adım 3  → platform-system + platform-test ayağa kalkar (compose-prod paralel)
Adım 4  → Test smoke testleri YEŞİL (zanzibar, e2e)
Adım 5  → compose-prod STOP (release date: T)
Adım 6  → docker system prune -a --volumes  → ~50 GB serbest (büyük temizlik)
Adım 7  → platform-prod K8s'te ayağa kalkar
Adım 8  → 1 hafta gözlem + rollback hazır (compose-prod restart script <30 sn)
Adım 9  → Compose backend tamamen kaldırılır (host-level PG/KC/Vault KALIR)
```

**Disk projeksiyonu (kritik nokta):**
- Adım 2 sonu: ~84 GB used (%87) ⚠️ — disk monitoring alert eşiği %85 = sınır
- Adım 6 sonu: ~30 GB used (%31) ✓ — rahat
- Steady state (12 ay): retention + state büyümesi ile ~50 GB hedefi

### 2.5 Cluster Topolojisi & Node Mimarisi (FINAL — 2 k3d)

**İki k3d cluster aynı host'ta** (staging-sw + geliştirici makinesi aynı şablon):
- `prod` cluster — üretim workload'ları, merkezi ArgoCD + monitoring
- `test` cluster — sadece workload'lar (ArgoCD/monitoring yok, prod cluster uzaktan yönetir/scrape eder)

**Prod cluster config (`k3d-prod.yaml`):**

```yaml
apiVersion: k3d.io/v1alpha5
kind: Simple
metadata:
  name: prod
servers: 1
agents: 0
image: rancher/k3s:v1.31.x-k3s1
network: platform-prod-net
kubeAPI:
  hostIP: "127.0.0.1"
  hostPort: "6443"
ports:
  - port: "127.0.0.1:30080:80"      # HTTP — host nginx proxy bunu dinler
    nodeFilters: [server:0]
  - port: "127.0.0.1:30443:443"     # HTTPS — kullanılmaz (TLS host'ta termine)
    nodeFilters: [server:0]
options:
  k3s:
    extraArgs:
      - arg: "--disable=traefik"
      - arg: "--disable=servicelb"
      - arg: "--disable=metrics-server"
      - arg: "--flannel-backend=none"
      - arg: "--disable-network-policy"
      - arg: "--cluster-cidr=10.42.0.0/16"
      - arg: "--service-cidr=10.43.0.0/16"
```

**Test cluster config (`k3d-test.yaml`):**

```yaml
apiVersion: k3d.io/v1alpha5
kind: Simple
metadata:
  name: test
servers: 1
agents: 0
image: rancher/k3s:v1.31.x-k3s1
network: platform-test-net           # ayrı Docker network
kubeAPI:
  hostIP: "127.0.0.1"
  hostPort: "7443"                   # prod'dan farklı
ports:
  - port: "127.0.0.1:31080:80"       # prod'dan farklı host port
    nodeFilters: [server:0]
options:
  k3s:
    extraArgs:
      - arg: "--disable=traefik"
      - arg: "--disable=servicelb"
      - arg: "--disable=metrics-server"
      - arg: "--flannel-backend=none"
      - arg: "--disable-network-policy"
      - arg: "--cluster-cidr=10.44.0.0/16"   # farklı pod CIDR
      - arg: "--service-cidr=10.45.0.0/16"   # farklı svc CIDR
      - arg: "--kube-apiserver-arg=enable-admission-plugins=NamespaceLifecycle,ResourceQuota"
      - arg: "--kubelet-arg=max-pods=50"     # test küçük
```

**Host-level nginx SNI proxy (`host-compose/proxy/nginx.conf`):**

```nginx
# mevcut platform-web-nginx YERİNE bu çalışacak
events { worker_connections 1024; }

http {
  # Prod upstream
  upstream prod_k3d { server 127.0.0.1:30080; keepalive 32; }
  upstream test_k3d { server 127.0.0.1:31080; keepalive 32; }

  server { listen 80; return 301 https://$host$request_uri; }

  # ai.acik.com → prod cluster
  server {
    listen 443 ssl http2;
    server_name ai.acik.com;
    ssl_certificate     /etc/nginx/tls/wildcard-acik-com.crt;
    ssl_certificate_key /etc/nginx/tls/wildcard-acik-com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    add_header Strict-Transport-Security "max-age=31536000" always;
    location / {
      proxy_pass http://prod_k3d;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Real-IP $remote_addr;
    }
  }

  # test.acik.com → test cluster
  server {
    listen 443 ssl http2;
    server_name test.acik.com;
    ssl_certificate     /etc/nginx/tls/wildcard-acik-com.crt;
    ssl_certificate_key /etc/nginx/tls/wildcard-acik-com.key;
    location / { proxy_pass http://test_k3d; ... }
  }
}
```

**Node mimarisi diyagramı:**

```
┌──────────────────── staging-sw HOST (4vCPU/24GB/200GB) ──────────────────────┐
│                                                                                │
│  ┌── Host nginx SNI proxy (Docker Compose) ──┐                                 │
│  │  :80  → redirect 443                       │                                 │
│  │  :443 → SSL termination (Sectigo wildcard) │                                 │
│  │         SNI routing:                       │                                 │
│  │         ai.acik.com   → 127.0.0.1:30080    │                                 │
│  │         test.acik.com → 127.0.0.1:31080    │                                 │
│  └────────────────────────────────────────────┘                                 │
│         │                          │                                            │
│         ▼                          ▼                                            │
│  ┌─ k3d cluster: prod ──┐   ┌─ k3d cluster: test ─┐                            │
│  │  API :127.0.0.1:6443 │   │  API :127.0.0.1:7443 │                            │
│  │  Ingress HTTP :30080  │   │  Ingress HTTP :31080  │                            │
│  │                       │   │                       │                            │
│  │  NS:                  │   │  NS:                  │                            │
│  │  ├─ kube-system       │   │  ├─ kube-system       │                            │
│  │  ├─ calico-system     │   │  ├─ calico-system     │                            │
│  │  ├─ ingress-nginx     │   │  ├─ ingress-nginx     │                            │
│  │  ├─ external-secrets  │   │  ├─ external-secrets  │                            │
│  │  ├─ argocd            │   │  └─ platform-test     │                            │
│  │  ├─ monitoring        │   │     (workload r=0     │                            │
│  │  │    (test'i de      │   │      default)         │                            │
│  │  │     scrape eder)   │   │                       │                            │
│  │  └─ platform-prod     │   │                       │                            │
│  │     (backend+openfga  │   │                       │                            │
│  │      +frontend)       │   │                       │                            │
│  └───────────────────────┘   └───────────────────────┘                            │
│         │                          │                                            │
│         │                          │                                            │
│  ┌─ Host Compose (K8s dışı) ────────────────────────────────┐                   │
│  │  PROD: postgres :5432, keycloak :8081, vault :8200       │                   │
│  │  TEST: postgres :5433, keycloak :8082, vault :8201       │                   │
│  │        (test yoğun saatlerde kapalı — toggle script)     │                   │
│  └──────────────────────────────────────────────────────────┘                   │
└────────────────────────────────────────────────────────────────────────────────┘

Cluster içinden host-level servisler:
  Service+Endpoints (IP pin) → 10.9.10.53:<port>

ArgoCD multi-cluster:
  prod cluster'daki ArgoCD hem in-cluster hem "test-cluster" context ile deploy eder
  Test cluster'ı scrape: Prometheus federate / remote_write veya service discovery

Docker network ayrımı:
  platform-prod-net ≠ platform-test-net (Docker bridge ayrı)
  Pod CIDR ayrı (10.42 vs 10.44), Svc CIDR ayrı (10.43 vs 10.45)
```

**Calico seçimi (her iki cluster'da):**
- Flannel NetworkPolicy desteklemez
- `tigera-operator` minimal kurulum (tek node için `Installation.spec.nodeSelector` ile)
- **Test cluster'da Typha skip** (tek node için gereksiz, ~150 MB tasarruf)

**ArgoCD multi-cluster kayıt:**
```bash
# prod cluster'da ArgoCD kurulu
kubectl --context k3d-prod apply -f argocd/install.yaml
# test cluster'ı ArgoCD'ye tanıt
argocd cluster add k3d-test \
  --kubeconfig ~/.kube/config \
  --name test-cluster \
  --project platform
# Application'lar `destination.name: test-cluster` ile test'e gider
```

### 2.6 GitOps Akışı

```
Developer                 platform-k8s-gitops           ArgoCD                k3s cluster
    │                           │                          │                       │
    ├── kustomize edit ────────>│                          │                       │
    │                           │                          │                       │
    │   git commit + push ─────>│                          │                       │
    │                           │<─── poll (3 min) ────────┤                       │
    │                           │                          │                       │
    │                           │─── manifest diff ───────>│                       │
    │                           │                          ├── kubectl apply ─────>│
    │                           │                          │                       │
```

---

## 3. Dizin Yapısı

```
platform-k8s-gitops/
├── PLAN.md                     # Bu dosya (son durum + yol haritası)
├── README.md                   # Repo amacı, bootstrap, nasıl başlatılır
├── .gitignore                  # secrets, .env, state, .DS_Store
│
├── kustomize/
│   ├── base/                   # Ortam-bağımsız manifest'ler
│   │   ├── host-services/      # ExternalName Service + Endpoints (PG/KC/Vault köprüsü)
│   │   ├── authz/
│   │   │   └── openfga/        # StatefulSet + Service + migrate Job
│   │   ├── apps/
│   │   │   ├── discovery-server/
│   │   │   ├── user-service/
│   │   │   ├── auth-service/
│   │   │   ├── variant-service/
│   │   │   ├── core-data-service/
│   │   │   ├── report-service/
│   │   │   ├── schema-service/
│   │   │   ├── permission-service/  # NOT: zanzibar-openfga.v1.json kuralı — legacy, yeni kullanım yok
│   │   │   └── api-gateway/
│   │   ├── frontend/           # nginx + MFE shell
│   │   └── monitoring/         # ServiceMonitor CR'ları
│   └── overlays/
│       ├── local/              # k3d — image: Never, ingress: *.localtest.me
│       ├── test/               # platform-test ns — ingress: test.acik.com (path-based)
│       └── prod/               # platform-prod ns — ingress: ai.acik.com (path-based)
│
├── helm-values/                # 3. parti chart values
│   ├── ingress-nginx/
│   ├── cert-manager/
│   ├── external-secrets/
│   ├── argocd/
│   ├── kube-prometheus-stack/
│   ├── loki/
│   └── tempo/
│
├── host-compose/               # Sunucu host-level Docker Compose
│   ├── env/                    # .env örnekleri (gerçek .env git-ignored)
│   ├── vault/
│   │   ├── test/docker-compose.yml
│   │   └── prod/docker-compose.yml
│   ├── keycloak/
│   │   ├── test/docker-compose.yml
│   │   └── prod/docker-compose.yml
│   └── state/                  # volume mount noktaları (git-ignored)
│       ├── test/
│       └── prod/
│
├── argocd/
│   └── applications/           # ArgoCD Application CR'ları (app-of-apps)
│       ├── root.yaml           # app-of-apps kök
│       ├── platform-test.yaml
│       ├── platform-prod.yaml
│       └── platform-system.yaml
│
└── docs/                       # (ileride) runbook'lar, diagram'lar
```

---

## 4. Faz Yol Haritası

### Faz 0 — Ön Hazırlık ✅ TAMAMLANDI
- [x] İskelet dizin ağacı
- [x] `git init` (bu repoda)
- [x] Karar kilitleme (bu PLAN.md)

### Faz 1 — Repo Temeli
- [ ] `README.md` — repo amacı + bootstrap komutları
- [ ] `.gitignore` — secrets, state/, .env, .DS_Store
- [ ] İlk commit: "initial plan + skeleton"
- [ ] **DNS ticket**: sysadmin'e `test.acik.com` A → `10.9.10.53` kaydı için talep (Windows AD DNS)
- [ ] **Opsiyonel quick-win**: mevcut compose `platform-web-nginx`'i Vault self-signed'dan Sectigo wildcard cert'e geçir (K8s öncesi tarayıcı uyarısını kapat)

### Faz 2 — Host-Level Servisler (Docker Compose)
- [ ] `host-compose/vault/test/docker-compose.yml` + `prod/`
- [ ] `host-compose/keycloak/test/docker-compose.yml` + `prod/`
- [ ] `host-compose/env/vault.env.example`, `keycloak.env.example`
- [ ] PostgreSQL: mevcut compose'daki konfig referans alınacak (`backend/docker-compose.yml` → postgres-db servisi)
- [ ] **Kabul kriteri:** test+prod için 6 container (2x PG, 2x KC, 2x Vault) host'ta ayağa kalkıyor, port çakışması yok

### Faz 3 — Cluster Platform (Helm values + 2 k3d kurulumu)

**Cluster setup:**
- [ ] `bootstrap/k3d-prod.yaml` — prod cluster config
- [ ] `bootstrap/k3d-test.yaml` — test cluster config
- [ ] `bootstrap/setup-clusters.sh` — `k3d cluster create --config k3d-prod.yaml && k3d cluster create --config k3d-test.yaml`
- [ ] `bootstrap/install-calico.sh` — tigera-operator her iki cluster'a apply
- [ ] `host-compose/proxy/` — host-level nginx SNI proxy Compose + nginx.conf + TLS volume

**Platform bileşenleri (prod cluster):**
- [ ] `helm-values/ingress-nginx/values.yaml` — **prod**: HTTP-only (TLS host'ta), hostPort 30080
- [ ] ~~wildcard cert Secret bootstrap in cluster~~ **DEĞİŞTİ**: TLS host nginx'te, cluster içinde cert Secret'a gerek YOK
- [ ] ~~`helm-values/cert-manager/values.yaml`~~ **DEFER**
- [ ] `helm-values/external-secrets/values.yaml` + Vault ClusterSecretStore (prod Vault URL)
- [ ] `helm-values/argocd/values.yaml` (SSO ile Keycloak bağlantısı; path prefix `/argocd`, multi-cluster için tek instance)
- [ ] `helm-values/kube-prometheus-stack/values.yaml` (Grafana path prefix `/grafana`, Prometheus `/prometheus`, test cluster'ı scrape federate)
- [ ] `helm-values/loki/values.yaml`
- [ ] `helm-values/tempo/values.yaml`

**Platform bileşenleri (test cluster — minimal):**
- [ ] `helm-values/ingress-nginx-test/values.yaml` — **test**: HTTP-only, hostPort 31080
- [ ] `helm-values/external-secrets-test/values.yaml` + Vault ClusterSecretStore (test Vault URL)
- [ ] ArgoCD YOK (prod cluster uzaktan yönetecek)
- [ ] Monitoring YOK (prod cluster'dan scrape)

**ArgoCD multi-cluster kayıt:**
- [ ] `argocd cluster add k3d-test --name test-cluster --project platform`

**Kabul kriteri:** 
- İki k3d cluster ayakta, `kubectl get nodes` her ikisinde çalışır
- Host nginx SNI proxy 443'ü alır, `ai.acik.com` prod cluster'a, `test.acik.com` test cluster'a yönlendirir (dummy backend ile test)
- Prometheus test cluster'ı federate edebiliyor (`up{job="test-federate"}` metriği var)

### Faz 4 — Kustomize Base: Host Service Köprüleri
- [ ] `kustomize/base/host-services/postgres-svc.yaml` (ExternalName + Endpoints)
- [ ] `kustomize/base/host-services/keycloak-svc.yaml`
- [ ] `kustomize/base/host-services/vault-svc.yaml`
- [ ] `kustomize/base/host-services/kustomization.yaml`
- [ ] **Kabul kriteri:** k3d'den `kubectl exec` ile busybox pod'dan `nc -vz postgres.svc 5432` bağlanır

### Faz 5 — Kustomize Base: OpenFGA
- [ ] StatefulSet (1 replica, migrate InitContainer)
- [ ] Service (4000/4001)
- [ ] Secret → ExternalSecret (Vault'tan `OPENFGA_STORE_ID`, `OPENFGA_MODEL_ID`)
- [ ] migrate Job (Helm hook benzeri)
- [ ] **Kabul kriteri:** k3d'de openfga ayaklanır, postgres-svc'ye bağlanır

### Faz 6 — Kustomize Base: Backend Apps (şablon + çoğaltma)
- [ ] `user-service/` — şablon olarak tam yaz (Deployment, Service, ConfigMap, HPA, PDB, ServiceMonitor, NetworkPolicy, ExternalSecret)
  - Resource: `requests: 256Mi/100m, limits: 512Mi/500m`, JVM `-Xmx384m` (prod) / `-Xmx256m` (test overlay)
- [ ] `auth-service/`, `variant-service/`, `core-data-service/`, `report-service/`, `schema-service/` — copy+edit
- [ ] ~~`permission-service/`~~ **SKIP** (legacy, kaldırıldı)
- [ ] ~~`discovery-server/` (Eureka)~~ **SKIP** (D7 revize: K8s native DNS kullanılacak)
- [ ] `api-gateway/` — en son, route'lar + rate limit config
  - Route hedefleri: `lb://user-service` → `http://user-service.platform-prod.svc.cluster.local:8089` (Eureka URI'leri svc URL ile değişir)
- [ ] **Kabul kriteri:** k3d'de api-gateway'den `/actuator/health/readiness` 200 döner, **tüm servis-arası çağrılar K8s svc DNS üzerinden çalışır** (curl `http://user-service.platform-test.svc.cluster.local:8089/actuator/health` test pod'undan)

### Faz 7 — Kustomize Base: Frontend
- [ ] nginx Deployment (MFE shell + remote'lar için path mapping)
- [ ] ConfigMap (nginx.conf — MF resilience için cache header'lar)
- [ ] Service
- [ ] **Kabul kriteri:** k3d'de shell açılır, remote'lar yüklenir, white screen yok

### Faz 8 — Kustomize Base: Monitoring
- [ ] ServiceMonitor CR'ları (her Spring Boot servisi için `/actuator/prometheus`)
- [ ] PrometheusRule'lar (mevcut `backend/infra/observability/alerts/` dosyalarından port)
- [ ] Grafana dashboard ConfigMap'leri (JSON import)

### Faz 9 — Overlay'ler
- [ ] `overlays/local/` — k3d için
  - image pull policy: Never
  - ingress: `*.localtest.me` (RFC2606 local-test domain)
  - replica: 1
  - resources: minimum
- [ ] `overlays/test/` — platform-test ns
  - image tag: `sha-<short>`
  - ingress: `test.acik.com` (path-based), TLS secret: `wildcard-acik-com-tls`
  - **replica: 0 (scale-to-zero default, D17)** — `test-toggle.sh up` ile 1'e çekilir
  - PriorityClass: `low-priority`
  - ArgoCD sync: `ignoreDifferences: [/spec/replicas]` (scale manuel)
- [ ] `overlays/prod/` — platform-prod ns
  - image tag: `v<semver>` (ArgoCD Image Updater önerilir)
  - ingress: `ai.acik.com` (path-based), TLS secret: `wildcard-acik-com-tls` (aynı)
  - replica: 2 (HPA 2-4)
  - PDB: minAvailable 1

### Faz 10 — ArgoCD Applications
- [ ] `argocd/applications/root.yaml` — app-of-apps kök
- [ ] `argocd/applications/platform-system.yaml` — helm-values içeriğini sync eder
- [ ] `argocd/applications/platform-test.yaml` — `overlays/test/` sync
- [ ] `argocd/applications/platform-prod.yaml` — `overlays/prod/` sync (manual sync!)
- [ ] **Kabul kriteri:** ArgoCD UI'da 4 application healthy + synced

### Faz 11 — Ana Repo Paralel İş (`autonomous-orchestrator`)
Bu repo'da DEĞİL, ana repo'da yapılacaklar. Manifest yazımıyla eş zamanlı ilerler.

- [ ] Her backend servise `src/main/resources/application-k8s.yml` profili
  - **Eureka kaldırma**: `spring.cloud.discovery.enabled=false`, `eureka.client.enabled=false` (default)
  - Actuator: `management.endpoints.web.exposure.include=health,prometheus,info`
  - `management.endpoint.health.probes.enabled=true` (startup/liveness/readiness ayrımı)
  - JVM: `JAVA_TOOL_OPTIONS=-Xmx384m -XX:MaxRAMPercentage=75` (prod) / `-Xmx256m` (test)
- [ ] **Eureka temizliği** (kod değişikliği):
  - `@EnableEurekaClient` / `@EnableDiscoveryClient` annotation'larını kaldır
  - `@LoadBalanced RestTemplate`/`WebClient.Builder` → K8s svc URL'leri (config'den okunur)
  - `pom.xml`: `spring-cloud-starter-netflix-eureka-client` dependency → kaldır
  - `discovery-server` modülü → arşivle (silme, ileride compose-fallback için kalabilir)
  - api-gateway route'ları: `lb://...` → `http://<svc>.<ns>.svc.cluster.local:<port>`
- [ ] Dockerfile güncelleme: non-root user + USER direktifi
- [ ] `decisions/topics/kubernetes-migration.v1.json` — ADR yaz (Eureka kaldırma + capacity strategy + path-based ingress)
- [ ] `docs/OPERATIONS/INFRASTRUCTURE-ENVIRONMENTS.md` güncelleme (K8s ortamı eklenir)
- [ ] `scripts/doctor-k8s.sh` — K8s için health check script'i (mevcut `doctor-infra.sh` paralel)

### Faz 12 — Lokal Doğrulama (k3d)
- [ ] `k3d cluster create platform --config <...>` komutu dokümante
- [ ] Tam E2E: ingress → gateway → servisler → openfga → host-PG bağlantı
- [ ] MFE shell + remote'lar çalışır
- [ ] Grafana'da metrikler akıyor

### Faz 13 — Staging (staging-sw) Deploy
- [ ] k3s cluster hazırlığı (staging-sw'de)
- [ ] Host-level PG/KC/Vault Compose kurulumu (test+prod paralel)
- [ ] `kubectl apply -k kustomize/overlays/test/` → platform-test
- [ ] Smoke testleri: `.github/workflows/smoke-zanzibar.yml` paralel K8s versiyonu
- [ ] 1 hafta staging gözlem

### Faz 14 — GitHub Remote + ArgoCD Bağlama
- [ ] `gh repo create halildeu/platform-k8s-gitops --private`
- [ ] `git push -u origin main`
- [ ] ArgoCD repo credential (deploy key)
- [ ] ArgoCD `root.yaml` apply → app-of-apps devreye

### Faz 15 — Production Cutover
- [ ] Blue/green: mevcut compose prod = blue, k3s prod = green
- [ ] DNS traffic kaydırma (%10 → %50 → %100)
- [ ] Rollback planı: compose prod 72 saat ayakta kalır
- [ ] Compose decommission (2 hafta sonra)

---

## 5. Ana Repo Bağlantısı

**autonomous-orchestrator** içinde kalacaklar:
- Backend kaynak kod (değişmez)
- Dockerfile'lar (güncellenecek: non-root)
- `application-k8s.yml` profilleri (yeni)
- `decisions/topics/kubernetes-migration.v1.json` (yeni ADR)
- CI/CD: `deploy-backend.yml` → GHCR push aynen kalır
- `scripts/doctor-k8s.sh` (yeni)

**Bu repo'ya taşınmayacaklar:** Hiç K8s manifest'i ana repo'ya girmez. Temiz ayrım.

---

## 6. Riskler ve Mitigasyon

| Risk | Etki | Mitigasyon |
|------|------|-----------|
| Eureka + K8s Service çifte discovery | Servis çağrıları confused | Eureka'yı K8s içinde single-replica + Headless Service, kısa süreli gözlem |
| Host-level PG'ye ağ erişim | Cluster ↔ host network izolasyonu | ExternalName Service + Endpoints ile statik mapping, network policy |
| Vault secret migration | Prod down riski | Önce test namespace'de ESO test et, prod'a son geç |
| MFE React duplicate (mevcut blocker) | White screen | K8s öncesi bu çözülmeli — nginx cache header'ları Faz 7'de revize |
| Decision registry ihlali | permission-service port 8090 yanlışlıkla eklenir | Her PR'da `doctor-zanzibar.sh --quick` koş |
| Cron deploy aktif edilirse erken push | Yarım manifest prod'a gider | DEPLOY_ENABLED=false kalır Faz 15'e kadar |
| **Wildcard cert expiry 2026-10-01** | prod + test TLS kesintisi | **P0 reminder 2026-09-01**: yeni Sectigo cert al ya da cert-manager + LE HTTP-01 otomasyonu aç. Renewal öncesi Secret rotate prosedürü test edilmeli |
| Dış proxy (212.115.26.190) başkasının yönetiminde | `ai.acik.com` üzerinde operasyonel değişiklikler koordinasyon ister | L4 pass-through varsayımı doğrulanmalı (sysadmin'e sor); değilse strateji değişir |
| `test.acik.com` DNS kaydı sysadmin gecikmesi | Faz 12/13 bloklanır | Faz 1'de erken ticket aç, paralel iş |
| **Eureka kaldırma kod değişikliği** (D7 revize) | Servis-arası çağrılar bozulur | Faz 11'de annotation + pom + route URL'leri sistematik temizle. Önce tek servis (örn. user-service) PoC, smoke yeşil olunca diğerlerine yay |
| **24 GB RAM dar bütçe** | OOM, swap'a düşme, prod degradasyon | Resource quota + LimitRange ZORUNLU. JVM heap explicit `-Xmx`. Retention KISA. Geçiş döneminde compose-prod + K8s-test paralel iken RAM <22 GB tut |
| **Disk %80 dolu, geçiş döneminde %87'ye** | k3s image pull başarısız, cluster instabil | Önce hafif prune; compose-prod stop sonrası `docker system prune -a` ile büyük temizlik. **Disk artırma opsiyonu açık** (sysadmin) |

---

## 7. Sonraki Session'a Bootstrap

**Bu dosyadan başlayacak session için:**

```
Ben şu anda /Users/halilkocoglu/Documents/platform-k8s-gitops/ dizinindeyim.
Bu repo autonomous-orchestrator platformunun K8s GitOps manifest'lerini tutar.
PLAN.md içindeki kararlar FINAL'dir, Faz 0 tamamlandı.
Devam edeceğim faz: Faz 1 — Repo Temeli (README + .gitignore + ilk commit).
```

**Referanslar (yeni session bu dosyaları okumalı):**
- `PLAN.md` (bu dosya) — tüm kararlar + yol haritası
- `/Users/halilkocoglu/Documents/dev/CLAUDE.md` — ana repo kuralları
- `/Users/halilkocoglu/Documents/dev/AGENTS.md` — orchestrator contract
- `/Users/halilkocoglu/Documents/dev/decisions/topics/zanzibar-openfga.v1.json` — auth FINAL kararlar
- `/Users/halilkocoglu/Documents/dev/backend/docker-compose.yml` — mevcut servis konfigi (manifest üretirken referans)
- `/Users/halilkocoglu/Documents/dev/deploy/docker-compose.prod.yml` — prod env konfigi

**Mevcut ana repo durumu (2026-04-14):**
- Worktree: `zealous-margulis` (branch: `claude/zealous-margulis`)
- Son compose stabilizasyon commit'leri: #357–#363
- Zanzibar Faz 2+3 tamam, Faz 4 %90
- Aktif blocker: MFE React duplicate → K8s öncesi çözülmeli

---

## 8. Değişiklik Kaydı

| Tarih | Değişiklik |
|-------|-----------|
| 2026-04-14 | İlk yazım — 15 faz, 14 FINAL karar kilitlendi |
| 2026-04-14 | **DNS & TLS bloğu netleşti** — D8 revize (wildcard Sectigo cert manuel, cert-manager DEFER), Bölüm 2.3 Hostname & TLS eklendi (path-based routing), Faz 1'e DNS ticket + quick-win, Faz 3 cert-manager çıkarıldı, 3 yeni risk (cert expiry 2026-10-01, dış proxy bağımlılığı, DNS ticket gecikmesi) |
| 2026-04-14 | **Kapasite & Eureka netleşti** — D7 revize (Eureka KALDIRILDI, K8s native DNS), Bölüm 2.4 Kapasite & Aşamalı Cutover eklendi (sabit 24GB/4vCPU/97GB bütçe, namespace quota tablosu, 9 adımlı cutover sırası), Faz 6 (discovery+permission SKIP), Faz 11 (Eureka kod temizliği detaylı), 3 yeni risk (Eureka kaldırma, RAM darlığı, disk darlığı). Disk artırma opsiyonu beklemede |
| 2026-04-14 | **Disk 200 GB onaylandı** (ETA 2026-04-16). Bölüm 2.4 güncellendi. Disk darlığı riski PASIF. RAM 24 GB sabit kalıyor — Eureka kaldırma + JVM heap sıkıştırma + quota stratejisi devam |
| 2026-04-14 | **Cluster mimari netleşti** — D2 revize (5 ns), D15 Calico CNI, D16 tek cluster, **D17 scale-to-zero test** (yoğun saatlerde test KAPALI, RAM=0), D18 hostNetwork ingress, D19 Service+Endpoints host köprü, D20 prod=mevcut portlar. Bölüm 2.5 Cluster Topoloji eklendi (k3s install flags, k3d config, namespace diyagramı). RAM bütçesi iki senaryolu tablo (kapalı 10.3 GB / açık 13.3 GB) |
| 2026-04-14 | **2 k3d cluster mimarisine geçildi** — D16 revize (tek k3s → 2 k3d aynı host), D18 revize (hostNetwork ingress → host nginx SNI proxy 443'ü alır, cluster içi HTTP-only). Gerekçe: "birini bozunca diğeri bozuluyor" deneyimine karşı kontrol düzlemi fiziksel ayrımı. Bölüm 2.5 tamamen yeniden yazıldı (k3d-prod/test.yaml config, host nginx SNI proxy nginx.conf, iki cluster diyagramı, ArgoCD multi-cluster). Bölüm 2.4 RAM tablosu cluster-başına detaylı (test kapalı 13.5 GB / açık 16.5 GB, 24 GB'ta rahat). Faz 3 2 cluster setup'a göre revize |

