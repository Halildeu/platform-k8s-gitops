# Prod Realign Plan — ai.acik.com → testai seviyesi (2026-05-18)

> Koordineli frontend+backend realign. Kaynak: operatör isteği "testai ile
> ai.acik.com arasında çok fark, iyileştirmeler prod'da yok."
> Format: D28 5-alan + servis-bazlı realign spec + P0 aksiyon listesi.
> Bu doküman = sıradaki session için executable spec + handoff.

---

## 1. Bağlam

`testai.acik.com` (k3d-test) her merge'de otomatik deploy alıyor
(`deploy-testai.yml` → `kubectl set image`). `ai.acik.com` (k3d-prod)
manuel + gated. Son prod realign 2026-05-04 (Session 37). O günden beri
fark birikti. Operatör koordineli (frontend+backend birlikte) realign
istedi — version skew'i önlemek için.

## 2. İddia — Gap envanteri (canlı pod digest'leri, 2026-05-18)

### Image gap

| Servis | prod (canlı) | test (canlı) | Aksiyon |
|---|---|---|---|
| frontend | `platform-web-frontend@6d926376` (PR#200, 05-04) | `platform-web-frontend-testai@caf8639f` (PR#596) | **bump** |
| api-gateway | `16451b81` | `bb95149a` | bump |
| auth-service | `1bfe6baa` | `81499ba0` | bump |
| core-data-service | `b803507a` | `ec5cfd1b` | bump |
| notification-orchestrator | `ef0f487f` | `70491543` | bump |
| permission-service | `a973be65` | `6cf81e19` | bump |
| report-service | `1d38fe3f` | `7f3f71d6` | bump |
| user-service | `df8b84d0` | `c1316fbc` | bump |
| variant-service | `393387a0` | `70106d05` | bump |
| schema-service | `894e492f` | `894e492f` | **senkron — değişiklik yok** |
| endpoint-admin-service | — YOK — | `5bb0fa26` | **Faz 2 onboarding** |
| mailpit | — | `axllent/mailpit` | test-only (tasarım) — atla |
| webhook-receiver | — | `nginx:1.27-alpine` (stub) | test-only — atla |

### Realign hedef digest'leri (prod overlay `images:` → bu digest'ler)

`kustomize/overlays/prod/kustomization.yaml` `images:` bölümü (satır 48+):

- frontend → `ghcr.io/halildeu/platform-web-frontend` digest `sha256:d8b7b6960e294ce0352c733308937182741c05e7019a648f17be25712f93beb8` (prod-variant build `sha-e6eeb62` / PR #596; CI run `26041791563`)
- api-gateway → `sha256:bb95149a3d5fc5dc7e545d8d51de6cf9085e6000728cbaff853fe5f00236b3c9`
- auth-service → `sha256:81499ba09e248791123f82a660d5776f33dba4ea226e30ce4b465ed1f03bf3b5`
- core-data-service → `sha256:ec5cfd1b9ce3e84fc4ea81461ba488b2569170da8442b4c8c22c9198e37b573c`
- notification-orchestrator → `sha256:70491543fdc3341fbf7685773efec74a6ca2ca473c90e38f89a5247e3568b1c3`
- permission-service → `sha256:6cf81e19b7e3883626dfeb8cbfa3514dd46546aecba4c65ee70abf9c722a709f`
- report-service → `sha256:7f3f71d67eaee2943b651abefce519ae0ce1e3e0742f648e8774d46272470158`
- user-service → `sha256:c1316fbc7ce3dd9d5b63295e7a6aa05a0e92e460b85fc557fa62b8facc0d43fe`
- variant-service → `sha256:70106d05b75c3117d7ad72e316e9501e034556eab23610979652f5524e13d550`

Backend image'ları env-agnostic (`platform-backend-<svc>` — test/prod aynı
repo); canlı test digest'i doğrudan prod hedefi. Frontend env-baked
(`-testai` vs prod-variant ayrı build).

### Config gap — prod ConfigMap reconciliation

platform-backend `application.yml` incelemesi (2026-05-18):

**JWT key'leri opsiyonel, default'lu** — `${SECURITY_JWT_ISSUER:...}`,
`${SECURITY_JWT_JWK_SET_URI:...}`, `${SECURITY_JWT_AUDIENCE:...}`. Default'lar
`serban` realm referanslı AMA `localhost` host'lu (k8s'te yanlış). Yani
digest bump sonrası key set edilmezse image yanlış-host default'a düşer.
Prod'a set EDİLMELİ (prod'un mevcut `KEYCLOAK_*` değerleriyle):
- `SECURITY_JWT_ISSUER` = `https://ai.acik.com/realms/serban`
- `SECURITY_JWT_JWK_SET_URI` = `http://keycloak:8080/realms/serban/protocol/openid-connect/certs`
- `SECURITY_JWT_AUDIENCE` = **DOĞRULAMA GEREKİR** — test değeri `account,frontend,<svc>`
  ama test `platform-test` realm; prod `serban`. application.yml default'u
  serban-aware (örn. core-data: `core-data-service,frontend,account,serban-web`).
  Prod realm `serban` token audience'ları operatör/Keycloak admin ile teyit edilmeli.

**`SPRING_FLYWAY_ENABLED` — KRİTİK**: yeni image'lar `application-k8s.yml`'de
`${SPRING_FLYWAY_ENABLED:true}` → k8s profilinde **default TRUE**. Prod
ConfigMap set etmezse Flyway prod DB'de migration koşar. Test'te
core-data/report/user/variant **explicit `false`**, auth-service `true`.
→ Prod'da test davranışıyla eşleştir (explicit set), aksi halde prod
test'in koşmadığı migration'ları koşar.

**`SPRING_JPA_HIBERNATE_DDL_AUTO`** — test per-service: çoğu `update`,
auth-service `validate`. Prod'da test ile eşleştir.

| Servis | prod ConfigMap aksiyonu |
|---|---|
| api-gateway | `SECURITY_JWT_ISSUER/JWK_SET_URI/AUDIENCE` set |
| auth-service | `SECURITY_JWT_*` set + `SPRING_FLYWAY_ENABLED=true` + `SPRING_JPA_HIBERNATE_DDL_AUTO=validate` + `SPRING_DATASOURCE_HIKARI_INITIALIZATION_FAIL_TIMEOUT=30000` |
| core-data-service | `SECURITY_JWT_*` set + `SPRING_FLYWAY_ENABLED=false` + `DDL_AUTO=update` (prod-only `CORE_DATA_FLYWAY_LOCATIONS` korunur) |
| report-service | `SPRING_FLYWAY_ENABLED=false` + `DDL_AUTO=update` (prod-only OpenFGA/PG key'leri korunur) |
| user-service | `SPRING_FLYWAY_ENABLED=false` + `DDL_AUTO=update` |
| variant-service | `AUTHZ_USER_TABLE=users` + `SECURITY_JWT_ISSUER/JWK_SET_URI` set + `SPRING_FLYWAY_ENABLED=false` + `DDL_AUTO=update` |
| permission-service | config delta yok — temiz digest bump |
| notification-orchestrator | prod config test superset'i — temiz digest bump |

**Açık karar (operatör/Codex):** (1) prod `serban` realm audience değerleri;
(2) Flyway prod policy — test ile eşle mi yoksa prod-özel mi.

prod overlay ConfigMap'leri `patches:` (satır 185) bloğunda yönetiliyor —
`configMapGenerator` değil; reconciliation patch'lere eklenir.

## 3. İspatlar

- Canlı `kubectl get deploy` her iki cluster (k3d-test 13 / k3d-prod 10 deploy).
- testai `build-info.json` → `sha: e6eeb629` (PR #596).
- Frontend prod-variant digest: platform-web CI run `26041791563` push log.
- ConfigMap key diff: `kubectl get cm <svc>-config -o json` her iki cluster.
- JWT/Flyway default'ları: platform-backend `application*.yml` grep (2026-05-18).

## 4. İspatlamaz (henüz)

- Yeni backend image'ların prod ConfigMap'iyle sorunsuz boot ettiği —
  test'te kanıtlı; prod'da deploy sonrası D29 3-katman verify gerekir.
- endpoint-admin-service prod onboarding (DB / Vault secret ihtiyacı).
- Migration footprint (kaç Flyway migration prod DB'de koşacak) sayılmadı.
- prod `serban` realm `SECURITY_JWT_AUDIENCE` değerleri (operatör teyidi açık).

## 5. Bilinen boşluk + P0 aksiyon listesi (sıradaki session)

> ÖNEMLİ — git hijyeni: gitops işini **izole worktree**'de yap, paylaşılan
> ana repo'da değil. Bu session ana repo'da branch çakışmasına yol açtı.
> Doküman commit'i `prod-realign-2026-05-18` branch'inde de duruyor (05a65dd).

### Faz 1 — prod'da mevcut 9 servis realign

1. **P0** — Branch + `kustomize/overlays/prod/kustomization.yaml`:
   - `images:` (satır 48+) → §2 hedef digest'leri (9 servis; schema-service hariç).
   - `patches:` bloğundaki ConfigMap patch'lerine §2 config tablosundaki
     reconciliation (değerler yukarıda; audience operatör-teyidine bağlı).
2. **P0** — `kubectl kustomize kustomize/overlays/prod` build sanity.
3. **P0** — Cross-AI Codex review (overlay diff + config reconciliation).
4. **P0** — CI yeşil → normal squash merge + `ai-post-merge-cleanup.sh`.
5. **P0 (operatör)** — `deploy-prod-gitops.yml` `workflow_dispatch` +
   `production` environment onayı → ArgoCD `platform-prod` sync.
6. **P0** — Deploy sonrası D29 3-katman + browser-verify (ai.acik.com
   console+network), notify/auth akışları skew kontrolü.

### Faz 2 — endpoint-admin-service prod onboarding (ayrı)

Yeni servis: prod overlay'e image + base resource + ConfigMap + (varsa)
DB + Vault secret. **Vault yazma-token blocker'ına bağımlı**
(`docs/runbooks/RB-vault-root-token-recovery.md`).

### Deploy mekanizması

`deploy-prod-gitops.yml` — manuel `workflow_dispatch` + `production` gate +
ArgoCD sync (auto-sync prod'da kapalı, D30 disiplini). Operatör setup:
`docs/operations/RUNBOOKS/RB-prod-gitops-sync.md`.

### Riskler

- Flyway: digest sıçraması migration taşır → prod DB'de koşar (test'te koştu).
- frontend↔backend skew: koordineli realign (hepsi birlikte) skew'i önler.
- Vault: yeni servisler yeni secret key isteyebilir → prod ESO + Vault yazma
  (blocker — RB-vault-root-token-recovery.md).

---

## 6. Güncelleme — D29 evidence + frontend split (2026-05-18, session devamı)

PR #816 ilk halinde 9 digest (8 backend + frontend) bump'lıyordu. CI'da
`D29 evidence required for prod digest changes` gate'i blokladı: prod overlay'e
giren her yeni digest için `release-candidates/<repo>/<sha>.json` ledger
entry'sinde D29-GREEN test smoke kanıtı şart.

**Codex istişare (thread `019e3c3b`) — verdict:**
- **Backend (8 digest):** manuel `generate-ledger.sh` + gerçek
  `d29-smoke-runner.sh test` + ledger damgası = meşru unblock (kanıt gerçek
  cluster smoke'undan; uydurma değil). → AGREE.
- **Frontend prod-variant:** PR #816'dan **çıkarıldı** (REVISE → Opsiyon A).
  Sebep: prod-variant digest `d8b7b696` hiçbir test cluster'da deployed değil
  (k3d-test `-testai` variant `caf8639f` çalıştırıyor — ayrı imaj, aynı kaynak,
  env-baking farkı). testai-variant smoke'u prod-variant için D29 kanıtı
  sayılmaz (Codex: B=RED). Frontend prod promotion ayrı PR + kendi kanıt
  yolu (gerçek prod-variant smoke veya `source-parity-with-test-verified-sibling`
  evidence-class governance PR'ı — Codex Opsiyon C).

**Yapılanlar (bu commit):**
- Prod overlay frontend digest geri alındı (`d8b7b696` → mevcut prod
  `6d926376`); PR #816 artık **backend-only realign** (8 digest).
- `d29-smoke-runner.sh` genişletildi: `D29_SERVICES` artık prod promotion'a
  giren tüm backend servislerini kapsıyor (auth-service, core-data-service,
  notification-orchestrator eklendi) + Tier Secured `SECURITY_JWT_ISSUER`
  fallback (notification-orchestrator `KEYCLOAK_ISSUER_URI` taşımıyor).
- k3d-test'te genişletilmiş D29 smoke: **9/9 servis GREEN** (Up/Functional/
  Secured/Zanzibar), report `2026-05-18T18:44:43Z`.
- 8 `release-candidates/platform-backend/<digest>.json` ledger entry üretildi.
  `git_sha` = OCI manifest digest-hex (şema `git_sha` alanı "64 = OCI manifest
  digest"i açıkça tanıyor) — monorepo'da 4 servis tek commit `fa3cbbd5`'ten
  build edildiği için git-commit-SHA dosya adı çakışması yaratıyordu; digest-hex
  her artefakt için tekil. `promotion.test.smoke_evidence` D29 raporundan
  damgalandı.
- `gate-evidence-check.py` lokal: 8/8 digest D29-kanıtlı → gate satisfied.

**Frontend follow-up (Faz 1b — board #820):** env-baked variant'lar için
evidence-class governance kuruldu — ADR-0022 `frontend-prod-variant-transient-
smoke` (Codex `019e3f7e` A-lite verdict; Option C `source-parity-with-test-
verified-sibling` reddedildi). Prod-variant `d8b7b696` (build `sha-e6eeb62`,
platform-web PR #596) k3d-test `platform-test` ns'inde transient koşturulup
smoke edildi (`scripts/smoke/d29-frontend-variant-smoke.sh`): d29_up +
d29_functional GREEN, d29_zanzibar AMBER (statik SPA, `jwt_validates:false`).
Ledger `release-candidates/platform-web/e6eeb6290ef83c9ac301e2eb9315fde53ceb05ab.json`.
Prod overlay frontend digest bump `6d926376` → `d8b7b696` aynı board #820
PR'ında; prod sync operatör-gated (`deploy-prod-gitops.yml`).
