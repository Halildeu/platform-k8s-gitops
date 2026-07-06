# Session Handoff — 2026-05-28/29 (Faz 22.5.2 hardware quick wins source slice CLOSED)

> Format: D28 5-alan + sıradaki agent action list
> Predecessor: docs/state/current-state.md
> Codex thread chain (this session): `019e7007`, `019e709c`, `019e70c1`, `019e70ce`

## 1. Bağlam (bu oturumda ne yapıldı)

Bu oturum açıldığında BE-022 V14 testai'de LIVE yeni-deploy edilmişti
(pod `endpoint-admin-service-85fcbf5c45-jmvll` Running 1/1, Flyway v14
applied, Hibernate validate clean). Kullanıcı sırasıyla sıralı adımlar
istedi: browser smoke + 7-Zip lifecycle smoke + AG-035 + WEB-013 + PM
truth refresh.

Sıralı adımlar tek otonom session içinde Codex MCP istişareli olarak
yürütüldü; her büyük slice plan-time + post-impl cross-AI review iter
chain ile geçirildi.

## 2. İddia (MERGED PR'lar)

| Slice | Repo | PR | Commit | Merge time | Codex iter |
|---|---|---|---|---|---|
| AG-035 Windows agent hardware probe | platform-agent | [#24](https://github.com/Halildeu/platform-agent/pull/24) | `ef83531c` | 22:41Z | plan-time AGREE → post-impl REVISE → AGREE iter-1 (019e709c) |
| BE-022Q hardware inventory query API | platform-backend | [#325](https://github.com/Halildeu/platform-backend/pull/325) | `4ff2ceb4` | 23:01Z | plan-time AGREE (7 must-fix) → post-impl AGREE iter-1 (019e70c1) |
| Gitops bump BE-022Q sha-4ff2ceb | platform-k8s-gitops | [#1124](https://github.com/Halildeu/platform-k8s-gitops/pull/1124) | `f29d7b17` | 23:26Z | n/a (small overlay diff; Codex review skipped per bump-PR pattern) |
| WEB-013 frontend hardware view | platform-web | [#700](https://github.com/Halildeu/platform-web/pull/700) | `26e68658` | 23:32Z | plan-time PARTIAL → post-impl REVISE → AGREE iter-2 (019e70ce) |

Plus BE-022 V14 source (PR #324 `931b6079`) + gitops bump (PR #1122 `b7219716`)
landed earlier this session per predecessor handoff.

## 3. İspatlar

### Cluster live state (BE-022Q on testai)

- `kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=endpoint-admin-service -o wide`
  → `endpoint-admin-service-579fbb5db4-bk5wd  1/1  Running  0  107s`
- `kubectl ... get pod ... -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'`
  → `ghcr.io/halildeu/platform-backend-endpoint-admin-service@sha256:c895cfd60d64840ddd85da91e23d4a982049e2e1d84c6cc1ca4fb24db58c07af`
  (= overlay digest pin)
- Pod-internal `curl http://localhost:8081/actuator/health` → HTTP 200
- Pod-internal `curl http://localhost:8096/api/v1/admin/endpoint-devices/<id>/hardware-inventory/latest` → HTTP 401 (auth-gated, doğru — JWT eksik)
- Pod-internal `curl http://localhost:8096/api/v1/admin/endpoint-devices/<id>/hardware-inventory/history` → HTTP 401 (auth-gated, doğru)
- Hibernate ddl-auto=validate clean (BE-022Q is code-only on top of V14)
- Flyway history: no new migration (V14 already in place from earlier this session)

### Browser smoke (V14 backend, pre-Donanım tab)

- testai.acik.com /endpoint-admin/devices: 6 device render, console clean (only ag-grid DEBUG)
- SRB-AIDENETIMPC drawer: 6 tabs (Detay/İşlemler/Denetim Geçmişi/Envanter/Yazılım Kataloğu/Uyum)
- Device ID `423b6fc3-7497-4083-bd2f-5e2fe543bfe9`, Tenant `00000000-0000-0000-0000-000000000001`, Çevrim içi, lastSeen 29.05.2026 01:05:35
- Yazılım Kataloğu tab: 7-Zip (BE-021 smoke), 7zip.7zip, Düşük risk
- "Kur" tıklanma → preflight modal:
  - 🔴 ENGELLENDİ
  - REASON: "Envanter henüz toplanmadı; önce envanter toplayın."
  - GEREKSİNİMLER: "Run COLLECT_INVENTORY to ingest a software snapshot first."
  - KARAR KANITI: Katalog sürümü 1 (28.05.2026 22:31:53)
- İşlemler tab SON KOMUTLAR: COLLECT_INVENTORY x5 hepsi "Başarılı" (software/lightweight agent loop kanıt)

### Test green (per slice)

- AG-035: `go build ./...`, `GOOS=windows go build ./...`, `go vet ./...` clean; `go test ./internal/inventory/... ./internal/commands/...` PASS
- BE-022Q: `mvn test -Dtest=AdminEndpointHardwareInventoryControllerTest,EndpointAdminAuthorizationAnnotationTest -Djacoco.skip=true` → Tests run: 13, Failures: 0, Errors: 0
- WEB-013: vitest 8 passed (6 original + 2 regression for iter-1 absorb)
- Gitops bump: CI ALL GREEN 14/14 (boundary OK, cross-ai-audit OK, Drift gates, Kustomize Build Sanity, ResourceQuota preflight, YAML/shell lints, gitleaks)
- WEB-013 source PR: CI 24 pass + 2 manual skipping, 0 fail

## 4. İspatlamaz

### Pending closure gates (in order)

1. **Frontend image build** (run `26608521488` in_progress at handoff)
2. **Frontend digest pin** in `kustomize/overlays/test/kustomization.yaml`
3. **Frontend gitops bump PR** + CI + merge
4. **Cluster apply** → frontend pod imageID match new digest
5. **Browser smoke**: Donanım tab empty state (no SRB snapshot yet)
6. **AG-035 binary distribution** to SRB-AIDENETIMPC — operator-bound channel (Windows installer build, signed binary deploy)
7. **COLLECT_INVENTORY includeHardware=true** trigger via Donanım tab indirect (İşlemler → "Envanteri Şimdi Topla") or direct backend POST
8. **Backend ingest row** in `endpoint_hardware_inventory_snapshots` (psql verify)
9. **GET /latest 200** real browser fetch (auth via shell login) — UI render with CPU/RAM/disks/NICs
10. **Re-preflight 7-Zip** sonrası state: inventory_missing → PASS/WARN transition (only software inventory was missing in this session's BLOCK; hardware ingest doesn't change preflight reason yet)

### Operator-bound / external

- AG-035 binary distribution to SRB-AIDENETIMPC (WiX MSI build + Authenticode signing + GPO delivery or manual install)
- Authenticated browser session for real /latest 200 evidence (operator at desk)

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### P0 — Next agent should start with these

1. **Frontend image build status** — `gh run view 26608521488 --repo Halildeu/platform-web`
   - Success → grab digest from `gh run view --log | grep frontend.*sha-26e6865` (or whatever short SHA)
   - Failure → triage CI, push fix
2. **platform-k8s-gitops frontend digest bump** — new branch `bump/web-013-hardware-tab`
   - Edit `kustomize/overlays/test/kustomization.yaml` frontend image digest pin
   - `kubectl kustomize` sanity
   - Commit + PR + CI green + squash merge
3. **Cluster apply** — ssh halil@staging-sw + `kubectl --context k3d-test apply -k /home/halil/platform-k8s-gitops/kustomize/overlays/test`
   - Verify pod imageID + rollout success
4. **Browser smoke Donanım tab** — claude-in-chrome MCP
   - Drawer açıp 7. tab "Donanım" görünür mü
   - Empty state mesajı ("Bu cihaz için henüz donanım envanteri toplanmamış") + İşlemler tab pointer
   - Console + network clean
   - V14 / BE-022Q backend ile uyumlu (network 200 for /hardware-inventory/latest 404)
5. **PM truth refresh remainder** — PLAN.md 22.5 satırı + handoff doc reference link

### P1 — Operator-bound (not agent-actionable)

- AG-035 binary distribution to SRB-AIDENETIMPC
- COLLECT_INVENTORY includeHardware=true field trigger
- Real backend ingest row + GET /latest 200 real render

### P2 — Backlog (Codex non-blocking)

- WEB-013 Option A refactor: InventoryTab segment switch (Yazılım / Donanım sub-mode) — Codex önerdiği "cleaner" mimari; current Option B (7. tab) acceptable for v1
- UI polish: i18n cleanup for hardcoded `cores`, `free`, `disks`, `probe errors` strings
- BE-022Q backend IP cap per-interface (agent caps at 16 already; backend adversarial hardening)
- BE-022Q follow-up: per-snapshot detail route `GET .../hardware-inventory/{snapshotId}` if WEB-013 v2 needs drilldown
- Fleet-wide hardware search `GET /api/v1/admin/endpoint-hardware-inventory` (CPU/RAM/OS filters)

### Composite (D29-disciplined)

22.5.2 hardware quick wins:
- Source-merged: 4/4 ✓ (~95%)
- GitOps deployed: 2/3 ✓ (~70%); frontend pending
- Live Up: backend LIVE, agent operator-bound, frontend pending (~55%)
- Functional: backend auth-gated, UI render pending apply, agent real probe operator-bound (~30%)
- End-to-end: pending real SRB hardware + UI live (~15%)

Composite ~55-65% (D29-disciplined; 5-layer not single-number per
AGENTS.md HARD RULE no-closure language).
