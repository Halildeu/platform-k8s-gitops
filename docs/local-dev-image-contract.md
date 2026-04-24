# Local Dev Image Handoff Contract (Faz 17.Y)

> Mac `k3d-dev` cluster'ında image loading stratejisi karar mühürü.
> Faz 17.2 profile matrix overlay'leri `imagePullPolicy: Never` patch uygular —
> image cluster'a **ön-yükleme** (pre-load) mekanizması gerekir.

---

## Seçenekler

### Option A (DEFAULT): `k3d image import`

**Akış**:
```
Tilt (platform-ssot) / docker build
      │
      ▼ docker image (local daemon)
      │
      ▼ k3d image import <image> --cluster dev
      │
      ▼ k3d cluster node local image cache
      │
      ▼ kubectl apply -k overlays/local-*
      │
      ▼ Pod `imagePullPolicy: Never` → local cache'den çalışır
```

**Avantajlar**:
- Moving parts az (Docker daemon → k3d import CLI → kubelet cache)
- Registry yönetimi yok
- Docker Desktop içinde self-contained
- Tilt `docker_build` + `k3d image import` default integrasyon

**Dezavantajlar**:
- Her image yeniden build'de import gerekir (cache invalidation)
- Rebuild iterasyonu yavaş (docker daemon save → tar → k3d load)

**Komut örneği**:
```bash
# Tilt ile otomatik (platform-ssot/Tiltfile içinde `custom_build` veya `docker_build`)
tilt up

# Manuel
docker build -t platform-ssot/auth-service:dev .
k3d image import platform-ssot/auth-service:dev --cluster dev
kubectl rollout restart deploy/auth-service -n platform-dev
```

---

### Option B (opt-in): Local Registry `registry.localhost:5002`

**Akış**:
```
Tilt / docker build
      │
      ▼ docker push registry.localhost:5002/platform-ssot/auth-service:dev
      │
      ▼ k3d-dev-registry (5002:5000 host-port)
      │
      ▼ Pod `imagePullPolicy: IfNotPresent` → registry'den pull
```

**Avantajlar**:
- Pull-based model (CI simülasyonu)
- Daha hızlı iteratif rebuild (registry layer cache)
- Multi-image aynı registry'de → diff-push sadece değişenleri

**Dezavantajlar**:
- Registry container ayağa kalkmalı (bootstrap/k3d-dev.yaml içinde var)
- `imagePullPolicy` overlay'de değiştirilmeli (`Never` → `IfNotPresent`)
- Registry auth (lokal için yok — güvenlik drift riski düşük)

**Komut örneği**:
```bash
# Registry'nin k3d içinden `platform-dev-registry:5000` olarak çözümlenmesi için
# bootstrap/k3d-dev.yaml `registries.create` bloğu (5002 host-port) kullanılır.

docker tag platform-ssot/auth-service:dev registry.localhost:5002/platform-ssot/auth-service:dev
docker push registry.localhost:5002/platform-ssot/auth-service:dev

# Overlay patch override (Option B'ye geçerken):
# kustomize/overlays/local-*/kustomization.yaml içinde
# imagePullPolicy: Never → IfNotPresent
```

---

## Karar (MVP)

**Option A (`k3d image import`) = DEFAULT**

Codex iter-4 AGREE cümlesi:
> "Image handoff default: `k3d image import` MVP için doğru default. Daha az
> moving part var. `registry.localhost:5000` opsiyonunu korumak doğru; hızlı
> rebuild ve daha "pull-benzeri" davranış istendiğinde açılır."

Gerekçe:
- Dev-loop first iteration: minimal setup
- Tilt `docker_build` → `k3d image import` otomatik
- Registry karmaşık için opt-in (15 dk karmaşıklık eklemeye değmez MVP'de)

**Option B opt-in**: Codex iter-4 cümle "hızlı rebuild istendiğinde açılır".
Geçiş yolu aşağıda.

---

## Option A → Option B Geçiş Rehberi

1. Registry container doğrula:
   ```bash
   docker ps | grep platform-dev-registry
   # k3d_registry.platform-dev-registry:5002 → 5000/tcp
   ```

2. `kustomize/overlays/local-*/kustomization.yaml` içinde patch:
   ```yaml
   patches:
     - target:
         kind: Deployment
         labelSelector: "app.kubernetes.io/part-of=platform"
       patch: |-
         - op: replace
           path: /spec/template/spec/containers/0/imagePullPolicy
           value: IfNotPresent   # Never değil
   ```

3. Image push:
   ```bash
   docker tag platform-ssot/auth-service:dev registry.localhost:5002/platform-ssot/auth-service:dev
   docker push registry.localhost:5002/platform-ssot/auth-service:dev
   ```

4. Deployment image ref (Tilt `k8s_yaml` veya kustomize `images:`):
   ```yaml
   images:
     - name: platform-ssot/auth-service
       newName: registry.localhost:5002/platform-ssot/auth-service
       newTag: dev
   ```

5. `kubectl rollout restart deploy` → kubelet registry'den pull.

---

## Performance Karşılaştırma (indikatif)

| Akış | Build-to-Pod süre | Moving parts |
|---|---|---|
| Option A (`k3d import`) | ~15-30s / image (docker save + load) | 2 (Docker + k3d) |
| Option B (registry push) | ~5-15s / image (docker push layer cache) | 3 (Docker + registry + kubelet) |

Rebuild %90+ kod-level (sadece app jar/binary layer) → Option B cache avantajı **1-3s**'ye kadar iner. Build-from-scratch: aynı hız.

---

## Tilt Integration (ssot Tiltfile, Faz 17.2)

Platform-ssot `Tiltfile` her iki option'ı destekler (geliştirici tercihi):

**Option A (default)**:
```python
docker_build('platform-ssot/auth-service', 'backend/auth-service', live_update=[...])
k8s_yaml(kustomize('../platform-k8s-gitops/kustomize/overlays/local-authn-min'))
# Tilt otomatik: docker build + k3d image import (k3d_image_import flag)
```

**Option B (opt-in)**:
```python
default_registry('registry.localhost:5002')
docker_build('platform-ssot/auth-service', 'backend/auth-service', live_update=[...])
k8s_yaml(kustomize('../platform-k8s-gitops/kustomize/overlays/local-authn-min-registry'))
# Tilt: docker build + docker push registry.localhost:5002/...
```

---

## İlişkili

- PLAN.md §17.Y
- `bootstrap/k3d-dev.yaml` registry config (`platform-dev-registry:5002`)
- `kustomize/overlays/local-*/kustomization.yaml` imagePullPolicy patch
- platform-ssot `Tiltfile` (code watch + image build, 17.2)

## Codex AGREE Referansları

Thread `019dbe80` iter-4 AGREE:
- Default `k3d image import` ✓
- Opsiyonel `registry.localhost:5000` opt-in ✓
- Moving parts argümanı (basit ön-yükleme) ✓
