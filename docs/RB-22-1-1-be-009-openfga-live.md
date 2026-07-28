# Runbook — Faz 22.1.1: BE-009 OpenFGA Live (Up/Functional/Secured/Zanzibar-ready)

> **Sprint**: "Prod post-cutover compliance" — Faz 22.1.1 milestone (Codex 019de00f revize)
> **Owner**: Engineering (platform-backend BE-009 + platform-k8s-gitops manifest reconcile)
> **Status**: ⚠️ **BLOCKED — pending III review** (Codex `019ded8d` AGREE post-A0 probe, 2026-05-03 Session 37)
> **Status detail**: 22.1.1 milestone Codex AGREE ile **22.1.1a (Runtime prep — current) + 22.1.1b (Live authz acceptance — blocked)** olarak bölündü
>
> **⚠️ ACCEPTANCE EXECUTION GUIDANCE**:
>  - **22.1.1a Runtime prep (current)**: image build (sha-451422e, sha256:89be36653bf6...) var; manifest skeleton var (gitops PR #312); application config var (PR #55 application-k8s.yml MERGED to sub-branch); tuple seed JSON committed (gitops PR #317); bu runbook committed
>  - **22.1.1b Live acceptance (blocked)**: 22 dosya implementation (controller/authz/interceptor/DTO/model) **source-of-truth branch'inde commit edilmemiş** (lokal halil@machine working tree dirty state). Image content probe match=0 (jar'da class yok). Acceptance D29 4-katman execute edilemez — endpoint mevcut değil
>  - **III review sub-task açılacak**: lokal 22 dosya code review + artifact parity. Verdict path: I-controlled (PR uygunluk) veya II-confirmed (scope reset)
>  - **3-tier drift A0 probe** (Codex revize): code (uncommitted varsayım `viewer`/`manager`) + seed JSON (gitops PR #317 `admin`/`viewer`) + live model (`can_view`/`can_manage`/`can_edit`/`blocked`) hiçbiri uyuşmuyor. III review verdict sonrası A1.1-prime relation alignment commit (`bf59897` lokal, push edilmedi) yeniden değerlendirilir
>
> **Bu runbook'taki tuple seed shape ve acceptance command'ları III review sonrası canonical shape'e çekilecek.** Şu an execute edilmemeli.
>
> **Reference**:
>  - ADR-0012-EA: `docs/adr/0012-EA-endpoint-admin-governance-charter.md`
>  - Codex thread `019ded8d-f321-71d1-829b-c4dcf9ac4b78` — drift backlog audit + 22.1.1a/b split + A0 probe + REVISE→AGREE chain
>  - Session 37 truth: `docs/state/current-state.md` (Live Delta — Session 37 22.1.1a/b milestone split)
>  - platform-backend: `endpoint-admin-service/` (BE-009 IMPLEMENTATION PENDING — III review)
>  - tuple seed: `bootstrap/openfga/endpoint-admin-tuples.json` (relations revize III sonrası)

## Bağlam

`endpoint-admin-service` BE-009 IN_PROGRESS — kod-test PASS (`AdminEndpointAuthorizationSecurityTest`, `EndpointAdminAuthorizationAnnotationTest`); k8s live config + smoke gate açık.

22.1.1 milestone bu gate'i kapatır:
- **Up**: Pod ready + readiness probe 200
- **Functional**: Admin allow + non-admin deny + unauthenticated deny (gerçek API)
- **Secured**: OpenFGA decision'dan deny + audit trace
- **Zanzibar-ready**: store/model IDs canlı + tuple seed idempotent

## Önkoşul (BE-009 backend tarafı)

`platform-backend/endpoint-admin-service/` final config (PR-A scope, ayrı):

- `application-k8s.yml`:
  - `ERP_OPENFGA_ENABLED=true`
  - `OPENFGA_API_URL=http://openfga.platform-test.svc.cluster.local:8080`
  - `OPENFGA_STORE_ID=<from ConfigMap>`
  - `OPENFGA_MODEL_ID=<from ConfigMap>`
  - **Fail-closed**: enabled=true ve store/model yoksa start fail
- Audit trace: `audit_log` table (`subject`, `action`, `object`, `decision`, `request_id`, `timestamp`)

## Tuple seed prosedürü

**Codex 019de00f revize**: tuple writer **permission-service** onaylı bootstrap yolundan (DD-EA-2 sınırı). Doğrudan OpenFGA gRPC/REST KULLANMA.

### Adım 1 — OpenFGA store + model var mı?

```bash
ssh halil@staging-sw "kubectl --context=k3d-test exec -n platform-test deploy/openfga -- \
  /openfga store list 2>&1 | grep platform-test || echo 'STORE YOK'"
```

Beklenen: `platform-test` store mevcut (varolan Zanzibar runtime'dan, BE-007/BE-008'le birlikte). Yoksa **BE-009 önkoşul fail**.

### Adım 2 — Test admin persona DB seed

```bash
# permission-service'in admin REST endpoint'i kullan
ssh halil@staging-sw "kubectl --context=k3d-test exec -n platform-test deploy/permission-service -- \
  curl -X POST http://localhost:8084/api/v1/admin/users \
    -H 'Authorization: Bearer <ADMIN_TOKEN>' \
    -H 'Content-Type: application/json' \
    -d '{\"id\":9001,\"email\":\"endpoint-admin-test@acik.com\",\"role\":\"admin\"}'"
```

Test persona DB'ye seed edildi (BE-009 user_lookup_service kullanır).

### Adım 3 — Tuple seed (permission-service admin endpoint)

```bash
# tuple JSON dosyasını permission-service'e gönder
TUPLES_JSON=$(cat bootstrap/openfga/endpoint-admin-tuples.json | jq '.tuples')

ssh halil@staging-sw "kubectl --context=k3d-test exec -n platform-test deploy/permission-service -- \
  curl -X POST http://localhost:8084/api/v1/admin/openfga/tuples/write \
    -H 'Authorization: Bearer <ADMIN_TOKEN>' \
    -H 'Content-Type: application/json' \
    -d '${TUPLES_JSON}'"
```

> **Not**: BE-009 final config sonrası `permission-service` admin endpoint'i `tuples/write` API expose etmeli. Bu endpoint mevcut değilse, BE-009 PR-A scope'unda eklenir veya alternatif: `bootstrap/seed-openfga-endpoint-admin.sh` script ile direkt OpenFGA gRPC (test-only bootstrap exception, Codex revize).

### Adım 4 — Tuple verify

```bash
# OpenFGA'da tuple var mı (read-only check, DD-EA-2 boundary OK)
ssh halil@staging-sw "kubectl --context=k3d-test exec -n platform-test deploy/openfga -- \
  /openfga query check \
    --store-id=<STORE_ID> \
    --model-id=<MODEL_ID> \
    --user=user:9001 --relation=admin --object=module:endpoint-admin"
```

Beklenen: `allowed: true`.

## Acceptance — Up + Functional + Secured + Zanzibar-ready

### Up — Pod ready + endpoint reachable

```bash
# 1. Deployment available
ssh halil@staging-sw "kubectl --context=k3d-test get deployment endpoint-admin-service -n platform-test \
  -o jsonpath='{.status.readyReplicas}/{.spec.replicas}'"
# Beklenen: 1/1

# 2. Pod readiness probe (management:8081)
ssh halil@staging-sw "kubectl --context=k3d-test exec -n platform-test deploy/endpoint-admin-service -- \
  curl -sk -o /dev/null -w '%{http_code}\n' http://localhost:8081/actuator/health/readiness"
# Beklenen: 200

# 3. Gateway route accessible (no token, expect 401)
curl -sk -o /dev/null -w '%{http_code}\n' https://testai.acik.com/api/v1/endpoint-admin/admin/endpoints
# Beklenen: 401 (gateway routing OK + auth filter alive)
```

### Functional — Gerçek endpoint-admin API allow/deny

```bash
# A2b.2 (2026-07-21): confidential smoke-client ROPC (client_id=frontend + DAG=false, A2c cutover);
# Vault path: kv/platform/keycloak/smoke-client (A2a); scope-mapping/mapper: A2b.1 setup-smoke-token-contract.sh
SMOKE_CLIENT_SECRET=$(ssh halil@staging-sw '
  VT=$(python3 -c "import json; print(json.load(open(\"/home/halil/bootstrap-drill/vault-init-test.json\"))[\"root_token\"])")
  docker exec -e VAULT_TOKEN=$VT platform-vault-test vault kv get -field=client_secret kv/platform/keycloak/smoke-client
')

# Admin token al (test admin persona, user:9001)
ADMIN_TOKEN=$(curl -sk -X POST \
  "https://testai.acik.com/realms/platform-test/protocol/openid-connect/token" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=smoke-client" \
  --data-urlencode "client_secret=${SMOKE_CLIENT_SECRET}" \
  --data-urlencode "username=endpoint-admin-test@acik.com" \
  --data-urlencode "password=${ENDPOINT_ADMIN_TEST_PASSWORD}" | jq -r .access_token)

# Admin allow check (gerçek API üzerinden — raw OpenFGA değil)
curl -sk -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  "https://testai.acik.com/api/v1/endpoint-admin/admin/endpoints"
# Beklenen: 200

# Viewer (user:9002) admin endpoint deny
VIEWER_TOKEN=$(curl -sk -X POST \
  "https://testai.acik.com/realms/platform-test/protocol/openid-connect/token" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=smoke-client" \
  --data-urlencode "client_secret=${SMOKE_CLIENT_SECRET}" \
  --data-urlencode "username=endpoint-viewer-test@acik.com" \
  --data-urlencode "password=${ENDPOINT_VIEWER_TEST_PASSWORD}" | jq -r .access_token)

curl -sk -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer ${VIEWER_TOKEN}" \
  "https://testai.acik.com/api/v1/endpoint-admin/admin/endpoints"
# Beklenen: 403 (RequireModule interceptor deny)

# Unauthenticated deny (token yok)
curl -sk -o /dev/null -w '%{http_code}\n' \
  "https://testai.acik.com/api/v1/endpoint-admin/admin/endpoints"
# Beklenen: 401
```

### Secured — Audit trace + OpenFGA decision

```bash
# 1. Audit trace verify (admin allow + viewer deny tek istek için)
ssh halil@staging-sw "kubectl --context=k3d-test exec -n platform-test deploy/endpoint-admin-service -- \
  curl -sk http://localhost:8081/actuator/health/audit \
    -H 'Authorization: Bearer ${ADMIN_TOKEN}' | jq '.audit_trail[-3:]'"
# Beklenen: 3 audit entry — admin/allow, viewer/deny, unauth/deny
# Her entry: subject, action, object, decision, request_id, timestamp

# 2. OpenFGA disabled fallback allow YOK (fail-closed)
# Geçici test: OpenFGA deploy scale=0 → admin endpoint 503 dönmeli (silent allow YASAK)
# (DESTRUCTIVE — sadece test cluster, geri scale=1 ile recover)

# 3. Decision OpenFGA'dan geliyor (caching layer DEĞİL)
# Tuple sil → admin endpoint 403 (deny) → tuple yeniden seed → admin endpoint 200
# Bu döngü idempotency + decision freshness kanıtı
```

### Zanzibar-ready — Live config + tuple persist + decision freshness

```bash
# 1. Canlı pod store/model IDs ConfigMap'ten
ssh halil@staging-sw "kubectl --context=k3d-test exec -n platform-test deploy/endpoint-admin-service -- \
  env | grep -E 'OPENFGA_STORE_ID|OPENFGA_MODEL_ID'"
# Beklenen: store + model IDs explicit set

# 2. Tuple persist (idempotent — aynı tuple iki kez yazılırsa no-op)
# Tuple seed adım 3'ü 2 kez çalıştır → 2. çalıştırma error vermez

# 3. Decision freshness (tuple sil → deny döner)
# Test admin tuple sil → 5 sn bekle → admin endpoint 403 dönmeli
# (eventual consistency contract — sıkı 5 sn bound)
```

## D29 4-katman özet

| Katman | Komut | Beklenen |
|---|---|---|
| **Up** | kubectl get + readiness probe + gateway no-token | 1/1 + 200 + 401 |
| **Functional** | Admin allow + viewer deny + unauth deny | 200 + 403 + 401 |
| **Secured** | Audit trace + fail-closed + decision freshness | 3 entry + 503 + freshness <5s |
| **Zanzibar-ready** | Store/model IDs config + tuple persist + decision live | OPENFGA_*_ID set + idempotent + delete→deny |

**Hepsi PASS → BE-009 IN_PROGRESS → DONE.** 22.1.1 milestone CLOSED.

## 22.1.1 → 22.1.2 unlock

BE-009 acceptance close → BE-013 maintenance token live başlar. **Acceptance sırası BE-009 → BE-013** (Codex revize AGREE).

## Out-of-scope (22.1.1)

- 22.2 trusted signing pre-req docs (sprint sonu, ayrı doküman)
- BE-014..BE-019 (audit hash-chain, destructive saga, AD/M365 password reset)
- WEB-001 MFE scaffold (22.2)
- Endpoint-admin prod overlay aktivasyon (22.2+ DD-EA-3 strict deploy)

## Codex referans

- Thread `019de00f` — sprint review + 22.1.1 plan-time AGREE-with-revisions
- Revize: tuple seed `bootstrap/openfga/...` (ESO altında DEĞİL), wildcard YASAK, gerçek API üzerinden Functional check (raw OpenFGA tek başına yetmez)

## Risk + rollback

**Risk**:
- BE-009 fail-closed davranış kod tarafında implement edilmemişse → silent allow → Secured fail
- Permission-service admin tuple write API yok → bootstrap script direct OpenFGA fallback (test-only exception)
- Audit trace endpoint mevcut değilse → 22.1.1 PR-A scope'unda eklenmeli

**Rollback**:
- Tuple seed sil (`/api/v1/admin/openfga/tuples/delete` veya direct OpenFGA write tombstone)
- Backend rollback (`deploy-endpoint-admin-prod.yml` digest pin önceki sürüme — ama 22.1.1 prod scope dışı, sadece test overlay)
- Audit log cleanup (test cluster için OK)
