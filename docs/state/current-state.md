# Current State — Platform K8s Migration

> **Status as of**: 2026-04-20 ~13:30 UTC+3 (Session 10 kapanış)
> **Verified by**: Claude Opus 4.7 + Codex (thread `019daad8`) adversarial review
> **Source set**: Live `kubectl`, `curl`, `docker`, `ssh staging-sw` outputs + repo main HEAD
> **Supersedes**: `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` bölümlerindeki `%99.5`, `DONE + LIVE (Faz H)`, `soft cutover` ifadeleri

---

## 1. 5-Sayaç Dashboard (0-95 skala)

Codex önerisi: `0=yok`, `25=doküman`, `50=partial live`, `75=kanıtlı ama cutover-ready değil`, `90+=gate geçmiş`. Tek host + warm rollback yok → tavan ~95.

| Sayaç | Değer | Claim | Last Evidence | Last Verified | Owner | Next Gate |
|---|---:|---|---|---|---|---|
| **test-k8s** | **75** | testai.acik.com OIDC discovery + frontend render canlı; authz plane henüz gate-ready değil | `curl .../testai.acik.com/realms/platform-test/.well-known` → 200, issuer=https://testai.acik.com; frontend deploy image=`nginx:1.27-alpine`; `openfga-0` CrashLoopBackOff | 2026-04-20 | Claude | OpenFGA recover + blocker alert=0 + ESO CSS Ready |
| **prod-stateful-split** | **65** | platform-pg-prod + kc-prod + vault-prod ayrı stack, 9 backend compose healthy | `docker ps` + `curl ai.acik.com/realms/serban/.well-known` 200 + JWT 401 | 2026-04-20 | Ops | DR drill + warm rollback kanıtı |
| **prod-workload-gitops** | **20** | ArgoCD root + platform-system Synced; platform-prod manual-sync mode + ESO blocked | `kubectl get applications -n argocd` + status OutOfSync/Missing | 2026-04-20 | Claude | ESO Ready + manual sync + imageID D30 |
| **secret-delivery** | **15** | ClusterSecretStore Ready=False (pod → stateful IP refused); ESO helm install var, AppRole secret yaratıldı | ESO controller logs `unable to log in with app role auth: Put ...: connect: connection refused` | 2026-04-20 | Ops | Packet-level kanıt + host-bridge kurtarma **veya** ADR-0003 pod-native pivot |
| **dr-validation** | **0** | Rollback drill YAPILMADI. Preserved volumes var (cold potential) ama test yok | `docker volume ls \| grep platform_` (mevcut) + `docs/S5-disaster-recovery-runbook.md` (runbook var, drill yok) | 2026-04-20 | Ops | Clone + boot + 2x independent smoke PASS |

**Weighted operational continuity**: `~%65` (core platform operasyonel, GitOps + DR açık)

---

## 2. Canlı Trafik Matrisi

| Hostname | Edge | Real Backend Owner | Smoke Evidence |
|---|---|---|---|
| `ai.acik.com` | staging-sw host nginx SSL termine → 127.0.0.1:8080/8081 | compose 9 backend + platform-kc-prod (yeni stack) + platform-pg-prod + platform-vault-prod | `curl /realms/serban/.well-known` 200 + `/api/auth/actuator/health` 401 JWT |
| `testai.acik.com` | staging-sw host nginx → 127.0.0.1:8082 (KC) + 127.0.0.1:9080 (k3d-test ingress) | k3d-test frontend deployment (`nginx:1.27-alpine`) + platform-kc-test + platform-pg-test | `curl /realms/platform-test/.well-known` 200 + frontend HTML render; authz plane blocker: `openfga-0` CrashLoopBackOff |
| `argocd` | k3d-prod cluster-internal (root Application Synced) | ArgoCD hub (argo-cd 7.7.5) | `kubectl get application root -o jsonpath='{.status.sync.status}'` → Synced |
| Monitoring | k3d-prod + k3d-test (kube-prometheus-stack v65.8.0) | Prometheus + Grafana + Loki + Promtail + Tempo | `kubectl get pod -n monitoring` → 5 pod Running test, ~10 pod prod |

---

## 3. Rollback Durumu

| Akış | Status | Preserved Volumes | Last Test Date | RTO/RPO |
|---|---|---|---|---|
| **ai.acik.com → compose legacy** | `cold-potential` (test edilmedi) | `platform_postgres_data`, `platform_vault_data`, `platform_keycloak_data`, `platform_loki_data`, `platform_tempo_data`, `platform_vault_logs`, `platform_vault_snapshots` | **NEVER** | Hedef: RTO≤4h, RPO≤24h (ölçülmedi) |
| **testai.acik.com → compose legacy** | `no rollback path` | Test stateful yeni stack, eski yoktu | N/A | N/A |
| **K8s workload rollback** | `k8s workload henüz apply edilmedi prod` | N/A | N/A | N/A |

**Warm rollback iddiası ihlali**: ADR-0002 §8 `T+72h warm rollback` istiyor. Şu an `cold rollback potential` = sözleşmeye aykırı.

---

## 4. Known Drift (Yazılı Karar Yok)

| Drift | ADR/Kontrat | Gerçek Durum | Owner | Target Date | Blocker Class |
|---|---|---|---|---|---|
| Disk path | `/srv/platform/stateful/{prod,test}/...` (ADR §3.2) | `/home/halil/platform-stateful/...` (override) | Ops | 2026-04-25 | LOW (çalışıyor, doküman eksik) |
| Test Vault port | 8201 (ADR §0.2) | 8301 (eski vault 8201'i tutuyor) | Ops | 2026-04-25 | LOW |
| Vault version | ≥1.21 (eski compose) | 1.17 (yeni host-compose) | Claude | 2026-04-23 | MEDIUM — undocumented version track change |
| k3d CLI | staging-sw'de kurulu (ADR §3.1 varsayım) | YOK, sadece Mac'te | Ops | Nice-to-have | LOW |
| Prod ESO `roleId` | Gerçek UUID overlay patch | Placeholder literal `"eso-runtime"` | Claude | Faz 11 | HIGH (secret delivery block) |
| ClusterIssuer Let's Encrypt | `bootstrap/install-cert-manager.sh` var, apply edilmiş | ClusterIssuer YOK canlıda | Claude | Faz 12 | MEDIUM |
| Test cluster ArgoCD register | Prod hub'dan yönet (ADR §3.7) | k3d-test kayıtlı DEĞİL | Ops | Faz 11 | MEDIUM |
| Handoff split | Append-only 1207 satır | Bu PR ile canonical + historical ayrımı başladı | Claude | Faz 10 | LOW |

---

## 5. Sonraki 4 Faz (Codex Planı)

Detay bu dokümanda tutulur; ayrı session log split'i henüz repo içine alınmadı.

| Faz | Pencere | Done Kriter | No-Go |
|---|---|---|---|
| **10 Dürüstlük Recovery** | D0-D1 (21-22 Nis) | Bu dosya + handoff split + söylem revizyonu | Aktif 1207 satır handoff karar kaynağı kalırsa |
| **11 Secret Delivery Truth** | D2-D4 (23-25 Nis) | Packet-level kanıt → host-bridge kurtarma VEYA Vault pod-native ADR-0003 | Paket kanıtı yoksa ilerleme yasak |
| **12 DR Cold Rollback** | D5-D7 (26-28 Nis) | Clone drill + 2x independent boot-smoke + RTO≤4h | Canlı volume dokunulursa |
| **13 Atomic Cutover** | D8-D11 (29 Nis-3 May) | Nginx upstream switch + T+15 gate + 72h warm rollback | `secret-delivery<80` veya `dr-validation<85` |

---

## 6. Yasak Terimler (Söylem Temizliği)

Bu dokümanda ve sonraki iletişimde **kullanılmayacak**:

- ❌ "Faz H DONE" / "H fiilen yapıldı" → ✅ "Legacy container rm, Faz H formal olarak henüz BAŞLAMADI (soak sonrası)"
- ❌ "Faz G cutover yapıldı" / "soft cutover" → ✅ "Stateful split migration with compose-preserved workload"
- ❌ "%99.5 migration complete" → ✅ "Weighted operational continuity ~%65"
- ❌ "warm rollback available" → ✅ "cold rollback potential, drill yapılmadı"
- ❌ "ESO chain hazır, sadece routing" → ✅ "ESO CSS Ready=False, secret delivery hard-blocked"

---

## 7. Referanslar

- **ADR**: `docs/adr/0002-single-host-dual-cluster.md` (supersedes D32)
- **Roadmap**: `PLAN.md` §0 Faz A-I (Faz 10-13 bu dokümanda ek)
- **Runbook**: `docs/prod-cutover-runbook-v2.md`, `docs/S5-disaster-recovery-runbook.md`
- **Handoff**: `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (Session 1-10 kronolojik, append-only, karar kaynağı değil)
- **Review backlog**: `docs/plan-revision-review-2026-04-20.md` (canonical cleanup backlog, working tree)
- **Codex adversarial reviews**: thread `019daa7f` (adversarial), thread `019daad8` (4-faz plan)
