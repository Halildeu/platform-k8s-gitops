# Faz 24 evidence: testai frontend rollout headroom

Tarih: 2026-07-11

Roadmap issue: [#2299](https://github.com/Halildeu/platform-k8s-gitops/issues/2299)

Önceki ürün promotion issue: [#2295](https://github.com/Halildeu/platform-k8s-gitops/issues/2295)

## Olay kanıtı

İlk immutable frontend verifier run'ı:
[29154847646](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29154847646).

Canlı event ve quota incelemesinde:

- `platform-quota.limits.cpu` hard `12`, used `12325m` idi.
- Yeni frontend podu (`limits.cpu=200m`) `exceeded quota` ile admission alamadı.
- Test frontend rollout stratejisi `maxSurge=0/maxUnavailable=1` idi.
- Eski tek pod yenisi Ready olmadan silindi; public `testai.acik.com` geçici
  HTTP 503 üretti.
- Argo sync revision'a ulaştı, fakat app health timeout oldu. Eski helper bunu
  yanlış biçimde “ArgoCD core unavailable / fallback disabled” diye raporladı.

Daha sonra ayrı desired-state değişikliğiyle quota 13 CPU oldu. Mevcut immutable
ürün artefaktı için verifier run
[29155631759](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29155631759)
Argo reconcile, exact pod digest, public module entry ve tam build SHA kapılarını
geçti. Bu kanıt mevcut artefaktın runtime'ını doğrular; rollout kesintisi sınıfını
tek başına önlediğini kanıtlamaz.

## #2299 kaynak değişikliği

- Test frontend: `maxSurge=1`, `maxUnavailable=0`,
  `progressDeadlineSeconds=300`.
- Argo öncesi canlı quota preflight: pod, requests/limits CPU ve bellek.
- Desired/live hard minimumu ile conservative hesap.
- Tüm app container'ları, init/restartable sidecar peak ve pod overhead hesabı.
- Eksik explicit resource veya quota metriğinde fail-closed.
- Başarılı Argo sync sonrası health timeout'ta kubectl fallback yok.
- Argo sync komutu başarısızlığında sonuç yutulmuyor ve fallback yok.
- Image pin yanında rollout strategy/deadline fingerprint değişimi de otomatik
  reconcile/runtime verifier'ı tetikliyor.

## Pre-merge doğrulama

- 28 automation test: PASS (ilk geniş tur; yeni fingerprint/sync testleriyle
  sonraki tur sayısı ayrıca PR kanıtında yazılır).
- `platform-test-gitops-sync-static.sh`: PASS.
- `shellcheck`: PASS.
- `actionlint`: PASS.
- `yamllint`: PASS.
- Rendered frontend strategy: `maxSurge=1/maxUnavailable=0`.
- Rendered progress deadline: `300`.
- Son erişilebilen canlı quota snapshot'ına karşı hesap:
  `limits.cpu margin=1175m`, `required=200m`; `pods margin=5`, `required=1`;
  verdict PASS.

## Açık acceptance kapıları

Bu belge kapanış iddiası değildir. Aşağıdaki kanıtlar merge sonrası ayrıca
toplanır:

1. PR CI ve gerçek Claude final adversarial review'de unresolved P0/P1 olmaması.
2. Self-hosted runner canlı preflight artefaktı.
3. Argo Synced/Healthy ve exact immutable digest/tam SHA/public module PASS.
4. Frontend rollout sırasında aralıksız public availability probe.
5. Project #2 ve `#2299` üzerinde acceptance kanıt comment'i; deliberate status
   kararı.
