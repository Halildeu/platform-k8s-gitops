# S5 Security Incident Response Runbook

> **Source:** K8s-6 S5 day-2 ops (security incident handling)
> **Kapsam:** Suspected breach, credential compromise, suspicious activity, container escape, DDoS
> **Severity:** Tümü P0 — immediate response
> **Compliance:** 3 yıl kayıt retention

---

## 1. Incident Kategorileri

| Tip | Trigger | İlk aksiyon |
|---|---|---|
| **Credential compromise** | Vault audit suspicious access / PAT leaked / GitHub secret scan | Credential revoke + rotation |
| **Container escape** | Kyverno disallow-privileged policy trigger / runtime anomaly | Pod isolate + image scan |
| **Suspicious edge traffic** | Edge log `.env`/`.git`/`/admin` pattern / rate spike | IP block + WAF rule |
| **Supply chain compromise** | GHCR image tamper / digest mismatch / unexpected base image | Deploy freeze + digest audit |
| **DDoS** | Edge 5xx sustained + request rate spike | Rate limit + upstream temp block |
| **Data exfiltration** | PG activity unusual / network egress spike | Audit query + network block |

---

## 2. Credential Compromise (P0, ilk 15 dk)

### 2.1 Vault Compromise Senaryosu

**Trigger:** `VaultFailedAuthSpike` alert veya audit log'da beklenmeyen kullanıcı.

**İlk aksiyon (0-5 dk):**
```bash
# 1. Vault audit log tail — şüpheli kullanıcı tespit
tail -n 1000 /srv/platform/stateful/prod/vault/logs/audit.log \
  | jq 'select(.auth.display_name != "admin" and .auth.display_name != "eso-runtime")'

# 2. Compromised role/token listele
VAULT_TOKEN=<admin> vault list auth/approle/role
VAULT_TOKEN=<admin> vault list auth/token/accessors | head -20

# 3. Şüpheli accessor revoke
VAULT_TOKEN=<admin> vault token revoke -accessor <accessor-id>

# 4. ESO AppRole secret-id rotate (ihtiyat)
NEW_SECRET_ID=$(VAULT_TOKEN=<admin> vault write -f -field=secret_id \
  auth/approle/role/eso-runtime/secret-id)
kubectl -n external-secrets patch secret vault-approle-secret \
  -p "{\"data\":{\"secret-id\":\"$(echo -n "${NEW_SECRET_ID}" | base64)\"}}"
kubectl -n external-secrets rollout restart deployment external-secrets
```

**5-15 dk:**
- KV path access pattern incele (`vault list kv/metadata/platform/`)
- Hangi secret'ler erişildi? (`vault kv metadata get kv/platform/<svc>`)
- Gerekirse KV path'ler rotate (DB password + JWT key + KC client secret)
- Audit log 90 gün full export (forensics)

### 2.2 GHCR PAT Compromise

**Trigger:** GitHub secret scanning uyarısı veya push log'unda suspicious actor.

**İlk aksiyon:**
```bash
# 1. GitHub portal: Settings → Developer settings → Personal access tokens
# 2. Compromised PAT "Delete" (revoke)
# 3. Yeni PAT create (read:packages veya write:packages)
# 4. Vault seed update:
VAULT_TOKEN=<admin> vault kv put kv/gitops/ghcr-token \
  username=halildeu password=<NEW_PAT>
# 5. ESO ExternalSecret refresh (30dk default veya manuel trigger)
kubectl --context k3d-prod -n platform-prod annotate externalsecret ghcr-pull \
  force-sync=$(date +%s) --overwrite
```

### 2.3 K8s ServiceAccount Token Compromise

**Trigger:** K8s audit log'unda beklenmeyen API access.

**İlk aksiyon:**
```bash
# 1. SA token rotate (K8s 1.24+ bound token gerekli — pod restart)
kubectl delete pod -l app.kubernetes.io/name=<svc> -n platform-prod
# Pod recreate → yeni SA token

# 2. Legacy SA secret silme (varsa)
kubectl get sa <sa-name> -n platform-prod -o yaml | grep secret
kubectl delete secret <sa-secret> -n platform-prod
```

---

## 3. Container Escape Suspicion (P0)

**Trigger:** Kyverno `disallow-privileged-pods` policy audit log, runtime anomaly (pod sudo attempt vb.).

**İlk aksiyon (0-10 dk):**
```bash
# 1. Pod isolate (network policy drop)
kubectl -n platform-prod label pod <suspicious-pod> quarantine=true

# NetworkPolicy quarantine rule (temp):
cat <<YAML | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: quarantine-drop
  namespace: platform-prod
spec:
  podSelector:
    matchLabels:
      quarantine: "true"
  policyTypes: [Ingress, Egress]
  # ingress + egress yok → tümü drop
YAML

# 2. Pod state snapshot (forensics)
kubectl -n platform-prod describe pod <pod> > /tmp/pod-snapshot-$(date +%s).txt
kubectl -n platform-prod logs <pod> --tail=5000 > /tmp/pod-logs-$(date +%s).txt

# 3. Image scan (Trivy veya Snyk)
trivy image <pod-image>
# HIGH/CRITICAL CVE varsa base image compromise

# 4. Pod silme (teşhis + snapshot sonrası)
kubectl -n platform-prod delete pod <pod>
```

**10-30 dk:**
- Aynı image kullanan pod'lar listesi
- Overlay tag'i önceki bilinen-güvenli sha-<short>'a geri al
- Image Dockerfile audit (GHCR)
- Base image (`eclipse-temurin:21-jre` vb.) güvenlik güncellemesi

---

## 4. Suspicious Edge Traffic (P1/P0)

**Trigger:** Ingress access log suspicious pattern.

**İlk aksiyon:**
```bash
# 1. Kaynak IP analiz (son 1h)
kubectl -n ingress-nginx logs -l app.kubernetes.io/name=ingress-nginx --tail=10000 \
  | jq -r 'select(.req | test("\\.env|\\.git|/admin|phpmyadmin|wp-admin")) | .ip' \
  | sort | uniq -c | sort -rn | head -20

# 2. Top IP'leri nginx rate limit veya drop
# (ingress-nginx ConfigMap rate-limit-rps veya whitelist/blacklist)

# 3. Kurumsal L4 proxy seviyesi IP block (sysadmin)
```

---

## 5. Supply Chain Compromise (P0)

**Trigger:** GHCR image digest kustomize overlay beklenenden farklı veya beklenmeyen base image layer.

**İlk aksiyon:**
```bash
# 1. Deploy freeze
argocd app set platform-prod --sync-policy none
kubectl -n argocd annotate application platform-prod \
  argocd-image-updater.argoproj.io/ignore=true

# 2. Mevcut pod imageID audit (tüm 8 servis)
for svc in auth-service api-gateway user-service variant-service \
           core-data-service report-service schema-service permission-service; do
  kubectl -n platform-prod get pod -l app.kubernetes.io/name=${svc} \
    -o jsonpath='{.items[0].status.containerStatuses[0].imageID}' 2>/dev/null
  echo " $svc"
done

# 3. Overlay beklenen tag vs gerçek digest
kustomize build kustomize/overlays/prod | grep "image:" | sort -u

# 4. Trivy scan tüm image'lar
for tag in $(kustomize build kustomize/overlays/prod | grep -oE "ghcr.io/[^ ]+" | sort -u); do
  trivy image --severity HIGH,CRITICAL "${tag}"
done

# 5. Rollback bilinen-güvenli sha (varsa):
kustomize edit set image <svc>=ghcr.io/...:sha-<known-safe>
git commit + PR + merge (manuel hızlı)
```

---

## 6. DDoS / Rate Spike (P1)

**Trigger:** Edge 5xx spike + request rate 10× baseline.

**İlk aksiyon:**
```bash
# 1. Rate limit trigger ingress-nginx ConfigMap (eğer yok, canlı patch):
kubectl -n ingress-nginx patch configmap ingress-nginx-controller \
  --type merge -p '{"data":{"limit-req-rpm":"60","limit-req-burst":"10"}}'

# 2. Source IP analiz (üst 10 IP)
kubectl -n ingress-nginx logs -l app.kubernetes.io/name=ingress-nginx --tail=10000 \
  | jq -r '.ip' | sort | uniq -c | sort -rn | head -10

# 3. Top IP'leri temp drop (kurumsal L4)
```

---

## 7. Post-Incident Süreci

### 7.1 Forensics (ilk 24h)

- [ ] Log snapshot (Vault + K8s API + edge + Loki) — /tmp/ veya secure archive
- [ ] Pod state snapshot (describe + logs + events)
- [ ] Network topology snapshot (NetworkPolicy + Service + Endpoints)
- [ ] Timeline docs (T+0 trigger → T+aksiyon)

### 7.2 Codex Post-Mortem (ilk 72h)

- Yeni Codex thread, post-mortem prompt
- Root cause + timeline + lessons learned
- Fix + test coverage + runbook update
- Repo: `docs/post-mortem-<YYYY-MM-DD>-<short-id>.md`

### 7.3 Compliance Kaydı

- `/home/halil/platform/audit/incident-<YYYY-MM-DD>-<severity>.md`
- Bulgu + aksiyon + imza + 3 yıl retention
- Compliance audit toplu hazır

---

## 8. Preventive Hardening Checklist

- [ ] Kyverno policy enforce mode (audit'ten geçiş)
- [ ] NetworkPolicy default-deny tüm ns'lerde (mevcut `netpol/`)
- [ ] Vault audit backend aktif + logrotate (mevcut `docs/S5-vault-audit-retention.md`)
- [ ] SSH authorized_keys audit (mevcut `docs/S5-privileged-access-review.md`)
- [ ] GHCR image scanning CI (Trivy/Snyk) — eklenmeli
- [ ] Sealed Secrets yerine ESO + Vault (mevcut)
- [ ] Bound SA token (K8s 1.24+ default)
- [ ] runAsNonRoot + readOnlyRootFilesystem (Kyverno policy)
- [ ] ingress-nginx rate limiting (canlı ConfigMap)
- [ ] Fail2ban veya benzer host-level (sysadmin)

---

## 9. Referanslar

- `docs/on-call-triage-playbook.md` — Alert karar matrisi
- `docs/S5-privileged-access-review.md` — Credential audit çeyreklik
- `docs/S5-vault-audit-retention.md` — Vault audit log
- `docs/S4-rollback-runbook.md` — Immediate rollback (network/edge incident sonrası)
- `kustomize/base/policies/` — Kyverno ClusterPolicy (admission level prevention)
- PLAN.md D28/D29/D30 HARD RULE
