# RB-vault-approle-setup-stage — Staging Vault AppRole Setup

ID: RB-vault-approle-setup-stage  
Service: backend-deploy-stage  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

Staging backend deploy secret zincirini token-path modelinden AppRole-first
modele geçirmek. STORY-0319 PR #3c AppRole kontratını scriptsel seviyede
kurdu; staging Vault'ta `auth/approle/` mount hiç enable edilmediği için
PR #3d soft-fail guard deploy'u unblock etti. Bu runbook kalıcı AppRole
setup'ı belgeler.

- `.github/workflows/deploy-backend.yml` soft-fail guard devre dışı hale
  gelir (workflow_dispatch rehearsal sonrası verify).
- Dalga 1 Stage 2 synthetic canary önkoşulu `RENDER_ENV_BEFORE_DEPLOY=true`
  rehearsal'ı kalıcılaşır.
- Container-side Spring Cloud Vault client aktive olur
  (`/actuator/health/vault` UP).

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

**Ortam:** `stage` (ai.acik.com)
**Vault auth mount:** `auth/approle`
**KV mount:** `secret` (KV v2)

**Etkilenen path'ler (scope split — 2026-04-18 OI-02 post-mortem):**

AppRole `backend-deploy-stage` **iki farklı consumer** tarafından kullanılır:
host-side deploy render ve container-side runtime Vault client. Policy her
iki scope'u da kapsar.

**Host render scope (deploy-time):**
- `secret/data/stage/backend-deploy/config` — deploy config (GIT_REMOTE_URL, GHCR_OWNER, vs.)

**Runtime Vault consumer scope (auth-service + permission-service Spring Cloud Vault):**
- `secret/data/stage/jwt/auth-service` — JWT signing keys (auth-service)
- `secret/data/stage/db/auth-service` — auth DB creds
- `secret/data/stage/db/user-service` — user DB creds
- `secret/data/stage/db/permission-service` — permission DB creds
- `secret/data/stage/db/variant-service` — variant DB creds
- `secret/metadata/stage/db/*` — list capability
- `secret/metadata/stage/jwt/*` — list capability

**AppRole role paths:**
- `auth/approle/role/backend-deploy-stage/role-id` (read)
- `auth/approle/role/backend-deploy-stage/secret-id` (update)

**Host filesystem:**
- `/home/halil/platform/env/backend.env`
- `/home/halil/platform/state/vault/approle/backend-deploy-stage.{role-id,secret-id}`

**Policy source of truth:** `backend/infra/vault/policies/backend-deploy-runtime.hcl`
(PR #13 seed script refactor ile canonical). Seed heredoc eliminated to
prevent 2026-04-18 drift class recurrence.

**İlgili entry point'ler:**
- `backend/scripts/vault/seed-stage-approle.sh` (yeni — bu runbook ile birlikte commit)
- `backend/scripts/vault/write-backend-deploy-stage.sh` (PR #3c AppRole-first payload)
- `backend/scripts/vault/check-backend-deploy-stage.sh` (PR #3c required_keys AppRole-first)
- `backend/scripts/vault/materialize-backend-deploy-approle.sh` (role-id + secret-id dosya yazımı)
- `deploy/ubuntu/render-backend-env.sh` + `render-backend-env-approle.sh`
- `deploy/ubuntu/deploy-backend.sh` (PR #3c AppRole precedence guard)
- `.github/workflows/deploy-backend.yml` (PR #3d soft-fail guard)

**Kapsam dışı:**
- Production Vault setup (bu runbook sadece staging)
- Cloud KMS auto-unseal (RB-vault-kms-autounseal)
- Full Vault dev-path migration (RB-vault-dev-path-migration)

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

### BAŞLATMA — AppRole setup (ssh staging-sw, tek session)

#### Preflight

```bash
ssh staging-sw '
  set -euo pipefail
  # Root token dosya path
  ROOT_TOKEN_FILE=/home/halil/platform/state/vault-dev/vault-root-token
  [ -f "$ROOT_TOKEN_FILE" ] || { echo "root token dosyası eksik: $ROOT_TOKEN_FILE" >&2; exit 1; }

  export VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
  export VAULT_TOKEN="$(cat "$ROOT_TOKEN_FILE")"

  docker exec platform-vault-1 vault status
  docker exec -e VAULT_ADDR=$VAULT_ADDR platform-vault-1 vault auth list
  docker exec -e VAULT_ADDR=$VAULT_ADDR platform-vault-1 vault secrets list
'
```

Beklenen:
- `Sealed false` (KMS auto-unseal veya manual unseal tamam)
- `auth list` → sadece `token/` mount görünüyor (AppRole YOK, bu beklenen başlangıç)
- `secrets list` → `secret/` KV v2 mevcut

#### Otomatik setup (tek komut)

```bash
ssh staging-sw '
  set -euo pipefail
  cd /home/halil/platform/repo
  export VAULT_ADDR="http://127.0.0.1:8200"
  export VAULT_TOKEN="$(cat /home/halil/platform/state/vault-dev/vault-root-token)"
  export ENV=stage
  bash backend/scripts/vault/seed-stage-approle.sh
'
```

Script adımları (idempotent):
- Step A: `auth/approle` mount enable (zaten varsa skip)
- Step B: Policy `backend-deploy-stage` yaz (KV read + AppRole secret-id update)
- Step C: Role `backend-deploy-stage` oluştur/update
- Step D: Role-id + secret-id üret
- Step E: `write-backend-deploy-stage.sh` invoke → KV'ye AppRole material + feature flag'ler
- Step F: Canonical env `/home/halil/platform/env/backend.env` update (atomic, backup)
- Step G: Verify — AppRole login + issued token ile role-id read → 200

#### Verify (manuel, setup sonrası)

```bash
ssh staging-sw '
  set -euo pipefail
  export VAULT_ADDR="http://127.0.0.1:8200"
  ROOT_TOKEN="$(cat /home/halil/platform/state/vault-dev/vault-root-token)"

  # Step A — AppRole enabled mı?
  docker exec -e VAULT_ADDR=$VAULT_ADDR platform-vault-1 \
    vault auth list | grep "^approle/"

  # Step B — Role detayı
  docker exec -e VAULT_ADDR=$VAULT_ADDR -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-1 \
    vault read auth/approle/role/backend-deploy-stage

  # Step C — Canonical env AppRole material non-blank
  grep -E "^(VAULT_ROLE_ID|VAULT_SECRET_ID|VAULT_AUTH_METHOD|SPRING_CLOUD_VAULT_ENABLED)=" \
    /home/halil/platform/env/backend.env \
    | sed "s/=\(.*\)/=<value>/"

  # Step D — KV config doğrulaması (check script AppRole-first required_keys)
  ENV=stage VAULT_ADDR=$VAULT_ADDR VAULT_TOKEN="$ROOT_TOKEN" \
    bash /home/halil/platform/repo/backend/scripts/vault/check-backend-deploy-stage.sh

  # Step E — AppRole login dry-run
  ROLE_ID="$(docker exec -e VAULT_ADDR=$VAULT_ADDR -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-1 \
    vault read -field=role_id auth/approle/role/backend-deploy-stage/role-id)"
  SECRET_ID="$(docker exec -e VAULT_ADDR=$VAULT_ADDR -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-1 \
    vault write -field=secret_id -f auth/approle/role/backend-deploy-stage/secret-id)"
  TOKEN="$(curl -sSf -H "Content-Type: application/json" \
    -X POST "$VAULT_ADDR/v1/auth/approle/login" \
    -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)[\"auth\"][\"client_token\"])")"
  curl -sS -o /dev/null -w "role-id read HTTP %{http_code}\n" \
    -H "X-Vault-Token: $TOKEN" \
    "$VAULT_ADDR/v1/auth/approle/role/backend-deploy-stage/role-id"
  # Beklenen: HTTP 200
'
```

#### Post-setup rehearsal

```bash
# Workflow dispatch ile AppRole path verify
gh workflow run deploy-backend.yml \
  -f env=stage \
  -f render_env_before_deploy=true \
  -f build_local=false \
  -f docker_pull_policy=always

# Beklenen log satırları:
# - "AppRole endpoint responded 200 (role configured, token authorized); normal rotation"
# - "render-backend-env-approle.sh" success
# - auth-service + permission-service container `SPRING_CLOUD_VAULT_ENABLED=true`
```

### DURDURMA — Rollback

#### Canonical env rollback

```bash
ssh staging-sw '
  # Script her çalıştırmada backup yazar: backend.env.bak-YYYYMMDDTHHMMSSZ
  ls -la /home/halil/platform/env/backend.env.bak-* | tail -5
  # En son pre-seed backup:
  LATEST_BAK="$(ls -1t /home/halil/platform/env/backend.env.bak-* | head -1)"
  cp "$LATEST_BAK" /home/halil/platform/env/backend.env
  chmod 600 /home/halil/platform/env/backend.env
'
```

#### AppRole role disable

```bash
ssh staging-sw '
  export VAULT_ADDR="http://127.0.0.1:8200"
  VAULT_TOKEN="$(cat /home/halil/platform/state/vault-dev/vault-root-token)"
  docker exec -e VAULT_ADDR=$VAULT_ADDR -e VAULT_TOKEN=$VAULT_TOKEN platform-vault-1 \
    vault delete auth/approle/role/backend-deploy-stage
  # Policy da kaldırılabilir (dikkat: başka rollarda paylaşılmıyor, stage-specific):
  # docker exec ... vault policy delete backend-deploy-stage
'
```

#### Workflow rollback

Emergency rollback: workflow_dispatch `render_env_before_deploy=false`:

```bash
gh workflow run deploy-backend.yml \
  -f env=stage \
  -f render_env_before_deploy=false
```

Bu, PR #3d soft-fail guard + token-path davranışı devreye sokar (canonical
env backup'taki eski VAULT_TOKEN kullanılır).

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

### Canlı smoke

```bash
ssh staging-sw '
  export VAULT_ADDR="http://127.0.0.1:8200"
  # auth/approle mount enable mı
  docker exec -e VAULT_ADDR=$VAULT_ADDR platform-vault-1 vault auth list | grep approle

  # Role read (root token gerekli)
  VAULT_TOKEN="$(cat /home/halil/platform/state/vault-dev/vault-root-token)" \
    docker exec -e VAULT_ADDR=$VAULT_ADDR -e VAULT_TOKEN=$VAULT_TOKEN platform-vault-1 \
    vault read auth/approle/role/backend-deploy-stage

  # Canonical env durumu
  grep -cE "^VAULT_(ROLE_ID|SECRET_ID|AUTH_METHOD)=" /home/halil/platform/env/backend.env
  # Beklenen: 3

  # Container Vault health (PR #3b actuator wiring)
  curl -fsS http://localhost:8088/actuator/health/vault | jq -r .status
  curl -fsS http://localhost:8090/actuator/health/vault | jq -r .status
  # Beklenen: "UP" her ikisi için
'
```

### Log observation

```bash
# Workflow run log
gh run view <RUN_ID> --log | grep -E "AppRole endpoint|secret-id|role-id|materialize"

# Container boot log (auth-service Vault client)
ssh staging-sw 'docker logs platform-auth-service-1 2>&1 | grep -iE "vault|located" | head -10'
```

### Metrikler

Bu runbook metric wiring eklemez. Vault sealed/unsealed state için
`RB-vault-kms-autounseal.md §4` Prometheus rule reference.

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

### AppRole mount endpoint 404

**Semptom:** `auth/approle/role/backend-deploy-stage/role-id` → 404.
**Kök neden:** `vault auth enable approle` çalışmadı veya başka path'e yazıldı.
**Çözüm:** `vault auth list` ile doğrula; yoksa `vault auth enable approle`
veya seed script'i tekrar çalıştır (idempotent).

### Runtime Vault consumer 403 (auth-service/permission-service)

**Semptom:** Container boot sırasında `org.springframework.vault.VaultException: Status 403 Forbidden [secret/data/stage/jwt/auth-service]`.
**Kök neden (2026-04-18 incident):** AppRole policy deploy-scope'ta (sadece
`backend-deploy/config` + `db/*`) kalmış, runtime path (`jwt/auth-service`)
dahil değil. Stale policy heredoc'tan kaynaklanıyor.
**Çözüm:**
- Policy source-of-truth PR #13 ile `backend/infra/vault/policies/backend-deploy-runtime.hcl`
  olarak kurulu; runtime path'ler dahil. Seed script re-run:
  ```bash
  ssh staging-sw '
    cd /home/halil/platform/repo
    export VAULT_ADDR="http://127.0.0.1:8200"
    export VAULT_TOKEN="$(cat /home/halil/platform/state/vault-dev/vault-root-token)"
    export ENV=stage
    bash backend/scripts/vault/seed-stage-approle.sh
  '
  ```
- Policy HCL'de `jwt/auth-service` read var mı doğrula:
  ```bash
  docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=... platform-vault-1 \
    vault policy read backend-deploy-stage | grep jwt
  ```
- AppRole login dry-run + jwt/auth-service kv read test (§3 Verify Step E benzeri)

### Runtime auth-service ephemeral RSA key (silent)

**Semptom:** Restart sonrası daha önce minted service token'lar 401.
**Kök neden (2026-04-18 incident):** PR #15 öncesi stage `backend/docker-compose.yml`
env var ismi `SERVICE_JWT_PRIVATE_KEY` idi ama `auth-service` application.properties
`AUTH_SERVICE_JWT_PRIVATE_KEY` okuyor. İsim uyuşmazlığı nedeniyle env IGNORE
ediliyor → boş değer → ephemeral RSA key generation.
**Çözüm (post PR #15):**
- `backend/docker-compose.yml` user + auth service env key `AUTH_SERVICE_JWT_*`
- `application-docker.properties` blank override kaldırıldı, env-aware fallback chain geri geldi
- Canonical env `/home/halil/platform/env/backend.env` `AUTH_SERVICE_JWT_PRIVATE_KEY` + `AUTH_SERVICE_JWT_PUBLIC_KEY` set
- Veya Spring Cloud Vault enabled + `secret/stage/jwt/auth-service` KV populated

### Secret-id expired

**Semptom:** AppRole login 403 + "invalid secret_id".
**Kök neden:** Secret-id TTL (default 768h / 32 gün) doldu veya num_uses limit.
**Çözüm:** Seed script'i re-run et — secret-id rotate edilir:
```bash
ssh staging-sw '
  cd /home/halil/platform/repo
  export VAULT_ADDR="http://127.0.0.1:8200"
  export VAULT_TOKEN="$(cat /home/halil/platform/state/vault-dev/vault-root-token)"
  export ENV=stage
  bash backend/scripts/vault/seed-stage-approle.sh
'
```

### Token leak (secret-id veya role-id)

**Semptom:** Unexpected secret-id kullanımı audit log'da görünür.
**Çözüm:**
- Eski secret-id'yi invalidate et:
  ```bash
  docker exec platform-vault-1 vault list auth/approle/role/backend-deploy-stage/secret-id
  # secret_id_accessor'ları listele
  docker exec platform-vault-1 vault write auth/approle/role/backend-deploy-stage/secret-id-accessor/destroy \
    secret_id_accessor="<accessor>"
  ```
- Yeni secret-id üret (seed script re-run)
- Canonical env + KV config yeniden yazılır

### Policy drift (Vault upgrade sonrası)

**Semptom:** `check-backend-deploy-stage.sh` FAIL + policy mismatch uyarısı.
**Çözüm:** `vault policy read backend-deploy-stage` ile HCL karşılaştır; seed
script `write_policy` fonksiyonu idempotent → re-run ile senkronize olur.

### Canonical env backup erişilemez

**Semptom:** Rollback sırasında `.bak-*` dosyası yok.
**Kök neden:** `seed-stage-approle.sh` backup `/home/halil/platform/env/`
dizininde; disk full veya permission issue.
**Çözüm:** Manuel canonical env restore — `backend/.env.prod.example` +
memory referanslarından re-build et, son 24h deploy log'unda VAULT_TOKEN
görünürse oradan rotate et.

### Render rehearsal fail

**Semptom:** `gh workflow run deploy-backend.yml -f render_env_before_deploy=true`
→ `render-backend-env-approle.sh` fail exit 22.
**Kök neden:**
- AppRole material canonical env'de yanlış yazıldı
- `VAULT_APPROLE_ROLE_NAME` env mismatch (default `backend-deploy-stage`)
- `deploy-backend.sh:150` token path'e düştü (AppRole precedence guard bozuldu)
**Çözüm:**
- Seed script verify section (§3 §Verify adım 5) AppRole login dry-run test
- `deploy-backend.sh:185-210` bootstrap_vault_credentials_from_env_file
  guard doğrulaması (`RENDER_ENV_BEFORE_DEPLOY=true` iken VAULT_TOKEN
  bootstrap skip)
- workflow VAULT_TOKEN step-level binding doğrulaması (`deploy-backend.yml:324`)

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

Acceptance checklist:

- [ ] `vault auth list` staging'de `approle/` mount görünüyor
- [ ] `vault read auth/approle/role/backend-deploy-stage` → role detayları
- [ ] Canonical env `VAULT_AUTH_METHOD=APPROLE` + `VAULT_ROLE_ID=<UUID>` +
  `VAULT_SECRET_ID=<UUID>` (sahte değil, gerçek Vault'tan)
- [ ] `check-backend-deploy-stage.sh` PASS (9 required key non-blank)
- [ ] AppRole login dry-run → issued token ile role-id read 200
- [ ] `gh workflow run deploy-backend.yml -f render_env_before_deploy=true`
  → "AppRole endpoint responded 200" log + container `SPRING_CLOUD_VAULT_ENABLED=true`
- [ ] auth-service + permission-service `/actuator/health/vault` UP
- [ ] `doctor-infra.sh` A-L PASS (post-deploy guard PR #4)

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Story: `docs/03-delivery/STORIES/STORY-0319-staging-prod-profile-migration.md`
- Canary runbook: `docs/04-operations/RUNBOOKS/RB-zanzibar-canary.md` §3.1.A pre-flight
- Staging prod-profile runbook: `docs/04-operations/RUNBOOKS/RB-staging-prod-profile.md`
- Vault dev-path migration: `docs/04-operations/RUNBOOKS/RB-vault-dev-path-migration.md`
- Vault KMS auto-unseal: `docs/04-operations/RUNBOOKS/RB-vault-kms-autounseal.md`
- Host-side AppRole (backend-deploy workflow): `docs/04-operations/RUNBOOKS/RB-ubuntu-backend-github-vault-deploy.md`
- Seed script: `backend/scripts/vault/seed-stage-approle.sh`
- Write script: `backend/scripts/vault/write-backend-deploy-stage.sh`
- Check script: `backend/scripts/vault/check-backend-deploy-stage.sh`
- Materialize script: `backend/scripts/vault/materialize-backend-deploy-approle.sh`
- Decision registry: `decisions/topics/zanzibar-openfga.v1.json` (D-001..D-008)
