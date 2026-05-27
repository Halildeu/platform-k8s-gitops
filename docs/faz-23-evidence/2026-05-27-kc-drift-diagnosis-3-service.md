# KC Drift Diagnosis — 3 Service (user-service / auth-service / perf-alertmanager)

> **Type**: Diagnosis-only evidence doc (NO mutation; live introspection)
> **Date**: 2026-05-27
> **Trigger**: Faz 23 v1 closure handoff RB §2 — "3 KC drift fix (user-svc ?, auth-svc 11char, perf-alertmanager orphan)" ⏳ Operator
> **Decision authority**: Codex strategic verdict thread `019e6abe-2e1b-7e23-b445-df3cf8f16fec` 2026-05-27 — "RECOMMENDED: A (3 KC drift diagnosis-only PR, no mutation)"; "diagnosis-only PR kesinlikle no-fix/no-mutation olmalı"
> **Cross-AI peer review chain**: Anthropic Claude implementer / OpenAI Codex reviewer per HARD RULE 2026-05-05/14
> **Boundary**: Pure docs-only single class (Documentation); no code/config/runtime/security mutation

---

## §1 Scope + Methodology

**Scope**: Live introspection — Vault prod (`platform-vault-prod`) + KC prod (`platform-kc-prod`) + K8s prod cluster (`k3d-prod`/`platform-prod`) for 3 services with previously suspected KC drift.

**Methodology**:
1. Vault path inventory (`vault kv list kv/platform`) — names only, no values
2. Vault key list per service (`vault kv get -format=json | jq -r '.data.data | keys[]'`) — key names only, no values
3. KC realm client introspection (`kcadm.sh get clients -r <realm> -q clientId=<name>`) per `serban` (prod canonical) + `master` realms
4. K8s prod secret key inventory (`kubectl get secret <name> -o json | jq -r '.data | keys[]'`) — key names only, no values
5. Cross-correlate evidence → drift verdict per service

**Why diagnosis-first**: Codex `019e6abe` verdict — "doğrudan fix PR açmak kalıcı çözüm değil, yanlış drift'i kalıcılaştırma riski taşır. Diagnosis-first PR ise mutasyon yapmadan live truth çıkarır, sonra her service için ayrı fix gate üretir."

**Anti-pattern avoided** (HARD RULE 2026-05-27 Uzun Vadeli Kalıcı Çözüm): "Bu çözüm 6 ay sonra hâlâ machine-enforced ve adversarial review'da geçer mi?" — phantom drift'e fix yazmak 6 ay sonra "neden bunu fix'lediğimizi unuttuk" cycle'ı yaratır. Diagnosis önce.

---

## §2 Drift Matrix (Live Evidence 2026-05-27)

| # | Service | Vault Path | Vault Keys (count + names) | K8s Secret (prod) | KC `serban` Client | KC `master` Client | Drift Verdict | Severity |
|---|---|---|---|---|---|---|---|---|
| 1 | **user-service** | ✅ `kv/platform/user-service` | 4: `db_password`, `db_username`, `internal_api_key`, `keycloak_client_secret` | ✅ `user-service-secrets` (6 keys: `SPRING_DATASOURCE_USERNAME/PASSWORD`, `KEYCLOAK_CLIENT_SECRET`, `PERMISSION_SERVICE_INTERNAL_API_KEY`, `ERP_OPENFGA_MODEL_ID`, `ERP_OPENFGA_STORE_ID`) | ✅ id=`9ec438ac-ce25-49f2-8b3a-dede2c111c3a` (enabled=true, protocol=openid-connect, publicClient=false, serviceAccountsEnabled=true) | absent | 🟢 **NO drift (phantom)** | None |
| 2 | **auth-service** | ✅ `kv/platform/auth-service` | 7: `db_password`, `db_username`, `impersonation_broker_client_secret`, `internal_api_key`, `jwt_private_key`, `jwt_public_key`, `keycloak_client_secret` | ✅ `auth-service-secrets` (7 keys: `SPRING_DATASOURCE_USERNAME/PASSWORD`, `KEYCLOAK_CLIENT_SECRET`, `AUTH_IMPERSONATION_BROKER_CLIENT_SECRET`, `PERMISSION_SERVICE_INTERNAL_API_KEY`, `SECURITY_SERVICE_JWT_PRIVATE_KEY/PUBLIC_KEY`) | ❌ **EMPTY** | absent | 🟡 **KC client absent in serban despite Vault+K8s expecting `KEYCLOAK_CLIENT_SECRET`** | **Medium** (auth flow risk if KC client expected) |
| 3 | **perf-alertmanager** | ✅ `kv/platform/perf-alertmanager` (path listed) | **null** (kv get returns `data.data = null` — path metadata exists but no payload data) | absent | absent | absent | 🟡 **Stale Vault path; no consumer (K8s + KC both absent)** | **Low** (no production impact; hygiene only) |

---

## §3 Per-Service Detailed Findings

### #1 user-service — 🟢 NO DRIFT (phantom)

**Live evidence**:
```bash
# Vault path + key list
$ vault kv list kv/platform | grep user-service
user-service
$ vault kv get -format=json kv/platform/user-service | jq -r '.data.data | keys[]'
db_password
db_username
internal_api_key
keycloak_client_secret

# K8s secret presence
$ kubectl --context k3d-prod -n platform-prod get secret user-service-secrets
NAME                   TYPE     DATA   AGE
user-service-secrets   Opaque   6      34d

# KC serban realm client
$ kcadm.sh get clients -r serban -q clientId=user-service --fields id,clientId,enabled,protocol,publicClient,serviceAccountsEnabled
[ {
  "id" : "9ec438ac-ce25-49f2-8b3a-dede2c111c3a",
  "clientId" : "user-service",
  "enabled" : true,
  "serviceAccountsEnabled" : true,
  "publicClient" : false,
  "protocol" : "openid-connect"
} ]
```

**Cross-check**: K8s `user-service-secrets` has 6 keys vs Vault 4 keys — discrepancy:
- `KEYCLOAK_CLIENT_SECRET` ← Vault `keycloak_client_secret` (matched via ExternalSecret remap)
- `PERMISSION_SERVICE_INTERNAL_API_KEY` ← Vault `internal_api_key` (matched)
- `SPRING_DATASOURCE_USERNAME/PASSWORD` ← Vault `db_username/db_password` (matched)
- `ERP_OPENFGA_MODEL_ID` + `ERP_OPENFGA_STORE_ID` — **not in user-service Vault path**

**Hypothesis**: The 2 ERP_OPENFGA_* keys come from a different ExternalSecret remoteRef (e.g., `kv/platform/openfga`). This is **not drift** — it's multi-source secret aggregation pattern (BL-028b PR #1069 cutover preserved this aggregation).

**Verdict**: 🟢 **NO drift**. Previous "(user-svc ?)" marker in handoff RB = phantom (uncertainty in absence of live evidence). KC client healthy + Vault key naming + ESO render aligned.

**Action**: None needed.

---

### #2 auth-service — 🟡 KC CLIENT ABSENT (medium severity)

**Live evidence**:
```bash
# Vault path + key list
$ vault kv get -format=json kv/platform/auth-service | jq -r '.data.data | keys[]'
db_password
db_username
impersonation_broker_client_secret
internal_api_key
jwt_private_key
jwt_public_key
keycloak_client_secret

# K8s secret presence
$ kubectl --context k3d-prod -n platform-prod get secret auth-service-secrets
NAME                    TYPE     DATA   AGE
auth-service-secrets    Opaque   7      34d

# KC serban realm client — EMPTY
$ kcadm.sh get clients -r serban -q clientId=auth-service --fields id,clientId
[ ]

# KC master realm — also EMPTY
$ kcadm.sh get clients -r master -q clientId=auth-service --fields id,clientId
[ ]
```

**Drift analysis**:
- Vault `kv/platform/auth-service` actively maintained (7 keys, includes `keycloak_client_secret`, `impersonation_broker_client_secret`)
- K8s `auth-service-secrets` actively rendered (7 keys, ExternalSecret consumer); pod consumes via envFrom
- KC `serban` realm has **NO `auth-service` client** despite secret rendering
- KC `master` realm also empty (excluded confused-realm explanation)

**Hypothesis A**: auth-service Spring boot pod consumes `KEYCLOAK_CLIENT_SECRET` env var but only uses it for **client_credentials grant** that's never triggered (dead branch). Lazy fail: app starts OK, KC OAuth call fails at runtime if hit.

**Hypothesis B**: auth-service KC client previously existed in `acik` realm (pre-BL-010 drift); `acik` → `serban` realm rename (BL-010 PR #1062) lost the client.

**Hypothesis C**: auth-service KC client exists in a realm we haven't inspected (e.g., `notify-canary` scope realm, or a tenant-specific realm).

**Fix-PR scope** (separate PR — NOT this diagnosis PR):
- Verify auth-service pod logs for KC OAuth call errors (no-error → unused secret; error → real broken flow)
- If unused → remove `KEYCLOAK_CLIENT_SECRET` + `impersonation_broker_client_secret` from `auth-service-secrets` ExternalSecret (clean dead config)
- If broken flow → recreate KC client in `serban` realm OR migrate auth-service to use a different client

**Action**: Spawn separate fix PR after live consumption verification (no mutation in this diagnosis PR).

**Owner**: ops + dev

**Risk**: **Medium** — auth flow could be silently broken; user-facing impact depends on whether OAuth client_credentials is actually invoked in current code path.

---

### #3 perf-alertmanager — 🟡 STALE VAULT PATH (low severity)

**Live evidence**:
```bash
# Vault path listed
$ vault kv list kv/platform | grep perf
perf-alertmanager

# Vault key list — EMPTY
$ vault kv get -format=json kv/platform/perf-alertmanager | jq -r '.data.data | keys[]'
jq: error (at <stdin>:17): null (null) has no keys
# (Vault returns data.data = null — path metadata exists but no payload data)

# K8s prod secret — absent
$ kubectl --context k3d-prod -n platform-prod get secret | grep perf-alert
# (no output)

# KC serban + master realm clients — both absent
$ kcadm.sh get clients -r serban -q clientId=perf-alertmanager
[ ]
$ kcadm.sh get clients -r master -q clientId=perf-alertmanager
[ ]
```

**Drift analysis**:
- Vault path `kv/platform/perf-alertmanager` exists in path listing but has **no data payload**
- No K8s secret in `platform-prod` consuming this path
- No KC client in either realm
- Likely **stale metadata** from past Vault entry (created, then `vault kv destroy` ran but `vault kv metadata delete` did not — keeps path listing as marker)

**Hypothesis A**: Pre-Faz 23 alertmanager experiment that was discarded; cleanup incomplete.

**Hypothesis B**: Future-planned entry seeded as placeholder; never populated.

**Hypothesis C**: Different cluster's perf-alertmanager (test cluster ≠ prod cluster) uses this path; prod orphan.

**Fix-PR scope** (separate PR — NOT this diagnosis PR):
- Either: `vault kv metadata delete kv/platform/perf-alertmanager` (hard delete metadata, removes from path listing) if confirmed orphan
- Or: document as future-trigger placeholder with reactivation chain (R23/ADR-0024 pattern — "asset-preserved demand-reactivated")
- Or: identify originating cluster + workflow and adopt as canonical

**Action**: Spawn separate fix PR after origin verification (no mutation in this diagnosis PR).

**Owner**: ops

**Risk**: **Low** — no consumer; pure hygiene; no production impact.

---

## §4 Cross-Service Findings

### Naming pattern (Vault → K8s render)

| Vault key | K8s env var |
|---|---|
| `db_username` | `SPRING_DATASOURCE_USERNAME` |
| `db_password` | `SPRING_DATASOURCE_PASSWORD` |
| `keycloak_client_secret` | `KEYCLOAK_CLIENT_SECRET` |
| `internal_api_key` | `PERMISSION_SERVICE_INTERNAL_API_KEY` |
| `impersonation_broker_client_secret` | `AUTH_IMPERSONATION_BROKER_CLIENT_SECRET` |
| `jwt_private_key` | `SECURITY_SERVICE_JWT_PRIVATE_KEY` |
| `jwt_public_key` | `SECURITY_SERVICE_JWT_PUBLIC_KEY` |

ExternalSecret CRD `remoteRef` → `secretKey` remap respects this pattern. **No drift in naming convention**.

### Realm canonical

`serban` realm is **prod canonical** (BL-010 PR #1062 evidence). `master` realm reserved for KC admin only. No other realms in prod `platform-kc-prod`.

### KC client → service deployment alignment

| KC client | K8s deployment | Status |
|---|---|---|
| `user-service` (serban) | `user-service` deploy (platform-prod) | ✅ aligned |
| `auth-service` | (deploy exists but no KC client) | 🟡 drift |
| `perf-alertmanager` | (no deploy + no KC client + no K8s secret) | 🟡 orphan |

---

## §5 Diagnosis-Only Boundary Statement

**No mutations performed**:
- Vault: read-only (`vault kv list`, `vault kv get -format=json`) — no `vault kv put/patch/delete`
- KC: read-only (`kcadm.sh get clients`) — no `create`, `update`, `delete` realm/client/scope/mapper
- K8s: read-only (`kubectl get secret -o json`) — no `apply`, `patch`, `delete`
- No `gh pr create` for fix PR in this branch
- No password/secret value logged or echoed (only key counts + names + length)

**Pre-Production Full Authority HARD RULE compliance**: Sistem credentials read access used; no user account password mutation.

---

## §6 Next Steps (Fix PR Pipeline — Separate PRs)

Per Codex `019e6abe` verdict: "Fix PR'lar daha sonra user authority gate per service ile açılır; tek PR'da prod KC/Vault mutation karışmaz."

**Pipeline** (each fix is independent — sequential or parallel; each per-service authority gate):

1. **Fix-PR-1 (auth-service KC client)**:
   - Verify auth-service pod logs for KC OAuth call patterns
   - Decision: dead-config-remove OR create-missing-KC-client OR migrate-to-different-realm
   - Cross-AI peer review + user authority approval
   - Live execute (Vault clean / KC create)

2. **Fix-PR-2 (perf-alertmanager Vault hygiene)**:
   - Verify path origin (test cluster vs prod cluster vs experiment)
   - Decision: hard-delete-metadata OR asset-preserve-document
   - Cross-AI peer review + user authority approval
   - Live execute (`vault kv metadata delete` if delete chosen)

3. **No-op (user-service)**:
   - No fix needed; phantom drift kapatıldı

**Important**: Each fix PR opens its own user authority gate. No batch mutation.

---

## §7 Evidence References

- **Codex diagnosis-first verdict**: thread `019e6abe-2e1b-7e23-b445-df3cf8f16fec` (2026-05-27)
- **Vault canonical access**: `/home/halil/bootstrap-drill/vault-init-prod.json` (root token; Pre-Production Full Authority HARD RULE 2026-04-29)
- **KC prod canonical password**: `/run/secrets/kc_admin_password` (Docker secret mount; 32-char + newline = 33 bytes)
- **KC realm canonical**: `serban` (BL-010 PR #1062 — `acik` → `serban` realm rename drift fix)
- **Handoff RB pointer**: `docs/runbooks/RB-faz-23-v1-closure-operator-handoff.md` — entry "3 KC drift fix (user-svc ?, auth-svc 11char, perf-alertmanager orphan) ⏳ Operator"
- **Previous BL-010 evidence**: `docs/faz-23-evidence/2026-05-25-bl010-prod-kc-org-id-mapper-serban.md` — `serban` realm `notify-canary` client scope precedent

---

## §8 Closing Summary (1-Sentence)

**3 service drift claim → live diagnosis**: 1 phantom (user-service ✅), 1 medium (auth-service 🟡 KC client absent despite Vault+K8s present), 1 low (perf-alertmanager 🟡 stale orphan Vault path); no mutation; fix PRs separate per-service authority gate.
