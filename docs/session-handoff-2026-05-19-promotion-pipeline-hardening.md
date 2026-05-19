# Session Handoff — 2026-05-19 — Promotion Pipeline Hardening (ADR-0023 + P0 onarım + 7-PR guardrail train)

> Format: D28 5-alan + sıradaki agent P0 aksiyon listesi
> Tetikleyici: HARD RULE — Session Otomatik Açma #1 (context doygunluğu) + #4 (initiative 18-task scope, faz geçişi).

## 1. Bağlam (neden bu handoff)

Bu session iki prod deploy zinciriyle başladı, ardından kullanıcının bildirdiği bir bug sistemik bir promotion-pipeline denetimini açtı.

- **M365-passive** (platform-backend PR #251 kaynağı) — yeni M365 kullanıcıları `enabled=false` auto-provision + `CurrentUserResolver` activation gate → `403 ACCOUNT_DISABLED`. Prod user-service'e taşındı.
- **Türkçe-isim UTF-8 mojibake fix** (platform-web PR #608 kaynağı). Prod frontend'e taşındı.
- **Kullanıcı bug raporu**: non-superadmin kullanıcı ("Halil Koçoğlu") prod rapor sayfalarında `403` alıyor; `admin@example.com` almıyor. Kök neden → prod OpenFGA modelinde `report_group` tipi eksik.
- **Kullanıcı talebi**: "bu işi çözmemiz lazım kontrol ve testlerle sağlamlaştırmamız lazım" — bug'ı çöz + CI gate + test ile tekrarını engelle.

4-nokta digest denetimi (ADR-0023 Ek A) `dev → test → prod` zincirinde 3 boşluk sınıfı buldu: (1) test overlay drift — `kubectl set image` overlay'i bypass ediyor, (2) test→prod terfi manuel + zorlanmıyor — prod sessizce bir jenerasyon geride, (3) image-dışı artifact (OpenFGA modeli) promotion pipeline'ı yok. Bunun üzerine **promotion-pipeline hardening initiative** başlatıldı: ADR-0023 (Guardrail PR-1) + 5-adımlı P0 onarım + 7-PR guardrail train (toplam 18 task).

## 2. İddia (bu session'da MERGED PR'lar — hepsi `platform-k8s-gitops`)

| PR | Başlık | Merge commit |
|---|---|---|
| #834 | fix(smoke): d29 Tier-2 schema-service probe → /schemas (auth-gated, fast) | `961f361` |
| #835 | chore(prod): user-service digest bump c94c057c → fce3096e (M365-passive) | `71cd845` |
| #837 | chore(prod): frontend digest bump d8b7b696 → 7e0999d1 (Türkçe-isim UTF-8 fix) | `a09a487` |
| #844 | docs(adr-0023): promotion pipeline — test overlay GitOps-authoritative | `b066634` |
| #845 | chore(test-overlay): realign overlays/test to validated test-live generation | `f79b7ba` |

P0 onarım ilerleme: **P0-a** (promotion freeze + 4-nokta denetim matrisi kanıt — task #12) ✅, **P0-b** (overlays/test → test-live jenerasyon realign — task #13 / PR #845) ✅. **Guardrail PR-1** (ADR-0023 — task #16 / PR #844) ✅.

Detay:
- **#834** — D29 smoke runner Tier-2 schema-service probe `/api/v1/schema/snapshot` → `/api/v1/schema/schemas`. `/snapshot` permitAll + cold-cache yavaş (>25s timeout → false-RED); `/schemas` JWT-gated, hızlı 401.
- **#835** — prod overlay user-service digest `c94c057c` → `fce3096eb994...` + el-yazımı D29 ledger. Dispatch + browser smoke: M365 first-login → `403 ACCOUNT_DISABLED` doğrulandı.
- **#837** — prod overlay frontend digest `d8b7b696` → `7e0999d1865a...` + frontend D29 ledger (`d29_zanzibar=AMBER`). Dispatch + browser-verify: Türkçe isim doğru render.
- **#844** — ADR-0023: shared `k3d-test` ana workload'ları yalnız `overlays/test` üzerinden GitOps-managed; ad-hoc `kubectl set image` YASAK. D1-D5 kararları + Ek A 4-nokta digest matrisi. `AGENTS.md` §3'e HARD RULE bullet eklendi. Codex thread `019e40e4` — REVISE (3 bulgu absorb) → AGREE.
- **#845** — `overlays/test/kustomization.yaml` 9 digest realign (8 backend + frontend-testai) test-CANLI jenerasyona. Yalnız bu dosya değişti.

## 3. İspatlar

- 5 PR `git log` ile MERGED doğrulandı; base `origin/main` = `f79b7ba` (#845). Bu handoff PR (#846) yalnız bu handoff dokümanını ekler — kod/manifest değişimi yok.
- **M365-passive CANLI**: prod user-service digest `fce3096e`'ye rollout; browser smoke M365 first-login → `403 ACCOUNT_DISABLED` (task #5).
- **UTF-8 fix CANLI**: prod frontend digest `7e0999d1`'e rollout; browser-verify Türkçe isim render (task #8).
- **reports-403 kök neden**: prod OpenFGA model `01KPXCVBMDKXXRPGKFGPDRVBQX` → `report_group` tipi **yok**; test model `01KRTJVEMAW80B2D35GN8HJDPG` → **var**. "Halil Koçoğlu" (userId 1204) `reports.hr-compensation-detay.view` permission'ına sahip (`scopes:[]`) ama model tipin kendisi eksik → `type_not_found` HTTP 400 → circuit breaker → 403. `admin@example.com` superAdmin OpenFGA check'i short-circuit ettiği için etkilenmiyor.
- **4-nokta digest denetim matrisi** (ADR-0023 Ek A — denetim anı / PR #845 öncesi snapshot): prod overlay == prod CANLI **her serviste** (prod GitOps-tutarlı); `overlays/test` 8/10 backend + frontend'de test CANLI'dan drift idi. PR #845 sonrası `overlays/test` test-live jenerasyona hizalı — overlay drift kapandı.
- ADR-0023 + PR-2 design Codex peer review: thread `019e40e4`.

## 4. İspatlamaz (henüz CANLI DEĞİL / kanıtlanmadı)

- **reports-403 bug HÂLÂ CANLI** — P0-c (OpenFGA `report_group` prod migration) yapılmadı. Kullanıcının bildirdiği bug açık.
- **prod backend 8 serviste hâlâ eski jenerasyon** — P0-d (8-servis prod generation promotion) yapılmadı.
- **8 test-live jenerasyon backend ledger'ı YOK** — PR #845 yalnız `overlays/test/kustomization.yaml`'ı değiştirdi; `release-candidates/platform-backend/` altında yeni digest'ler (`6175711ae208`, `6820e91e57da`, `040ddddf2163`, `a87b8c3959cd`, `5ae0c4d6ee32`, `2f80e2a98c12`, `00bcbc24f8fa`, `caf02c248bb6`) için ledger oluşturulmadı. Codex'in P0-d exit kriteri: prod overlay PR'ı açmadan önce 8 backend ledger + test evidence backfill.
- **platform-test ArgoCD app CANLI DEĞİL** — Guardrail PR-2 implement edilmedi; Codex Option A design hazır (aşağıda §5).
- Guardrail PR-3..PR-7 + P0-e (post-sync proof) yapılmadı.

## 5. Bilinen Boşluk + Sıradaki Agent P0 Aksiyon Listesi

Initiative task tracking: TaskList #1-#22 (bu session'ın local task seti). Completed: #1-#10, #12, #13, #16. Pending: #11, #14, #15, #17-#22. Sıra ADR-0023 D5 P0 onarım sırasına göre.

### P0-c (task #11) — OpenFGA `report_group` prod migration ← SIRADAKİ, kullanıcının bug'ını kapatır

Runbook: `docs/RB-openfga-report-group-migration.md` (test'te koşuldu; **prod adımı atlandı** — bu handoff'un kök bug'ı).

⚠ Runbook komutları tarihsel olarak `k3d-test` / `platform-test` / test Vault path odaklı. P0-c **prod** uygulanırken `kubectl` context, namespace ve Vault path bilinçli olarak prod'a çevrilmeli — runbook'taki literal test komutları aynen koşturulMAZ.

Adımlar:

1. Runbook'u oku — prod OpenFGA store'a `report_group` tipini içeren authorization model yaz (test modeli `01KRTJVEMAW80B2D35GN8HJDPG` referans şekil).
2. Vault `kv/platform/...` `ERP_OPENFGA_MODEL_ID` → yeni prod model ID. ESO reconcile → secret render → permission-service rollout restart (prod overlay'deki mevcut digest `6cf81e19` ile; P0-d sonra yeni jenerasyona bump eder).
3. `report_group` tuple backfill (prod).
4. **Acceptance**: prod'da non-superadmin "Halil Koçoğlu" ile `/admin/reports/hr-compensation` → 403 YOK; browser console + network temiz (HARD RULE — Deploy Sonrası Tarayıcı Console Verifikasyonu).
5. ADR-0023 D4: image-dışı artifact → P0 freeze penceresinde acil onarım runbook ile; `runtime-artifacts/openfga-model/<id>.json` ledger formalizasyonu Guardrail PR-6 (#21). P0-c sonrası en azından bir `runtime-artifacts/` kaydı bırakılması önerilir.

⚠ PROD mutation (OpenFGA store write + Vault flip + permission-service rollout). Additif değişiklik; kullanıcı bug'ı açıkça bildirdi + "çözmemiz lazım" dedi → fix yetkili. Prod OpenFGA write öncesi tek-satır kullanıcı doğrulaması ADR-0002 D-disiplini ile uyumlu.

### P0-d (task #14) — Prod backend 8-servis generation promotion (tek PR)

`kustomize/overlays/prod/kustomization.yaml` 8 backend digest bump. **Önkoşul (Codex exit kriteri)**: PR açmadan önce 8 backend `release-candidates/platform-backend/<digest>.json` ledger + test evidence backfill (§4 boşluğu).

| Servis | prod overlay ŞİMDİ | → terfi (test-validated — `overlays/test`'te) |
|---|---|---|
| api-gateway | `bb95149a3d5f...` (satır 72) | `6175711ae208...` |
| auth-service | `81499ba09e24...` (satır 64) | `6820e91e57da...` |
| core-data-service | `ec5cfd1b9ce3...` (satır 99) | `040ddddf2163...` |
| notification-orchestrator | `70491543fdc3...` (satır 210) | `caf02c248bb6...` |
| permission-service | `6cf81e19b7e3...` (satır 139) | `a87b8c3959cd...` |
| report-service | `7f3f71d67eae...` (satır 102) | `5ae0c4d6ee32...` |
| schema-service | `894e492f029c...` (satır 121) | `2f80e2a98c12...` |
| variant-service | `70106d05b75c...` (satır 96) | `00bcbc24f8fa...` |

8 hedef full digest `kustomize/overlays/test/kustomization.yaml`'da mevcut (PR #845 sonrası). Dispatch `deploy-prod-gitops.yml` (`production` environment gate). user-service (`fce3096e`) + frontend (`7e0999d1`) zaten terfi edildi (#835/#837).

### P0-e (task #15) — Post-sync proof

prod overlay == prod CANLI her serviste; OpenFGA prod model ID doğrulama; non-superadmin reports browser smoke. 4-nokta denetim matrisini güncelle.

### Guardrail train — PR-2..PR-7 (task #17-#22)

**PR-2 (task #17) — platform-test ArgoCD app activation. Codex Option A design hazır:**
- `argocd/applications/root.yaml` — `exclude` listesinden YALNIZ `platform-test.yaml`'ı çıkar; `platform-eso-test.yaml` excluded KALSIN (hâlâ `server: https://kubernetes.default.svc` in-cluster hedefliyor — un-exclude prod'a test ESO iter).
- `argocd/applications/platform-test.yaml` — `prune: true` → `false` (güvenli ilk aktivasyon; `selfHeal: true` kalır).
- YENİ runbook `docs/operations/RUNBOOKS/RB-argocd-register-test-cluster.md` — `argocd cluster add k3d-test --name test-cluster` prosedürü (canlı operatör adımı; credential git-commit edilmez).
- Kısıtlı test-runner RBAC PR-2'den çıkarıldı → ayrı PR.

**PR-3 (#18)** test deploy workflow'ları → GitOps PR (`kubectl set image` yok). **PR-4 (#19)** `check_env_drift.sh` — test+prod overlay/live drift gate. **PR-5 (#20)** promotion-lag/generation gate (`gate-evidence-check.py`). **PR-6 (#21)** image-dışı artifact ledger (`runtime-artifacts/`, `openfga-model` kind). **PR-7 (#22)** `deploy-prod-gitops.yml` artifact-dependency preflight.

## Referanslar

- ADR-0023 `docs/adr/0023-promotion-pipeline-test-overlay-authoritative.md` — canonical karar + Ek A 4-nokta matris.
- `docs/RB-openfga-report-group-migration.md` — P0-c runbook.
- Codex thread `019e40e4` — ADR-0023 + PR-2 cross-AI mimari konsensüs.
- `AGENTS.md` §3 HARD RULE — Test overlay GitOps-authoritative.

## Yeni Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-05-19-promotion-pipeline-hardening.md   # tam context
bash scripts/board-sync.sh list                                       # board claim durumu
# Sıradaki: P0-c — docs/RB-openfga-report-group-migration.md prod adımı
```
