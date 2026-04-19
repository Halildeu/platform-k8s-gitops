# HAND-OFF: S2-B Artifact Hardening (W1 ghcr-pull ESO + W3 Digest Pin CI)

> **Source:** K8s-6 Seviye 2 scope (2026-04-19)
> **Target:** platform-ssot CI + ops (ESO ConfigMap + deploy-backend.yml workflow)
> **Priority:** P1 S2 scope — D30 Immutable Artifact HARD RULE tam uyumu + W1 pull drift'in kalıcı kapanışı

---

## 1. Bağlam

Seviye 1'de iki geçici/minimal çözüm uygulandı:
- **W1 ghcr-pull:** staging-sw docker GHCR login + image preloaded → pod-level `ghcr-pull` Secret eksik ama pull zaten başarılı (local cache). Kalıcı çözüm ESO ExternalSecret.
- **W3 digest pin:** permission-service için **pilot** `sha-3923901` immutable tag, diğer 7 servis hâlâ `main-stable` moving tag. D30 tam uyumu için full digest/SHA pin CI tarafında.

## 2. W1 — ghcr-pull ESO ExternalSecret

### 2.1 Mevcut Durum

- K8s-6 tarafında `kustomize/base/apps/<svc>/serviceaccount.yaml` her servis için `imagePullSecrets: [{name: ghcr-pull}]` referansı **VAR** (D26 pattern)
- Cluster'da `ghcr-pull` Secret **YOK** — stub uyarı: `FailedToRetrieveImagePullSecret`
- Mevcut pod'lar lokal image ile çalışıyor (staging-sw docker GHCR login + preload)
- **Risk:** yeni pod reschedule + lokal cache temizlenirse GHCR pull fail

### 2.2 İstenen İş

**K8s-gitops tarafı:**
- `kustomize/base/eso/` dizini (veya mevcut `host-services` yanına)
  - `externalsecret-ghcr-pull.yaml` — ESO CR: Vault'tan `kv/gitops/ghcr-token` → K8s Secret `ghcr-pull` type `docker-registry`
  - ClusterSecretStore (eğer tanımlı değilse) — Vault AppRole + read policy `gitops-runtime`

**Vault tarafı (ops iş):**
- `vault kv put kv/gitops/ghcr-token username=<pat-user> password=<github-pat>`
- PAT scope: `read:packages` (GHCR private read)
- AppRole `gitops-runtime` policy: `path "kv/data/gitops/ghcr-token" { capabilities = ["read"] }`

**ESO Installation (Faz 3, D9):**
- ClusterSecretStore `vault-platform-gitops` tanımlı olmalı
- Secret refresh interval 30min (token rotation)

### 2.3 Kabul Kriteri

- [ ] `kubectl -n platform-test get secret ghcr-pull` **VAR** (type kubernetes.io/dockerconfigjson) — **workload ns** (Codex iter-5 Opsiyon B)
- [ ] `kubectl -n platform-test get externalsecret ghcr-pull` Synced=True
- [ ] ESO pod Running (`kubectl -n external-secrets get pods`)
- [ ] Pod spec `imagePullSecrets: [{name: ghcr-pull}]` aktif kullanım
- [ ] **Cache-busting gerçek pull kanıtı** (Codex iter-5 uyarısı — "secret var" ≠ "pull auth çalıştı"): (a) fresh sha-<short> tag deploy veya (b) node image cache temizle + rollout restart veya (c) `kubectl describe pod` Events'da `Successfully pulled image`

### 2.4 K8s-6 Manifest (Codex iter-5 Opsiyon B — overlay-specific)

**Kalıcı konum:** `kustomize/overlays/test/eso/externalsecret-ghcr-pull.yaml` + `kustomize/overlays/prod/eso/externalsecret-ghcr-pull.yaml` (base/eso'da DEĞİL — namespace drift önlemi).

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: ghcr-pull
  namespace: platform-test    # workload ns (overlay-specific)
spec:
  refreshInterval: 30m
  secretStoreRef:
    kind: ClusterSecretStore
    name: vault-platform-gitops
  target:
    name: ghcr-pull
    template:
      type: kubernetes.io/dockerconfigjson
      data:
        .dockerconfigjson: |
          {
            "auths": {
              "ghcr.io": {
                "auth": "{{ printf "%s:%s" .username .password | b64enc }}"
              }
            }
          }
  data:
    - secretKey: username
      remoteRef:
        key: kv/gitops/ghcr-token
        property: username
    - secretKey: password
      remoteRef:
        key: kv/gitops/ghcr-token
        property: password
```

## 3. W3 — Full Digest Pin CI (platform-ssot workflow)

### 3.1 Mevcut Durum

- K8s-gitops `overlays/test + overlays/prod` kustomization `images:` tablosu 7 servis `newTag: main-stable` (moving tag), 1 servis `newTag: sha-3923901` (pilot)
- Platform-ssot CI `deploy-backend.yml` hem `main-stable` hem `sha-<short>` tag push ediyor (satır 117, 135, 212)
- **D30 HARD RULE:** `main-stable` moving tag tek başına kanıt sayılmaz — digest pin zorunlu

### 3.2 İstenen İş

**Platform-ssot deploy-backend.yml workflow:**
- Her build sonunda image AMD64 digest'ini resolve et:
  ```bash
  DIGEST=$(docker manifest inspect ghcr.io/halildeu/platform-ssot-<svc>:sha-${SHORT_SHA} --platform linux/amd64 | jq -r '.config.digest')
  ```
- Digest'i K8s-gitops repo'ya PR ile push et:
  ```bash
  cd platform-k8s-gitops
  kustomize edit set image <svc>=ghcr.io/halildeu/platform-ssot-<svc>@${DIGEST}
  git commit + push branch + gh pr create
  ```
- Ya da: `kustomize edit set image` ile `newTag: sha-${SHORT_SHA}` yaz (immutable tag, digest'ten daha human-readable). Permission-service pattern'ı.

**Sıralama:**
1. Her servis için `sha-<short>` immutable tag (permission-service gibi)
2. Sonra full digest pin (`@sha256:...`) — opsiyonel ileriki iyileştirme

### 3.3 Kabul Kriteri

- [ ] Platform-ssot deploy-backend.yml her build sonunda K8s-gitops'a PR açıyor
- [ ] PR overlay test+prod `newTag: sha-<short>` güncelliyor (tüm 8 servis)
- [ ] `kustomize/overlays/test/kustomization.yaml` 0 `main-stable` tag kalıyor
- [ ] D30 HARD RULE PASS: her pod `imageID == GHCR digest`

### 3.4 K8s-gitops Tarafı

- Bu PR otomatik oluştuğunda ArgoCD (S2-C1 install sonrası) auto-sync yapar
- Rollback: `git revert` → ArgoCD sync

## 4. Codex İstişare

Her iki madde (W1 + W3) mimari değişiklik içeriyor (ESO wiring + CI workflow revize). Codex plan istişaresi **önerilir**:
- W1 ClusterSecretStore path + refresh interval kontrolü
- W3 digest pin stratejisi (`sha-<short>` vs `@sha256:...`) — tag okunabilirliği vs değişmezlik garantisi

## 5. Prompt (ops/CI session'a)

```
TASK: S2-B Artifact Hardening (W1 ghcr-pull ESO + W3 digest pin CI)
From: K8s-6 Seviye 2 scope

Detay: platform-k8s-gitops/docs/handoff-S2-B-artifact-hardening.md

Özet:
- W1: ghcr-pull Secret ESO ile Vault'tan auto-inject (stub değil ESO)
- W3: platform-ssot deploy-backend.yml her build sonrası K8s-gitops'a PR açıp
  overlay image tag'leri sha-<short> ile güncellemeli (permission-service pattern)

Kabul: kubectl get secret ghcr-pull (docker-registry) + Deploy-backend her run
K8s-gitops'a commit açıyor + overlay'de main-stable yok (sha-<short> tüm 8
servis).
```
