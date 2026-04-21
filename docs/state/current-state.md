# Current State — Platform K8s Migration

> **Status as of**: 2026-04-21 ~11:20 UTC+3 (Session 12 live truth closure refresh)
> **Verified by**: Codex + live `ssh staging-sw`
> **Source set**: Live `kubectl`, `curl`, `docker`, Prometheus API, `ssh staging-sw` outputs + repo HEAD
> **Supersedes**: `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` bölümlerindeki `%99.5`, `DONE + LIVE (Faz H)`, `soft cutover` ifadeleri
> **Interpretation gate**: Önce [../../AGENTS.md](../../AGENTS.md), ardından [../context-priority-rules.md](../context-priority-rules.md) okunur; bu dosya canlı truth snapshot'tır, repo-geneli kural sözleşmesi değildir.

---

## 1. 5-Sayaç Dashboard (0-95 skala)

Codex önerisi: `0=yok`, `25=doküman`, `50=partial live`, `75=kanıtlı ama cutover-ready değil`, `90+=gate geçmiş`. Tek host + warm rollback yok → tavan ~95.

| Sayaç | Değer | Claim | Last Evidence | Last Verified | Owner | Next Gate |
|---|---:|---|---|---|---|---|
| **test-k8s** | **85** | testai.acik.com OIDC discovery + canonical frontend render canlı; frontend `platform-ssot-frontend-testai:sha-2169841` image'ında ve public pull yolunda. Dış deny zinciri yeşil, fakat authenticated allow hâlâ kırık: `testuser` tokenı ile `/variants` `500`, gateway JWT decoder hâlâ `serban` realm JWKS'ine gidiyor | `curl https://testai.acik.com/realms/platform-test/.well-known/openid-configuration` → `200`; root HTML yalnız `testai.acik.com` + `platform-test`; no-token `/variants` ve `/auth/login` → `401`; password-grant token ile `/variants` → `500`; gateway log: `/realms/serban/protocol/openid-connect/certs` + `No suitable decoder accepted the token` | 2026-04-21 | Codex | Gateway JWT realm drift fix (`serban`→`platform-test`) + allow synthetic `2xx/403` + 24h soak |
| **prod-stateful-split** | **63** | `platform-pg-prod` + `platform-vault-prod` canlı; 9 backend compose Up. `platform-kc-prod` edge'den cevap veriyor ama container healthcheck `unhealthy`, bu yüzden prod stateful split tam temiz değil | `docker ps` → 9 backend Up + `platform-pg-prod` healthy + `platform-vault-prod` healthy + `platform-kc-prod` unhealthy; `curl ai.acik.com/realms/serban/.well-known/openid-configuration` → `200`; `/api/auth/actuator/health` → `401` | 2026-04-21 | Ops | `platform-kc-prod` unhealthy kök nedeni + DR drill + KC backup freshness |
| **prod-workload-gitops** | **0** | Live host `k3d-prod` cluster'da ArgoCD, ESO ve `platform-prod` workload yüzeyi YOK; bu başlık şu an doküman/runbook seviyesinde, canlı kontrol-plane olarak doğrulanamıyor | `docker exec k3d-prod-server-0 kubectl get ns` → yalnız system/monitoring namespace'leri; `argocd`, `external-secrets`, `platform-prod` yok; `kubectl get crd | egrep 'argoproj.io|external-secrets.io'` → boş | 2026-04-21 | Ops | Live host `k3d-prod` üzerine ArgoCD + ESO bootstrap + `platform-prod` namespace/sync |
| **secret-delivery** | **55** | Test ClusterSecretStore recovery tamam; kritik backend/OpenFGA secret'leri Sync durumda. `ghcr-pull` SecretSynced olsa da frontend public GHCR pull kullandığı için `frontend` ServiceAccount bağı kaldırıldı. Prod secret-delivery ise beklenenden daha geride: live host `k3d-prod` cluster'da ESO CRD/namespace görünmüyor | Test: `ClusterSecretStore/vault-platform-gitops` Ready=`True`; `ghcr-pull`, `core-data-service-secrets`, `permission-service-secrets`, `user-service-secrets`, `variant-service-secrets` = `SecretSynced=True`; `kubectl -n platform-test get sa frontend -o jsonpath='{.imagePullSecrets}'` → boş. Prod: `kubectl get crd | egrep 'external-secrets.io'` → boş; `kubectl get ns` → `external-secrets` yok | 2026-04-21 | Codex | Live host prod ESO bootstrap + AppRole/roleId truth + sustained reconcile |
| **dr-validation** | **0** | Rollback drill YAPILMADI. Cold potential var ama yalnız kısmi volume/bind-mount kanıtı mevcut; `backup_freshness.prom` içinde `kc=0`, yani backup tarafı eksiksiz doğrulanmış değil | `docker volume ls \| grep platform_`; `/home/halil/platform-stateful/{prod,test}/{postgres,keycloak,vault}`; `~/node_exporter_textfile/backup_freshness.prom` → `pg>0`, `vault>0`, `kc=0`; `docs/S5-disaster-recovery-runbook.md` (runbook var, drill yok) | 2026-04-21 | Ops | Clone + boot + 2x independent smoke PASS + KC backup path |

**Weighted operational continuity**: `~%68` (test frontend parity ve deny zinciri toparlandı; authenticated allow, prod GitOps/ESO ve DR hâlâ açık)

---

## 2. Canlı Trafik Matrisi

| Hostname | Edge | Real Backend Owner | Smoke Evidence |
|---|---|---|---|
| `ai.acik.com` | staging-sw host nginx SSL termine → 127.0.0.1:8080/8081 | compose 9 backend + platform-kc-prod (yeni stack) + platform-pg-prod + platform-vault-prod | `curl /realms/serban/.well-known` 200 + `/api/auth/actuator/health` 401 JWT |
| `testai.acik.com` | staging-sw host nginx → 127.0.0.1:8082 (KC) + 127.0.0.1:9080 (k3d-test ingress) | k3d-test frontend (`platform-ssot-frontend-testai:sha-2169841`) + 8 backend + `openfga` + platform-kc-test + platform-pg-test + platform-vault-test | OIDC `200`; root HTML yalnız `testai.acik.com` + `platform-test`; no-token deny `401`; authenticated `testuser` token ile `/variants` `500`; gateway log'unda `serban` realm cert fetch `404` |
| `argocd` | live host `k3d-prod` cluster'da yüzey doğrulanamadı | `argocd` namespace/CRD yok | `kubectl get ns` → `argocd` yok; `kubectl get crd | grep argoproj.io` → boş |
| Monitoring | test monitoring + host backup freshness metriği | Test: 5 pod Running; host textfile: `pg`/`vault` timestamp var, `kc=0` | Prometheus query `ALERTS{severity="critical",alertstate="firing"}` → boş; `ALERTS{alertname="BackupKCStale",alertstate="firing"}` → `1`; `backup_freshness.prom` içinde `backup_last_success_timestamp_seconds{type="kc"} 0` |

---

## 3. Rollback Durumu

| Akış | Status | Preserved Volumes | Last Test Date | RTO/RPO |
|---|---|---|---|---|
| **ai.acik.com → compose legacy** | `cold-potential` (test edilmedi) | Docker volume: `platform_loki_data`, `platform_tempo_data`, `platform_vault-data`, `platform_vault_logs`, `platform_vault_snapshots`; host bind-mount: `/home/halil/platform-stateful/prod/{postgres,keycloak,vault}` | **NEVER** | Hedef: RTO≤4h, RPO≤24h (ölçülmedi) |
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
| Gateway JWT realm drift | Test authn/authz zinciri `platform-test` realm ile kapanmalı | Authenticated `testuser` tokenı ile `/variants` `500`; `api-gateway` log'u hâlâ `GET /realms/serban/protocol/openid-connect/certs` çağırıyor ve `404` sonrası `No suitable decoder accepted the token` üretiyor | App/Ops | Faz 11 | HIGH |
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
| **11 Secret Delivery Truth** | D2-D4 (23-25 Nis) | Test CSS Ready + kritik ExternalSecret Sync + frontend canonical image + frontend SA public pull path + deny zinciri yeşil + authenticated allow blocker'ı açıkça yazılmış + prod ESO live-host yokluğu dürüstçe yazılmış | `current-state` hâlâ frontend'i `ghcr-pull`a bağlı gösteriyor, authenticated allow zincirini kanıtsız biçimde geçti sayıyor veya prod ESO/GitOps yüzeyini canlı kurulmuş gibi sunuyorsa |
| **12 DR Cold Rollback** | D5-D7 (26-28 Nis) | Clone drill + 2x independent boot-smoke + RTO≤4h | Canlı volume dokunulursa |
| **13 Atomic Cutover** | D8-D11 (29 Nis-3 May) | Nginx upstream switch + T+15 gate + 72h warm rollback | `secret-delivery<80` veya `dr-validation<85` |

---

## 6. Yasak Terimler (Söylem Temizliği)

Bu dokümanda ve sonraki iletişimde **kullanılmayacak**:

- ❌ "Faz H DONE" / "H fiilen yapıldı" → ✅ "Legacy container rm, Faz H formal olarak henüz BAŞLAMADI (soak sonrası)"
- ❌ "Faz G cutover yapıldı" / "soft cutover" → ✅ "Stateful split migration with compose-preserved workload"
- ❌ "%99.5 migration complete" → ✅ "Weighted operational continuity ~%68"
- ❌ "test Zanzibar smoke tamam" → ✅ "Deny zinciri yeşil; authenticated allow hâlâ `500` (`serban` realm drift)"
- ❌ "warm rollback available" → ✅ "cold rollback potential, drill yapılmadı"
- ❌ "ESO chain hazır, sadece routing" → ✅ "Test secret-delivery toparlandı; frontend public GHCR pull path kullanıyor; live host prod cluster'da ESO yüzeyi henüz yok"

---

## 7. Referanslar

- **ADR**: `docs/adr/0002-single-host-dual-cluster.md` (supersedes D32)
- **Roadmap**: `PLAN.md` §0 Faz A-I (Faz 10-13 bu dokümanda ek)
- **Runbook**: `docs/prod-cutover-runbook-v2.md`, `docs/S5-disaster-recovery-runbook.md`
- **Handoff**: `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (Session 1-10 kronolojik, append-only, karar kaynağı değil)
- **Review backlog**: `docs/plan-revision-review-2026-04-20.md` (canonical cleanup backlog)
- **Codex adversarial reviews**: thread `019daa7f` (adversarial), thread `019daad8` (4-faz plan)
