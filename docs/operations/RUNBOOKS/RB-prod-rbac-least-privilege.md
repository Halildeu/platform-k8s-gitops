# Runbook — Prod Deploy RBAC Least-Privilege

> prod-deploy 4-PR planı (Codex `019e35d1`) PR-3. Scope kararı: Codex
> `019e380b` — PR-3 tek geniş "RBAC apply" PR'ı değil; **PR-3A repo-only
> contract** + ardından operator-gated küçük adımlar (PR-3B/C/D/E).
>
> **Scope**: prod GitOps deploy runner'ının (`deploy-prod-gitops.yml` sync
> job) ve break-glass yolunun least-privilege RBAC'a taşınması.
>
> **DURUM**: PR-3A `kustomize/base/rbac/prod-deploy-smoke/` staged manifest'i
> + bu runbook'u **repo'ya** ekler. PR-3A merge'i **canlı cluster state'i
> DEĞİŞTİRMEZ** — manifest hiçbir overlay'e bağlı değil, ArgoCD sync path'ine
> girmez. Canlıya alma adımları (PR-3B/C) `state-mutation (production)` →
> owner/operator onayı gerektirir.

## Bağlam — neden least-privilege

`docs/operations/rbac-break-glass-design.md` Session 37 audit'i: operator
kubeconfig + CI runner + ArgoCD'nin üçü de cluster-admin. PR-1 (#780) prod'un
**tek normal writer**'ını ArgoCD yaptı (`prod-gitops-sync` account `platform-prod`
`get`+`sync`'e scoped). PR-2 (#789) image-only `kubectl set image` prod
workflow'larını sildi.

Kalan risk yüzeyi artık `deploy-prod-gitops.yml` sync job'unun `.15`
`aiserver-testai-deploy` runner'ında kullandığı runtime kimliktir. Workflow'un
gerçek kubectl ihtiyacı dar:

| Adım | Namespace | İhtiyaç |
|---|---|---|
| `kubectl port-forward svc/argocd-server` | `argocd` | service/pod keşfi + `pods/portforward` create |
| `kubectl rollout status deployment/<x>` | `platform-prod` | deployment/replicaset/pod `get,list,watch` |

ArgoCD app sync'i `argocd` CLI + `ARGOCD_PROD_SYNC_TOKEN` ile yapılır (ArgoCD
kendi RBAC'ı) — k8s SA'nın app-sync yetkisine ihtiyacı yok. Yani runner k8s
identity'si yalnız **port-forward + read** olmalı; workload-mutate (patch /
set image / scale / exec) **olmamalı**.

## PR-3A — staged artefaktlar (bu PR)

- `kustomize/base/rbac/prod-deploy-smoke/prod-deploy-smoke.yaml` — `prod-deploy-smoke`
  SA (`argocd` ns) + 2 Role + 2 RoleBinding. argocd ns: port-forward + read;
  platform-prod ns: deployment/pod read+watch. Workload-mutate YOK.
- `kustomize/base/rbac/prod-deploy-smoke/kustomization.yaml` — standalone
  entrypoint; hiçbir overlay/base consume etmez.
- Bu runbook.

Doğrulama (PR-3A): `kustomize build kustomize/base/rbac/prod-deploy-smoke`
render OK + `ci.yml` kustomize-build job'unda render sanity. Canlı cluster'a
hiçbir şey uygulanmaz.

## PR-3C — prod-deploy-smoke runner cutover (operator-gated)

> **Boundary**: state-mutation (production). Owner/operator açık onayı gerek.
>
> **DURUM (2026-07-23 live recheck)**:
> - **Adım 1-2 yürütüldü** — `prod-deploy-smoke` SA + 4 RBAC objesi k3d-prod'da
>   canlı, `auth can-i` acceptance matrisi 10/10 (Codex `019e3a40` Verdict A;
>   agent-otonom — additive RBAC ≠ destructive).
> - **Adım 3 yeniden tasarlandı** — runner host inventory (2026-05-18) eski
>   "runner `~/.kube/config`'ini swap'la" modelini geçersiz kıldı. Yeni model:
>   workflow restricted kubeconfig'i `production` environment secret'tan
>   runtime materialize eder.
> - `.15` üzerinde `prod-deploy-smoke` SA/RBAC canlıdır; izin matrisi ilk 6
>   `yes`, son 4 `no` olarak yeniden doğrulanmıştır.
> - `PROD_DEPLOY_SMOKE_KUBECONFIG_B64` secret'ı `.15` cluster CA/server/token
>   bilgisiyle rotate edilmiştir. Production dispatch hâlâ required-reviewer
>   insan kapısındadır.

### Adım 1 — staged manifest'i prod cluster'a apply

```bash
kubectl --context k3d-prod apply -k kustomize/base/rbac/prod-deploy-smoke
```

- **Beklenen**: `serviceaccount/prod-deploy-smoke`, 2 `role`, 2 `rolebinding`
  created (`argocd` + `platform-prod` ns).
- **Fail sinyali**: namespace yok hatası → `argocd`/`platform-prod` ns'lerin
  varlığını doğrula (ikisi de canlıda mevcut olmalı).

### Adım 2 — yetki matrisini doğrula (`auth can-i`, impersonation)

Operator kendi kubeconfig'iyle, SA'yı impersonate ederek (token üretmeden):

```bash
SA=system:serviceaccount:argocd:prod-deploy-smoke
# İZİN VERİLMELİ (yes) — port-forward path + rollout-status path:
kubectl --context k3d-prod -n argocd        auth can-i get    services                       --as=$SA
kubectl --context k3d-prod -n argocd        auth can-i list   pods                           --as=$SA
kubectl --context k3d-prod -n argocd        auth can-i create pods --subresource=portforward --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i get    deployments                    --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i watch  deployments                    --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i get    pods                           --as=$SA
# REDDEDİLMELİ (no):
kubectl --context k3d-prod -n platform-prod auth can-i patch  deployments                    --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i create pods --subresource=exec        --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i create pods --subresource=portforward --as=$SA
kubectl --context k3d-prod                  auth can-i '*' '*'                               --as=$SA
```

> ⚠️ Subresource kontrolleri (`pods/portforward`, `pods/exec`) **`--subresource=`
> flag**'iyle yazılmıştır — `auth can-i` subresource kontrolünün canonical formu
> budur. `pods/portforward` slash formu kubectl v1.36'da intended subresource
> SAR'ını temsil etmeyip false-`no` döndürebilir; `--subresource=` formu RBAC'ı
> doğru evaluate eder. Role kuralı zaten `resources: [pods/portforward]`; gerçek
> izin doğru.

Devam eşiği: ilk 6 `yes`, son 4 `no`. Aksi halde Role kapsamını incele,
**Adım 3'e geçme**.

### Adım 3 — restricted kubeconfig'i `production` env secret olarak ver

> **2026-07-23 host inventory**: `deploy-prod-gitops.yml` runner'ı artık
> `/home/aiadmin/actions-runner-gitops-testai` üzerinde
> `[self-hosted, aiserver, testai-deploy]` etiketiyle `aiadmin` kullanıcısı
> olarak çalışır. Eski `.53` runner kaydı silinmiştir.

**Yeni mekanizma**: `deploy-prod-gitops.yml` restricted kubeconfig'i **`production`
GitHub environment secret**'tan (`PROD_DEPLOY_SMOKE_KUBECONFIG_B64`) runtime
materialize eder — `$RUNNER_TEMP`'e yazar, `KUBECONFIG`'i pinler, fail-fast guard
(identity + negatif `* *`/patch → `::error::`+exit) + `if: always()` cleanup.
`~/.kube/config` ve testai workflow'ları DOKUNULMAZ. PR-3C, PR-3D'den decouple olur.

**Adım 3.1 — `prod-deploy-smoke` için uzun-ömürlü SA-token Secret** (elle
oluşturulan `kubernetes.io/service-account-token` tipli Secret — runner aralıklı
çalışır, kısa-TTL uygun değil; blast-radius port-forward+read ile sınırlı):

```bash
kubectl --context k3d-prod -n argocd apply -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: prod-deploy-smoke-token
  namespace: argocd
  annotations:
    kubernetes.io/service-account.name: prod-deploy-smoke
type: kubernetes.io/service-account-token
EOF
```

**Adım 3.2 — restricted kubeconfig kur → `production` env secret**. context adı
tam **`k3d-prod`** olmalı (workflow `kubectl --context k3d-prod` çağırır); cluster
`server` + `certificate-authority-data` mevcut admin kubeconfig'inden, `users`
bloğu yalnız SA token. base64 → env secret:

```bash
TOKEN=$(kubectl --context k3d-prod -n argocd get secret prod-deploy-smoke-token \
  -o jsonpath='{.data.token}' | base64 -d)
# restricted kubeconfig kur — context: k3d-prod, user: prod-deploy-smoke (token).
# Sonra base64'le (host-kalıcı dosya BIRAKMA — pipe ile) → production env secret:
base64 -w0 < <restricted-kubeconfig> | \
  gh secret set PROD_DEPLOY_SMOKE_KUBECONFIG_B64 --env production \
    --repo Halildeu/platform-k8s-gitops
```

> Revoke / rotation = `prod-deploy-smoke-token` Secret delete+recreate + env
> secret güncelle (token sızıntı şüphesi / runner devri / periyodik hijyen).
> Kubeconfig host'ta KALICI dosya olarak bırakılmaz — yalnız `production` env
> secret; workflow job süresince `$RUNNER_TEMP`'te materialize edip cleanup'la siler.
>
> ⚠️ `~/.kube/config`'teki `admin@k3d-prod` PR-3C'de DOKUNULMAZ — operator'ün
> manuel/break-glass erişimi. PR-3C iddiası dar: "prod **workflow** artık admin
> kullanmıyor". Aynı Unix user'ında `admin@k3d-prod` durduğu sürece host/user
> trust boundary kapanmaz — bu PR-3D'nin işi.

### Adım 4 — cutover doğrulama (env-gate'li dispatch)

Workflow PR merge sonrası `deploy-prod-gitops.yml`'i `production` env-gate
onayıyla dispatch et. **No-op sync seçme** — workflow `argocd app diff` exit 0'ı
(fark yok) hata sayabilir; runner RBAC başarısızlığı workflow business-guard
başarısızlığıyla karışmasın diye küçük gerçek/düşük-riskli desired-state sync ya
da kontrollü out-of-sync resource filtresi seç.

Beklenen (job log): "Restricted kubeconfig — prod-deploy-smoke materialize +
guard" adımı `identity: system:serviceaccount:argocd:prod-deploy-smoke` +
guard'lar geçer; port-forward `argocd-server` kurulur; ArgoCD app
get/diff/sync/wait çalışır; `rollout status` okur — job `success`. Fail sinyali:
port-forward `Forbidden` → Role eksik; identity-guard fail → secret/kubeconfig
yanlış; ArgoCD-tarafı 401 → `ARGOCD_PROD_SYNC_TOKEN` ayrı sorun (k8s RBAC değil).

### Rollback (PR-3C)

`deploy-prod-gitops.yml`'in "Restricted kubeconfig" adımını + `env` girişini
revert et (PR revert) → workflow `~/.kube/config`'e geri düşer. İstenirse
`PROD_DEPLOY_SMOKE_KUBECONFIG_B64` env secret + `prod-deploy-smoke-token` Secret
silinir. RBAC manifest'i (`prod-deploy-smoke` SA/Role/RoleBinding) cluster'da
kalabilir — kullanılmadığı sürece zararsız (yalnız izin verir, kimseden almaz).

## PR-3B — break-glass SA live activation (operator-gated)

> **DURUM (2026-05-18)**:
> - **Test-cluster drill yürütüldü** (#804) — `ops-break-glass` SA + cluster-admin
>   CRB k3d-test'e apply + `break-glass-token.sh` exit 0 + 1h TTL token verified
>   (`auth whoami` = `system:serviceaccount:kube-system:ops-break-glass`, `auth
>   can-i '*' '*'` = `yes`, gerçek `get ns` token-canlı), audit log yazıldı; drill
>   sonrası SA k3d-test'ten silindi. `gh` yok → issue graceful-skip; Alertmanager
>   fallback toggle-off → exercise yok.
> - **Prod RBAC activation yürütüldü** (owner "sen yap" + Codex `019e3a40`):
>   `kubectl --context k3d-prod apply -k kustomize/base/rbac` → `ops-break-glass`
>   SA + cluster-admin CRB k3d-prod'da **canlı** (server dry-run temiz); `auth
>   can-i '*' '*' --as=system:serviceaccount:kube-system:ops-break-glass` = `yes`.
>   **Prod'da token issuance bilerek exercise EDİLMEDİ** — token path k3d-test
>   drill'de kanıtlı; prod'da gereksiz cluster-admin token + `gh`-yok governance
>   sürtünmesi. Token üretimi yalnız gerçek break-glass incident'inde (aşağıdaki
>   prosedür) + governance trail ile.

`ops-break-glass` SA + `ops-break-glass-cluster-admin` CRB **k3d-prod'da canlı**
(2026-05-18 apply edildi — DURUM marker). Aşağıdaki bash, **gerçek bir
break-glass incident'inde** (ArgoCD sync bloklu + acil state mutation gerekli)
audited TTL token issuance prosedürüdür — rutin değil, yalnız incident; `apply`
satırı idempotent (SA zaten canlı):

```bash
kubectl --context k3d-prod apply -k kustomize/base/rbac     # ops-break-glass

# ⚠️ break-glass-token.sh `--context` ALMAZ — `kubectl config current-context`
# kullanır. Yanlış-context token/audit riskini engellemek için izole bir
# kubeconfig'i k3d-prod'a pinle + PREFLIGHT doğrula, script'i AYNI KUBECONFIG
# ile çalıştır (test drill 2026-05-18 bulgusu — DURUM marker'a bak):
cp ~/.kube/config /tmp/kc-bg-prod
KUBECONFIG=/tmp/kc-bg-prod kubectl config use-context k3d-prod
# PREFLIGHT fail-fast — yanlış context'te token/audit üretimini engelle:
test "$(KUBECONFIG=/tmp/kc-bg-prod kubectl config current-context)" = "k3d-prod" \
  || { echo "ABORT: context k3d-prod değil — token üretme"; exit 1; }
KUBECONFIG=/tmp/kc-bg-prod bash scripts/operations/break-glass-token.sh "PR-3B activation smoke"
rm -f /tmp/kc-bg-prod    # izole kubeconfig (creds içerir) — temizle
```

Doğrula: 1h TTL token üretilir, `/var/log/break-glass-audit.log` satırı yazılır.
**GitHub audit issue**: script `gh` kurulu + authenticated ise issue açar; aksi
halde "gh CLI unavailable — SKIPPED" warning'i basıp devam eder. Gerçek
break-glass token issuance'da `gh` kurulu/authenticated OLMALI — script
gh-unavailable warning'i verirse operator issue'yu **manuel açmadan** kabul
etmez (governance trail zorunlu). `kubectl create token` API server TTL cap'ine takılırsa cap'i kontrol
et. **Static long-lived break-glass token YOK** — yalnız TTL token. Test
cluster'da drill: yukarıdaki DURUM marker (2026-05-18 yapıldı, mekanizma
doğrulandı).

## PR-3D — operator readonly identity (owner-coordination)

> **Boundary** — PR diff'i: **none of the above** (repo-only staged manifest +
> CI render step + runbook doc; merge canlı cluster state'i DEĞİŞTİRMEZ).
> Runbook execution (Adım 1-5): state-mutation (production) + credential
> material issuance/read (Adım 3 SA-token Secret üretir + token okur) +
> owner/operator-gate — Adım 1-5 operator'ün **günlük kubectl kimliğini**
> değiştirir.
>
> **DURUM (2026-05-18)**:
> - **Staged manifest yürürlükte** — `kustomize/base/rbac/prod-operator-readonly/`
>   (`prod-operator-readonly` SA `kube-system` ns + `prod-operator-readonly-view`
>   ClusterRoleBinding → built-in `view`). PR-3A pattern: standalone entrypoint,
>   hiçbir overlay/base consume etmez → merge canlı state'i DEĞİŞTİRMEZ. CI
>   `ci.yml` kustomize-build job'unda `kustomize build` render sanity.
> - **Önkoşul karşılandı** — PR-3B `ops-break-glass` SA + cluster-admin CRB
>   k3d-prod'da canlı (yukarıdaki PR-3B DURUM); token path k3d-test drill'inde
>   kanıtlı. Operator readonly'ye geçtikten sonra mutate / exec / secret yolu
>   break-glass üzerinden açık kalır.
> - Aşağıdaki Adım 1-5 operator-gated, owner kararıyla yürütülür.

### Tasarım — neden yeni SA, `admin@k3d-prod`'a `view` DEĞİL

`rbac-break-glass-design.md` Faz 3'ün orijinal yaklaşımı (`view` ClusterRoleBinding'i
mevcut `admin@k3d-prod` User'a ekle) **eksik**: Kubernetes RBAC **additive** —
cluster-admin binding dururken `view` eklemek yalnız izin EKLER, yetki DÜŞÜRMEZ.

Doğru tasarım: yeni `prod-operator-readonly` ServiceAccount → yalnız `view`
ClusterRoleBinding. Operator bu SA olarak authenticate eden kubeconfig'i günlük
kullanıma alır → günlük yetki read-only'ye düşer. `admin@k3d-prod` günlük
path'ten çıkar, yalnız break-glass / offline issuer olarak saklanır (silinmez).

`view` — ClusterRoleBinding nedeniyle — `view` kapsamındaki (namespaced)
kaynaklarda TÜM namespace'lerde get/list/watch + `pods/log` verir; secret read,
pods/exec, pods/portforward, her türlü mutate VERMEZ. Cluster-scoped infra
read'leri de (`nodes`, `persistentvolumes`, `storageclasses` — `view`
namespaced-aggregated, bunları kapsamaz) kapsam dışı: bilinçli minimal
başlangıç; operator adoption'ında düzenli bir gap çıkarsa ayrı supplementary
ClusterRole follow-up'ı, mutate ihtiyacı `ops-break-glass` yolu.

### Adım 1 — staged manifest'i prod cluster'a apply

```bash
kubectl --context k3d-prod apply -k kustomize/base/rbac/prod-operator-readonly
```

- **Beklenen**: `serviceaccount/prod-operator-readonly` (`kube-system`) +
  `clusterrolebinding/prod-operator-readonly-view` created.
- Additive RBAC — mevcut hiçbir binding'i kaldırmaz; `admin@k3d-prod` bu adımda
  el değmeden durur (yetki düşürme Adım 4 kubeconfig cutover'ında olur).

### Adım 2 — yetki matrisini doğrula (`auth can-i`, impersonation)

```bash
SA=system:serviceaccount:kube-system:prod-operator-readonly
# İZİN VERİLMELİ (yes) — namespaced read (CRB her ns'de geçerli):
kubectl --context k3d-prod -n platform-prod auth can-i get   pods                     --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i watch deployments              --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i get   pods --subresource=log   --as=$SA
kubectl --context k3d-prod -n argocd        auth can-i list  services                 --as=$SA
# REDDEDİLMELİ (no) — mutate / exec / secret:
kubectl --context k3d-prod -n platform-prod auth can-i patch  deployments             --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i delete pods                    --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i create pods --subresource=exec --as=$SA
kubectl --context k3d-prod -n platform-prod auth can-i get    secrets                 --as=$SA
kubectl --context k3d-prod                  auth can-i '*' '*'                        --as=$SA
# REDDEDİLMELİ (no) — cluster-scoped infra read (`view` namespaced-aggregated; bilinçli kapsam dışı):
kubectl --context k3d-prod auth can-i get  nodes                          --as=$SA
kubectl --context k3d-prod auth can-i list persistentvolumes              --as=$SA
kubectl --context k3d-prod auth can-i list storageclasses.storage.k8s.io  --as=$SA
```

> ⚠️ Subresource kontrolleri (`pods/log`, `pods/exec`) `--subresource=` flag'iyle
> — `auth can-i` subresource'un canonical formu; slash formu kubectl v1.36'da
> false-`no` döndürebilir (PR-3C Adım 2 notuna bak).

Devam eşiği: ilk 4 `yes`, son 8 `no`. Aksi halde ClusterRole/CRB'yi incele,
**Adım 3'e geçme**.

### Adım 3 — readonly kubeconfig kur

`prod-deploy-smoke` (PR-3C Adım 3.1-3.2) ile aynı mekanizma — uzun-ömürlü
SA-token Secret + restricted kubeconfig:

```bash
kubectl --context k3d-prod -n kube-system apply -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: prod-operator-readonly-token
  namespace: kube-system
  annotations:
    kubernetes.io/service-account.name: prod-operator-readonly
type: kubernetes.io/service-account-token
EOF

TOKEN=$(kubectl --context k3d-prod -n kube-system get secret prod-operator-readonly-token \
  -o jsonpath='{.data.token}' | base64 -d)
# readonly kubeconfig kur — context adı `k3d-prod-ro` (günlük admin context'iyle
# karışmasın); cluster `server` + `certificate-authority-data` mevcut admin
# kubeconfig'inden, `users` bloğu yalnız SA token.
```

### Adım 4 — günlük kullanıma al + `admin@k3d-prod` stash (owner kararı)

- Operator'ün günlük kubeconfig'i (`~/.kube/config`) `k3d-prod-ro` context'ine
  geçer; `current-context` readonly olur.
- `admin@k3d-prod` context + user girişi günlük kubeconfig'ten **çıkarılır**, ayrı
  offline dosyaya (`~/.kube/admin-k3d-prod.offline`, `chmod 600`) taşınır —
  SİLİNMEZ; break-glass dışı acil offline erişim için saklanır.
- ⚠️ Host-paylaşımlı runner etkisi: `deploy-prod-gitops.yml` PR-3C cutover'ı
  sonrası `production` env secret'taki restricted kubeconfig'i kullanır,
  `~/.kube/config`'e bağımlı değil → readonly geçişi prod deploy workflow'unu
  KIRMAZ. `deploy-testai.yml` k3d-test context'i kullanır, k3d-prod'dan etkilenmez.

### Adım 5 — cutover doğrula

```bash
kubectl config current-context             # → k3d-prod-ro
kubectl get  pods   -n platform-prod        # → çalışır (view)
kubectl logs        -n platform-prod <pod>  # → çalışır (pods/log)
kubectl delete pod  -n platform-prod <x>    # → Forbidden (mutate kapalı — beklenen)
kubectl get  secret -n platform-prod <x>    # → Forbidden (view secret hariç — beklenen)
```

Mutate / exec / secret gerektiğinde: `ops-break-glass` TTL-token yolu (yukarıdaki
PR-3B prosedürü) + 30dk reconciliation PR.

### Rollback (PR-3D)

Günlük kubeconfig `current-context`'ini `admin@k3d-prod`'a geri al (offline
dosyadan context + user girişini geri ekle). `prod-operator-readonly` SA + CRB +
token Secret cluster'da kalabilir — kullanılmadığı sürece zararsız (yalnız read
izni verir, kimseden yetki ALMAZ).

## PR-3E — audit/alarm (Faz 5)

> Codex `019e3a40` scope: PR-3E **3 parçaya** ayrıldı — biri autonomous (A),
> ikisi operator-gated (audit-policy + PR-3E-B).

### PR-3E-A — RBAC Forbidden telemetri (autonomous, staged)

`kustomize/base/monitoring/rbac-least-privilege-rule.yaml` — `PrometheusRule`
(ns `monitoring`, `release: kube-prometheus-stack`): k8s API 403/Forbidden
**PROXY-telemetrisi**.
- **KubeAPIForbiddenMutatingRequest** — `apiserver_request_total{code="403",
  verb=~"POST|PUT|PATCH|DELETE|CONNECT"}` increase >0 (least-privilege sonrası
  yetkisiz mutate denemesi; `CONNECT` = pods/exec, pods/portforward yolları).
- **KubeAPIForbiddenRequestSpike** — 403 oranı >0.2 req/s, 10dk (bozuk
  kubeconfig / loop'ta yetkisiz job / yanlış token).
- İkisi de `severity: warning` — canlı baseline sonrası threshold/severity
  ayarlanabilir.
- ⚠️ `apiserver_request_total` **tam RBAC audit log DEĞİL** — Forbidden
  yanıtları için proxy sinyaldir. Tam audit (kim/ne/ne zaman) audit-policy
  gerektirir (aşağı).
- Staged: `kustomize/base/monitoring/kustomization.yaml` `resources:`'ine
  eklendi; canlı firing `kubectl apply -k kustomize/base/monitoring` (prod
  monitoring ns) + Prometheus rule reload sonrası (operatör / ArgoCD monitoring sync).

### PR-3E — operator-gated kalanlar

- **audit-policy.yaml** — kube-apiserver `--audit-policy-file` = k3d
  control-plane launch config + host path mount + API server restart.
  Kubernetes manifest DEĞİL → operator/cluster-admin, maintenance window.
  Repo'da taslak/runbook olabilir; PR-3E-A acceptance bununla bloke değil.
- **PR-3E-B — `BreakGlassUsed` Alertmanager route** (Slack/email out-of-band
  receipt). break-glass kullanımının PRIMARY audit'i zaten `break-glass-token.sh`
  (GitHub issue + local audit log); `BreakGlassUsed` script-push Alertmanager
  alert'i — metric DEĞİL, PrometheusRule ile yakalanamaz. Native Slack/email
  route prod Alertmanager config değişimi + secret readiness + Helm upgrade
  gerektirir → ayrı operator-gated PR.

## NE YAPMA

- ❌ PR-3A staged manifest'i bir overlay/`base`'in `resources:`'ine ekleme —
  ArgoCD `platform-prod` sync'inde canlıya sızar (operator-gate'siz mutation).
- ❌ `prod-deploy-smoke` Role'üne `patch`/`update`/`delete`/`pods/exec` ekleme
  — bütün amaç workload-mutate'i kapatmak.
- ❌ Static long-lived break-glass token üretme — yalnız TTL.
- ❌ PR-3D'yi (operator readonly) break-glass canlı + doğrulanmadan yapma.
- ❌ Runner cutover'ı eski admin kubeconfig'i host'tan kaldırmadan "bitti"
  sayma — least-privilege bypass açık kalır.

## Referanslar

- `docs/operations/rbac-break-glass-design.md` — RBAC tasarım + Faz 1-5
- `kustomize/base/rbac/prod-deploy-smoke/` — PR-3A staged manifest
- `kustomize/base/rbac/break-glass-sa.yaml` — break-glass SA (staged)
- `scripts/operations/break-glass-token.sh` — break-glass TTL token helper
- `.github/workflows/deploy-prod-gitops.yml` — prod deploy workflow (runner)
- `docs/operations/RUNBOOKS/RB-prod-gitops-sync.md` — sync workflow runbook
- Codex thread `019e380b` (PR-3 scope) + `019e35d1` (4-PR planı)
