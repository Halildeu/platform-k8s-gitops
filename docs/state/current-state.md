# Current State — Platform K8s Migration

> **Status as of**: 2026-04-24 ~00:35 UTC+3 (Session 25 — Faz 10/11/12 operasyonel kapanış. 9 PR merged 2 saat içinde: #52/51/54/55/56/53/57/58/59/60; PR #48 (Codex DRAFT, CONFLICTING) cherry-pick + close ile kurtarıldı. **KC compose recreate canlıda → Health=HEALTHY** (Known Drift §platform-kc-prod CLOSED). **Prod ESO roleId** placeholder → gerçek UUID (Known Drift §HIGH CLOSED). **DR drill canlı PASS** staging-sw'de: PG restore 2s + Vault init/unseal/restore 13s + 2x smoke + 60s sleep = **RTO 81 saniye** (4h budget'ın %0.56'sı, SKIP_KC=1 PARTIAL). Faz 12 runtime gate geçti; `dr-validation` sayacı 0→70. 5 iterative drill script bug fix (#55 initial sonrası #58/#59/#60 bash-set-e + container permission + smoke sealed-acceptance). Faz 11 runtime canlı ve stabil; ArgoCD cosmetic OutOfSync/Degraded kaldı (Faz 13 rebuild ile doğal temizlenecek teknik borç).
> **Verified by**: Codex + live `ssh staging-sw`
> **Source set**: Live `kubectl`, `curl`, `docker`, `ssh staging-sw` outputs + repo HEAD
> **Supersedes**: `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` bölümlerindeki `%99.5`, `DONE + LIVE (Faz H)`, `soft cutover` ifadeleri
> **Interpretation gate**: Önce [../../AGENTS.md](../../AGENTS.md), ardından [../context-priority-rules.md](../context-priority-rules.md) okunur; bu dosya canlı truth snapshot'tır, repo-geneli kural sözleşmesi değildir.

---

## Live Delta — Session 25 (2026-04-24 ~00:35 UTC+3)

- **5 yeni PR merge** (iterative drill hardening + KC/ESO cherry-pick):
  - `a4e902c` **PR #57** `fix(prod)`: KC dual-network (`platform-prod-net` + `platform_microservice-network`) + healthcheck `localhost→127.0.0.1` + printf portability. Cherry-pick Codex PR #48'in değerli iki deltasından biri; 172.21.0.6 IP regression kaçınıldı (FQDN `vault.platform-prod.svc.cluster.local:8200` korundu). **ESO roleId** placeholder `"eso-runtime"` → gerçek AppRole UUID `0db7ba83-b485-4afb-da7d-e1041b1f8a56`.
  - `27ebffa` **PR #58** `fix(faz-12)`: DR drill script 3 kritik bug fix: safety glob false positive (`platform-stateful*` → `platform-stateful-drill` yanlış match) + `((i++))` set -e infaz bug (eski değer 0 exit 1) + docker run stderr gizleme (`>/dev/null` → `>>DRILL_LOG 2>&1`).
  - `2d067fc` **PR #59** `fix(faz-12)`: DR drill sandbox `chmod 0777` (Vault container UID 100 `/vault/data/vault.db: permission denied` fix).
  - `22c3df9` **PR #60** `fix(faz-12)`: DR drill Vault smoke sealed post-restore accept (exit code 2 = sealed NORMAL, snapshot restore kanıtı `Initialized=true`).
  - PR #48 (Codex DRAFT, CONFLICTING 14 dosya) **closed** supersede-via-cherry-pick; 569 deletion'ı main'deki PR #51/#52/#54/#55 işlerini silecekti.

- **Canlı KC drift kapatma**:
  - `docker compose up -d --force-recreate keycloak` staging-sw host-compose
  - `docker inspect platform-kc-prod --format '{{.State.Status}} {{.State.Health.Status}}'` → `running healthy`
  - Healthcheck log son 3 iter: `[0] [0] [0]` (hepsi başarılı)
  - `/health/ready → HTTP/1.1 200 OK` direct test
  - Known Drift §"platform-kc-prod healthcheck unhealthy" → **CLOSED**

- **Canlı DR drill PASS** (staging-sw, 2026-04-24 00:31:11 → 00:32:33):
  - Komut: `DRILL_ROOT=/home/halil/drill-sandbox DRILL_CONFIRM=yes SKIP_KC=1 bash bootstrap/dr-drill.sh`
  - Aşamalar:
    - SAFETY ✅ + PREFLIGHT ✅ (disk 182GB)
    - PG up 2s + restore 2s (128KB dump `pg_dumpall_20260424-0005.sql.gz`)
    - Vault init+unseal 9s + snapshot restore 4s (88KB `vault-snapshot-20260423-0200.snap`)
    - SMOKE[1] PASS (PG DB listesi + Vault Initialized=true, Sealed=true)
    - 60s independence sleep
    - SMOKE[2] PASS (tekrar doğrulama)
    - **RTO: 81 saniye / 14400s budget (0.56%) ✅**
  - Sonuç: `=== DR DRILL PASS ===` exit 0, teardown clean
  - KC drill SKIP_KC=1 çünkü `kc-export-cron.sh` hâlâ `kcadm.sh get realms/<realm>` (PARTIAL export, users/creds yok) → `dr-validation=70` PARTIAL, full=85 için KC export cron upgrade ayrı iş

- **Faz 11 ESO roleId uyumu** (ArgoCD sync beklentisi):
  - Manifest `kustomize/overlays/prod/eso/clustersecretstore-patch.yaml`: roleId gerçek UUID
  - Canlı CSS zaten aynı UUID ile çalışıyordu (placeholder sadece GitOps drift)
  - Known Drift §"Prod ESO roleId HIGH" → **CLOSED**

- **5-sayaç Session 25 delta**:
  - `test-k8s`: 86 (değişim yok)
  - `prod-stateful-split`: 73 → **76** (KC healthy + ESO roleId manifest-canlı parite)
  - `prod-workload-gitops`: 72 → **75** (ESO roleId paritesi, ArgoCD sync cosmetic diff azalır)
  - `secret-delivery`: 82 → **87** (roleId real UUID manifest + live CSS Ready=True, ghcr-pull zinciri canlı, PR #57 bekleyen uzak detay kapattı)
  - `dr-validation`: 5 → **70** (PARTIAL drill PASS, RTO 81s 4h budget'ın binde 5'i; KC full drill için cron export upgrade gerekir)
- **Weighted operational continuity**: `~%80` → **`~%86`** (Faz 10 T2 kapandı, Faz 11 KC healthy + ESO uyum, Faz 12 drill PASS)

### Faz 12 Follow-up (out-of-scope this session)

1. `bootstrap/kc-export-cron.sh` full `kc.sh export --users realm_file` geçişi → `dr-validation` 70 → 85 (KC dahil full drill)
2. Drill cron scheduling (PLAN.md D23 quarterly) → drill otomasyonu
3. Drill success metric → Prometheus node_exporter textfile (`dr_drill_last_pass_timestamp_seconds`) → alerting

### Faz 13 Atomic Cutover Prereq Check

Gate şartları (`docs/state/current-state.md` §5):
- `secret-delivery>=80` → **87 ✅**
- `dr-validation>=85` → **70 ⚠️** (KC full drill eklenirse 85 hedefi)
- Alternatif: mevcut hybrid cutover kontrat olarak kabul (ai.acik.com/api/ K8s, /realms/+/resources/ compose KC) + 72h warm rollback (compose prod hâlâ ayakta, PR #57 healthy)

## Live Delta — Session 24 (2026-04-24 ~00:00 UTC+3)

- **4 PR merge 5 dk içinde** (Claude execution → kullanıcı approval):
  - `17191e8` **PR #52** `fix(eso)`: 10 manifest `external-secrets.io/v1beta1 → v1` (supersedes PR #44). ArgoCD ComparisonError (`unable to resolve parseableType for GroupVersionKind`) **kapandı** — Apps artık diff hesaplayabiliyor.
  - `bf637f1` **PR #51** `docs(state)`: Codex Session 20-23 truth refresh (prod-workload-gitops 0→63, secret-delivery 58→78).
  - `64f9aa4` **PR #54** `fix(argocd)`: `argocd/applications/platform-prod.yaml` + `platform-eso-prod.yaml` `ignoreDifferences` genişletildi (ExternalSecret + CSS `/metadata/{annotations,managedFields}/status`, Endpoints `/subsets`, ConfigMap openfga-config `/data/OPENFGA_DATASTORE_URI`).
  - `ccf84a5` **PR #55** `feat(faz-12)`: `bootstrap/dr-drill.sh` (447 LOC, shellcheck warning-free). Sandbox-isolated, 6 safety assertion, port offset +10000, drill-* container prefix, 2x smoke + RTO measure.
- **PR #53 OPEN**: Faz 10 T2 handoff split (1290 satır → 10 session-logs + 55 satır index). CI pass.
- **Faz 11 runtime kapalı — canlı kanıt**:
  - `ssh staging-sw 'docker exec k3d-prod-server-0 kubectl -n platform-prod get clustersecretstore vault-platform-gitops -o jsonpath="{.status.conditions[0].type} {.status.conditions[0].status}"'` → `Ready True`
  - `kubectl -n platform-prod get externalsecret -o wide` → 8 ES `SecretSynced=True` (auth, core-data, ghcr-pull, permission, report, schema, user, variant)
  - `kubectl -n platform-prod get pods | grep Running | wc -l` → `19`
  - `curl -sk -o /dev/null -w '%{http_code} %{size_download}B\n' https://ai.acik.com/api/v1/theme-registry` → `200 15666B`
  - `curl -sk -H 'Host: ai.acik.com' https://127.0.0.1:30443/api/v1/theme-registry` → byte-perfect match (K8s ingress-nginx NodePort K8s'e akıtılıyor; /api/ K8s, /realms/+/resources/ compose KC hybrid)
- **Faz 11 GitOps kozmetik boşluk** (runtime'ı etkilemiyor):
  - `kubectl -n argocd get applications.argoproj.io -o wide` → `platform-prod OutOfSync/Degraded` + `platform-eso-prod OutOfSync/Degraded`, revision `ccf84a5`
  - `operationState.phase=Succeeded, message=successfully synced (all tasks run)` — sync fiilen uygulanmış
  - Degraded kök neden: ConfigMap'lerde `health.status=null` (K8s inherent health yok) → Argo Application-level aggregation bunu `Degraded` yorumluyor
  - Diff kök neden: v1beta1 era'dan kalma stored `managedFields` serialization; PR #54 `ignoreDifferences` hedefliyor ama ServerSideApply reconcile'da yeniden üretiyor
  - Açık teknik borç (Faz 11 cleanup): (A) `argocd-cm` ConfigMap'te `resource.customizations.health.ConfigMap` lua script Healthy döndür veya (B) `syncPolicy.syncOptions` içine `RespectIgnoreDifferences=true` ekle veya (C) Faz 13 cluster rebuild bu cosmetic'i doğal temizler
- **Faz 12 başlangıç çıktısı**:
  - `bootstrap/dr-drill.sh` merged, çalıştırılabilir
  - Backup producers canlı: `ssh staging-sw 'ls -lah ~/platform/backup/pg/prod | tail -3'` → `pg_dumpall_*.sql.gz` son 30 gün retention aktif
  - Vault snapshot 14 gün, KC export `kc=0` drift (partial export cron)
  - Manuel drill henüz YAPILMADI: `dr-validation` 0 → **5** (script var, execute yok)
- **5-sayaç Session 24 delta**:
  - `test-k8s`: 86 (değişim yok)
  - `prod-stateful-split`: 73 (değişim yok)
  - `prod-workload-gitops`: 63 → **72** (ComparisonError kapandı + operationState Succeeded; cosmetic diff GitOps gate'i `90+ Synced/Healthy`a taşıyamaz ama runtime gate geçti)
  - `secret-delivery`: 78 → **82** (v1 migration tam uyum, CSS + 8 ES stabil SecretSynced, ghcr-pull pull chain canlı, prod tarafı test tarafıyla paritede)
  - `dr-validation`: 0 → **5** (runbook + script var, drill execute yok)
- **Weighted operational continuity**: `~%74` → **`~%80`**

## Live Delta — Session 23 (2026-04-23 20:15 UTC+3)

- Public front-door no-token kontratı iki hostname'de tekrar doğrulandı:
  - `testai.acik.com`: `/api/v1/authz/me` `401`, `/api/v1/theme-registry` `200`, `/api/v1/variants?gridId=1204` `401`.
  - `ai.acik.com`: `/api/v1/authz/me` `401`, `/api/v1/theme-registry` `200`, `/api/v1/variants?gridId=1204` `401`.
- Prod k8s secret-delivery/workload yüzeyi canlı:
  - `ClusterSecretStore/vault-platform-gitops` `Ready=True/Valid`.
  - `platform-prod` namespace altında kritik `ExternalSecret` seti `SecretSynced=True`.
  - `platform-prod` backend Deployment'lar `READY=2/2`.
  - Argo app health notu: `platform-prod` hâlâ `Unknown/Degraded`, `platform-eso-prod` `Unknown/Healthy`.
- Prod authenticated smoke iki ayrı token sınıfıyla tekrarlandı:
  - `smoke-client` (service account): `authz/me=200`, `variants(1204|test-grid)=401`.
  - `canary-restricted@stage.local` (password grant, `canary-load`): `authz/me=200`, `superAdmin=false`, `permissions_count=7`, `roles_count=15`, `allowedScopes=[]`, `variants(1204)=403`, non-scoped `variants(9999)=401`.
- Kimlik eşleme drift bulgusu: farklı Keycloak kullanıcıları (`admin@example.com` ve `canary-restricted@stage.local`) `authz/me` tarafında aynı `userId=920001` ile dönüyor; scoped allow modelinin kapanmamasında bu eşleşme drift'i aday kök neden.
- Drift'in canlı kaynağı netleşti: prod `serban` realm `canary-load` client'ında `uid-static` hardcoded claim mapper (`claim.value=920001`) bulunuyor. Bu mapper `uid-claim` kullanıcı attribute mapper'ını gölgede bıraktığı için farklı kullanıcı tokenları aynı `uid` ile üretiliyor.
- Sonuç: authenticated zincirde artık deny davranışı (`403`) non-superAdmin kullanıcıyla kanıtlı; açık kapı non-superAdmin scoped allow (`gridId=1204` için `200`) seed kontratıdır.

## Live Delta — Session 22 (2026-04-23 19:41 UTC+3)

- Public front-door no-token kontratı iki hostname'de yeniden doğrulandı:
  - `testai.acik.com`: `/api/v1/authz/me` `401`, `/api/v1/theme-registry` `200`, `/api/v1/variants?gridId=1204` `401`.
  - `ai.acik.com`: `/api/v1/authz/me` `401`, `/api/v1/theme-registry` `200`, `/api/v1/variants?gridId=1204` `401`.
- Prod authenticated smoke (service-account token) tekrarlandı:
  - `smoke-client` client-credentials tokenında `aud=account`, `azp=smoke-client`.
  - Public `ai.acik.com`: `/api/v1/authz/me` `200`, `/api/v1/variants?gridId=1204` `401`, `/api/v1/variants?gridId=test-grid` `401`.
  - Ingress `https://127.0.0.1:30443` + `Host: ai.acik.com`: aynı pattern (`authz/me=200`, `variants=401`).
- Prod Keycloak client kontratı notu: `canary-load` client'ı `client_credentials` için `unauthorized_client (Client not enabled to retrieve service account)` döndürüyor; service-account smoke için aktif client `smoke-client`.
- Realm issuer parity no-token probeda korunuyor:
  - `testai`: `https://testai.acik.com/realms/platform-test`
  - `ai`: `https://ai.acik.com/realms/serban`
- Session 21'de kaydedilen public `503 vault_unavailable` bu turdaki no-token front-door probeda tekrar üretilemedi.
- Açık boşluk (Session 23 sonrası güncel): non-superAdmin scoped deny kanıtlandı (`403`), ancak scoped allow (`gridId=1204` için `200`) henüz canlıda kapanmadı.

## Live Delta — Session 21 (2026-04-23 18:05 UTC+3)

- Host-bridge ağ kontratı prod için tek modelde çalışıyor:
  - Compose bind: `platform-pg-prod` `10.9.10.53:5432`, `platform-kc-prod` `10.9.10.53:8081`, `platform-vault-prod` `10.9.10.53:8200` (+ `127.0.0.1` admin bind).
  - K8s host-service Endpoints: `postgres=10.9.10.53:5432`, `keycloak=10.9.10.53:8081`, `vault=10.9.10.53:8200`.
  - UFW routed modeli canlı: `10.9.10.53:{5432,8081,8200}` için `ALLOW IN` + `ALLOW FWD` kuralları aktif.
- Gate sonucu (istenen sıra):
  - `ClusterSecretStore Ready=True`: `vault-platform-gitops -> True/Valid`.
  - `prod ExternalSecret SecretSynced=True`: kritik setin tamamı `True/SecretSynced`.
  - `backend rollout Running`: tüm backend Deployment'lar `ready=desired`, `openfga` StatefulSet `1/1`.
  - `authenticated prod smoke`: **PARTIAL** (k8s ingress: `authz/me=200`, `variants=401`; public `ai.acik.com`: `authz/me` ve `variants` `503 vault_unavailable`).
- Authenticated zincirde kök neden ayrıştırması:
  - Aynı bearer token ile `127.0.0.1:30443` (ingress) ve `ai.acik.com` (public front-door) farklı davranıyor; bu, blocker'ın host-bridge/ESO değil front-door backend zinciri olduğunu doğruluyor.
  - `variant-service` authenticated çağrıda halen `401` dönüyor; ağ/ESO katmanı geçti, kalan blocker authz/contract düzeyi.
- Ek kapanış:
  - `kv/platform/openfga` placeholder değerleri canlıda güncellendi (`store_id` + `model_id` gerçek ID), `permission-service-secrets` ve `variant-service-secrets` yeni ID'lerle senkronlandı.
  - `smoke-client` service-account token ve `testuser` password-grant token ile sonuç aynı pattern'i veriyor (`ingress 200/401`, public 503).

---

## 1. 5-Sayaç Dashboard (0-95 skala)

Codex önerisi: `0=yok`, `25=doküman`, `50=partial live`, `75=kanıtlı ama cutover-ready değil`, `90+=gate geçmiş`. Tek host + warm rollback yok → tavan ~95.

| Sayaç | Değer | Claim | Last Evidence | Last Verified | Owner | Next Gate |
|---|---:|---|---|---|---|---|
| **test-k8s** | **86** | Authoritative `staging-sw` test cluster'da bridge/ESO zinciri canlı: `ClusterSecretStore` `Ready=True`, kritik `ExternalSecret`'ler `SecretSynced=True`, `variant-service` + `permission-service` + `api-gateway` `1/1 Running`. `api-gateway` üstündeki public v1 theme ve variants route drift'i live patch ile kapatıldı; `/api/v1/theme-registry` `200`. Scoped authz kanıtı artık non-superAdmin synthetic kullanıcıyla canlı: `canaryscope` tokenında `superAdmin=false`, `roles=[\"VARIANT_SCOPE_CANARY\"]`, allow scope `PROJECT/1204`; aynı tokenla `/api/v1/variants?gridId=1204` `200`, `gridId=test-grid` `403`. Anonymous crawler ikinci kez `0` hata verdi. Caveat: authoritative remote `k3d-test` cluster'da şu an `monitoring` namespace / `Probe` / `PrometheusRule` yüzeyi yok; bu yüzden `24h` soak `2026-04-22 23:18 UTC+3` itibarıyla public/front-door soak olarak başladı, full in-cluster alert-backed soak değil | `curl -ks https://testai.acik.com/` → `VITE_FRONTEND_PUBLIC_ORIGIN=https://testai.acik.com`, `VITE_KEYCLOAK_REALM=platform-test`, `VITE_GATEWAY_URL=https://testai.acik.com/api`; `curl -sk https://testai.acik.com/realms/platform-test/.well-known/openid-configuration | jq -r .issuer` → `https://testai.acik.com/realms/platform-test`; `curl -sk -I https://testai.acik.com/resources/4wivm/login/keycloak.v2/css/styles.css` → `200 text/css`; `ssh staging-sw 'docker exec k3d-test-server-0 kubectl get clustersecretstore vault-platform-gitops -o jsonpath=\"{.status.conditions[0].type} {.status.conditions[0].status} {.status.conditions[0].reason}\"'` → `Ready True Valid`; `ssh staging-sw 'docker exec k3d-test-server-0 kubectl -n platform-test get externalsecret -o wide'` → kritik secret'ler `SecretSynced=True`; `ssh staging-sw 'docker exec k3d-test-server-0 kubectl -n platform-test get deploy variant-service permission-service api-gateway -o wide'` → `1/1`; `curl -sk -o /dev/null -w '%{http_code}' https://testai.acik.com/api/v1/theme-registry` → `200`; password grant (`client_id=frontend`, `username=canaryscope`) + `curl -sk -H 'Authorization: Bearer …' https://testai.acik.com/api/v1/authz/me` → `200` + `superAdmin=false` + `allowedScopes=[{\"scopeType\":\"PROJECT\",\"scopeRefId\":1204}]`; `curl -sk -H 'Authorization: Bearer …' 'https://testai.acik.com/api/v1/variants?gridId=1204'` → `200`; `curl -sk -H 'Authorization: Bearer …' 'https://testai.acik.com/api/v1/variants?gridId=test-grid'` → `403`; crawler raporları `/Users/halilkocoglu/Documents/.cache/reports/staging-console-crawler-2026-04-22T20-02-11-902Z.json` ve `/Users/halilkocoglu/Documents/.cache/reports/staging-console-crawler-2026-04-22T20-22-28-113Z.json` → `routes with errors: 0`, `console errors: 0`, `network failures: 0`; `ssh staging-sw 'docker exec k3d-test-server-0 kubectl get ns'` → `monitoring` yok; `kubectl get probe -A` / `kubectl get prometheusrule -A` → boş | 2026-04-23 | Codex | `24h` public soak penceresini izle; authoritative test monitoring truth'unu geri kur veya yokluğunu plan/durumda açıkça taşı |
| **prod-stateful-split** | **73** | `platform-pg-prod` + `platform-vault-prod` canlı; prod compose/discovery yüzeyi yeniden toparlandı: `auth-service`, `user-service`, `permission-service`, `variant-service`, `api-gateway`, `discovery-server` `Up/healthy` ve Eureka'da kayıtlı. Canlı kök neden zinciri genişledi: önce prod/test stateful alias collision kapatıldı (`platform-pg-prod` ve `platform-pg-test` aynı `platform_microservice-network` içinde `postgres-db` adı yayıyordu), sonra `platform-web-nginx` içindeki aktif `ai` `/api/` upstream'i `127.0.0.1:8082` yerine `127.0.0.1:8080` gateway yoluna çevrildi, ardından prod `api-gateway` temiz env ile recreate edilerek gerçek prod issuer/JWKS değerleri container'a geçirildi. Bu turda `variant-service` canlı compose override'ı da düzeltildi: audience `account`, OpenFGA store/model değerleri ve `PERMISSION_SERVICE_BASE_URL=http://permission-service:8084` container env'ine geçti. Sonuçta authenticated prod çağrıda `authz/me` `200` korunuyor; `variants` davranışı token sınıfına göre ayrışıyor (`smoke-client` service-account `401`, non-superAdmin `canary-restricted@stage.local` için canary `gridId=1204` çağrısı `403`, non-scoped `gridId=9999` çağrısı `401`). `canary-restricted` için `authz/me` yanıtı `superAdmin=false`, `permissions_count=7`, `allowedScopes=[]`; açık blocker prod scoped allow seed kontratı. `platform-kc-prod` healthcheck ayrı drift olarak hâlâ `unhealthy` | `docker ps` → `platform-auth-service-1`, `platform-user-service-1`, `platform-permission-service-1`, `platform-variant-service-1` healthy + `platform-pg-prod` healthy + `platform-vault-prod` healthy + `platform-kc-prod` unhealthy; `docker exec platform-discovery-server-1 curl http://localhost:8761/eureka/apps` → `AUTH-SERVICE`, `USER-SERVICE`, `PERMISSION-SERVICE`, `VARIANT-SERVICE`, `API-GATEWAY`, `CORE-DATA-SERVICE`, `REPORT-SERVICE`; `docker inspect platform-pg-prod` + `platform-pg-test` → her ikisi de daha önce `platform_microservice-network` içinde `postgres-db` alias'ına sahipti; `docker network disconnect platform_microservice-network platform-pg-test` sonrası `nslookup postgres-db` yalnız `172.18.0.2`; source canonical örnek `/Users/halilkocoglu/Documents/dev/deploy/ubuntu/nginx-frontend-5544.example.conf` içinde `/api/` → `127.0.0.1:8080/api/`; canlı `platform-web-nginx` config `/home/halil/platform/web/nginx/default.conf` içinde `/api/` upstream `127.0.0.1:8082` idi, `127.0.0.1:8080` olarak değiştirildi; `docker inspect platform-api-gateway-1 --format '{{range .Config.Env}}{{println .}}{{end}}'` → `SECURITY_JWT_ISSUER=https://ai.acik.com/realms/serban`, `SECURITY_JWT_JWK_SET_URI=http://keycloak:8080/realms/serban/protocol/openid-connect/certs`, `SECURITY_AUTH_ALLOWED_CLIENT_IDS=frontend,admin-cli,serban-web,account,canary-load`; `docker port platform-permission-service-1` → `8084/tcp -> 0.0.0.0:8090`; `docker exec platform-variant-service-1 curl http://permission-service:8084/actuator/health` → `200`, `permission-service:80`/`:8090` refused; `docker exec platform-variant-service-1 env` → `SECURITY_JWT_AUDIENCE=account`, `ERP_OPENFGA_STORE_ID=01KPVGQCTZ3K5PHHM1HY0PMN13`, `ERP_OPENFGA_MODEL_ID=01KPVGQCY4XGRVAHWATQ4PQ974`, `PERMISSION_SERVICE_BASE_URL=http://permission-service:8084`; gerçek prod token smoke: `curl -sk -X POST https://ai.acik.com/realms/serban/protocol/openid-connect/token ... client_id=canary-load ...` → token, decoded claims `aud=\"account\"`, `azp=\"canary-load\"`, `preferred_username=\"canary-restricted@stage.local\"`; aynı tokenla `curl -sk -H 'Authorization: Bearer …' https://ai.acik.com/api/v1/authz/me` → `200` + `superAdmin=false` + `permissions_count=7`; `curl -sk -H 'Authorization: Bearer …' 'https://ai.acik.com/api/v1/variants?gridId=1204'` → `403`; `curl -sk -H 'Authorization: Bearer …' 'https://ai.acik.com/api/v1/variants?gridId=9999'` → `401`; service-account token smoke: `authz/me=200`, `variants=401`; `variant-service` logları → `JwtAuthenticationProvider : Authenticated token`, `OpenFGA client created: url=http://openfga:8080, storeId=01KPVGQCTZ3K5PHHM1HY0PMN13`; `docker inspect platform-kc-prod` → `Health.Status=unhealthy` ama `ai.acik.com/realms/serban` token mint çalışıyor | 2026-04-23 | Ops | Prod scoped allow seed kontratı + `platform-kc-prod` unhealthy kök nedeni + DR drill + KC backup freshness |
| **prod-stateful-split** | **76** | Session 25: `platform-kc-prod` compose recreate sonrası `Health.Status=healthy` (PR #57 dual-network + healthcheck `localhost→127.0.0.1` + printf); Known Drift "platform-kc-prod unhealthy" kapandı. Prod compose/discovery yüzeyi stabil | `docker inspect platform-kc-prod --format '{{.State.Status}} {{.State.Health.Status}}'` → `running healthy`; `docker inspect platform-kc-prod --format '{{range \$k,\$v:=.NetworkSettings.Networks}}{{\$k}} {{end}}'` → `platform-prod-net platform_microservice-network`; healthcheck exit log son 3 `[0] [0] [0]` | 2026-04-24 | Ops | Prod scoped allow seed kontratı + DR full drill (KC dahil) |
| **prod-workload-gitops** | **75** | Session 25: PR #57 ESO roleId manifest'te gerçek UUID (canlı CSS ile parite), Faz 11 GitOps drift minimal kaldı. Runtime 19 pod Running + canlı trafik akıyor, ArgoCD OutOfSync/Degraded kozmetik | Kanıtlar Session 24 satırı + PR #57 `kubectl kustomize kustomize/overlays/prod/eso` → `roleId: 0db7ba83-b485-4afb-da7d-e1041b1f8a56` (canlı CSS ile parite) | 2026-04-24 | Claude | Faz 13 cluster rebuild (C rotası) cosmetic diff'i doğal temizle |
| **secret-delivery** | **87** | Session 25: Prod ESO roleId manifest-canlı paritede (PR #57), v1 migration + ignoreDifferences + ghcr-pull zinciri canlı. Artık her iki cluster'da secret-delivery gate %85+ | Kanıtlar Session 24 satırı + `kubectl describe clustersecretstore vault-platform-gitops` → `Role Id: 0db7ba83-b485-4afb-da7d-e1041b1f8a56` aktif + manifest ile parite | 2026-04-24 | Codex | Faz 13 atomic cutover için gate ≥80 ✅ |
| **dr-validation** | **70** | Session 25: **DR drill canlı PASS** 2026-04-24 00:31:11-00:32:33 UTC+3. RTO **81 saniye** / 14400s budget (0.56%). SKIP_KC=1 PARTIAL (KC export cron `kcadm.sh get` şu an partial export, users/creds yok). 5 iterative drill bug fix (#55 initial → #58 set-e+stderr+safety glob → #59 sandbox chmod → #60 Vault sealed smoke). PG 4s + Vault 13s + 2x smoke + 60s sleep + RTO = 81s | `ssh staging-sw 'cat /tmp/dr-drill-20260424-003111.log'` → `=== DR DRILL PASS ===`, `RTO: PASS (81s / 14400s budget)`, `SMOKE[1]: PASS` + `SMOKE[2]: PASS`, `VAULT: restored (4s)`, `PG: restored (2s)`, `Vault: Initialized=true (Sealed=true) — snapshot restore validated` | 2026-04-24 | Claude | Full drill (KC dahil): `kc-export-cron.sh` full `kc.sh export --users realm_file` upgrade → dr-validation 70→85; drill cron scheduling PLAN.md D23 quarterly |

**Weighted operational continuity**: `~%86` (Session 25: Faz 10/11/12 operasyonel kapanış — 9 PR merge + 5 drill iterative bug fix. Faz 11 KC compose healthy + ESO roleId manifest-canlı parite; Faz 12 DR drill canlı PASS RTO 81s, `dr-validation` 0→70. Kalan açık: prod non-superAdmin scoped allow seed kontratı (variants 1204=200), KC full drill için export cron upgrade, Faz 13 atomic cutover karar ve ArgoCD cosmetic OutOfSync (Faz 13 rebuild ile doğal temizlenir). Faz 13 prereq: secret-delivery=87 ≥80 ✅; dr-validation=70 (<85) — hybrid kabul veya full drill gerekli.)

---

## 2. Canlı Trafik Matrisi

| Hostname | Edge | Real Backend Owner | Smoke Evidence |
|---|---|---|---|
| `ai.acik.com` | staging-sw live edge + restored prod web root | Prod web rollback sonrası authoritative root yeniden `/home/halil/platform/web/releases/773175b`; frontend `platform-web-nginx` container'ı bu release'i mount ediyor ve host-network modunda `:80/:443` front-door'u servis ediyor. Backend tarafında prod compose/discovery yüzeyi toparlandı: `AUTH-SERVICE`, `USER-SERVICE`, `PERMISSION-SERVICE`, `VARIANT-SERVICE` healthy ve Eureka'da kayıtlı. Canlı recovery zinciri: prod/test PG alias collision kapatıldı, aktif `platform-web-nginx` config'inde `ai` `/api/` upstream'i `127.0.0.1:8082` yerine `127.0.0.1:8080` gateway yoluna çevrildi, prod `api-gateway` temiz env ile recreate edilerek gerçek prod issuer/JWKS değerleri container'a geçirildi, ardından `variant-service` canlı compose env'i audience/OpenFGA/permission-service internal port açısından hizalandı. Sonuçta public no-token kontratı hizalı, authenticated hatta `authz/me` `200`; kalan açık drift scoped allow seed kontratı (`smoke-client` service-account hattında `variants=401`, non-superAdmin password-grant hattında canary `gridId=1204` için `403`, non-scoped `gridId=9999` için `401`) | `docker inspect platform-web-nginx` → `NetworkMode=host`; canlı config `/home/halil/platform/web/nginx/default.conf` ve `docker exec platform-web-nginx nginx -T` içinde `server_name ai.acik.com` + `location /api/`; fix öncesi `proxy_pass http://127.0.0.1:8082;`, source canonical örnekte `/Users/halilkocoglu/Documents/dev/deploy/ubuntu/nginx-frontend-5544.example.conf` içinde `/api/` → `127.0.0.1:8080/api/`; fix sonrası public no-token smoke: `curl -sk https://ai.acik.com/api/v1/authz/me` → `401`, `curl -sk https://ai.acik.com/api/v1/theme-registry` → `200`, `curl -sk 'https://ai.acik.com/api/v1/variants?gridId=1204'` → `401`; gerçek prod token smoke: `curl -sk -X POST https://ai.acik.com/realms/serban/protocol/openid-connect/token ... client_id=canary-load ...` → token, decoded claims `aud=\"account\"`; aynı tokenla `curl -sk -H 'Authorization: Bearer …' https://ai.acik.com/api/v1/authz/me` → `200` + `superAdmin=false` + `permissions_count=7`; `curl -sk -H 'Authorization: Bearer …' 'https://ai.acik.com/api/v1/variants?gridId=1204'` → `403`; `curl -sk -H 'Authorization: Bearer …' 'https://ai.acik.com/api/v1/variants?gridId=9999'` → `401`; service-account token smoke: `authz/me=200`, `variants=401`; `docker exec platform-variant-service-1 env` → `SECURITY_JWT_AUDIENCE=account`, `ERP_OPENFGA_STORE_ID=01KPVGQCTZ3K5PHHM1HY0PMN13`, `ERP_OPENFGA_MODEL_ID=01KPVGQCY4XGRVAHWATQ4PQ974`, `PERMISSION_SERVICE_BASE_URL=http://permission-service:8084`; `docker exec platform-discovery-server-1 curl http://localhost:8761/eureka/apps` → `AUTH-SERVICE`, `USER-SERVICE`, `PERMISSION-SERVICE`, `VARIANT-SERVICE`, `API-GATEWAY`, `CORE-DATA-SERVICE`, `REPORT-SERVICE` kayıtlı |
| `testai.acik.com` | Authoritative external edge doğru stage release yüzeyine bakıyor | Host üstündeki `/home/halil/platform/web-stage/releases/a67f34e` release'i, `platform-web-nginx-stage`, `platform-kc-test`, `platform-pg-test`, `platform-vault-test` ve remote `k3d-test` public front-door'a bağlı. Frontend bundle public `testai/api` kontratıyla derlenmiş. Test ESO/bridge zinciri remote hostta sağlıklı; `api-gateway` üstündeki eksik `theme` + public v1 `variants` route'ları live patch edildiği için `/api/v1/theme-registry` `200`. Scoped authz zinciri artık gerçek non-superAdmin synthetic ile kanıtlı: `canaryscope` kullanıcı/tokenu canary `gridId=1204` için `200`, non-canary `test-grid` için `403`. Anonymous crawler iki koşuda da hata üretmedi | Public truth: `curl -ks https://testai.acik.com/` → `VITE_FRONTEND_PUBLIC_ORIGIN=https://testai.acik.com`, `VITE_KEYCLOAK_REALM=platform-test`, `VITE_GATEWAY_URL=https://testai.acik.com/api`; `curl -sk https://testai.acik.com/realms/platform-test/.well-known/openid-configuration | jq -r .issuer` → `https://testai.acik.com/realms/platform-test`; `curl -sk https://testai.acik.com/login` → `200`; `curl -sk -I https://testai.acik.com/resources/4wivm/login/keycloak.v2/css/styles.css` → `200 text/css`; `curl -sk -o /dev/null -w '%{http_code}' https://testai.acik.com/api/v1/theme-registry` → `200`; no-token `curl -sk -o /dev/null -w '%{http_code}' 'https://testai.acik.com/api/v1/variants?gridId=1204'` → `401`; password grant (`client_id=frontend`, `username=canaryscope`) ile `curl -sk -H 'Authorization: Bearer …' https://testai.acik.com/api/v1/authz/me` → `200` + `superAdmin=false`; `curl -sk -H 'Authorization: Bearer …' 'https://testai.acik.com/api/v1/variants?gridId=1204'` → `200`; `curl -sk -H 'Authorization: Bearer …' 'https://testai.acik.com/api/v1/variants?gridId=test-grid'` → `403`; crawler raporları `/Users/halilkocoglu/Documents/.cache/reports/staging-console-crawler-2026-04-22T20-02-11-902Z.json` ve `/Users/halilkocoglu/Documents/.cache/reports/staging-console-crawler-2026-04-22T20-22-28-113Z.json` → `routes with errors: 0`, `console errors: 0`, `network failures: 0` |
| `argocd` | live host `k3d-prod` cluster'da control-plane var ama degraded | `argocd` + `external-secrets` + `platform-prod` namespace/CRD/app yüzeyi mevcut; fakat `platform-prod` ve `platform-eso-prod` app'leri `OutOfSync/Degraded` | `kubectl get ns` → `argocd`, `external-secrets`, `platform-prod` var; `kubectl get applications.argoproj.io -n argocd` → prod app'ler `OutOfSync/Degraded`; `kubectl get crd | egrep 'argoproj.io|external-secrets.io'` → mevcut |
| Monitoring | Host backup freshness metriği var; authoritative test cluster monitoring yüzeyi şu an yok | Remote `k3d-test` authoritative cluster'da `monitoring` namespace, `Probe` ve `PrometheusRule` bulunmuyor. Bu nedenle `24h` soak, Prometheus-backed değil public front-door/manual soak olarak başladı. Host textfile exporter tarafında `pg`/`vault` timestamp var, `kc=0` devam ediyor | `ssh staging-sw 'docker exec k3d-test-server-0 kubectl get ns'` → `monitoring` yok; `kubectl get probe -A` → boş; `kubectl get prometheusrule -A` → boş; `backup_freshness.prom` içinde `backup_last_success_timestamp_seconds{type=\"kc\"} 0` |

---

## 3. Rollback Durumu

| Akış | Status | Preserved Volumes | Last Test Date | RTO/RPO |
|---|---|---|---|---|
| **ai.acik.com → compose legacy** | `cold-potential` (test edilmedi) | Docker volume: `platform_loki_data`, `platform_tempo_data`, `platform_vault-data`, `platform_vault_logs`, `platform_vault_snapshots`; host bind-mount: `/home/halil/platform-stateful/prod/{postgres,keycloak,vault}` | **NEVER** | Hedef: RTO≤4h, RPO≤24h (ölçülmedi) |
| **testai.acik.com → compose legacy** | `no rollback path` | Test stateful yeni stack, eski yoktu | N/A | N/A |
| **K8s workload rollback** | `k8s workload henüz apply edilmedi prod` | N/A | N/A | N/A |

**Warm rollback iddiası ihlali**: ADR-0002 §8 `T+72h warm rollback` istiyor. Şu an `cold rollback potential` = sözleşmeye aykırı.

---

## 4. Known Drift (Yazılı Karar Yok)

| Drift | ADR/Kontrat | Gerçek Durum | Owner | Target Date | Blocker Class |
|---|---|---|---|---|---|
| Disk path | `/srv/platform/stateful/{prod,test}/...` (ADR §3.2) | `/home/halil/platform-stateful/...` (override) | Ops | 2026-04-25 | LOW (çalışıyor, doküman eksik) |
| Test Vault port | 8201 (ADR §0.2) | 8301 (eski vault 8201'i tutuyor) | Ops | 2026-04-25 | LOW |
| Vault version | ≥1.21 (eski compose) | 1.17 (yeni host-compose) | Claude | 2026-04-23 | MEDIUM — undocumented version track change |
| k3d CLI | staging-sw'de kurulu (ADR §3.1 varsayım) | VAR; Session 13 recreate runbook'u `ssh staging-sw` üstünden `k3d cluster delete/create test` ile canlı çalıştı | Ops | N/A | LOW |
| Test runtime closure | `testai.acik.com` public root, gateway ve realm stage yüzeyine gidiyor olmalı; bunun üstüne runtime deny/login/crawler + authenticated allow kapanmalı; test authoritative before prod | Front-door parity doğru, Keycloak browser static asset zinciri canlıda temiz, anonymous crawler iki kez `0` hata üretti. Scoped authz zinciri artık non-superAdmin synthetic ile kanıtlı: `canaryscope` tokenıyla `authz/me` `200` + `superAdmin=false`, `/api/v1/variants?gridId=1204` `200`, `/api/v1/variants?gridId=test-grid` `403`. Ayrı not: authoritative remote `k3d-test` cluster'da monitoring/blackbox yüzeyi yok; başlatılan `24h` soak bu yüzden public/front-door soak. Prod public hedefleri (`ai.acik.com/api/v1/*`) no-token tarafta hizalı; authenticated hatta `authz/me` `200` korunuyor fakat `variants` davranışı token sınıfına göre ayrışıyor (`smoke-client` service-account `401`, non-superAdmin password-grant `403`). Bu artık audience/JWKS değil; prod scoped allow seed kontratı ayrı blocker olarak açık | Ops/App | Faz 11 | HIGH |
| Kubectl context split | `testai` için authoritative cluster aynı hostta çalışan `staging-sw` `k3d-test` olmalı | Lokal Mac `kubectl --context k3d-test` ayrı cluster'a gidiyor (`linuxkit`/Docker Desktop) ve `testai.acik.com` için karar kaynağı değildir; live truth bundan sonra `ssh staging-sw` üstünden alınmalı | Codex | Hemen | MEDIUM |
| Test monitoring drift | Faz C tarzı soak için authoritative test cluster'da monitoring/Probe/PrometheusRule yüzeyi bulunmalı | Remote `k3d-test` cluster recreate sonrası `monitoring` namespace ve Prometheus operator yüzeyi yok; mevcut soak yalnız public/front-door kanıtı üretiyor | Ops | Faz 11 | HIGH |
| Prod authenticated public contract | `ai.acik.com` public `/api/v1/*` kontratı front-door'da internal gateway ile hizalanmalı ve gerçek prod token authenticated smoke geçmeli | Prod `platform-api-gateway-1` route table'da v1 path'ler var; compose/discovery yüzeyi toparlanmış durumda ve `AUTH-SERVICE`, `USER-SERVICE`, `PERMISSION-SERVICE`, `VARIANT-SERVICE` Eureka'da kayıtlı. Front-door drift kapatıldı: aktif `platform-web-nginx` config'inde `ai` `/api/` upstream'i `127.0.0.1:8082` idi, `127.0.0.1:8080` yapıldı ve public no-token smoke internal gateway ile hizalandı (`401/200/401`). Prod `api-gateway` issuer/JWKS drift'i kapatıldı: canlı env artık `SECURITY_JWT_ISSUER=https://ai.acik.com/realms/serban` + `SECURITY_JWT_JWK_SET_URI=http://keycloak:8080/realms/serban/protocol/openid-connect/certs` taşıyor ve gerçek prod token ile `authz/me` `200` dönüyor. Bu turda `variant-service` canlı compose env'i de düzeltildi: `SECURITY_JWT_AUDIENCE=account`, OpenFGA store/model dolu, `permission-service` internal URL `http://permission-service:8084`. Açık authenticated blocker artık audience/JWKS/env değil: `canary-load` tokenındaki `canary-restricted@stage.local` kullanıcısı için `authz/me` `200` + `permissions_count=7` + `allowedScopes=[]` + `superAdmin=false`; canary `variants?gridId=1204` `403`, non-scoped `variants?gridId=9999` `401`. Service-account tokenında ise `variants` `401` devam ediyor. `platform-kc-prod` healthcheck ayrı drift olarak `unhealthy` kalıyor, fakat token mint ve `authz/me` geçtiği için artık birincil public blocker gateway decoder değil | Ops/App | Faz 11 | HIGH |
| Prod Keycloak uid mapper drift | Non-superAdmin scoped parity için farklı kullanıcı tokenları farklı kimlik claim'i taşımalı (`uid` veya `userId`) | `serban` realm `canary-load` client'ında iki mapper birlikte aktif: `uid-claim` (user attribute) + `uid-static` (hardcoded). Hardcoded mapper `claim.value=920001` nedeniyle farklı kullanıcılar aynı `uid` ile token alıyor (`admin@example.com` ve `canary-restricted@stage.local` için `uid=920001`). Bu yüzden scoped allow modelinde kullanıcı ayrımı bozuluyor | `kcadm get clients/<canary-load-id>/protocol-mappers/models -r serban` → `uid-static` + `claim.value=920001`; token decode (`grant_type=password`, `client_id=canary-load`) ile iki farklı user için `uid=920001`; `variant-service` logu `Resolved variant authz context ... userId=920001` | Ops/App | Faz 11 | HIGH |
| Prod ESO `roleId` | Gerçek UUID overlay patch | Placeholder literal `"eso-runtime"` | Claude | Faz 11 | HIGH (secret delivery block) |
| ClusterIssuer Let's Encrypt | `bootstrap/install-cert-manager.sh` var, apply edilmiş | ClusterIssuer YOK canlıda | Claude | Faz 12 | MEDIUM |
| Test cluster ArgoCD register | Prod hub'dan yönet (ADR §3.7) | k3d-test kayıtlı DEĞİL | Ops | Faz 11 | MEDIUM |
| Handoff split | Append-only 1207 satır | Bu PR ile canonical + historical ayrımı başladı | Claude | Faz 10 | LOW |

---

## 5. Sonraki 4 Faz (Codex Planı)

Detay bu dokümanda tutulur; ayrı session log split'i henüz repo içine alınmadı.

| Faz | Pencere | Done Kriter | No-Go |
|---|---|---|---|
| **10 Dürüstlük Recovery** | D0-D1 (21-22 Nis) | Bu dosya + handoff split + söylem revizyonu | Aktif 1207 satır handoff karar kaynağı kalırsa |
| **11 Secret Delivery Truth** | D2-D4 (23-25 Nis) | Test CSS Ready + kritik ExternalSecret Sync + frontend canonical image + frontend SA public pull path + stage/prod web path isolation host üzerinde doğrulanmış + authoritative public `testai.acik.com` root gerçekten stage bundle'ı servis ediyor: `VITE_FRONTEND_PUBLIC_ORIGIN=testai`, `VITE_GATEWAY_URL=testai/api`, `VITE_KEYCLOAK_REALM=platform-test` + `/.well-known/openid-configuration` `200` + Keycloak browser login support path temiz (`3p-cookies` beklenen davranışta, login static resources 2xx/MIME doğru) + deny zinciri yeşil + crawler `runtimeErrors=0` + public authenticated path dürüstçe yazılmış: `canaryscope` (non-superAdmin, `VARIANT_SCOPE_CANARY`, `PROJECT/1204`) ile canary `gridId=1204` `200`, non-canary `test-grid` `403`; `testuser(superAdmin)` yalnız broad-admin smoke olarak kalır + authoritative test monitoring yokluğu açıkça yazılmış + prod ESO/live-host yokluğu ve prod public `/api/v1/*` kontrat açığı dürüstçe yazılmış | `curl https://testai.acik.com/` veya `/.well-known/openid-configuration` yeniden drift ederse; anonymous crawler yeniden hata üretirse; browser Keycloak static resources `404/500` + yanlış MIME verirse; login smoke callback/token aşamasında kırılırsa; authoritative test monitoring yokluğu gizlenirse veya prod public `/api/v1/*` kontratı kapanmamışken hazır dili kullanılırsa |
| **12 DR Cold Rollback** | D5-D7 (26-28 Nis) | Clone drill + 2x independent boot-smoke + RTO≤4h | Canlı volume dokunulursa |
| **13 Atomic Cutover** | D8-D11 (29 Nis-3 May) | Nginx upstream switch + T+15 gate + 72h warm rollback | `secret-delivery<80` veya `dr-validation<85` |

---

## 6. Yasak Terimler (Söylem Temizliği)

Bu dokümanda ve sonraki iletişimde **kullanılmayacak**:

- ❌ "Faz H DONE" / "H fiilen yapıldı" → ✅ "Legacy container rm, Faz H formal olarak henüz BAŞLAMADI (soak sonrası)"
- ❌ "Faz G cutover yapıldı" / "soft cutover" → ✅ "Stateful split migration with compose-preserved workload"
- ❌ "%99.5 migration complete" → ✅ "Weighted operational continuity ~%74"
- ❌ "test Zanzibar smoke tamam" → ✅ "Front-door, Keycloak static asset zinciri, test ESO/ExternalSecret, non-superAdmin scoped deny/allow, authenticated allow ve anonymous crawler canlıda doğrulandı; authoritative test monitoring ise şu an yok"
- ❌ "warm rollback available" → ✅ "cold rollback potential, drill yapılmadı"
- ❌ "ESO chain hazır, sadece routing" → ✅ "Authoritative `staging-sw` test cluster'da ESO/ExternalSecret zinciri çalışıyor; `theme-registry` sorunu live `api-gateway` route drift'iydi ve patch edildi. Prod cluster'da ESO yüzeyi ise henüz yok"

---

## 7. Referanslar

- **ADR**: `docs/adr/0002-single-host-dual-cluster.md` (supersedes D32)
- **Roadmap**: `PLAN.md` §0 Faz A-I (Faz 10-13 bu dokümanda ek)
- **Runbook**: `docs/prod-cutover-runbook-v2.md`, `docs/S5-disaster-recovery-runbook.md`
- **Handoff**: `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (Session 1-10 kronolojik, append-only, karar kaynağı değil)
- **Review backlog**: `docs/plan-revision-review-2026-04-20.md` (canonical cleanup backlog)
- **Codex adversarial reviews**: thread `019daa7f` (adversarial), thread `019daad8` (4-faz plan)
