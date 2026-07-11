# Runbook: testai frontend GitOps promotion

## Amaç

`platform-web` immutable frontend artefaktını `testai.acik.com` ortamına,
tek hazır podu kesintiye uğratmadan ve canlı `ResourceQuota` headroom'unu
ArgoCD mutasyonundan önce doğrulayarak taşır.

Bu runbook yalnız test overlay içindir. Production promotion, D30 ve owner
acceptance kapıları ayrıca işletilir.

## Otorite ve değişmezler

- Desired state: `kustomize/overlays/test/kustomization.yaml`
- Promotion: `.github/workflows/deploy-testai.yml`
- Reconcile/verify: `.github/workflows/verify-testai-frontend-rollout.yml`
- Runtime verifier: `scripts/deploy/verify-testai-frontend-runtime.sh`
- Project/claim: Project #2 ve ilgili gerçek issue

Değişmezler:

1. Frontend image `sha-<7>` tag + `sha256:<64>` digest + tam 40 karakter
   `sourceRevision` ile pinlenir.
2. Test frontend `maxSurge=1`, `maxUnavailable=0` ve pozitif
   `progressDeadlineSeconds` kullanır. Eski hazır pod, yenisi Ready olmadan
   silinmez.
3. Workload üzerinde `kubectl set image`, `patch`, `edit` veya doğrudan apply
   yapılmaz. Mutasyon yalnız review edilen desired state ve ArgoCD üzerinden
   gerçekleşir.
4. Başarılı Argo sync sonrası health timeout, kubectl fallback sebebi değildir.
   Rollout fail olur; mevcut hazır pod hizmet vermeye devam eder.

## Otomatik akış

1. `platform-web` build immutable digest üretir.
2. App-authenticated promotion workflow test overlay pinini dar diff ile günceller
   ve review edilebilir GitOps PR'ı açar.
3. Merge sonrası verifier image pin veya rollout-contract fingerprint değişimini
   algılar.
4. `preflight-testai-frontend-rollout.sh`, rendered frontend Deployment,
   rendered desired quota ve canlı quota durumunu salt-okuma olarak toplar.
5. Preflight PASS ise ArgoCD Application reconcile edilir.
6. Runtime verifier canlı pod imageID digestini, public Module Federation
   entrypoint'i ve `/build-info.json` tam source SHA'sını doğrular.

## Kota hesabı

Preflight aşağıdaki metrikleri fail-closed değerlendirir:

- `requests.cpu`
- `requests.memory`
- `limits.cpu`
- `limits.memory`
- `pods`

Her metrik için:

```text
effectiveHard = min(live.status.hard, renderedDesired.spec.hard)
margin        = effectiveHard - live.status.used
required      = effectivePodResource * resolvedMaxSurge
PASS          = liveUsed <= effectiveHard AND margin >= required
```

`maxSurge` yüzdesi Kubernetes ile aynı şekilde yukarı yuvarlanır. Uygulama
container toplamı, restartable init sidecar steady-state toplamı, init peak ve
pod overhead hesaba katılır. Her container için CPU/bellek request ve limit
değerleri açıkça yazılmalıdır; LimitRange defaulting'e güvenilirse preflight
fail eder. Eksik quota metriği PASS sayılmaz. Tam sınır (`margin == required`)
kabul edilir.

Preflight ile admission atomik değildir. Bu TOCTOU penceresi availability
riski üretmez: `maxUnavailable=0` eski podu korur. Başka bir eşzamanlı rollout
headroom'u tüketirse yeni pod admission alamaz, progress deadline/Argo health
timeout devreye girer ve workflow fail olur.

## Kanıt ve tanı

Workflow artefaktında iki JSON bulunur:

- `testai-frontend-quota-preflight.json`
- `platform-test-frontend-sync-report.json`

Preflight raporunda her metrik için desired hard, live hard, effective hard,
live used, required ve margin vardır. Secret, token veya ham kullanıcı verisi
yoktur.

Argo raporunda requested/observed revision ile sync/health durumu bulunur.
`ArgoCD sync completed but application did not reach Synced/Healthy` mesajı,
sync komutunun çalıştığını ancak uygulamanın süre içinde sağlıklı olmadığını
ifade eder. `ArgoCD sync command failed` ayrı hata sınıfıdır ve iki durumda da
kubectl fallback çalıştırılmaz.

## Rollback ve kurtarma

- İstenmeyen artefakt veya manifest için canonical rollback, son iyi GitOps pini
  geri alan review edilmiş PR'dır.
- Çalışan eski pod korunuyorsa doğrudan workload mutasyonu yapılmaz; önce Argo
  raporu, Deployment event'leri ve quota raporu incelenir.
- Public availability ayrı prob ile rollout boyunca izlenir. HTTP 200 tek başına
  exact artifact kanıtı değildir; digest ve tam source SHA birlikte gerekir.
- Break-glass ancak repo `AGENTS.md` dört koşulunu karşılayan ayrı incident/issue,
  TTL, drift alarmı ve aynı-incident reconciliation PR ile mümkündür.

## Lokal doğrulama

```bash
python3 -m unittest discover -s tests/automation -p 'test_*.py'
bash scripts/test/platform-test-gitops-sync-static.sh
shellcheck scripts/deploy/preflight-testai-frontend-rollout.sh \
  scripts/faz22/sync-platform-test-gitops.sh
actionlint .github/workflows/verify-testai-frontend-rollout.yml
kubectl kustomize kustomize/overlays/test >/dev/null
```

Canlı preflight yalnız `k3d-test` context'ine sahip self-hosted `staging-sw`
runner'da çalıştırılır. Lokal Mac'te context yoksa bu bir ürün/runtime sonucu
değil, doğru authority boundary'dir.
