# RB-prod-gitops-sync — Prod GitOps Sync (ArgoCD platform-prod)

ID: RB-prod-gitops-sync
Service: platform-prod / argocd
Status: Active
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `platform-prod` ArgoCD Application'ını kontrollü, audit-trail'li biçimde
  istenen git revision'a sync etmek.
- Prod cluster'a giden **tek kanonik deploy mekanizmasını** tarif etmek:
  `.github/workflows/deploy-prod-gitops.yml` (workflow_dispatch +
  `environment: production` env-gate).
- image-only `deploy-backend-prod.yml` / `deploy-frontend-prod.yml`
  workflow'larının kapsamadığı ConfigMap / manifest / yeni-resource
  değişikliklerini prod'a güvenle taşımak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Kapsam içi: `kustomize/overlays/prod` altındaki herhangi bir desired-state
  değişikliğinin (image digest, ConfigMap, replica policy, yeni manifest)
  prod cluster'a ArgoCD üzerinden uygulanması.
- Kapsam dışı:
  - test cluster (`platform-test`) — ArgoCD `platform-test` ayrı, auto-sync'li.
  - ArgoCD `platform-prod` Application objesinin kendisinin değişimi
    (`argocd/applications/platform-prod.yaml`) — normal PR + merge.
  - D30 atomic cutover edge switch — `RB-production-cutover-checklist.md`.
- Ön-şart: sync edilecek revision **origin/main'e merge edilmiş** olmalı; prod
  overlay digest değişiklikleri D29 evidence gate'inden (release-candidates
  ledger) geçmiş olmalı.

-------------------------------------------------------------------------------
3. ÖN-KOŞUL
-------------------------------------------------------------------------------

- [ ] Sync hedefi commit `origin/main` HEAD'de veya bir ancestor'ında (workflow
      preflight `git merge-base --is-ancestor` ile zorlar).
- [ ] Workflow `main` branch'inden dispatch ediliyor (preflight `GITHUB_REF`
      gate ile zorlar — başka branch'ten dispatch reddedilir).
- [ ] GitHub Environment `production` mevcut, required reviewer set'li.
- [ ] Self-hosted runner `[self-hosted, staging-sw, prod-deploy]` online;
      kubeconfig'inde `k3d-prod` context var.
- [ ] Runner kubeconfig'i `applications.argoproj.io` CR üzerinde get + patch +
      update yetkisine sahip (`argocd --core` operation/refresh-annotation
      yazımı için). Mevcut prod-deploy runner geniş kubectl yetkisine sahip;
      PR-3 least-privilege RBAC bunu `platform-prod` app'e daraltacak.
- [ ] k3d-prod cluster'da ArgoCD ayakta (`argocd` namespace,
      `argocd-repo-server` + `argocd-application-controller`).
- [ ] §4 Adım 0 dispatch-öncesi diff ön-kontrolü yapıldı (ZORUNLU evidence).

-------------------------------------------------------------------------------
4. TETİK & SYNC AKIŞI
-------------------------------------------------------------------------------

Adım 0 — Dispatch öncesi diff (ZORUNLU evidence, ~3 dk):
  - `production` environment onayı sync job'ı başlamadan istenir; in-job diff
    onaydan sonra üretilir. Onaylayan kişinin kapsamı ONAYDAN ÖNCE görmesi
    için diff dispatch öncesi alınır ve dispatch/PR evidence'ına eklenir.
  - Not: bu diff bir OPERATÖR aksiyonudur — workflow primitifi DEĞİL. Workflow
    `kubectl exec` çalıştırmaz (yasak primitive). Operatör staging-sw'de
    `argocd --core` ile diff alır:

        ssh halil@staging-sw
        # ArgoCD sürümünü öğren + eşleşen CLI'yi indir (workflow ile aynı yol)
        VER=$(kubectl -n argocd get deploy -l app.kubernetes.io/name=argocd-repo-server \
          -o jsonpath='{.items[0].spec.template.spec.containers[0].image}'); VER=${VER##*:}
        curl -fsSL -o /tmp/argocd \
          "https://github.com/argoproj/argo-cd/releases/download/${VER}/argocd-linux-amd64"
        chmod +x /tmp/argocd
        /tmp/argocd --core app diff platform-prod --revision <hedef-sha>

  - Beklenen: yalnız niyet edilen resource'lar OutOfSync. Başka gerçek
    değişiklik görünüyorsa → DUR, kök nedeni incele, dispatch etme.

Adım 1 — Workflow dispatch (~10 sn + onay bekleme):

      gh workflow run deploy-prod-gitops.yml -R Halildeu/platform-k8s-gitops \
        --ref main \
        -f revision=<origin-main-head-sha> \
        -f sync_mode=resources \
        -f resources=':ConfigMap:<cm-adı>,apps:Deployment:<deploy-adı>' \
        -f allow_prune=false \
        -f confirm=SYNC-PROD

  - `--ref main` zorunlu — workflow yalnız main'den dispatch edilebilir.
  - `revision` boş bırakılırsa preflight `origin/main` HEAD'i kullanır.
  - `sync_mode=full` → tüm overlay sync edilir (`resources` yok sayılır).
  - `allow_prune=false` (prod default) — repodan silinmiş manifest karşılığı
    canlı resource SİLİNMEZ.
  - Beklenen: preflight job yeşil; sync job `production` env onayı bekler.
  - Fail sinyali: preflight kırmızı → input hatası (confirm / revision /
    resources format / non-main ref); job log'undaki `::error::` satırını oku.

Adım 2 — `production` environment onayı:
  - GitHub Actions UI → run → "Review deployments" → `production` onayla.
  - Devam eşiği: onay verilince sync job self-hosted runner'da başlar.

Adım 3 — Sync job adımları (otomatik, ~3-15 dk):
  - Isolated kubeconfig (k3d-prod context, runner shared-state'e dokunmaz).
  - ArgoCD CLI cluster sürümüne göre + checksum doğrulamalı indirilir.
  - `app get --hard-refresh` (connectivity smoke + cache refresh).
  - `app diff --revision` (pre-sync gate — rc 0/1 OK, rc 2+ fail).
  - `argocd --core app sync` → Application CR'a operation yazar; cluster-içi
    controller işi yapar.
  - `app wait` + (resources modunda) `kubectl rollout status`.
  - Post-sync state step summary'ye yazılır.

-------------------------------------------------------------------------------
5. DOĞRULAMA
-------------------------------------------------------------------------------

Sync job yeşil olduktan sonra (workflow İZİNLİ primitive'lerle):

- [ ] Step summary "Post-sync state": beklenen `app sync` / `health` durumu.
- [ ] `kubectl --context k3d-prod -n platform-prod get deploy -o wide` —
      hedef Deployment yeni imageID/generation'da.
- [ ] `kubectl --context k3d-prod -n platform-prod rollout status deploy/<ad>`
      tamamlanmış; eski ReplicaSet pod kalmamış.

Workflow DIŞI derin kabul testi (agent / ayrı verify adımı — workflow
`kubectl exec` çalıştırmaz):

- [ ] Pod runtime env beklenen değerde.
- [ ] `/actuator/health/readiness` 200/UP; log temiz.
- [ ] Servis fonksiyonel smoke (endpoint response shape).
- [ ] Public edge no-token isteği 401 (auth zinciri sağlam).

-------------------------------------------------------------------------------
6. ARIZA & ROLLBACK
-------------------------------------------------------------------------------

- Preflight kırmızı:
  - Workflow `main`'den mi dispatch edildi (`--ref main`)? `confirm` tam olarak
    `SYNC-PROD` mü? `revision` 40-char hex + `origin/main` ancestor mı?
    `resources` token'ları `GROUP:KIND:NAME` (namespace'siz) formatında mı?
- ArgoCD CLI indirme adımı kırmızı:
  - `argocd-repo-server` deployment `argocd` namespace'inde mi, image tag'i
    `vX.Y.Z` formatında mı? Checksum mismatch → release artifact tutarsızlığı.
- `app diff` adımı kırmızı (rc 2+):
  - `argocd --core` cluster'a erişemiyor / `revision` repo-server'da
    bulunamıyor olabilir. `app get` connectivity adımı geçtiyse revision'ı
    doğrula.
- `app sync` kırmızı / `app wait` timeout:
  - `argocd --core app get platform-prod` ile operation phase + message oku.
  - Pod crashloop ise `kubectl logs` ile kök neden; gerekirse rollback.
- `sync_mode=full` + `allow_prune=false` + repodan silinmiş resource:
  - Full sync app'i `Synced`'e götüremez (silinmiş resource `OutOfSync` kalır,
    prune kapalı) → `app wait --sync` timeout eder. Çözüm: prune'lanacak
    resource'u manuel incele, bilinçli `allow_prune=true` ile yeniden dispatch
    et; ya da `sync_mode=resources` ile hedefli sync yap.
- `sync_mode=full` + `revision` != origin/main HEAD (eski ancestor rollback):
  - Sync sonrası app `targetRevision=main`'e göre `OutOfSync` görünür — bu
    BEKLENEN. Workflow bu durumda `app wait --health` ile bekler (`--sync`
    değil); job yeşil olur. Kalıcı düzeltme: revert PR merge → main HEAD
    yeniden doğru desired-state, sonra normal sync.
- Rollback (desired-state geri alma):
  1. `kustomize/overlays/prod` değişikliğini revert eden PR aç + merge et
     (digest değişiklikleri için D29 evidence kuralı geçerli).
  2. Bu workflow'u revert commit'inin SHA'sıyla yeniden dispatch et.
  - Acil durumda: bu workflow'u bilinen son iyi `revision` SHA'sı ile
    dispatch et (overlay zaten o commit'te doğru desired-state'i taşır).

-------------------------------------------------------------------------------
7. REFERANS
-------------------------------------------------------------------------------

- `.github/workflows/deploy-prod-gitops.yml`
- `argocd/applications/platform-prod.yaml`
- `docs/operations/RUNBOOKS/RB-production-cutover-checklist.md`
- `docs/session-handoff-2026-05-17-session-68-prod-deploy-architecture.md` (§5)
- Codex thread `019e35d1` (prod-deploy architecture 4-PR planı)
- Codex thread `019e3638` (PR-1 cross-AI peer review)
