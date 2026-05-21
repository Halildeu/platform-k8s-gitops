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

### 1. Keycloak realm: `acik` (prod)

Realm console: `https://ai.acik.com/auth/admin/master/console/#/acik`

### 2. User'a `org_id` attribute ekle

**User**: `halilkocoglu` (veya canary smoke yapacak user)

- Realm → Users → search `halilkocoglu` → Attributes tab
- **Add attribute**:
  - Key: `org_id`
  - Value: `default`
- Save

### 3. Client scope mapper: `org_id` claim'i JWT'ye taşı

- Realm → Client Scopes → `notify-orchestrator` (veya kullanılan API scope) → Mappers tab
- **Eğer yoksa, Create mapper**:
  - Mapper type: `User Attribute`
  - Name: `org_id`
  - User Attribute: `org_id`
  - Token Claim Name: `org_id`
  - Claim JSON Type: `String`
  - Add to ID token: ON
  - Add to access token: ON
  - Add to userinfo: ON
- Save

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
