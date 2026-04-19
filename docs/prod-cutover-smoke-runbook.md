# Prod Cutover Smoke Runbook — S4-D Atomic Switch

> **Source:** K8s-6 Codex thread `019d9a75` 4-tur mutabakat Tur A3 + S4-D blueprint (2026-04-19)
> **Prereq:** S4-F1-F9 staging-sw-2 bootstrap tamam (D32 checklist PLAN.md Bölüm 1.5)
> **Prereq:** S3 testai stability soak PASS (No-Go gate 6/6 blocker 🟢)
> **Pattern:** Atomic proxy upstream switch + 72h warm rollback (D30 HARD RULE)
> **YASAK:** Weighted DNS %10/50/100 (D30 — session/cache/side-effect riski ayrı doğrulanmamış)

---

## 1. Cutover Adımları (atomic)

### Adım -1 — Preflight (T-24h)

- [ ] **DNS doğrulama:** `ai.acik.com` → dış proxy `212.115.26.190` (kurumsal L4 pass-through), TTL düşürülmüş (60s) — T-48h önce
- [ ] **TLS cert:** Sectigo wildcard `*.acik.com`, staging-sw-2 nginx mount, expire > 60 gün
- [ ] **Artifact digest immutability:** tüm 8 servis overlay `newTag: sha-<short>` (D30 uyumu). `kubectl kustomize overlays/prod | grep "main-stable"` → **0 match**
- [ ] **Pod imageID eşleşmesi:** staging-sw-2 k3d-prod'da 8 servis Pod Ready, pod imageID == CI digest (S1-E1 pattern)
- [ ] **Rollback config backup:** staging-sw compose state snapshot (PG dump + nginx config + docker compose yaml)
- [ ] **Smoke-client token hazır:** S2-B3 handoff merged, Keycloak confidential client + Vault secret accessible

### Adım 0 — Git/Live Reconcile (T-2h)

- [ ] `git pull` — K8s-gitops main branch up-to-date
- [ ] `kubectl --context k3d-prod -n platform-prod diff -k kustomize/overlays/prod` → **drift = 0**
- [ ] ArgoCD varsa: `argocd app diff platform-prod --exit-code` → **exit 0**
- [ ] Git last-applied annotation vs live state eşleşiyor

### Adım 1 — Rollback Rehearsal (T-1h)

- [ ] Upstream switch script prova:
  ```bash
  # Test: dış proxy backend staging-sw → staging-sw-2 (simulated, apply YOK)
  # Gerçek: sysadmin tarafından proxy panel veya CLI
  ```
- [ ] Compose state staging-sw'de FROZEN (deploy kilidi: `COMPOSE_DEPLOY_LOCK=1`)
- [ ] Canlı pod restart test senaryosu staging-sw-2'de prova

### Adım 2 — Atomic Switch (T-0)

- [ ] **Dış proxy `212.115.26.190` L4 backend hedef değişim:** `staging-sw → staging-sw-2` (sysadmin iş)
- [ ] **NOT:** DNS A record DEĞİŞMEZ (proxy upstream switch yeterli, TTL risk yok)
- [ ] Anlık: `ai.acik.com` → staging-sw-2 k3d-prod ingress-nginx :30080 → gateway → backend

### Adım 3 — Immediate Smoke (T+5min)

- [ ] Edge real-backend:
  ```bash
  curl -sk https://ai.acik.com/auth/actuator/health → 401 JSON Spring Security
  curl -sk https://ai.acik.com/api/users → 401 JSON
  curl -sk https://ai.acik.com/ → 200 frontend HTML (MFE shell)
  ```
- [ ] Cluster-direct readiness (staging-sw-2): 8 pod Ready
- [ ] JWT E2E: smoke-client token ile `/api/users` 2xx
- [ ] Negatif: bilinmeyen path → 404 (frontend catch-all DEĞİL, gerçek 404)

### Adım 4 — Hot Observation (T+30min → T+60min)

- [ ] Prometheus 5xx ratio: sürekli `< 0.5%`
- [ ] p95 latency: steady-state baseline içi
- [ ] Restart count: `0` unexpected
- [ ] Hikari timeout log: `0`
- [ ] Authz plane uptime: `100%`

### Adım 5 — Continuity Check (T+90min)

- [ ] Canary rollout restart: `kubectl rollout restart deploy/report-service` (single service, non-critical)
- [ ] Restart boyunca gateway upstream 502/504: **0**
- [ ] Yeni pod Ready sonrası smoke tekrar: PASS

### Adım 6 — 72h Warm Rollback Window

- [ ] `staging-sw` compose stack FROZEN ama canlı (trafik dışı) — `docker ps` healthy
- [ ] Rollback tetikleyici:
  - Prod 5xx ratio > 1% 15dk
  - Authz synthetic fail 3x peş peşe
  - Critical bug raporu
- [ ] Rollback adım: dış proxy backend switch `staging-sw-2 → staging-sw`, 30 saniye içinde

### Adım 7 — Decommission Gate (T+72h)

- [ ] Cutover stabil (metric eşikler 72h boyunca)
- [ ] **Decommission karar AYRI** — otomatik değil, explicit onay
- [ ] staging-sw compose stack kapatılır (2 hafta sonra, safety window)
- [ ] DNS cleanup (gerekirse)

## 2. Rollback Senaryoları Matrisi

| Senaryo | İlk 3 Adım | Kanıt Komutu |
|---|---|---|
| Prod k3d regression | 1. Deploy/sync freeze. 2. Dış proxy backend `staging-sw-2 → staging-sw`. 3. Edge smoke doğrula. | `nginx -T` (dış proxy), `curl https://ai.acik.com/` (compose backend HTML) |
| Authz plane down | 1. Edge proxy compose'a geri al. 2. k3d-prod'da permission-service log detay. 3. Teşhis. | `kubectl logs -l app.kubernetes.io/name=permission-service`, edge 401 JSON kontrol |
| CNI/Calico failure | 1. **Önce trafik** compose'a. 2. k3d-prod trafik dışı. 3. TigeraStatus + node debug. | `kubectl -n calico-system get pods`, `labeled pod nc test` |
| ArgoCD bad sync | 1. Auto-sync/self-heal kapat. 2. `git revert <bad-commit>`. 3. Manual sync + rollout verify. | `argocd app sync --dry-run`, `kubectl rollout status` |

**Prensip:** **Önce trafik, sonra teşhis.** Tek-host CNI arızasında in-place fix varsayılmaz.

## 3. Cutover PASS/FAIL Gate (decommission öncesi)

**PASS (decommission aç):**
- 72h metric eşikler stabil
- 0 unexpected rollback tetikleyici
- Authz synthetic PASS 72h

**FAIL (rollback + decommission kapat):**
- 1+ rollback trigger aktivasyon
- Authz synthetic 3x fail
- 5xx ratio > 1% sustained

## 4. Decommission Sırası (T+72h+2 hafta)

- [ ] staging-sw compose stack stop (`docker compose down`)
- [ ] Host-level PG/KC/Vault stop (staging-sw)
- [ ] Compose volume cleanup (1 ay backup retention sonrası)
- [ ] staging-sw host'u diğer iş için yeniden kullanılabilir

## 5. Referanslar

- Codex thread `019d9a75` Tur A3 cutover blueprint
- PLAN.md D30 Cutover Atomic Switch HARD RULE
- PLAN.md Bölüm 1.5 D32 staging-sw-2 Bootstrap Kontrat F1-F9
- S3-stability-soak-pack.md (No-Go gate review template)
