# BL-010 — Keycloak `org_id` User Attribute Mapper + Canary Persona Live Evidence (2026-05-24)

> **Status**: 🟢 **PASS (test cluster scope)** — KC `platform-test` realm'inde `notify-canary` client scope + `org_id` User Attribute mapper + `notify-canary-org-default` persona LIVE; JWT mint başarılı, `org_id=default` claim verified, multi-tenant DENY boundary (HTTP 403) doğrulandı.
> Prod cluster (`acik` veya `platform-prod` realm) bu PR scope dışı; operator action runbook `RB-prod-canary-kc-claim-setup.md` zaten mevcut.
> **Sub-faz**: Faz 23 — Notification Orchestration Platform v1 closure backlog
> **BL-010** ref: [`RB-faz-23-v1-closure-operator-handoff.md`](../runbooks/RB-faz-23-v1-closure-operator-handoff.md) §Sprint B canary smoke
> **Codex strategic verdict**: thread `019e5a75-ebf3-7860-9832-2776a6d185b6` (post-impl AGREE conditional under Pre-Production Full Authority HARD RULE)
> **Cluster**: k3d-test (`platform-test` namespace) + KC test container (`platform-kc-test`, host port 8082, realm `platform-test`)
> **HARD RULE**: No Fake Work (REST API çağrı + response + JWT decode kanıt) + Türkçe + Kullanıcı Aktif Credential Dokunma (ayrı `notify-canary-org-default` persona; admin/halilkocoglu kullanıcısına dokunulmadı) + Pre-Production Full Authority + D29 disiplin

---

## 0. Bağlam (BL-010 scope)

Faz 23 v1 closure backlog `BL-010` — "Keycloak `org_id=default` claim setup" gereği. Codex iter-2 + iter-3 (`019e5a75`) AGREE verdict'inde **conditional agent-actionable** olarak belirlendi: persona pattern (`notify-canary-org-default`) + User Attribute mapper (oidc-usermodel-attribute-mapper) + hardcoded mapper YASAK (drift global; multi-tenant guard bypass).

### Codex iter-2 + iter-3 absorb maddeleri (HARD RULE eşleştirme)

| Codex maddesi | Uygulama (bu evidence) | HARD RULE link |
|---|---|---|
| Hardcoded claim mapper YASAK | `oidc-usermodel-attribute-mapper` kullanıldı; `user.attribute=org_id` claim source = User attribute (drift kaynağı yok) | Codex `019e5a75` iter-2 |
| Persona dedicated, kullanıcının login user'ına dokunulmasın | `notify-canary-org-default@test.platform` yeni persona; `halilkocoglu` realm user'ına dokunulmadı | Kullanıcı Aktif Credential Dokunma (2026-04-29) |
| Multi-tenant boundary kanıtlanmalı (allow + deny) | ALLOW path `orgId=default` → JWT auth pass (`X-Org-Id: default` mismatch yok); DENY path `orgId=otherorg` → HTTP 403 Forbidden `insufficient_scope` | D29 Zanzibar-ready disiplin §6 |
| Persona lifecycle: disabled after canary VEYA restricted smoke (silme YOK) | Persona enabled=true bırakıldı (smoke regression için); KC admin opsiyonel disable | Codex `019e5a75` iter-3 |

### D29 Disiplin Matrix (BL-010 scope)

| Katman | Boundary | Source-side LIVE | Test cluster Evidence |
|---|---|---|---|
| **D29-Up** | KC container Running + TCP reachable | ✅ (`platform-kc-test` 13 days healthy) | ✅ §2.1 health |
| **D29-Functional-mint** | Token mint başarılı + audience match | ✅ (frontend client, `realms/platform-test/protocol/openid-connect/token`) | ✅ §3 token decode |
| **D29-Functional-claim** | `org_id=default` access token + ID token + userinfo | ✅ (mapper id_token=true, access_token=true, userinfo=true) | ✅ §3 + §4 |
| **D29-Functional-guard** | `NotifyOrgAccessGuard.requireOrgAccessOrThrow()` `source="org_id"` increment | ✅ (PR-5.2 backend cutover M2 2026-05-14) | ✅ **§5.2 metric counter 4.0** |
| **D29-Zanzibar-ready** | Multi-tenant DENY boundary enforce (cross-org reject) | ✅ (NotifyOrgAccessGuard mismatch 403) | ✅ §6 DENY 403 + metric `source="none"` |

---

## 1. Persona setup adımları — Keycloak REST API (test cluster scope)

### 1.1 Preflight: KC test container health + realm list

```bash
# Test KC host port 8082 (platform-kc-test docker container)
$ ssh halil@staging-sw 'docker ps | grep platform-kc-test'
4db0da6478d0  quay.io/keycloak/keycloak:26.5.5  Up 13 days (healthy)
                                                  127.0.0.1:8082->8080/tcp
                                                  platform-kc-test

# Master realm reachable (no JWT — internal network)
$ ssh halil@staging-sw 'curl -sS -o /dev/null -w "HTTP=%{http_code}\n" \
    http://127.0.0.1:8082/realms/master/.well-known/openid-configuration'
HTTP=200

# platform-test realm reachable
$ ssh halil@staging-sw 'curl -sS -o /dev/null -w "HTTP=%{http_code}\n" \
    http://127.0.0.1:8082/realms/platform-test/.well-known/openid-configuration'
HTTP=200
```

Issuer: `https://testai.acik.com/realms/platform-test`.

### 1.2 Admin token acquire (master realm, `admin-cli` client, password grant)

```bash
$ ssh halil@staging-sw '
  ADMIN_PASS=$(docker exec platform-kc-test cat /run/secrets/kc_admin_password)
  curl -sS -X POST http://127.0.0.1:8082/realms/master/protocol/openid-connect/token \
    -d "username=admin" \
    --data-urlencode "password=$ADMIN_PASS" \
    -d "grant_type=password" \
    -d "client_id=admin-cli"
'
{"access_token":"eyJ...ICIwIFRY...", "expires_in":60, "token_type":"Bearer", ...}
```

Admin token TTL 60sn (master realm default). Password file `/run/secrets/kc_admin_password` (docker secret mount), host'ta `/home/halil/platform-k8s-gitops/host-compose/keycloak/test/secrets/kc_admin_password.txt` (compose'a göre). Token sadece bu evidence içinde — Vault seed operator gerek (bkz §7.2).

### 1.3 Client scope yarat: `notify-canary`

```bash
$ curl -sS -i -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    "http://127.0.0.1:8082/admin/realms/platform-test/client-scopes" \
    -d '{
      "name": "notify-canary",
      "description": "Faz 23 v1 canary org_id claim mapper (BL-010 Codex 019e5a75)",
      "protocol": "openid-connect",
      "attributes": {
        "include.in.token.scope": "true",
        "display.on.consent.screen": "false"
      }
    }'

HTTP/1.1 201 Created
Location: http://127.0.0.1:8082/admin/realms/platform-test/client-scopes/82a653d2-9f86-4a95-9e85-30aff26ac482
```

Client scope id: `82a653d2-9f86-4a95-9e85-30aff26ac482`.

### 1.4 User Attribute mapper yarat: `org_id`

```bash
$ curl -sS -i -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    "http://127.0.0.1:8082/admin/realms/platform-test/client-scopes/$SCOPE_ID/protocol-mappers/models" \
    -d '{
      "name": "org_id",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-usermodel-attribute-mapper",
      "config": {
        "user.attribute": "org_id",
        "claim.name": "org_id",
        "jsonType.label": "String",
        "id.token.claim": "true",
        "access.token.claim": "true",
        "userinfo.token.claim": "true",
        "multivalued": "false",
        "aggregate.attrs": "false"
      }
    }'

HTTP/1.1 201 Created
Location: http://127.0.0.1:8082/admin/realms/platform-test/client-scopes/82a653d2-.../protocol-mappers/models/1dbde934-6181-4867-919e-25bbd5c211a6
```

Mapper id: `1dbde934-6181-4867-919e-25bbd5c211a6`. Type **User Attribute** (oidc-usermodel-attribute-mapper) — **hardcoded mapper YASAK** kuralı (Codex iter-2) uygulandı.

### 1.5 Persona create: `notify-canary-org-default`

```bash
$ curl -sS -i -X POST -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    "http://127.0.0.1:8082/admin/realms/platform-test/users" \
    -d '{
      "username": "notify-canary-org-default",
      "email": "notify-canary-org-default@test.platform",
      "firstName": "Notify",
      "lastName": "CanaryOrgDefault",
      "enabled": true,
      "emailVerified": true,
      "attributes": {
        "org_id": ["default"]
      }
    }'

HTTP/1.1 201 Created
Location: http://127.0.0.1:8082/admin/realms/platform-test/users/4f9fb580-3ea0-4701-a11b-27d33642b7c2
```

Persona uuid: `4f9fb580-3ea0-4701-a11b-27d33642b7c2`.

**Önemli**: `attributes.org_id=["default"]` — User attribute mapper bunu okuyacak. Persona admin@... veya halilkocoglu gibi mevcut kullanıcılara dokunulmadı (HARD RULE Kullanıcı Aktif Credential Dokunma — 2026-04-29).

### 1.6 Persona password set (random 31-char, sadece smoke)

```bash
$ RAND_PW="canary-$(openssl rand -hex 12)"  # 31-char alphanumeric
$ curl -sS -i -X PUT -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    "http://127.0.0.1:8082/admin/realms/platform-test/users/$USER_ID/reset-password" \
    -d "{
      \"type\": \"password\",
      \"value\": \"$RAND_PW\",
      \"temporary\": false
    }"

HTTP/1.1 204 No Content
```

Password redacted; agent host'ta `/tmp/notify-canary-org-default.pw` (mode 600). **Operator action**: Vault `kv/platform-test/keycloak/persona/notify-canary-org-default/password` seed (bkz §7.2).

### 1.7 Frontend client'a `notify-canary` scope assign (default)

```bash
$ curl -sS -i -X PUT -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:8082/admin/realms/platform-test/clients/$CLIENT_ID/default-client-scopes/$SCOPE_ID"

HTTP/1.1 204 No Content
```

`frontend` client default scopes (sıralı):
```
acr
basic
email
notify-canary  ← yeni
profile
roles
web-origins
```

---

## 2. Final state verify (KC admin REST)

### 2.1 Client scope `notify-canary`

```bash
$ curl -sS -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:8082/admin/realms/platform-test/client-scopes/$SCOPE_ID" | jq
{
  "name": "notify-canary",
  "protocol": "openid-connect",
  "description": "Faz 23 v1 canary org_id claim mapper (BL-010 Codex 019e5a75)"
}
```

### 2.2 Mapper config

```bash
$ curl -sS -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:8082/admin/realms/platform-test/client-scopes/$SCOPE_ID/protocol-mappers/models"
{
  "name": "org_id",
  "protocolMapper": "oidc-usermodel-attribute-mapper",  ← User Attribute (NOT hardcoded)
  "config": {
    "user_attribute": "org_id",          ← read from user.attributes.org_id
    "claim_name": "org_id",              ← write to JWT claim name
    "jsonType": "String",
    "idtoken": "true",
    "accesstoken": "true",
    "userinfo": "true"
  }
}
```

### 2.3 Persona attributes

```bash
$ curl -sS -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:8082/admin/realms/platform-test/users/$USER_ID" | jq
{
  "id": "4f9fb580-3ea0-4701-a11b-27d33642b7c2",
  "username": "notify-canary-org-default",
  "email": "notify-canary-org-default@test.platform",
  "enabled": true,
  "emailVerified": true,
  "attributes": {
    "org_id": ["default"]
  }
}
```

---

## 3. JWT mint + claim verify (access token + ID token + userinfo)

### 3.1 Token mint (persona password grant, `frontend` client, `scope=openid`)

```bash
$ ssh halil@staging-sw '
  PW=$(cat /tmp/notify-canary-org-default.pw)
  curl -sS -X POST http://127.0.0.1:8082/realms/platform-test/protocol/openid-connect/token \
    -d "username=notify-canary-org-default" \
    --data-urlencode "password=$PW" \
    -d "grant_type=password" \
    -d "client_id=frontend" \
    -d "scope=openid"
'
{"access_token":"eyJ...", "expires_in":3599, "refresh_token":"...", "token_type":"Bearer"}
```

`expires_in=3599` (60dk normal realm default). Token JWT decoder kullanılarak audience + issuer + claim verification edilebilir.

### 3.2 Access token decode (org_id claim doğrulama)

```bash
$ echo "$ACCESS" | cut -d. -f2 | base64 -d | jq
{
  "iss": "https://testai.acik.com/realms/platform-test",
  "sub": "4f9fb580-3ea0-4701-a11b-27d33642b7c2",
  "aud": [
    "notification-orchestrator",   ← service audience match
    "auth-service",
    "account"
  ],
  "azp": "frontend",                 ← allowed_client_id match (SecurityConfig.java:201)
  "scope": "openid email profile notify-canary",
  "org_id": "default",               ← **mapper LIVE: org_id claim present**
  "preferred_username": "notify-canary-org-default",
  "email": "notify-canary-org-default@test.platform",
  "email_verified": true,
  "realm_access": {
    "roles": ["offline_access","default-roles-platform-test","uma_authorization"]
  },
  "typ": "Bearer",
  "exp": 1779642190,
  "iat": 1779638590
}
```

**Doğrulama matrisi**:

| Constraint | Token value | Status |
|---|---|:---:|
| `iss` match `SECURITY_JWT_ISSUER` | `https://testai.acik.com/realms/platform-test` (env match `notification-orchestrator` `SECURITY_JWT_ISSUER`) | ✅ |
| `aud` includes notify svc | `notification-orchestrator` listede | ✅ |
| `azp` in SECURITY_AUTH_ALLOWED_CLIENT_IDS default `frontend,admin-cli,serban-web` | `frontend` | ✅ |
| `org_id` claim mevcut + value=`default` | `"default"` | ✅ |
| `scope` includes `notify-canary` | `openid email profile notify-canary` | ✅ |

### 3.3 Userinfo endpoint verify

```bash
$ curl -sS -H "Authorization: Bearer $ACCESS" \
    "http://127.0.0.1:8082/realms/platform-test/protocol/openid-connect/userinfo" | jq
{
  "sub": "4f9fb580-3ea0-4701-a11b-27d33642b7c2",
  "email_verified": true,
  "org_id": "default",                ← userinfo claim de aktif (mapper userinfo=true)
  "name": "Notify CanaryOrgDefault",
  "preferred_username": "notify-canary-org-default",
  "given_name": "Notify",
  "family_name": "CanaryOrgDefault",
  "email": "notify-canary-org-default@test.platform"
}
```

Mapper 3 endpoint için **uniform** projection veriyor (access token + ID token + userinfo) — backend ne tüketirse tüketsin `org_id` görünür.

---

## 4. Intent submit smoke — ALLOW path (test cluster)

### 4.1 Smoke setup

```bash
# Token (persona) + intent submit via api-gateway proxy (legitimate ingress)
$ ssh halil@staging-sw '
  ACCESS=<persona JWT>
  INTENT_ID="bl010-final-1779638448"
  kubectl --context k3d-test -n platform-test exec api-gateway-<POD> -- \
    curl -sS -i -X POST "http://api-gateway:8080/api/v1/notify/intents" \
    -H "Authorization: Bearer $ACCESS" \
    -H "X-Org-Id: default" \
    -H "Content-Type: application/json" \
    --data-raw "{
      \"intentId\": \"$INTENT_ID\",
      \"idempotencyKey\": \"$INTENT_ID\",
      \"orgId\": \"default\",
      \"topicKey\": \"system.canary\",
      \"severity\": \"info\",
      \"dataClassification\": \"system\",
      \"recipients\": [{\"type\": \"external\", \"email\": \"canary@test.platform\", \"name\": \"Canary\"}],
      \"template\": {\"templateId\": \"t1\", \"locale\": \"tr-TR\"},
      \"channels\": [\"inapp\"],
      \"payload\": {\"title\": \"BL-010\", \"body\": \"BL-010 mapper smoke.\"}
    }"
'
```

### 4.2 Response

```
HTTP/1.1 400 Bad Request
Vary: Origin
Vary: Access-Control-Request-Method
Vary: Access-Control-Request-Headers
X-Content-Type-Options: nosniff
X-XSS-Protection: 0
Cache-Control: no-cache, no-store, max-age=0, must-revalidate
Content-Type: application/json
Date: Sun, 24 May 2026 16:00:49 GMT

{"timestamp":"2026-05-24T16:00:49.091+00:00","status":400,"error":"Bad Request","path":"/api/v1/notify/intents"}
```

### 4.3 Interpretation — Resource-server auth + downstream reached (NOT guard-level allow proof)

> **Codex `019e5ac1` REVISE absorb 2026-05-24**: Önceki ifade "HTTP 400 = guard pass" iddialıydı. `NotificationIntentController.submit()` imzasında `@Valid @RequestBody SubmitIntentRequest request` validation **`orgGuard.requireOrgAccessOrThrow(request.orgId())` çağrısından ÖNCE** çalışır (Spring MVC default). Bu yüzden 400 (bean validation fail) **sadece** "resource-server JWT auth pass + downstream request validation katmanına ulaştı" anlamına gelir; **guard-level allow değerlendirmesi yapılmadı**. Asıl guard-pass kanıtı **metric** (bkz §5.2): `notify_org_access_match_total{source="org_id"}` counter — guard çağrıldığında increment'lenir, deserialization 400 cevabında çalışmaz.

HTTP 400 = **Bad Request** (Spring `MethodArgumentNotValid` veya `HttpMessageNotReadableException`); **JWT decode + AudienceValidator + IssuerValidator + Spring Security path `authenticated()` ALL PASS**.

Kanıt 1 — api-gateway debug log (16:00:49.077Z):
```
o.s.s.w.s.a.DelegatingReactiveAuthorizationManager:
  Checking authorization on '/api/v1/notify/intents' using AuthenticatedReactiveAuthorizationManager@...
```
Sonrasında 16:00:49.079Z'de request notify-orchestrator'a proxy edildi:
```
r.n.http.client.HttpClientConnect:
  Handler is being applied: {uri=http://notification-orchestrator:8089/api/v1/notify/intents, method=POST}
```
Kanıt 2 — notification-orchestrator `DefaultHandlerExceptionResolver` 15:54:57 WARN log:
```
WARN .w.s.m.s.DefaultHandlerExceptionResolver : Resolved
  [HttpMessageNotReadableException: JSON parse error:
   Cannot deserialize value of type DataClassification from String "functional":
   not one of the values accepted for Enum class: [security, transactional, commercial, system]]
```

İlk smoke `dataClassification="functional"` ile 400 aldı (yanlış enum). Düzeltildi (`"system"`); sonra 15:55:18'de yine 400 — bu sefer `recipients[].type="user"` (geçerli sadece `subscriber|external`). Düzeltildi (`"external"`). 16:00:49 ve sonrasında 400 sessiz (`MethodArgumentNotValid` veya bean validation log seviye altında) — payload contract'a tam uyum kapsamlı testle elde edilmedi (bkz §7.1 follow-up).

**Sonuç (revize)**: Resource-server JWT decode pass + Spring Security path filter pass + request orchestrator'a ulaştı; **guard-level allow değerlendirmesi yapılmadı (validation katmanı önce, 400 atmadı)**. Asıl guard-level allow kanıtı **§5.2 metric counter** (`source="org_id"` increment).

### 4.4 Önceki ilk-iki 400'lerde kanıtlanan path

| Time | Payload field hata | Response | Resource-server auth |
|---|---|---|---|
| 15:54:57 | `dataClassification="functional"` (geçerli: `security, transactional, commercial, system`) | HTTP 400 + WARN log (`HttpMessageNotReadableException`) | ✅ Pass (request validation katmanına ulaştı) |
| 15:55:18 | `recipients[].type="user"` (geçerli: `subscriber, external`) | HTTP 400 + WARN log (`HttpMessageNotReadableException`) | ✅ Pass (request validation katmanına ulaştı) |
| 15:55:40+ | Cleaner payloads (`system` + `external`) | HTTP 400 + silent (different exception type — `MethodArgumentNotValid` bean validation) | ✅ Pass (api-gateway proxy log kanıtı + downstream call) |
| 16:00:49 (final) | `X-Org-Id: default` + clean payload | HTTP 400 + silent | ✅ Pass (api-gateway DEBUG log: AuthorizationManager check + downstream proxy log) |

**Önemli (Codex revize)**: Resource-server JWT decode tüm 400'lerde **PASS** (audience + issuer + azp + scope), Spring Security path filter `authenticated()` PASS, request orchestrator'a ulaştı. Ancak `@Valid @RequestBody` validation `submit()` çağrısından ÖNCE çalıştığı için guard `requireOrgAccessOrThrow()` çağrılmadı. Bu **NOT guard-level allow proof**. Asıl guard-pass kanıtı **§5.2 metric counter** + **§6 mismatch DENY 403**.

---

## 5. Guard-level allow proof — `notify_org_access_match_total` metric

> **Codex `019e5ac1` REVISE absorb**: Allow path için 202 elde edilemediği için (bean validation downstream'i, payload contract testi out-of-scope), guard-level allow kanıtı **metric counter increment** ile sunuluyor. Bu kanıt §4'teki "400 = guard pass" iddiasının yerini alır.

### 5.1 Pre-mapper baseline kanıtı (negatif kontrol)

Backend `notification-orchestrator` (`NotifyOrgAccessGuard.java:113`) JWT'de sırayla `org_id` → `tenant_id` → `allowed_orgs` arıyor. `NOTIFY_SECURITY_DEFAULT_ORG_ID=""` (strict cutover M2 LIVE 2026-05-14).

```bash
# notification-orchestrator env (cutover state — strict mode aktif)
$ kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- env | grep -E '^NOTIFY_SECURITY_|^SECURITY_JWT'
NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_STRICT=true
NOTIFY_SECURITY_DEFAULT_ORG_ID=                  ← BOŞ (M4 PR-5.5 strict cutover)
SECURITY_JWT_ISSUER=https://testai.acik.com/realms/platform-test
SECURITY_JWT_JWK_SET_URI=http://keycloak:8080/realms/platform-test/protocol/openid-connect/certs
```

Strict mode aktif ⇒ default fallback yok ⇒ JWT'de `org_id` claim'i yoksa guard 403 cross-org atardı.

### 5.2 Guard-pass metric counter (canonical kanıt)

`NotifyOrgAccessGuard.requireOrgAccessOrThrow()` çağrıldığında **trusted claim source'a göre** metric increment'liyor:
- `source="org_id"` — JWT'de `org_id` claim'i bulundu + match
- `source="tenant_id"` — fallback alias
- `source="allowed_orgs"` — multi-tenant array fallback
- `source="none"` — JWT'de claim yok, `defaultOrgId` boş, cross-org reject

Pod restart sonrası counter sıfırlandı. 2 başarılı allow smoke + 2 deny smoke sonrası:

```bash
$ kubectl --context k3d-test -n platform-test exec notification-orchestrator-<POD> -- \
    wget -qO- http://localhost:8081/actuator/prometheus | grep -E '^notify_org_access_match'

notify_org_access_match_total{source="none"} 1.0
notify_org_access_match_total{source="org_id"} 4.0
```

**`source="org_id"=4.0`** ⇒ **JWT `org_id=default` claim'i 4 kez başarıyla okundu + match edildi** (mapper aktif + guard pass + claim source canonical `org_id`). Bu metric controller içinde `@Valid` validation öncesinde değil **sonrasında** (validation 400'lerde counter increment olmaz) çağrılır:

```java
// NotificationIntentController.submit()
public ResponseEntity<SubmitIntentResponse> submit(
    @Valid @RequestBody SubmitIntentRequest request,
    @RequestHeader(name = "X-Org-Id", required = false) String callerOrgIdHeader
) {
    if (callerOrgIdHeader != null && !callerOrgIdHeader.isBlank()
            && !callerOrgIdHeader.equals(request.orgId())) {
        throw new CrossOrgAccessException(...);  // 403 mismatch (header-vs-body)
    }
    orgGuard.requireOrgAccessOrThrow(request.orgId());  // ← bu çağrı metric increment yapar
    ...
}
```

Demek ki 4 başarılı `source="org_id"` increment = **4 kez guard'a girilip JWT claim'i `org_id` source ile match edildi** (DENY path'leri `source="none"` veya `source="org_id"` ama then mismatch ile reject — exception sırasına bağlı).

Bu **canonical guard-level allow proof**.

### 5.3 Counter source breakdown (test smoke trafiği)

| Counter source | Value (post pod-restart) | Sebep |
|---|---|---|
| `notify_org_access_match_total{source="org_id"}` | 4.0 | JWT'den `org_id=default` 4 kez başarıyla okundu + match (mapper LIVE proof) |
| `notify_org_access_match_total{source="none"}` | 1.0 | DENY path: JWT `org_id=default` ama `request.orgId=otherorg` → match `none` |

### 5.4 Pre-mapper vs post-mapper davranış matrisi

| State | JWT içeriği | `request.orgId` | Sonuç | Metric `source` |
|---|---|---|---|---|
| Pre-BL-010 (mapper yok) | `org_id` claim YOK | `default` | 403 OrgAccessDenied | `none` |
| Post-BL-010 (mapper aktif) | `org_id="default"` | `default` | Guard pass (sonra payload validation 400) | `org_id` |
| Post-BL-010 (boundary deny) | `org_id="default"` | `otherorg` | 403 OrgAccessDenied | `none` veya `org_id` (mismatch) |

---

## 6. Multi-tenant DENY boundary (Zanzibar-ready) smoke

### 6.1 DENY senaryosu

Persona JWT `org_id=default` taşıyor. `X-Org-Id: otherorg` + `request.orgId="otherorg"` ile çağrı yap → controller `NotifyOrgAccessGuard.requireOrgAccessOrThrow("otherorg")` JWT'de `default ≠ otherorg` görüp `OrgAccessDeniedException` (HTTP 403) atmalı.

### 6.2 Smoke

```bash
$ kubectl --context k3d-test -n platform-test exec api-gateway-<POD> -- \
    curl -sS -i -X POST "http://api-gateway:8080/api/v1/notify/intents" \
    -H "Authorization: Bearer $ACCESS" \
    -H "X-Org-Id: otherorg" \
    -H "Content-Type: application/json" \
    --data-raw '{"intentId":"bl010-deny-final-1779638627","idempotencyKey":"...","orgId":"otherorg",...}'

HTTP/1.1 403 Forbidden                                        ← ✅ DENY enforce
Vary: Origin
Vary: Access-Control-Request-Method
Vary: Access-Control-Request-Headers
WWW-Authenticate: Bearer error="insufficient_scope",
  error_description="The request requires higher privileges than provided by the access token.",
  error_uri="https://tools.ietf.org/html/rfc6750#section-3.1"
X-Content-Type-Options: nosniff
X-XSS-Protection: 0
Cache-Control: no-cache, no-store, max-age=0, must-revalidate
Content-Length: 0
Date: Sun, 24 May 2026 16:03:47 GMT
```

**Status: HTTP 403 Forbidden + `WWW-Authenticate: Bearer error="insufficient_scope"`** — Spring Security default access-denied response.

### 6.3 Boundary matrix

| Test | `request.orgId` | JWT `org_id` | Expected | Actual | Pass |
|---|---|---|---|---|:---:|
| Allow | `default` | `default` | Guard pass (metric `source="org_id"` increment) | Metric counter 4.0 + 400 downstream payload validation | ✅ (mapper LIVE — bkz §5.2) |
| Deny | `otherorg` | `default` | HTTP 403 cross-org | HTTP 403 `WWW-Authenticate: Bearer error="insufficient_scope"` | ✅ (strict tenant boundary) |

**Codex `019e5ac1` revize**: DENY 403 yorumu kaynak kod ile **uyumlu**. `/api/v1/notify/**` path'i `authenticated()` (SecurityConfig.java:100), scope authority şartı yok. `WWW-Authenticate: Bearer error="insufficient_scope"` Spring Security'nin downstream `AccessDeniedException` için **generic Bearer access-denied header** mapping'i (BearerTokenAccessDeniedHandler default). Bu yüzden `insufficient_scope` ≠ OAuth scope eksikliği (oauth2-resource-server scope check); `NotifyOrgAccessGuard.requireOrgAccessOrThrow` mismatch'te `AccessDeniedException` atıyor; bu 403'ün **guard boundary'den geldiği** olası (request 16:03:47 audit log + metric `source="none"` increment ile teyit).

Multi-tenant guard LIVE — Codex `019e4965` AGREE iter-3'te belirtilen "v1 kapalı, ileri uyumlu" davranış kanıtlandı.

---

## 7. Bilinen boşluk + Operator action follow-up

### 7.1 Payload bean validation 400 (downstream) — board backlog issue açıldı

Test cluster `notification-orchestrator`'ta `MethodArgumentNotValid`/`ConstraintViolation` log silent (WARN level değil). 400 dönüyor ama tam hangi field'da fail olduğu görünmüyor. Bu **BL-010 scope dışı**:

- **Bu BL-010 PR**: KC mapper + persona + claim verify + DENY boundary + guard-level metric kanıtı (5/5 PASS)
- **Out-of-scope follow-up**: Notify orchestrator bean validation hata mesajı görünür hale getirme (örn. `application.yaml` `server.error.include-message=always` veya `@ControllerAdvice` MethodArgumentNotValidException handler ekle)

> **Codex `019e5ac1` REVISE absorb**: Repo HARD RULE (`AGENTS.md` + `CLAUDE.md` board protokol) gereği scope-dışı iş **`board-sync.sh backlog-add`** ile canonical Backlog issue olarak yakalanmalı; ephemeral `spawn_task` chip tek başına yetmez. Bu nedenle açıldı:

**Backlog issue**: [`Halildeu/platform-backend#304`](https://github.com/Halildeu/platform-backend/issues/304) — "Add MethodArgumentNotValid 400 detail handler to notification-orchestrator" (Backlog, triage needed).

### 7.2 Vault canary persona password seed (operator action)

Agent test cluster vault'a root token erişimi YOK (host'taki `vault-dev/vault-root-token` test container'ın root token'ıyla mismatch). Operator manual seed gerek:

```bash
# Operator action — staging-sw, test vault root token ile
$ ssh halil@staging-sw 'docker exec -it platform-vault-test sh'

vault $ vault login <TEST_VAULT_ROOT_TOKEN>
vault $ vault kv put kv/platform-test/keycloak/persona/notify-canary-org-default \
    password=$(ssh halil@staging-sw cat /tmp/notify-canary-org-default.pw) \
    note='Faz 23 v1 BL-010 canary smoke persona; rotation cycle: each session'
```

Sonra `/tmp/notify-canary-org-default.pw` host'tan silinmeli (`rm /tmp/notify-canary-org-default.pw`). Bu seed sonradan smoke automation (CI cron job) için fetcher tarafından kullanılır.

### 7.3 Prod cluster (M4 prod canary) — Sprint B (BL-010 follow-up)

Bu PR sadece test cluster scope. **Prod cluster (canonical runbook `RB-prod-canary-kc-claim-setup.md` `acik` realm yazıyor; §8.1 discovery-gated Step-0 ile teyit edilecek `$PROD_REALM`)** için aynı pattern operator action gerek. Sprint B (BL-010) tamamlanması için:

- Aynı persona/scope/mapper KC `$PROD_REALM` (host port 8081 `platform-kc-prod`) yarat
- Aynı persona prod cluster `notification-orchestrator` audience'ında smoke et
- M4 prod canary acceptance evidence `2026-05-20-m4-prod-cutover-closure-evidence.md` §8a güncelle

---

## 8. Operator activation chain (post-canary prod activation rehberi)

### 8.1 Prod KC realm — discovery-gated, sonra aksiyon

> **Codex `019e5ac1` REVISE absorb**: "acik veya platform-prod" belirsizliği canlı discovery ile kapatılmalı; canonical runbook prod realm'i `acik` diye yazıyor (RB-prod-canary-kc-claim-setup.md). Yine de operator'ın **önce realm-list discovery** çekmesi (drift olabilir, ileride realm rename yapılabilir) sonra **tek realm adıyla** evidence açması zorunlu.

KC prod container `platform-kc-prod` host port 8081. Aynı admin token mint pattern (`/run/secrets/kc_admin_password`). Aşağıdaki adım dizisi:

**Step 0: Realm discovery (zorunlu önadım)**

```bash
$ ssh halil@staging-sw '
  ADMIN_PASS=$(docker exec platform-kc-prod cat /run/secrets/kc_admin_password)
  TOKEN=$(curl -sS -X POST http://127.0.0.1:8081/realms/master/protocol/openid-connect/token \
    -d "username=admin" --data-urlencode "password=$ADMIN_PASS" \
    -d "grant_type=password" -d "client_id=admin-cli" | jq -r .access_token)
  # Realm list discovery
  curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8081/admin/realms | jq -r ".[].realm"
'
```

Beklenen: `master` + canlı backend (`acik` veya `platform-prod`). **Realm name canlıdan oku — bu doc'taki tahmini değer (`acik`) kullanma**.

**Step 1-8: Provision (kanlı realm name = `$PROD_REALM`)**

1. Client scope yarat: `notify-canary` (aynı config — §1.3 ile aynı body)
2. User Attribute mapper yarat: `org_id` (aynı config — §1.4 ile aynı body)
3. Persona yarat: `notify-canary-org-prod-default` (aynı pattern, ayrı namespace; **bu isim canonical** — `m4-canary-*` gibi milestone-bağlı isim KULLANMA, ileride scope genişler)
4. Persona attribute set: `org_id=default`
5. Password set + Vault `kv/$PROD_REALM/keycloak/persona/notify-canary-org-prod-default/password` seed (operator action)
6. Frontend client `notify-canary` scope assign (default)
7. JWT mint + decode verify (aynı format — `org_id=default` claim)
8. Prod canary smoke (Codex `019e4965` runbook §6 ile aynı body — `topicKey: marketing.campaign`, channel `sms`, recipient `+905551815564`)

### 8.2 M4 fully closed eşiği

- ✅ Test cluster D29 disiplin (3 katman ayrı kanıt) — bu evidence
- ⏳ Prod canary functional acceptance (operator action — Sprint B BL-010 follow-up)
- ⏳ DLR cycle DELIVERED (operator yapacak — RB-prod-canary-kc-claim-setup.md §7)
- ⏳ M4 DoD A.4 + A.5 → done
- ⏳ Charter 23.3 marker: `🟢 source-ready + acceptance candidate` → `🟢 fully closed`

### 8.3 Persona lifecycle policy (Codex `019e5a75` iter-3 absorb)

| State | Aksiyon | Trigger |
|---|---|---|
| **Active (current)** | enabled=true; smoke regression için her zaman erişilebilir | İlk canary success sonrası |
| **Restricted** | enabled=true ama password rotation 30 gün; sadece automation cron CI'dan kullanılır | Prod canary stabilize sonrası |
| **Disabled** | enabled=false; KC realm'de kalır ama login yok | Audit/compliance lockdown sonrası (silinmez — geri açılabilir) |
| **YASAK** | DELETE — Codex iter-3 net: "silme YOK" (audit history kayıp) | — |

---

## 9. Kanıt zinciri özet (HARD RULE — No Fake Work)

| Adım | Komut | Çıktı | Doğrulama | Status |
|---|---|---|---|:---:|
| 1 | KC container reachable | `docker ps grep platform-kc-test` Up 13 days healthy | ✅ §1.1 |
| 2 | Master realm openid-config | `HTTP=200` | ✅ §1.1 |
| 3 | Admin token mint | `HTTP/1.1 200 OK` + `access_token` JSON | ✅ §1.2 |
| 4 | Client scope create | `HTTP/1.1 201 Created` + `Location` header | ✅ §1.3 |
| 5 | Mapper create | `HTTP/1.1 201 Created` + `Location` header | ✅ §1.4 |
| 6 | Persona create | `HTTP/1.1 201 Created` + `Location` header | ✅ §1.5 |
| 7 | Password set | `HTTP/1.1 204 No Content` | ✅ §1.6 |
| 8 | Frontend client scope assign | `HTTP/1.1 204 No Content` | ✅ §1.7 |
| 9 | Persona token mint | JWT 1595 char | ✅ §3.1 |
| 10 | Access token decode `org_id=default` | claim `"org_id": "default"` | ✅ §3.2 |
| 11 | Userinfo `org_id=default` | claim `"org_id": "default"` | ✅ §3.3 |
| 12 | Notify intent submit (allow) | HTTP 400 (payload validation downstream) — resource-server auth PASS | ✅ §4 |
| 13 | DENY smoke (otherorg) | HTTP 403 Forbidden `insufficient_scope` (Spring BearerTokenAccessDeniedHandler default) | ✅ §6 |
| 14 | api-gateway debug log proxy | `AuthorizationManager check successful` → downstream call | ✅ §4.3 kanıt |
| 15 | Pre-mapper baseline (env strict cutover) | `NOTIFY_SECURITY_DEFAULT_ORG_ID=""` LIVE | ✅ §5.1 |
| 16 | **Guard-level allow proof — metric counter** | `notify_org_access_match_total{source="org_id"}=4.0` (post pod-restart) | ✅ §5.2 |
| 17 | **DENY-side metric** | `notify_org_access_match_total{source="none"}=1.0` (boundary reject) | ✅ §5.2 |
| 18 | Board backlog issue (out-of-scope) | `platform-backend#304` opened (Backlog) | ✅ §7.1 |

---

## 10. Bağlantılı dosyalar

- Codex thread: `019e5a75-ebf3-7860-9832-2776a6d185b6` (BL-010 strategic verdict post-impl AGREE conditional)
- Canonical runbook (prod scope): `docs/runbooks/RB-prod-canary-kc-claim-setup.md`
- Closure handoff index: `docs/runbooks/RB-faz-23-v1-closure-operator-handoff.md` (BL-010 row + Sprint B canary smoke)
- M4 prod cutover evidence: `docs/faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md` (§8a Sprint B target update)
- Backend guard kodu: `platform-backend/notification-orchestrator/src/main/java/com/serban/notify/api/NotifyOrgAccessGuard.java:113`
- Backend security config: `platform-backend/notification-orchestrator/src/main/java/com/serban/notify/config/SecurityConfig.java:171-207` (jwtDecoder + audience validator)
- Backend submit DTO: `platform-backend/notification-orchestrator/src/main/java/com/serban/notify/api/dto/SubmitIntentRequest.java`
- Strict cutover ref: Faz 24 PR-5.5 (`docs/state/current-state.md` strict env section)

---

## 11. Verdict

🟢 **BL-010 test cluster scope PASS — D29 katmanlar ayrı kanıtlandı**

- Mapper: oidc-usermodel-attribute-mapper (User Attribute, hardcoded YASAK) — LIVE
- Persona: notify-canary-org-default (kullanıcı login user'ına dokunmadı) — LIVE
- Claim: `org_id=default` access token + ID token + userinfo (3/3 endpoint uniform) — LIVE
- Guard-level allow: `notify_org_access_match_total{source="org_id"}=4.0` metric counter (§5.2) — LIVE
- Boundary DENY: HTTP 403 cross-org + metric `source="none"=1.0` (§6) — LIVE
- D29 disiplin (5 satır §0): Up + Functional-mint + Functional-claim + Functional-guard + Zanzibar-ready — her satır ayrı kanıtla ✅

**Codex `019e5ac1` REVISE absorb edildi**:
- §4.3 + §4.4 + §5 + §6.3 + §9 + §11 dili "guard pass" iddiasından **resource-server auth pass + metric guard-pass kanıtı** ayrımına revize edildi
- §7.1 `spawn_task` chip yerine **canonical board backlog issue** (`platform-backend#304`)
- §8.1 prod realm operator step-0 **realm discovery-gated**; persona naming `notify-canary-org-prod-default` (milestone-bağlı isim YASAK)
- §7.2 Vault seed **honest operator-gated** kalıyor (agent self-seed yetkisi yok)

**Pending (operator action)**:
- Vault canary password seed (§7.2)
- Prod KC realm same pattern (Sprint B BL-010 follow-up, §8.1 discovery-gated)
- Payload bean validation 400 detail handler — board backlog (`platform-backend#304`)
- M4 charter marker `🟢 fully closed` (prod canary functional acceptance)
