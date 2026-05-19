# Runbook — D29 Test Persona Credential (Keycloak)

> board #819. Codex design consensus: thread `019e4012`.
>
> **Scope**: a disposable, least-privilege **normal** Keycloak user in the
> `platform-test` realm — a stable, non-interactive credential for D29 smoke /
> #754 M2, replacing the ad-hoc master-admin password-reset. **Authentication
> credential only** — D29 *data* authorization (OpenFGA explicit-scope) is a
> separate step (see §"Persona kontratı").
>
> **Roller**: 🧑 = operator (Vault seed, acceptance) · 🤖 = agent (kcadm apply + verify).
>
> **Realm**: `platform-test` ONLY — no prod path; the `serban` (prod) realm
> uses real users, never a smoke persona. The script rejects any other realm.

## Genel akış

```
🤖 1. setup-d29-test-persona.sh → platform-test: persona create + SECRET_OUT
🧑 2. SECRET_OUT'tan Vault seed → kv/platform/keycloak/d29-test-persona
🧑 3. SECRET_OUT shred
🤖 4. VERIFY_ONLY=1 read-back + acceptance checklist
```

## Persona kontratı

| Alan | Değer |
|---|---|
| Realm | `platform-test` |
| Username | `d29-test-persona` |
| Email | `d29-test-persona@testai.acik.com` |
| Roller | realm default rolleri — admin / realm-admin / create-realm **YOK** (least-privilege) |
| Auth yolu | mevcut `smoke-client` confidential client üzerinden password grant → normal-user JWT |
| Vault path | `kv/platform/keycloak/d29-test-persona` |
| Vault fields | `username`, `email`, `keycloak_user_id`, `password` |

**Kapsam sınırı (Codex `019e4012` #5) — authentication ≠ authorization:** bu
persona bir **kimlik doğrulama** credential'ıdır — D29'da `smoke-client`
password grant ile geçerli bir normal-user JWT üretir. **Veri yetkilendirmesi
ayrıdır**: D29 allow/deny kanıtı OpenFGA explicit-scope tuple'larına bağlıdır
(örn. `PROJECT:1204` + `VARIANTS_READ` — `docs/handoff-smoke-client-keycloak.md`).
Bu runbook tek başına "D29 Zanzibar-ready" **sağlamaz** — yalnız stabil,
non-interactive kimlik sağlar; scope seed ayrı iştir.

**Kimlik claim'i (Codex `019e4012` #3):** persona JWT'si standart Keycloak
claim'lerini taşır — `sub` = Keycloak kullanıcı UUID'si, `preferred_username`,
`email`. Vault'taki `keycloak_user_id` alanı bu **Keycloak UUID**'sidir. D29
OpenFGA explicit-scope seed'lerinin kullandığı **platform numeric `user_id`**
(örn. `docs/handoff-smoke-client-keycloak.md`'deki `user_id=2`) bundan
**ayrıdır** — backend `users` tablosunda ilk-login sync ile çözülür; bu
runbook onu formalize etmez.

## 🤖 ADIM 1 — Persona apply (`platform-test`)

staging-sw'de:
```bash
bash scripts/keycloak/setup-d29-test-persona.sh
```
Idempotent: persona yoksa oluşturur + parola üretir → `SECRET_OUT`; varsa yalnız
attribute converge eder — **parola değişmez** (Keycloak↔Vault drift önlenir).
Exit 0 = PASS · 1 = ERROR · 3 = VERIFY_FAILED.

## 🧑 ADIM 2 — Parola → Vault

Script parolayı **yalnız** `SECRET_OUT` dosyasına yazar (default
`/tmp/d29-test-persona-secret.txt`, `umask 077`) — stdout'a/log'a **asla**.
Operator staging-sw'de, `SECRET_OUT` içindeki değerlerle:
```bash
vault kv put kv/platform/keycloak/d29-test-persona \
  username=d29-test-persona \
  email=d29-test-persona@testai.acik.com \
  keycloak_user_id='<SECRET_OUT keycloak_user_id>' \
  password='<SECRET_OUT password>'
```

## 🧑 ADIM 3 — SECRET_OUT shred

```bash
shred -u /tmp/d29-test-persona-secret.txt   # veya: rm -P
```

## 🤖 ADIM 4 — Verify + acceptance checklist

```bash
VERIFY_ONLY=1 bash scripts/keycloak/setup-d29-test-persona.sh
```
read-back: persona `enabled` + `emailVerified` + admin/realm-admin/create-realm
rolü **YOK**. Exit 0 = PASS · 3 = VERIFY_FAILED.

**Acceptance checklist (Codex `019e4012` #6):**

- [ ] `admin@example.com` değişmedi — persona ayrı kullanıcı (script `admin` /
      `admin@example.com` username'ini reddeder).
- [ ] `d29-test-persona` normal user — realm-admin / admin / create-realm rolü yok.
- [ ] password grant token mint OK — `smoke-client` + `d29-test-persona`:
  ```bash
  curl -sk -X POST "https://testai.acik.com/realms/platform-test/protocol/openid-connect/token" \
    -d grant_type=password -d client_id=smoke-client \
    -d "client_secret=$(vault kv get -field=CLIENT_SECRET kv/platform/keycloak/smoke-client)" \
    -d "username=$(vault kv get -field=username kv/platform/keycloak/d29-test-persona)" \
    -d "password=$(vault kv get -field=password kv/platform/keycloak/d29-test-persona)" \
    | jq -r .access_token
  ```
- [ ] `/api/v1/authz/me` token ile `200` + beklenen identity (username/email).
- [ ] **(D29 data-allow — ayrı)** scoped allow `gridId=1204` → `200`, scope-dışı
      → `403`. Bu OpenFGA explicit-scope seed'ine bağlı — persona formalization
      kapsamı **dışı** (`docs/handoff-smoke-client-keycloak.md`).
- [ ] Vault path `kv/platform/keycloak/d29-test-persona` dolu; parola
      stdout/log'da yok; `SECRET_OUT` shred edildi.

## Rotation

Parola rotation **explicit** — normal re-run parolayı değiştirmez:
```bash
ROTATE_D29_TEST_PERSONA_PASSWORD=1 bash scripts/keycloak/setup-d29-test-persona.sh
# → yeni parola SECRET_OUT'a yazılır → ADIM 2-3 tekrar (Vault re-seed + shred)
```
Tetik: sızıntı şüphesi, periyodik hijyen.

## Dispose

Persona disposable — gerektiğinde:
```bash
docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh delete \
  "users/<user_id>" -r platform-test
vault kv delete kv/platform/keycloak/d29-test-persona   # operator
```

## NE YAPMA

- ❌ Persona parolasını git'e / log'a / sohbete yazma — yalnız `SECRET_OUT` → Vault.
- ❌ `admin@example.com` veya `admin` kullanıcısına dokunma — script reddeder; persona ayrı kullanıcı.
- ❌ Persona'ya realm-admin / admin / `manage-users` rolü verme — least-privilege; normal user kalır.
- ❌ `serban` (prod) realm'e uygulama — persona test-only; script `platform-test` dışını reddeder.
- ❌ Normal re-run'da parola rotation bekleme — rotation yalnız `ROTATE_D29_TEST_PERSONA_PASSWORD=1`.
- ❌ Bu persona ile tek başına "D29 Zanzibar-ready" iddia etme — authentication ≠ authorization; OpenFGA scope seed ayrı iş.

## Referanslar

- board #819 · Codex design thread `019e4012`
- `scripts/keycloak/setup-d29-test-persona.sh` — idempotent apply
- `docs/handoff-smoke-client-keycloak.md` — `smoke-client` confidential client + D29 numeric scope seed
- ADR-0010 §2.5 — Vault credential lifecycle / operator-agent authority matrix
- `docs/operations/RUNBOOKS/RB-m365-sso-broker.md` — sibling Keycloak setup-script runbook pattern
