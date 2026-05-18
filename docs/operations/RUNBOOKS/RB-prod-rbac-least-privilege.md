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

Kalan risk yüzeyi: `deploy-prod-gitops.yml` sync job, `staging-sw-testai-deploy`
runner'ında `kubectl --context k3d-prod` çağırıyor — runner kubeconfig hâlâ
`admin@k3d-prod` cluster-admin. Workflow'un gerçek kubectl ihtiyacı dar:

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
> Tetik: PR-3A merged + runner least-privilege'a geçiş kararı.
>
> **DURUM (2026-05-18)**: **Adım 1-2 yürütüldü** — `prod-deploy-smoke` SA + 4
> RBAC objesi k3d-prod'da canlı, `auth can-i` acceptance matrisi 10/10. Codex
> `019e3a40` Verdict A: Adım 1-2 (additive RBAC apply + read-only `auth can-i`
> doğrulama) agent-otonom yürütülebilir — istişare verdict'i bu dar alt-adım
> için operator-gate'i açtı (Pre-Production Full Authority; additive RBAC ≠
> destructive). **Operator Adım 3'ten devam eder.** Adım 3-4 hâlâ
> operator-gated (runner kubeconfig cutover + env-gate dispatch — gerçek
> prod-deploy-infra değişimi). Adım 1-2 idempotent — yeniden koşulabilir.

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
> flag**'iyle yazılmıştır. kubectl `auth can-i`'nin eski `pods/portforward` slash
> formu modern kubectl'de (doğrulandı v1.36) subresource'u yanlış değerlendirip
> false-`no` döndürür — `--subresource=` formu RBAC'ı doğru evaluate eder. Role
> kuralı zaten `resources: [pods/portforward]`; gerçek izin doğru.

Devam eşiği: ilk 6 `yes`, son 4 `no`. Aksi halde Role kapsamını incele,
**Adım 3'e geçme**.

### Adım 3 — runner kubeconfig'i prod-deploy-smoke token'ına çevir

`prod-deploy-smoke` için **uzun ömürlü SA token Secret'ı** (elle oluşturulan
`kubernetes.io/service-account-token` tipli Secret — runner aralıklı çalıştığı
için kısa-TTL token uygun değil; blast-radius zaten port-forward+read ile
sınırlı). Revoke = Secret delete + recreate; rotation cadence: token sızıntı
şüphesi / runner devri / periyodik hijyen (break-glass'ın kısa-TTL token'ından
ayrımı budur):

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

TOKEN=$(kubectl --context k3d-prod -n argocd get secret prod-deploy-smoke-token \
  -o jsonpath='{.data.token}' | base64 -d)
```

Token'la kısıtlı bir kubeconfig kur (cluster server + CA mevcut admin
kubeconfig'inden kopyalanır; **user** bloğu token olur). Bu kubeconfig
runner host'unda `deploy-prod-gitops.yml`'in `k3d-prod` context'i için
kullanılan dosyanın yerine konur.

> ⚠️ **Kritik**: runner host'unda eski `admin@k3d-prod` cluster-admin
> kubeconfig'i runner user tarafından okunabilir kalırsa cutover eksik —
> least-privilege bypass edilebilir. Eski admin kubeconfig'i runner user
> erişiminden kaldır (host-spesifik yol operatör tarafından belirlenir;
> `staging-sw-testai-deploy` runner'ın `KUBECONFIG`/`~/.kube/config` yolu).

### Adım 4 — runner cutover doğrulama (canlı sync)

PR-3C sonrası bir `deploy-prod-gitops.yml` no-op/küçük sync dispatch et;
`production` env-gate onayıyla. Beklenen: port-forward kurulur, ArgoCD
app get/diff/sync/wait çalışır, `rollout status` okur — job `success`.
Fail sinyali: port-forward `Forbidden` → Role eksik; sync ArgoCD-tarafı
401 → `ARGOCD_PROD_SYNC_TOKEN` ayrı sorun (k8s RBAC değil).

### Rollback (PR-3C)

Runner kubeconfig'ini önceki (admin) hâline geri al; `prod-deploy-smoke-token`
Secret'ını sil. Manifest (`prod-deploy-smoke` SA/Role/RoleBinding) cluster'da
kalabilir — kullanılmadığı sürece zararsız (yalnız izin verir, kimseden almaz).

## PR-3B — break-glass SA live activation (operator-gated)

`kustomize/base/rbac/break-glass-sa.yaml` (`ops-break-glass` SA + cluster-admin
CRB) + `scripts/operations/break-glass-token.sh` repo'da **var ama** hiçbir
overlay'e bağlı değil → canlıda **yok** (`kubectl -n kube-system get sa
ops-break-glass` → NotFound). PR-3B canlıya alır:

```bash
kubectl --context k3d-prod apply -k kustomize/base/rbac     # ops-break-glass
# token issuance smoke:
bash scripts/operations/break-glass-token.sh "PR-3B activation smoke"
```

Doğrula: 1h TTL token üretilir, `/var/log/break-glass-audit.log` satırı +
GitHub audit issue açılır. `kubectl create token` API server TTL cap'ine
takılırsa cap'i kontrol et. **Static long-lived break-glass token YOK** —
yalnız TTL token. Önce test cluster'da drill önerilir.

## PR-3D — operator readonly identity (ayrı owner-coordination)

> `rbac-break-glass-design.md` Faz 3'teki "`admin@k3d-prod` user'a `view`
> ClusterRoleBinding ekle" yaklaşımı **eksik**: Kubernetes RBAC additive'dir
> — mevcut cluster-admin binding dururken `view` eklemek yetki DÜŞÜRMEZ.

Doğru PR-3D: yeni readonly normal identity üret + günlük kullanıma al; eski
`admin@k3d-prod`'u normal path'ten çıkar, yalnız break-glass/offline issuer
olarak sakla. Bu kullanıcının canlı kubectl-mutate alışkanlığını ve incident
müdahale yolunu değiştirir → **açık owner/oncall koordinasyonu** gerekir;
PR-3B (break-glass) canlı + token issuance doğrulanmadan yapılmaz.

## PR-3E — audit/alarm (Faz 5)

break-glass kullanım alert'i + Forbidden/RBAC-violation telemetrisi + audit
log retention. Ayrı PR; `rbac-break-glass-design.md` Faz 5.

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
