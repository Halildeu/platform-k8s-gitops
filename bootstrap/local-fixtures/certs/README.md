# Local Dev Fixtures — Certs

> ⚠️ **NOT_FOR_PROD — fake credentials, dev-only, git'e committed**
> Bu PEM dosyaları sadece Mac developer machine `k3d-dev` cluster için deterministic
> seed sağlar. Prod/test Vault'tan GELEN gerçek key'lerle hiçbir ilgisi yoktur.
> Bu key'ler herhangi bir üretim JWT'sini imzalamak için kullanılamaz.

## Dosyalar

- `jwt-signing.pem` — Fake RSA 2048 private key (auth-service JWT signing için)
- `jwt-public.pem` — Fake RSA public key (token verification)

## Regenerate (nadir — key pattern değişirse)

```bash
cd bootstrap/local-fixtures/certs
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out jwt-signing.pem
openssl pkey -pubout -in jwt-signing.pem -out jwt-public.pem
```

## Neden git'te?

Faz 17.1 deliverable — Codex iter-1 RED #2 absorb kararıyla **fixture deterministic**
olmalı (token deterministic değil). Her geliştiricinin kendi key'ini üretmesi
drift yaratır (signature doğrulama kolektif kırılır). Key **fake** olduğu için
git'te zararsız.

Vault dev-mode opsiyonel `full` profile'da: `export VAULT_TOKEN=dev-root-token`
script/env seviyesinde kalır — **asla git'e commit edilmez** (Codex kuralı).
