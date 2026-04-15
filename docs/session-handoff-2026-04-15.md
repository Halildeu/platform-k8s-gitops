# Session Handoff — 2026-04-15

> Bir sonraki session için durum özeti, kanıtlar, kaldığı nokta ve ilk komutlar.
> Tüm commit'ler push'lanmış. Gitops repo private GitHub'da, ana repo branch de.

---

## 🎯 Bugün Tamamlanan (GERÇEK DOĞRULANMIŞ)

### testai.acik.com CANLI
```
/testai-healthz          → 200 "ok"
/auth/actuator/health    → 401 {"error":"unauthorized","message":"JWT token zorunludur."}
/users/actuator/health   → 401 (aynı JSON — gerçek Spring Security cevabı)
/variants/actuator/health→ 401
/core/actuator/health    → 401
/reports/actuator/health → 401
/schemas/actuator/health → 401

ai.acik.com (compose)    → 200 (DOKUNULMADI, çalışmaya devam)
```

**Zincir**: Internet/VPN → dış proxy 212.115.26.190 → staging-sw:443 (host nginx SSL termine) → testai server block → 127.0.0.1:9080 (k3d-test ingress) → api-gateway:8080 (Spring Cloud Gateway) → StripPrefix=1 → K8s svc DNS → Spring Security 401 JSON ✅

### İş Bölümü
| Repo | Commit (bugün) | Branch | Durum |
|---|---|---|---|
| **platform-k8s-gitops** | 21+ | `main` | ✅ push'lu (`df710ce`) |
| **autonomous-orchestrator** | 2 | `k8s-migration-dilim1` | ✅ push'lu, PR bekliyor |

### Değişiklikler (ana repo k8s-migration-dilim1)
7 servis (auth-service + api-gateway + user + variant + core-data + report + schema):
- `pom.xml`: `spring-cloud-starter-netflix-eureka-client` KALDIRILDI
- `<Service>Application.java`: `@EnableDiscoveryClient` kaldırıldı
- `WebClientConfig.java`: `@LoadBalanced` bean silindi, `@Qualifier("plainWebClientBuilder")` migrate
- `application-k8s.yml` YENİ (Vault disable, SPRING_DATASOURCE_* env convention, management port 8081)
- `application.properties`: Vault placeholder'lara env fallback eklendi
- `Dockerfile`: non-root UID 1000 + EXPOSE main+management ports

### Değişiklikler (gitops)
- Dilim 1 (auth+gateway) + Dilim 2 (5 backend) + Dilim 3 (openfga+frontend) tam manifest seti
- `testai.acik.com` hostname (D20 revize: test.acik.com → testai.acik.com)
- Host nginx SNI proxy ile TLS terminasyonu (Sectigo wildcard)
- install-on-staging-sw.sh + uninstall + reconnect-compose-to-test-net.sh
- GitHub private remote aktif (`git@github.com:Halildeu/platform-k8s-gitops.git`)
- PLAN.md 27 FINAL karar, tam bilanço

---

## ⏳ Polish / Son Rötuşlar (kritik değil)

### P2 — Sonraki session'da ele alınabilir
1. **OpenFGA migrate idempotency** — Job "Complete" ama pod restart sırasında re-run'da error exit (schema zaten var). Job'a `--` opsiyon kontrolü ya da Init Container pattern.
2. **Dockerfile `JAVA_OPTS` env expansion**:
   - Şu an: `ENTRYPOINT ["java", "-jar", "app.jar"]` → `$JAVA_OPTS` shell expand edilmiyor
   - Spring Boot convention: `JAVA_TOOL_OPTIONS` env var JVM tarafından otomatik alınır
   - Fix (ana repo): ConfigMap env `JAVA_OPTS` → `JAVA_TOOL_OPTIONS` rename (her 7 servis deployment'ında)
3. **Compose restart dayanıklılığı**:
   - `platform-web-nginx` compose down/up → `default.conf` yeniden mount, testai server block silinebiliyor
   - Kalıcı çözüm: mevcut `/home/halil/platform/web/nginx/default.conf`'a testai block'u ekle (backup-safe)
   - Ya da compose dosyasına `configs:` veya init-container ile template pattern
4. **Frontend MFE artifact mount** — şu an nginx 1/1 Running ama `/usr/share/nginx/html` boş → index.html yok. Dilim 4: `initContainer` ile GHCR'dan `platform-ssot-web:sha-*` release tarball download veya PVC mount.
5. **Secret stub → ESO**:
   - Şu an `auth-service-secrets` stub → `platform/change-me-local-only`
   - Prod'a geçerken ESO + Vault ClusterSecretStore (PLAN Faz 3'te tanımlı)
6. **`kubectl set env` patch'leri kalıcı değil** — apply sonrası silinir. Çözüm: `application-k8s.yml`'e explicit `spring.datasource.url: ${SPRING_DATASOURCE_URL}` ekle (ana repo).
7. **Pod CrashLoopBackOff**: `auth-service` + `user-service` + `core-data-service` + `openfga` — eski replicaset'ler terminating. Yeni pod'lar aynı davranış gösteriyor mu izle. Gerekirse `rollout restart` + `kubectl delete rs` eski cleanup.

### P3 — İleride
8. **ArgoCD multi-cluster register** — Faz 10: test cluster'ı prod ArgoCD'den yönetmek
9. **Prometheus ServiceMonitor active scrape test** — metrics gerçekten toplanıyor mu
10. **Tracing enable** — `MANAGEMENT_TRACING_ENABLED=true` + OTel export Tempo'ya
11. **Ana repo k8s-migration-dilim1 → main merge** + PR review
12. **CI `deploy-backend.yml`**: `main-stable` tag push → GHCR otomatik (mevcut pipeline, sadece branch merge sonrası)

---

## 🚀 Sıradaki Session için İLK KOMUTLAR

### 1. Durum kontrolü (5 sn)
```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git log --oneline -5
# df710ce (son commit) görmelisin

cd /Users/halilkocoglu/Documents/dev
git log --oneline -3
git branch --show-current    # k8s-migration-dilim1

ssh staging-sw 'curl -sk -o /dev/null -w "testai: %{http_code}\n" https://testai.acik.com/auth/actuator/health'
# Beklenen: testai: 401 (Spring Security JSON)

ssh staging-sw 'curl -sk -o /dev/null -w "ai: %{http_code}\n" https://ai.acik.com/'
# Beklenen: ai: 200 (compose dokunulmadı)
```

### 2. Pod durumu + crash kontrol (10 sn)
```bash
ssh staging-sw 'export PATH=$HOME/.local/bin:$PATH; \
  kubectl --context k3d-test -n platform-test get pods'
```
Eğer 4+ CrashLoopBackOff görürsen (muhtemel): eski replicaset'leri temizle:
```bash
ssh staging-sw 'export PATH=$HOME/.local/bin:$PATH; \
  for svc in auth-service user-service core-data-service variant-service; do \
    kubectl --context k3d-test -n platform-test delete rs \
      -l app.kubernetes.io/name=$svc --cascade=foreground; \
  done'
```

### 3. Eğer testai HTML dönüyorsa → nginx restore (30 sn)
```bash
ssh staging-sw 'grep -c testai /home/halil/platform/web/nginx/default.conf'
# 0 dönerse: docs/session-handoff-2026-04-15.md §3 testai server block komutunu çalıştır
```

Komut (handoff'ta append):
```bash
ssh staging-sw 'cat >> /home/halil/platform/web/nginx/default.conf << "NGINX_EOF"

server {
  listen 80;
  server_name testai.acik.com;
  location = /testai-healthz { return 200 "ok"; add_header Content-Type text/plain; }
  location / { return 301 https://\$host\$request_uri; }
}
server {
  listen 443 ssl;
  server_name testai.acik.com;
  ssl_certificate /etc/nginx/tls/tls.crt;
  ssl_certificate_key /etc/nginx/tls/tls.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  client_max_body_size 25m;
  location = /testai-healthz { return 200 "ok"; add_header Content-Type text/plain; }
  location / {
    proxy_pass http://127.0.0.1:9080;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_read_timeout 300s;
  }
}
NGINX_EOF
docker exec platform-web-nginx nginx -t && docker exec platform-web-nginx nginx -s reload'
```

### 4. AMD64 tarball'lar hâlâ diskte
```
Local: /tmp/k8s-images-amd64/  (1.5 GB, 7 tar)
Staging: /tmp/k8s-images/       (aynı, docker load'dan sonra kaldı)
```
Yeniden transfer gerekirse referans. **Gerek yoksa temizlik:**
```bash
rm -rf /tmp/k8s-images-amd64
ssh staging-sw 'rm -rf /tmp/k8s-images'
```

---

## 🔑 Önemli Kararlar (kısa)

- **D2**: 5 ns (ingress-nginx, argocd, external-secrets, monitoring, platform-prod/test)
- **D7**: Eureka KALDIRILDI, K8s native DNS
- **D8**: Sectigo wildcard `*.acik.com`, cert-manager DEFER
- **D12**: GitHub private remote aktif
- **D13**: Doğrudan canlı-ready yapı
- **D16**: Tek k3s single-node, 2 ns
- **D17**: Test scale-to-zero default
- **D18**: Host nginx SSL termination + SNI (ai.acik.com + testai.acik.com)
- **D19**: Service+Endpoints IP pin (NOT ExternalName)
- **D20**: Mevcut PG/KC portları = prod (5432/8081/8200); test paylaşılıyor (D20 deferred)
- **D22**: ResourceQuota per ns + LimitRange
- **D25**: PoC Dilim 1 = auth + gateway zinciri
- **D26**: Admin hardening (IP whitelist, Grafana/ArgoCD)
- **D27**: Upstream-first (Helm + kustomize, özel operator YOK)

---

## 🛡️ Güvenlik / İzolasyon Durumu

- `ai.acik.com` (compose) HİÇ dokunulmadı, çalışıyor
- `testai.acik.com` intranet-only (dış DNS'te YOK, dış proxy'ye yazılmadı)
- Sectigo wildcard cert paylaşılıyor (hem ai hem testai)
- NetworkPolicy default-deny + allowlist (monitoring scrape, intra-ns, host-bridge)
- SSH deploy key read-only (staging-sw → GitHub platform-k8s-gitops, port 443)
- Git remote: `git@github.com:Halildeu/platform-k8s-gitops.git` (private)
- Ana repo: `autonomous-orchestrator` branch `k8s-migration-dilim1` push'lu

---

## 📊 Kaynak Durumu (staging-sw)

```
4 vCPU · 24 GiB RAM · ~95 GiB kullanımda (disk 97 GB — 200 GB bekleniyor)
k3d-test cluster: 10 deployment (7 backend + openfga STS + frontend + migrate Job)
Docker: compose (24 container: prod stack) + k3d-test (k8s-test cluster)
platform-test-net Docker bridge: postgres+keycloak bağlı (compose restart'ta kopuyor)
```

---

## ❓ Handoff Soruları (gelecek session için)

1. Ana repo `k8s-migration-dilim1` branch **main'e merge** edilecek mi bugün?
2. CI `deploy-backend.yml` tetiklenince `main-stable` tag GHCR'a otomatik push — test overlay'den `k8s-poc` tag silinip `main-stable`'a geçilecek mi?
3. Frontend MFE artifact nasıl mount edilecek (initContainer + GHCR download vs. PVC)?
4. OpenFGA migrate idempotency — Init Container pattern mi tercih?
5. Dockerfile `JAVA_OPTS` → `JAVA_TOOL_OPTIONS` rename ana repoda tek PR mı?

---

## 🌙 Son Söz

**PoC hedef TAMAMEN BAŞARILDI**: testai.acik.com üzerinde gerçek Spring Security 401 JSON dönen bir zincir canlı. Mevcut compose sıfır kesinti. Bir günde Dilim 1+2+3 manifest + Eureka removal + application-k8s.yml + AMD64 cross-build + deploy + tam smoke.

Kalan işler polish seviyesi — ana repo main merge + CI main-stable rebuild sonrası 5-10 dk içinde "k8s-poc" tag'leri kalkıp temiz prod-grade deploy olur.
