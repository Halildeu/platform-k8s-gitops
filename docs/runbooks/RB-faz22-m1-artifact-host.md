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
# (e) PROD (board #1428 enable — AFTER merge + ArgoCD reconcile): ai.acik.com/artifacts
#     gerçek installer SERVİS ETMELİ (artık SPA fallback DEĞİL).
P="https://ai.acik.com/artifacts/endpoint-agent/<tag>"
curl -sI "$P/EndpointAgent.zip" | grep -i content-type        # application/zip (text/html DEĞİL)
curl -fsSL "$P/EndpointAgent.zip" -o /tmp/EA-prod.zip && shasum -a 256 /tmp/EA-prod.zip
curl -fsSL "$P/EndpointAgent.zip.sha256"                       # eşleşmeli
curl -s -o /dev/null -w '%{http_code}\n' "$P/does-not-exist"   # 404 (SPA fallback DEĞİL)
# NOT (prod-enable öncesi, PR merge edilmeden): hâlâ SPA fallback (text/html) döner.
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
- **Prod (board #1428) — public exposure kapatma**: prod sync `allow_prune=false`
  ile çalışır (RB-prod-gitops-sync.md), bu yüzden gitops main'i revert etmek
  Ingress `/artifacts` path'ini kaldırır (→ public erişim DERHAL kapanır, SPA
  fallback'e döner) **ama** artifact-host Deployment/Service/SA/PDB cluster'da
  **orphan** kalabilir. Kalıntı istenmiyorsa: ya **revert-forward PR** (resource
  + image pin + ingress patch'i geri çek) + `allow_prune=true` ile bir prune
  sync, ya da `kubectl --context k3d-prod -n platform-prod delete deploy/svc/sa/pdb
  -l app.kubernetes.io/name=artifact-host`. Public exposure'ı kapatmak için
  Ingress path revert TEK BAŞINA yeterlidir (pod kalsa da dışarıdan erişilemez).

## 8. Prod-enable (board #1428 — PR PREPARED; merge OWNER + D30 gated)

Prod-enable PR'ı hazırlandı (board #1428). Aşağıdaki desired-state değişiklikleri
`kustomize/overlays/prod` + `docs/operations/services.yaml`'da uygulandı; **merge
owner sign-off + D30 cutover gate'ine bağlı** (CI yeşil + Codex cross-AI AGREE +
`user-approval-required` label). Merge = yalnız desired-state; `ai.acik.com/artifacts`
ArgoCD prod **reconcile** ile LIVE olur (prod app selfHeal=false → manuel sync adımı).

Uygulanan değişiklikler:
1. `kustomize/overlays/prod/kustomization.yaml` → `../../base/apps/artifact-host`
   resource + image digest pin (testai ile **aynı** image+digest:
   `ghcr.io/halildeu/platform-agent-artifacts:v0.1.1-lab.2@sha256:7ac0fd57…` —
   yeniden build YOK).
2. Prod `platform` Ingress JSON6902 `/artifacts` path patch (test overlay ile aynı şekil).
3. `docs/operations/services.yaml` → artifact-host `prod: deferred → enabled`.
4. **D29 evidence ledger**: `release-candidates/platform-agent/<sha>.json` (testai
   D29 Up GREEN / Functional GREEN / Zanzibar AMBER — jwt_validates=false) +
   `schema/promotion-ledger-v1.schema.json` repo enum `platform-agent` eklendi
   (`gate-d29-evidence-required` prod gate'i bu olmadan kırmızı olur).
5. **Edge: değişiklik YOK** — canlı `platform-web-nginx` ai.acik.com 443 bloğunda
   `location / → proxy_pass https://127.0.0.1:30443` (Host $host, verbatim path)
   zaten `/artifacts`'i prod cluster ingress'e taşır (`nginx -T` ile doğrulandı;
   testai'deki açık `/artifacts/` bloğu yalnız eski `:5545` stage route'unu
   override etmek içindi — prod'da öyle bir route yok).

### ⚠️ KEYSTONE (Codex 019eacc3 P1) — installer default'u TEST cluster'a gider

`bootstrap-package.ps1`/`install.ps1` default `-ApiUrl` =
`https://testai.acik.com/api/v1/endpoint-agent`, default `-AutoEnrollApiUrl` =
`https://endpoint-agent-mtls.testai.acik.com/...`. Yalnız `-PackageUrl` ve
`-ExpectedZipSha256` mandatory. Yani **prod domain'den indirilen installer, açık
`-ApiUrl` verilmezse agent'ı TEST cluster'a enroll eder** (secret leak değil ama
ciddi yanlış-hedef riski). Prod install komutu **mutlaka** prod API hedefini
explicit geçmeli:

```powershell
$B = "https://ai.acik.com/artifacts/endpoint-agent/v0.1.1-lab.2"
iwr "$B/bootstrap-package.ps1" -OutFile $env:TEMP\bp.ps1
powershell -ExecutionPolicy Bypass -File $env:TEMP\bp.ps1 `
  -PackageUrl "$B/EndpointAgent.zip" -ExpectedZipSha256 <sha> `
  -ApiUrl "https://ai.acik.com/api/v1/endpoint-agent" `
  -AutoEnrollApiUrl "https://endpoint-agent-mtls.ai.acik.com/api/v1/endpoint-agent" `
  -Start -Force
```

Kalıcı (durable) çözüm = platform-agent'ta host-türevli (download URL'inden
ApiUrl çıkaran) veya prod-default bir bootstrap (ayrı follow-up; M1 pilot için
explicit-flag mitigasyonu kabul edilir, owner sign-off'ta flag'lendi).

### Owner sign-off + acceptance
- **Owner sign-off** (ZORUNLU, irreversible public exposure): private-repo
  lab-signed installer'ın `ai.acik.com` üzerinden public erişilebilir olması
  kararı (KVKK/güvenlik) — board #1428 + PR'da kayıtlı. Codex-consult ≠ owner-auth.
- **Merge sonrası** operator: deploy-prod-gitops sync (selfHeal=false manuel) →
  prod D29 (Up/Functional) + §6(e) prod acceptance (ZIP/content-type/SHA/404) +
  **prod-API-target smoke** (yukarıdaki prod komutla bir lab PC'nin `ai.acik.com`'a
  enroll olduğu, testai'ye DEĞİL) + browser smoke. Sonra ledger prod block doldurulur.

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
- Codex thread 019eac74 (test-host design + post-impl AGREE)
- Codex thread 019eacc3 (prod-enable cross-AI review — REVISE→absorb)
- Board: platform-k8s-gitops#1424 (test host, CLOSED), #1428 (prod-enable)
