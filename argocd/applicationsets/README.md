# ArgoCD ApplicationSet Patterns

> **Status:** DRAFT — D32 sonrası multi-cluster ArgoCD için. Şu an `argocd/applications/` altı 6 tek Application ile yönetiliyor.
> **Source:** K8s-6 S2-C ArgoCD install plan (Codex ileri iş)

---

## 1. Pattern Açıklaması

**Sorun:** Her cluster (test + prod) için ayrı Application manifest yazmak tekrar. Multi-cluster ArgoCD'de cluster generator pattern ile tek ApplicationSet → her cluster için ayrı Application render.

**Çözüm:** ArgoCD ApplicationSet CRD cluster selector ile:

```yaml
spec:
  generators:
    - clusters:
        selector:
          matchLabels:
            platform: "true"
  template:
    # {{name}}, {{server}}, {{metadata.labels.<X>}} template var'lar
```

## 2. Aktivasyon Adımları (D32 sonrası)

### 2.1 Cluster Secret Label

Prod ArgoCD'de her cluster secret (`argocd/secret/<cluster-name>`) label'lanır:

```bash
# Test cluster (staging-sw k3d-test)
kubectl --context k3d-prod -n argocd label secret cluster-test \
  platform=true env=test

# Prod cluster (staging-sw-2 k3d-prod, kendi)
kubectl --context k3d-prod -n argocd label secret cluster-prod \
  platform=true env=prod
```

### 2.2 Mevcut Application'ları Kaldır

```bash
# Önce ApplicationSet'i apply et, sonra eski Application'ları sil
# (ApplicationSet yeni Application'ları render edecek, aynı adla çakışma olmaz)

kubectl --context k3d-prod -n argocd delete application platform-test
kubectl --context k3d-prod -n argocd delete application platform-prod
kubectl --context k3d-prod -n argocd delete application platform-eso-test
kubectl --context k3d-prod -n argocd delete application platform-eso-prod
```

### 2.3 ApplicationSet Apply

```bash
kubectl --context k3d-prod apply -f argocd/applicationsets/platform-overlays.yaml
kubectl --context k3d-prod apply -f argocd/applicationsets/platform-eso.yaml

# Doğrula (ApplicationSet → N tane Application render eder)
argocd --server argocd.prod.local appset list
argocd --server argocd.prod.local app list
# Beklenen: platform-test + platform-prod + platform-eso-test + platform-eso-prod
```

### 2.4 ArgoCD root.yaml update

`argocd/applications/root.yaml` app-of-apps şu an `argocd/applications/` path'i yönetir. ApplicationSet aktif olursa:

```yaml
# argocd/applications/root.yaml path güncellenir:
source:
  path: argocd/applicationsets     # applications/ yerine applicationsets/
```

Veya ikisi paralel (hybrid): hem `applications/` hem `applicationsets/` path'leri root.yaml tarafından yönetilir — directory recursion.

## 3. Pattern Avantajlar

- **DRY:** Template tek yerde, cluster ekleme sadece secret label ile
- **Multi-env tutarlılık:** selfHeal, syncPolicy, ignoreDifferences cluster'a göre template condition
- **Scale:** 10+ cluster'a büyüme zaman tek ApplicationSet (vs 10+ Application)

## 4. Dezavantaj / Risk

- **Karmaşıklık:** Template var + cluster secret label prerequisite
- **Debugability:** ApplicationSet fail → hangi cluster için template fail? log filtreleme zor
- **D30 atomic cutover:** Prod için selfHeal=false template condition kritik — test edilmemiş `{{- if eq -}}` syntax

## 5. Şu An Kullanım

**MVP (D32 öncesi):** Bireysel Application CR'lar (`argocd/applications/platform-*.yaml`). ApplicationSet dosyaları bu dizinde draft olarak durur.

**D32 sonrası:** Multi-cluster ArgoCD (prod → test + prod yönetir) aktif olunca bu pattern'e geçiş değerlendirilir.

## 6. Referanslar

- ArgoCD ApplicationSet docs: <argocd-docs> (çevrimiçi)
- `docs/S2-C-argocd-install-plan.md` — tek Application pattern (mevcut)
- `argocd/applications/` — mevcut 6 Application CR
