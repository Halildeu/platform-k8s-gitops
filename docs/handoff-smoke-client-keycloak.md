# HAND-OFF: Keycloak `smoke-client` Confidential Client

> **Source:** K8s-6 Seviye 1 acceptance (2026-04-19, Codex thread `019d9a75` S1-E6 tamamlanma review)
> **Target:** platform-ssot (Keycloak realm config + seed) veya ops ekibi
> **Priority:** P1 — S2 ilk blocker (D29 Zanzibar-ready full acceptance için **allow synthetic** kanıtı)
> **Codex S1-E6 uzlaşısı:** "Authenticated allow synthetic hâlâ eksik, S2'nin ilk işi olmalı — shortname refactor DEĞİL"

---

## 1. Bağlam

K8s-6 Seviye 1 deploy PASS:
- permission-service (`sha-3923901`) 1/1 Running testai'de
- Hub smoke (cluster-direct): `/api/v1/authz/version` + `/api/v1/authz/me` → **401 JWT required** (endpoint aktif, Spring Security chain doğru)
- Intra-cluster gateway deny enforce: `/variants`, `/auth/login` (no token) → **401 JSON** ✅
- Authoritative edge (intranet host, testai A kaydı) deny enforce ✅

**Açık kapı:** D29 tam Zanzibar-ready kabul için **synthetic allow kanıtı** gerek — yani **authenticated user** ile `/variants` 2xx, unauthorized scope ile 403.

## 2. Sorun

`admin-cli` Keycloak default client `direct_access_grants_enabled=false` (SPA public client). Password grant ile token alınamıyor:

```bash
curl -X POST "http://keycloak:8080/realms/serban/protocol/openid-connect/token" \
  -d "grant_type=password&client_id=admin-cli&username=admin&password=admin"
→ HTTP 401
```

Zanzibar-25'te de benzer engelle karşılaşıldı (kişi not edilmişti). Çözüm: **confidential client** yaratılmalı.

## 3. İstenen İş

### 3.1 Keycloak realm config — `smoke-client` (veya `canary-load`)

**Client properties:**
- Client ID: `smoke-client` (veya Zanzibar-25 canary ile birleşik `canary-load`)
- Client type: **Confidential** (`publicClient: false`)
- Standard Flow: **Disabled** (OAuth2 authorization_code akışı gerekmiyor)
- Direct Access Grants: **Enabled** (`directAccessGrantsEnabled: true`)
- Service Accounts: **Enabled** (`serviceAccountsEnabled: true`)
- Client Authenticator: Client ID and Secret
- Secret: auto-generate (Vault'ta saklanacak)

### 3.2 Realm export (import icin)

Keycloak realm `serban` JSON export'ta bu client seed olarak dahil olmalı. Lokal dev'de `backend/docker-compose.yml` ile birlikte gelir. Staging'de de seed.

### 3.3 Secret Flow

**Vault path:** `kv/platform/keycloak/smoke-client` → `CLIENT_SECRET` alanı
**K8s-6 ConfigMap/Secret:** `smoke-client-secrets` (ESO inject — S2-B1 W1 ESO work ile birleşir)
**Smoke script env:** `SMOKE_CLIENT_ID=smoke-client`, `SMOKE_CLIENT_SECRET=<vault-inject>`

### 3.4 Test Usage (K8s-6 Seviye 1 acceptance için)

```bash
# Token al (client_credentials flow veya password grant)
TOKEN=$(curl -sk -X POST \
  "https://testai.acik.com/auth/realms/serban/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=smoke-client" \
  -d "client_secret=$SMOKE_CLIENT_SECRET" \
  | jq -r .access_token)

# Authenticated allow synthetic
curl -sk -H "Authorization: Bearer $TOKEN" "https://testai.acik.com/variants"
# beklenen: 2xx (yetkili varsa)

# Unauthorized scope deny
curl -sk -H "Authorization: Bearer <restricted-persona-token>" "https://testai.acik.com/variants"
# beklenen: 403
```

## 4. Kabul Kriteri

- [ ] Keycloak `serban` realm'inde `smoke-client` confidential client var (direct_access_grants + service_accounts)
- [ ] Vault `kv/platform/keycloak/smoke-client` path'inde CLIENT_SECRET
- [ ] Realm export JSON'a eklenmiş
- [ ] Lokal dev'de `docker-compose up` sonrası KC'de görünür
- [ ] Staging'de seed script ile gelir
- [ ] K8s-6 smoke tuple B katmanı `curl -H "Authorization: Bearer <token>" /variants` 2xx + 403 kanıt

## 5. Zanzibar-25 ile Birleşim

**Not:** Zanzibar-25 `canary-load` dedicated client pattern'ini kullandı (k6 persona matrix için). Eğer `canary-load` zaten confidential client ve aynı özellikleri karşılıyorsa, **yeni client yaratmaya gerek yok** — aynı client'ı K8s-6 smoke-client olarak kullanabiliriz.

**Kontrol:** Zanzibar-25 session sonu realm config'te `canary-load` hâlâ var mı? `directAccessGrantsEnabled=true` mi? `serviceAccountsEnabled=true` mi? Varsa K8s-6 smoke bu client'ı kullanır, sadece secret'i erişilebilir yapmak gerek (K8s Secret'a inject).

## 6. Codex İstişare Önerisi

Küçük scope (realm config + secret path). Plan istişaresi opsiyonel. Büyük risk yok.

## 7. Prompt (Zanzibar/ops session'a kopyala-yapıştır)

```
TASK: smoke-client Keycloak confidential client (K8s-6 S2 ilk blocker)
From: K8s-6 S1-E6 Codex tamamlanma review
Priority: P1 (Zanzibar-ready full acceptance blocker)

Detay: platform-k8s-gitops/docs/handoff-smoke-client-keycloak.md

Özet: admin-cli direct_access_grants=false. Synthetic allow+deny smoke için
confidential client gerek. Keycloak realm serban içinde smoke-client (veya
canary-load birleşik) confidential + direct_access_grants + service_accounts.
Secret Vault'ta kv/platform/keycloak/smoke-client. Lokal realm export'a seed.

Kabul: curl -d grant_type=client_credentials + client_id + client_secret →
access_token → /variants (authenticated) 2xx, /variants (unauthorized) 403.

Not: Zanzibar-25 canary-load dedicated client varsa aynı kullanılabilir.
```

## 8. Referanslar

- Codex thread: `019d9a75-4299-7313-85bb-003a7de680eb` (S1-E6 review)
- K8s-6 PLAN.md Seviye 1 deploy-sonrası entry (2026-04-19)
- Zanzibar-25 handoff notları (canary-load client pattern)
