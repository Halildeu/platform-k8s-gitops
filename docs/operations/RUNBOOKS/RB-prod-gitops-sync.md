# Runbook — Prod GitOps Sync (deploy-prod-gitops.yml)

> Codex `019e35d1` prod-deploy mimarisi 4-PR planı — PR-1.
> Cross-AI peer review: Codex `019e362d` AGREE (Seçenek B).
>
> **Scope**: `platform-prod` ArgoCD Application'ının canlı prod cluster'a
> (`k3d-prod`) sync edilmesi. Prod'un **tek normal deploy mekanizması**:
> `production` environment gate'li `deploy-prod-gitops.yml` workflow'u.
>
> **Rollback**: bu runbook'un `full` + eski-revision modu rollback yapar
> (§5 — dispatch mekaniği). Rollback **kararı** (tetik matrisi, önceki-iyi
> revision bulma, follow-up) için `docs/RB-prod-deploy-rollback.md`.
>
> **2026-07-23 canlı hedef**: workflow runner'ı `.15`
> `aiserver-testai-deploy`; ArgoCD `server.rootpath=/argocd` kullandığı için
> bütün CLI çağrıları `--grpc-web-root-path /argocd` ile yapılır. Production
> environment required-reviewer kapısı korunur.

## Bağlam — neden bu mekanizma

Session 68 öncesi prod deploy yapısal olarak eksikti:

- `deploy-backend-prod.yml` image-only (`kubectl set image`) — ConfigMap /
  manifest değişikliklerini **kapsamaz**.
- ArgoCD `platform-prod` auto-sync KAPALI (D30 atomic cutover kuralı) +
  sunucuda `argocd` CLI yok.
- Ad-hoc `kubectl` prod mutasyonu guardrail-blocked + manifest drift riski.

Çözüm: prod'un tek deployer'ı ArgoCD; tetik `production` env-gate'li
`workflow_dispatch`. Auto-sync prod'da **açılmaz** — her sync manuel +
insan onaylı kalır.

---

## 1. Operator setup (tek seferlik — workflow çalışmadan ÖNCE zorunlu)

> **Yetki**: `argocd` namespace control-plane + GitHub secret mutation
> içerir → **owner/operator action** (agent yalnız açık owner opt-in ile).

PR-1 merge edildiğinde repo desired-state hazır olur (`helm-values/argocd/
values.yaml` → `prod-gitops-sync` account + RBAC). Aşağıdaki 3 adım canlıya
yansıtır.

### 1.1 — ArgoCD Helm upgrade (account + RBAC canlıya)

```bash
# Mevcut release + chart sürümünü öğren (hardcode etme)
helm list -n argocd --kube-context k3d-prod

# Önizleme (helm-diff plugin varsa) — yalnız argocd-cm + argocd-rbac-cm
# data değişikliği görünmeli; fazlası varsa ÖNCE drift'i araştır
helm diff upgrade argocd argo/argo-cd \
  --namespace argocd --kube-context k3d-prod \
  --version <helm-list'teki-chart-version> \
  --values helm-values/argocd/values.yaml

# Uygula
helm upgrade argocd argo/argo-cd \
  --namespace argocd --kube-context k3d-prod \
  --version <helm-list'teki-chart-version> \
  --values helm-values/argocd/values.yaml
```

- **Beklenen**: `argocd-cm` data'sına `accounts.prod-gitops-sync: apiKey`,
  `argocd-rbac-cm` `policy.csv`'ye 2 `p,` satırı eklenir. argocd-server
  ConfigMap'leri otomatik reload eder (~30 s).
- **Fail sinyali**: `helm diff` argocd-cm/argocd-rbac-cm dışında değişiklik
  gösterirse (drift) → durdur, drift'i ayrı incele.
- **Doğrulama**:
  ```bash
  kubectl --context k3d-prod -n argocd get cm argocd-cm \
    -o jsonpath='{.data.accounts\.prod-gitops-sync}'   # → apiKey
  kubectl --context k3d-prod -n argocd get cm argocd-rbac-cm \
    -o jsonpath='{.data.policy\.csv}' | grep prod-gitops-sync
  ```

### 1.2 — `prod-gitops-sync` API token üret

```bash
# admin parolası
ADMIN_PW=$(kubectl --context k3d-prod -n argocd get secret \
  argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)

# port-forward (workflow ile aynı pattern: HTTP, server.insecure=true)
kubectl --context k3d-prod -n argocd \
  port-forward svc/argocd-server 18083:80 &
PF_PID=$!

argocd login 127.0.0.1:18083 --plaintext --grpc-web-root-path /argocd \
  --username admin --password "${ADMIN_PW}"

# token üret — ÇIKTIYI GÜVENLE KOPYALA (bir kez gösterilir)
argocd --plaintext --grpc-web-root-path /argocd --server 127.0.0.1:18083 \
  account generate-token --account prod-gitops-sync

kill "${PF_PID}" 2>/dev/null || true
```

- **Beklenen**: tek satır JWT token çıktısı.
- **Fail sinyali**: `account 'prod-gitops-sync' does not have apiKey
  capability` → 1.1 uygulanmamış / reload bekleniyor.

### 1.3 — GitHub `production` environment secret

```bash
gh secret set ARGOCD_PROD_SYNC_TOKEN \
  --env production \
  --repo Halildeu/platform-k8s-gitops \
  --body '<1.2-token>'

# doğrula (değer görünmez)
gh secret list --env production --repo Halildeu/platform-k8s-gitops \
  | grep ARGOCD_PROD_SYNC_TOKEN
```

> `production` environment'ında **required reviewers** (1+) ayarlı olmalı —
> her sync job'u insan onayı bekler.

---

## 2. Sync operasyonu

### 2.1 — Girdiler

| Girdi | Açıklama |
|---|---|
| `revision` | Hedef commit SHA (40-hane hex). `origin/main` ancestor olmalı. |
| `sync_mode` | `resources` (filtreli — `revision` == main HEAD şart) / `full` (tüm app — eski ancestor rollback destekler). |
| `resources` | `sync_mode=resources` için zorunlu. Virgülle ayrık `GROUP:KIND:NAME` (core grup boş). |
| `allow_prune` | `true` ise ArgoCD desired-state dışı kaynakları silebilir. Default `false`. |
| `confirm` | Onay token (§2.2). |

### 2.2 — Confirm token matrisi

| Operasyon | confirm token |
|---|---|
| Normal sync (resources veya full, revision == HEAD, prune yok) | `SYNC-PROD` |
| `allow_prune=true` | `SYNC-PROD-PRUNE` |
| `full` mode + eski revision (rollback) | `SYNC-PROD-ROLLBACK` |

`allow_prune=true` + eski-revision rollback aynı run'da **desteklenmez** —
ayrı çalıştır.

### 2.3 — Dispatch

```bash
gh workflow run deploy-prod-gitops.yml \
  --repo Halildeu/platform-k8s-gitops --ref main \
  -f revision=<40-hane-sha> \
  -f sync_mode=resources \
  -f resources=':ConfigMap:<cm-adı>,apps:Deployment:<deploy-adı>' \
  -f allow_prune=false \
  -f confirm=SYNC-PROD
```

`production` environment approval gate → reviewer onaylar → `sync` job
çalışır. Takip:

```bash
gh run list --workflow=deploy-prod-gitops.yml \
  --repo Halildeu/platform-k8s-gitops --limit 3
gh run watch <RUN_ID> --repo Halildeu/platform-k8s-gitops
```

### 2.4 — Q4 schema-service ilk kullanım (örnek)

PR-1'in ilk kullanımı: schema-service Q4 desired-state'ini (#749) prod
cluster'a uygula.

```bash
REV=$(git rev-parse origin/main)   # PR-1 merge sonrası main HEAD
gh workflow run deploy-prod-gitops.yml \
  --repo Halildeu/platform-k8s-gitops --ref main \
  -f revision="${REV}" \
  -f sync_mode=resources \
  -f resources=':ConfigMap:schema-service-config,apps:Deployment:schema-service' \
  -f allow_prune=false \
  -f confirm=SYNC-PROD
```

---

## 3. Workflow gate'leri — abort koşulları

`sync` job şu noktalarda **ABORT** eder (her biri kasıtlı koruma):

| Gate | ABORT koşulu |
|---|---|
| Branch guard | workflow `main` dışından dispatch edildi |
| Revision | 40-hane hex değil / `origin/main` ancestor değil |
| Resources mode | `revision` != main HEAD (preflight + sync job re-check) |
| Secret guard | `ARGOCD_PROD_SYNC_TOKEN` yok (operator setup eksik) |
| `app diff` | exit 0 = fark yok (sync edilecek bir şey yok / yanlış revision); exit ≥2 = diff hatası |
| Prune gate | `requiresPruning` kaynak var ama `allow_prune=false` |
| Resource whitelist | (resources mode) istenen filtre dışında out-of-sync kaynak var |

Whitelist mantığı: resources mode'da **yalnız** `resources` filtresindeki
kaynaklar out-of-sync olabilir. Filtre dışında bir kaynak da out-of-sync ise
main beklenmedik şekilde drift etmiş demektir → sync etmeden önce incele.

---

## 4. Acceptance smoke (workflow DIŞINDA)

Workflow `argocd app wait --health` ile sağlığı bekler ve resources mode'da
`kubectl rollout status` okur — ama **derin smoke ayrı adımdır** (Codex
`019e35d1`). Sync sonrası operator/agent doğrular.

### 4.1 — schema-service Q4 acceptance smoke

```bash
CTX=k3d-prod; NS=platform-prod
# pod imageID == Q4 digest
kubectl --context $CTX -n $NS get pod -l app.kubernetes.io/name=schema-service \
  -o jsonpath='{range .items[*]}{.status.containerStatuses[0].imageID}{"\n"}{end}'
# beklenen: sha256:894e492f029c93277ee7d84c993bad2535d970995b0d2df08a48ebb23340ae26
# eski sha256:b660b25a... pod kalmamalı

# ConfigMap timeout parity
kubectl --context $CTX -n $NS get cm schema-service-config \
  -o jsonpath='{.data.SCHEMA_MSSQL_QUERY_TIMEOUT_SECONDS}'   # → 300

# readiness + snapshot
POD=$(kubectl --context $CTX -n $NS get pod \
  -l app.kubernetes.io/name=schema-service -o name | head -1)
kubectl --context $CTX -n $NS exec "$POD" -- \
  curl -sk -o /dev/null -w '%{http_code}\n' \
  http://localhost:8081/actuator/health/readiness   # → 200
```

Beklenen: `/api/v1/schema/snapshot?schema=workcube_mikrolink` 200 + 1513
tablo + `Extracted storage for 1513 tables` log; startup error / MSSQL
timeout / `SnapshotUnavailableException` yok. Public no-token uçlar 401.

---

## 5. Rollback — `full` mode + eski revision

Bir sync regresyon yaratırsa, `platform-prod`'u önceki iyi commit'e geri al:

```bash
gh workflow run deploy-prod-gitops.yml \
  --repo Halildeu/platform-k8s-gitops --ref main \
  -f revision=<önceki-iyi-40-hane-sha> \
  -f sync_mode=full \
  -f allow_prune=false \
  -f confirm=SYNC-PROD-ROLLBACK
```

- `revision` `origin/main` ancestor olmalı (history'de durmalı).
- `full` mode tüm app'i o revision'a sync eder.
- ⚠️ **Kaynak ekleme/silme rollback sınırı**: rollback run `--prune` taşımaz
  ve prune gate revision-aware değildir — eski revision'da bulunmayan (HEAD'de
  sonradan eklenmiş) kaynak orphan kalır. Detay + Yol A/B kararı:
  `docs/RB-prod-deploy-rollback.md` "Yol A sınırı".
- ConfigMap-only geri-alınmaması gereken parity değişiklikleri (örn.
  schema-service 300s timeout — backward-compatible) için resources mode +
  HEAD ile selective forward-fix tercih edilir.

---

## 6. Token rotation / revoke

```bash
# port-forward + admin login (§1.2 ile aynı)
# mevcut token'ları listele
argocd --plaintext --grpc-web-root-path /argocd --server 127.0.0.1:18083 \
  account get prod-gitops-sync

# yeni token üret → GitHub secret'ı güncelle (§1.3)
argocd --plaintext --grpc-web-root-path /argocd --server 127.0.0.1:18083 \
  account generate-token --account prod-gitops-sync

# eski token'ı revoke et (id account get çıktısından)
argocd --plaintext --grpc-web-root-path /argocd --server 127.0.0.1:18083 \
  account delete-token --account prod-gitops-sync --id <ESKİ_TOKEN_ID>
```

Rotation tetikleyici: token sızıntı şüphesi, runner devri, periyodik
hijyen. Revoke sonrası eski token'la sync denemesi 401 alır.

---

## 7. NE YAPMA

- ❌ `platform-prod` ArgoCD app'ine `automated:` (auto-sync) ekleme — D30
  HARD RULE; boş `automated: {}` bile auto-sync açar.
- ❌ Canlı `argocd-cm` / `argocd-rbac-cm` elle patch (repo değerlerinden
  koparır — yalnız `helm-values/argocd/values.yaml` + helm upgrade).
- ❌ `prod-gitops-sync` RBAC'ına `delete` / `override` / `update` / app
  `create` ekleme — least privilege (mutasyon = yalnız platform-prod sync;
  read default `role:readonly`'den gelir).
- ❌ Workflow'a `kubectl apply` / `set image` / patch / `exec` ekleme —
  tek deployer ArgoCD ilkesini zayıflatır.
- ❌ Token'ı repo'ya / log'a / config dosyasına yazma — yalnız GitHub
  `production` environment secret + workflow runtime env.

---

## Referanslar

- `.github/workflows/deploy-prod-gitops.yml` — bu workflow
- `helm-values/argocd/values.yaml` — `prod-gitops-sync` account + RBAC
- `argocd/applications/platform-prod.yaml` — Application (manual syncPolicy)
- `docs/RB-prod-deploy-rollback.md` — prod rollback karar runbook'u (tetik
  matrisi + önceki-revision bulma; dispatch mekaniği §5'e devreder)
- Codex thread `019e35d1` (4-PR planı) + `019e362d` (PR-1 erişim
  yöntemi AGREE — Seçenek B)
