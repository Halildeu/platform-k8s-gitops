# Runbook — Deploy Stability Window + Rollout/RS-Split/CrashLoop Response

> Codex 019e256f Session 49 — PR-4 PrometheusRule annotation referansı.

Bu runbook üç PrometheusRule alarmının response prosedürünü tarifler:

- `KubeDeploymentRolloutStuck` — Deployment Progressing=False > 15 dk
- `KubeReplicaSetSplit` — Birden çok aktif RS + yeni RS ready=0 > 10 dk
- `KubePodCrashLooping` — Container CrashLoopBackOff > 5 dk

Üç alarm tamamlayıcıdır:
- **Drift detector timer** (PR #551 `check_env_drift.sh`) — 15 dk cadence; spec drift'i raporlar
- **Gate 1d** (PR #552 `gate-stability-window.sh`) — deploy CI'da tek-shot 2-3 dk pencere
- **Bu PR-4 alarmları** — kontinü kube-state-metrics izlemesi

---

## rollout-stuck

**Tetik**: `Deployment.status.condition[Progressing].status=False` 15 dakikadan uzun süredir bu halde.

**Olasılıkları**:
1. `progressDeadlineSeconds` aşıldı (default 600s); yeni replicas Ready olmuyor
2. Image pull fail (`ImagePullBackOff`)
3. Readiness probe fail (probe path veya port yanlış)
4. ResourceQuota / LimitRange istek karşılayamıyor
5. ESO/Secret eksik — pod env reference'i resolve edilemiyor

**Response adımları**:

```bash
NS="platform-test"   # veya platform-prod
DEPLOY="<alert label deployment>"

# 1. Rollout durumu özet
kubectl -n "$NS" rollout status deploy/"$DEPLOY" --timeout=10s

# 2. En yeni ReplicaSet'i seç (creationTimestamp sort) + olaylar
NEW_RS=$(kubectl -n "$NS" get rs -l app.kubernetes.io/name="$DEPLOY" \
  --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
echo "newest RS: $NEW_RS"
kubectl -n "$NS" describe rs "$NEW_RS" | tail -30

# 3. Yeni pod log + state
kubectl -n "$NS" get pod -l app.kubernetes.io/name="$DEPLOY" -o wide
POD=$(kubectl -n "$NS" get pod -l app.kubernetes.io/name="$DEPLOY" --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
kubectl -n "$NS" describe pod "$POD" | tail -50
kubectl -n "$NS" logs "$POD" --tail=80
```

**Kararlar**:
- Eğer **probe drift** (yeni RS spec'inde yanlış path/port) → runtime drift detector (`check_env_drift.sh`) çıktısını kontrol; PR-time gate (Check 5) bu PR'ı bloklamış olması gerek
- Eğer **ImagePullBackOff** → GHCR manifest existence (`verify_ghcr_manifests.py`); digest gerçekten var mı
- Eğer **ESO secret missing** → `kubectl get externalsecret`, `kubectl describe externalsecret` SecretSynced=true?

**Rollback**: `kubectl rollout undo deploy/$DEPLOY -n $NS` — önceki RS'e geri al.

---

## replicaset-split

**Tetik**: Bir Deployment için 2+ active ReplicaSet (spec.replicas>0) ve **en az bir active RS** 0 ready replicaslara sahip, 10 dakikadan uzun süredir. (Endpoint-admin fingerprint senaryosunda non-ready RS yeni olan; ama PromQL `topk newest` seçmiyor — herhangi bir non-ready active RS alarmı tetikler.)

**Kanonik fingerprint** (2026-05-13 endpoint-admin 16h silent CrashLoop):
- Eski RS: spec.replicas=1, status.readyReplicas=1 (Ready, traffic akıyor)
- Yeni RS: spec.replicas=1, status.readyReplicas=0 (crash)
- Service traffic eski RS'e gidiyor → silent fail; manuel `kubectl get pod` olmadan görünmez

**Response**:

```bash
NS="platform-test"
DEPLOY="<owner_name from alert>"

# Aktif RS'leri listele
kubectl -n "$NS" get rs -l app.kubernetes.io/name="$DEPLOY" \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.replicas}{"\t"}{.status.readyReplicas}{"\n"}{end}' \
  | sort

# Yeni RS (en son creationTimestamp)
NEW_RS=$(kubectl -n "$NS" get rs -l app.kubernetes.io/name="$DEPLOY" \
  --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
kubectl -n "$NS" describe rs "$NEW_RS" | tail -40

# Yeni RS pod'unun log + state
kubectl -n "$NS" get pod -l pod-template-hash="$(echo $NEW_RS | rev | cut -d- -f1 | rev)"
```

**Sınıflandırma**:
1. Probe drift (en yaygın) → `check_env_drift.sh` çıktısını kontrol; PR-time gate'in neden geçtiğini sorgula (servis catalog'da `probe_contract` eksik olabilir)
2. Image hash mismatch — yeni RS yanlış digest'le başlatıldı (ESO/Vault drift veya kasıtlı override)
3. Pod-level securityContext / volumes / ConfigMap kaynağı eksik

**Reconcile**:
- Eski RS'i geriye al: `kubectl -n $NS rollout undo deploy/$DEPLOY` (yeni RS'i ölü-letter pos'a düşürür)
- Repo HEAD'i selective apply: `kubectl -n $NS apply -f <rendered-deployment>.yaml` (overlay'in canonical hali)
- Hot-fix sırasında manuel patch yapıldıysa root cause araştır

---

## crashloopbackoff

**Tetik**: Container `waiting.reason=CrashLoopBackOff` 5 dakikadan uzun süredir.

**Diğer iki alarm'dan farkı**: Bu alarm probe / spec drift değil **runtime ortam** failure'larını yakalar:
- Image-level config bug (env eksik, dependency unreachable)
- DB / KC / Vault egress kırık (network policy + dependency)
- OOM kill
- App-level startup exception

**Response**:

```bash
NS="<namespace>"
POD="<alert label pod>"
CONTAINER="<alert label container>"

# Container exit reason + restart count
kubectl -n "$NS" describe pod "$POD" | grep -A 10 "Last State\|Restart Count\|Exit Code"

# Container son log
kubectl -n "$NS" logs "$POD" -c "$CONTAINER" --tail=200 --previous 2>&1 || \
  kubectl -n "$NS" logs "$POD" -c "$CONTAINER" --tail=200
```

**Tipik patternler**:
- **Exit 137** (OOM) → resource limits arttır veya app memory leak araştır
- **Exit 143** (SIGTERM after probe fail) → liveness probe path/timing kontrol
- **Spring "no decoder accepted"** → KEYCLOAK_ISSUER_URI / JWKS_URI ConfigMap drift
- **`UnknownHostException`** → NetworkPolicy egress eksik (mail-providers / openfga / KC)
- **Hibernate `Schema-validation failed`** → V-series migration ordering veya DDL_AUTO drift (D1.1b restoration)

**Eskalasyon**:
- Eğer 30 dk içinde root cause bulunamazsa rollback (`kubectl rollout undo`)
- Cluster-wide pattern (birden fazla service aynı anda crash) → infrastructure investigation (PG / KC / Vault / network)

---

## Cross-references

- ADR-0011 §4 drift detection guards
- PR #551 — `scripts/drift_detection/check_deployment_contracts.py`
- PR #552 — `scripts/deploy/gate-stability-window.sh`
- PR #554 — normalizer baseline cleanup (cpu/memory + TGP)
- Drift detector systemd timer: `scripts/drift-detection/systemd/`
- AlertManager → GitHub Issues bridge: `kustomize/base/monitoring/alertmanager-bridge/`
