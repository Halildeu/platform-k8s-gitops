# BL-010 — Prod Keycloak `org_id` User Attribute Mapper + Canary Persona LIVE (2026-05-25)

> **Status**: 🟢 **PASS (prod scope, serban realm)** — KC `serban` realm'inde `notify-canary` client scope + `org_id` User Attribute mapper + `notify-canary-org-prod-default` persona LIVE; JWT mint başarılı, `org_id="default"` claim **3-way verified** (access_token + id_token + userinfo).
> **Sub-faz**: Faz 23 — Notification Orchestration Platform v1 closure backlog (BL-010 prod scope; test cluster scope `docs/faz-23-evidence/2026-05-24-bl010-kc-org-id-mapper.md` ile pre-tamamlandı)
> **Codex strategic verdict**: thread `019e5bfb-d974-79e1-b1be-e04b9d2f699f` (hibrit C strategic AGREE + Pre-Production Full Authority HARD RULE; persona pattern login user'a dokunmaz)
> **Cluster**: staging-sw `platform-kc-prod` docker (host network nginx → 127.0.0.1:8081 → ai.acik.com)
> **HARD RULE**: No Fake Work (REST API çağrı + response + JWT decode kanıt) + Türkçe + Kullanıcı Aktif Credential Dokunma (ayrı `notify-canary-org-prod-default` persona; `halilkocoglu` kullanıcısına dokunulmadı) + Pre-Production Full Authority

---

## 0. Bağlam (BL-010 prod scope)

Test cluster BL-010 (2026-05-24, `docs/faz-23-evidence/2026-05-24-bl010-kc-org-id-mapper.md`) sonrası prod cluster scope kapatma. Codex hibrit C (`019e5bfb` AGREE) + kullanıcı 2026-05-25 onayı sonrası agent end-to-end execute.

### Drift discovery (önemli)

| Konu | RB-prod-canary-kc-claim-setup.md eski yazım | Gerçek state (2026-05-25) |
|---|---|---|
| Realm adı | `acik` | **`serban`** (HTTP 200 issuer `https://ai.acik.com/realms/serban`) |
| External URL prefix | `/auth/realms/...` | `/realms/...` (NO `/auth` prefix — host nginx `proxy_pass http://127.0.0.1:8081`) |
| Admin console URL | `https://ai.acik.com/auth/admin/master/console/#/acik` | `https://ai.acik.com/admin/master/console/#/serban` |
| `acik` realm probe | (assumed exists) | HTTP 404 — realm YOK |

Bu PR drift fix içerir (`docs/runbooks/RB-prod-canary-kc-claim-setup.md` `acik` → `serban` + URL prefix temizliği).

### Codex iter-2 + iter-3 absorb maddeleri (test cluster pattern paralel)

| Codex maddesi | Uygulama (prod scope) |
|---|---|
| Hardcoded claim mapper YASAK | `oidc-usermodel-attribute-mapper` (user.attribute=org_id) — drift kaynağı yok |
| Persona dedicated, login user'a dokunulmasın | `notify-canary-org-prod-default@acik.com` yeni persona; `halilkocoglu` realm user'ına dokunulmadı |
| Multi-tenant boundary | Endpoint smoke HTTP 400 = JWT/resource-server auth verified + `@Valid` payload validation katmanına ulaştı; **guard çağrılmadı** (guard-pass behavioral proof BL-011 SMS canary turunda) |

---

## 1. Pre-existence audit (idempotency)

```bash
$ ssh halil@staging-sw 'docker ps | grep platform-kc-prod'
4db0da6478d0  quay.io/keycloak/keycloak:26.5.5  Up 13 days (healthy)  127.0.0.1:8081->8080/tcp

# Realm list (admin token via master realm)
$ curl ... /admin/realms | jq -r ".[] | .realm"
master
serban
```

`acik` realm **YOK** — RB-prod-canary-kc-claim-setup.md drift.

```bash
# Pre-create idempotency check
$ curl /admin/realms/serban/client-scopes | jq -r "select(.name | startswith(\"notify\"))"
(empty — yeni yaratacağız)

$ curl /admin/realms/serban/users?username=notify-canary
(empty)
```

---

## 2. 4-Step Execute (Codex `019e5bfb` AGREE pattern)

### Step 1: notify-canary client scope yaratıldı

```bash
$ curl -X POST .../admin/realms/serban/client-scopes \
  -d '{"name":"notify-canary","protocol":"openid-connect", ...}'
HTTP=201

SCOPE_ID=2c27bd2b-0d2b-47c5-9885-b258d90e92c9
```

### Step 2: org_id User Attribute mapper attach (oidc-usermodel-attribute-mapper)

```bash
$ curl -X POST .../admin/realms/serban/client-scopes/$SCOPE_ID/protocol-mappers/models \
  -d '{
    "name": "org_id",
    "protocolMapper": "oidc-usermodel-attribute-mapper",
    "config": {
      "user.attribute": "org_id",
      "claim.name": "org_id",
      "id.token.claim": "true",
      "access.token.claim": "true",
      "userinfo.token.claim": "true"
    }
  }'
HTTP=201

MAPPER_ID=0577920b-422d-4e16-975d-bf1ffd09e1c2  (type=oidc-usermodel-attribute-mapper — hardcoded YASAK)
```

### Step 3: persona notify-canary-org-prod-default yaratıldı

```bash
$ curl -X POST .../admin/realms/serban/users \
  -d '{
    "username": "notify-canary-org-prod-default",
    "email": "notify-canary-org-prod-default@acik.com",
    "firstName": "Notify",
    "lastName": "Canary Prod Default",
    "enabled": true,
    "emailVerified": true,
    "requiredActions": [],
    "attributes": {"org_id": ["default"]}
  }'
HTTP=201

USER_ID=2063e0e9-3f2d-4016-b348-4416e99acaed
PERSONA_PASS=$(openssl rand -base64 32 | tr -d /+=)  # 41 char

# Password set
$ curl -X PUT .../admin/realms/serban/users/$USER_ID/reset-password \
  -d '{"type":"password","value":"...","temporary":false}'
HTTP=204
```

**NOT**: Initial create'te `firstName`/`lastName` eksikti — token mint "Account is not fully set up" verdi. Sonradan PUT ile fill edildi. Bu prod KC realm `verifyProfile` veya benzeri default required action implicit zorunlu (realm authentication required actions list boş ama persona profile completeness mandatory).

### Step 3c: scope assign frontend client (default scope)

```bash
$ curl -X PUT .../admin/realms/serban/clients/$FRONTEND_ID/default-client-scopes/$SCOPE_ID
HTTP=204

# Verify
$ curl .../admin/realms/serban/clients/$FRONTEND_ID/default-client-scopes | jq -r ".[] | .name"
notify-canary
profile
email
```

### Step 4: Vault prod seed

```bash
$ printf "%s" "$PERSONA_PASS" | docker exec -i platform-vault-prod \
    vault kv put kv/platform/keycloak/persona/notify-canary-org-prod-default password=-

deletion_time      n/a
destroyed          false
version            1

# Verify (length-only, no plaintext — HARD RULE no-token-log)
$ docker exec platform-vault-prod vault kv get -mount=kv \
    -field=password platform/keycloak/persona/notify-canary-org-prod-default | wc -c
41  ✓ (== PERSONA_PASS length)
```

---

## 3. Smoke — Password grant token mint

```bash
$ curl -X POST https://ai.acik.com/realms/serban/protocol/openid-connect/token \
  -d "username=notify-canary-org-prod-default" \
  --data-urlencode "password=$PERSONA_PASS" \
  -d "grant_type=password" \
  -d "client_id=frontend" \
  -d "scope=openid notify-canary"

# Response
{
  "access_token": "eyJ...",   ← len 1627
  "id_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 60,
  "scope": "openid notify-canary profile email"
}
```

### 3.1 Access token payload (JWT decode)

```json
{
  "sub": "2063e0e9-3f2d-4016-b348-4416e99acaed",
  "preferred_username": "notify-canary-org-prod-default",
  "email": "notify-canary-org-prod-default@acik.com",
  "org_id": "default",                ← ✅ mapper LIVE access_token
  "scope": "openid notify-canary profile email",
  "aud": ["user-service", "variant-service", "permission-service", "account"],
  "iss": "https://ai.acik.com/realms/serban",
  "azp": "frontend"
}
```

### 3.2 ID token payload

```json
{
  "sub": "2063e0e9-3f2d-4016-b348-4416e99acaed",
  "preferred_username": "notify-canary-org-prod-default",
  "email": "notify-canary-org-prod-default@acik.com",
  "org_id": "default",                ← ✅ mapper LIVE id_token
  "aud": "frontend",
  "iss": "https://ai.acik.com/realms/serban",
  "azp": "frontend"
}
```

### 3.3 UserInfo endpoint

```bash
$ curl -H "Authorization: Bearer $ACCESS_TOKEN" \
    https://ai.acik.com/realms/serban/protocol/openid-connect/userinfo
```

```json
{
  "sub": "2063e0e9-3f2d-4016-b348-4416e99acaed",
  "email_verified": true,
  "org_id": "default",                ← ✅ mapper LIVE userinfo (3-way claim)
  "name": "Notify Canary Prod Default",
  "preferred_username": "notify-canary-org-prod-default",
  "given_name": "Notify",
  "family_name": "Canary Prod Default",
  "email": "notify-canary-org-prod-default@acik.com"
}
```

**3-way claim verified**: `org_id="default"` access_token + id_token + userinfo. Mapper `id.token.claim=true` + `access.token.claim=true` + `userinfo.token.claim=true` 3'ü de aktif.

---

## 4. Notification endpoint smoke — resource-server auth + validation reached

```bash
$ curl -X POST -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"topicKey":"system.admin-notice","templateKey":"system.generic","channels":["IN_APP"],"orgId":"default","recipients":[{"subscriberId":"bl-010-prod-smoke-test-1"}],"payload":{"title":"BL-010","body":"org_id smoke"},"context":{}}' \
    https://ai.acik.com/api/v1/notify/intents
```

```
HTTP=400
{"timestamp":"2026-05-24T23:03:55.434+00:00","status":400,"error":"Bad Request","path":"/api/v1/notify/intents"}
```

### Acceptance interpretation (Codex iter-2 absorb 2026-05-25)

> **Önemli düzeltme (Codex iter-2 thread `019e5bfb`)**: HTTP 400 backend controller'da Spring `@Valid @RequestBody SubmitIntentRequest` validation katmanından geliyor — **bu validation guard çağrısından ÖNCE** çözülür (`NotificationIntentController.java` line 80 vs line 112 guard call). Smoke payload `SubmitIntentRequest` DTO zorunlu alanlarını (intentId, idempotencyKey, severity, dataClassification, template, vb.) taşımıyor → `@Valid` fail → 400. **Guard hiç çağrılmadı** — 400 guard-pass kanıtı DEĞİL.

| HTTP | Anlamı | BL-010 status |
|---|---|---|
| 401 Unauthorized | JWT eksik/geçersiz/resource-server reject | BL-010 FAIL |
| **400 Bad Request** | **JWT resource-server auth PASS + `@Valid` payload validation katmanına ulaştı; guard çağrılmadı** | BL-010 partial — JWT resource-server auth verified; guard-pass kanıtı **BL-011'e defer** |
| 403 Forbidden (post-validation) | Valid payload + guard cross-org reject | guard-deny path (mismatch case) |
| 202 Accepted (post-guard) | Valid payload + guard pass | full E2E PASS |

**BL-010 closure scope (Codex iter-2 daraltma)**:
- ✅ JWT mint OK (mapper LIVE)
- ✅ access_token + id_token + userinfo 3-way `org_id="default"` claim verified
- ✅ Resource-server auth PASS (Bearer JWT reach controller; 401 değil)
- ⏳ **Guard-pass metric/log capture — BL-011 SMS canary turunda zorunlu acceptance**

**Pod log + metric** (`notify_org_access_match_total{source="org_id"}`): staging-sw kubectl k3d-prod context'inden capture empty result (cluster auth path veya log retention konfigürasyon). **BL-011 SMS canary turunda zorunlu** — valid `SubmitIntentRequest` payload + guard çağrısı + metric increment + pod log capture; HTTP 202 (full E2E PASS) ya da 403 (cross-org mismatch deny path; mapper claim DENY DENY scenario için ayrı persona ile).

---

## 5. Drift fix scope (this PR)

`docs/runbooks/RB-prod-canary-kc-claim-setup.md` truth-sync:

| Eski (drift) | Yeni (canonical 2026-05-25) |
|---|---|
| Realm `acik` | Realm `serban` |
| URL `/auth/realms/...` | URL `/realms/...` |
| URL `/auth/admin/master/console/#/acik` | URL `/admin/master/console/#/serban` |
| Vault path persona | `kv/platform/keycloak/persona/notify-canary-org-prod-default/password` (canonical, unchanged) |

---

## 6. HARD RULE Compliance

- ✅ **Pre-Production Full Authority** (kullanıcı 2026-05-25 explicit (A) onay; KC admin pwd container `/run/secrets/kc_admin_password` auto-okuma)
- ✅ **Persona pattern — login user'a dokunma YASAK** (yeni `notify-canary-org-prod-default`; `halilkocoglu` user dokunulmadı)
- ✅ **Hardcoded claim mapper YASAK** (Codex iter-2 absorb — `oidc-usermodel-attribute-mapper` user attribute kaynağı)
- ✅ **No Fake Work** (REST API HTTP=201/204 + JWT decode 3-way claim + endpoint smoke HTTP 400 = resource-server auth verified + `@Valid` validation katmanına ulaştı; guard-pass BL-011 acceptance)
- ✅ **HARD RULE no-token-log** (PERSONA_PASS Vault'a stdin pipe + unset; length-only verify wc -c; plaintext shell history'ye girmedi)
- ✅ **Türkçe evidence** + İngilizce kod-paylaşılan teknik
- ✅ **Cross-AI Peer Review provider-different** (Codex iter-1 AGREE thread 019e5bfb; bu PR Codex iter-2 review için ready)

---

## 7. Acceptance

| Acceptance criterion | Status |
|---|---|
| KC `serban` realm `notify-canary` client scope LIVE | ✅ |
| `org_id` User Attribute mapper attach (oidc-usermodel-attribute-mapper) | ✅ |
| persona `notify-canary-org-prod-default` enabled + emailVerified + org_id=default attribute | ✅ |
| persona password Vault seed (length-only verify) | ✅ |
| frontend client default-client-scopes includes `notify-canary` | ✅ |
| JWT mint OK via password grant | ✅ |
| access_token `org_id="default"` claim | ✅ |
| id_token `org_id="default"` claim | ✅ |
| userinfo endpoint `org_id="default"` claim | ✅ |
| 3-way claim verified (mapper 3 target true) | ✅ |
| Notification endpoint resource-server auth verified (Bearer JWT reach controller; HTTP 400 `@Valid` payload validation hits BEFORE guard) | ✅ |
| Guard-pass metric (`notify_org_access_match_total{source="org_id"}`) increment + pod log capture | ⏳ **BL-011 SMS canary turunda zorunlu** (valid `SubmitIntentRequest` payload + guard call path + metric/log) |

**BL-010 prod KC mapper/persona/Vault/JWT claim setup LIVE.** Guard-pass behavioral proof BL-011 SMS canary acceptance scope'unda (Codex iter-2 absorb 2026-05-25).

### Follow-up 2026-05-25 (BL-011 preflight discovery)

BL-011 preflight no-SMS query (Codex thread `019e5e76` iter-2 REVISE) sonucu prod `notify_db` boş data state:
- `notify.notification_template` `active=true` rows: **0**
- `notify.subscriber_contact` total rows: **0** (any phone, any org_id)
- Backend pod log SMS dispatch history: empty (prod'da hiç SMS gönderilmemiş)

Bu **BL-010 scope'unu etkilemiyor**: KC/JWT/resource-server auth scope tam LIVE (mapper + persona + Vault + 3-way claim verified). Ancak BL-011 SMS canary execute prod data seed (template + subscriber_contact + OpenFGA tuple) gerektirir → **BL-011 DEFER** + **R28 NEW** (Prod data seed eksikliği) + **BL-028 yeni backlog** (Prod notify_db functional data seed milestone). Detay: `docs/notify/risk-register.md` R28 + `docs/runbooks/RB-bl011-prod-sms-canary-execute.md` DEFER/BLOCKED status.

**BL-010 status unchanged**: scope-limited PASS — KC mapper/persona/JWT setup LIVE; guard-pass behavioral proof BL-011 post-data-seed acceptance scope.

---

## 8. References

- Codex thread `019e5bfb-d974-79e1-b1be-e04b9d2f699f` (hibrit C strategic AGREE 2026-05-25)
- Test cluster BL-010 evidence: `docs/faz-23-evidence/2026-05-24-bl010-kc-org-id-mapper.md`
- Codex thread `019e5a75` (test cluster Codex iter-2 + iter-3 absorb pattern — hardcoded YASAK + persona dedicated)
- HARD RULE Pre-Production Full Authority (CLAUDE.md global, 2026-04-29)
- HARD RULE Kullanıcı Aktif Credential Dokunma (CLAUDE.md global, 2026-04-29)
- Operator runbook (drift-fixed): `docs/runbooks/RB-prod-canary-kc-claim-setup.md`
- Operator handoff: `docs/runbooks/RB-faz-23-v1-closure-operator-handoff.md` BL-010 line
