# ArgoCD `RespectIgnoreDifferences` + Blanket `/metadata` Ignore — Anti-pattern

> Codex thread `019e41d7` AGREE / `019e4216` AGREE_WITH_REVISIONS — Session 42 (2026-05-19) bug class fix + regression guard.
>
> PR'lar: [#850](https://github.com/Halildeu/platform-k8s-gitops/pull/850) (`platform-eso-prod`), [#851](https://github.com/Halildeu/platform-k8s-gitops/pull/851) (`platform-prod`).
>
> CI gate: `.github/workflows/gate-argocd-respect-ignore-diff.yml` →
> `scripts/governance/check_argocd_respect_ignore_diff.py`.

## 1. Bug class — iki ayrı sınıf (Codex `019e4216` post-impl absorb)

`RespectIgnoreDifferences=true` syncOption ile birlikte iki **ayrı** bug sınıfı vardır; her ikisi de regression guard ile yasaklanır ama mekanizmaları farklıdır:

### 1.A — API-server hard failure (managedFields class)

`spec.ignoreDifferences` içinde **`/metadata`** (exact) veya **`/metadata/managedFields`** veya managedFields descendant (örn. `/metadata/managedFields/0`, `.metadata.managedFields[].fieldsV1`) → Server-Side-Apply sync'i **her seferinde** `metadata.managedFields must be nil` ile API server tarafından **hard-rejected**. Uygulama `OutOfSync+Degraded` kilidine girer; bu sınıf bypass edilemez — Kubernetes API contract'ı zorlar.

### 1.B — Policy/guard ban (container class)

`/metadata/annotations` (exact, key segmenti yok) veya `/metadata/labels` (exact, key segmenti yok) — bunlar "tüm annotations / tüm labels" container'ını ignore eder. API server bunu hard-reject etmez, ama:
- Kontrolsüz yüzey: yeni annotations/labels eklenip silindiğinde diff sürekli salınır, GitOps tracking güvenilmez olur (örn. `argocd.argoproj.io/tracking-id` annotation'ı bile bu container'ın içinde — kendini ignore eder)
- Repo governance kararı: yalnız **specific-key path'leri** (örn. `/metadata/annotations/<escaped-key>`) kabul; container-level ignore policy gate ile reddedilir

## 2. Mekanizma

### 2.A — Class 1.A mekanizması (API server reject)

1. `ServerSideApply=true` ArgoCD'yi SSA gövdesini API server'a göndermeye yönlendirir.
2. `RespectIgnoreDifferences=true` `spec.ignoreDifferences` listesini **diff görünümünden** çıkarıp **desired-state SSA gövdesine** dahil eder — yani ignore edilen yollar "canlı değer korunur" olarak SSA payload'ına geri konur.
3. Blanket `/metadata` veya `/metadata/managedFields` ifadesi ArgoCD'ye canlı `/metadata` bloğunu — **`managedFields` dahil** — SSA gövdesine kopyalamasını söyler.
4. Kubernetes API server SSA isteklerinde `metadata.managedFields` field'ının `nil` olmasını zorunlu kılar (server bu field'ı her zaman kendi yönetir).
5. Sonuç: ilk sync denemesi `metadata.managedFields must be nil` hatasıyla **API tarafından** reddedilir; ArgoCD app `OutOfSync` + `Degraded` kalır; tüm child resource sync'leri bu app altında bloke olur (sadece bug'lı entry değil — sync **transaction** seviyesinde fail eder).

### 2.B — Class 1.B mekanizması (policy enforcement)

1. `/metadata/annotations` container'ı ignore edildiğinde ArgoCD ServerSideApply gövdesine canlı annotations bloğunun **tamamını** kopyalar.
2. API server bunu hard-reject etmez (annotations alan SSA-compatible), ama:
   - **`argocd.argoproj.io/tracking-id`** annotation'ı bu container'ın içindedir — ArgoCD'nin kendi ownership tracking'ini kendisi ignore etmiş olur (live-state ile desired drift kaybolur, governance bozulur)
   - Başka actor'lar (CI bot, operatör, başka ArgoCD app) annotations ekleyip sildiğinde ArgoCD sürekli reconcile döner; cosmetic drift sonsuz
3. Bu yüzden repo regression guard `/metadata/annotations` veya `/metadata/labels` **container** ignore'unu reddeder; sadece spesifik-key path'leri (`/metadata/annotations/<escaped-key>`) kabul eder.

## 3. Canlı kanıt geçmişi

- **2026-04-23 PR #54** (`platform-prod`): `v1beta1→v1` ExternalSecret CRD geçişi sonrası cosmetic diff bastırmak için `/metadata` ignore + `RespectIgnoreDifferences=true` eklendi. İlk sırada işe yaradı gibi göründü çünkü o zaman ArgoCD versiyonu / ESO versiyonu kombinasyonunda `managedFields` SSA gövdesine taşınmıyordu (eski davranış).
- **2026-04-24 Session 28**: cosmetic OutOfSync sürekli görünmeye başladı.
- **2026-05-09 ESO v1 default-fields** (`conversionStrategy`, `decodingStrategy`, `metadataPolicy`, `nullBytePolicy`): `jqPathExpressions` ile targeted ignore (cosmetic diff için bu kısım hâlâ doğru).
- **2026-05-19 Session 42**: PR #570'in handoff merge + JetSMS şifre fix akışı sırasında `platform-eso-prod` resource-scoped sync `metadata.managedFields must be nil` ile fail oldu. Root cause tespit edildi: `RespectIgnoreDifferences=true` + blanket `/metadata` → SSA `managedFields` reject.
- **PR #850**: `platform-eso-prod` — `RespectIgnoreDifferences=true` syncOption **kaldırıldı**; ExternalSecret + ClusterSecretStore `/metadata` → `/status` daraltıldı.
- **PR #851**: `platform-prod` — `RespectIgnoreDifferences=true` **kaldı** (legitimate: HPA `/spec/replicas` + ConfigMap `/data` + 3 spesifik annotation path); fakat ExternalSecret `/metadata` → `/status` daraltıldı (aynı bug class'ının latent instance'ı).

## 4. Doğru pattern'ler

### 4.1 `RespectIgnoreDifferences` ne zaman gerekli

ArgoCD `automated.selfHeal=true` veya operatör manuel `app sync` sırasında **canlı runtime değerlerin manifestteki desired-state'e geri çekilmesini istemiyorsan** gerek var. Örnekler:

| Senaryo | Targeted ignore | Neden |
|---|---|---|
| HPA Deployment'ın `/spec/replicas`'ı | `apps/Deployment` → `jsonPointers: [/spec/replicas]` | HPA scale subresource'u desired replica sayısını yönetir; ArgoCD manifest'i `replicas: 2` ise selfHeal aksi halde her drift'i 2'ye geri çeker. |
| Dinamik writer ConfigMap (örn. smoke status writer) | `kind: ConfigMap, name: <writer-managed>` → `jsonPointers: [/data, /metadata/annotations/<specific-key>]` | Writer her tetikte `/data` ve spesifik annotation'ları update eder; ArgoCD aksi halde her sync'te boş baseline'a geri çeker. |
| ESO ExternalSecret v1 default fields | `jqPathExpressions: [.spec.data[].remoteRef.conversionStrategy, …]` | ESO v1 CRD'de bu field'lar default değer ile canlıda var ama manifest'te yok → cosmetic OutOfSync. |

### 4.2 İzin verilen pointer/expression örnekleri

- `/status`
- `/spec/replicas`
- `/metadata/annotations/<escaped-specific-key>` — örn. `/metadata/annotations/frontend-federation-smoke.io~1last-fire`. (`~1` = `/` JSON pointer escape'i.)
- `/metadata/labels/<escaped-specific-key>`
- `/metadata/finalizers` — istisna; bu container "specific-key" değil ama Kubernetes API'sinde finalizer set'ini olduğu gibi koruma legitimate olabilir. **Blanket `/metadata` ile karıştırılmamalı.**

### 4.3 Yasak pointer/expression örnekleri

- `/metadata` — blanket
- `/metadata/managedFields` — direkt managedFields field'ı
- `/metadata/managedFields/<n>` — managedFields descendant
- `/metadata/annotations` — container, spesifik key segmenti yok
- `/metadata/labels` — container, spesifik key segmenti yok
- `.metadata` — jq exact
- `.metadata.managedFields` — jq exact

## 5. CI guard

`.github/workflows/gate-argocd-respect-ignore-diff.yml` PR-time static analysis:

- Sadece `kind: Application` dokümanlarını tarar (`argocd/applications/**/*.yaml`).
- `spec.syncPolicy.syncOptions[]` içinde `RespectIgnoreDifferences=true` varsa **risk modu**'na girer.
- Risk modunda her `spec.ignoreDifferences[]` entry'sinin `jsonPointers` ve `jqPathExpressions` listesini tarar.
- §4.3'teki yasak pattern'i hit ederse PR fail eder; remediation hint + Codex thread / PR referansı çıktıya basar.

Acceptance:

```bash
python3 scripts/governance/check_argocd_respect_ignore_diff.py --verbose
python3 -m unittest tests.governance.test_check_argocd_respect_ignore_diff -v
```

## 6. Tarihsel durum tablosu

| App | RespectIgnoreDifferences | `/metadata` ignore | Durum |
|---|---|---|---|
| `platform-eso-prod` | ❌ kaldırıldı (PR #850) | yok (eski `/metadata` → `/status` daraltıldı) | ✅ Fixed |
| `platform-prod` | ✅ var (legitimate) | yok (eski ExternalSecret `/metadata` → `/status` daraltıldı; HPA + ConfigMap pattern'leri targeted) | ✅ Fixed |
| `platform-test` | ✅ var (legitimate) | yok (yalnız `/metadata/annotations/frontend-federation-smoke.io~1<key>` specific paths) | ✅ Zaten safe |
| Diğer ArgoCD app'leri | ❌ yok | yok | ✅ Safe |

## 7. Bağlantı

- **HARD RULE — Governance / Sistemik Bug** (`~/.claude/CLAUDE.md` global): aynı pattern'in geri gelmesini sistem temizliği gerekliği olarak işaretler.
- **HARD RULE — No Fake Work**: `RespectIgnoreDifferences=true` + blanket `/metadata` ignore'un ürettiği `SecretSynced=True` görünümü gerçek delivery sağlamayabilir; bu doc gate ile birlikte regression sahte-yeşil sinyali engeller.
- **ArgoCD docs**: [Diffing Customization](https://argo-cd.readthedocs.io/en/stable/user-guide/diffing/), [Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/#respect-ignore-difference-configs).
