# RB-production-cutover-checklist – Production Promote Checklist

ID: RB-production-cutover-checklist
Service: production-cutover
Status: Draft
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Stage'de doğrulanmış backend ve deploy zincirini production'a kontrollü taşımak.
- Secret source of truth olarak Vault'u korumak.
- DNS, TLS, reverse proxy ve frontend bağımlılıklarını tek operasyon checklist'inde toplamak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Bu runbook production backend promote, production frontend publish ve public açılış öncesi kontrol noktalarını kapsar.
- Kapsama dahil ana akışlar:
  - `secret/prod/backend-deploy/config` ve ilişkili prod Vault path'leri
  - GitHub `prod` environment ve deploy secret sync hattı
  - Prod hostta AppRole materialization, env render ve deploy
  - `ai.acik.com` için public DNS, TLS ve reverse proxy hazırlığı
  - Frontend publish, public smoke ve rollback kapısı
- Başlamadan önce aşağıdakiler zaten yeşil olmalıdır:
  - stage backend deploy PASS
  - stage post-deploy validate PASS
  - son iyi release tag'i ve rollback yolu biliniyor

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

Production promote adımları:

- Vault hazırlığı:
  - [ ] `secret/prod/backend-deploy/config`
  - [ ] `secret/prod/ops/github/backend-deploy`
  - [ ] `secret/prod/db/auth-service`
  - [ ] `secret/prod/db/user-service`
  - [ ] `secret/prod/db/permission-service`
  - [ ] `secret/prod/db/variant-service`
  - [ ] `secret/prod/jwt/auth-service`
- `backend-deploy/config` içinde zorunlu anahtarlar doğrulandı:
  - [ ] `GIT_REMOTE_URL`
  - [ ] `REPO_BRANCH`
  - [ ] `GHCR_OWNER`
  - [ ] `GHCR_USERNAME`
  - [ ] `GHCR_TOKEN`
  - [ ] `VAULT_URI`
  - [ ] `VAULT_TOKEN`
  - [ ] `KEYCLOAK_ISSUER_URI`
  - [ ] `KEYCLOAK_JWKS_URI`
  - [ ] `AUTH_VERIFICATION_BASE_URL`
  - [ ] `AUTH_RESET_BASE_URL`
  - [ ] `SERVICE_CLIENT_USER_SERVICE_SECRET`
  - [ ] `PERMISSION_SERVICE_INTERNAL_API_KEY`
  - [ ] `POSTGRES_USER`
  - [ ] `POSTGRES_PASSWORD`
  - [ ] `OPENFGA_STORE_ID`
  - [ ] `OPENFGA_MODEL_ID`
  - [ ] `CORE_DATA_DB_URL`
  - [ ] `CORE_DATA_DB_USERNAME`
  - [ ] `CORE_DATA_DB_PASSWORD`
- Prod GitHub environment hazırlığı:
  - [ ] `prod` environment mevcut
  - [ ] `vault-secrets-sync.yml` `mode=backend-deploy`, `env=prod`, `secret_scope=environment`, `github_environment=prod`, `dry_run=true`
  - [ ] aynı workflow `dry_run=false`
  - [ ] `BACKEND_SSH_DEPLOY_ENABLED`
  - [ ] `BACKEND_DEPLOY_SSH_HOST` yalnız push-based prod seçildiyse
  - [ ] `BACKEND_DEPLOY_SSH_PORT` yalnız push-based prod seçildiyse
  - [ ] `BACKEND_DEPLOY_SSH_USER` yalnız push-based prod seçildiyse
  - [ ] `BACKEND_DEPLOY_SSH_KEY` yalnız push-based prod seçildiyse
  - [ ] `BACKEND_DEPLOY_SSH_KNOWN_HOSTS` yalnız push-based prod seçildiyse
  - [ ] `BACKEND_DEPLOY_REMOTE_ENV_FILE`
  - [ ] `BACKEND_DEPLOY_REMOTE_REPO_DIR`
  - [ ] `BACKEND_DEPLOY_REMOTE_COMPOSE_PROFILES`
  - [ ] `BACKEND_HEALTH_URLS`
- Prod host hazırlığı:
  - [ ] `/home/halil/platform/repo`
  - [ ] `/home/halil/platform/env/backend.env.prod`
  - [ ] `/home/halil/platform/state/vault/approle/backend-deploy-prod.role-id`
  - [ ] `/home/halil/platform/state/vault/approle/backend-deploy-prod.secret-id`
  - [ ] `backend/scripts/vault/materialize-backend-deploy-approle.sh`
  - [ ] `deploy/ubuntu/render-backend-env-approle.sh`
  - [ ] `deploy/ubuntu/pull-promote-backend.sh`
  - [ ] pull-based model seçildiyse host cron/systemd timer kuruldu
  - [ ] `docker compose -f backend/docker-compose.prod.yml config --services`
- Deploy ve durdurma akışı:
  - [ ] `deploy-backend.yml` workflow_dispatch `env=prod`
  - [ ] push-based yerine pull-based model seçildiyse workflow yalnız GHCR publish için kullanılıyor
  - [ ] host tarafında `pull-promote-backend.sh` en az bir kez başarıyla çalıştı
  - [ ] rollback gerekiyorsa `rollback.yml` workflow_dispatch `env=prod`, `confirm=ROLLBACK`

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

Production gözlemleme ve doğrulama kapıları:

- Vault tarafı:
  - [ ] `backend/scripts/vault/check-backend-deploy-prod.sh` PASS
  - [ ] stage/prod farkları gerektiğinde `backend/scripts/vault/check-backend-deploy-stage.sh` ile karşılaştırıldı
- Public edge:
  - [ ] `ai.acik.com -> 212.115.26.190` DNS A kaydı (inbound edge IP; outbound NAT: 31.145.18.18)
  - [ ] `Host: ai.acik.com` için binding, vhost veya route tanımlı
  - [ ] hedef backend `10.9.10.53:8082` veya production iç hedef
  - [ ] TLS sertifikası aktif
  - [ ] `dig ai.acik.com` beklenen IP'yi döndürüyor
  - [ ] `curl -I https://ai.acik.com` HTTP cevap veriyor
- Frontend:
  - [ ] static hosting prod publish tamam
  - [ ] shell ve remote URL'leri prod domainlerle hizalı
  - [ ] gateway URL kararı net
  - [ ] Keycloak redirect ve origin ayarları prod domainlerle uyumlu
- Uygulama doğrulaması:
  - [ ] `post-deploy-validate.yml` workflow_dispatch `env=prod`, `target=backend`
  - [ ] frontend hazırsa `target=all`
  - [ ] backend health PASS
  - [ ] login, token ve protected endpoint PASS
  - [ ] frontend -> gateway -> backend zinciri PASS

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

Sık görülen production promote arızaları ve ilk adımlar:

- Vault check FAIL:
  - `secret/prod/backend-deploy/config` içindeki zorunlu anahtarlar eksik olabilir.
  - `check-backend-deploy-prod.sh` ile eksik key listesini yeniden üret.
- GitHub environment sync FAIL:
  - `secret/prod/ops/github/backend-deploy` path'ini ve `github_environment=prod` parametresini kontrol et.
  - Gerekirse önce `dry_run=true` ile yeniden doğrula.
- Host render FAIL:
  - AppRole dosyalarının varlığını ve `render-backend-env-approle.sh` çıktısını kontrol et.
  - Prod `backend.env` render edilmeden deploy başlatma.
- Public domain yanlış siteye düşüyor:
  - Edge üzerinde `Host: ai.acik.com` binding'i eksik veya yanlış hedefe gidiyor olabilir.
  - DNS doğru olsa bile vhost veya route ayrı doğrulanmalıdır.
- Frontend çalışıyor ama auth kırık:
  - Keycloak issuer, JWKS, redirect URI ve web origin ayarlarını prod domainlerle yeniden hizala.
- Deploy sonrası servis health FAIL:
  - `post-deploy-validate.yml` ile backend doğrulamasını tekrar çalıştır.
  - Gerekirse `rollback.yml` `env=prod` ile son iyi release'e dön.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Production canlı sayılması için şu kapılar birlikte yeşil olmalıdır:
  - [ ] prod Vault PASS
  - [ ] prod GitHub environment PASS
  - [ ] prod host render ve deploy PASS
  - [ ] domain ve TLS canlı
  - [ ] frontend canlı
  - [ ] public smoke PASS
  - [ ] rollback yolu doğrulanmış
- Bu checklist tamamlanmadan public production açılışı yapılmamalıdır.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- `deploy/ubuntu/README.md`
- `docs/04-operations/RUNBOOKS/RB-ubuntu-backend-github-vault-deploy.md`
- `docs/OPERATIONS/prod-vault-key-matrix.v1.json`
- `docs/OPERATIONS/prod-github-environment-secret-map.v1.json`
- `docs/OPERATIONS/prod-public-edge-map.v1.json`
- `deploy/ubuntu/Caddyfile.ai-acik.com.example`
- `.github/workflows/deploy-backend.yml`
- `.github/workflows/post-deploy-validate.yml`
- `.github/workflows/rollback.yml`
- `.github/workflows/vault-secrets-sync.yml`
- `backend/.env.prod.example`
- `backend/docker-compose.prod.yml`
