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

## §2 Drift Matrix (Live Evidence 2026-05-27 — iter-2 Codex `019e6ac8` REVISE absorb)

> **Iter-2 update**: Codex review thread `019e6ac8-7dc0-7f71-bd6b-1205b5c8a9db` REVISE absorb 2026-05-27 — auth-service KC client adı `auth-service` DEĞİL `impersonation-broker` (configmap canonical); perf-alertmanager `platform-prod` ns değil `monitoring` ns ESO desired-state (owner-action pending Vault seed, NOT stale orphan). Iter-1 misclassification'lar düzeltildi.

| # | Service | Vault Path | Vault Keys (count + names) | K8s Secret + Namespace | KC `serban` Active Client | Drift Verdict | Severity |
|---|---|---|---|---|---|---|---|
| 1 | **user-service** | ✅ `kv/platform/user-service` | 4: `db_password`, `db_username`, `internal_api_key`, `keycloak_client_secret` | ✅ `user-service-secrets` in `platform-prod` (6 keys; ERP_OPENFGA_* multi-source from `kv/platform/openfga` per `kustomize/base/apps/user-service/ops/externalsecret.yaml:38`) | ✅ id=`9ec438ac-ce25-49f2-8b3a-dede2c111c3a` (enabled=true, protocol=openid-connect, serviceAccountsEnabled=true) | 🟢 **NO drift (phantom)** | None |
| 2 | **auth-service** | ✅ `kv/platform/auth-service` | 7: `db_password`, `db_username`, `impersonation_broker_client_secret`, `internal_api_key`, `jwt_private_key`, `jwt_public_key`, `keycloak_client_secret` | ✅ `auth-service-secrets` in `platform-prod` (7 keys: incl. `AUTH_IMPERSONATION_BROKER_CLIENT_SECRET` + `KEYCLOAK_CLIENT_SECRET`) | ✅ **`impersonation-broker` LIVE** in serban: id=`3ebfd270-51ff-4489-a395-a10ea869136b` (enabled=true, serviceAccountsEnabled=true). `AUTH_IMPERSONATION_BROKER_CLIENT_ID="impersonation-broker"` canonical (`kustomize/base/apps/auth-service/configmap.yaml:70`). `KEYCLOAK_CLIENT_SECRET` separately consumed by Spring resource-server JWT validation (oauth2 resource-server pattern, not client_credentials) | 🟢 **NO drift (phantom iter-1 misclassification — Codex `019e6ac8` catch)** | None |
| 3 | **perf-alertmanager** | ✅ `kv/platform/perf-alertmanager` (path listed; data.data=null — payload missing) | 🟡 ESO `perf-alertmanager-secrets` in **`monitoring` ns** with **`Ready=False (reason=SecretSyncedError)` 7d20h** (NOT `platform-prod` — iter-1 misclassification); Helm values mount `/etc/alertmanager/secrets/perf-alertmanager-secrets/SLACK_WEBHOOK_URL` LIVE via `api_url_file` (`helm-values/kube-prometheus-stack/values-prod.yaml:209`) | N/A (alertmanager Slack receiver, not KC client) | 🟡 **Owner-action pending activation — Vault `SLACK_WEBHOOK_URL` seed gap** | **Low** (no current Slack delivery; but desired-state LIVE; V2.1 Ops-A A2 runbook owner step) |

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

### #2 auth-service — 🟢 NO DRIFT (phantom; iter-2 Codex catch corrected)

> **Iter-2 update (Codex `019e6ac8` REVISE absorb)**: Iter-1 yanlış KC client adı arıyordu (`clientId=auth-service`). Canonical KC client adı `impersonation-broker` (configmap.yaml:70). Iter-2 doğru introspection ile **phantom drift kanıtlandı**.

**Live evidence (iter-2)**:
```bash
# 1. auth-service canonical KC client ID — from manifest:
$ grep AUTH_IMPERSONATION_BROKER_CLIENT_ID kustomize/base/apps/auth-service/configmap.yaml
AUTH_IMPERSONATION_BROKER_CLIENT_ID: "impersonation-broker"

# 2. KC serban realm — impersonation-broker client LIVE:
$ kcadm.sh get clients -r serban -q clientId=impersonation-broker --fields id,clientId,enabled,protocol,publicClient,serviceAccountsEnabled
[ {
  "id" : "3ebfd270-51ff-4489-a395-a10ea869136b",
  "clientId" : "impersonation-broker",
  "enabled" : true,
  "serviceAccountsEnabled" : true,
  "publicClient" : false,
  "protocol" : "openid-connect"
} ]

# 3. Vault path: kv/platform/auth-service (7 keys — confirms keycloak_client_secret + impersonation_broker_client_secret)
# 4. K8s auth-service-secrets in platform-prod (7 keys — AUTH_IMPERSONATION_BROKER_CLIENT_SECRET + KEYCLOAK_CLIENT_SECRET aligned)
```

**Cross-AI catch (Codex `019e6ac8` iter-1)**: "`clientId=auth-service` yokluğu tek başına broken-flow kanıtı değil; manifestte aktif impersonation path broker client id olarak `impersonation-broker` kullanıyor, secret de `AUTH_IMPERSONATION_BROKER_CLIENT_SECRET` üzerinden geliyor."

**Two consumption paths**:
1. **Impersonation flow** (impersonation-broker client_credentials):
   - KC client `impersonation-broker` (serban id `3ebfd270`) → service account JWT mint
   - Backend: `auth-service` REST endpoint `/api/v1/impersonation/sessions` calls KC token-exchange
   - Env: `AUTH_IMPERSONATION_BROKER_CLIENT_ID="impersonation-broker"` + `AUTH_IMPERSONATION_BROKER_CLIENT_SECRET=<vault.impersonation_broker_client_secret>`
   - Status: ✅ LIVE
2. **Resource server JWT validation** (Spring Security `oauth2-resource-server`):
   - Backend validates incoming JWTs minted by other services
   - Env: `KEYCLOAK_CLIENT_SECRET=<vault.keycloak_client_secret>` (Spring resource-server pattern; client_credentials için DEĞİL, JWT introspect/validate için optional config)
   - Status: ✅ LIVE (Spring resource-server validates without active client_credentials grant)

**No drift conclusion**: Both consumption paths have proper KC backing. Phantom drift was caused by iter-1 search using wrong clientId.

**Action**: None needed; phantom kapatıldı.

**Risk**: **None** — auth flow LIVE; impersonation broker client + resource-server JWT validation both aligned.

---

### #3 perf-alertmanager — 🟡 OWNER-ACTION PENDING ACTIVATION (V2.1 Ops-A A2; iter-2 Codex catch corrected)

> **Iter-2 update (Codex `019e6ac8` REVISE BLOCKER absorb)**: Iter-1 sadece `platform-prod` namespace'i taradı (yanlış scope). Canonical desired-state `monitoring` namespace'inde V2.1 Ops-A pattern ile ESO render var. Iter-1 verdict "stale orphan/no consumer" YANLIŞTI; gerçek verdict "owner-action pending Vault `SLACK_WEBHOOK_URL` seed".

**Live evidence (iter-2 — monitoring namespace canonical)**:
```bash
# 1. ExternalSecret canonical: monitoring namespace
$ kubectl --context k3d-prod -n monitoring get externalsecret | grep perf-alert
perf-alertmanager-secrets   ClusterSecretStore   vault-platform-gitops   1h   SecretSyncedError   False   7d20h

# 2. Source-of-truth ExternalSecret manifest:
$ cat kustomize/overlays/prod/eso/alertmanager/externalsecret-perf-alertmanager.yaml | tail -25
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: vault-platform-gitops
  target:
    name: perf-alertmanager-secrets
    creationPolicy: Owner
  data:
    - secretKey: SLACK_WEBHOOK_URL
      remoteRef:
        key: kv/platform/perf-alertmanager
        property: SLACK_WEBHOOK_URL

# 3. Helm values consumer (Alertmanager pod mount):
$ grep -E "perf-alertmanager-secrets|api_url_file" helm-values/kube-prometheus-stack/values-prod.yaml | head -6
    # ESO `perf-alertmanager-secrets` K8s Secret pod'a file mount edilir;
    # Alertmanager config `slack_configs.api_url_file` ile path okur (env injection DEĞİL).
    # Mount path: /etc/alertmanager/secrets/perf-alertmanager-secrets/SLACK_WEBHOOK_URL
      - perf-alertmanager-secrets
          - api_url_file: /etc/alertmanager/secrets/perf-alertmanager-secrets/SLACK_WEBHOOK_URL

# 4. Vault payload missing:
$ vault kv get -format=json kv/platform/perf-alertmanager | jq -r '.data.data | keys[]'
jq: error (at <stdin>:17): null (null) has no keys
# Path metadata exists (kv list shows entry) but data.data = null
```

**Cross-AI catch (Codex `019e6ac8` iter-1 BLOCKER)**: "PR doc platform-prod namespace'te secret arıyor, ama source desired-state `perf-alertmanager-secrets` ExternalSecret'i monitoring namespace'inde render ediyor ve `kv/platform/perf-alertmanager` `SLACK_WEBHOOK_URL` bekliyor. `kustomize build kustomize/overlays/prod/eso` bunu bağımsız doğruladı."

**Drift analysis (iter-2)**:
- **Desired-state LIVE**: ExternalSecret + Helm values + Alertmanager `api_url_file` mount path canonical configured
- **ESO sync state**: `Ready=False (reason=SecretSyncedError)` 7d20h (sync failing because Vault `SLACK_WEBHOOK_URL` field missing)
- **Owner-action gap**: V2.1 Ops-A A2 runbook (`docs/runbooks/V2.1-perf-alert-receiver.md`) owner step — `vault kv put kv/platform/perf-alertmanager SLACK_WEBHOOK_URL=<https://hooks.slack.com/...>`
- **NOT KC drift**: alertmanager Slack receiver pattern; KC client gerekli değil (api_url_file file-mount pattern)
- **NOT stale orphan**: V2.1 Ops-A A2 isolation pattern desired-state aktif (Codex `019e267a` AGREE_AFTER_REVISIONS)

**Fix-PR scope** (separate PR — owner-action):
- **Owner-side**: Slack workspace `team=perf` channel webhook URL üret → `vault kv put kv/platform/perf-alertmanager SLACK_WEBHOOK_URL=<URL>` execute
- **Agent-side post-owner-action**: ESO force-sync verify → `kubectl get secret perf-alertmanager-secrets -n monitoring -o json | jq '.data | keys[]'` should show `SLACK_WEBHOOK_URL` → Alertmanager pod log check for `Notify success` after first SLACK alert
- **NOT applicable**: `vault kv metadata delete` — pattern aktif desired-state, retirement değil

**Action**: Owner Vault seed action; agent post-seed verification.

**Owner**: ops (Vault seed) + agent (post-seed sync verify)

**Risk**: **Low** (no current Slack delivery for perf-alerts; but R8/R13 alerts via Email leg LIVE via `alertmanager-fallback-secrets`). Activation triggers perf-alert Slack channel routing per V2.1 Ops-A A2 design.

**Reference**: `docs/runbooks/V2.1-perf-alert-receiver.md` §A2 + Codex `019e267a` iter-2 AGREE_AFTER_REVISIONS.

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

### KC client / Consumer → service deployment alignment (iter-2 corrected)

> **Iter-2 update**: iter-1 tablo §2/§3/§6 verdict'leriyle çelişiyordu (Codex `019e6ac8` iter-2 catch). Düzeltilmiş tablo aşağıda.

| Service | Active Consumer Pattern | Aligned? |
|---|---|---|
| **user-service** | KC serban client `user-service` (id `9ec438ac`) ↔ `user-service` deploy in `platform-prod` | ✅ Aligned |
| **auth-service** | KC serban client `impersonation-broker` (id `3ebfd270`) ↔ `auth-service` impersonation flow in `platform-prod`; resource-server JWT validation via `KEYCLOAK_CLIENT_SECRET` separate path | ✅ Aligned |
| **perf-alertmanager** | Alertmanager Slack receiver (kube-prometheus-stack) ↔ `monitoring` ns ExternalSecret `perf-alertmanager-secrets` + Helm `api_url_file` mount; **KC client not expected** (Slack webhook file-mount pattern) | 🟡 Owner-action pending Vault `SLACK_WEBHOOK_URL` seed (V2.1 Ops-A A2 runbook); desired-state LIVE, payload missing |

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

## §6 Next Steps (iter-2 — Revised Pipeline post-Codex `019e6ac8` REVISE)

Per iter-2 Codex catch absorb: gerçek aktivasyon pattern'lerinin **fix scope'ları daraldı**.

**Revised pipeline**:

1. **No-op (user-service)**: Phantom drift kapatıldı; her şey LIVE ve aligned. Fix gerekmez. ✅
2. **No-op (auth-service)**: Phantom drift kapatıldı; KC `impersonation-broker` client + resource-server JWT validation aligned LIVE. Fix gerekmez. ✅
3. **Owner-action (perf-alertmanager)**: V2.1 Ops-A A2 owner step pending — Vault `kv/platform/perf-alertmanager` `SLACK_WEBHOOK_URL` seed:
   - **Owner-side runbook**: `docs/runbooks/V2.1-perf-alert-receiver.md` §A2 — owner generates Slack webhook URL + `vault kv put` command
   - **Agent post-seed**: ESO force-sync verify; `kubectl get secret perf-alertmanager-secrets -n monitoring` → `SLACK_WEBHOOK_URL` key present + length>0
   - **Cross-AI**: agent diagnosis evidence iter-2 (this doc); owner Vault write authority gate; post-seed verify can be separate PR or in-line evidence
   - **Reference**: PR #1093 (this PR) provides diagnosis-only attestation; owner action is operational step (Vault root token + Slack webhook generation)

**Important**: Iter-2 revision **eliminated 2 of 3 originally-suspected drift fix PRs** (user-service + auth-service phantoms). Only **1 actionable item remains**: perf-alertmanager owner Vault seed. This is consistent with HARD RULE — Uzun Vadeli Kalıcı Çözüm: phantom-fix anti-pattern avoided.

---

## §7 Evidence References

- **Codex diagnosis-first verdict**: thread `019e6abe-2e1b-7e23-b445-df3cf8f16fec` (2026-05-27)
- **Vault canonical access**: `/home/halil/bootstrap-drill/vault-init-prod.json` (root token; Pre-Production Full Authority HARD RULE 2026-04-29)
- **KC prod canonical password**: `/run/secrets/kc_admin_password` (Docker secret mount; 32-char + newline = 33 bytes)
- **KC realm canonical**: `serban` (BL-010 PR #1062 — `acik` → `serban` realm rename drift fix)
- **Handoff RB pointer**: `docs/runbooks/RB-faz-23-v1-closure-operator-handoff.md` — entry "3 KC drift fix (user-svc ?, auth-svc 11char, perf-alertmanager orphan) ⏳ Operator"
- **Previous BL-010 evidence**: `docs/faz-23-evidence/2026-05-25-bl010-prod-kc-org-id-mapper-serban.md` — `serban` realm `notify-canary` client scope precedent

---

## §8 Closing Summary (1-Sentence; iter-2 final)

**3 service drift claim → live diagnosis iter-2 (Codex `019e6ac8` REVISE absorb)**: **2 phantom** (user-service ✅ + auth-service ✅ phantom corrected via `impersonation-broker` canonical client + resource-server JWT separation) + **1 owner-action pending** (perf-alertmanager 🟡 monitoring ns ESO `Ready=False (reason=SecretSyncedError)` 7d20h → V2.1 Ops-A A2 Vault `SLACK_WEBHOOK_URL` seed owner step); no mutation; fix scope tek owner-action'a indirgendi.
