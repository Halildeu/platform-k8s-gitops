# Session Handoff — 2026-06-01 — Faz 22.5.3C Truth Refresh + BE-028 LIVE Closure

> Format: D28 5-alan (Bağlam · İddia · İspatlar · İspatlamaz · Bilinen Boşluk + P0 Aksiyon Listesi)

## 1. Bağlam (bu oturumda ne yapıldı)

Önceki session (BE-028 install-audit reader live verify + #348 gitops convergence) doygunluk noktasında handoff edilmişti. Bu session iki ana iş zincirini kapattı:

**Zincir A — BE-028 install-audit ledger closure**:
- PR #1156 (önceden merged #1154 PR-4) BE-028 cross-dependency cross-AI audit comment olarak GitHub'a kayıt.
- Cluster image triple-match `fd272365` (#348) doğrulandı; `f5b8f744` (#348) ⊃ `6a21180f` (#347 BE-028 commit) ancestry verified (`git merge-base --is-ancestor 6a21180f f5b8f744` → exit 0).
- Browser teyit önceki session'da 20:39'da yapılmıştı; bu session'da Chrome MCP pair handshake gerçekleşmediği için browser re-verify atlandı (kanıt zaten kapsamlı).

**Zincir B — Faz 22.5.3C truth refresh discovery + LIVE evidence**:
- Codex MCP pre-impl iter (`019e801e`) sırasında kritik bulgu: kullanıcının "Sprint B planına geç" dediği AG-036 + BE-024 + BE-025 iş paketleri **zaten merged** on `origin/main` of platform-agent + platform-backend (PRs #38/#40/#334/#335/#336). Plan + state docs hâlâ "TODO" diyordu — stale.
- Sprint B pivot: implementation yerine **truth refresh** + **LIVE acceptance evidence chain** kapatma.
- Flyway ledger query (testai cluster) V18 (BE-024) + V19 (BE-025) + V20 (AG-036-be) `success=true` 2026-05-30 doğrulandı.
- Cluster-internal API smoke 4/4 endpoint için HTTP 401 (no JWT) — endpoint reachable + Spring Security admin auth-gate enforce, no 500 / no 404.
- BE-025 audit handle source-code review: `EndpointComplianceEvaluation` row IS the audit handle (Codex `019e7623` (d) intentional, no dedicated alert-row needed). Codex must-fix #5 cevaplandı.
- Admin JWT mint path: Keycloak admin password rotation operator-bound (secret file 2026-04-20 stale, master realm `invalid_grant`). Board issue #1164 ile gelecek session'a aktarıldı.

## 2. İddia (MERGED PR'lar + Board issue'lar + audit comment)

| Aksiyon | Sonuç | Codex Thread |
|---|---|---|
| **PR #1157** | docs(state): BE-028 install-audit LIVE + #348 gitops convergence | `019e8007` iter-1 REVISE → iter-2 AGREE |
| **PR #1158** | docs(truth): Faz 22.5.3C AG-036+BE-024+BE-025 already SOURCE-MERGED | `019e801e` iter-1/2 REVISE → iter-3 AGREE |
| **PR #1159** | docs(truth): V18/V19/V20 Flyway apply verified live on testai 2026-05-30 | `019e801e` iter-4 REVISE → iter-5 AGREE |
| **PR #1161** | docs(truth): BE-025 alert-row check resolved (Codex mf #5) | `019e801e` iter-6/7 REVISE → iter-8 AGREE |
| **PR #1162** | docs(truth): API service reachability + auth-gate verified | `019e801e` iter-9 REVISE → iter-10 AGREE |
| **PR #1156 comment** | BE-028 cross-dependency acknowledgment | n/a |
| **Issue platform-web #719** | WEB-014E (outdated/diff/prohibited UI surfaces) | n/a |
| **Issue platform-agent #44** | AG-037 (Windows Update / hotfix posture probe) | n/a |
| **Issue platform-k8s-gitops #1164** | Faz 22.5.3C admin JWT path (operator-bound) | n/a |

5 PR merged + 1 audit comment + 3 board issue + Codex `019e801e` thread **10-iter cross-AI consensus convergence**.

## 3. İspatlar (canlı/build sanity)

### 3.1 Cluster image triple-match (BE-028 + Faz 22.5.3C aggregate)

- Pod `endpoint-admin-service-…-mbvj2` 1/1 Running on imageID `fd272365…`
- = GHCR manifest digest
- = gitops kustomize pin (`kustomize/overlays/test/kustomization.yaml` endpoint-admin digest `sha256:fd27236541bb048216a30867d4cd7608fee0a3f107835932a20d1d97d3fd866c`)
- Backend `main` ancestry: `f5b8f744` (#348) ⊃ `6a21180f` (#347 BE-028) ⊃ `f8e2cb7a` (#346) ⊃ ... ⊃ `7f8c1a90` (#336 AG-036-be) ⊃ `7bb0340e` (#335 BE-025) ⊃ `d154ac7a` (#334 BE-024)
- Backend `git merge-base --is-ancestor 6a21180f f5b8f744` → exit 0
- `#347 → #348` diff = `common-export/pom.xml` + `endpoint-admin-service/pom.xml` only (commons-compress 1.25.0 pin for poi-ooxml)

### 3.2 Flyway live ledger (PR #1159 evidence)

```sql
SELECT version, description, success, installed_on::date
FROM endpoint_admin_service.endpoint_admin_flyway_history
WHERE version::int BETWEEN 17 AND 21
ORDER BY version::int;

 version |                description                | success | installed_on
---------+-------------------------------------------+---------+--------------
 17      | endpoint device health                    | t       | 2026-05-29
 18      | endpoint software inventory state history | t       | 2026-05-30
 19      | endpoint prohibited software rules        | t       | 2026-05-30
 20      | endpoint outdated software                | t       | 2026-05-30
 21      | catalog detection rule agent schema       | t       | 2026-05-31
```

Captured via: `ssh halil@staging-sw 'docker exec platform-pg-test psql -U platform -d endpoint_admin -c "..."'`.

Schema-qualified tables verified present in `endpoint_admin_service` schema:
- `endpoint_software_inventory_state_history` (V18 / BE-024)
- `endpoint_prohibited_software_rules` (V19 / BE-025)
- `endpoint_outdated_software_packages` + `endpoint_outdated_software_snapshots` (V20 / AG-036-be)

### 3.3 API service reachability + Spring Security admin auth-gate (PR #1162 evidence)

Cluster-internal smoke (no JWT, expecting 401 = admin chain enforce):

| Admin URL | HTTP code |
|---|---|
| `/api/v1/admin/endpoint-devices/{id}/software-inventory/diff` | **401** |
| `/api/v1/admin/endpoint-devices/{id}/software-inventory/history` | **401** |
| `/api/v1/admin/endpoint-devices/{id}/outdated-software/latest` | **401** |
| `/api/v1/admin/endpoint-devices/{id}/prohibited-software` (corrected from `/findings` per Codex iter-9) | **401** |

Significance (narrowed per Codex iter-9): proves service reachability + Spring Security admin auth-gate enforce. Does **NOT** prove route-level controller-mapping or payload-shape acceptance (under SecurityConfig admin chain enforces 401 before handler mapping; non-existent admin URLs would also return 401).

### 3.4 BE-025 audit handle source-resolved (PR #1161 evidence)

- `ProhibitedSoftwareFindingService.java` reads `evidence.matchedItems.prohibitedInstalled` projection from the latest persisted `EndpointComplianceEvaluation` row.
- `EndpointComplianceService.java` persists the row.
- `ComplianceInventoryEventListener.java` uses `@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)` after `SoftwareInventorySnapshotPersistedEvent` for inventory-driven re-evaluation.
- `ComplianceInstallAuditEventListener.java` handles the separate install-audit-driven re-evaluation path (`EndpointInstallAuditRecordedEvent`).
- Doc-string: "a GET that recomputes would let the device compliance state and this response diverge and would be expensive + side-effecting" (Codex `019e7623` (d) intentional).
- No dedicated alert-row needed — the compliance evaluation row IS the audit handle.

### 3.5 Forensic archive tags

- `archive/2026/05/docs-current-state-be028-348-convergence-pr1157` (pushed)
- `archive/2026/05/docs-truth-refresh-be024-025-ag036-pr1158` (pushed)
- `archive/2026/05/docs-flyway-live-evidence-be024-025-ag036-pr1159` (pushed)
- `archive/2026/05/docs-be025-audit-handle-resolved-codex-mf5-pr1161` (pushed)
- PR #1162 cleanup partial (shared worktree blocker — paralel session `roadmap-1085-pr-evidence-pat-fallback` branch + dirty `.github/workflows/board-pr-evidence.yml`). GitHub merge log (`cbd5bd02`) audit handle taşıyor.

## 4. İspatlamaz (henüz kanıtlanmamış)

### Faz 22.5.3C residual acceptance

- **Authenticated 200 + JSON shape smoke** (admin JWT path) — Keycloak master admin password rotation operator-bound. Board issue [#1164](https://github.com/Halildeu/platform-k8s-gitops/issues/1164). Mevcut: HTTP 401 auth-gate enforce only.
- **WEB-014E** outdated/diff/prohibited UI surfaces — backend tüm endpoint'leri hazır; web view kuyrukta. Board issue [platform-web #719](https://github.com/Halildeu/platform-web/issues/719).
- **HALILKOOLUB735 endpoint AG-036 e2e** — agent binary distribution operator-bound; `COLLECT_INVENTORY{includeOutdatedSoftware:true}` `winget upgrade --include-returning-apps --source winget` probe → backend ingest → DB row → API read e2e zinciri henüz çalıştırılmadı.
- **AG-037 Windows Update / hotfix posture probe** — TODO. Board issue [platform-agent #44](https://github.com/Halildeu/platform-agent/issues/44).

### Önceki session'lardan devreden + bu session'da dokunulmadı

- **WEB post_verification surfacing chip** — ayrı spawn session `platform-web` deposunda; SATISFIED/UNSATISFIED/UNKNOWN badge + i18n key `endpointAdmin.drawer.install.reasonCode.winget_package_query_inconclusive`. Bu session'da duplicate yapılmadı (HARD RULE).
- **Browser drawer 7-Zip SATISFIED visual re-confirm** — Chrome MCP extension pair handshake gerçekleşmedi (`list_connected_browsers` boş; 6 retry + 20s wait yetersiz). DB+API+source+console kanıtları zaten kesin; visual re-confirm nice-to-have.
- **7-Zip lifecycle smoke #1** — `be021-smoke-7zip` UNKNOWN durumu beklenen (Session-0 WINGET-confirm-only path). Bu, BE-028 tri-state modelinin doğru cevabıdır.

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### P0 — Operator action gerek (agent autonomous yapamıyor)

1. **`platform-k8s-gitops #1164` — Keycloak admin password rotation**.
   - Tetik: Faz 22.5.3C full payload 200 smoke (admin JWT path) ihtiyacı.
   - Operator yolu: (a) `kc_admin_password` secret file'i mevcut admin password ile güncelle, VEYA (b) yeni admin persona mint et (`kcadm.sh` ile veya Keycloak UI'dan), `module:endpoint-admin can_view` role attach + bir kerelik JWT hand-off.
   - Sonrası: agent autonomous — `ssh halil@staging-sw 'JWT=<...> && kubectl exec deploy/api-gateway -- curl -H "Authorization: Bearer $JWT" http://endpoint-admin-service:8096/api/v1/admin/endpoint-devices/<uuid>/<endpoint>'` × 4.

2. **HALILKOOLUB735 endpoint AG-036 e2e binary distribution**.
   - Tetik: Faz 22.5.3C agent-side LIVE acceptance.
   - Operator yolu: post-PR40 agent binary (`e64c131` `UpgradeTruncated` fix dahil) HALILKOOLUB735 endpoint'ine dağıt (mevcut pattern: AG-030..033 quartet binary distribution).
   - Sonrası: `COLLECT_INVENTORY{includeOutdatedSoftware:true}` payload bit → backend ingest → DB row in `endpoint_admin_service.endpoint_outdated_software_packages` → API read.

### P0 — Agent autonomous (yeni session başlangıcı için en hazır iş)

3. **`platform-web #719` WEB-014E** — outdated/diff/prohibited UI surfaces (agent autonomous).
   - Yeni session ilk komut: `cd /Users/halilkocoglu/Documents/platform-web && cat ../platform-k8s-gitops/docs/session-handoff-2026-06-01-faz225-3c-closure-be028-live.md`
   - Codex pre-impl iter (`mcp__codex__codex`) ile plan-time istişare → AGREE → impl direkt başla (HARD RULE Plan Consensus Autonomy).
   - Reuse pattern: `SoftwareCatalogTab.tsx` "Kur" button + `useListInstallAuditsQuery` + drawer audit panel; aynı `endpoint-admin` module path; i18n TR + EN; tenant-scoped no-existence-leak (BE-024 sentetik `appKey` keying).
   - Acceptance: per-device drawer Outdated/Diff/Prohibited tabs + cross-device list view; HARD RULE No identifier leak + browser smoke deploy verify + Codex post-impl iter + CI green + normal squash merge.

4. **`platform-agent #44` AG-037** — Windows Update / hotfix posture probe (agent autonomous).
   - Branch hygiene call-out: local `platform-agent` worktree `feat/agent/AG-038-agent-self-diagnostics-probe` upstream-gone + PR #40 (`e64c131`) öncesi parser; yeni AG-037 branch **`origin/main`'den** oluşturulmalı, bu stale branch'tan değil.
   - Reuse pattern: AG-030..033 posture quartet + AG-025H lightweight/full guard + `COLLECT_INVENTORY{includeHotfixPosture:true}` opt-in + identifier-leak-free.
   - Çıktılar: `endpoint_hotfix_posture_history` V22 migration + `AdminEndpointHotfixPostureController` + `docs/faz-22-hotfix-posture-contract-v1.md` (gitops) + browser smoke yok (agent-only) + Codex iter + CI green + merge.

### P1 — Faz 22.5 quick-wins kuyruğu (faz-22 plan §9 satır 16)

5. **AG-038 Agent self-diagnostics** — `67bd4ba` (#39) zaten merged on `platform-agent origin/main`. **Truth refresh PR** gerekli (mevcut plan + state docs hâlâ "TODO" diyebilir).
6. **AG-039 / AG-040** — service + exposure quick wins. Faz 22.5 §3 row 188+. Plan-time iter ile scope.

### P2 — Strategic gates (uzun kuyruk)

7. **22.5.4 First Install Pilot 7-Zip lifecycle smoke** — `be021-smoke-7zip` operator-bound (HALILKOOLUB735 lab; runbook `RB-faz22-7zip-lifecycle-smoke.md` hazır).
8. **22.5.5 WEB-015 endpoint report / CSV export** — RBAC-controlled.

## Yeni Session İçin İlk Komutlar

```bash
# Standart başlangıç (handoff + truth ledger oku)
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-06-01-faz225-3c-closure-be028-live.md
git log --oneline -10 origin/main

# Board claim öncesi
gh issue view 719 --repo Halildeu/platform-web    # WEB-014E
gh issue view 44 --repo Halildeu/platform-agent   # AG-037
gh issue view 1164 --repo Halildeu/platform-k8s-gitops  # admin JWT operator

# WEB-014E impl başlatma örneği
cd /Users/halilkocoglu/Documents/platform-web
git fetch origin && git checkout -b feat/web-014e-outdated-diff-prohibited-ui origin/main
# → Codex pre-impl iter (mcp__codex__codex)
```

## Codex Thread References (continuity için)

- **`019e7f93-65ce-7b23-a9ab-28643e341afc`** — BE-028 gitops resolution-A consultation (prior session)
- **`019e8007-e424-73d3-be76-3644e03704f4`** — BE-028 doc delta (PR #1157) cross-AI review
- **`019e801e-8e10-70d1-826e-5da09c329c7c`** — Faz 22.5.3C truth refresh + Flyway evidence + BE-025 audit handle + API smoke (PRs #1158/#1159/#1161/#1162, 10-iter consensus)
- **`019e7623`** (referenced) — BE-025 design intent (`ProhibitedSoftwareFindingService` read-from-evaluation-row not recompute)

## Linked Truth Ledger

- `docs/state/current-state.md` top 3 Live Delta blocks:
  1. Faz 22.5.3C Outdated/Diff/Prohibited SOURCE-MERGED truth refresh (2026-06-01)
  2. BE-028 install-audit chain LIVE + #348 gitops convergence (2026-05-31 → 2026-06-01)
  3. Faz 22.5 install lifecycle source-MERGED + AG-026B/C/D persist + HALILKOOLUB735 live verify (2026-05-29 PM)
- `docs/faz-22-software-deployment-plan.md` §0.1bis row 76 + §3 main packet table rows 170-172 + §9 numbered item 10

---

**Per HARD RULE No Closure Language**: bu handoff doc bir kapanış değil, **yeni session devamı için açık bir kapı**. Kullanıcı müsait olunca P0 listesinden sıradaki işe geçilir.

**Per HARD RULE Session Otomatik Açma**: yeni session açıldığında ilk komut bu doc'u okumak; kullanıcı `cd` + `cat` adımını manuel atmak zorunda değil.
