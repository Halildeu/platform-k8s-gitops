# RB — Prod Canary SMS: Keycloak `org_id` Claim Setup (M4 23.3 Functional Acceptance)

> **Status**: ACTIVE (Codex `019e4965` AGREE PARTIAL absorb 2026-05-21)
> **Tetik**: M4 prod canary SMS smoke 403 strict-mode deny — `NotifyOrgAccessGuard.requireOrgAccessOrThrow("default")` fails çünkü JWT'de `org_id`/`tenant_id`/`allowed_orgs` claim'i yok ve `NOTIFY_SECURITY_DEFAULT_ORG_ID=""` strict cutover aktif (Faz 24 PR-5.5).
> **Süre**: 15-30 dk operator iş
> **Owner**: ops (Keycloak admin) + dev (verify)

## Bağlam

M4 prod cutover LIVE 2026-05-20 (PR-B4 #916 MERGED). Backend SmtpAdapter + SmsAdapter + JetSmsDlrPollingWorker + ProductionConfigValidator all guards PASSED. Ancak gerçek end-to-end SMS dispatch için `POST /api/v1/notify/intents` çağrısı her seferinde HTTP 403 alıyor çünkü:

1. `NotifyOrgAccessGuard` sırayla JWT'de `org_id`, `tenant_id`, `allowed_orgs` arıyor (`/Users/halilkocoglu/Documents/platform-backend/notification-orchestrator/src/main/java/com/serban/notify/api/NotifyOrgAccessGuard.java:113`)
2. v1'de `notify-deliveries-cross-org` permission seedli **değil** (Codex iter-3 AGREE — "v1 kapalı, ileri uyumlu")
3. Default fallback `notify.security.default-org-id` **boş** (`NOTIFY_SECURITY_DEFAULT_ORG_ID=""` strict cutover)
4. **Sonuç**: `source=none` metric + `AccessDeniedException` → HTTP 403

Bu **beklenen davranış**: strict-mode + KVKK 12.B multi-tenancy guard LIVE. Real prod canary için kullanıcı JWT'sine `org_id` claim'i eklemek gerek.

## Adımlar

### 1. Keycloak realm: `serban` (prod)

> **Drift fix 2026-05-25 (BL-010 prod execute — Codex `019e5bfb` AGREE)**: Eski yazım `acik` realm DRIFT idi (`acik` realm yok; canonical `serban`). External URL `/auth/realms/...` prefix de drift (host nginx config `/home/halil/platform/web/nginx/default.conf` `proxy_pass http://127.0.0.1:8081` direkt `/realms/...` map eder). Detay: `docs/faz-23-evidence/2026-05-25-bl010-prod-kc-org-id-mapper-serban.md`.

Realm console: `https://ai.acik.com/admin/master/console/#/serban` (NOT `/auth/admin/...` — drift fix)
Realm well-known: `https://ai.acik.com/realms/serban/.well-known/openid-configuration` (HTTP 200; issuer `https://ai.acik.com/realms/serban`)

### 2. Persona pattern (post-2026-05-25 canonical — BL-010 prod execute)

> **HARD RULE Kullanıcı Aktif Credential Dokunma YASAK 2026-04-29**: `halilkocoglu` realm user'ına attribute eklemek **YASAK**. Yeni dedicated persona yaratılır.
>
> **Post-2026-05-25 canonical persona** (BL-010 prod execute live):
> - Username: `notify-canary-org-prod-default`
> - Email: `notify-canary-org-prod-default@acik.com`
> - firstName: `Notify`, lastName: `Canary Prod Default` (KC 26+ profile completeness mandatory; eksikse "Account is not fully set up" token mint error)
> - emailVerified: `true`, enabled: `true`, requiredActions: `[]`
> - Attribute: `org_id=default`
> - Password: Vault seed `kv/platform/keycloak/persona/notify-canary-org-prod-default/password` (stdin pipe + length-only verify)

**Canonical REST API pattern** (UI yerine, idempotent + scriptable):

```bash
# Persona create
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "username":"notify-canary-org-prod-default",
    "email":"notify-canary-org-prod-default@acik.com",
    "firstName":"Notify","lastName":"Canary Prod Default",
    "enabled":true,"emailVerified":true,"requiredActions":[],
    "attributes":{"org_id":["default"]}
  }' \
  https://ai.acik.com/admin/realms/serban/users
# Expect HTTP 201

# Password (Vault'tan stdin pipe — HARD RULE no-token-log)
curl -X PUT -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "{\"type\":\"password\",\"value\":\"$PERSONA_PASS\",\"temporary\":false}" \
  https://ai.acik.com/admin/realms/serban/users/$USER_ID/reset-password
# Expect HTTP 204
```

**Legacy/historical pattern** (NOT canonical post-2026-05-25): UI üzerinde `halilkocoglu` user'a `org_id=default` attribute ekleme yolu mevcut RB versiyonunda yazılı idi; HARD RULE 2026-04-29 ile YASAK. **Bu yol BL-010 için kullanılmaz** — dedicated persona pattern canonical.

### 3. Client scope mapper: `org_id` claim'i JWT'ye taşı (post-2026-05-25 canonical)

> **Post-2026-05-25 canonical**: Client scope **`notify-canary`** (NOT eski `notify-orchestrator`); frontend client'a **default-client-scope** olarak assign edilir.

**Canonical REST API pattern**:

```bash
# Client scope yarat
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name":"notify-canary",
    "description":"Faz 23 v1 prod canary org_id claim mapper",
    "protocol":"openid-connect",
    "attributes":{"include.in.token.scope":"true","display.on.consent.screen":"false"}
  }' \
  https://ai.acik.com/admin/realms/serban/client-scopes
# Expect HTTP 201; capture SCOPE_ID from GET /client-scopes

# Mapper attach (oidc-usermodel-attribute-mapper — hardcoded YASAK Codex iter-2 absorb)
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name":"org_id",
    "protocol":"openid-connect",
    "protocolMapper":"oidc-usermodel-attribute-mapper",
    "config":{
      "user.attribute":"org_id",
      "claim.name":"org_id",
      "jsonType.label":"String",
      "id.token.claim":"true","access.token.claim":"true","userinfo.token.claim":"true",
      "multivalued":"false","aggregate.attrs":"false"
    }
  }' \
  https://ai.acik.com/admin/realms/serban/client-scopes/$SCOPE_ID/protocol-mappers/models
# Expect HTTP 201

# Default-client-scope assign to frontend
curl -X PUT -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://ai.acik.com/admin/realms/serban/clients/$FRONTEND_ID/default-client-scopes/$SCOPE_ID
# Expect HTTP 204
```

**Legacy reference** (eski yazım): `notify-orchestrator` scope adı + manual UI mapper formu — post-2026-05-25 BL-010 prod execute pattern superseded eder. Bkz. `docs/faz-23-evidence/2026-05-25-bl010-prod-kc-org-id-mapper-serban.md` §2 canonical 4-step.

**Alternatif**: `allowed_orgs` mapper (multi-tenant operator için)
- Mapper type: `User Attribute`
- Name: `allowed_orgs`
- User Attribute: `allowed_orgs` (multi-value)
- Token Claim Name: `allowed_orgs`
- Claim JSON Type: `JSON String[]`
- Multivalued: ON
- Aggregate attribute values: ON

**Önerilen**: `org_id` (Codex `019e4965` AGREE — frontend tarafında `allowed_orgs[0]` sessizce org seçmek bilinçli yasaklı; en az sürprizli yol).

### 4. User'a yeniden login yaptır

Browser:
- `https://ai.acik.com` → top-right user dropdown → Logout
- Tekrar login (M365 SSO flow)

VEYA token refresh (browser dev tools → Application → Cookies → KC session cookie sil → page reload)

### 5. Verify: `/api/v1/authz/me` projection

Browser dev console:
```javascript
fetch('/api/v1/authz/me', { credentials: 'include' })
  .then(r => r.json())
  .then(j => console.log('orgId:', j.orgId, '| allowedScopes:', j.allowedScopes));
```

**Expected**: `orgId: "default"` veya `allowedScopes: ["default"]` field surface'e gelmeli.

### 6. Real canary SMS smoke

Browser dev console (kullanıcı + agent ortak):
```javascript
fetch('/api/v1/notify/intents', {
  method: 'POST',
  credentials: 'include',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    intentId: 'canary-prod-' + Date.now(),
    idempotencyKey: 'canary-prod-' + Date.now(),
    orgId: 'default',
    topicKey: 'marketing.campaign',
    severity: 'info',
    dataClassification: 'commercial',
    recipients: [{ type: 'external', phone: '+905551815564', name: 'Canary' }],
    template: { templateId: 't1', locale: 'tr-TR' },
    channels: ['sms'],
    payload: { body: 'Prod cutover canary test SMS, ignore.' }
  })
}).then(r => r.json()).then(j => console.log('Result:', j));
```

**Expected response**: HTTP 202 Accepted + `{intentId, status: "PENDING_DISPATCH"}` veya benzeri.

### 7. DLR cycle verify (5-60 sn beklendi)

```bash
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod logs deploy/notification-orchestrator --since=2m | grep -E 'jetsms (SOAP|ACCEPTED|DELIVERED)|dlr jetsms'"
```

**Expected**: `jetsms SOAP ACCEPTED (awaits DLR poll): msg_id=...` → 60sn sonra `dlr jetsms UPDATED: code=1 new=DELIVERED`.

### 8. Telefonda SMS doğrula

+905551815564 → "Prod cutover canary test SMS, ignore." → screenshot al → evidence doc'a ekle.

## Rollback

Eğer `org_id` claim eklenmesi başka çağrıları etkilerse (ör. başka tenant kullanıcıları yanlış org'a düşer):
1. Keycloak → User attributes → `org_id` sil
2. Client scope mapper aktif kalır (başka kullanıcılar için forward-compat)

## Evidence doc kaydı

Canary success sonrası `docs/faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md` §8a "Prod Canary Attempt — Strict-Mode Deny Evidence" altına yeni blok ekle:
- Path + timestamp
- HTTP 202 response
- JetSMS SOAP ACCEPTED log
- DLR DELIVERED cycle log
- SMS screenshot reference (varsa)
- M4 DoD A.4 + A.5 → [x] done
- Charter 23.3 marker: `🟢 source-ready + acceptance candidate` → `🟢 fully closed` (functional canary acceptance)

## Why bu runbook gerekli

Codex `019e4965` AGREE: M4 functional acceptance için service principal / machine token impl (~3-4h dev iş) **kısa yol değil**, repeatable regression smoke altyapısı olarak ayrı sprint scope'unda. Bu runbook **operator gate** yolu sağlar:
- Tek seferlik canary smoke için 15-30 dk yeterli
- Service principal smoke automation sonradan eklenebilir (CI cron job)
- Test cluster smoke 3-senaryo DELIVERED + prod strict deny + canary functional → M4 fully closed evidence triplet

## Bağlantı

- Codex thread: `019e4965-23fc-71c0-bd71-40faa3c1a14e` (M4 prod canary 403 interpretation + closure path)
- Önceki Codex thread'ler: `019e4722` M4 closure, `019e472f` M5 chain, `019e493f` Slack Block Kit, `019e492f` T4.3.b email suppression, `019e4950` KVKK review
- Backend guard kodu: `notification-orchestrator/src/main/java/com/serban/notify/api/NotifyOrgAccessGuard.java`
- Frontend auth helpers: `apps/mfe-shell/src/app/config/auth-helpers.ts`
- Strict cutover ref: Faz 24 PR-5.5 (`docs/state/current-state.md` strict env section)
