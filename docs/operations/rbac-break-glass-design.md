# RBAC Break-Glass Design — Codex P0 #5

> **Codex AGREE Session 37** (2026-05-04, thread `019df2bf`, item #9):
> "Runner/operator RBAC'tan normal `patch deployments` yetkisini çıkar.
> ArgoCD SA tek normal writer olsun. Break-glass SA TTL token + audit +
> mandatory reconciliation PR. Admission/Kyverno/Gatekeeper şart değil;
> önce RBAC + audit yeter."

> **Güncelleme — 2026-05-18 (PR-2, Codex `019e35d1` 4-PR planı)**: Prod
> image-only deploy workflow'ları `deploy-backend-prod.yml` +
> `deploy-frontend-prod.yml` emekli edildi (silindi). Prod'un `kubectl set
> image` CI yolu artık **yok** — tek normal writer ArgoCD: `production`
> env-gate'li `deploy-prod-gitops.yml` (PR-1, `#780`). Aşağıdaki **Faz 4'ün
> prod ayağı bu retire ile karşılandı**; `deploy-backend-testai.yml` (test
> cluster) image-only deploy hâlâ Faz 4 kapsamında. Aşağıdaki audit
> snapshot'ı Session 37 durumu — `deploy-backend-prod.yml:148` satır
> referansı artık geçersiz.

Bu doc, manuel `kubectl set image` müdahalelerinin nasıl D30 immutable
artifact disiplinine sokulacağını belirler. Implementation ayrı PR;
burada **design + audit + migration playbook** var.

## PR-3A güncelleme — 2026-05-18 (Codex `019e380b`)

prod-deploy 4-PR planı (Codex `019e35d1`) PR-3, Codex `019e380b` scope kararı
ile **alt-adımlara bölündü**. PR-3A repo-only contract; canlı RBAC enforcement
PR-3B/C/D/E (operator-gated). Aşağıdaki "Codex P0 sequence" tablosu Session 37
planıdır; güncel sıralama bu bölümdedir.

### Faz 2 (break-glass SA) gerçek durumu

`kustomize/base/rbac/break-glass-sa.yaml` + `kustomization.yaml` +
`scripts/operations/break-glass-token.sh` repo'da **var**, ama
`kustomize/base/rbac` hiçbir overlay'e veya `kustomize/base/kustomization.yaml`'a
**bağlı değil** (orphan). Canlı doğrulama: `kubectl --context k3d-prod -n
kube-system get sa ops-break-glass` → **NotFound**. Faz 2 "manifest yazıldı,
hiçbir cluster'a deploy edilmedi" durumunda. Canlıya alma → PR-3B.

### Faz 3 tasarım düzeltmesi

Aşağıdaki Faz 3'teki "`admin@k3d-prod` user'a `view` ClusterRoleBinding ekle"
yaklaşımı **teknik olarak eksik**: Kubernetes RBAC **additive**'dir — mevcut
cluster-admin binding dururken ayrıca `view` bağlamak yetkiyi DÜŞÜRMEZ. Doğru
Faz 3 (→ PR-3D): yeni readonly normal identity üret + günlük kullanıma al;
eski `admin@k3d-prod`'u normal path'ten çıkar, yalnız break-glass/offline
issuer olarak sakla.

### PR-3A katkısı (bu PR, repo-only)

- `kustomize/base/rbac/prod-deploy-smoke/` — `prod-deploy-smoke` SA + Role'ler:
  `argocd` ns'de argocd-server port-forward + read; `platform-prod` ns'de
  deployment/pod read+watch. Workload-mutate (patch / set image / scale / exec)
  YOK.
- Standalone kustomize entrypoint — hiçbir overlay/base consume etmez; ArgoCD
  `platform-prod` sync path'ine girmez. CI yalnız `kustomize build` render
  doğrular. **Merge anında canlı state değişmez.**
- Runbook: `docs/operations/RUNBOOKS/RB-prod-rbac-least-privilege.md`.

### Güncel sıralama (PR-3 alt-adımları)

| Alt-PR | İş | Boundary |
|---|---|---|
| **PR-3A** (bu PR) | repo-only: prod-deploy-smoke staged manifest + runbook + bu güncelleme | none (no live mutation) |
| **PR-3B** | break-glass SA live activation + token issuance smoke | state-mutation (prod) — operator-gated |
| **PR-3C** | prod-deploy-smoke apply + runner kubeconfig least-privilege cutover | state-mutation (prod) — operator-gated |
| **PR-3D** | operator readonly identity migration (Faz 3 düzeltilmiş) | state-mutation (prod) + owner coordination |
| **PR-3E** | audit/alarm (Faz 5) | düşük |

`deploy-backend-testai.yml` (test cluster) image-only `kubectl set image` yolu
PR-3 kapsamı dışı — ayrı izlenir.

## Sorun: D30 disiplini bozuk

Session 37 audit'inde tespit edilen pattern:

| Müdahale | Etki | Karşılaşılan |
|---|---|---|
| `kubectl set image deploy/api-gateway` | Live Deployment spec güncellenir, gitops yaml drift kalır | PR #321/#332 cleanup'ta yaşandı |
| `kubectl patch configmap` (KC env hot-fix) | Live config değişir, gitops yaml düzeltilmedi | PR #330/#333 cleanup'ta yaşandı |
| `kubectl rollout restart deploy` | State değişimi yok ama envFrom pickup için kullanıldı | Normal pattern, sorun yok (read benzeri) |
| `kubectl scale deploy --replicas=N` | Live replica değişir, yaml drift | Session 37 api-gateway recovery'de yapıldı |

**Sonuç**: ArgoCD `Synced/Healthy` rapor etse bile cluster'ın gerçek
state'i gitops yaml'dan farklı. Drift detector (PR #334) bunu yakalıyor
ama **önleme** yok — yetkisi olan herkes break-glass'sız manuel mutate
edebiliyor.

## Şu anki RBAC durumu (audit)

```
ArgoCD:
  ClusterRoleBinding: argocd-application-controller
  ClusterRoleBinding: argocd-server
  → cluster-admin level, yaml apply yetkili (tasarım hedefi)

Operator (halil) kubeconfig:
  user: admin@k3d-prod
  → cluster-admin (k3d default), her şeyi yapabilir
  → Session 37'deki tüm manuel `kubectl set image / patch / scale`
    bu kullanıcı ile yapıldı

GitHub Actions runner (deploy-backend-prod.yml):
  → kubeconfig içinde admin@k3d-prod kullanıyor
  → CI workflow'unda `kubectl set image` step'i var
    (deploy-backend-prod.yml:148)
  → Ne ArgoCD SA, ne break-glass SA — operator'ın admin token'ı
    GitHub secret'ında saklı

Sonuç: 3 farklı entity (operator, runner, ArgoCD) hepsi cluster-admin.
Hangisi ne yaptığı audit log dışında belirlenemez. ArgoCD "single source
of write" değil — herhangi biri override edebilir.
```

## Hedef state

```
[ArgoCD SA — single normal writer]
  ClusterRoleBinding: cluster-admin (gitops desired-state apply)
  Audit: ArgoCD UI/CLI history, sync events

[Operator kubeconfig — read-only by default]
  ClusterRoleBinding: view + cluster-info read
  Resource patch yetkisi YOK
  Manuel `kubectl set image` denemesi → "Forbidden: User cannot patch deployments"

[Break-glass SA — TTL token, audit-on-use]
  Name: ops-break-glass
  ClusterRoleBinding: cluster-admin
  Token: ServiceAccount token (k8s 1.24+ projected token, max 1h TTL)
  Provisioning: helper script `scripts/operations/break-glass-token.sh`
  Audit: kubectl audit log + zorunlu reconciliation PR (assertion)

[CI runner SA — restricted writer]
  ClusterRoleBinding: deploy-restricted (configmap update, deploy restart, get/list)
  Resource patch yetkisi YOK
  `kubectl set image` çağrısı CI workflow'undan KALDIRILACAK
  Yerine: gitops PR generator bot (Codex P0 #2 — separate)
```

## Migration playbook

### Faz 1 — Audit (bu PR'da yapıldı)

- ArgoCD SA, operator kubeconfig, runner config baseline alındı
- Mevcut müdahale pattern'leri Session 37 PR history'sinden çıkarıldı

### Faz 2 — Break-glass SA tanımı (ayrı PR)

```yaml
# kustomize/base/rbac/break-glass-sa.yaml (yeni dosya)
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ops-break-glass
  namespace: kube-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ops-break-glass-cluster-admin
subjects:
  - kind: ServiceAccount
    name: ops-break-glass
    namespace: kube-system
roleRef:
  kind: ClusterRole
  name: cluster-admin
  apiGroup: rbac.authorization.k8s.io
```

Helper script:

```bash
# scripts/operations/break-glass-token.sh
# Issues a 1-hour TTL token for the ops-break-glass SA
# Logs the request to /var/log/break-glass-audit.log + GitHub issue audit
NS=kube-system
SA=ops-break-glass
DURATION=1h
REASON="${1:-MISSING_REASON}"

[[ "$REASON" == "MISSING_REASON" ]] && {
  echo "ERR: provide reason: ./break-glass-token.sh '<reason>'"
  exit 1
}

TOKEN=$(kubectl create token "$SA" -n "$NS" --duration="$DURATION")
echo "$(date -Iseconds) | break-glass | reason=$REASON | requested-by=$USER" >> /var/log/break-glass-audit.log
gh issue create --title "Break-glass token issued: $REASON" --label "ops-audit" --body "..."

export KUBECONFIG=/tmp/kubeconfig-break-glass-$$
# write minimal kubeconfig with TOKEN
echo "Token issued. KUBECONFIG=$KUBECONFIG (1h TTL)"
echo "Reconciliation PR REQUIRED within 30min of any state change."
```

### Faz 3 — Operator kubeconfig restrict (ayrı PR)

> **Düzeltme — PR-3A (Codex `019e380b`)**: Aşağıdaki `view` ClusterRoleBinding
> yaklaşımı eksik — RBAC additive; mevcut cluster-admin dururken `view` eklemek
> yetki düşürmez. Doğru tasarım yukarıdaki "PR-3A güncelleme → Faz 3 tasarım
> düzeltmesi" bölümünde (→ PR-3D yeni readonly identity).

```yaml
# kustomize/base/rbac/operator-readonly.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: operator-readonly
subjects:
  - kind: User
    name: admin@k3d-prod
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: view
  apiGroup: rbac.authorization.k8s.io
```

`admin@k3d-prod` artık sadece `view` yetkisinde. Mutate için:
1. `./scripts/operations/break-glass-token.sh "fixing X"` çalıştır
2. `KUBECONFIG=...` ile o oturumda mutate
3. 30dk içinde reconciliation PR (gitops yaml = cluster live)

### Faz 4 — CI runner kısıtlama (ayrı PR)

```yaml
# kustomize/base/rbac/ci-runner-deploy.yaml
# CI runner'a `kubectl set image` yetkisi VERME — sadece configmap update,
# rollout restart (envFrom pickup), get/list/describe.
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ci-runner-deploy
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["update", "patch", "get"]
  - apiGroups: ["apps"]
    resources: ["deployments/restart"]
    verbs: ["create"]  # rollout restart için
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list"]
  # PATCH ve UPDATE yetki YOK — kubectl set image fail etsin
```

CI workflow değişikliği (deploy-backend-prod.yml ve deploy-backend-testai.yml):
- `kubectl set image` adımı KALDIRILACAK
- Yerine gitops PR generator bot (Codex P0 #2 — image digest yaml update)

### Faz 5 — Audit log + alarm

```
audit-policy.yaml — kubectl operations log to /var/log/k8s-audit.log
break-glass usage → GitHub issue + email
RBAC violation (Forbidden) → metric + dashboard
```

## Reconciliation PR contract

Break-glass kullandıktan sonraki **30 dakika içinde** zorunlu PR:

```markdown
## Break-glass reconciliation

**Date**: 2026-XX-XX
**Reason**: ... (audit log'dan kopyala)
**Cluster change**: ... (kubectl set image / patch detayı)

## Yaml update

(diff göster)

## Verification

kubectl kustomize ... | diff <(kubectl get ... -o yaml)
→ should match
```

PR template: `.github/PULL_REQUEST_TEMPLATE/break-glass-reconciliation.md`

## Codex P0 sequence

> Session 37 planı (tarihsel). Güncel sıralama: yukarıdaki "PR-3A güncelleme —
> 2026-05-18" bölümü (4-PR prod-deploy planı PR-3 alt-adımları PR-3A..E).

| Sıra | İş | Risk |
|---|---|---|
| **P0a (bu PR)** | Audit + design doc | Düşük (yalnız yazı) |
| **P0b** | Break-glass SA + helper script (Faz 2) | Düşük (sadece spec, kullanım opsiyonel) |
| **P0c** | Operator kubeconfig restrict (Faz 3) | Orta (manuel müdahale yolu kapanır) |
| **P0d** | CI runner restrict + kubectl set image kaldır (Faz 4) | Orta (CI workflow değişikliği — test cluster önce) |
| **P0e** | Audit log + alarm (Faz 5) | Düşük |

**Bağımlılıklar**: P0d, Codex P0 #2 (gitops PR generator bot) gerektirir.
Bot olmadan kubectl set image kaldırılırsa CI deploy yolu kesilir. Sıra:
P0 #2 (PR generator) → P0 #5d (CI restrict).

## Boundary boundary

Bu PR:
- [x] none of the above (sadece doküman)

Implementation PR'ları (P0b-e):
- [x] state-mutation (production) — RBAC manifest cluster'a apply olur

Her birinde ayrı user-approval-required gate.

## İlişkili belgeler

- ADR-0011 §2.3 boundary declaration
- `docs/context-priority-rules.md` — truth hierarchy
- `scripts/drift-detection/check_env_drift.sh` — drift detector (PR #334)
- `scripts/drift-detection/check_pr_time.sh` — PR-time gate (PR #335)
- `docs/authz/openfga-model-contract.md` — OpenFGA contract (PR #336)
- `scripts/drift-detection/check_quota_headroom.sh` — quota preflight (PR #337)
