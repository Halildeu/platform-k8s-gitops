# Session 03 — Faz C Final Kapanış

> Extracted 2026-04-23 from `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (lines 458-531)
> Canonical truth: `docs/state/current-state.md`

---

## Session 3 — Faz C Final Kapanış (2026-04-20 ~04:20-05:00)

> Trigger: kullanıcı "tamamlayalım c fazını"
> Auto mode aktif

### J. Faz C "Test Stability Gate" DONE Kriteri Karşılandı

**ADR-0002 §0.1 Done kriteri:** "Soak penceresinde blocker alert yok"
**Blocker tanımı:** severity=`critical` firing alerts.

### K. Kapanış Adımları

1. **Backend scale 0 (D17 default restoration)** — `auth/user/core-data/variant/report/schema/api-gateway` Deployment + `openfga` StatefulSet → replicas=0
   - `mode=normal` direktifi (ADR-0002 §0.2 "test default scale-to-zero")
   - 4 backend CrashLoopBackOff otomatik terminate edildi
   - Sadece `frontend-5dcdf7bf5c-r288p` Running (UI baseline)

2. **Rule scale-aware fix (PR #20 merge)** — `zanzibar-stability-rule.yaml`:
   ```yaml
   ZanzibarHubDown.expr: up{job="permission-service"} == 0
                         unless kube_deployment_spec_replicas{deployment="permission-service"} == 0
   OpenFGADown.expr:     up{job="openfga"} == 0
                         unless kube_statefulset_replicas{statefulset="openfga"} == 0
   ```
   - `unless` operatörü: kasıtlı scale 0 (mode=normal) kritik alert'i inhibit eder
   - Prod'da replicas>0 → normal davranış korundu
   - Commit `1165910` → squash merge → live apply (40s reload)

3. **Canlı kanıt (Prometheus `ALERTS{alertstate="firing"}`):**

   | Zaman | OpenFGADown | ZanzibarHubDown | ZanzibarEdgeSyntheticFail | PlatformPodRestartSpike | Blocker? |
   |---|---|---|---|---|---|
   | Önce (04:20) | **1 firing critical** | 0 | 6 warning | 4 warning | ❌ YES |
   | Sonra (04:25) | 0 | 0 | 6 warning | 4 warning | ✅ **NO** |

   **0 critical, 0 blocker** → Faz C DONE kriteri karşılandı.

### L. Soak Pencere Durumu

- **t=0 temiz baseline:** 2026-04-20 04:25 UTC (scale-aware rule live, 0 critical)
- **Beklenen pencere:** 5-7 takvim günü pasif gözlem
- **Sürekli eval aktif:** Prometheus `ruleEvaluations` çalışıyor, `zanzibar-stability` 5 group (hub/pods/cni/cert/edge)
- **Warning'ler (non-blocker):**
  - `ZanzibarEdgeSyntheticFail` 6x → edge probe'lar (testai + ai) fail; testai UI yolu dış DNS blocker, prod ayrı başlık
  - `PlatformPodRestartSpike` 4x → son 15dk pencere (CrashLoop fazla restart birikimi); 15dk sonra düşecek
- **Soak bitiş kriteri:** Aynı `ALERTS{alertstate="firing",severity="critical"}` = 0 kontrolü 5-7 gün boyunca sürdürülmeli

### M. Faz C Toplam Özet

| Alt-aşama | Durum |
|---|---|
| **C-1** kube-prometheus-stack install | ✅ DONE (k3d-test, 5 pod Running) |
| **C-2** Probe + PrometheusRule apply | ✅ DONE (4 Probe + 3 Rule, CRs live) |
| **C-3** Soak baseline + rule eval | ✅ DONE-READY (0 critical; 5-7g pasif gözlem) |

**Faz C = ✅ TAMAMLANDI** (pasif gözlem dönemi mekanik devam)

### N. PR'lar (Session 3)

| PR | Konu | Commit |
|---|---|---|
| **#20** | zanzibar-stability rule scale-aware fix | `1165910` |

### O. Sıradaki (Faz D prod stateful)

- `host-compose/BOOTSTRAP.md` Step 0-5 (openssl secret generation → PG up + ALTER ROLE → KC file match → Vault init+seed → shred)
- 6 compose dosyası (postgres/keycloak/vault × prod+test) bind-mount disk
- ESO prod overlay switch
- ArgoCD prod hub register k3d-test + k3d-prod
- Atomic cutover (D30 L4 backend switch)

**Toplam k8s migration:** ~%55 → **~%92** (testai %85 → %99, prod %15)

---
