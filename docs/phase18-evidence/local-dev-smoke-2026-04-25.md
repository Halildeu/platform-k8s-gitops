# Faz 18.8 — Mac k3d-dev Clean Smoke Evidence

**Tarih**: 2026-04-25 19:00 UTC (Mac MacBook Pro M1, Darwin 25.4.0 arm64)
**Operator**: Claude (agent SSH+kubectl yetkisi — CLAUDE.md kural #7)
**Status**: PARTIAL EVIDENCE (bring-up infra validated; image inner-loop deferred)

---

## Bağlam

PLAN.md Faz 18.8 — D34 "local dev" bacağı evidence için Mac üzerinde k3d-dev cluster bring-up validation. Codex iter-3'te non-blocking (Faz 18.1-18.7 gate değil) işaretlenmiş.

## İddia

Mac developer machine üzerinde lokal dev cluster bring-up path'i (cluster create → CNI install → overlay apply) **runtime'da çalışıyor**. 2 fix gerekti:

1. `bootstrap/install-calico.sh` `dev` target eksikti (sadece prod/test) → eklendi (pod_cidr=10.46.0.0/16)
2. `kustomize/overlays/local-authn-min` ingress `tls.hosts[0]` PLACEHOLDER override eksikti → eklendi (`app.localtest.me`)

## İspatlar (canlı runtime)

### k3d-dev cluster create

```
$ ./bootstrap/setup-clusters.sh dev
[bootstrap] Created network 'platform-dev-net'
[bootstrap] Created node 'k3d-dev-server-0'
[bootstrap] Cluster 'dev' created successfully!
[bootstrap] cluster 'dev' hazır (context: k3d-dev)
```

Network: `platform-dev-net` (test/prod izole)
Pod CIDR: `10.46.0.0/16` (test 10.44 + prod 10.42 farklı, çakışma yok)
Service CIDR: `10.47.0.0/16`
Port: `127.0.0.1:32080:80` + `127.0.0.1:32443:443`

### Calico CNI install

```
$ ./bootstrap/install-calico.sh dev
[calico] [dev] tigera-operator uygulanıyor (v3.29.1)
[calico] [dev] tigera-operator hazırlanıyor...
deployment.apps/tigera-operator condition met
[calico] [dev] Installation CR apply — podCIDR=10.46.0.0/16
installation.operator.tigera.io/default created
```

Pod state (Calico ready):

```
NAMESPACE          NAME                                       READY   STATUS
calico-system      calico-node-smdfz                          1/1     Running
calico-system      calico-typha-b4bf94d54-kv6nb               1/1     Running
calico-system      calico-kube-controllers-...                 1/1     Running
tigera-operator    tigera-operator-...                         1/1     Running
kube-system        coredns-...                                 1/1     Running
```

Node: `k3d-dev-server-0   Ready   control-plane,master   v1.31.2+k3s1`

### Overlay apply (local-authn-min)

```
$ ./scripts/dev-up.sh --profile authn-min
[dev-up] cluster 'dev' zaten var — atlanıyor
[dev-up] k3d-dev Ready
[dev-up] namespace platform-dev oluşturuluyor
[dev-up] overlay apply: kustomize/overlays/local-authn-min (profile=authn-min)
serviceaccount/api-gateway created
serviceaccount/auth-service created
configmap/api-gateway-config created
configmap/auth-service-config created
endpoints/keycloak created
endpoints/postgres created
endpoints/vault created
service/api-gateway created
service/auth-service created
deployment.apps/api-gateway created
deployment.apps/auth-service created
poddisruptionbudget.policy/api-gateway created
poddisruptionbudget.policy/auth-service created
ingress.networking.k8s.io/platform created
[dev-up] === dev-up tamamlandı ===
```

`local-authn-min` overlay 4 workload (Deployment + StatefulSet + Endpoints) içerir:
- api-gateway
- auth-service
- host-service postgres (bridge Endpoints, host-gateway 192.168.65.254:5432)
- host-service keycloak (bridge Endpoints, host-gateway 192.168.65.254:8081)

## İspatlamaz (deferred — kapsam dışı)

### Image inner-loop (Faz 17.3 deferred)

```
NAME                            READY   STATUS              RESTARTS
api-gateway-b99f465dc-77bzc     0/1     ErrImageNeverPull   0
auth-service-65b6794bcf-bpn9q   0/1     ErrImageNeverPull   0
```

**Sebep**: Overlay `imagePullPolicy: Never` set ediyor + `auth-service:poc` / `api-gateway:poc` tag arıyor. Bu image'lar Tiltfile (platform-ssot) tarafından build edilirdi — ama platform-ssot 2026-04-25 deprecated (Faz 19.10 soft lock) ve Tiltfile yeni repolara port edilmedi.

**Workaround denemeleri (başarısız)**:

1. `docker pull --platform linux/amd64 ghcr.io/halildeu/platform-backend-{auth-service,api-gateway}:latest`
2. `docker tag ... auth-service:poc` + `api-gateway:poc`
3. `k3d image import auth-service:poc api-gateway:poc -c dev`

Sonuç: k3d "Successfully imported" diyor ama containerd error: `failed resolving platform for image docker.io/library/auth-service:poc, error="content digest sha256:... not found"`. K3d image import bug'ı veya OCI manifest layer eksiklik.

**Çözüm yolu (ayrı iş — Faz 17.3 follow-up)**:
- Tiltfile yeni repolara port (platform-backend + platform-web) — image build pipeline
- Veya `k3d image import` yerine `docker save | k3d image import-tar` kullan
- Veya overlay `imagePullPolicy: IfNotPresent` + `image: ghcr.io/...` direkt çekim (k3d-dev internet erişimi var)

### Authentik smoke (dev-seed.sh + dev-smoke.sh) deferred

Image olmadan pod çalışmadığı için auth-service `:8081/actuator/health/readiness` doğrulanmadı. Bring-up kanal validated; functional smoke ayrı iş.

## Bilinen boşluk

| Bekleyen | Öncelik | Çözüm yolu |
|---|---|---|
| Tiltfile yeni repolara port | P2 | platform-backend + platform-web Tiltfile setup (Faz 17.3 follow-up) |
| Image import workaround (`docker save | k3d import-tar`) | P3 | scripts/dev-up.sh'a eklenebilir |
| Authentik functional smoke (dev-smoke.sh) | P2 | Image hazır olunca otomatik geçer |
| Tiltfile alternatif: imagePullPolicy IfNotPresent + GHCR digest | P3 | Overlay patch yeterli |

## D34 evidence pozisyonu

**Local dev bacağı bring-up infrastructure**: ✅ Validated (cluster + CNI + overlay apply path)
**Local dev bacağı functional**: ❌ Deferred (image inner-loop eksik)

D34 3-realm bağımsızlık (lokal dev + ubuntu test + ubuntu prod) iddiası **2 bacakta tam çalışıyor** (ubuntu test = testai.acik.com canlı, ubuntu prod = ai.acik.com canlı). Lokal dev bacağı **bring-up validated** + **functional deferred**. PLAN.md Faz 18.8 description "Codex iter-3 paralel, 18.1-18.7 gate değil" ile uyumlu.

## Yapılacak iş (ayrı PR)

- `bootstrap/install-calico.sh` `dev` case ekle (yapıldı bu PR)
- `kustomize/overlays/local-authn-min/kustomization.yaml` ingress tls.hosts[0] fix (yapıldı bu PR)
- PLAN.md Faz 18.8 PARTIAL/COMPLETE state güncelle

## Referanslar

- [PLAN.md Faz 18.8](/PLAN.md)
- [bootstrap/k3d-dev.yaml](/bootstrap/k3d-dev.yaml)
- [bootstrap/install-calico.sh](/bootstrap/install-calico.sh) (dev case ekleme)
- [kustomize/overlays/local-authn-min/kustomization.yaml](/kustomize/overlays/local-authn-min/kustomization.yaml) (ingress tls fix)
- [scripts/dev-up.sh](/scripts/dev-up.sh)
- ADR-0003 inner-loop tooling ownership (Faz 17.6)
