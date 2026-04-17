# platform-k8s-gitops — Canlı Geçiş Planı

**Repo amacı:** Bu repo `autonomous-orchestrator` platformunun Kubernetes GitOps manifest'lerini tutar. Docker Compose üzerinden k3s cluster'a tam geçiş için **tek doğruluk kaynağıdır**. Bu repo'dan geliştirilen yapı, testler yeşil olduğunda **doğrudan canlıya alınır** — deneysel/atılabilir yapı değildir.

**Son güncelleme:** 2026-04-14 (Codex Tur-4 uzlaşı + drift cleanup)
**Durum:** PoC Dilim 1 manifest'leri + platform katmanı (ingress-nginx, ArgoCD, kube-prometheus-stack, Loki, Promtail, Tempo) + NetworkPolicy + Quota/LimitRange + ServiceAccount/imagePullSecret şablonu yazıldı. Lokal k3d-prod'da doğrulandı (pod'lar Ready, ingress/quota/NP aktif). Ana repoda (`autonomous-orchestrator`) auth-service + api-gateway Eureka kaldırma işi beklemede → image hazır olunca Dilim 1 smoke test. Test cluster (k3d-test) henüz ayakta değil. ESO/Vault auth henüz kapalı (stub Secret). Disk ETA 2026-04-16 staging-sw'de.

---

## 1. Kilitli Kararlar (FINAL)

| # | Karar | Değer |
|---|---|---|
| D1 | Deployment hedefi | staging-sw üzerinde aynı hostta iki ayrı `k3d` cluster: `prod` + `test`. Bu karar HA/DR değil, **izolasyon** kararıdır |
| D2 | Namespace stratejisi | **Cluster-bazlı**. Prod cluster: `platform-prod`, `ingress-nginx`, `external-secrets`, `argocd`, `monitoring`. Test cluster: `platform-test`, `ingress-nginx`, `external-secrets`. Prod/test aynı cluster'ı **paylaşmaz** |
| D3 | Lokal dev | k3d (Docker Desktop üzerinde) |
| D4 | GitOps motoru | ArgoCD (app-of-apps pattern) |
| D5 | Manifest yönetimi | Kustomize (base + overlays) + Helm (3. parti chart'lar için) |
| D6 | Host-level servisler | PG + Keycloak + Vault → **Kubernetes DIŞINDA** Docker Compose ile host'ta çalışır, test+prod ayrı instance |
| D7 | Service discovery | **Eureka KALDIRILDI** — K8s native DNS (`<svc>.<ns>.svc.cluster.local`). **Dilimli geçiş** (Codex onayı): her PoC diliminde backend + çağıranlar + gateway route birlikte temizlenir. Geçici Eureka YOK |
| D8 | Ingress + TLS | TLS host-level nginx'te termine edilir (cluster içi ingress-nginx HTTP-only). MVP: manuel Sectigo wildcard rotation + script + `60/30/7d` uyarı takvimi + panel erişim doğrulaması. Faz 12 sonrası: yalnız `ai.acik.com` için LE HTTP-01 **dry-run**; başarılıysa otomasyona geç, başarısızsa manuel sürer |
| D9 | Secret | External Secrets Operator + Vault (mevcut Vault source-of-truth kalır) |
| D10 | Observability | kube-prometheus-stack + Loki + Tempo (Helm). **Retention**: Prometheus 10 gün, Loki 7 gün, Tempo 48 saat (MVP). Gerçek ingest ölçüldükten sonra artırma değerlendirilir |
| D11 | Image registry | GHCR (mevcut `deploy-backend.yml` push akışı korunur) |
| D12 | Git stratejisi | Lokal `.git` aktif + **GitHub private remote** (`Halildeu/platform-k8s-gitops`, 2026-04-15 aktif). Lokal → push. Sunucuda deploy key (read-only, port 443 SSH). install-on-staging-sw.sh rsync yerine `git clone/pull`. ArgoCD GitOps bu URL'i kullanır |
| D13 | Yaklaşım | Doğrudan canlı-ready yapı — atılabilir/deney değil |
| D14 | Ana repo paralel | `application-k8s.yml` profili + Dockerfile probe'ları K8s manifest yazımıyla **eş zamanlı** yazılır |
| D15 | CNI | **Calico** (başlangıçtan) — NetworkPolicy garantisi. Flannel değil. +200 MB RAM kabul |
| D16 | Cluster topolojisi | **2 k3d cluster aynı host'ta** (staging-sw): `prod` + `test`. Docker container'larda ayrı k3s node'ları (ayrı API server, etcd, CNI, Docker network, Pod/Svc CIDR). Gerekçe: "birini bozunca diğeri etkileniyor" tecrübesinin tekrarlanmaması. Lokal geliştirici makinede de aynı iki-cluster modeli |
| D17 | Test ortamı çalışma modeli | **Scale-to-zero workload**: test cluster control plane açık (~2 GB sabit), workload'lar default `replicas: 0`. Yoğun saatlerde backend+openfga+frontend kapalı (~0 GB). İhtiyaç halinde `test-toggle.sh up`. Host-level test PG/KC/Vault de kapalı varsayılan |
| D18 | İngress + TLS termination | **Host-level nginx SNI reverse proxy** (mevcut `platform-web-nginx` yerine) 80/443 alır, Sectigo wildcard cert'i termine eder. Hostname'e göre backend: `ai.acik.com` → prod k3d HTTP :30080, `testai.acik.com` → test k3d HTTP :31080. Cluster'ların içindeki ingress-nginx HTTP-only (cert'i host handle ediyor) |
| D19 | Host servis köprüsü | **Service + Endpoints** (IP pin `10.9.10.53`). ExternalName yerine; CoreDNS rewrite kırılgan |
| D20 | Host port ataması | **Mevcut portlar = PROD (`5432, 8081, 8200`)**, yeni portlar = TEST (`5433, 8082, 8201`). Prod verisi migrasyonu YOK |
| D21 | HPA & replica | **MVP'de HPA YOK**. `metrics-server` kapalı kalır. Prod sabit `replicas: 2`, test açıldığında `replicas: 1`. HPA ancak ilk gerçek CPU/latency grafiği toplandıktan sonra geri açılabilir. **Gerekçe**: metrics-server disabled + HPA birlikte tutarsızdı (Codex Tur-1) |
| D22 | CPU bütçesi | Steady-state test kapalı `1.6-2.2 vCPU`, test açık `2.0-2.8 vCPU`; spike (prom compaction + loki flush + rollout aynı anda) `3.4-4.0 vCPU`. **Politika**: CPU request dar ama gerçekçi, limit cömert. `request=limit` yapılmaz. Örüntü: backend `req 150m / lim 750-1000m`, ağır 2-3 servis `req 250-300m`, gateway `req 250m`, kritik podda limit olmayabilir |
| D23 | DR / RPO / RTO | **Prod**: RPO ≤ 24 saat, RTO ≤ 4 saat. **Test**: RPO ≤ 24 saat, RTO ≤ 1 iş günü. Off-host backup (PG dump + Vault raft snapshot farklı host/object storage'a), düzenli restore provası, stateful/node bakım runbook'u **zorunlu**. Tek host bu karar seviyesini destekler — RPO <1h istenirse mimari değişir |
| D24 | JVM bellek politikası | **Ortak explicit heap**: `-Xmx384m` (prod default), ağır 2-3 serviste override (512m), test overlay'de `-Xmx256m`. `-XX:MaxRAMPercentage` **KALDIRILDI** (Xmx ile çelişiyor, yanlış beklenti üretiyordu). Container `resources.limits.memory: 512Mi` (heap + metaspace + direct buffer + JIT için tampon) |
| D25 | PoC dilim stratejisi | Tam manifest çoğaltmasına **geçilmez**, önce ince dilim: `api-gateway + auth-service` (Dilim 1) → `api-gateway + user-service` (Dilim 2) → kalan backend'ler bağımlılık grafına göre. **Kabul kriteri (Dilim 1)**: gateway route `lb://` yok → K8s svc DNS, `auth-service` Eureka'sız kalkar, Keycloak/DB host köprüsü çalışır, smoke yeşil |
| D26 | YAPMA listesi | MVP kapsamında **yok**: MetalLB, GraalVM, K8s içinde geçici Eureka, aynı hosttaki 2 cluster'ı DR/HA gibi sunma, admin UI'ları aynı hostname altında sertleştirmeden bırakma |
| D27 | Upstream-first prensibi | Her bileşen **kendi upstream native mekanizmasını** kullanır: k3s (Rancher), Calico (tigera-operator), ArgoCD (upstream Helm + dex OIDC built-in), kube-prometheus-stack (upstream Helm), External Secrets Operator (upstream CRD), Loki/Tempo (upstream Helm). Bizim yazdığımız custom kod **minimum**: sadece `bootstrap/*.sh` (orchestration), `host-compose/proxy/nginx.conf` (reverse proxy), `kustomize/base/apps/<service>/` (backend manifest'leri, Helm chart değil çünkü zaten build pipeline'ı bizim). **YASAK**: custom admission webhook, özel operator, manuel YAML patch'leri (Kustomize strategic merge yerine). **Gerekçe**: satıcı kilidi yok, upgrade yolu net, community desteği aktif |
| D28 | Handoff şablonu | 5-alan **zorunlu**: `(Bağlam / İddia / İspatlar / İspatlamaz / Bilinen boşluk)`. Tek iddia yeterli değil; her bulgu kanıt ve sınır koşulu ile raporlanır. İlk örnek: `docs/session-handoff-2026-04-17.md`. Sebep: handoff v1↔v2 kanıt sınıfı yarılması (v2 "tam yeşil" iddiası v1'in şüphelerini kapatmadan yazıldı). Kural 2026-04-17 Codex 4-tur mutabakatı |
| D29 | Raporlama seviyeleri | Tek "green" etiketi **YASAK**. 3 seviye zorunlu: (1) **Up** = Pod Ready + edge gerçek backend + kritik dep TCP açık; (2) **Functional** = Up + ana işlev doğru dep ile çalışıyor; (3) **Zanzibar-ready** = Functional + permission-service hub yayında + OpenFGA enabled + `/authz/me`+`/authz/version` + synthetic allow/deny enforce kanıtlı. Ayrıca **Dilim 1A** (authn/transport slice) ≠ **Dilim 1Z** (authz plane env doğru); auth-service permission-service'siz boot edebilir ama "Dilim 1 tamam" denmez |
| D30 | Cutover stratejisi | Weighted DNS (%10→50→100) **DEĞİL**. Tek-seferlik proxy upstream switch (`ai.acik.com` compose → `k3d-prod:30080` host nginx reload) + **72 saat warm rollback** (compose canlı ama trafik dışı). Ayrıca: test/prod overlay'lerde **digest pin** (repo@sha256) zorunlu, moving tag (`main-stable`) tek başına kanıt değil; pod `imageID` ↔ GHCR digest eşleşmesi doğrulanır. Sebep: weighted için session/cache/side-effect güvenliği ayrı doğrulanmalı — şu anki tasarımda gereksiz risk |
| D31 | Primary datasource mimarisi | **Tüm mimari PostgreSQL üzerine** kuruludur; PG varsayılan DB (auth, user, variant, core, report, schema, permission, openfga, keycloak). **Dış SQL (MSSQL vb.) secondary/opsiyonel** integration — örn. report/schema Workcube ERP'den `reporting` ve `workcube_mikrolink` DB'lerine **read-only** bağlanır. Dev repo `application-k8s.yml` report/schema için `SQLServerDriver` PRIMARY varsayması **YANLIŞ** → `platform-ssot` tarafında primary PG + secondary MSSQL multi-datasource pattern'e geçilmeli. MSSQL host köprüsü gerekirse D19 pattern (Service+Endpoints IP pin) + ESO-Secret credentials. MSSQL feature **cutover blocker DEĞİL** — feature-flagged opsiyonel |

**HARD RULES:**
- **D16 gereği**: `prod` ve `test` **AYRI k3d cluster**'larında çalışır (aynı host'ta ama farklı control plane). Her cluster'da kendi `platform-*` ns'i, kendi `ingress-nginx` + `external-secrets` ns'i. Prod cluster'ında ayrıca `argocd` + `monitoring` ns'leri.
- Her iki cluster da **ayrı host-level PG/KC/Vault** instance'ı kullanır (D6, D20)
- OpenFGA K8s içinde (StatefulSet), PostgreSQL host'ta
- Mevcut `decisions/topics/zanzibar-openfga.v1.json` kuralları K8s'te de geçerlidir (ScopeContextFilter order, vb.). **Not 2026-04-17 revize:** Eski "port 8090 yok" kuralı KALDIRILDI — D-003 TRANSFORMED ile uyumlu olarak `permission-service` Service `port: 8090, targetPort: 8084` **doğru** kontrattır. `platform-ssot` compose `8090:8084` mapping ve `auth-service` K8s profile `http://permission-service.../:8090` bu güncel tasarımı yansıtır.
- Cron deploy DISABLED kalır stabilizasyon bitene kadar
- **Prod dış + iç, test sadece iç**: prod `ai.acik.com` dış proxy (`212.115.26.190`, L4 pass-through) üzerinden kurum ağı/VPN'den erişilir; test `testai.acik.com` yalnız intranet (A kaydı `10.9.10.53`, dış proxy'e yazılmaz)
- **Admin UI'lar path altında**: ArgoCD, Grafana, Prometheus dahil her admin endpoint `ai.acik.com/<path>` şemasını kullanır — ayrı subdomain yok (DNS yükü minimum, tek cert yeter)
- **STABİLİTE KAPISI** (2026-04-15 kararı): `testai.acik.com` üzerinde **tüm Dilim'ler tamamen stabil olduktan sonra** `ai.acik.com` prod cutover'a geçilir. Test ortamı, prod'a geçişin **kabul kriteri**dir; smoke + chaos + load test'leri yeşil olmadan prod kurulumu başlamaz. Bu yüzden sıralama: test cluster ayağa → testai.acik.com smoke → tüm Dilim 1+2+3 testai'de stabil → SONRA prod cluster ayağa + cutover.
- **AUTHORITATIVE ENTRYPOINT** (2026-04-17, Codex 4-tur mutabakat): "Yeşil/hazır/stabil" iddiası, **authoritative entrypoint** ve **hop sınıfı** açık değilse **geçersizdir**. Cluster-bypass kanıtı (intra-cluster exec, management port) gerçek kullanıcı yolunu tek başına ispatlamaz. Smoke tuple zorunlu: `(status + Content-Type + body sentinel)` + negatif kontrol (bilinmeyen host → 200 HTML OLMAZ). Sebep: handoff v2 "testai 7/7 smoke 200" iddiası SNI fallback yüzünden yanıltıcıydı (gerçekte compose frontend HTML döndü).
- **UP ≠ FUNCTIONAL ≠ ZANZIBAR-READY** (2026-04-17, D29 karşılığı): Tek kelimelik "green" etiketi **YASAK**. Her servis için 3 seviye ayrı raporlanır: (1) **Up** = Pod Ready + edge gerçek backend + kritik dep TCP açık; (2) **Functional** = Up + kendi ana işlevi doğru dependency ile (örn. report/schema primary PG kullanımı); (3) **Zanzibar-ready** = Functional + permission-service hub yayında + OpenFGA enabled=true + `/authz/me` + `/authz/version` çalışıyor + synthetic allow+deny enforce kanıtlı. "Dilim 1A" (authn slice) ≠ "Dilim 1Z" (authz plane env doğru).
- **IMMUTABLE ARTIFACT — DIGEST+IMAGEID** (2026-04-17, D30 karşılığı): `main-stable` gibi moving tag **tek başına kanıt sayılmaz**. Overlay'lerde CI tarafından yazılan **digest pin** (repo@sha256:...) zorunlu. Pod `imageID` ile GHCR digest eşleşmesi doğrulanır. Sebep: GHCR rebuild K8s'e "yeni image" dedirtmez, IfNotPresent policy eski image ile çalışır.
- **CUTOVER ATOMIC SWITCH** (2026-04-17, D30 karşılığı): Cutover weighted DNS (%10→50→100) **DEĞİL** — tek-seferlik proxy upstream switch (`ai.acik.com` compose → `k3d-prod:30080`) + **72 saat warm rollback** (compose canlı ama trafik dışı). Weighted yalnızca session/cache/side-effect riski ayrı doğrulandığında açılabilir; şu anki tasarımda gereksiz risk.
- **HANDOFF ŞABLONU 5-ALAN** (2026-04-17, D28 karşılığı): Her drift iddiası `(Bağlam / İddia / İspatlar / İspatlamaz / Bilinen boşluk)` formatında yazılır. Tek başına "iddia" yeterli değil. Örnek: `docs/session-handoff-2026-04-17.md`.

---

## 2. Mimari

### 2.1 Fiziksel Topoloji

> **Bu bölüm eski tek-k3s modelini anlatıyordu. Güncel 2-k3d topolojisi için
> Bölüm 2.5 Cluster Topolojisi'ne bakın (D16).**
> Aşağıdaki diyagram REFERANS — fiziksel kaynak dağılımı açıklığı için tutuldu.

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
│   │  (platform-system tek-ns modeli     │                                      │
│   │   eski — güncel: ayrı ns'ler        │                                      │
│   │   Bölüm 2.5; cert-manager YOK,      │                                      │
│   │   TLS host nginx'te termine D8/D18) │                                      │
│   └──────────────────────────────────────┘                                      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Network Akışı

```
Internet/VPN → host nginx (SSL termine) → prod k3d ingress-nginx → 
  /, /api, /auth, /actuator → api-gateway.platform-prod.svc (gateway route)
  /argocd                   → argocd-server.argocd.svc (ayrı Ingress, argocd ns)
  /grafana                  → grafana.monitoring.svc (ayrı Ingress)
  /prometheus               → prometheus.monitoring.svc (ayrı Ingress)

testai.acik.com → test k3d ingress-nginx → api-gateway.platform-test.svc
  (test cluster'da ArgoCD/Grafana YOK, prod cluster uzaktan yönetir)
```

### 2.3 Hostname & TLS (FINAL)

**Hostname şeması — path-based routing:**

```
PROD (platform-prod)                     TEST (platform-test)
ai.acik.com/                             testai.acik.com/
├── /            → frontend (MFE)        ├── /            → frontend
├── /api         → api-gateway           ├── /api         → api-gateway
├── /auth        → api-gateway → auth-svc├── /auth        → api-gateway → auth-svc
├── /argocd      → argocd-server         ├── /argocd      → argocd-server
├── /grafana     → grafana               ├── /grafana     → grafana
└── /prometheus  → prometheus            └── /prometheus  → prometheus
```

- `ai.acik.com`: **mevcut**, prod. Erişim yolu: internet/VPN → dış proxy `212.115.26.190` (L4 pass-through, kurum yönetiminde) → `10.9.10.53:443` (k3s ingress-nginx)
- `testai.acik.com`: **YENİ**, intranet-only. A kaydı `10.9.10.53` — sadece iç Windows AD DNS'e (`acikdc01.acik.local`) eklenir, dış proxy'e yazılmaz.
- Path-based seçiminin gerekçesi: sadece 1 yeni DNS kaydı (testai.acik.com) + tek wildcard cert, admin UI'lar için subdomain yok.

**TLS stratejisi — host-level nginx'te termine (D18):**

| Lokasyon | Dosya | Cert | Kaynak |
|---|---|---|---|
| Host (Compose) | `host-compose/proxy/tls/wildcard-acik-com.{crt,key}` | Sectigo `*.acik.com` + `acik.com` | mevcut PEM (`STAR_acik_com.crt` + `.key`, Nginx bundle) |

- Hem `ai.acik.com` hem `testai.acik.com` aynı host nginx + aynı cert ile servis edilir (wildcard SAN).
- **Cluster içinde TLS Secret YOK** — k3d ingress-nginx HTTP-only dinler (port 30080/31080), host nginx zaten SSL termine ediyor.
- **cert-manager MVP'de kurulmaz**. Renewal stratejisi (D8): manuel Sectigo rotation + script + 60/30/7 gün uyarı + panel erişim doğrulaması.
- **Faz 12 sonrası**: `ai.acik.com` için LE HTTP-01 dry-run. Başarılıysa cert-manager otomasyonu ayrıca kararlandırılır; `testai.acik.com` intranet-only kaldığı sürece bu kapsam dışı.
- Compose nginx (mevcut `platform-web-nginx`) cutover anında durdurulur; host-compose/proxy/ altındaki yeni nginx devralır (aynı 443 port, aynı cert).

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
| Monitoring stack (prom+grafana+loki+tempo+promtail+alertmanager) | ~2.2 GB | **0** | Sadece prod'da. Retention: Prom 10d, Loki 7d, Tempo 48h (MVP, D10) |
| **Cluster overhead (alt toplam)** | **~5.7 GB** | **~2.1 GB** | |
| Backend prod (8 × 384 MB heap) | ~3 GB | - | `-Xmx384m` explicit (D24 — MaxRAMPercentage kaldırıldı) |
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

**CPU bütçesi (D22):**

| Senaryo | CPU kullanımı | Not |
|---|---|---|
| Test kapalı, steady-state | **1.6-2.2 vCPU** | k3d overhead + prod 8 backend idle + Prometheus scrape |
| Test açık, steady-state | **2.0-2.8 vCPU** | + test control plane + test workload idle |
| Spike (prom compaction + loki flush + rollout aynı anda) | **3.4-4.0 vCPU** | Kısa süreli, dar request'li podlarda throttle mümkün |
| Kalıcı saturation (rollout + trafik spike + compaction) | **4.0+ vCPU** | Node CPU pressure → latency artar |

**CPU request/limit örüntü:**
- Backend tipik: `request 150m` / `limit 750m-1000m`
- Ağır 2-3 servis: `request 250-300m` / `limit 1000m`
- api-gateway: `request 250m` / `limit 1000m`
- Kritik podda limit YOK (kontrollü node saturation)
- **`request=limit` YAPILMAZ** (D22) — QoS BestEffort/Burstable avantajı kaybedilir
- JVM için `-XX:ActiveProcessorCount=<limit_cpu>` yoksa GC threadleri host 4 vCPU'ya göre scale eder → throttle artar

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

  # testai.acik.com → test cluster
  server {
    listen 443 ssl http2;
    server_name testai.acik.com;
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
│  │         testai.acik.com → 127.0.0.1:31080    │                                 │
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
│       ├── test/               # platform-test ns — ingress: testai.acik.com (path-based)
│       └── prod/               # platform-prod ns — ingress: ai.acik.com (path-based)
│
├── helm-values/                # 3. parti chart values
│   ├── ingress-nginx/           # values-prod.yaml, values-test.yaml
│   ├── external-secrets/        # (DEFER — Vault auth sonrası)
│   ├── argocd/                  # prod cluster only (multi-cluster yönetir)
│   ├── kube-prometheus-stack/   # prod cluster only
│   ├── loki/                    # prod cluster only
│   ├── promtail/                # DaemonSet, prod cluster
│   └── tempo/                   # prod cluster only
│   # NOT: cert-manager YOK (D8/D18: TLS host nginx'te)
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
- [ ] **DNS ticket**: sysadmin'e `testai.acik.com` A → `10.9.10.53` kaydı için talep (Windows AD DNS)
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
- [x] `helm-values/ingress-nginx/values-test.yaml` — **test**: HTTP-only, hostPort 80/443 (k3d-test 31080:80 map)
- [ ] `helm-values/external-secrets-test/values.yaml` + Vault ClusterSecretStore (test Vault URL)
- [ ] ArgoCD YOK (prod cluster uzaktan yönetecek)
- [ ] Monitoring YOK (prod cluster'dan scrape)

**ArgoCD multi-cluster kayıt:**
- [ ] `argocd cluster add k3d-test --name test-cluster --project platform`

**Kabul kriteri:** 
- İki k3d cluster ayakta, `kubectl get nodes` her ikisinde çalışır
- Host nginx SNI proxy 443'ü alır, `ai.acik.com` prod cluster'a, `testai.acik.com` test cluster'a yönlendirir (dummy backend ile test)
- Prometheus test cluster'ı federate edebiliyor (`up{job="test-federate"}` metriği var)

### Faz 4 — Kustomize Base: Host Service Köprüleri
- [ ] `kustomize/base/host-services/postgres-svc.yaml` (Service + Endpoints, D19 — IP pin `10.9.10.53`, ExternalName kullanılmaz)
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
- [ ] `user-service/` — şablon olarak tam yaz (Deployment, Service, ConfigMap, ~~HPA~~ (D21 — MVP'de yok), PDB, ServiceMonitor, NetworkPolicy, ExternalSecret)
  - Resource: `requests: 256Mi/150m, limits: 512Mi/750m`, JVM `-Xmx384m` (prod) / `-Xmx256m` (test overlay). **`-XX:MaxRAMPercentage` kullanılmaz** (D24)
  - Replica: prod 2 sabit (D21), test 0 default (D17) / 1 açıldığında
- [ ] `auth-service/`, `variant-service/`, `core-data-service/`, `report-service/`, `schema-service/` — copy+edit
- [ ] `permission-service/` — **AKTIF** (2026-04-17 düzeltme): Zanzibar D-003 FINAL "TRANSFORMED — OpenFGA authorization hub (kaldırılmayacak)" kararı gereği. Eski "SKIP" satırı Codex ref CNS-20260411-001 ile çelişiyordu. Yazılacak: Deployment (port 8084 app), Service (`port: 8090, targetPort: 8084`), ConfigMap (DB + Keycloak + OpenFGA env'leri), ExternalSecret (PG + JWK creds), NetworkPolicy (auth/user/variant/core/report caller'lardan ingress), ServiceMonitor. **Prerequisite:** platform-ssot'ta `permission-service/src/main/resources/application-k8s.yml` YOK → Faz 11'de yazılmalı (Eureka kaldır, actuator expose, JVM heap, no-hardcoded-namespace). Auth-service K8s profile hardcoded `platform-prod` namespace'i de `PERMISSION_SERVICE_BASE_URL` env-driven olacak.
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
- [x] `overlays/test/` — platform-test ns
  - image: **digest pin** (D26 + Codex Tur-4; CI sha256 ile günceller)
  - ingress host: `testai.acik.com` (path-based), **TLS host nginx'te D18** (cluster Secret yok)
  - **replica: 0 (scale-to-zero default, D17)** — `test-toggle.sh up` ile 1'e çekilir
  - ResourceQuota: 3Gi/1vCPU (PLAN §2.4)
- [x] `overlays/prod/` — platform-prod ns
  - image: **digest pin** (CI günceller, ArgoCD Image Updater KULLANILMIYOR — D27 YAPMA listesi dışı)
  - ingress host: `ai.acik.com` (path-based), **TLS host nginx'te D18**
  - replica: 2 sabit (D21: HPA yok)
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
  - JVM: `JAVA_TOOL_OPTIONS=-Xmx384m` (prod) / `-Xmx256m` (test). `MaxRAMPercentage` **KULLANILMAZ** (D24 + Codex Tur-4)
- [ ] **Eureka temizliği — DİLİMLİ** (D7, Codex onayı):
  - **Dilim 1 (PoC, D25)**: `api-gateway + auth-service`
    - `auth-service`: `@EnableEurekaClient` kaldır, `@LoadBalanced` client yok
    - `api-gateway`: route `lb://auth-service` → `http://auth-service.platform-prod.svc.cluster.local:8088`
    - Smoke: gateway üzerinden `/auth/actuator/health` 200, e2e Keycloak login
  - **Dilim 2**: `+ user-service` (aynı desen)
  - **Dilim 3+**: kalan backend'ler bağımlılık grafına göre
  - **pom.xml temizliği her dilimde**: `spring-cloud-starter-netflix-eureka-client` dependency kaldırılır
  - `discovery-server` modülü: **tüm filo K8s'e geçtikten sonra** arşivlenir (geçici K8s Eureka YOK — D26)
  - Geçici `EUREKA_ENABLED=false` env var kullanılmaz — annotation ve dependency tamamen temizlenir
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
| ~~Eureka + K8s Service çifte discovery~~ | **PASIF** (D7 revize) | Eureka tamamen kaldırıldı, K8s native DNS kullanılıyor. Geçici Eureka YOK (D26) |
| **CPU throttle** (4 vCPU, spike senaryosu) | Request timeout, GC pause, p95 latency bozulması | D22 politikası: request dar (150m), limit cömert (750-1000m), `request=limit` yok. `-XX:ActiveProcessorCount` JVM için pod limit'ine set. Prometheus scrape 30s→60s gerekirse. Gerçek yük ölçülüp gözden geçirilecek |
| **HPA metrics-server çelişkisi (kapatıldı)** | Autoscaling çalışmazdı | D21: MVP'de HPA YOK, metrics-server kapalı kalır, sabit replica. Gelecekte metrics-server veya Prometheus Adapter kararı ayrıca alınır |
| **Tek host = HA/DR değil** | Hardware failure → toplam outage | D23: RPO/RTO tanımlı, off-host backup + restore prova zorunlu, runbook'lar Faz 12 öncesi hazır. RPO<1h gerekirse mimari değişir |
| **PoC dilim başarısızlığı** | Yanlış mimari varsayımı erken yakalanmazsa manifest çoğaltmasında kaybolmuş olur | D25: kabul kriteri net, yeşil olmadan tam filoya geçilmez. Her dilim ayrı PR + smoke test |
| Host-level PG'ye ağ erişim | Cluster ↔ host network izolasyonu | ExternalName Service + Endpoints ile statik mapping, network policy |
| Vault secret migration | Prod down riski | Önce test namespace'de ESO test et, prod'a son geç |
| MFE React duplicate (mevcut blocker) | White screen | K8s öncesi bu çözülmeli — nginx cache header'ları Faz 7'de revize |
| Decision registry ihlali | permission-service port 8090 yanlışlıkla eklenir | Her PR'da `doctor-zanzibar.sh --quick` koş |
| Cron deploy aktif edilirse erken push | Yarım manifest prod'a gider | DEPLOY_ENABLED=false kalır Faz 15'e kadar |
| **Wildcard cert expiry 2026-10-01** | prod + test TLS kesintisi | **P0 reminder 2026-09-01**: yeni Sectigo cert al ya da cert-manager + LE HTTP-01 otomasyonu aç. Renewal öncesi Secret rotate prosedürü test edilmeli |
| Dış proxy (212.115.26.190) başkasının yönetiminde | `ai.acik.com` üzerinde operasyonel değişiklikler koordinasyon ister | L4 pass-through varsayımı doğrulanmalı (sysadmin'e sor); değilse strateji değişir |
| `testai.acik.com` DNS kaydı sysadmin gecikmesi | Faz 12/13 bloklanır | Faz 1'de erken ticket aç, paralel iş |
| **Eureka kaldırma kod değişikliği** (D7 revize) | Servis-arası çağrılar bozulur | Faz 11'de annotation + pom + route URL'leri sistematik temizle. Önce tek servis (örn. user-service) PoC, smoke yeşil olunca diğerlerine yay |
| **24 GB RAM dar bütçe** | OOM, swap'a düşme, prod degradasyon | Resource quota + LimitRange ZORUNLU. JVM heap explicit `-Xmx`. Retention KISA. Geçiş döneminde compose-prod + K8s-test paralel iken RAM <22 GB tut |
| **Disk %80 dolu, geçiş döneminde %87'ye** | k3s image pull başarısız, cluster instabil | Önce hafif prune; compose-prod stop sonrası `docker system prune -a` ile büyük temizlik. **Disk artırma opsiyonu açık** (sysadmin) |

---

## 6.5 DR / RPO / RTO (FINAL — D23)

**Tek host mimarisinin sınırları:** staging-sw kernel panic/donanım arızası → tüm cluster'lar ve host Compose aynı anda offline. Bu tasarım **HA değil**, operasyonel süreklilik için manuel restore'a güvenir.

**Hedefler:**

| Ortam | RPO | RTO | Kayıp toleransı |
|---|---|---|---|
| **prod** | ≤ 24 saat | ≤ 4 saat | Son gecelik backup'a dön |
| **test** | ≤ 24 saat | ≤ 1 iş günü | İstek halinde restore |

**Backup kapsamı (her öğe için off-host kopya zorunlu):**

| Veri | Kaynak | Yedek | Frekans |
|---|---|---|---|
| PG (prod) | host Compose `/var/lib/postgresql/data` | `pg_dump` + physical snapshot → off-host (S3 veya ayrı makine) | günlük 03:00 (mevcut) |
| PG (test) | host Compose test PG | `pg_dump` → off-host | günlük (ya da on-demand) |
| Vault raft (prod) | host Compose vault state | `vault operator raft snapshot save` → off-host | günlük 03:00 (mevcut) |
| Vault raft (test) | host Compose test vault | raft snapshot → off-host | günlük |
| Keycloak state | PG içinde (KC tabloları) | PG backup içinde | PG ile |
| k3d cluster state (etcd) | PVC'ler | k3d'nin yerleşik backup'ı yok; **etcd snapshot manuel**, ama GitOps'tan **geri kurulum tercih** | on-demand |
| Host Compose state dizinleri | `/home/halil/platform/state/*` | tarball → off-host | günlük |
| Monitoring PVC (prom/loki/tempo) | k3d local-path | **yedek YOK** (retention penceresi kabul) | - |
| Cert ve key (`host-compose/proxy/tls/`) | host | güvenli off-host (Vault KV veya şifreli bucket) | her rotation'da |

**Restore provası (zorunlu):** Her çeyrekte bir kez prod PG dump'ı test'e restore edilmeli. Başarı kriteri: backend `/actuator/health/readiness` 200 döner, smoke test geçer.

**Runbook'lar (docs/runbook/ altında, Faz 12 öncesi hazır):**
- `pg-restore.md` — dump/snapshot'tan restore
- `vault-unseal-restore.md` — raft snapshot + unseal prosedürü
- `cluster-rebuild.md` — k3d cluster'ı GitOps'tan yeniden kurma (<1 saat hedefi)
- `cert-rotation.md` — Sectigo yeni cert indirme + host nginx reload + doğrulama
- `node-maintenance.md` — kernel patch/reboot öncesi downtime planlama + bildirim

**RPO <1 saat veya RTO <1 saat gerekirse:** mevcut mimari yeterli değildir — iki host replication (PG streaming, Vault HA), veya cloud managed DB/KV zorunlu olur. Bu kapsam bu PLAN'ın DIŞINDA.

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
| 2026-04-14 | **D27 Upstream-first prensibi** eklendi: her bileşen kendi native Helm/operator kullanır, custom kod minimum. Custom admission webhook / özel operator / manuel YAML patch YASAK |
| 2026-04-14 | **Codex Tur-3 + Tur-4**: Kurulum inceleme + kısmi itiraz uzlaşısı. 10 bulgu (3 P0, 5 P1, 2 P2). Tur-4'te benim 2 itirazıma Codex gerekçeyle cevap: (1) admin hardening lokalde toleranslı ama repo-seviyesi prod/test overlay'lerde ŞIMDI sertleştirme, (2) image tag `:poc` REDDEDILDI "cutover'da düzeltilir" argümanım tutmadı — prod/test digest pin + ESO-fed imagePullSecret bugün girdi. NP için C+ model (default-deny + 4 allowlist) seçildi. Tüm 10 madde 3 commit'te kapatıldı (73d8600 + bf7f19f + BU COMMIT). PLAN drift 7 satır temizlendi. |
| 2026-04-14 | **Codex istişaresi — 2 turlu, UZLAŞI** (docs/codex-review-2026-04-14.md). Drift temizliği: D1 (tek cluster → 2 k3d), D2 (5 ns tek cluster → cluster-başına ns), D16 ("Docker-in-Docker" → Docker container), §2.3 TLS (cluster Secret → host nginx), Faz 4 (ExternalName → Service+Endpoints), §6 Risk (Eureka K8s-içi single-replica → PASIF). D7 revize: dilimli Eureka kaldırma. D8 revize: 2 aşamalı cert stratejisi (manuel + Faz 12 HTTP-01 dry-run). D10: retention 14d→10d/14d→7d/3d→48h. **6 yeni karar**: D21 HPA (MVP'de yok), D22 CPU bütçesi, D23 DR/RPO/RTO, D24 JVM `-Xmx` explicit (MaxRAMPercentage kaldırıldı), D25 PoC dilim (`api-gateway + auth-service` → `user-service`), D26 YAPMA listesi. Yeni §6.5 DR/RPO/RTO bölümü. §2.4 CPU bütçesi tablosu. 4 yeni risk (CPU throttle, HPA çelişkisi pasif, tek-host DR sınırı, PoC dilim başarısızlığı) |
| 2026-04-15 | **Hostname rename + STABİLİTE KAPISI**: `test.acik.com` → `testai.acik.com` (5 dosya: PLAN.md, ingress.yaml, overlay test, host nginx.conf, README). Sectigo wildcard `*.acik.com` kapsıyor → cert değişimi YOK. Yeni HARD RULE: testai.acik.com'da Dilim 1+2+3 stabil olmadan ai.acik.com prod cutover BAŞLAMAZ. Sıralama: test cluster ayağa → testai smoke → tüm dilim'ler yeşil → prod cluster + cutover. |
| 2026-04-15 | **GitHub remote AKTİF** (D12 revize). `git@github.com:Halildeu/platform-k8s-gitops.git` private repo. Lokal SSH key + sunucu için ayrı read-only deploy key (port 443 alternatif, kurum firewall 22 kapalı). install-on-staging-sw.sh: rsync → git clone/pull (6/14 adımı güncellendi, SSH config otomatik ekleniyor). ArgoCD Application CR'ları bu URL'i source olarak alacak (Faz 10). |
| 2026-04-15 | **Dilim 1+2+3 CANLI (testai.acik.com)**. Ana repo (autonomous-orchestrator `k8s-migration-dilim1` branch): auth-service + api-gateway + user/variant/core-data/report/schema-service için Eureka dep kaldırıldı + `application-k8s.yml` profile yazıldı + non-root Dockerfile. 7 image local build + staging-sw'ye scp + k3d import. Gitops: image override (`k8s-poc` tag, imagePullPolicy: Never), quota genişletildi (4/8 vCPU, 8/16 GiB), NP/NP, overlay scale patches. Tam smoke: **testai.acik.com 8/8 path HTTP 200** (/testai-healthz, /actuator, /auth, /users, /variants, /core, /reports, /schemas). Mevcut `ai.acik.com` compose DOKUNULMADI (200 dönüyor). OpenFGA migrate Completed, frontend nginx 1/1 Running (MFE artifact boş — Dilim 4). Bazı backend pod'lar hâlâ CrashLoopBackOff (Spring DB resolve env convention — ana repo main-stable rebuild gerekli); ancak zincir çalışıyor (gateway yanıt veriyor, ingress route'lar tam). **Bu repo işi BİTTİ** — tam sistem sonraki adımda `main-stable` tag güncellenince 5-10 dk içinde temiz deploy edilir. |
| 2026-04-15 | **GERÇEK TAM BİTİŞ** — Codex Tur-7+8 false-positive 200'lerin nginx'te testai server block silinmesinden kaynaklandığını keşfetti. Pod crash ana nedeni: **ARM64 (M4 Pro) image AMD64 staging-sw'de exec format error**. AMD64 cross-build → tarball → scp → docker load → k3d import → rollout. Ayrıca kustomize patch'ler SPRING_DATASOURCE_URL pod env'e erişemedi (Spring Boot property resolution sırası) → `kubectl set env` ile explicit env ekleme ile çözüldü. Son smoke: **6/6 backend path → 401 "JWT token zorunludur" JSON** (gerçek Spring Security cevabı, HTML değil). Zincir: ingress → gateway:8080 → K8s DNS → `<svc>.platform-test.svc.cluster.local:<port>` → Spring Security 401. ai.acik.com (compose) DOKUNULMADI → 200. PoC HEDEFİ TAMAMEN BAŞARILDI. Kalan polish: OpenFGA migrate idempotency, Dockerfile `JAVA_TOOL_OPTIONS` env adı (JAVA_OPTS ENTRYPOINT'te expand olmuyor), testai nginx block'un compose restart'a dayanıklılığı (docker-compose.yml networks block). |
| 2026-04-17 | **Drift teşhis + 4-tur Codex istişare re-baseline** (thread `019d9a75-4299-7313-85bb-003a7de680eb`). **Eklenen:** D28 (handoff 5-alan zorunlu), D29 (Up≠Functional≠Zanzibar-ready 3 seviye raporlama, tek "green" yasak), D30 (cutover atomic switch + 72h warm rollback, digest pin zorunlu, weighted YASAK), D31 (primary DB PostgreSQL, MSSQL secondary/opsiyonel external). **Revize:** "port 8090 yok" HARD RULE KALDIRILDI — D-003 TRANSFORMED uyumlu `permission-service` Service 8090→8084 DOĞRU kontrat. **Düzeltme:** Faz 6 `permission-service SKIP` → **AKTIF** (Zanzibar authz hub, CNS-20260411-001). **Yeni HARD RULES:** Authoritative Entrypoint (smoke tuple + negatif kontrol), Up≠Zanzibar-ready ayrımı, Immutable Artifact (digest pin + imageID), Cutover Atomic Switch, Handoff 5-alan. **Drift haritası (bugünkü gerçek):** Faz 3/4/5/6 REGRESSION (Calico BIRD down + Typha watch cache bozuk; 5 pod crash 20h; testai edge SNI fallback compose frontend'e; users_db+variants_db YOK; OpenFGA enabled=false default; ghcr-pull secret eksik), Faz 10 BAŞLAMADI (ArgoCD yok), Faz 13 REGRESSION (1-hafta gözlem başlamamış), Faz 15 BAŞLAMADI. **Repo ayrımı netleşti:** `platform-k8s-gitops` (bu repo, manifest) + `platform-ssot` (Java backend + MFE, `/Users/halilkocoglu/Documents/dev/`) + `autonomous-orchestrator` (Python control-plane, governance). Handoff v3 `docs/session-handoff-2026-04-17.md` ilk 5-alan örneği. |
| 2026-04-17 | **Seviye 0 canlı recovery TAMAMLANDI** (Codex thread devamı). **Fix uygulandı:** `calico-typha scale=0` + `calico-node` recycle → BIRD up, Tigera DEGRADED=**False**. `users_db`+`variants_db` zaten mevcut (önceki drift). 5 crash pod rollout restart → **9/9 Pod Running + Ready**, tüm Endpoints doldu. **Intra-cluster Up kanıt:** labeled busybox nc 3/3 OPEN (postgres.svc:5432, keycloak.svc:8080, raw 172.19.0.4:5432), management:8081/actuator/health auth/user/variant/core → **4/4 200**. **testai edge fix:** `/home/halil/platform/web/nginx/default.conf` host dosyasına `testai.acik.com` server_block + `/testai-healthz` sentinel + proxy → `127.0.0.1:9080` (k3d-test serverlb). Config mount kalıcı (compose restart dayanıklı). **Gerçek edge smoke:** `/testai-healthz`→200 "testai-healthz" body, `/auth/actuator/health`→ K8s gateway JSON "JWT token zorunludur", `/reports`+`/schemas`→ 401 Spring Security. **compose fallback YOK** (drift #1 kapatıldı). `ai.acik.com` dokunulmadı (200+401 aynen). **Warning kalıntıları** (Seviye 1/2'ye ertelendi): Content-Type text/html vs application/json drift (gateway response header), auth/user/variant/core `/actuator/health` 200 vs report/schema 401 tutarsızlığı, calico-typha Tigera operator auto-recreate (Installation CR override — Seviye 2.5'e), ghcr-pull secret restore, Promtail sysctl fix, dev repo permission-service application-k8s.yml yok, OpenFGA enabled=false default, digest pin yok. **Seviye 0 kapatıldı**; Seviye 1 Zanzibar runtime aktivasyonu sıradaki iş (permission-service manifest + OpenFGA enabled + auth-service hardcoded namespace temizliği). |

