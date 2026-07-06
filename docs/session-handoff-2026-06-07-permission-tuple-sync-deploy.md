# Session Handoff — 2026-06-07 — permission-service OpenFGA tuple-sync consolidation + deploy

> Format: D28 5-alan (Bağlam / İddia / İspatlar / İspatlamaz / Bilinen boşluk + P0).
> Bu oturum: kullanıcının verdiği **#1275 → #84 → #1274-deploy** sırası + fleet-health audit.

---

## 1. Bağlam (bu oturumda ne yapıldı)

Önceki oturum AG-028 OpenFGA revoke-orphan + #1274 grant-add (PR #502) ile permission-service granule tuple
sync'ini düzeltmiş, geriye **son fail-SİLENT yol** (`PermissionService.syncTuplesToOpenFga`) + onun **testai'ye
deploy edilmemiş olması** kalmıştı. Bu oturum o iki kapağı kapadı (Option A fold + cumulative deploy) ve
testai backend fleet'inin gitops-desired ↔ live senkronunu doğruladı.

- **#1275** — son fail-silent legacy OpenFGA yazma yolunu sil, fail-loud aggregate TupleSyncService'e fold (Option A end-state).
- **#84** — agent local-user mutation guards (RID 500-504 + last-admin lock) — paralel session'da landed, doğrulandı.
- **#1274 deploy** — #1272+#1274+#1275 tek image'da testai'ye rollout + D29 acceptance.
- **Fleet audit** — 10 backend servisin gitops-desired digest ↔ live pod imageID senkronu.

---

## 2. İddia (MERGED PR'lar)

| PR | Repo | Başlık | Merge | Cross-AI |
|---|---|---|---|---|
| **#503** | platform-backend | `fix(permission #1275): fold legacy tuple sync into fail-loud TupleSyncService` | 815308a | Codex 019ea233 plan PARTIAL→AGREE + post-impl AGREE |
| **#1328** | platform-k8s-gitops | `chore(deploy): bump permission-service to sha-815308a (#1274+#1275)` | 8307d55b | Codex 019ea233 (source image) |

Issue durumu: **#1275 CLOSED** (completed), **#1274 CLOSED** (önceki oturum + bu deploy evidence comment).

### #1275 değişim özeti (PR #503)
- `PermissionService.syncTuplesToOpenFga` (fail-silent per-role legacy write/delete) **silindi**.
- Yeni `TupleSyncService.refreshFeatureAndLegacyTuplesForUser` composite (AccessRoleService ordering: refresh→writeLegacy→tek bump).
- `assignRole` / `updateAssignment` → GAIN reconcile (composite); `revokeRole` → `refreshFeatureTuples` spare-set (latent multi-role over-delete bug fix).
- `PermissionService` artık `OpenFgaAuthzService`'e **bağımlı değil** (compile-time guard — direct writeTuple/deleteTuple geri gelemez).
- Test: 383/383 unit (InOrder + fail-loud propagation + updateAssignment role-swap + revoke never-writeLegacy) + yeni TupleSyncServiceTest composite + real-FGA Testcontainer IT.

---

## 3. İspatlar (canlı / build kanıtı)

- **Source CI**: PR #503 tüm check yeşil (383/383 unit + real-FGA Testcontainer IT). Codex post-impl AGREE.
- **Image build**: run 27094209115 `Build + Push permission-service` success; GHCR `sha-815308a` (`sha256:f3177b4a9966…`). Co-job core-data transient Docker Hub timeout → rerun success (main CI yeşil).
- **gitops CI**: PR #1328 boundary declaration (lokal validator PASS) + cross-ai-audit (field-format fix sonrası success 27094422051) + mergeable=clean.
- **D29 LIVE (k3d-test / platform-test)**:
  - **Up + parity**: `deployment "permission-service" successfully rolled out`; pod `permission-service-74f5484cdd-rlrzj` Running 1/1, imageID == `@sha256:f3177b4a9966…` (birebir).
  - **Functional**: `Ready=True / ContainersReady=True` (readiness `/actuator/health/readiness` mgmt:8081 UP); `Started PermissionServiceApplication 47.4s`; public gateway `GET /api/v1/authz/me` → 401, `POST /api/v1/permissions/check` → 401 (doğru shape).
  - **OpenFGA live integration**: deployed pod store `01KPP0CFP4G82K42Y6NYSPT4JF`'i sorguladı, populated.
- **Fleet drift audit (10/10 OK, drift=0)**: her backend servisin deployment spec digest'i == live pod imageID (api-gateway, auth, core-data, endpoint-admin, notification-orchestrator, permission, report, schema, user, variant). testai backend fleet tam senkron, stuck rollout yok.

---

## 4. İspatlamaz (pending acceptance / residual)

- **Live new-persona granule-grant smoke**: assignRole → tuple-appears uçtan uca canlı senaryo **koşulmadı** (Keycloak admin-JWT orchestration + testai state mutation + cleanup gerektirir). Davranış **deployed image'ın kaynak commit'inde (815308a) real-FGA Testcontainer IT ile kanıtlı** (mock değil — gerçek OpenFGA + gerçek PG; digest parity ile aynı image); risk **düşük** (değişiklik zaten-canlı fail-loud path'lere yönlendiren refactor).
- **#84 agent**: paralel session'da source-landed; bu oturum doğruladı, kendi PR'ını açmadı.

---

## 5. Bilinen boşluk + Sıradaki Session için P0 Aksiyon Listesi

### Canonical board durumu (Project #2 platform Roadmap)
- **Eligible (Todo)**: yalnız #760 [Faz 23][M8] Multi-tenant Trigger Gate — **operatör/zaman-bağımlı** (M7 v1 30-gün stable + R10 mitigation; harness PR-1..5 DONE).
- **In Progress (claim'siz)**: #751 (Notification Orchestration — DORMANT), #765/#768/#769/#770/#771/#772/#773 (R6-R22 risk-tracking).
- **Present, küçük, tek-başına-agent-doable code slice YOK** — kalan iş büyük epic / operator-bound / future-dependent.

### P0 — operatör/zaman gates (agent fast-forward edemez)
1. **#760 M8 / #99 C3** — M7 v1 **30-gün mismatch=0** observation penceresi (harness recording rules + evidence script DONE). Operatör: pencere dolunca `scripts/...` evidence çalıştır → C3 Done → M8 gate açılır.
2. **D30 atomic cutover** — prod cutover irreversible, operator açık karar (ayrı runbook).
3. **AG-029 self-update** — prod trusted-tier signing cert + rollout (operator-bound; lab churn = security gate doğru çalışıyor).

### P1 — resumable threads (fresh-context session önerilir; strateji kullanıcı kararı)
4. **#751 Notification Orchestration** — 2026-05-14'ten beri **bilerek DORMANT**. Resume = Faz 22.5/21.1'den Faz 23'e re-prioritization (kullanıcı sinyali gerek). Canonical: ADR-0013 + RB-faz-23-charter + docs/notify/README.md.
5. **Faz 23 agent-doable risk mitigations** — R16 (Prometheus federation cardinality recording-rule), R21 (provider rate-limit retry), R22 (GHCR outage pull-fallback). R6/R15/R17 operator/legal/strategic (agent dışı).
6. **#768 R14 bundle size gate** — Notification in-app inbox/preference UI (23.4+23.5) gelince; şu an present regression yok.

### P2-P3 — deferred (önceki handoff'lardan taşınan)
- agent #55 PR1b, 22.5.8 #477, #1164 Keycloak, Faz 21.1 A6 #476 (tenant_id DROP — operator-gated M7/Inv-4/R10/D30).

---

## Sıradaki Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin && git log origin/main --oneline -3
cat docs/session-handoff-2026-06-07-permission-tuple-sync-deploy.md   # bu doc
bash scripts/board-sync.sh list                                       # canonical board
```

Karar: P1 (#751 resume / risk mitigation) bir stratejik seçim — kullanıcı yönlendirmesiyle başlatılır.
P0 gates operatör/zaman bağımlı (agent bekleme penceresini fast-forward edemez).
