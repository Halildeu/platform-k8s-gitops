# RB Faz 21.3 D35-3 Prereq — `module:ACCESS` Authorization Tuple Seed

> **Tetikleyici**: D35-2-full / D35-3 evidence runları öncesi tek seferlik prereq.
> **Authority**: agent yapabilir (test cluster, test-store scope; CLAUDE.md HARD RULE #7 SSH+sudo+kubectl + ADR-0010 §2.5 operator/agent matrix). **Production tuple seed kullanıcı-only**.
> **Codex**: `019dd409` PARTIAL/AGREE-with-revisions — "test OpenFGA tuple write, credential-write değil; test state mutation sınıfında. Auto-mode + Codex consensus ile agent çalıştırabilir, ama sadece test store ve açıkça seçilmiş admin UID için."

## Neden gerekli

`/api/v1/access/scope` endpoint'leri Faz 21.3 PR-D ile gate'lendi:
- `POST /api/v1/access/scope` → `@RequireModule("ACCESS", "can_manage")`
- `DELETE /api/v1/access/scope/{id}` → `@RequireModule("ACCESS", "can_manage")`
- `GET /api/v1/access/scope` → `@RequireModule("ACCESS", "can_view")`

Her iki relation `type module` (`backend/openfga/model.fga`). Admin persona için tuple seedlenmeden **ilk REST grant 403** döner. D35-2-full için **ZORUNLU**.

## Kapsam

- **Test cluster (k3d-test)**: agent çalıştırabilir, evidence runları için
- **Production cluster (k3d-prod)**: kullanıcı-only; ayrı runbook + dual-clearance approval gerek (CLAUDE.md HARD RULE #6)

## Prereq

- [ ] Vault'tan `kv/platform/openfga` okunabilir (`vault kv get` çalışır)
- [ ] OpenFGA endpoint reachable (test cluster'da port-forward veya in-cluster service)
- [ ] Admin persona Keycloak UUID'si bilinir (`docs/RB-faz-21-3-d35-3-keycloak-admin-jwt.md` Step 2 sonrası)

## Seed komutu (manuel adım adım)

### 1. Env'i set et

```bash
ADMIN_UID="<admin persona UUID — Keycloak'tan>"
GRANTED_UID="<granted persona UUID, opsiyonel — list endpoint test edilecekse>"

STORE_ID=$(vault kv get -field=store_id kv/platform/openfga)
MODEL_ID=$(vault kv get -field=model_id kv/platform/openfga)

# Test cluster'da OpenFGA nereden erişilir
# Option A: in-cluster (varsayılan, agent için en güvenli)
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  port-forward svc/openfga 18080:8080 --address=127.0.0.1 \
  >/tmp/openfga-pf.log 2>&1 &"
sleep 3

OPENFGA_URL="http://127.0.0.1:18080"

# Option B: cluster IP üzerinden (D35-2 evidence pattern: 10.44.3.209:8080)
# OPENFGA_URL="http://10.44.3.209:8080"
```

### 2. Admin persona için seed

```bash
# Admin persona: hem can_manage hem can_view (admin GET de yapabilsin)
ssh halil@staging-sw "curl -sf -X POST \
  http://10.44.3.209:8080/stores/${STORE_ID}/write \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  \"authorization_model_id\": \"${MODEL_ID}\",
  \"writes\": {
    \"tuple_keys\": [
      {\"user\": \"user:${ADMIN_UID}\", \"relation\": \"can_manage\", \"object\": \"module:ACCESS\"},
      {\"user\": \"user:${ADMIN_UID}\", \"relation\": \"can_view\",   \"object\": \"module:ACCESS\"}
    ]
  }
}
EOF
"
```

**Beklenen response**: HTTP 200, body `{}` (boş JSON object — OpenFGA write success).

**Hata türleri**:
- `409 Conflict — write_failed_due_to_invalid_input`: tuple zaten var (idempotent retry — sorun değil; aynı tuple iki kez yazılırsa OpenFGA reject eder)
- `400 Bad Request — invalid_authorization_model_id`: MODEL_ID yanlış; Vault'tan tekrar oku
- `404 Not Found`: STORE_ID veya endpoint yanlış

### 3. (Opsiyonel) Granted persona için `can_view` seed

> Sadece D35-3 Step 4 (granted persona kendi listesini görsün) yapılacaksa.

```bash
ssh halil@staging-sw "curl -sf -X POST \
  http://10.44.3.209:8080/stores/${STORE_ID}/write \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  \"authorization_model_id\": \"${MODEL_ID}\",
  \"writes\": {
    \"tuple_keys\": [
      {\"user\": \"user:${GRANTED_UID}\", \"relation\": \"can_view\", \"object\": \"module:ACCESS\"}
    ]
  }
}
EOF
"
```

### 4. /check ile doğrulama

```bash
ssh halil@staging-sw "curl -sf -X POST \
  http://10.44.3.209:8080/stores/${STORE_ID}/check \
  -H 'Content-Type: application/json' \
  -d \"{
    \\\"authorization_model_id\\\":\\\"${MODEL_ID}\\\",
    \\\"tuple_key\\\":{\\\"user\\\":\\\"user:${ADMIN_UID}\\\",\\\"relation\\\":\\\"can_manage\\\",\\\"object\\\":\\\"module:ACCESS\\\"}
  }\""
# Beklenen: {"allowed":true}

ssh halil@staging-sw "curl -sf -X POST \
  http://10.44.3.209:8080/stores/${STORE_ID}/check \
  -H 'Content-Type: application/json' \
  -d \"{
    \\\"authorization_model_id\\\":\\\"${MODEL_ID}\\\",
    \\\"tuple_key\\\":{\\\"user\\\":\\\"user:${ADMIN_UID}\\\",\\\"relation\\\":\\\"can_view\\\",\\\"object\\\":\\\"module:ACCESS\\\"}
  }\""
# Beklenen: {"allowed":true}
```

**Gate**: ikisi de `allowed: true`.

### 5. Cleanup (port-forward kapat)

```bash
ssh halil@staging-sw "pkill -f 'port-forward.*openfga' || true"
```

## Otomatize: `scripts/d35-3/openfga-access-tuple-seed.sh`

Manuel adımlar tek script ile koşulabilir:

```bash
ADMIN_UID="<uuid>" GRANTED_UID="<uuid>" \
  ./scripts/d35-3/openfga-access-tuple-seed.sh
```

Detay: ilgili script dosyası `scripts/d35-3/openfga-access-tuple-seed.sh`. Idempotent: tuple zaten varsa 409 sessizce yutulur, /check her zaman canlı doğrulama olarak koşar.

## Cleanup / Rollback

Bir tuple yanlış seedlenirse `delete` ile kaldır:

```bash
ssh halil@staging-sw "curl -sf -X POST \
  http://10.44.3.209:8080/stores/${STORE_ID}/write \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  \"authorization_model_id\": \"${MODEL_ID}\",
  \"deletes\": {
    \"tuple_keys\": [
      {\"user\": \"user:${ADMIN_UID}\", \"relation\": \"can_manage\", \"object\": \"module:ACCESS\"}
    ]
  }
}
EOF
"
```

## Boundary notes

- **Test cluster**: agent SSH+sudo+kubectl yetkisi var (CLAUDE.md HARD RULE #7); tuple write = test state mutation, kabul edilir.
- **Production cluster**: bu runbook'un prod versiyonu **ayrı dosya** olur, ve **kullanıcı-only**. Production tuple seed = canlı kullanıcı yetkilendirmesi; agent dokunmaz.
- **Vault model_id ve store_id**: gerçek değerler agent transcript'ine girmesin (env'den oku, log'a yazma).

## References

- ADR-0008 § "Object id encoding" (V25 transition map; module type pre-V25 stable)
- `docs/openfga-multi-org-rollout.md` Step 8 § "Pre-flip operator authz tuple seed (Faz 21.3 PR-D)" satır 234-277
- `backend/openfga/model.fga` (`type module` ve `relation can_manage|can_view`)
- D35-2-full template prereq listesi
- Codex thread `019dd409` PARTIAL/AGREE-with-revisions
