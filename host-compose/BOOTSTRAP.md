# Fresh Bootstrap Runbook — Host Compose Stateful (ADR-0002)

> **Scope:** Sıfırdan prod veya test stateful stack kurulumu
> **Prereq:** Docker 24+, sudo access, bind-mount dizinleri oluşturulmuş (bkz host-compose/README.md §1)
> **Output:** 3 healthy container (PG + KC + Vault) + credential zinciri tutarlı

## Credential Zinciri (KRİTİK — Codex PR #12 iter-1 blocker fix)

Fresh bootstrap'ta 3 bileşen BİRBİRİYLE EŞLENMİŞ credential kullanır:

```
1. PG init SQL → yaratır: platform, keycloak_user, openfga users (CHANGE_ME_<ENV>)
2. KC secret file → yazılır: kc_db_password.txt (PG'deki keycloak_user şifresi ile EŞİT olmak zorunda)
3. Vault seed → tutar: kv/platform/<svc>/db_password (PG'deki gerçek şifre ile EŞİT)
4. ESO sync → kopyalar: Vault → K8s Secret → Pod env
5. Deployment → kullanır: Secret'tan gelen username/password
```

**Herhangi bir adımda eşitlik kırılırsa → deployment crash.**

## Prod Bootstrap Sırası (Step-by-Step)

### Step 0 — Secret Generation (single source)
```bash
# 3 ayrı güçlü random password üret (yerel tek seferlik)
PG_PLATFORM_PW=$(openssl rand -base64 32)
PG_KC_PW=$(openssl rand -base64 32)
PG_OPENFGA_PW=$(openssl rand -base64 32)
VAULT_PLATFORM_PW="${PG_PLATFORM_PW}"    # same password, different user path
KC_ADMIN_PW=$(openssl rand -base64 24)

# SAKLA (Vault seed için gerekecek)
cat > /tmp/bootstrap-creds.env <<EOF
PG_PLATFORM_PW=${PG_PLATFORM_PW}
PG_KC_PW=${PG_KC_PW}
PG_OPENFGA_PW=${PG_OPENFGA_PW}
KC_ADMIN_PW=${KC_ADMIN_PW}
EOF
chmod 600 /tmp/bootstrap-creds.env
# NOT: Vault seed sonrası bu dosyayı SECURE WIPE et (shred -u)
```

### Step 1 — PG up + ALTER ROLE (init SQL placeholder → gerçek şifre)
```bash
# Secret dosyası PG (postgres super-user için — root password)
cd host-compose/postgres/prod
mkdir -p secrets
PG_ROOT_PW=$(openssl rand -base64 32)
echo "${PG_ROOT_PW}" > secrets/pg_password.txt
chmod 600 secrets/pg_password.txt

# Compose up (init SQL CHANGE_ME_PROD placeholder ile role + DB yaratır)
docker compose up -d

# Wait PG ready
until docker exec platform-pg-prod pg_isready -U postgres; do sleep 2; done

# KRİTİK: Placeholder şifreleri gerçekleriyle değiştir (ALTER ROLE)
source /tmp/bootstrap-creds.env
docker exec -i platform-pg-prod psql -U postgres <<SQL
ALTER ROLE platform WITH PASSWORD '${PG_PLATFORM_PW}';
ALTER ROLE keycloak_user WITH PASSWORD '${PG_KC_PW}';
ALTER ROLE openfga WITH PASSWORD '${PG_OPENFGA_PW}';
SQL

# Doğrulama (login test)
docker exec -e PGPASSWORD="${PG_PLATFORM_PW}" platform-pg-prod \
  psql -h 127.0.0.1 -U platform -d auth_db -c 'SELECT 1'
# Beklenen: 1 row — PASS
```

### Step 2 — Keycloak secret → Compose up
```bash
cd ../../keycloak/prod
mkdir -p secrets
source /tmp/bootstrap-creds.env
echo "${PG_KC_PW}" > secrets/kc_db_password.txt       # PG'deki keycloak_user ile EŞİT
echo "${KC_ADMIN_PW}" > secrets/kc_admin_password.txt
chmod 600 secrets/*.txt

docker compose up -d

# Wait healthy (PG'ye bağlanır, realm schema migrate eder)
until docker exec platform-kc-prod curl -sf http://localhost:8080/health/ready; do sleep 5; done
```

### Step 3 — Vault up + operator init + seed
```bash
cd ../../vault/prod
docker compose up -d

# Operator init (5 key shares, 3 threshold)
docker exec platform-vault-prod vault operator init -key-shares=5 -key-threshold=3 > /tmp/vault-init-prod.txt
# KRİTİK: Bu dosyayı güvenli yere taşı (backup/offsite)
chmod 600 /tmp/vault-init-prod.txt

# Unseal (3/5 key)
KEY1=$(grep 'Unseal Key 1:' /tmp/vault-init-prod.txt | awk '{print $NF}')
KEY2=$(grep 'Unseal Key 2:' /tmp/vault-init-prod.txt | awk '{print $NF}')
KEY3=$(grep 'Unseal Key 3:' /tmp/vault-init-prod.txt | awk '{print $NF}')
docker exec platform-vault-prod vault operator unseal "${KEY1}"
docker exec platform-vault-prod vault operator unseal "${KEY2}"
docker exec platform-vault-prod vault operator unseal "${KEY3}"

# Login + KV + policy + AppRole
ROOT_TOKEN=$(grep 'Initial Root Token:' /tmp/vault-init-prod.txt | awk '{print $NF}')
export VAULT_ADDR=http://localhost:8200
export VAULT_TOKEN=${ROOT_TOKEN}

vault secrets enable -version=2 -path=kv kv
vault audit enable -path=file_audit file file_path=/vault/logs/audit.log

# Policy (canonical: eso-runtime)
# Mevcut repo path: bootstrap/vault-policies/eso-runtime.hcl (düz)
# PR-next-3 sonrası {common,prod,test}/ refactor gelecek; o zaman prod/eso-runtime.hcl olacak
cd ../../../bootstrap/vault-policies
vault policy write eso-runtime eso-runtime.hcl
vault auth enable approle
vault write auth/approle/role/eso-runtime \
  token_policies=eso-runtime \
  token_ttl=1h token_max_ttl=24h

# KRİTİK: Seed Vault with ACTUAL credentials (Step 0'da üretilenler)
source /tmp/bootstrap-creds.env
for svc in auth-service user-service variant-service core-data-service report-service schema-service permission-service; do
  vault kv put "kv/platform/${svc}" \
    db_username=platform \
    db_password="${PG_PLATFORM_PW}" \
    keycloak_client_secret="PLACEHOLDER_ROTATE_VIA_KC_ADMIN" \
    internal_api_key="$(openssl rand -base64 32)"
done

# Auth-service JWT pair (manuel generate)
openssl genrsa -out /tmp/jwt-priv.pem 2048
openssl rsa -in /tmp/jwt-priv.pem -pubout -out /tmp/jwt-pub.pem
vault kv put kv/platform/auth-service \
  db_username=platform \
  db_password="${PG_PLATFORM_PW}" \
  jwt_private_key="$(cat /tmp/jwt-priv.pem)" \
  jwt_public_key="$(cat /tmp/jwt-pub.pem)" \
  keycloak_client_secret="PLACEHOLDER" \
  internal_api_key="$(openssl rand -base64 32)"
shred -u /tmp/jwt-priv.pem /tmp/jwt-pub.pem

# OpenFGA (placeholder — OpenFGA install sonrası gerçek store/model)
vault kv put kv/platform/openfga store_id=placeholder model_id=placeholder

# GHCR pull token
vault kv put kv/gitops/ghcr-token username=halildeu password="${GHCR_READ_PAT}"

# AppRole secret-id generate + K8s Secret
vault write -f auth/approle/role/eso-runtime/secret-id > /tmp/approle-secret-id.txt
SECRET_ID=$(grep 'secret_id ' /tmp/approle-secret-id.txt | awk '{print $NF}')
kubectl --context k3d-prod -n external-secrets create secret generic \
  vault-approle-secret --from-literal=secret-id="${SECRET_ID}"

# role-id oku (overlays/prod/eso/clustersecretstore-patch.yaml güncellemek için)
vault read auth/approle/role/eso-runtime/role-id
# → UUID commit et (prod OPS-PREREQ tamamlanır)
```

### Step 4 — Secure Wipe
```bash
# Bootstrap credential dosyasını SIL (Vault'ta güvenli saklandı)
shred -u /tmp/bootstrap-creds.env
shred -u /tmp/vault-init-prod.txt   # OPSİYONEL: offsite backup sonrası
shred -u /tmp/approle-secret-id.txt

# Vault login unset
unset VAULT_TOKEN
```

### Step 5 — Smoke
```bash
# PG connectivity
docker exec -e PGPASSWORD="${PG_PLATFORM_PW}" platform-pg-prod \
  psql -h 127.0.0.1 -U platform -d auth_db -c 'SELECT 1'

# KC realm discovery
curl http://localhost:8081/realms/serban/.well-known/openid-configuration | jq .issuer

# Vault health + ESO sync
curl http://localhost:8200/v1/sys/health
kubectl --context k3d-prod get clustersecretstore vault-platform-gitops
kubectl --context k3d-prod -n platform-prod get externalsecret

# 7 ES Synced=True beklenir
```

## Test Bootstrap Sırası

Prod ile aynı pattern, FARKLI secret values. Test credentials prod'dan BAĞIMSIZ (ADR-0002 §3.2 full isolation).

```bash
# Step 0-5 yukarıdakiyle aynı; test klasörü + test Vault + port 5433/8082/8201
cd host-compose/postgres/test
# ... aynı sıra
```

## Rotation (post-bootstrap)

- Vault AppRole secret-id: 30 gün prod / 14 gün test (day-2-governance §2.1)
- PG role passwords: Vault rotate + `ALTER ROLE` + rolling restart
- KC admin: çeyreklik
- JWT keys: yılda 1 (overlap window)

## Troubleshooting

**Symptom: `password authentication failed for user "postgres"`**
- Neden: Vault `db_password` ile PG gerçek şifresi eşleşmiyor
- Fix: Vault'tan Secret'ı re-fetch + `ALTER ROLE` çalıştır

**Symptom: KC startup fail `connection refused postgres:5432`**
- Neden: Startup order; KC PG hazır olmadan başlamış
- Fix: `restart: unless-stopped` 60s retry yapar; manuel `docker compose restart keycloak`

**Symptom: Vault ES `Ready=False` login 400**
- Neden: `roleId` base placeholder (literal "eso-runtime") overlay patch uygulanmadı
- Fix: overlays/<env>/eso/clustersecretstore-patch.yaml UUID patch kontrol

## Referanslar
- [ADR-0002 §3.2-3.6](../docs/adr/0002-single-host-dual-cluster.md) (stateful isolation)
- [host-compose/README.md](./README.md) (dizin yapı + izolasyon kontratı)
- [docs/S2-B1-vault-property-matrix.md](../docs/S2-B1-vault-property-matrix.md) (Vault path matrix)
- [docs/day-2-governance.md §1-2](../docs/day-2-governance.md) (backup + rotation)
