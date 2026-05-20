# Session Handoff — 2026-05-20 — Promotion Pipeline Hardening Progress (P0 closed + PR-2/PR-5)

> Format: D28 5-alan + sıradaki agent P0 aksiyon listesi
> Önceki handoff: `docs/session-handoff-2026-05-19-promotion-pipeline-hardening.md` (P0-a/b + Guardrail PR-1 + initial 5-step P0 plan).
> Tetikleyici: HARD RULE — Session Otomatik Açma #4 (pre-completion natural break — 4 PR merged + P0 onarım kapandı, 5+ PR kalan).

## 1. Bağlam (neden bu handoff)

Önceki handoff (`2026-05-19`) P0-a + P0-b'yi kapatıp 7-PR guardrail train'i tanıtmıştı. Bu session **P0 onarım'ı tamamen kapattı + 2 guardrail PR daha landed**:

- **P0-c** OpenFGA `report_group` prod migration paralel session tarafından tamamlanmış (model `01KS15PF531R1P99BMMM7SFMV1` live, 5 servis ESO refresh + restart, tuple backfill).
- **P0-d** prod backend 7-servis generation promotion (bu session, PR #863).
- **P0-e** post-sync proof — backend reports-403 bug class structurally FIXED + verified 3 bağımsız kanıt katmanı.
- **Guardrail PR-2** platform-test ArgoCD app activation + runbook (PR #866).
- **Guardrail PR-5** promotion-lag/generation gate (PR #876).

Reports-403 bug closed at backend layer. Yan-issue: frontend reports MFE `PermissionProvider` auth race ortaya çıktı (backend fix sonrası görünür hale geldi); spawn_task chip'inde tracked.

## 2. İddia (bu session'da MERGED PR'lar — hepsi `platform-k8s-gitops`)

| PR | Başlık | Merge commit |
|---|---|---|
| #846 | docs(handoff): 2026-05-19 promotion-pipeline hardening session handoff | `6afaa6a` |
| #863 | chore(prod): P0-d — 7-service backend generation promotion (ADR-0023) | `a73f9cf` |
| #866 | feat(argocd): Guardrail PR-2 — platform-test ArgoCD app activation (ADR-0023) | `5cee52a` |
| #876 | feat(promotion): Guardrail PR-5 — promotion-lag/generation gate (ADR-0023) | `a074dbe` |

Detay:

- **#846** — D28 5-alan handoff dokümanı. Codex thread `019e40e4` AGREE (3 tur REVISE absorb sonrası).
- **#863** — `kustomize/overlays/prod/kustomization.yaml` 7 backend digest bump (api-gateway, auth, core-data, permission, report, schema, variant) test-validated jenerasyona. notification-orchestrator notify-23.3 sprint sınırına saygıdan dışarıda. 7 release-candidates ledger backfill (D29 smoke 2026-05-19T23:24:50Z all 4 tier GREEN). User explicit "Evet, merge et" approval + production environment approval gate'i geçildi.
- **#866** — root.yaml exclude listesinden YALNIZ `platform-test.yaml` çıkarıldı (eso-test in-cluster destination, excluded kaldı). `platform-test.yaml` `prune: true→false` (güvenli ilk aktivasyon). YENİ `docs/operations/RUNBOOKS/RB-argocd-register-test-cluster.md` runbook. `bootstrap/register-test-cluster-argocd.sh` default `CLUSTER_NAME k3d-test→test-cluster` align. Codex `019e42c4` 1 tur REVISE (3 finding) → AGREE.
- **#876** — `scripts/promotion/gate-evidence-check.py` +277 satır (yeni `prod_pipeline_services`, `extract_service_digests_from_render`, `latest_verified_per_service`, `check_promotion_lag`). Yeni `.github/workflows/gate-promotion-lag.yml` (schedule + dispatch + PR triggers). Codex `019e443d` 1 tur REVISE (3 finding: scope filter, per-service digest map, remove unimplemented deferral text) → AGREE.

## 3. İspatlar

- 4 PR merge commit'leri `git log origin/main` ile doğrulandı.
- **P0-d cluster verification**: 7 prod pod imageID == yeni test-validated digest byte-identical; all 1/1 Running 0 restart; ArgoCD `platform-prod` Synced/Healthy revision=a73f9cfb (PR #863 merge SHA).
- **P0-e backend acceptance** (3 bağımsız kanıt katmanı):
  - D29 prod smoke 2026-05-20T00:06:07Z all 4 tier GREEN, Zanzibar synthetic `user:1204 admin=allow OK` (Halil Koçoğlu için OpenFGA evaluation çalışıyor, type_not_found YOK).
  - report-service + permission-service prod log son 15dk: 0 adet 403/denied/type_not_found/circuit-breaker.
  - Prod OpenFGA direct query: `list-objects type=report_group user:1204` → `["report_group:FINANCE_REPORTS","report_group:SALES_REPORTS","report_group:ANALYTICS_REPORTS","report_group:HR_REPORTS"]`. userId 1204 4 grup için ALLOW tuple sahibi.
- **PR #876 self-validation**: kendi workflow'u kendi PR'ında koştu + PASS (post-P0-d state 0 lag, exit=0).
- Cross-AI Codex AGREE 4 PR için tutarlı (`019e40e4`, none-of-the-above for handoff doc, `019e42c4` for PR-2, `019e443d` for PR-5).

## 4. İspatlamaz (henüz CANLI DEĞİL / yan-issue olarak track'li)

- **Frontend reports MFE auth race**: backend fix sonrası ortaya çıktı. Non-superadmin "Halil Koçoğlu" `/admin/reports/hr-compensation` → `PermissionProvider AuthNotReadyError` race ile widget'lar hiç render olmuyor (0 adet 403 + 0 adet reports endpoint isteği). `/home` aynı kullanıcı için çalışıyor (Keycloak session valid). spawn_task chip oluşturuldu (platform-web kapsamı, ayrı sprint).
- **PR-2 operator action pending**: `argocd cluster add k3d-test --name test-cluster` runbook (`docs/operations/RUNBOOKS/RB-argocd-register-test-cluster.md`) henüz koşulmadı. PR-2 manifest merged; `platform-test` Application Unknown/Error kalıyor target cluster registered değil. **PR-3 bu operator adımına bağlı** — cluster registered olmadan PR-3 merge'i test deploys async breaks.
- Guardrail PR-3, PR-4, PR-6, PR-7, PR-8 yapılmadı.

## 5. Bilinen Boşluk + Sıradaki Agent P0 Aksiyon Listesi

Initiative task tracking: TaskList #18-#23 (5 PR + 1 PR-8). Completed bu session: #11 (P0-c), #14 (P0-d), #15 (P0-e), #16 (PR-1), #17 (PR-2), #20 (PR-5). Pending: #18, #19, #21, #22, #23.

### Önceliklendirme

| # | PR | Engelleyen | Tahmini effort | Önerilen sıra |
|---|---|---|---|---|
| #23 | **PR-8** live-mutation board-claim hardening | bağımsız | M | **1 (önceliklendirilebilir)** — bu session 2 kez paralel session worktree-branch switch yaşadık; PR-8 bunu adresliyor + sonraki PR'lar için ortam korur |
| #19 | PR-4 `check_env_drift.sh` test+prod overlay/live drift gate | bağımsız | M | 2 — `check_prod_drift.sh` mevcut; test-mode wrapper + CI gate |
| #21 | PR-6 image-dışı artifact ledger (`runtime-artifacts/openfga-model/<id>.json`) | bağımsız | M-L | 3 — P0-c'nin formalizasyonu; PR-7'nin ön-koşulu; PR-5'in "promotion-deferred:" follow-up'ını da kapsayabilir |
| #18 | PR-3 test deploy workflow'ları → GitOps PR (no `kubectl set image`) | **operator cluster-add gated** | L | 4 — operator `docs/operations/RUNBOOKS/RB-argocd-register-test-cluster.md` koştuktan sonra; `deploy-backend-testai.yml` (467 satır) ve `deploy-testai.yml`'da yeni `sync-test-overlay-pr` path (#841'den) zaten var, eski `kubectl set image` path'i kaldırılır |
| #22 | PR-7 `deploy-prod-gitops.yml` artifact-dependency preflight | PR-6 sonrası | M | 5 — PR-6'nın ledger formatı belirlendikten sonra |

### PR-8 (önerilen #1) — bağlam

Bu session paralel session **2 kez** worktree branch'imi switch'ledi (`roadmap-858-metrics-server-test-fix-v2`, `roadmap-858-metrics-server-test-destination-fix`) → local edits 2 kez kayboldu (PR-2 absorb commit, bootstrap script edit). Origin'deki branch'ler sağlamdı, recovery yapıldı ama overhead yarattı.

Mevcut `scripts/board-sync.sh` lease/heartbeat var ama worktree-level isolation yok. PR-8 yaklaşımı: ya per-session worktree (her session kendi `git worktree add`), ya da claim öncesi worktree branch lock check (lease+heartbeat'e ek olarak).

### PR-3 operator action (PR-3 unblock için)

```bash
# docs/operations/RUNBOOKS/RB-argocd-register-test-cluster.md Step 2:
ssh halil@staging-sw '
  argocd cluster add k3d-test \
    --name test-cluster \
    --upsert \
    --yes
'
# Verify:
ssh halil@staging-sw 'argocd cluster list 2>&1 | grep test-cluster'
ssh halil@staging-sw 'kubectl --context k3d-prod -n argocd get application platform-test \
  -o jsonpath="status.sync={.status.sync.status} status.health={.status.health.status}\n"'
# Beklenen post: status.sync=Synced status.health=Healthy
```

## Referanslar

- ADR-0023 `docs/adr/0023-promotion-pipeline-test-overlay-authoritative.md` — canonical karar + Ek A 4-nokta matris.
- Önceki handoff `docs/session-handoff-2026-05-19-promotion-pipeline-hardening.md`.
- Codex threads (bu session): `019e40e4` (handoff doc), `019e42c1` (P0-e closure), `019e42c4` (PR-2 implementation), `019e443d` (PR-5 implementation).
- spawn_task chip: "Fix reports MFE PermissionProvider auth race" (platform-web kapsamı).

## Yeni Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-05-20-promotion-pipeline-progress.md   # bu doküman
bash scripts/board-sync.sh list                                       # board claim durumu
# Geçerli sıra (PR-8 sonrası — bkz. aşağıdaki "Update" notu):
#   PR-4 → PR-6 → operator cluster-add → PR-3 → PR-7
```

---

## Update 2026-05-20 — PR-8 Was Already Merged But Missing From Original Handoff Content (omission correction)

Bu handoff doc'u `da9128a` ile merge edildiğinde PR-8 (`ac5a3b2`) **zaten merge edilmişti** (`git merge-base --is-ancestor ac5a3b2 da9128a` ✓; commit dates: PR-8 `2026-05-20T10:45:24+03:00`, handoff `2026-05-20T10:52:21+03:00` — yani PR-8 doc'tan ~7 dk önce landed). Ancak doc'un §2 İddia tablosu PR-8'i içermiyor ve §5 priority tablosu PR-8'i hâlâ "yapılmadı + #1 önerilen" olarak listeliyor. Bu Update bölümü o **omission**'ı düzeltir.

> **Reader note**: Aşağıdaki §4/§5 PR-8 satırları (PR-8 = pending/öncelik #1) **tarihsel içerik olarak bırakıldı**; geçerli durum bu Update bölümüdür.

### PR-8 — MERGED

| PR | Başlık | Merge commit |
|---|---|---|
| #883 | feat(board): Guardrail PR-8 — live-mutation require-claim guard (ADR-0023) | `ac5a3b2` |

Detay:

- **#883** — `scripts/board/require-claim.sh` YENİ (201 satır, +x): fail-closed live-mutation guard; `BOARD_SESSION_ID` ↔ body `claim_session` + `claim_worktree`/`claim_branch` identity match + `expires_at > now`. Empty identity fields **FAIL** (silently skipped değil). Distinct unblock advice: `LEASE_EXPIRED` flag — expired ise "re-claim" (heartbeat refuses), valid-lease mismatch ise "switch to correct worktree/branch". Exit 0/1/2.
- `scripts/board-sync.sh` L50 fix: `CLAIM_TTL_HOURS="${CLAIM_TTL_HOURS:-2}"` + `^[0-9]+$` numeric guard. Önceki hardcoded `=2` env override'ı yutuyordu; `CLAIM_TTL_HOURS=6 board-sync.sh claim ...` artık honored (uzun P0 işleri için).
- `docs/board-protocol.md` §8.1 sub-section: trigger (lease silent expire pattern), kullanım örneği, `CLAIM_TTL_HOURS=6` override notu, scope-out (worktree mkdir lock + per-session worktree convention deferred to PR-8 follow-up Opsiyon B/C).
- Codex `019e444d` 1 tur REVISE (3 finding: TTL env honor, empty identity fail-closed, expired-vs-mismatch distinct advice) → AGREE.
- Bu sırada paralel session worktree branch'imi 2 kez switch'ledi; bu pattern PR-8'in adreslediği problemin **canlı kanıtı** (PR-8 öncesi sürtünme).

### Geçerli Kalan Sıra (effective remaining sequence)

PR-8 completed olduğu için önerilen sıra:

| # | İş | Engelleyen | Effort |
|---|---|---|---|
| 1 | **PR-4** `check_env_drift.sh` — test+prod overlay/live drift gate | bağımsız | M |
| 2 | **PR-6** image-dışı artifact ledger (`runtime-artifacts/openfga-model/<id>.json`) | bağımsız | M-L |
| 3 | **Operator cluster-add** `argocd cluster add k3d-test --name test-cluster --upsert --yes` (RB-argocd-register-test-cluster.md Step 2) | — | XS |
| 4 | **PR-3** test deploy workflow'ları → GitOps PR (no `kubectl set image`) | operator cluster-add (#3) | L |
| 5 | **PR-7** `deploy-prod-gitops.yml` artifact-dependency preflight | PR-6 (#2) | M |

### TaskList sync notu

Bu session başında 23 task'tan 7'si pending'di; bu session +5 completed. **Şu anki pending durum**: #18 (PR-3), #19 (PR-4), #21 (PR-6), #22 (PR-7). PR-8 (#23) ve PR-5 (#20) completed olarak işaretli — TaskList tutarlı.

### Paralel session içeriği (referans)

Bu repo'da aynı gün başka session **multi-initiative closure wave** yaptı (8 PR merge, doc: `docs/session-handoff-2026-05-20-multi-initiative-closure.md`). İçerik bu promotion-pipeline initiative'inden bağımsız (HR Compensation polish + #847 OpenFGA prod migration formal kayıt + #842 PR-A2 cross-ai-audit hardening + M365 v2 verify + M5/M6a acceptance). Cross-reference: P0-c (#847 OpenFGA prod migration) bu session'da `paralel session tarafından tamamlanmış` olarak referans aldığım — kanıtı multi-initiative doc'unda detaylı.

### Codex thread referansları (PR-8 dahil)

- `019e40e4` (handoff doc #846)
- `019e42c1` (P0-e closure)
- `019e42c4` (PR-2 #866 implementation)
- `019e443d` (PR-5 #876 implementation)
- `019e444d` (PR-8 #883 implementation)
- `019e44ad` (bu Update bölümü Codex peer review — REVISE→AGREE)

### Yeni session İlk Komutu (güncel)

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git pull --rebase origin main
cat docs/session-handoff-2026-05-20-promotion-pipeline-progress.md   # bu doc + bu Update bölümü
bash scripts/board-sync.sh list                                       # board claim durumu
# İlk iş: PR-4 (check_env_drift.sh) — bağımsız + lokalde başlanabilir.
```
