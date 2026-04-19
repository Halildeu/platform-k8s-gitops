# S4 Rollback Runbook — D30 72h Warm Rollback

> **Source:** PLAN.md D30 Cutover Atomic Switch + 72h Warm Rollback HARD RULE
> **Prereq:** S4-D cutover gerçekleşmiş (`ai.acik.com` → staging-sw-2 upstream)
> **Scope:** Canlı trafik geri alma (staging-sw-2 → staging-sw compose), dar — teşhis SONRA
> **YASAK:** Weighted DNS, partial rollback, paralel deploy (D30 HARD RULE)
> **Codex iter-4/iter-5 uyumu:** Ana gövde 5 dk trafik geri alma; teardown/decommission AYRI bölüm (prod-cutover-smoke-runbook.md §4)

---

## 1. Tetikleyici Matrisi

| Tetikleyici | Eşik | Komut/Dashboard | Aksiyon |
|---|---|---|---|
| **Edge 5xx ratio** | `> 1%` 15dk sustained | `EdgeHigh5xxRatio` alert (PrometheusRule) | Immediate rollback |
| **Authz synthetic fail** | 3× peş peşe (probe_success=0) | `ZanzibarEdgeSyntheticFail` alert (testai/prod 4 probe) | Immediate rollback |
| **Hub DOWN** | permission-service up=0 2dk+ | `ZanzibarHubDown` alert | Immediate rollback |
| **Critical bug raporu** | Kullanıcı/müşteri bildirimi | Slack oncall | Immediate rollback |
| **p95 latency** | `> 2s` 10dk sustained | `EdgeHighLatency` alert | Investigate → rollback candidate |
| **OpenFGA DOWN** | openfga up=0 2dk+ | `OpenFGADown` alert | Authz plane kayıp → rollback |
| **Pod restart spike** | 3+ restart 15dk | `PlatformPodRestartSpike` alert | Investigate → rollback candidate |

**Prensip (D30):** "Önce trafik, sonra teşhis." Immediate tetikleyicilerde teşhis BEKLEMEZ.

---

## 2. 5 Dakika Trafik Geri Alma

### Adım 1 — Deploy Freeze (T+0)

```bash
# ArgoCD: prod application auto-sync + self-heal kapat (halihazırda manuel D30 gereği)
argocd app set platform-prod --sync-policy none
argocd app set platform-prod --self-heal=false

# Slack oncall notify
echo "CUTOVER-ROLLBACK IN PROGRESS — <trigger> tetikleyici" | slack-notify oncall
```

### Adım 2 — Dış Proxy Upstream Switch (T+1min)

**Sysadmin iş** (kurumsal L4 proxy panel veya CLI):
- Dış proxy backend hedef: `staging-sw-2 → staging-sw`
- Anlık (30 saniye ETA)
- DNS değişmez (proxy upstream switch yeterli, TTL risk yok)

### Adım 3 — Edge Smoke Doğrulama (T+3min)

```bash
# Compose backend'e trafik akıyor mu?
curl -sk https://ai.acik.com/ -o /tmp/idx.html
grep -E "(Autonomous|MFE)" /tmp/idx.html        # frontend HTML pattern

curl -sk https://ai.acik.com/auth/actuator/health
# Beklenen: 200 veya 401 (compose backend)

curl -sk https://ai.acik.com/api/users
# Beklenen: 401 JSON "JWT zorunlu" (compose Spring Security)

curl -sk https://ai.acik.com/variants
# Beklenen: 401 JSON (compose backend deny)
```

**PASS kriteri:** 3 endpoint doğru davranışı + compose backend yanıt.
**FAIL:** endpoint'ler timeout veya 502 → compose stack DOWN → escalate P0.

### Adım 4 — k3d-prod Trafik Dışı Kontrol (T+5min)

```bash
# Cluster hâlâ Running (teşhis için) ama trafik almıyor
kubectl --context k3d-prod -n platform-prod get pods -o wide
# Beklenen: 8 pod Ready (teşhis edilebilir durumda)

# Edge smoke k3d-prod'a gitmiyor (serverlb izole)
curl -sk http://10.9.10.53:9080/ -H "Host: ai.acik.com"
# İzole test — sadece debug amaçlı
```

**Rollback PASS:** T+5 kadar `curl https://ai.acik.com/` compose backend'e → ✅

---

## 3. 72h Warm Window İşletim

### 3.1 Deploy Kilidi (T+0 → T+72h)

- ArgoCD `platform-prod` Application **MANUAL sync** + `selfHeal=false` (aynen)
- Git `main` branch'e push: sadece rollback-fix commit'leri ayrı branch + review
- staging-sw compose stack deploy kilidi (`COMPOSE_DEPLOY_LOCK=1` — ops enforce)
- k3d-prod cluster **ayakta** ama trafik dışı (log/metric aç, teşhis için)

### 3.2 Teşhis Süreci

1. **Neden rollback?** Log + metric tab:
   ```bash
   kubectl --context k3d-prod -n platform-prod logs <failing-pod> --tail=500
   kubectl --context k3d-prod describe pod <failing-pod>  # Events
   # Prometheus: query window T-30dk → T+5dk rollback (anomali tespit)
   ```

2. **Codex adversarial review** (CLAUDE.md Codex MCP kuralı):
   - Hangi HARD RULE ihlali? (D18 edge, D29 authoritative, D30 immutable)
   - Hangi test katmanı kaçırıldı? (S1 deploy, S2 acceptance, S3 soak)

3. **Fix plan:**
   - Plan-time istişare (Codex MCP yeni thread)
   - PR taslak + CI + review (staging-sw-2 separate branch'te prova)

### 3.3 Yeni Deploy Denemesi

```bash
# 1. Fix merge + CI GHCR push (yeni sha-<short>)
# 2. Overlay prod tag güncelle
kustomize edit set image <svc>=ghcr.io/halildeu/platform-ssot-<svc>:sha-<new-short>

# 3. Commit + PR (main)
git commit -m "fix(rollback): <reason> — cutover tekrar"
gh pr create

# 4. staging-sw-2 k3d-prod'a yeni image import (manuel test)
docker pull ghcr.io/halildeu/platform-ssot-<svc>:sha-<new-short>
k3d image import -c prod ghcr.io/halildeu/platform-ssot-<svc>:sha-<new-short>

# 5. Smoke ön-doğrulama (staging-sw-2 intra-cluster)
kubectl --context k3d-prod -n platform-prod rollout restart deploy/<svc>
kubectl --context k3d-prod -n platform-prod rollout status deploy/<svc>

# 6. Sysadmin koordineli YENI cutover
#    — docs/prod-cutover-smoke-runbook.md tam rehearsal
```

---

## 4. Doğrulama Smoke (rollback sonrası stabilite)

```bash
# 1. Compose backend sağlık (30 dk süreyle)
while true; do
  curl -sk -o /dev/null -w "%{http_code}\n" https://ai.acik.com/auth/actuator/health
  sleep 30
done
# Beklenen: sürekli 200 veya 401 (JWT zorunlu); 5xx YOK

# 2. Compose stack healthcheck
docker ps --filter "name=platform-" --format "table {{.Names}}\t{{.Status}}"
# Beklenen: 7 servis + PG + KC + Vault (healthy) Up

# 3. Compose backend authn akış (manuel)
TOKEN=$(curl -sk -X POST https://ai.acik.com/auth/realms/serban/protocol/openid-connect/token \
  -d "grant_type=password&client_id=admin-cli&username=admin&password=admin" \
  | jq -r .access_token)
curl -sk -H "Authorization: Bearer $TOKEN" https://ai.acik.com/api/users
# Beklenen: 2xx (authenticated allow)
```

**PASS kriteri:** 30 dk boyunca `/auth/actuator/health` sürekli sağlam + 0 unexpected 5xx.

---

## 5. Rollback Senaryoları Matrisi

| Senaryo | İlk 3 Adım | Kanıt Komutu |
|---|---|---|
| **Prod k3d regression** | 1. Deploy freeze. 2. Dış proxy backend `staging-sw-2 → staging-sw`. 3. Edge smoke. | `curl https://ai.acik.com/` HTML, `/api/users` 401 JSON |
| **Authz plane down** | 1. Edge proxy compose'a. 2. k3d-prod permission-service log detay. 3. Teşhis. | `kubectl logs permission-service`, edge 401 JSON |
| **CNI/Calico failure** | 1. Trafik compose'a. 2. k3d-prod trafik dışı. 3. TigeraStatus + node debug. | `kubectl get tigerastatus`, labeled pod nc test |
| **ArgoCD bad sync** | 1. Auto-sync kapat. 2. `git revert <bad-commit>`. 3. Manual sync + rollout verify. | `argocd app sync --dry-run`, `kubectl rollout status` |
| **GHCR pull fail** | 1. Edge proxy compose'a. 2. ExternalSecret + Vault AppRole audit. 3. Fix + re-sync. | `kubectl describe pod` Events (ImagePullBackOff), `vault kv get` |

---

## 6. Decommission Gate (T+72h+2 hafta)

**Ayrı bölüm — rollback runbook'unun konusu DEĞİL.** docs/prod-cutover-smoke-runbook.md §4 Decommission Sırası oku.

Kısa:
- T+72h stabil → decommission aç (manuel onay)
- +2 hafta safety window → staging-sw compose stop + volume cleanup

---

## 7. Referanslar

- PLAN.md D30 Cutover Atomic Switch + 72h Warm Rollback HARD RULE
- docs/prod-cutover-smoke-runbook.md Adım 6 (72h Warm Rollback Window)
- docs/D32-bootstrap-runbook.md §11 Partial Unwind
- docs/S3-stability-soak-pack.md No-Go gate
- Codex thread `019d9a75` iter-4/iter-5 rollback scope uzlaşı
