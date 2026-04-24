# Local Dev Fixtures (Faz 17.1)

> ⚠️ **NOT_FOR_PROD — tüm içerik fake credentials, dev-only, deterministic**
>
> Bu dizin sadece Mac developer machine `k3d-dev` cluster için deterministic
> seed sağlar. **Hiçbir dosya gerçek secret içermez**. Prod/test Vault'tan
> GELEN gerçek key'lerle hiçbir ilgisi yoktur.

## Dizin Yapısı

```
bootstrap/local-fixtures/
├── README.md                     ← bu dosya
├── certs/
│   ├── README.md                 ← openssl regenerate talimatı
│   ├── jwt-signing.pem           ← fake RSA 2048 private (auth-service JWT)
│   └── jwt-public.pem            ← public key (verification)
├── keycloak/
│   └── dev-local-realm.json      ← KC realm `dev-local`: 2 user + 2 client
├── openfga/
│   └── tuples.json               ← Zanzibar tuple fixtures (scope-aware seed)
└── postgres/
    └── seed-dev.sql              ← 4 PG DB seed (auth + user + permission + reports)
```

## Kullanım

### Otomatik (dev-seed.sh — Faz 17.3)

```bash
./scripts/dev-seed.sh --profile zanzibar-min
# Tüm fixture'ları cluster'a yükler (KC realm import, PG seed, OpenFGA tuple write)
```

### Manuel (debug)

```bash
# 1. KC realm import
curl -X POST http://app.localtest.me:8081/admin/realms \
  -H "Authorization: Bearer $KC_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d @bootstrap/local-fixtures/keycloak/dev-local-realm.json

# 2. PG seed (via postgres host-bridge)
docker exec -i platform-dev-postgres psql -U platform < bootstrap/local-fixtures/postgres/seed-dev.sql

# 3. OpenFGA tuple write
for tuple in $(jq -c '.tuples[]' bootstrap/local-fixtures/openfga/tuples.json); do
  curl -X POST http://openfga.localtest.me/stores/$STORE_ID/write \
    -H "Content-Type: application/json" \
    -d "{\"writes\": {\"tuple_keys\": [$tuple]}}"
done
```

## Fake Credentials (tam liste)

| Fixture | Value | Purpose |
|---|---|---|
| `jwt-signing.pem` | RSA 2048 PEM | auth-service JWT imza (fake key, üretim değeri yok) |
| KC user `dev@localtest.me` password | `dev` | ADMIN login |
| KC user `viewer@localtest.me` password | `viewer` | VIEWER role (deny testleri için) |
| KC client `platform-gateway` secret | `dev-local-client-secret-NOT_FOR_PROD` | OIDC client |
| PG user | `platform` password `platform-dev-NOT_FOR_PROD` | PG connection (auth/user/permission/reports DB) |
| Vault (opsiyonel `full` profile) | `dev-root-token` | **NEVER git** — script env `export VAULT_TOKEN=...` |

## Codex AGREE Referansları

Bu klasörün tasarımı Codex thread `019dbe80` iter-4 AGREE bulgularını absorb eder:

- **iter-1 RED #2**: "Vault `-dev` + git'e root token kötü default" → absorb: fake
  fixtures deterministic git'te, token **per-dev env** (asla git'e)
- **iter-2 PARTIAL**: "profile render modeli" → absorb: fixtures profile-aware
  (authn-min KC realm + minimal user, zanzibar-min OpenFGA tuple)
- **iter-3 PARTIAL**: "unknown_float_class SEAL BLOCKER" (data contract) ile
  paralel: lokal fixtures deterministic, "unknown" value yasak

## Regenerate

### JWT keys (nadir — pattern değişirse)

```bash
cd bootstrap/local-fixtures/certs
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out jwt-signing.pem
openssl pkey -pubout -in jwt-signing.pem -out jwt-public.pem
```

### KC realm (yeni user/client eklenince)

JSON'u elle düzenle, `dev-up.sh` tekrar koş (idempotent import).

### OpenFGA tuples (yeni smoke check eklenince)

JSON'a satır ekle, `dev-seed.sh` tuple write tekrarla.

### PG seed

SQL'i düzenle, `dev-seed.sh` re-run (ON CONFLICT DO NOTHING idempotent).
