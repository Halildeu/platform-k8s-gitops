# Session Handoff — 2026-05-18 — D29 smoke Tier-2 network-path fix MERGED; prod-deploy repo-only otonom kapsam kayda geçti

> Format: D28 5-alan + sıradaki agent aksiyon listesi
> Önceki handoff: `session-handoff-2026-05-18-prod-deploy-pr4a.md`
> Codex thread: `019e3a17` (Tier-2 plan-time + post-impl cross-AI review);
> mimari plan `019e35d1` (4-PR prod-deploy)

---

## 1. Bağlam

`session-handoff-2026-05-18-prod-deploy-pr4a.md` §5 Tier-2 runner network-path
kalemini "spec-bekleyen → defer" devretmişti — root cause spec'i yoktu (hangi
host / kubeconfig / svc-port / failure classification). Bu session o kalemi
otonom yürüttü: root cause araştırıldı, mini-design Codex `019e3a17` ile
uzlaşıldı, fix uygulandı + canlı doğrulandı + merge edildi (#798).

Tier-2, PR-4A handoff §5'teki tek **otonom-yapılabilir** (operator
gerektirmeyen, repo-içi) kalemdi. #798 ile prod-deploy 4-PR mimari planının
(Codex `019e35d1`) repo-only otonom platform-k8s-gitops kapsamı
PR-1/2/3A/4A + Tier-2 olarak kayda geçti. Kalan iş tümüyle operator-gated
(PR-3B/C/D/E) veya cross-repo (PR-4 ledger B3) — bu repo'da otonom-yapılabilir
prod-deploy işi kalmadı.

---

## 2. İddia — bu session'da yapılanlar

### #798 (MERGED, `95a59eb`) — d29-smoke Tier-2 port-forward named port + 3-state

**Bug**: `scripts/smoke/d29-smoke-runner.sh` `tier_functional` her servisi
`kubectl port-forward svc/<name> $port:80` ile forward ediyordu. Hiçbir JWT
servisi port 80 expose etmiyor — her biri ayrı numara (api-gateway 8080,
user-service 8089, variant-service 8091, permission-service 8090,
schema-service 8096, report-service 8095), hepsi `http` adlı port altında.
port-forward `error: ... does not have a service port 80` ile fail ediyor,
local port hiç açılmıyor, curl `000` dönüyor → 6 servis de RED her koşuda
(üstelik `|| echo "000"` ile `000000` artefact'i). PR-4A handoff §4'te
"yeniden gözlemlendi" diye not edilen Tier-2 RED'inin root cause'u buydu.

**Fix**:
- `tier_functional` → yeni `probe_functional_endpoint` helper'ı:
  - **named port** — `$port:80` → `$port:http` (her servisin kendi portuna
    çözülür).
  - **2 deterministik wiring pre-check** — `http` adlı port yok / ready
    endpoint yok → RED (manifest/selector drift net RED, transient değil).
  - **tunnel-bind poll** — kör `sleep 2` yerine `Forwarding from` log satırı
    için ~8s poll.
  - **3-state verdict** — OK (200/401/403) / RED (tunnel kurulduktan **sonra**
    5xx/000/beklenmeyen kod, ya da wiring) / AMBER (tunnel hiç bind olmadı —
    transient, inconclusive). Tier rollup'ta RED, AMBER'ı override eder.
  - curl `localhost`→`127.0.0.1`; gereksiz `|| echo "000"` kaldırıldı
    (`000000` artefact'i giderildi, `set -e`-safe).
- `scripts/smoke/systemd/smoke-{test,prod}.service` — `SuccessExitStatus=0 1`
  → `0 1 3`. PR-4A exit 3 (incomplete) getirmişti ama unit'ler exit 3'ü
  unit-failure sayıyordu → incomplete koşuda `ExecStartPost` ledger marker
  atlanıyordu (`Type=oneshot` davranışı).
- Codex `019e3a17` plan-time REVISE→AGREE (3-state model düzeltmesi: tunnel
  bind olduktan sonra `000` AMBER değil RED'dir) + post-impl AGREE.

---

## 3. İspatlar

- **#798**: CI 8/8 GREEN (shell-lint/shellcheck dahil), `mergeState=CLEAN`,
  mergedAt 2026-05-18T08:19:04Z. Archive tag
  `archive/2026/05/fix-d29-smoke-tier2-port-pr798`.
- **Fonksiyonel kanıt**: değiştirilmiş `d29-smoke-runner.sh test` `k3d-test`'te
  koştu — 4 tier GREEN, exit 0; **Tier 2 Functional RED→GREEN**
  (`all 6 endpoints returned 200/401/403`), JSON `d29_functional.status=GREEN`.
- **RED dalları execute-doğrulandı**: `probe_functional_endpoint openfga
  /no-such-path` → `RED|tunnel up, endpoint returned 404`; eksik servis →
  `RED|no http-named service port`.
- `bash -n` + `shellcheck -S warning` temiz.
- Codex cross-AI: `019e3a17` plan-time REVISE→AGREE + post-impl AGREE.

---

## 4. İspatlamaz

- **AMBER dalı (tunnel hiç bind olmadı) execute edilmedi** — fonksiyon portu
  `RANDOM` seçtiği için non-destructive bir bind-failure zorlanamadı. Kod
  read-verified + Codex review'lü; AMBER güvenli yön (exit 3, yanlış promote
  etmez). İleride kubectl-mock'lu shell harness ile test edilebilir
  (confidence; fonksiyonel blocker değil).
- **PR-3B/C/D canlıya alınmadı** — operator-gated; runner kubeconfig hâlâ
  `admin@k3d-prod`. Runbook `RB-prod-rbac-least-privilege.md` shipped.
- **PR-4 ledger CI automation yapılmadı** — `scripts/promotion/*` script'leri
  hazır; eksik = B2 GitHub App registration (operator-manual) + B3 cross-repo
  CI çağrısı.
- Tier-2 fix yalnız `k3d-test`'te doğrulandı; prod smoke run operator-gated
  (deploy sonrası systemd unit tetikler).

---

## 5. Bilinen Boşluk + Sıradaki Agent Aksiyonları

> prod-deploy 4-PR planında bu repo'da **otonom-yapılabilir iş kalmadı**.
> Kalan kalemler operator yetkisi veya başka repo gerektirir.

### 🟠 Operator-gated — runbook `RB-prod-rbac-least-privilege.md` shipped
- **PR-3B** — break-glass SA live activation (`kubectl apply -k
  kustomize/base/rbac` + `break-glass-token.sh` smoke).
- **PR-3C** — `prod-deploy-smoke` apply + runner kubeconfig least-privilege
  cutover + `kubectl auth can-i` acceptance matrisi.
- **PR-3D** — operator readonly identity migration (owner koordinasyonu).
- **PR-3E** — audit/alarm (Faz 5); PR-3B sonrası.

### 🔵 Cross-repo / operator — PR-4 ledger CI automation
- **B2** (operator-manual): GitHub App registration — gitops repo'ya ledger
  entry commit yetkisi.
- **B3** (cross-repo): `platform-backend` + `platform-web` CI'larına image
  build + GHCR push sonrası `generate-ledger.sh` çağrısı. B3 PR'ları o
  repo'ların CI'larında açılır; `platform-ssot` hedef repo değil.

### 🟢 Otonom izlenebilir (opsiyonel, blocker değil)
- Tier-2 AMBER dalı için kubectl-mock'lu shell harness testi.
- Q4 prod authenticated snapshot-data smoke (önceki handoff residual).

---

## Sıradaki Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin main && git log origin/main --oneline -6
cat docs/session-handoff-2026-05-18-d29-tier2.md                  # bu doc
cat docs/operations/RUNBOOKS/RB-prod-rbac-least-privilege.md      # PR-3B/C/D operator
# prod-deploy 4-PR: repo-only otonom kapsam kayıtlı (PR-1/2/3A/4A + Tier-2).
# Kalan: operator PR-3B/C/D/E + cross-repo PR-4 B3 — agent-only repo işi yok.
```
