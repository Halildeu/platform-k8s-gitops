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

- 29 automation test: PASS.
- `platform-test-gitops-sync-static.sh`: PASS.
- `shellcheck`: PASS.
- `actionlint`: PASS.
- `yamllint`: PASS.
- `black` ve `ruff`: PASS.
- Rendered frontend strategy: `maxSurge=1/maxUnavailable=0`.
- Rendered progress deadline: `300`.
- Son erişilebilen canlı quota snapshot'ına karşı hesap:
  `limits.cpu margin=1175m`, `required=200m`; `pods margin=5`, `required=1`;
  verdict PASS.
- Gerçek Claude final adversarial review: `NO_P0_P1`.

## Post-merge runtime acceptance kanıtı

Kaynak PR
[#2301](https://github.com/Halildeu/platform-k8s-gitops/pull/2301),
`ea138e990da71193fc503f9be2bedfc81c409b97` merge SHA'sı ile `main`'e
alındı. Post-merge self-hosted verifier run'ı
[#29157600538](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29157600538)
`success` verdi. Ham makine kanıtı
[`testai-frontend-gitops-rollout-ea138e...`](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29157600538/artifacts/8249898645)
artefaktındadır.

Canlı preflight sonucu:

- resolved rollout: replicas `1`, `maxSurge=1`, `maxUnavailable=0`,
  `progressDeadlineSeconds=300`;
- `requests.cpu`: margin `3525m`, surge requirement `10m`;
- `requests.memory`: margin `6752Mi`, surge requirement `32Mi`;
- `limits.cpu`: margin `1175m`, surge requirement `200m`;
- `limits.memory`: margin `12352Mi`, surge requirement `128Mi`;
- `pods`: margin `5`, surge requirement `1`;
- aggregate verdict: `PASS`.

Reconcile/runtime sonucu:

- Argo observed revision merge SHA ile eşleşti;
- sync `Synced`, health `Healthy`;
- rollout başarıyla gözlendi; yeni pod `frontend-76d85bdd74-bkgjp`;
- exact runtime digest
  `sha256:4ff08fd67234e11f655487d8524351abdc739713dcc6e15fd7472dcefd6a201b`;
- public module entry `/mf-entry-bootstrap-0.js`: PASS;
- build lineage full SHA
  `29ebe18c8197fee7621cc3130c11d893ab9ecd3b`, immutable image lineage
  `sha-29ebe18` ile eşleşti.

Bağımsız public probe, gerçek Argo sync/rollout penceresini kapsayan
`2026-07-11T15:16:31Z..15:17:18Z` aralığında `45/45` HTTP 200 gördü;
non-200 `0`, maksimum toplam istek süresi `0.422s` oldu.

## Acceptance sınırı

Bu kanıt `testai` frontend GitOps promotion durability ve zero-downtime rollout
sınıfı içindir. Faz 24'ün canlı transcript, doğruluk, diarization, toplantı
çıktısı ve diğer ürün acceptance kapılarını doğrulamaz. Project #2 / `#2299`
deliberate status kararı ayrı governance adımıdır; PR merge tek başına issue'yu
`Done` yapmaz.
