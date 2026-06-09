# RB — Faz 22.5 M1 endpoint-agent artifact host

> Tetik: M1 "tek-komut" Windows agent kurulumunun
> `https://testai.acik.com/artifacts/endpoint-agent/<version>/{bootstrap-package.ps1,EndpointAgent.zip}`
> kaynağını **gerçekten** servis eden, GitOps-yönetimli, dayanıklı artifact host.

## 1. Neden / sorun

M1 istemcisi (`bootstrap-package.ps1`) `platform-agent` reposunda mevcuttu ama
**hosting hiç deploy edilmemişti**. testai edge `/artifacts/` isteğini geçici
olarak host stage nginx'e (`:5545`) proxy ediyordu; o da SPA `index.html`
fallback'i döndürüyordu. Sonuç: dokümante edilen tek-komut bootstrap, PowerShell
script yerine **HTML** indiriyor ve her satır hata veriyordu.

## 2. Mimari (durable, GitOps)

```
Windows PC
  └─ iwr https://testai.acik.com/artifacts/endpoint-agent/<tag>/bootstrap-package.ps1
        │
   host edge nginx (platform-web-nginx, :443)  ── host-compose/web-nginx/default.conf
     location /artifacts/  →  proxy_pass http://127.0.0.1:31080   (k3d-test ingress, HTTP)
        │
   k3d-test ingress-nginx  ──  Ingress `platform` (testai.acik.com)
     path /artifacts  →  Service artifact-host:80
        │
   artifact-host Deployment (nginx)  ──  kustomize/base/apps/artifact-host
     image ghcr.io/halildeu/platform-agent-artifacts@sha256:<digest>  (ghcr-pull, D30)
     serves /usr/share/nginx/html/artifacts/endpoint-agent/<tag>/...
```

- **Artifact transport**: artifact'ler bir **GHCR nginx image**'ına gömülür
  (`platform-agent` release workflow → publish job → `docker build` + push). Cluster
  bu image'ı **mevcut `ghcr-pull` secret**'ı ile **digest-pinned** çeker
  (yeni PAT / `contents:read` / runtime GitHub bağımlılığı YOK; D30 immutable).
- **Edge**: testai `/artifacts/` artık cluster ingress'e (`:31080`) gider —
  `/` ve `/api/` ile aynı hedef. URI'siz `proxy_pass` (path verbatim geçer).
- **Image içeriği** (`/artifacts/endpoint-agent/<tag>/`):
  `bootstrap-package.ps1`, `EndpointAgent.zip`, `EndpointAgent.zip.sha256`,
  `SHA256SUMS` (served-dir hash'leri), `release-manifest.json`.

## 3. Retention contract (ÖNEMLİ)

Artifact host **aynı anda yalnızca pinli (current) release sürümünü** servis eder.
Image yeni sürüme rollover edince eski `/artifacts/<old-tag>/` host URL'leri **404**
olabilir. Tüm sürümlerin **kalıcı arşivi GitHub release asset'leridir**
(`EndpointAgent.zip` + `bootstrap-package.ps1` + loose dosyalar). Install komutu
her zaman current pinli sürümü kullanır. Bu, pilot UX için kabul edilen bir
davranıştır — "eski host URL 404" bir regression değildir.

## 4. Yeni sürüm yayınlama (publish chain)

1. `platform-agent` reposunda yeni tag push: `git tag -a vX.Y.Z-lab.N -m "..." && git push origin vX.Y.Z-lab.N`
2. `release.yml` çalışır: windows build+sign → publish job EndpointAgent.zip + .sha256
   üretir, release'e ekler, `ghcr.io/halildeu/platform-agent-artifacts:vX.Y.Z-lab.N`
   (+`sha-<short>`) image'ı build+push eder. **Run summary** image digest'ini basar:
   `digest: sha256:...`.
3. Bu repoda (`platform-k8s-gitops`) `kustomize/overlays/test` artifact-host `images:`
   entry'sinde `newTag` + `digest:` güncellenir (D30 immutable pin).
4. README (`platform-agent/installers/windows/README.md`) `<version>` path'i bump edilir.

## 5. Deploy (test cluster)

```bash
# 1. Selective apply (blast radius düşük): artifact-host workload + ingress
kubectl --context k3d-test -n platform-test apply \
  -f <(kubectl kustomize kustomize/overlays/test | \
       yq 'select(.metadata.name=="artifact-host" or (.kind=="Ingress" and .metadata.name=="platform"))')
# (veya full overlay apply — Scale-to-Zero YASAK sonrası güvenli)

kubectl --context k3d-test -n platform-test rollout status deploy/artifact-host --timeout=120s
kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=artifact-host -o wide
# imageID, pin'lenen digest ile eşleşmeli (D30 + ghcr-pull pull kanıtı)
```

### Edge route (host, bir defalık + GitOps'a yansıdı)

`host-compose/web-nginx/default.conf` testai server bloğunda `/artifacts/` →
`http://127.0.0.1:31080`. Canlı host'a uygula:

```bash
# backup + edit (5545 stage route → 31080 cluster) + test + reload
ssh halil@staging-sw 'sudo cp /home/halil/platform/web/nginx/default.conf{,.bak-$(date +%s)}'
# default.conf'u bu repodaki host-compose/web-nginx/default.conf ile hizala (veya
# yalnız /artifacts/ bloğunu 31080'e çevir), sonra:
ssh halil@staging-sw 'docker exec platform-web-nginx nginx -t && docker exec platform-web-nginx nginx -s reload'
```

## 6. Verify (acceptance — hepsi PASS olmalı)

```bash
B="https://testai.acik.com/artifacts/endpoint-agent/<tag>"
# (a) bootstrap-package.ps1 → PowerShell (HTML DEĞİL); ilk satır 'param(' veya '#'
curl -fsSL "$B/bootstrap-package.ps1" | head -1
curl -sI "$B/bootstrap-package.ps1" | grep -i content-type      # text/* veya octet-stream, text/html DEĞİL
# (b) EndpointAgent.zip → application/zip + content-length + sha256 eşleşmesi
curl -sI "$B/EndpointAgent.zip" | grep -iE 'content-type|content-length'   # application/zip
curl -fsSL "$B/EndpointAgent.zip" -o /tmp/EA.zip && shasum -a 256 /tmp/EA.zip
curl -fsSL "$B/EndpointAgent.zip.sha256"        # eşleşmeli (= -ExpectedZipSha256)
# (c) olmayan artifact → 404 (HTML fallback DEĞİL)
curl -s -o /dev/null -w '%{http_code}\n' "$B/does-not-exist"   # 404
# (d) SPA + API edge değişiminden etkilenmedi
curl -s -o /dev/null -w '%{http_code}\n' https://testai.acik.com/        # 200 (SPA)
curl -s -o /dev/null -w '%{http_code}\n' https://testai.acik.com/api/v1/endpoint-agent/health
# (e) PROD defer: ai.acik.com/artifacts gerçek artifact DÖNMEMELİ (SPA fallback)
curl -sI "https://ai.acik.com/artifacts/endpoint-agent/<tag>/EndpointAgent.zip" | grep -i content-type  # text/html
```

Windows tek-komut smoke (Parallels `prlctl exec "Windows 11"` = SYSTEM, veya lab PC):
`iwr .../bootstrap-package.ps1 -OutFile ...; powershell -File ... -PackageUrl .../EndpointAgent.zip -ExpectedZipSha256 <sha> -Start -Force`
→ servis kurulur + enroll olur + **clean version** (vX.Y.Z-lab.N, `0.1.0-dev` DEĞİL) raporlar,
böylece UPDATE_AGENT self-update capability'sini de advertise eder.

## 7. Rollback

- **Edge**: `/artifacts/` proxy_pass'i tek satır geri al (31080 → eski) veya
  `default.conf.bak-*`'tan restore + `nginx -t` + reload. (Cluster artifact-host
  pod'u kalır, zararsız.)
- **Cluster**: artifact-host yalnız additive (yeni Deployment/Service + ingress
  path). Kaldırmak için overlay'den resource + ingress patch çıkar + apply.
- **Image**: bozuk image → önceki digest'e re-pin + apply.

## 8. Prod-enable (DEFERRED — operator/owner gate)

Şu an prod overlay'de artifact-host **YOK** (true defer): `ai.acik.com/artifacts/...`
prod `/` catch-all üzerinden SPA fallback'e düşer (gerçek installer servis edilmez).
Prod'da açmak için ayrı gated PR:
1. `kustomize/overlays/prod` → `../../base/apps/artifact-host` resource + image digest pin.
2. Prod ingress'e `/artifacts` path patch (test overlay ile aynı JSON6902).
3. **Owner sign-off**: private-repo lab-signed installer'ın `ai.acik.com` üzerinden
   public erişilebilir olması kararı (KVKK/güvenlik) + D30 prod cutover gate.
4. Prod D29 + browser smoke.

## 9. Güvenlik / boundary

- `EndpointAgent.zip` içinde **secret/token YOK** (enrollment token runtime'da
  `Read-Host -AsSecureString` ile alınır). Binary lab-only-evidence self-signed.
- **Public exposure**: testai.acik.com/artifacts → private-repo lab-signed
  installer'ı erişime açar. Bu M1 tasarımının dokümante edilmiş davranışıdır
  (installer README) — owner sign-off raporda flag'lenir.

## 10. Referanslar

- platform-agent: `.github/workflows/release.yml` (publish job), `deploy/artifact-host/`,
  `scripts/build/windows-package.sh` (PREBUILT_EXE), `installers/windows/README.md`
- gitops: `kustomize/base/apps/artifact-host/`, `kustomize/overlays/test/kustomization.yaml`
  (artifact-host image pin + `/artifacts` ingress patch), `host-compose/web-nginx/default.conf`
- Codex thread 019eac74 (design + post-impl AGREE)
- Board: platform-k8s-gitops#1424
