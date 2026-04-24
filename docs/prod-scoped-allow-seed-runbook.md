# Prod Non-SuperAdmin Scoped Allow Seed — Runbook

> **Hedef**: Prod `canary-restricted@stage.local` token ile `ai.acik.com/api/v1/variants?gridId=1204` → **200** (şu an `403` scoped deny).
> **Codex verdict (threads 019dbca5 + 019dbca8 + 019dbcab)**: T+60 PASS sonrası (a) seed, ama uid-static drift ara kapısı önce temizlenmeli. Operasyonel: **T+24h ertelendi** (2026-04-25 01:25 UTC+3 sonrası sakin pencere).
> **Risk**: Prod KC client mapper + user attribute + OpenFGA tuple — 7 adım, revertable.
> **Referans**: `docs/state/current-state.md` §"Prod authz scope/permission seed" drift + Session 26 canary-restricted authz/me `permissions_count=7` ama `allowedScopes=[]` tespit.

---

## 0. Ön-Koşul Kanıtları

### Test realm pattern (working baseline)
```bash
ssh staging-sw
# Test canaryscope user:
docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master --user admin --password "${KC_ADMIN_PW_TEST}"
docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh get users -r platform-test \
  --query "username=canaryscope" | jq '.[0] | {id,username,email,attributes}'
# Beklenen: attributes.userId = ["3"]
```

### Prod canary-restricted broken state
```bash
# Prod:
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh get users -r serban \
  --query "username=canary-restricted@stage.local" | jq '.[0] | {id,username,attributes,realmRoles,clientRoles}'
# Gerçek: attributes=null, roles=null (→ allowedScopes=[])
```

## 1. uid-static Mapper Drift Fix (ia)

**Problem**: `canary-load` client'ta **static `uid-static=920001` protocol mapper** var → her user aynı userId basıyor → OpenFGA user mapping kırık.

### 1.1 Backup
```bash
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh get \
  clients/6ace51a1-7d07-4200-b192-8a5191f245e7/protocol-mappers/models \
  -r serban > /tmp/canary-load-mappers.backup.$(date +%Y%m%d-%H%M).json
```

### 1.2 Static Mapper ID Tespit
```bash
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh get \
  clients/6ace51a1-7d07-4200-b192-8a5191f245e7/protocol-mappers/models \
  -r serban | jq '[.[] | select(.name | test("uid|userId"; "i")) | {id,name,protocolMapper,claim_value:.config."claim.value",user_attribute:.config."user.attribute"}]'
```
`claim.value` dolu olan satır = static mapper.

### 1.3 Static Mapper Delete
```bash
UID_STATIC_ID=<1.2 output id>
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh delete \
  clients/6ace51a1-7d07-4200-b192-8a5191f245e7/protocol-mappers/models/${UID_STATIC_ID} \
  -r serban
```

### 1.4 Dynamic Mapper Create/Update
```bash
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh create \
  clients/6ace51a1-7d07-4200-b192-8a5191f245e7/protocol-mappers/models \
  -r serban \
  -s name=uid-claim \
  -s protocol=openid-connect \
  -s protocolMapper=oidc-usermodel-attribute-mapper \
  -s 'config."user.attribute"=userId' \
  -s 'config."claim.name"=uid' \
  -s 'config."jsonType.label"=String' \
  -s 'config."id.token.claim"=true' \
  -s 'config."access.token.claim"=true' \
  -s 'config."userinfo.token.claim"=true'
```

### 1.5 Rollback (Fail Durumunda)
```bash
# Yeni dynamic mapper delete:
UID_CLAIM_NEW_ID=<1.4 output id>
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh delete \
  clients/6ace51a1-7d07-4200-b192-8a5191f245e7/protocol-mappers/models/${UID_CLAIM_NEW_ID} \
  -r serban

# Static mapper restore (backup'tan):
STATIC_PAYLOAD=$(jq -c '.[] | select(.name | test("uid-static"; "i"))' /tmp/canary-load-mappers.backup.*.json)
docker exec -i platform-kc-prod /opt/keycloak/bin/kcadm.sh create \
  clients/6ace51a1-7d07-4200-b192-8a5191f245e7/protocol-mappers/models \
  -r serban -f - <<<"$STATIC_PAYLOAD"
```

## 2. User Attribute Seed (unique userId)

### 2.1 canary-restricted
```bash
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh update \
  users/d8fae312-b69f-464e-a9da-c276894b950a \
  -r serban \
  -s 'attributes.userId=["920002"]'
```

### 2.2 Diğer canary-load token kullanıcıları (testuser, admin@example.com)
Her kullanıcıya **unique** userId:
```bash
# testuser:
TESTUSER_ID=$(docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh get users \
  -r serban --query "username=testuser" | jq -r '.[0].id')
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh update \
  users/$TESTUSER_ID -r serban -s 'attributes.userId=["920003"]'
# ...vb.
```

### 2.3 Rollback
```bash
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh update \
  users/d8fae312-b69f-464e-a9da-c276894b950a \
  -r serban \
  -s 'attributes.userId=null'
```

## 3. Token Claim Verify

```bash
source ~/bootstrap-drill/prod-creds.env
TOKEN=$(curl -sk -X POST 'https://ai.acik.com/realms/serban/protocol/openid-connect/token' \
  -d 'grant_type=password' -d 'client_id=canary-load' \
  -d "client_secret=${CANARY_LOAD_SECRET}" \
  -d 'username=canary-restricted@stage.local' \
  -d "password=${CANARY_LOAD_USER_PW}" | jq -r .access_token)

# Token decode:
echo "$TOKEN" | cut -d. -f2 | tr '_-' '/+' | base64 -d 2>/dev/null | jq '{sub,preferred_username,uid,userId}'
# Beklenen: uid="920002" (DYNAMIC) ve preferred_username="canary-restricted@stage.local"
```

Başka bir user ile test:
```bash
TOKEN2=$(curl ... username=testuser ...)
echo "$TOKEN2" | cut -d. -f2 | ... | jq .uid
# Beklenen: 920003 (farklı userId — static drift fix kanıtı)
```

## 4. KC Role / Composite Seed

### 4.1 VARIANT_SCOPE_CANARY realm role oluştur (yoksa)
```bash
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh create roles \
  -r serban -s name=VARIANT_SCOPE_CANARY \
  -s "description=Variant service scoped canary allow (grid 1204)"
```

### 4.2 canary-restricted'a role assign
```bash
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh add-roles \
  -r serban \
  --uusername canary-restricted@stage.local \
  --rolename VARIANT_SCOPE_CANARY
```

### 4.3 Rollback
```bash
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh remove-roles \
  -r serban \
  --uusername canary-restricted@stage.local \
  --rolename VARIANT_SCOPE_CANARY
# Role kendisi silinmek için:
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh delete roles/VARIANT_SCOPE_CANARY -r serban
```

## 5-pre. Permission-Service DB Seed (Session 28 Keşif)

> **Kritik keşif** (Codex thread `019dbdf2`): KC + OpenFGA seed tek başına **yetersiz**. variant-service `authz/me` için **permission-service hub**'a çağrı yapıyor; allowedScopes + permissions Spring Boot-side DB-backed. OpenFGA `Check` muhtemelen ikincil resource-level doğrulama için.

### Gerçek Blocker Yeri

- `variant-service` log: `Resolved variant authz context: userId=920002 ... permissionsCount=0 isAdmin=false`
- Token'da `VARIANT_SCOPE_CANARY` role görünüyor
- authz/me `{superAdmin: false, allowedScopes: [], permissions_count: 0}` → scope+permission hub-side boş

### Schema (canlı keşif)

permission_db tabloları:
- `permissions` (id, code, module_name) → `VARIANTS_READ` id=45
- `roles` (id, name)
- `role_permissions` (role_id, permission_id)
- `user_role_assignments` (user_id, company_id, project_id, warehouse_id, role_id, active)
- `scopes` (id, scope_type, ref_id) — unique (scope_type, ref_id)
- `user_permission_scope` (user_id, permission_id, scope_id) — direct user-perm-scope

### 5-pre.1 Seed SQL (idempotent, yetki gerektirir)

```sql
-- permission_db içinde platform user'la execute
BEGIN;
-- Scope PROJECT/1204 (yoksa)
INSERT INTO scopes(scope_type, ref_id, description)
  VALUES('PROJECT', 1204, 'Canary scoped allow — scoped variant seed 2026-04-24')
  ON CONFLICT (scope_type, ref_id) DO NOTHING;

-- User 920002'ye VARIANTS_READ@PROJECT/1204 grant
INSERT INTO user_permission_scope(user_id, permission_id, scope_id)
  SELECT 920002, 45, s.id FROM scopes s
  WHERE s.scope_type='PROJECT' AND s.ref_id=1204
  ON CONFLICT (user_id, permission_id, scope_id) DO NOTHING;
COMMIT;

-- Verify
SELECT * FROM scopes WHERE scope_type='PROJECT' AND ref_id=1204;
SELECT * FROM user_permission_scope WHERE user_id=920002;
```

### 5-pre.2 Execute Komutu

```bash
ssh staging-sw
docker exec -i platform-pg-prod psql -U platform -d permission_db <<'SQL'
[yukarıdaki BEGIN..COMMIT bloğu]
SQL
```

### 5-pre.3 Rollback

```sql
DELETE FROM user_permission_scope WHERE user_id=920002 AND permission_id=45;
DELETE FROM scopes WHERE scope_type='PROJECT' AND ref_id=1204
  AND NOT EXISTS (SELECT 1 FROM user_permission_scope WHERE scope_id=scopes.id);
```

## 5. OpenFGA Tuple Seed (muhtemelen ikincil, check için)

### 5.1 Prod OpenFGA container
```bash
# prod OpenFGA pod (k3d-prod cluster):
docker exec k3d-prod-server-0 kubectl -n platform-prod get pods -l app.kubernetes.io/name=openfga
# Beklenen: openfga-0 Running

# Prod Store ID (Session 26 kanıt: ERP_OPENFGA_STORE_ID=01KPVGQCTZ3K5PHHM1HY0PMN13)
```

### 5.2 Tuple Write
```bash
# fga CLI openfga container içinde:
docker exec k3d-prod-server-0 kubectl -n platform-prod exec openfga-0 -- fga tuple write \
  --store-id 01KPVGQCTZ3K5PHHM1HY0PMN13 \
  --model-id 01KPVGQCY4XGRVAHWATQ4PQ974 \
  user:920002 scope_allow grid:1204
```

### 5.3 Rollback
```bash
docker exec k3d-prod-server-0 kubectl -n platform-prod exec openfga-0 -- fga tuple delete \
  --store-id 01KPVGQCTZ3K5PHHM1HY0PMN13 \
  user:920002 scope_allow grid:1204
```

## 6. Public Smoke Kanıt

```bash
# Fresh token (user attribute seed sonrası uid=920002):
TOKEN=$(curl -sk -X POST 'https://ai.acik.com/realms/serban/protocol/openid-connect/token' \
  -d 'grant_type=password' -d 'client_id=canary-load' \
  -d "client_secret=${CANARY_LOAD_SECRET}" \
  -d 'username=canary-restricted@stage.local' \
  -d "password=${CANARY_LOAD_USER_PW}" | jq -r .access_token)

# Smoke:
curl -sk -H "Authorization: Bearer $TOKEN" https://ai.acik.com/api/v1/authz/me | jq '.allowedScopes'
# Beklenen: [{"scopeType":"PROJECT","scopeRefId":1204}]  ← yeni
# Önceki: []

curl -sk -o /dev/null -w "variants(1204) → %{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" "https://ai.acik.com/api/v1/variants?gridId=1204"
# Beklenen: 200 (şu an 403)

curl -sk -o /dev/null -w "variants(test-grid) → %{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" "https://ai.acik.com/api/v1/variants?gridId=test-grid"
# Beklenen: 403 (scoped deny korundu)
```

## 7. Current-state.md Delta + PR

```markdown
## Live Delta — Session X (tarih UTC+3)

### (a) Prod scoped allow seed — CANLI KANITLI (Session 27 sonrası uid-static drift fix sonrası)

- KC canary-load client: uid-static mapper → uid-claim dynamic (`user.attribute=userId`)
- canary-restricted user: `attributes.userId=["920002"]`
- Realm role: `VARIANT_SCOPE_CANARY` oluşturuldu + canary-restricted'a atandı
- OpenFGA tuple: `user:920002 scope_allow grid:1204` write edildi
- Smoke: `authz/me.allowedScopes=[{PROJECT,1204}]`, `variants(1204)=200`, `variants(test-grid)=403` ✅
- Session önceki "scope_allow seed açık" blocker CLOSED

### Sayaç update
- prod-workload-gitops: 88 → 92 (D29 Zanzibar-ready threshold geçti)
- Weighted: %89 → %91
```

---

## Timeline

- **T0** = 2026-04-24 01:25 UTC+3 Faz 13 Hybrid GO
- **T+60 PASS** = 02:23 UTC+3 (runtime sağlıklı, rollback-window sakin)
- **T+24h** = 2026-04-25 01:25 UTC+3 (seed execute penceresi açılır)
- **T+72h** = 2026-04-27 01:25 UTC+3 rollback-window kapanış

## Rollback-Window İçinde Yürütmenin Riski

- 3 farklı subsystem yazma (KC client, KC user, OpenFGA)
- Rollback multi-step (uid-static restore + user attr clear + role remove + tuple delete)
- Partial state riski: KC role eklenirse OpenFGA tuple fail olursa authz/me 7 permission + scope boş pattern (runtime etki sınırlı)

## Güvenlik

- Her adım revertable (backup + rollback komut)
- Public smoke kanıt sonrası commit (eşleşmezse commit yok)
- Session başka user'ları kirletmez (sadece canary-restricted + specific canary-load client)

## Related

- Codex threads: `019dbca5`, `019dbca8`, `019dbcab` (Session 28 paralel cleanup + (a) seed strateji)
- Current-state §"Prod non-superAdmin scoped allow seed" HIGH drift
- PR #71 Faz 13 Hybrid GO
