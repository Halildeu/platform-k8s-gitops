# RB-staging-prod-profile — Staging'i Prod-Profile'a Geçirme Runbook

ID: RB-staging-prod-profile  
Service: backend-stack (7 Spring Boot services)  
Status: Rehearsed (2026-04-18; PR #3f deploy 24590348212 canlı kanıt — profile=prod,docker runtime, GHCR digest aktif, 8 container healthy, /authz/me superAdmin=True authzVersion=8; AppRole setup pending operational)
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

Staging ortamını "prod-like" hale getirmek: 7 backend servisin
`SPRING_PROFILES_ACTIVE` içinde `local` kalmayacak, Vault AppRole secret
fetch fiilen çalışacak, GHCR image pull staging deploy'da gerçekten
egzersiz edilecek. Amaç iki:

- **Prod cutover risk azaltma:** Production'a ilk çıkışta bir path'in
  ilk kez gerçekleşmesini engellemek. Staging'de her adım ≥1 hafta
  stabil çalışırsa prod'da sürpriz yok.
- **Zanzibar canary sinyal anlamlılığı:** Local profile'da
  `SecurityConfigLocal permitAll` JWT doğrulamayı kapatıyor,
  deny-rate/tuple-sync metrikleri sahte yeşil veriyor. Prod-profile
  staging canary run'larının anlamlı olmasını sağlar (Dalga 1 Stage 2
  önkoşul).

**Bu runbook STORY-0319 acceptance'ını karşılar ve Dalga 1 Stage 2
synthetic canary run'un prereq'ini belgeler.**

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

**Sorumlu ekipler:** Platform Engineering (operasyon).
**Ortam:** staging (`ai.acik.com`, host-backed docker compose).
**Base:** 7 Spring Boot servisi (user, auth, variant, core-data,
api-gateway, permission, report), Vault 1.21.4 + AppRole, HashiCorp Vault
dev-path (staging), GHCR registry.

**İlgili dosyalar:**
- `backend/docker-compose.yml` — compose default (D-105 + C-103 gereği değişmez)
- `backend/.env.prod.example` — canonical env template
- `deploy/ubuntu/render-backend-env.sh` — canonical env render script (host-side AppRole; `VAULT_ADDR`+`VAULT_TOKEN` zorunlu)
- `deploy/ubuntu/deploy-backend.sh` — staging deploy entry point
- `.github/workflows/deploy-backend.yml` — CI deploy workflow (inputs: `env`, `render_env_before_deploy`, `build_local`, `docker_pull_policy`; PR #3a-c sonrası default'lar staging rehearsal için flip edildi)
- `backend/scripts/doctor-infra.sh` — L1-L8 profile drift guard
- `backend/{auth,permission}-service/src/main/resources/application-prod.yml`
  — prod profile Spring Cloud Vault actuator + KV wiring (report-service'te bu bağ şu an yok; scope'a dahil değil)
- Staging canonical env: `/home/halil/platform/env/backend.env` (staging host tarafı)
- Vault host-side AppRole referansı: `docs/04-operations/RUNBOOKS/RB-ubuntu-backend-github-vault-deploy.md`

**Kapsam dışı:**
- Production deploy (bu runbook sadece staging — prod için ayrı runbook).
- Canary metric üretimi (RB-zanzibar-canary).
- Vault KMS auto-unseal (RB-vault-kms-autounseal, P1.10'dan).
- report-service Spring Cloud Vault integrasyonu (PR #3 scope'u yalnızca auth + permission;
  report-service ayrı follow-up'a taşındı — mevcut model host-side env render
  ile secret fetch yapıyor, in-container Vault client egzersizi yok).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

### BAŞLATMA — Prod-profile geçişi (staging)


### Pre-migration kanıt toplama

```bash
# Mevcut staging profile durumunu kaydet
ssh staging-sw 'cd /home/halil/platform/repo/backend && bash scripts/doctor-infra.sh' \
  | tee .cache/reports/staging-pre-prod-profile-$(date +%Y%m%d).log
```

L1-L8 başlangıç snapshot'u: hangi servisler hâlâ `local,docker` ?
hangi canonical env key'leri blank ?

### Render contract güncellemesi (PR #2 sonrası)

```bash
# render-backend-env.sh host-side AppRole'dan KV mount okur; VAULT_ADDR ve
# VAULT_TOKEN zorunlu (script line 5-6 assert ediyor). Deploy runner AppRole
# login ile kısa ömürlü VAULT_TOKEN alır — RB-ubuntu-backend-github-vault-deploy
# §3 bu flow'u tarif eder.
ssh staging-sw '
  cd /home/halil/platform/repo && \
  VAULT_ADDR="${VAULT_ADDR:?set in /etc/platform/vault.env}" \
  VAULT_TOKEN="${VAULT_TOKEN:?approle login ile alınmalı}" \
  RENDER_ENV_BEFORE_DEPLOY=true \
  DEPLOY_ENV=stage \
  bash deploy/ubuntu/render-backend-env.sh
'

# Canonical env doğrula
ssh staging-sw '
  grep -E "^(USER|AUTH|VARIANT|CORE_DATA|API_GATEWAY|PERMISSION|REPORT)_SERVICE_PROFILES" \
    /home/halil/platform/env/backend.env
'
# Beklenen: hepsi prod,docker
```

### Vault actuator smoke — auth + permission

PR #3b + PR #3c sonrası container-side Spring Cloud Vault client aktif;
actuator health indicator staging host-local smoke ile doğrulanır
(host firewall/network policy'e bağlı "internal" semantiği — port binding
`8088:8088` + `8090:8084` tüm interface'lere açık, hardening follow-up'a
taşındı):

```bash
ssh staging-sw '
  curl -fsS http://localhost:8088/actuator/health/vault | jq .status
  curl -fsS http://localhost:8090/actuator/health/vault | jq .status
'
# Beklenen: "UP" her ikisi için
```

report-service bu turda kapsam dışı; secret fetch host-side render üzerinden
devam eder (değişiklik yok).

### GHCR pull staging deploy

PR #3c sonrası staging default `BUILD_LOCAL=false` + `DOCKER_PULL_POLICY=always`.
`deploy-backend.sh` remote-pull mode'da doğrudan `docker pull ghcr.io/...`
yapar + her servis için `platform-{svc}:latest` retag. Eksik image → exit 1
(sessiz stale image fallback yok).

```bash
# Workflow dispatch (default path — operatör override gerekmez)
gh workflow run deploy-backend.yml -f env=stage

# Post-deploy assertion (GHCR digest ground truth)
ssh staging-sw '
  docker image inspect platform-auth-service:latest \
    --format "{{json .RepoDigests}}"
'
# Beklenen: ["ghcr.io/halildeu/platform-ssot-auth-service@sha256:..."]

# Emergency rollback (GHCR rate-limit / auth fail durumunda):
gh workflow run deploy-backend.yml \
  -f env=stage \
  -f build_local=true \
  -f docker_pull_policy=never \
  -f render_env_before_deploy=false
```

### Post-deploy doctor-infra (PR #4 sonrası — otomatik)

CI workflow `post-deploy-doctor-infra` job'ı deploy sonrası otomatik
çalışır. Manuel tetikleme için:

```bash
gh workflow run deploy-backend.yml -f env=stage
# Her başarılı deploy sonunda post-doctor PASS annotation beklenir
```

### DURDURMA — Rollback

#### 4.1. Profile rollback (canonical env)

Migration regresyonu → staging canary down → canonical env restore:

```bash
ssh staging-sw '
  cp /home/halil/platform/env/backend.env.bak-YYYYMMDD \
     /home/halil/platform/env/backend.env && \
  cd /home/halil/platform/repo/backend && \
  docker compose --env-file /home/halil/platform/env/backend.env \
    up -d --force-recreate
'
```

### GHCR pull rollback

Normal akış: `BUILD_LOCAL=false` + `DOCKER_PULL_POLICY=always` (PR #3c
stage default). Emergency rollback için workflow_dispatch override:

```bash
gh workflow run deploy-backend.yml \
  -f env=stage \
  -f build_local=true \
  -f docker_pull_policy=never
```

**Uyarı:** `build_local=true` sadece emergency (GHCR rate-limit / auth
fail / digest gecikmesi). Kullanım sonrası GHCR credential rotation
runbook adımı çalıştırılmalı (`GHCR_TOKEN` yenileme + workflow secret
update). `build_local=true` ile deploy olan staging build digest'leri
post-deploy doctor-infra smoke ile validate edilmeli.

### Vault actuator rollback

PR #3b container-side Vault client aktif + PR #3c AppRole-first.
Vault kısa süre erişilemez + boot loop durumunda:

```bash
# Canonical env'de Spring Cloud Vault geçici disable
ssh staging-sw '
  sed -i "s/SPRING_CLOUD_VAULT_ENABLED=true/SPRING_CLOUD_VAULT_ENABLED=false/" \
    /home/halil/platform/env/backend.env && \
  cd /home/halil/platform/repo/backend && \
  docker compose --env-file /home/halil/platform/env/backend.env \
    up -d --force-recreate auth-service permission-service
'
```

**Kök neden tespiti:** `docker logs vault` + `vault status` kontrol et;
`VAULT_DEV_PATH` staging override doğru mu (feedback_infra_stability.md §Vault).

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

### Canlı smoke

```bash
# Profile doğrulama (doctor-infra L1)
ssh staging-sw 'docker exec platform-user-service-1 printenv SPRING_PROFILES_ACTIVE'
# Beklenen: prod,docker (local YOK)

# JWT filter doğrulama (doctor-infra L2)
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://ai.acik.com/api/v1/authz/check \
  -H 'Content-Type: application/json' \
  -d '{"relation":"can_view","objectType":"module","objectId":"REPORT"}'
# Beklenen: 401

# Canonical env drift doğrulama (doctor-infra L3-L8)
ssh staging-sw 'cd /home/halil/platform/repo/backend && bash scripts/doctor-infra.sh'
# Beklenen: L1-L8 hepsi PASS
```

### Vault actuator health (auth + permission)

```bash
ssh staging-sw '
  curl -fsS http://localhost:8088/actuator/health/vault | jq .status
  curl -fsS http://localhost:8090/actuator/health/vault | jq .status
'
# Beklenen: "UP" her ikisi için
```

PR #3b container-side Vault client aktivasyonu + PR #3c AppRole-first
migration ile endpoint hazır; staging host-local smoke path (port
binding `8088:8088` + `8090:8084` tüm interface'lere açık, hardening
follow-up'ta).

### GHCR pull log

```bash
gh run view <RUN_ID> --log | grep -E "docker pull|retagged" | head -20
# Beklenen: "docker pull ghcr.io/halildeu/platform-ssot-*" +
#           "[deploy] retagged N/7 GHCR images -> platform-*:latest"
```

PR #3c sonrası staging default remote-pull: `docker pull` + retag to
`platform-{svc}:latest` + `docker compose up` build by-pass. Image
digest doğrulama: `docker image inspect platform-auth-service:latest
--format '{{json .RepoDigests}}'`.

### Prometheus (Dalga 1 Stage 2 prereq'i için)

Bu runbook sadece profile migration kapsamı. Canary metric gözlemi
`RB-zanzibar-canary.md` §4'te.

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

### Staging canary sahte yeşil

**Semptom:** `/authz/check` token'sız 200 dönüyor, canary deny rate 0.
**Kök neden:** Canonical env'de `{SERVICE}_PROFILES` blank → compose
default `local,docker` devreye girdi → `SecurityConfigLocal permitAll` aktif.
**Çözüm:** §3.2 render contract rehearsal + doctor-infra L1 check.

### Boot log "Unable to connect to Vault"

**Semptom:** auth-service/permission-service boot fail Vault connection error;
actuator /health/vault `DOWN` veya endpoint cevap vermiyor.
**Kök neden:** Spring Cloud Vault override aktif (PR #3b/c sonrası) ama
Vault sealed veya AppRole material eksik (container'a `VAULT_ROLE_ID` /
`VAULT_SECRET_ID` inmiyor; canonical env'e render yazılmamış).
**Çözüm:**
- `vault status` + container env kontrolü (`docker exec ... printenv VAULT_*`).
- Sealed ise §4.3 rollback + unseal recovery (RB-vault-dev-path-migration §5).
- AppRole material eksik → Vault KV `secret/stage/backend-deploy/config`
  içinde `VAULT_ROLE_ID` + `VAULT_SECRET_ID` yazılı mı kontrol et
  (check-backend-deploy-stage.sh ile).

### GHCR pull HTTP 401 / rate-limit

**Semptom:** `docker pull ghcr.io/...` auth fail.
**Kök neden:** `GHCR_TOKEN` expired veya rate-limit hit.
**Çözüm:** GitHub → Settings → Developer settings → Personal access tokens
→ new token (read:packages scope) → workflow secret update. §4.2 emergency
rollback ile kesintiyi minimize et.

### nginx /api/* 502

**Semptom:** Frontend /api/* 502 döner; curl direct gateway 200.
**Kök neden:** nginx upstream port stage compose binding'den sapıyor.
Yaygın kaynak: GitHub env (stage) `WEB_GATEWAY_UPSTREAM` değeri 8082 set
edilmiş ama stage compose hardcoded 8080:8080 bind ediyor (2026-04-18
incident). `run-frontend-nginx-container.sh` script fallback `DEPLOY_ENV=stage
→ 8080` çalışsa bile GH env override eder (`${VAR:-fallback}` VAR set iken
dokunmaz).
**Çözüm (sıralı adımlar):**
- Step A — `gh api repos/:owner/:repo/environments/stage/variables/WEB_GATEWAY_UPSTREAM`
  ile mevcut değeri kontrol et.
- Step B — 8080 olmalı: `gh api ... -X PATCH -f name=WEB_GATEWAY_UPSTREAM -f value=http://127.0.0.1:8080`.
- Step C — `gh workflow run deploy-web.yml --ref main` ile nginx config regenerate.
- Step D — `ssh staging-sw "grep proxy_pass /home/halil/platform/web/nginx/default.conf"`
  ile doğrula.
- Step E — Smoke: `curl -o /dev/null -w '%{http_code}' https://ai.acik.com/api/v1/authz/version -k`
  → 401 (anon, başarılı route) beklenir, 502 değil.

### Post-deploy doctor-infra FAIL

**Semptom:** Workflow `post-deploy-doctor-infra` step RED.
**Kök neden:** L1-L8 herhangi biri FAIL — output annotation'da hangi
check belirtilir.
**Çözüm:** Annotation'a göre §3 ilgili step'i rehearse et;
`RB-backend-env-drift-guard.md` §4 detaylı drift repair prosedürü.

### Host-side render VAULT_TOKEN expired / Vault unreachable

**Semptom:** `render-backend-env.sh` çağrısı `VAULT_ADDR required` veya
`VAULT_TOKEN required` assert fail ile durur; deploy-backend pipeline
canonical env render adımında CRIT exit 1.
**Kök neden:** AppRole login token'ı expire oldu (kısa ömürlü — 1h tipik),
Vault unsealed ama token invalid; veya Vault sealed/unreachable
(`vault status` → sealed: true).
**Çözüm:**

- **Vault status (host AppRole env'i yükleyerek):**
  ```bash
  ssh staging-sw '
    set -a && . /etc/platform/vault.env && set +a && \
    vault status
  '
  ```
  Sealed ise unseal sidecar'ı kontrol et (`RB-vault-dev-path-migration §5`).
- **Unsealed + token invalid (AppRole login tekrar):**
  ```bash
  ssh staging-sw '
    set -a && . /etc/platform/vault.env && set +a && \
    vault write -field=token auth/approle/login \
      role_id="$VAULT_ROLE_ID" \
      secret_id="$VAULT_SECRET_ID"
  '
  ```
  Dönen token'ı `VAULT_TOKEN` olarak export et, render script'i yeniden
  çalıştır (§3.2 örneğindeki gibi).
- **AppRole material eksik:** `VAULT_ROLE_ID`/`VAULT_SECRET_ID` staging
  host `/etc/platform/vault.env` içinde set olmalı (host-side AppRole
  deploy flow — `RB-ubuntu-backend-github-vault-deploy §3`).
- **Persistent unreachable:** compose `vault` container log'u + raft storage
  durumu kontrol et; gerekirse vault container recreate (Shamir seal
  durumunda unseal key manual).

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

Acceptance checklist:


- [ ] Staging 7 servis `SPRING_PROFILES_ACTIVE=prod,docker` (L1 PASS)
- [ ] `/authz/check` token'sız 401/403 (L2 PASS)
- [ ] Canonical env `ERP_OPENFGA_*` + `SECURITY_JWT_ISSUER(S)` non-blank (L3-L8 PASS)
- [ ] Vault actuator smoke UP — auth (8088) + permission (8090)
  `/actuator/health/vault` (PR #3b/c sonrası; report-service scope dışı;
  host-local smoke — port binding 127.0.0.1 hardening ayrı follow-up)
- [ ] GHCR pull staging deploy SUCCESS (BUILD_LOCAL=false)
- [ ] nginx stage/prod upstream symmetry (workflow cleanup done)
- [ ] Post-deploy CI guard 5+ ardışık SUCCESS (`post-doctor-infra` job)
- [ ] Dalga 1 Stage 2 synthetic canary run prereq karşılandı
  (→ `RB-zanzibar-canary.md` §3.1 handoff)

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Story: `docs/03-delivery/STORIES/STORY-0319-staging-prod-profile-migration.md`
- Acceptance: `docs/03-delivery/ACCEPTANCE/AC-0319-staging-prod-profile-migration.md`
- Test plan: `docs/03-delivery/TEST-PLANS/TP-0319-staging-prod-profile-migration.md`
- Canary runbook (downstream): `docs/04-operations/RUNBOOKS/RB-zanzibar-canary.md`
- Env drift guard: `docs/04-operations/RUNBOOKS/RB-backend-env-drift-guard.md`
- Vault dev-path runbook: `docs/04-operations/RUNBOOKS/RB-vault-dev-path-migration.md`
- Decision registry: `decisions/topics/security-local-dev.v1.json`
- Master plan: `.claude/plans/zanzibar-master-plan.md`
