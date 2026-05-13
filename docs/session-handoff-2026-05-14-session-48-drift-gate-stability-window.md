# Session Handoff — 2026-05-14 (Session 48 Drift Gate + Stability Window)

> Format: D28 5-alan + sıradaki agent P0 aksiyon listesi.
> Önceki handoff: [docs/session-handoff-2026-05-13-session-47-bug-wave-closure.md](./session-handoff-2026-05-13-session-47-bug-wave-closure.md).

---

## 1. Bağlam (bu oturumda ne yapıldı)

Session 47 closure'dan sonra Session 48 açılışında kullanıcı sordu: **"çok fazla bug oluyor bunu engellemek ya da tespit etmek için bir şey var mı?"**

Triage: 2026-05-13 endpoint-admin-service silent CrashLoopBackOff bug pattern'i analiz edildi — repo HEAD'de fix var (PR #499 `5f6ef07`: `startupProbe` + `/actuator/health/{liveness,readiness}`) ama cluster ReplicaSet hâlâ skeleton-era `/healthz/*` spec'iyle yeni replica spawn'lıyor (apply gap). 16h silent crash. Aynı pattern son 30 günde 3+ kez tetiklendi (D33 Gateway ConfigMap drift, V19 drift, 11-day silent CrashLoop).

Codex strategy thread `019e2319` iter-3 AGREE → 2-PR sequential plan: PR-1 deployment contract drift gate (PR-time + runtime), PR-2 deploy CI stability window. Plus immediate fix: cluster'daki drift'li endpoint-admin ReplicaSet selective apply ile düzeltildi (rollout success, testai 200 LIVE).

---

## 2. İddia (MERGED PR'lar)

| PR | Repo | Başlık | Implementer | Reviewer | Codex Thread |
|---|---|---|---|---|---|
| **#551** | platform-k8s-gitops | Deployment contract drift gate (probe + template + RS-split) | Claude | Codex async (REVISE→AGREE) | `019e2327` |
| **#552** | platform-k8s-gitops | Pod stability window gate (Gate 1d) in deploy workflows | Claude | Codex async (REVISE→AGREE) | `019e233b` |

**2 PR MERGED**, sıfır admin bypass, normal squash merges, cross-AI peer review HARD RULE uyumu.

Plus immediate fix (no PR, selective apply): endpoint-admin yeni RS `/healthz/*` → `/actuator/health/*` + `startupProbe` deploy gap kapatıldı; CrashLoop terminate, testai 200 LIVE.

---

## 3. İspatlar

### Bug fix (immediate, no PR)
- `kubectl --context k3d-test -n platform-test apply -f endpoint-admin-deployment.yaml` (kustomize overlay rendered)
- `rollout status deploy/endpoint-admin-service` → successful
- `testai.acik.com` → 200 (önce 503 idi)
- 273-restart CrashLoop RS terminate edildi

### PR #551 (drift gate)
- 35/35 unittest PASS (`python3 -m unittest discover scripts/drift_detection/tests/`)
- check_pr_time.sh test+prod overlay Check 5 → clean
- check_prod_drift.sh test cluster runtime → 10 P1 finding (baseline cleanup için bekleniyor, Codex iter-3 explicit)
- Codex thread `019e2327` REVISE (6 blocker) → iter-2 AGREE (`ready_to_merge: true`)
- Merge sha: `3720716`

### PR #552 (stability window)
- gate-stability-window.sh canlı smoke k3d-test:
  - api-gateway 60s window → PASS
  - endpoint-admin-service 40s window → PASS
- Codex thread `019e233b` REVISE (3 issue: timeout, t=0 check, sidecar-safe restart map) → iter-2 AGREE
- Merge sha: `7a16982`

### Forensic cleanup
- archive tags pushed: `archive/2026/05/codex-deployment-contract-drift-gate-pr551` + `archive/2026/05/codex-deploy-stability-window-gate-pr552`
- Recovery 1+ year mümkün

### 3-katman live state (Session 48 close anı)

| Alan | Durum | Not |
|---|---|---|
| Mac k3d-dev | 🟢 | Node Ready 17d |
| staging-sw k3d-test | 🟢 | 14 deploy ready, testai 200 |
| staging-sw k3d-prod | 🟢 | 12/12 ready, ai 200 |
| Compose stateful | 🟢 | 9 healthy (PG/KC/Vault test+prod + nginx edge×2 + GHA runner) |

---

## 4. İspatlamaz (henüz kanıt yok)

- **Runtime drift detector baseline cleanup**: 10 P1 finding live cluster vs desired diff'te. Çoğu apply gap (env drift birkaç backend'de) + 2 normalizer iyileştirme adayı:
  - `terminationGracePeriodSeconds=30` Kubernetes default — normalizer'da inject edilmeli
  - `resources.limits.cpu "1" vs "1000m"` Kubernetes quantity equivalence — normalize edilmeli
- **Gate 1d ilk gerçek deploy smoke**: bir image-bump PR merge edilip workflow'un Gate 1d adımını uçtan uca çalıştırması gerek; yerel smoke 60s window ile yapıldı ama 120s/180s window CI'da henüz canlı koşulmadı.
- **Live BUG #1 + BUG #3 browser smoke (Session 47'den devir)**: testai admin login refresh + impersonation flow + audit row capture hâlâ pending.
- **Codex MCP stability investigation**: Session 47'de tetiklenen "Connection closed" hataları teşhis edilmedi (bu session'da MCP stabil çalıştı — yine de root cause araştırılmadı).

---

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### P0 — Hemen başla

1. **Runtime drift baseline cleanup (PR-3)** — ~2-3h
   - Normalizer fix:
     - `terminationGracePeriodSeconds=30` default inject
     - Kubernetes resource quantity parser (cpu "1" == "1000m", memory "1Gi" == "1024Mi")
   - 10 P1 finding sınıflandır: gerçek apply gap → reconcile (selective apply); intentional drift → overlay düzelt
   - Initial baseline temizlendikten sonra timer'ın "clean" üretmesi beklenir

2. **PrometheusRule cluster alerting (PR-4)** — ~1-2h
   - `KubeDeploymentRolloutStuck` (Progressing=False > 15m)
   - `KubeReplicaSetSplit` (>1 active RS + newest ready=0 > 10m)
   - `KubePodCrashLooping` (kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} > 0 for 5m)
   - Mevcut 25 PrometheusRule'a ek + AlertManager routing

3. **Live BUG #1 + BUG #3 browser smoke (Session 47 devir)** — ~5 dk
   - Browser MCP / Chrome connection ile testai admin login + impersonation flow
   - Kanıt: screenshot + console + network + audit DB row
   - HARD RULE — Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi

### P1 — Timer/blocker-bound

4. **check_pr_time.sh Check 3 line 213 bash quoting hiccup** — küçük cleanup (Codex iter-2 non-blocking)
5. **Prod cutover (ai.acik.com)** — V16 migration + atomic L4 switch + 72h warm rollback (owner-go bekliyor)

### P2-P3 — Sonraki sprint

6. **Spawn task'lar (Session 47'den devir)**:
   - BE WireMock IT scaffold (8 case)
   - FE Playwright scaffold (5 E2E case)

---

## Codex Thread Referansları

- **Plan-time strategy**: `019e2319-f8e6-7b00-902c-7b082742fc1b` (G1+G2 deployment contract drift gate, iter-3 AGREE)
- **PR-1 peer review**: `019e2327-e11d-7c20-9c9e-3497df683bf6` (6 blocker REVISE → iter-2 AGREE)
- **PR-2 peer review**: `019e233b-1672-7702-9c28-54830cea404f` (3 issue REVISE → iter-2 AGREE)
- **Önceki zincirler**: `019e1e0f` (Session 47 bug wave), `019df310` (governance migration)

---

## Yeni Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-05-14-session-48-drift-gate-stability-window.md

# Hemen P0-1 ile başla:
ssh halil@staging-sw "cd /home/halil/platform/platform-k8s-gitops && python3 scripts/drift_detection/check_deployment_contracts.py --mode runtime --env test --render-source kustomize/overlays/test --live-context k3d-test --live-namespace platform-test --catalog docs/operations/services.yaml --output text"
# 10 P1 finding listesi gelmeli — bunları sınıflandır + fix PR
```

---

## Karar Özeti (tek cümle)

Session 48'de "çok fazla bug oluyor" sorusuna kalıcı 3-katman yanıt verildi (PR-time gate + runtime detector + deploy CI stability window); endpoint-admin probe drift pattern'i artık merge öncesi fail eder, live drift 15dk içinde P1 alarm üretir, deploy sonrası 2-3dk crash penceresi otomatik yakalanır.
