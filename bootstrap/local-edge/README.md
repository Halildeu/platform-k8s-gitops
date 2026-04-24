# Local Edge TLS (Faz 17.X)

> mkcert + Caddy ile `https://app.localtest.me:8443` lokal TLS edge.
> OIDC redirect + cookie `Secure=true` + `SameSite=None` parity sağlar (testai/prod davranışı).

## Kurulum (One-time)

### 1. mkcert + Caddy Install

```bash
# macOS (Homebrew)
brew install mkcert caddy

# Linux (apt)
sudo apt install mkcert caddy
```

### 2. Root CA Install

```bash
mkcert -install
```

Bu, sistem trust store'una mkcert local CA ekler (Firefox/Chrome/Safari tarayıcılar otomatik güvenir).

### 3. Cert Generate

```bash
cd bootstrap/local-edge
mkcert app.localtest.me "*.localtest.me" openfga.localtest.me localhost 127.0.0.1 ::1
# Generates: app.localtest.me.pem + app.localtest.me-key.pem
```

### 4. Caddy Run

```bash
# Default :8443 — sudo gerekmez
caddy run --config Caddyfile

# Alternatif :443 (sudo):
#   sudo caddy run --config Caddyfile
# veya /etc/pf.conf redirect (macOS):
#   rdr pass on lo0 inet proto tcp from any to any port 443 -> 127.0.0.1 port 8443
```

### 5. /etc/hosts (opsiyonel)

`*.localtest.me` RFC2606 ile 127.0.0.1 resolve eder; /etc/hosts değişikliği gerekmez. Ama eğer DNS cache sorun olursa:

```
127.0.0.1 app.localtest.me openfga.localtest.me
```

## Port Seçimi

| Port | Özellik | Kullanım |
|---|---|---|
| **:8443** (default) | sudo gerekmez | Çoğu geliştirici için |
| :443 | sudo veya pf rdr | Daha temiz URL (ancak port yönetimi karmaşık) |

Faz 17.X Codex iter-4 AGREE cümlesi: ":443 bağlamak macOS'ta privileged bind ister. `sudo caddy`/pf redirect/:8443 fallback — hepsi geçerli. Default :8443."

## Route Kontratı

```
https://app.localtest.me:8443/realms/*     → KC :8081 (OIDC)
https://app.localtest.me:8443/resources/*  → KC :8081 (static)
https://app.localtest.me:8443/api/*        → ingress-nginx :32080 → api-gateway
https://app.localtest.me:8443/auth/*       → ingress-nginx :32080 → auth-service
https://app.localtest.me:8443/             → ingress-nginx :32080 → frontend
https://openfga.localtest.me:8443/         → openfga :32080
```

**KC routes önemli**: `ingress/base/ingress.yaml` **`/realms/*` ve `/resources/*` içermez**
(testai/prod'da host nginx üstlenir). Lokal edge Caddy bu rotaları doldurur.

## OIDC Flow Testi

```bash
# Discovery
curl -k https://app.localtest.me:8443/realms/dev-local/.well-known/openid-configuration

# Token mint (direct grant)
curl -k -X POST https://app.localtest.me:8443/realms/dev-local/protocol/openid-connect/token \
  -d "client_id=platform-gateway" \
  -d "client_secret=dev-local-client-secret-NOT_FOR_PROD" \
  -d "username=dev@localtest.me" \
  -d "password=dev" \
  -d "grant_type=password"
```

## Cookie Secure Parity

Prod/test HTTPS → cookie `Secure=true` + `SameSite=None` → browser sadece HTTPS'te gönderir.
Lokal HTTP'de cookie sessizce drop edilir → OIDC redirect flow patlar ("Invalid state",
"Session lost" hataları).

**Caddy HTTPS terminate eder** → app seviyesi cookie `Secure=true` ile sorun olmaz → testai/prod
davranışı lokalde tekrarlanır.

## Teardown

```bash
# Caddy stop (Ctrl+C veya kill)
pkill -f 'caddy run'

# Cert'leri sil (opsiyonel; genelde tutmak daha iyi)
rm -f app.localtest.me.pem app.localtest.me-key.pem

# mkcert CA uninstall (dev makinesi reset için)
mkcert -uninstall
```

## Sorun Giderme

**"NET::ERR_CERT_AUTHORITY_INVALID" (Chrome)**
→ `mkcert -install` çalıştır; tarayıcıyı yeniden başlat.

**"connection refused" :8443**
→ Caddy çalışıyor mu? `pgrep caddy` veya `lsof -i :8443`.

**KC OIDC redirect loop**
→ KC client `redirectUris` içinde `https://app.localtest.me:8443/*` var mı kontrol et
(bootstrap/local-fixtures/keycloak/dev-local-realm.json satır 68-73).

**WebSocket / SSE**
→ Caddy `reverse_proxy` default upgrade header forward eder. Ek config gerekmez.

## Codex AGREE Referansları

- iter-4 AGREE cümlesi: "local edge `/realms/*` ve gerekiyorsa `/resources/*` trafiğini
  Keycloak'a explicit proxy eder" → Caddyfile `handle_path /realms/*` ve `/resources/*` route ✓
- iter-3 cümlesi: ":443 privileged port yasağı yok, 32080/32443 high-port; lokal edge
  :443 veya :8443 fallback" → :8443 default ✓
- iter-2 HTTPS boşluğu: "OIDC cookie Secure parity için mkcert+Caddy" → bu deliverable ✓

## İlişkili

- PLAN.md §17.X
- `.env.example` LOCAL_EDGE_HOST + LOCAL_EDGE_PORT
- `docs/local-dev-runbook.md` (17.3 çıkıtısı) — user flow guide
- `docs/promotion-contract.md` §3.1 — lokal dev gate
