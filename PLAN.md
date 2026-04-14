# platform-k8s-gitops — Canlı Geçiş Planı

**Repo amacı:** Bu repo `autonomous-orchestrator` platformunun Kubernetes GitOps manifest'lerini tutar. Docker Compose üzerinden k3s cluster'a tam geçiş için **tek doğruluk kaynağıdır**. Bu repo'dan geliştirilen yapı, testler yeşil olduğunda **doğrudan canlıya alınır** — deneysel/atılabilir yapı değildir.

**Son güncelleme:** 2026-04-14
**Durum:** İskelet klasörler hazır, manifest yazımı başlamadı

---

## 1. Kilitli Kararlar (FINAL)

| # | Karar | Değer |
|---|---|---|
| D1 | Deployment hedefi | k3s (staging-sw sunucusu), tek cluster |
| D2 | Namespace stratejisi | `platform-test` + `platform-prod` (aynı cluster, namespace izolasyonu) |
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

**RAM bütçesi (hedef):**

| Bileşen | RAM | Not |
|---|---|---|
| k3s control plane (etcd+apiserver+kubelet+kube-proxy) | ~1.5 GB | Tek node |
| ingress-nginx + ESO + ArgoCD | ~1.5 GB | platform-system ns |
| kube-prometheus-stack + Loki + Tempo + Promtail | ~2-2.5 GB | retention KISA: prom 7d, loki 7d, tempo 3d |
| **K8s overhead toplam** | **~5-5.5 GB** | |
| platform-prod backend (8 servis × 350 MB heap, Eureka+permission yok) | ~2.8 GB | `-Xmx` her servis için explicit |
| platform-test backend (8 servis × 256 MB heap) | ~2 GB | dar heap, sadece test trafiği |
| OpenFGA (StatefulSet, prod+test) | ~150 MB | |
| Frontend nginx (prod+test) | ~50 MB | |
| Host-level Compose (PG×2, KC×2, Vault×2) | ~1.5 GB | K8s dışı, mevcut |
| **Workload toplam** | **~6.5 GB** | |
| **Cluster + workload TOPLAM** | **~12 GB** | 24 GB içinde rahat ✓ |

**Resource quota (FINAL):**

| Namespace | RAM cap | CPU cap |
|---|---|---|
| `platform-system` | 4 GiB | 1.5 vCPU |
| `platform-prod` | 8 GiB | 2 vCPU |
| `platform-test` | 6 GiB | 1.5 vCPU |

**Pod default LimitRange:** `requests=128Mi/100m, limits=512Mi/500m` (servis bazında override).

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

### 2.5 GitOps Akışı

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

### Faz 3 — Cluster Platform (Helm values)
- [ ] `helm-values/ingress-nginx/values.yaml`
- [ ] **wildcard cert Secret bootstrap** — `kubectl -n ingress-nginx create secret tls wildcard-acik-com-tls --cert=... --key=...` (manuel; GitOps'a girmez, `.gitignore`'lu dokümante script)
- [ ] ~~`helm-values/cert-manager/values.yaml` + ClusterIssuer (Let's Encrypt)~~ **DEFER** — 2026-09 civarı renewal öncesi yeniden değerlendirilir
- [ ] `helm-values/external-secrets/values.yaml` + Vault ClusterSecretStore
- [ ] `helm-values/argocd/values.yaml` (SSO ile Keycloak bağlantısı; path prefix `/argocd`)
- [ ] `helm-values/kube-prometheus-stack/values.yaml` (Grafana path prefix `/grafana`, Prometheus `/prometheus`)
- [ ] `helm-values/loki/values.yaml`
- [ ] `helm-values/tempo/values.yaml`
- [ ] **Kabul kriteri:** k3d cluster'da `helm install` ile hepsi çalışır, Grafana açılır (path prefix ile)

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
  - replica: 1
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

