# RB-eso-vault-approle-rotate — ESO Vault AppRole Rotation Runbook

> **Status**: ACTIVE (Faz 23.2.D T1.4 D43 drill prereq; Codex 019e0dea iter-1 P1 #2 absorb)
> **Trigger**: ESO ClusterSecretStore "invalid role or secret ID" 4xx login fail
> **Owner**: ops (Vault root token erişimi gerekli)
> **Risk**: ESO Secret materialization fail → tüm dependent ExternalSecret SecretSyncedError

---

## 1. Sorun & Tetik

ESO ClusterSecretStore (vault-platform-gitops) Vault'a AppRole login yapamaz:

```
unable to log in with app role auth: Error making API request.
URL: PUT http://vault.platform-test.svc.cluster.local:8200/v1/auth/approle/login
Code: 400. Errors:
* invalid role or secret ID
```

**Tetik**:
- ESO controller log: "could not get provider client: unable to log in to auth method"
- ClusterSecretStore status: `Ready=False, Reason=InvalidProviderConfig`
- Dependent ExternalSecret status: `SecretSyncedError, message: ClusterSecretStore is not ready`

**Etki**:
- Tüm ExternalSecret sync STOP (cached K8s Secret eskimeye devam eder)
- Yeni Vault path init'leri (örn. `kv/platform/alertmanager-fallback`) materialize olamaz
- Pod restart → eski cached secret ile bağlanır (deterministik DEĞİL — Vault rotation ile drift)
- T1.4 D43 drill prereq #2 (`SecretSynced=True`) bloklanır

---

## 2. Tanı (3 dakika)

### 2.1 ClusterSecretStore status

```bash
ssh halil@staging-sw

kubectl --context k3d-test get clustersecretstore vault-platform-gitops \
  -o jsonpath='{.status.conditions[0].status}{" "}{.status.conditions[0].message}{"\n"}'
# Expected (drift):
#   False unable to create client / InvalidProviderConfig
```

### 2.2 ESO controller log (son 30s)

```bash
kubectl --context k3d-test -n external-secrets logs deploy/external-secrets --tail=30 | \
  grep -iE 'approle|invalid|denied|role|secret-id' | head -10
# Expected:
#   "invalid role or secret ID" pattern x N
```

### 2.3 Vault AppRole role-id mevcut mu

```bash
docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-test \
  vault read auth/approle/role/eso-runtime/role-id

# Expected: role_id <UUID> (örn. 5f3f58d4-4a0a-5b76-aa83-fcb277a5573a)
# Eğer "no role with name 'eso-runtime'" → AppRole role yok, oluştur (Step 3.0)
```

### 2.4 K8s Secret vault-approle-secret mevcut mu

```bash
kubectl --context k3d-test -n external-secrets get secret vault-approle-secret \
  -o jsonpath='{.data.secret-id}' | base64 -d | head -c 8
# Expected: 8-char prefix (UUID); secret-id mevcut
# Eğer secret yok → operator init gerek (Step 3.0)
```

---

## 3. Rotasyon (5-10 dakika)

### 3.0 Pre-prereq: AppRole role + policy (one-shot bootstrap, sadece ilk)

Eğer Step 2.3'te "no role" çıktıysa — bu rotation değil, initial bootstrap:

```bash
# Vault policy write
docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-test \
  sh -c 'cat > /tmp/eso-runtime.hcl' < bootstrap/vault-policies/common/eso-runtime.hcl
docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-test \
  vault policy write eso-runtime /tmp/eso-runtime.hcl

# AppRole role create
docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-test \
  vault write auth/approle/role/eso-runtime \
    token_policies="eso-runtime" \
    token_ttl="1h" \
    token_max_ttl="24h" \
    secret_id_ttl="0" \
    secret_id_num_uses="0"
```

### 3.1 Yeni secret-id rotate (force)

```bash
NEW_SECRET_ID_OUTPUT=$(docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-test \
  vault write -force -format=json auth/approle/role/eso-runtime/secret-id)

# JSON parse
NEW_SECRET_ID=$(echo "$NEW_SECRET_ID_OUTPUT" | jq -r '.data.secret_id')
NEW_SECRET_ID_ACCESSOR=$(echo "$NEW_SECRET_ID_OUTPUT" | jq -r '.data.secret_id_accessor')

echo "New secret-id accessor: $NEW_SECRET_ID_ACCESSOR (8-char prefix: ${NEW_SECRET_ID:0:8}...)"

# Audit log (no token-leak)
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) | eso-vault-approle-rotate | accessor=$NEW_SECRET_ID_ACCESSOR | by=$USER@$(hostname)" \
  >> /var/log/platform-vault-audit.log
```

> **HARD RULE — no-token-log**: secret-id değeri log'a/PR'a/message'a YAZILMAZ. Sadece accessor + ilk 8 char prefix audit için.

### 3.2 K8s Secret vault-approle-secret update

```bash
kubectl --context k3d-test -n external-secrets create secret generic vault-approle-secret \
  --from-literal=secret-id="$NEW_SECRET_ID" \
  --dry-run=client -o yaml | kubectl --context k3d-test apply -f -

# secret-id env var temizle (no-token-log)
unset NEW_SECRET_ID
```

### 3.3 ESO controller restart (yeni secret-id pickup)

```bash
kubectl --context k3d-test -n external-secrets rollout restart deploy/external-secrets
kubectl --context k3d-test -n external-secrets rollout status deploy/external-secrets --timeout=60s
```

### 3.4 ClusterSecretStore Ready=True doğrula

```bash
# Wait until Ready=True (max 30s expected)
kubectl --context k3d-test get clustersecretstore vault-platform-gitops \
  -o jsonpath='{.status.conditions[0].status}'
# Expected: True
```

### 3.5 ExternalSecret sync verify

```bash
# notification-orchestrator-secrets
kubectl --context k3d-test -n platform-test get externalsecret notification-orchestrator-secrets \
  -o jsonpath='{.status.conditions[0].status}{" "}{.status.refreshTime}{"\n"}'
# Expected: True <timestamp>

# T1.4 D43 drill prereq alertmanager-fallback-secrets (path init sonrası)
kubectl --context k3d-test -n monitoring get externalsecret alertmanager-fallback-secrets \
  -o jsonpath='{.status.conditions[0].status}{"\n"}'
# Expected: True (path init Step 4'te)
```

---

## 4. Vault Path Init (T1.4 D43 drill için, post-rotation)

```bash
# alertmanager-fallback path (T1.4 PR-1 ESO ExternalSecret bekliyor)
docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-test \
  vault kv put kv/platform/alertmanager-fallback \
    SLACK_WEBHOOK_URL="<test webhook URL — drill kanalı>" \
    SMTP_HOST="mailpit.platform-test.svc.cluster.local" \
    SMTP_PORT="587" \
    SMTP_USER="alertmanager-fallback@local" \
    SMTP_PASSWORD="<irrelevant for Mailpit; non-empty>"
```

ESO 1h refresh'i için elle tetikle:
```bash
kubectl --context k3d-test -n monitoring annotate externalsecret alertmanager-fallback-secrets \
  force-sync=$(date +%s) --overwrite
```

---

## 5. Pod Restart (yeni secret pickup)

ExternalSecret sync sonrası dependent pod'lar yeni K8s Secret'ı mount etmek için restart:

```bash
# notification-orchestrator (DB password drift sonrası kritik)
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s

# Plus PG'deki password Vault'taki ile sync olmalı (eğer Vault'ta password değişmiş ise):
# docker exec platform-pg-test psql -U postgres -d notify_db \
#   -c "ALTER USER platform WITH PASSWORD '<vault'taki gerçek password>';"
# (Vault'taki password ile PG ALTER USER eşleştirilir; password rotation policy)
```

---

## 6. Doğrulama (3 dakika)

| Check | Komut | Expected |
|---|---|---|
| ClusterSecretStore Ready | `kubectl get clustersecretstore vault-platform-gitops -o jsonpath='{.status.conditions[0].status}'` | `True` |
| ExternalSecret sync (notify) | `kubectl get externalsecret notification-orchestrator-secrets -n platform-test -o jsonpath='{.status.conditions[0].status}'` | `True` |
| ExternalSecret sync (alertmanager-fallback) | `kubectl get externalsecret alertmanager-fallback-secrets -n monitoring -o jsonpath='{.status.conditions[0].status}'` | `True` |
| Pod ready | `kubectl get pod -l app.kubernetes.io/name=notification-orchestrator -n platform-test -o jsonpath='{.items[0].status.containerStatuses[0].ready}'` | `true` |
| ESO log temiz | `kubectl logs deploy/external-secrets -n external-secrets --tail=30 \| grep -iE 'invalid\|denied'` | empty |
| T1.4 drill kapısı açık | (Step 5 RB-notification-outage-fallback prereq) | YES |

---

## 7. Audit Log

```
/var/log/platform-vault-audit.log:
2026-05-09T20:30:00Z | eso-vault-approle-rotate | accessor=<UUID> | by=halil@staging-sw
```

GitHub issue (governance trail):
```
gh issue create --repo Halildeu/platform-k8s-gitops \
  --title "[ops-audit] ESO Vault AppRole rotated $(date -u +%Y-%m-%d)" \
  --label "ops-audit,eso,vault" \
  --body "Vault AppRole eso-runtime secret-id rotated.
- Accessor: <UUID>
- Operator: $USER@$(hostname)
- Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)
- Trigger: ESO ClusterSecretStore 'invalid role or secret ID' 4xx login fail
- Post-rotation status: ClusterSecretStore Ready=True; ExternalSecret SecretSynced=True"
```

---

## 8. Rollback

Eğer rotation post-step 3.4 fail (ClusterSecretStore Ready=False kalır):

```bash
# Olası sebepler:
# 1. Vault auth/approle/login fail → Vault root token expired veya policy missing
# 2. K8s Secret update fail → namespace external-secrets RBAC issue
# 3. ESO controller pod CrashLoopBackOff → image issue

# Diagnostic:
kubectl describe clustersecretstore vault-platform-gitops
kubectl describe deploy/external-secrets -n external-secrets
docker exec platform-vault-test vault auth list

# Eğer Vault auth approle backend yok:
docker exec -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-test \
  vault auth enable approle
# Sonra Step 3.0 bootstrap
```

---

## 9. Periyodik Rotation Cadence

- **AppRole secret-id**: 30-day rotation (security best practice; HARD RULE policy: `secret_id_ttl="0" secret_id_num_uses="0"` infinite ama operasyon disiplin)
- **AppRole role-id**: rotation hiç gerekmez (UUID; role kaldırılırsa yeniden oluşturulur)
- **Vault root token**: ayrı runbook (post-cutover credential rotation D-N9)

---

## 10. Cross-Reference

- `bootstrap/vault-policies/common/eso-runtime.hcl` (policy authoritative)
- `kustomize/base/eso/clustersecretstore-vault.yaml` (CSS manifest)
- `kustomize/overlays/test/eso/clustersecretstore-patch.yaml` (test cluster role-id patch)
- `RB-notification-outage-fallback.md` Step 3.1 (T1.4 D43 drill prereq)
- ADR-0010 §2.5 boundary matrix (Vault credential boundary)
- Codex thread `019e0dea` iter-1 P1 #2 (T1.4 PR-1 review — ESO drift incident)

---

## 11. Last Update

**2026-05-09 20:15Z** — Created (Codex iter-1 P1 #2 absorb T1.4 PR-1 review). T1.4 D43 drill prereq #1.
