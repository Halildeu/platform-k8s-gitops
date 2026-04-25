# RB-vault-dev-path-migration – Vault Dev Path Migration (staging/prod)

ID: RB-vault-dev-path-migration  
Service: vault-cluster  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `vault-unseal` sidecar bind mount'unu relative CI workdir'inden permanent
  `/home/halil/platform/state/vault-dev` path'ine taşımak ve staging'de
  sealed-loop regression'ını önlemek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Staging + prod sunucuları: `vault-unseal` sidecar çalıştıran ortamlar
  (self-hosted runner deploy flow'u).
- Local dev ETKİLENMEZ: compose default `./.vault-dev` korunur, `dev_init.sh`
  aynı şekilde çalışmaya devam eder.

Arka plan:

- Mevcut compose mount "./.vault-dev:/vault-dev:ro" relative path; compose
  dosyasının dizinine göre çözülür.
- Staging'de `deploy-stage-host` job (.github/workflows/deploy-backend.yml:334)
  `repo_dir="${GITHUB_WORKSPACE}"` kullanır → CI runner ephemeral workdir.
- Runner workdir temizlenip yeniden checkout yapıldığında bind inode stale olur;
  `dev_init.sh`'ın permanent repo'ya yazdığı unseal key container'a görünmez
  → vault sealed-loop.
- 2026-04-14 incident: Vault 2+ saat sealed; tactical fix olarak key manuel
  kopyalanıp vault-unseal restart edildi.
- Bu runbook kalıcı düzeltmeyi adım adım anlatır.

Fix — compose override pattern:

```yaml
volumes:
  - ${VAULT_DEV_PATH:-./.vault-dev}:/vault-dev:ro
```

- Local: env set edilmez → default `./.vault-dev`.
- Staging/prod: env'de `VAULT_DEV_PATH=/home/halil/platform/state/vault-dev`.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

3.1 Permanent state dir + key taşıma

```bash
ssh staging-sw
STATE_DIR=/home/halil/platform/state/vault-dev
REPO_SRC=/home/halil/platform/repo/backend/.vault-dev

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

cp "$REPO_SRC/vault-unseal-key" "$STATE_DIR/"
[ -f "$REPO_SRC/vault-init.json" ] && cp "$REPO_SRC/vault-init.json" "$STATE_DIR/"
[ -f "$REPO_SRC/vault-root-token" ] && cp "$REPO_SRC/vault-root-token" "$STATE_DIR/"

chmod 600 "$STATE_DIR"/*

# Doğrula (md5 eşleşmeli)
md5sum "$REPO_SRC/vault-unseal-key" "$STATE_DIR/vault-unseal-key"
```

3.2 Env file'a VAULT_DEV_PATH ekle

```bash
ENV_FILE=/home/halil/platform/env/backend.env

# Backup al
cp "$ENV_FILE" "$ENV_FILE.bak-$(date +%Y%m%d)-vault-dev-path"

# Satırı ekle (idempotent — grep ile check)
if ! grep -q '^VAULT_DEV_PATH=' "$ENV_FILE"; then
  cat >> "$ENV_FILE" <<'EOF'

# Vault dev state path — RB-vault-dev-path-migration
VAULT_DEV_PATH=/home/halil/platform/state/vault-dev
EOF
fi

grep VAULT_DEV_PATH "$ENV_FILE"
```

3.3 Deploy sonrası devreye alma

- Main'e merge → `deploy-stage-host` tetiklenir → compose yeni `VAULT_DEV_PATH`
  destekli sürüm dağıtılır.
- Deploy sırasında compose `up -d` otomatik `vault-unseal`'i recreate eder;
  mount `/home/halil/platform/state/vault-dev`'e döner.
- Manuel recreate (gerekirse):

```bash
ssh staging-sw
set -a; . /home/halil/platform/env/backend.env; set +a
cd /home/halil/platform/repo/backend  # ya da runner workdir — compose aynı sonucu verir
docker compose up -d --force-recreate vault-unseal
```

3.4 Durdurma (rollback için — bkz. §5)

- vault-unseal container'ı durdurmak **Vault'u etkilemez** (zaten unsealed
  kalır). Sadece restart sonrası unseal otomatiği devre dışı olur.
- Vault container'ı kendisi durdurmak kullanıcı trafiğini keser (auth/secret
  okumaları başarısız) — production'da yapılmaz.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

4.1 Mount doğrulama

```bash
docker inspect platform-vault-unseal-1 \
  --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}' \
  | grep vault-dev
# Beklenen satır:
# /home/halil/platform/state/vault-dev -> /vault-dev
```

4.2 Vault seal status

```bash
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-1 vault status \
  | grep -E 'Sealed|Initialized'
# Beklenen:
#   Initialized    true
#   Sealed         false
```

4.3 vault-unseal sidecar log

```bash
docker logs platform-vault-unseal-1 --tail 5
# Beklenen son satır: "[vault-unseal] OK: unsealed"
```

4.4 Healthcheck trend

```bash
# Son 5 healthcheck exit code'u (0=pass)
docker inspect platform-vault-1 \
  --format '{{range .State.Health.Log}}{{.ExitCode}} {{end}}'
```

4.5 İlgili metrikler

- Prometheus: `vault_core_unsealed` gauge (1 = unsealed, 0 = sealed)
- Grafana: Vault dashboard panel "Seal Status" (authz-zanzibar-rules.yml
  referansı)

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

5.1 Deploy sonrası vault sealed-loop devam ediyor

Tespit:
- `docker logs platform-vault-unseal-1 --tail 5` → "SKIP: unseal key not found"
- Mount `/home/halil/platform/state/vault-dev` YERINE CI workdir gösteriyor

Çözüm adımları:

- Env var set mi kontrol: `grep VAULT_DEV_PATH /home/halil/platform/env/backend.env`
- Compose'un env'i okuyup okumadığını doğrula:
  ```bash
  docker compose --env-file /home/halil/platform/env/backend.env \
    -f /home/halil/platform/repo/backend/docker-compose.yml config | grep -A1 vault-dev
  ```
- Beklenen değil ise: `docker compose up -d --force-recreate vault-unseal vault`
- Hala başarısız: §5.3 tactical fix

5.2 Healthcheck false-positive (service-manager)

IPv4/IPv6 localhost resolution bug (fix bu migration PR'ında, compose
healthcheck `127.0.0.1` açık). Deploy sonrası otomatik çözülür.

5.3 Tactical hotfix (acil durum, deploy yoksa)

Sealed vault acil unseal (compose fix deploy olmadan):

```bash
# Key'i runner workdir'in .vault-dev'ine manuel kopyala
RUNNER_VD=/home/halil/actions-runner-stage/_work/platform-ssot/platform-ssot/backend/.vault-dev
mkdir -p "$RUNNER_VD"
cp /home/halil/platform/state/vault-dev/vault-unseal-key "$RUNNER_VD/"
docker restart platform-vault-unseal-1
# 10-20s sonra vault status ile doğrula
```

5.4 Rollback (migration'dan dön)

```bash
ENV_FILE=/home/halil/platform/env/backend.env

# Adım A. VAULT_DEV_PATH'i yorumla
sed -i 's/^VAULT_DEV_PATH=/#VAULT_DEV_PATH=/' "$ENV_FILE"

# Adım B. Eski permanent repo yolundaki key'i geri koy
#   (silmemişseniz hala duruyor: /home/halil/platform/repo/backend/.vault-dev/vault-unseal-key)

# Adım C. Recreate
source "$ENV_FILE"
docker compose up -d --force-recreate vault-unseal
```

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Compose mount artık `VAULT_DEV_PATH` env-overridable (`${VAULT_DEV_PATH:-./.vault-dev}`).
- Local dev: sıfır değişiklik (default relative).
- Staging: permanent `/home/halil/platform/state/vault-dev` kullanılır — CI
  runner workdir'inden bağımsız.
- Service-manager healthcheck `localhost` → `127.0.0.1` (IPv6/IPv4 false-positive
  düzeltmesi).
- Doğrulama: §4 komutları ile mount, seal status ve unseal log kontrol edilir.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- `backend/docker-compose.yml` vault-unseal volumes + service-manager healthcheck
- `.github/workflows/deploy-backend.yml` line ~334 (deploy-stage-host repo_dir)
- `backend/scripts/vault/dev_init.sh` (local dev init — değişmedi)
- `.claude/plans/session-plan-20260415-zanzibar-next.md` (P0.5a migration)
- `docs/04-operations/RUNBOOKS/RB-vault.md` (vault operasyon genel runbook)
