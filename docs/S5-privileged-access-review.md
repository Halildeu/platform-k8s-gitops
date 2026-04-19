# S5 Privileged Access Review — Day-2 Ops Rutini

> **Source:** K8s-6 S5 day-2 ops (Codex iter-8 non-blocking öneri)
> **Kapsam:** Vault AppRole + K8s RBAC + SSH erişim + GHCR PAT
> **Frekans:** Çeyrek yılda bir (tam review) + haftalık (anomali kontrol)

---

## 1. Privileged Credential Envanteri

### 1.1 Vault AppRole

| AppRole | Policy | Kullanıcı | Rotation |
|---|---|---|---|
| `eso-runtime` | `eso-runtime` | ESO Operator (K8s) | Secret-ID çeyrekte bir |
| `gitops-runtime` | `gitops-runtime` (ileride) | ArgoCD repo access veya CI | Çeyrekte bir |

### 1.2 Vault Admin Token

- **Root token:** sadece bootstrap anında kullanılır, sonra revoke (güvenlik best practice)
- **Admin token:** ops ekibi için günlük operasyon (Vault policy yönetimi)
- **Rotation:** 90 gün

### 1.3 K8s RBAC ClusterRole Bindings

| Subject | ClusterRole | Scope | Review notu |
|---|---|---|---|
| `system:serviceaccount:argocd:argocd-application-controller` | `cluster-admin` | cluster | Gerekli (GitOps sync) |
| `system:serviceaccount:external-secrets:external-secrets` | sınırlı | cluster-wide ExternalSecret CRD | OK |
| Platform servis SA'ları (auth-service, user-service, vb.) | sadece default + imagePullSecrets | namespace-scope | OK minimal |

**Anti-pattern:** Kullanıcı hesaplarına doğrudan `cluster-admin` binding — bunun yerine `kubectl` RBAC + rol-bazlı erişim.

### 1.4 SSH Erişim

| Host | Kullanıcı | Key | Review notu |
|---|---|---|---|
| staging-sw | halil | SSH public key (kurumsal) | Günlük ops |
| staging-sw-2 (D32) | halil | Aynı SSH key | D32 sonrası aktif |
| GitHub git+ssh+443 | halil, deploy key | SSH config port 443 override | Deploy key sadece read |

**Kural:** Ops ekibi dışında SSH erişimi YOK. deploy key sadece `read` (push yapmaz).

### 1.5 GHCR PAT (Personal Access Token)

- **Kullanım:** CI pipeline (push) + K8s ghcr-pull secret (pull)
- **Scope:**
  - CI PAT: `write:packages` + `read:packages`
  - K8s PAT: `read:packages` (Vault `kv/gitops/ghcr-token`)
- **Rotation:** Yıllık (veya GitHub expire ayarına bağlı)

---

## 2. Çeyreklik Review Checklist

### 2.1 Vault AppRole Secret ID Rotation

```bash
# Mevcut secret ID'yi revoke etmeden önce yeni üret
export VAULT_ADDR=http://<vault-host>:8200
vault login <admin-token>

NEW_SECRET_ID=$(vault write -f -field=secret_id auth/approle/role/eso-runtime/secret-id)
OLD_SECRET_ID=$(kubectl --context k3d-prod -n external-secrets \
  get secret vault-approle-secret -o jsonpath='{.data.secret-id}' | base64 -d)

# Update K8s Secret
kubectl --context k3d-prod -n external-secrets patch secret vault-approle-secret \
  -p "{\"data\":{\"secret-id\":\"$(echo -n "${NEW_SECRET_ID}" | base64)\"}}"

# ESO rollout restart (yeni secret-id pickup)
kubectl --context k3d-prod -n external-secrets rollout restart \
  deployment external-secrets

# 5 dk bekle + doğrula (yeni secret-id ile ClusterSecretStore Ready)
kubectl --context k3d-prod get clustersecretstore vault-platform-gitops

# Eski secret-id'yi revoke (list secret accessors + delete)
vault list auth/approle/role/eso-runtime/secret-id
vault delete auth/approle/role/eso-runtime/secret-id-accessor/<OLD_ACCESSOR>
```

### 2.2 K8s RBAC Audit

```bash
# Tüm cluster-admin binding'leri listele
kubectl --context k3d-prod get clusterrolebinding -o json \
  | jq '.items[] | select(.roleRef.name == "cluster-admin") | {name: .metadata.name, subjects: .subjects}'

# Platform ns RBAC
kubectl --context k3d-prod -n platform-prod get rolebinding,role -o json \
  | jq '.items[] | {kind, name: .metadata.name}'

# Anti-pattern check: user/group'a cluster-admin var mı?
kubectl --context k3d-prod get clusterrolebinding -o json \
  | jq '.items[] | select(.roleRef.name == "cluster-admin") | .subjects[] | select(.kind == "User" or .kind == "Group")'
# Beklenen: boş (sadece ServiceAccount'lara)
```

### 2.3 SSH Authorized Keys Review

```bash
# Her host'ta authorized_keys audit (staging-sw + staging-sw-2)
sudo cat /home/halil/.ssh/authorized_keys | wc -l
# Beklenen: bilinen key sayısı (değişim varsa audit)

# Fingerprint listesi
sudo ssh-keygen -lf /home/halil/.ssh/authorized_keys
# Her satır eşleşen ops ekibi kişisi kontrol
```

### 2.4 GHCR PAT Scope Audit

- GitHub portal: Settings → Developer settings → Personal access tokens
- Her PAT için:
  - Adı anlamlı mı? (örn. `k8s-ghcr-pull-vault-injected`)
  - Scope minimum mu? (`read:packages` pull için yeterli, `write:packages` sadece CI)
  - Expire date yaklaştı mı? (30 gün uyarı)
- Rotation: yeni PAT + Vault seed + eski PAT revoke

---

## 3. Haftalık Anomali Kontrolü

### 3.1 Vault Audit Log

```bash
# Son 7 gün policy değişiklikleri (review YASAK)
grep -h "sys/policies/acl" /var/lib/docker/volumes/host-compose_vault-logs/_data/audit.log.* \
  | jq 'select(.request.operation == "update" or .request.operation == "delete")' \
  | jq -s '.[] | {time, path, subject: .auth.display_name}'
# Beklenen: sadece bilinen ops hesabı
```

### 3.2 K8s API Audit

```bash
# Eğer k8s audit log enabled (k3d-prod cluster):
# /var/lib/rancher/k3s/server/logs/audit.log

# Son 24h privilege escalation denemeleri
grep -h "escalate" /var/lib/rancher/k3s/server/logs/audit.log* | tail -20
```

### 3.3 Failed Auth Spike

```promql
# Vault audit metric (custom exporter ile)
rate(vault_audit_failed_auth_total[5m]) > 0.5
# 5 dk'da 30+ failed auth = brute force belki
```

---

## 4. Bulgu Sonrası Aksiyon

| Bulgu | Severity | Aksiyon |
|---|---|---|
| Beklenmeyen cluster-admin binding | CRITICAL | Immediate delete + incident raporu |
| Vault policy change (bilinmeyen) | CRITICAL | Policy revert + audit log forensics |
| SSH authorized_keys yeni satır | WARNING | Ops ekibi doğrula — bilinmeyen ise delete |
| GHCR PAT expire < 7 gün | WARNING | Rotation başlat (1-2 gün içinde) |
| Vault audit exporter DOWN | CRITICAL | Monitoring restore önce (gözetim kaybı) |

---

## 5. Compliance Kaydı

Her çeyrek review sonrası:
- Audit raporu: `/home/halil/platform/audit/privileged-access-<YYYY-Q>.md`
- Bulgu + düzeltme + tarih + ops imza (manuel veya Git commit)
- 3 yıl retention (compliance gereksinimi)

---

## 6. Referanslar

- `bootstrap/vault-policies/` — Vault policy HCL şablonları + rotation
- `docs/S5-vault-audit-retention.md` — Audit log retention
- `docs/on-call-triage-playbook.md` — Alert sonrası aksiyon
- GitHub org settings (deploy key + PAT)
- PLAN.md D30 HARD RULE (immutable artifact + atomic cutover)
