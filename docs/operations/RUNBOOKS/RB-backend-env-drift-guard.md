# RUNBOOK — Backend Env Drift Guard

ID: RB-backend-env-drift-guard
Service: all backend services (report-service focus)
Status: Active (PR #424, CNS-20260416-003)
Owner: @halil
Last updated: 2026-04-16

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

`deploy-backend` workflow'u iki ayrı env kaynağı kullanıyor ve aralarında
sessiz drift oluşabiliyor:

- **Repo**: `backend/.env` — geliştirici referansı, `docker-compose.yml`
  değişkenlerinin local doğrulaması.
- **Canonical (staging host)**: `/home/halil/platform/env/backend.env` —
  `deploy-backend.sh` `--env-file` olarak bunu kullanıyor
  (`BACKEND_DEPLOY_REMOTE_ENV_FILE`). Deploy workflow default'ta bu dosyayı
  *render etmiyor* (`RENDER_ENV_BEFORE_DEPLOY=false`). Yalnız AppRole
  credentials refresh oluyor.

İki dosya arasındaki profile/ID/issuer drift'i post-deploy'da sessiz deny
yaratıyor:

- `REPORT_SERVICE_PROFILES` canonical'de yoksa → `local,docker` → SecurityConfigLocal permitAll.
- `ERP_OPENFGA_STORE_ID/MODEL_ID` canonical'de yoksa → OpenFgaAuthzService disabled → `/api/v1/reports` herkese boş liste (PR6c-1 regresyonu).
- `SECURITY_JWT_ISSUER(S)` `ai.acik.com`'u içermiyorsa → prod token'lar 401.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- **Sorumlu:** Platform Engineering (deploy ops), @halil (owner).
- **Ortamlar:** stage (öncelikli), prod (adopte edilecek).
- **Servisler:** report-service (asıl hedef), diğer backend servisler (spring profile çapraz kontrol).
- **Tetikleyici:** Her `deploy-backend` workflow çalışması sonrası manuel doctor run. İleride otomatik post-deploy entegrasyon planlı (bölüm 5).
- **Başarı kriteri:** `doctor-infra.sh` exit 0 (L1-L8 PASS).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

Drift guard ayrı bir servis değil — `doctor-infra.sh` L-section olarak mevcut.
Her deploy sonrası manuel çalıştırılır; ileride otomatik post-deploy trigger
planlı (bkz. §5).

### Tespit — doctor-infra.sh L3-L8

`backend/scripts/doctor-infra.sh` L-section'ı artık drift'i yakalıyor
(PR #424):

| Check | Kriter | Sonuç |
|---|---|---|
| L1 | 7 servis `SPRING_PROFILES_ACTIVE` içinde `local` yok | FAIL: canary sahte yeşil |
| L2 | Token'sız `/authz/check` → 401/403 | FAIL: permitAll aktif |
| **L3** | report-service `ERP_OPENFGA_ENABLED` set | FAIL: resolver disabled |
| **L4** | report-service `ERP_OPENFGA_STORE_ID` dolu | FAIL: store id empty |
| **L5** | report-service `ERP_OPENFGA_MODEL_ID` dolu | FAIL: model id empty |
| **L6** | report-service `PERMISSION_SERVICE_BASE_URL` set | FAIL: version polling kırık |
| **L7** | report-service `AUTHZ_USER_TABLE` set | FAIL: user lookup table missing |
| **L8** | report-service `SECURITY_JWT_ISSUER(S)` ai.acik.com içeriyor | FAIL: prod tokens 401 |

**Çalıştırma:**
```bash
ssh staging-sw
bash /home/halil/platform/repo/backend/scripts/doctor-infra.sh
# veya hızlı:
bash /home/halil/platform/repo/backend/scripts/doctor-infra.sh --quick
```

Exit 0 → drift yok. Exit 1 → drift var, müdahale gerekli.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

### Canonical env sync (drift düzeltme)

Drift tespit edilirse canonical env'i repo `.env` ile hizala:

```bash
ssh staging-sw

# Step A — Backup al
cp /home/halil/platform/env/backend.env \
   /home/halil/platform/env/backend.env.bak-$(date +%Y%m%d-%H%M%S)

# Step B — Eksik entry'leri ekle (repo .env'den kopyala)
grep -E "^(USER_SERVICE_PROFILES|AUTH_SERVICE_PROFILES|VARIANT_SERVICE_PROFILES|CORE_DATA_SERVICE_PROFILES|API_GATEWAY_PROFILES|PERMISSION_SERVICE_PROFILES|REPORT_SERVICE_PROFILES|ERP_OPENFGA_ENABLED|ERP_OPENFGA_STORE_ID|ERP_OPENFGA_MODEL_ID|SECURITY_JWT_ISSUER|SECURITY_JWT_ISSUERS)=" \
    /home/halil/platform/repo/backend/.env \
    >> /home/halil/platform/env/backend.env

# Step C — Container'ları env'den yeniden başlat
cd /home/halil/platform/repo/backend
docker compose up -d --force-recreate

# Step D — Vault unseal (recreate sonrası sealed gelir)
UNSEAL=$(cat /home/halil/platform/state/vault-dev/vault-unseal-key)
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-1 \
    vault operator unseal "$UNSEAL"

# Step E — Dependent servisleri tekrar başlat (Vault healthy olduktan sonra)
docker compose up -d auth-service user-service permission-service api-gateway

# Step F — Doğrula
bash /home/halil/platform/repo/backend/scripts/doctor-infra.sh
```

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

### Deploy zincirine entegrasyon (gelecek iş)

**Şu an:** `doctor-infra.sh` manuel çalıştırılıyor. Post-deploy health check
(`deploy/ubuntu/post-deploy-health-check.sh`) yalnız container sağlığı kontrolü
yapıyor; config drift'i yakalamıyor.

**Hedef (PR #425 veya follow-up):**
- `deploy-backend.sh` `main()` sonunda `doctor-infra.sh --post-deploy` çağır.
- Exit 1 → deploy FAIL (rollback trigger).
- Workflow annotation'la drift nedeni göster.

Alternatif: `RENDER_ENV_BEFORE_DEPLOY=true` açıp canonical env'i repo
template'inden üret (`backend.env.template` + envsubst). Drift imkânsız hale
gelir ama template maintenance ek iş.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- `/home/halil/platform/env/backend.env` (canonical) ile repo `backend/.env`
  arasında drift sessiz deny üretir.
- `doctor-infra.sh` L3-L8 bu drift'i fail-closed yakalar.
- Canlı sync prosedürü §4, deploy-chain entegrasyon planı §5.

### Köken

- **PR #422** (a5a4f389) report-service direct OpenFGA SDK migration. Deploy
  sonrası container'larda ERP_OPENFGA env yoktu → resolver disabled mode →
  `/reports` empty. İlk drift belirti.
- **PR #423** (29913194) compose yml fix (env forwarding). Compose `.env`
  okumasını düzeltti ama staging'de `.env` ≠ canonical olduğu için canlıda
  yeterli olmadı.
- **CNS-20260416-003** Codex 3 tur ping-pong review. Post-deploy round
  "sahte yeşil" riskini ve env SSOT bozukluğunu tespit etti.
- **PR #424** (bu PR): doctor-infra.sh L3-L8 drift guard + runbook.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Codex thread: `019d9688-233c-7c50-85f0-73ee5d106753` (CNS-20260416-003)
- Master plan Rev 23 §2 Dalga 3 — `.claude/plans/zanzibar-master-plan.md`
- STORY-0319 — `docs/03-delivery/STORIES/STORY-0319-staging-prod-profile-migration.md`
- Decision C-008 — `decisions/topics/zanzibar-openfga.v1.json`
- Handoff 2026-04-16 — `.claude/plans/session-handoff-20260416-zanzibar-dalga1-done.md`
