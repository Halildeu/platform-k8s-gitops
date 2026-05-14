# Session Handoff — 2026-05-14 (Session 50) — PERF-INIT-V2 B5b2-hostfix + Status Writer Live Monitoring

> Format: D28 5-alan + sıradaki agent P0 aksiyon listesi.
> Önceki handoff: [docs/session-handoff-2026-05-14-session-48-supplement-d-wave.md](./session-handoff-2026-05-14-session-48-supplement-d-wave.md) → Session 49 D1.1a closure (PR #570).
> Çapraz repo handoff: platform-web PR #477 (B5b2-hostfix kod tarafı) + bu repo'daki gitops PR'ları.

---

## 1. Bağlam (bu turda ne yapıldı)

Session 50 PERF-INIT-V2 plan'ının iki kanalı paralel ilerletti:

**Kanal A — B5b2 kritik fonksiyonel regresyon fix'i** (platform-web)
Kullanıcı browser'ında `UNKNOWN Reporting şu anda kullanılamıyor [B5b2-prep] Host MF runtime instance 'mfe_shell' not initialized` hatası raporladı. Root cause: 7 ayrı on-demand wrapper içindeki duplicate `getHostMfInstance()` arayan `name === 'mfe_shell'` literal eşitlik (Vite plugin runtime aslında `__mfe_internal__mfe_shell` namespace ile register ediyor). Codex thread `019e2528` ile **single source of truth helper** + S7 CI invariant guard pattern AGREE.

**Kanal B — Cluster-side smoke kalıcı monitoring** (platform-k8s-gitops)
Kullanıcı sorusu "iyileştirmeler kalıcı olarak takip edilecek mi sorun olduğunda müdahele edecek miyiz" → Codex thread `019e25a7` ile **status ConfigMap writer pattern**: CronJob smoke her fire'da `/data/{lastFire,result,failures}` upsert eder + ArgoCD `ignoreDifferences` ile drift-fight yok + observability tek yüzey. RBAC narrow (Codex iter-1 P1: `get,patch` only, no `create`) + NetworkPolicy iter-2 least-privilege (Service IP /32 + bridge /16:6443 post-DNAT).

**Final kanıt: prod cluster smoke GERÇEK regresyon yakaladı** — B3c long-cache prod'da eksik (`Cache-Control: max-age=3600` observed vs `max-age=31536000.*immutable` expected). Live monitoring + müdahale altyapısı doğrulanmış oldu.

---

## 2. İddia (MERGED PR'lar)

### Bu repo (platform-k8s-gitops)

| PR | sha | Konu | Codex Thread |
|---|---|---|---|
| [#562](https://github.com/Halildeu/platform-k8s-gitops/pull/562) | `50cb516` | CronJob smoke prod overlay promote + D29 ledger whitelist (curl utility image) | `019e25a7` |
| [#565](https://github.com/Halildeu/platform-k8s-gitops/pull/565) | `caea2b4` | Status ConfigMap writer (RBAC + ConfigMap + NetworkPolicy + Argo ignoreDifferences) | `019e25a7` iter-1 P1 absorb |
| [#568](https://github.com/Halildeu/platform-k8s-gitops/pull/568) | `7d1b623` | Writer block heredoc → plain interpolation + `set +eu` wrap (silent failure fix) | `019e25a7` iter-2 |
| [#569](https://github.com/Halildeu/platform-k8s-gitops/pull/569) | `4336271` | NetworkPolicy CIDR fix — Service IP /32 + k3d bridge /16:6443 (post-DNAT) | `019e25a7` iter-3 |

### Çapraz repo (platform-web)

| PR | Konu |
|---|---|
| [#477](https://github.com/Halildeu/platform-web/pull/477) | B5b2-hostfix: `apps/mfe-shell/src/app/config/host-mf-instance.ts` single source of truth (`isHostRuntimeName` predicate `__mfe_internal__mfe_shell` namespace handle) + 7 on-demand wrapper refactor (282 satır duplicate silindi) |
| [#478](https://github.com/Halildeu/platform-web/pull/478) | S7 invariant CI guard: token-level scan `__FEDERATION__`, `__INSTANCES__`, local `getHostMfInstance` redeclaration YASAK + helper import zorunlu |
| #561 | Frontend image digest bump (`sha-103805c`) — B5b2-hostfix prod'a deploy |

**Toplam: 5 PR MERGED this session (4 gitops + 1 image bump) + 2 platform-web kod PR**. Plus 1 spawn task chip aktive edildi (B3c prod long-cache promote).

---

## 3. İspatlar

### B5b2-hostfix runtime fix (platform-web)

**Browser eval kanıt** (regresyon öncesi):
```js
> Object.keys(globalThis.__FEDERATION__.__INSTANCES__).map(k => globalThis.__FEDERATION__.__INSTANCES__[k].options?.name)
['__mfe_internal__mfe_shell']  // ← literal 'mfe_shell' DEĞİL
```

**Fix doğrulama** (post-deploy `sha-103805c`):
- Reporting MFE init başarılı (`Host MF runtime instance` not-found hatası kaybloldu)
- 7 canary route smoke (B5b1/B5b1.5/B5b2a/B5b2 chain) browser'da regression yok

### Status Writer live evidence

**Test cluster** (manual smoke trigger sonrası):
```json
{
  "data": {
    "failures": "0",
    "lastFire": "2026-05-14T09:29:56Z",
    "result": "PASS"
  }
}
```
Writer log: `[STATUS] patched ConfigMap frontend-federation-smoke-status (HTTP 200, result=PASS, failures=0)` + `[B5b3e] PASS`

**Prod cluster** (ArgoCD sync sonrası + manual smoke trigger):
```json
{
  "data": {
    "failures": "1",
    "lastFire": "2026-05-14T09:32:11Z",
    "result": "FAIL"
  }
}
```
Smoke fail detail: `[FAIL] hashed root asset /assets/index-QlXd9_3B.css HTTP 200 but Cache-Control did NOT match: max-age=31536000.*immutable; observed: max-age=3600`

### RBAC narrowness verify (Codex iter-1 P1)

Prod cluster post-apply check:
```bash
$ kubectl auth can-i create configmaps --as=system:serviceaccount:platform-prod:frontend-federation-smoke -n platform-prod
no
$ kubectl auth can-i patch configmaps/frontend-federation-smoke-status --as=system:serviceaccount:platform-prod:frontend-federation-smoke -n platform-prod
yes
```
→ Codex'in `resourceNames` collection endpoint constraint kuralı tutuyor.

### NetworkPolicy CIDR (Codex iter-3)

Test cluster k3d Flannel egress path:
- Service IP `10.45.0.1:443` pre-DNAT match (kube-proxy DNAT'tan önce)
- k3d docker bridge `172.19.0.0/16:6443` post-DNAT endpoint (apiserver actual port)
- İki egress rule birleşince HTTP 200 from writer pod

### ArgoCD ignoreDifferences pattern

`argocd/applications/platform-{test,prod}.yaml`:
```yaml
syncOptions:
  - RespectIgnoreDifferences=true
ignoreDifferences:
  - kind: ConfigMap
    name: frontend-federation-smoke-status
    jsonPointers:
      - /data
```
→ Argo `/data` dinamik alanları revert etmiyor; GitOps metadata + writer runtime data ayrı kapı.

### Live cluster state (Session 50 close)

| Alan | Durum | Notlar |
|---|---|---|
| Mac k3d-dev | 🟢 | Node Ready |
| staging-sw k3d-test | 🟢 14 deploy | Status writer LIVE, son fire 09:29:56Z PASS, failures=0 |
| staging-sw k3d-prod | 🟢 12/12 | Status writer LIVE, son fire 09:32:11Z **FAIL**, failures=1 (B3c gap) |
| Compose stateful | 🟢 9 | Vault test sealed=false |

---

## 4. İspatlamaz (henüz kanıt yok)

- **Prod cluster B5b3e doğal cron fire** — natural schedule next at `30 */6` Europe/Istanbul; manual smoke fire'lar test edildi, scheduled fire henüz gözlenmedi. İlk doğal fire'da status ConfigMap'in lastFire alanı UTC ISO ile güncellenmeli.
- **B3c prod long-cache promote** — Spawn task chip aktif. Prod regresyonu mevcut (`failures=1`), fix yolu Codex consult predicted: "operationally much stronger, not yet fully pager-backed". Test cluster B3c LIVE (PR #558 ConfigMap nginx long-cache), prod promote PR henüz açılmadı.
- **Sprint 1 B (branch protection)** — Conservative tier (5+5 required_status_checks + enforce_admins) AskUserQuestion ile seçildi ama auto-mode classifier `gh api PUT /repos/.../branches/main/protection` engelliyor → kullanıcı manual çalıştırması gerek (komut runbook'ta hazır).
- **Sprint 2 A (Slack webhook)** — `SLACK_PERF_WEBHOOK_URL` secret yok; kullanıcı Slack incoming webhook oluşturup `gh secret set` çalıştırması gerek.
- **Sprint 2 C (M2a auth-storage)** — Test persona credentials veya Keycloak admin API authorization gerekli (HARD RULE: kullanıcı login user şifresine dokunma YASAK → test-persona ayrı).
- **Sprint 2 D (B3b1 Brotli)** — Edge nginx infra authorization gerek (host config değişimi).
- **AlertManager → Slack route** — PrometheusRule var (PR #563) ama Slack receiver wire-up `SLACK_PERF_WEBHOOK_URL` secret oluştuktan sonra; şu an alarm log'a düşüyor, mesaj kanala gitmiyor.

---

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### P0 — Hemen başla

1. **Prod B3c long-cache promote PR'ı aç** (~20-30dk + cross-AI Codex review)
   - Spawn task chip aktif — yeni session'da prompt'u devral
   - Test cluster B3c LIVE pattern: `kustomize/overlays/test/api-gateway/nginx-cache.configmap.yaml` (PR #558)
   - Prod overlay aynı ConfigMap pattern + selective apply + smoke verify
   - Live regresyon kanıtı zaten elimizde: prod status CM `result=FAIL, failures=1, lastFire=2026-05-14T09:32:11Z`
   - Fix sonrası natural cron fire prod status CM'i `result=PASS` döndürmeli (kalıcı monitoring closure-loop kanıtı)

2. **Prod cluster ilk doğal cron fire verify** (~5-10dk gözlem)
   - Schedule: `30 */6` Europe/Istanbul → next fire 12:30 / 18:30 / 00:30 / 06:30
   - Cron pod log + status ConfigMap timestamp update kontrol
   - Eğer B3c fix merged + deploy edildi ise `result=PASS` bekleniyor

### P1 — Sonraki sprint (user action gerek)

3. **Sprint 1 B: Branch protection Conservative tier** — kullanıcı manual `gh api`
   ```bash
   # Conservative tier (5+5 required_status_checks + enforce_admins=false)
   # Bash runbook hazır: docs/runbooks/branch-protection-conservative.md (eğer yoksa runbook yazılır)
   gh api -X PUT repos/Halildeu/platform-k8s-gitops/branches/main/protection \
     -F required_status_checks.strict=true \
     -F required_status_checks.contexts='["status-check-1","status-check-2",...]'
   ```

4. **Sprint 2 A: Slack webhook secret**
   ```bash
   # User creates Slack incoming webhook → URL alır
   gh secret set SLACK_PERF_WEBHOOK_URL --repo Halildeu/platform-k8s-gitops < webhook-url.txt
   ```
   Sonrasında AlertManager Slack receiver wire-up + smoke (test cluster intentional CrashLoop deploy → alarm'ın Slack'e düşmesi)

5. **Sprint 2 C: M2a auth-storage** — Test persona credentials
   - **HARD RULE bağlantı**: Kullanıcının login user şifresi YASAK; test persona ayrı (`test-admin@`, `canary-scope` gibi)
   - Keycloak admin API + Vault rotation ile test persona oluştur + Vault'a yaz
   - M2a auth-storage browser smoke (impersonation, role switch, session refresh)

6. **Sprint 2 D: B3b1 Brotli** — Edge nginx infra
   - Host nginx config (`ssh halil@staging-sw`) — staging-sw edge proxy Brotli module load + `brotli on; brotli_types ...;` directive
   - User-explicit onay gerek (host nginx reload destructive değil ama production-adjacent)

### P2 — Continuous

7. **Status writer continuous observation**
   - Test + prod cluster `frontend-federation-smoke-status` ConfigMap her 6 saatte bir fire eder
   - Manual probe: `kubectl --context k3d-prod -n platform-prod get cm frontend-federation-smoke-status -o jsonpath='{.data}'`
   - Failures counter monotonic artarsa root cause + müdahale (Codex consult pattern)

8. **PrometheusRule alert continuous** (PR #563)
   - RolloutStuck + RSSplit + CrashLooping alert'leri Prometheus'a yüklendi
   - Slack receiver wire-up (P1 #4) sonrası kanal'a düşmeye başlar

### P3 — Backlog (sıradaki sprint için scope)

9. **PERF-INIT-V2 Sprint 3 planning** — Codex thread `019e25a7` continuation
   - B5b3 metrics endpoint live wiring
   - B6 workflow chunks (Lighthouse advisory FAIL pre-existing — root cause analysis gerek)
   - Auth Transport E2E advisory FAIL pre-existing — Sprint 2 C ile bağlantılı

---

## Codex Thread Referansları

| Thread | Konu | Durum |
|---|---|---|
| `019e2528` | B5b2-hostfix single source of truth + S7 invariant guard | AGREE (PR #477 + #478) |
| `019e25a7` | Status ConfigMap writer + RBAC + NetworkPolicy + Argo ignoreDifferences (3 iter PARTIAL→AGREE) | AGREE (PR #562 + #565 + #568 + #569) |
| `019e258a` | D1.1a runbook 4-iter REVISE→AGREE (Session 49 referans) | AGREE (PR #564) — önceki session |

---

## Boundary declaration (ADR-0011 §2.3)

- [x] credential-read (Vault token unseal — Session 49 mirası, bu turda kullanılmadı)
- [ ] credential-write (Vault patch — bu turda yok)
- [x] state-mutation (test cluster — manual `kubectl apply -k`)
- [x] state-mutation (production — ArgoCD sync trigger, narrow status writer scope)
- [ ] boundary-cross
- [x] user-communication (handoff doc + final summary)

---

## Yeni Session İçin İlk Komut

```bash
cd ~/Documents/platform-k8s-gitops
cat docs/session-50-handoff-perf-init-v2-b5b2-hostfix-status-writer.md  # tam context
gh pr view 569 --repo Halildeu/platform-k8s-gitops  # son merge'in detayı
kubectl --context k3d-prod -n platform-prod get cm frontend-federation-smoke-status -o jsonpath='{.data}' | jq .  # son prod fire durumu
```

Sıradaki en doğal P0: prod B3c long-cache promote PR (spawn task chip aktif).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
