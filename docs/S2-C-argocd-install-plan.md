# S2-C: ArgoCD Install + App-of-Apps Plan

> **Source:** K8s-6 S2 scope (2026-04-19)
> **Codex Tur 1 kararı:** "ArgoCD MVP'de sadece prod cluster yönetsin, multi-cluster ertele"
> **S2-C scope:** Test cluster için ArgoCD install opsiyonel (dev ergonomics), PROD için D32 staging-sw-2 sonrası (F2.4)

---

## 1. Apply Sırası (S2)

### S2-C1 — ArgoCD Install Test Cluster (opsiyonel, dev ergonomics)

**Mevcut script:** `bootstrap/install-argocd.sh prod` — D32 staging-sw-2'de kullanılacak.

**Test için opsiyonel:**
```bash
# Test cluster için ArgoCD ayrı instance (GitOps sync önizleme)
bash bootstrap/install-argocd.sh test
# Veya prod cluster ArgoCD multi-cluster kaydı
argocd cluster add k3d-test --name test-cluster --project platform
```

**Codex önerisi:** Test için ArgoCD install **S3 stability soak** öncesi gereksiz. S4 prod cutover yaklaştığında kur (test cluster'daki state'i ArgoCD'den görmek için).

**Bugünkü durum:** Yazılı plan var, apply S3/S4 session'da.

### S2-C2 — ArgoCD Application CR'ları (app-of-apps)

**Manifest yapısı:**

```
argocd/applications/
├── root.yaml              # app-of-apps kök (tüm diğer Application'ları yönetir)
├── platform-system.yaml   # ingress-nginx + ESO + kube-prometheus-stack + Loki + Tempo
├── platform-test.yaml     # overlays/test sync
└── platform-prod.yaml     # overlays/prod sync (manual sync, D32 sonrası)
```

**root.yaml taslak:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/Halildeu/platform-k8s-gitops.git
    targetRevision: main
    path: argocd/applications
    directory:
      recurse: false
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**platform-prod.yaml taslak (manual sync — D30 atomic cutover):**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-prod
  namespace: argocd
spec:
  project: platform
  source:
    repoURL: https://github.com/Halildeu/platform-k8s-gitops.git
    targetRevision: main
    path: kustomize/overlays/prod
  destination:
    name: prod-cluster         # D32: staging-sw-2 k3d-prod (ayrı cluster)
    namespace: platform-prod
  syncPolicy:
    # MANUAL sync — D30 HARD RULE: atomic cutover, auto-sync YOK
    automated: {}
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas  # HPA veya manuel scale korunur (D21)
```

## 2. Faz 10 Kabul Kriteri

- [ ] ArgoCD UI'da 4 application (root + 3 platform) healthy + synced
- [ ] Git push → ArgoCD 3dk içinde reconcile
- [ ] Prod application manual sync (D30 atomic cutover gereği)
- [ ] Test application auto-sync (dev ergonomics)

## 3. Codex İstişare

**Bugün scope:** Sadece plan doküman. Apply **S3 öncesi opsiyonel (test cluster)** veya **S4 D32 sonrası zorunlu (prod)**.

Küçük scope, Codex plan istişaresi gereksiz. Apply'da istişare gerekli.

## 4. Prompt (S3/S4 session'a)

```
TASK: S2-C ArgoCD install + app-of-apps
From: K8s-6 S2 plan

Detay: platform-k8s-gitops/docs/S2-C-argocd-install-plan.md

Sıra:
1. test cluster: bash bootstrap/install-argocd.sh test (opsiyonel S3)
2. argocd/applications/ dizini + 4 CR (root + platform-system/test/prod)
3. Git push + ArgoCD first sync

Prod ArgoCD: D32 staging-sw-2 bootstrap F2.4 adımında.
```
