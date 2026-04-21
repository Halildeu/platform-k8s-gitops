# S1/S2 Acceptance Smoke Runbook

> **Interpretation gate:** Once [../AGENTS.md](../AGENTS.md), ardindan [context-priority-rules.md](./context-priority-rules.md), sonra live truth icin [state/current-state.md](./state/current-state.md) okunur.
> **Source:** K8s-6 Seviye 1 + Seviye 2 acceptance template
> **Pattern:** D29 HARD RULE — Up ≠ Functional ≠ Zanzibar-ready 3 katman smoke
> **Kullanım:** Her deploy sonrası hızlı doğrulama, No-Go gate ön-kontrol, rollback sonrası smoke
> **Role:** Bu dokuman smoke ve kabul kaniti prosedurudur; aktif canli skor veya faz durumu buradan okunmaz.
> **Scope:** testai (k3d-test) + ai.acik.com (k3d-prod, Faz G same-host cutover sonrasi) her iki ortama adapte

---

## 1. 3 Katman D29 Acceptance (HARD RULE)

Tek "yeşil" yeterli DEĞİL. Her deploy/cutover sonrası **3 katman** ayrı kanıtlanır:

| Katman | Ne kanıtlar | Komut/Endpoint | Expected |
|---|---|---|---|
| **Up** | Pod Running, port reachable | `kubectl get pods`, TCP probe | Running 1/1, nc -z success |
| **Functional** | Endpoint response shape doğru | `curl /actuator/health`, `curl /authz/version` | 200 JSON, 401 JSON (chain'e göre) |
| **Zanzibar-ready** | Allow + Deny enforce authoritative | Token'lı `/variants` 2xx + no-token 401 + unauthorized 403 | Synthetic allow/deny kanıtı |

**D29 prensibi:** Bir katman PASS, diğerleri bekliyor olabilir. "Seviye 1 deploy PASS" ≠ "Seviye 1 acceptance full". Rapor her katman ayrı: `Up ✅ / Functional ⚠ partial / Zanzibar-ready ⚠ allow bekler`.

---

## 2. Katman 1 — Up (pod + port reachable)

### 2.1 Cluster-direct pod sağlığı

```bash
CTX=k3d-test   # veya k3d-prod
NS=platform-test   # veya platform-prod

kubectl --context $CTX -n $NS get pods -o wide
# Beklenen: auth-service + api-gateway + user-service + variant-service +
# core-data-service + report-service + schema-service + permission-service
# + openfga + frontend — tümü Running + Ready 1/1
```

**Fail sinyali:**
- `CrashLoopBackOff` → `kubectl logs <pod> --tail=100` + container start failure
- `ImagePullBackOff` → ghcr-pull Secret eksik veya Vault/ESO sorunu
- `Pending` → ResourceQuota veya node not ready

### 2.2 Intra-cluster TCP reachability

```bash
# Labeled busybox pod (bir kez kur, persist)
kubectl --context $CTX -n $NS run smoke-nc --image=busybox:1.36 --restart=Never \
  --labels=app.kubernetes.io/name=smoke-nc -- sleep 3600

# Test connectivity (nc -z -w 2)
for svc in postgres:5432 keycloak:8080 vault:8200 permission-service:8090 \
           auth-service:8088 api-gateway:8080 openfga:8080; do
  kubectl --context $CTX -n $NS exec smoke-nc -- nc -z -w 2 ${svc%:*} ${svc#*:} \
    && echo "$svc ✅" || echo "$svc ❌"
done
# Beklenen: 7/7 ✅

# Cleanup (isteğe bağlı)
kubectl --context $CTX -n $NS delete pod smoke-nc
```

---

## 3. Katman 2 — Functional (endpoint response shape)

### 3.1 Spring Boot actuator health

```bash
# Management port 8081 cluster-direct
for svc in auth-service user-service variant-service core-data-service \
           report-service schema-service permission-service api-gateway; do
  kubectl --context $CTX -n $NS exec smoke-nc -- \
    wget -qO- "http://${svc}:8081/actuator/health" 2>/dev/null | head -c 100
  echo " ← $svc"
done
# Beklenen: 8/8 `{"status":"UP"}` (auth/user/variant/core/report/schema + gateway + permission)
```

### 3.2 Zanzibar Hub cluster-direct (permission-service)

```bash
kubectl --context $CTX -n $NS exec smoke-nc -- wget -qO- \
  "http://permission-service:8090/api/v1/authz/version" 2>&1
# Beklenen: 401 JSON "JWT token zorunludur" (endpoint aktif, Spring Security chain doğru)

kubectl --context $CTX -n $NS exec smoke-nc -- wget -qO- \
  "http://permission-service:8090/api/v1/authz/me" 2>&1
# Beklenen: 401 JSON aynı
```

**Fail sinyali:**
- 404 → endpoint yok, deploy eksik veya wrong image
- 500 → Spring Boot internal error, log incele
- Connection refused → servis up ama port dinlemiyor (port config check)

### 3.3 Gateway cluster-direct (intra-enforcement)

```bash
# Token YOK — deny beklenir
kubectl --context $CTX -n $NS exec smoke-nc -- wget -qO- \
  "http://api-gateway:8080/variants" 2>&1
# Beklenen: 401 JSON "JWT zorunlu"

kubectl --context $CTX -n $NS exec smoke-nc -- wget -qO- \
  "http://api-gateway:8080/auth/login" -X POST --header "Content-Type: application/json" 2>&1
# Beklenen: 401 JSON (login endpoint JWT gerektirir veya 400 malformed)
```

---

## 4. Katman 3 — Zanzibar-ready (allow + deny synthetic)

### 4.1 External edge (D29 authoritative entrypoint)

```bash
HOST=testai.acik.com   # veya ai.acik.com (Faz G same-host cutover sonrasi)

# Deny (unauthenticated)
curl -sk -o /dev/null -w "%{http_code}\n" "https://${HOST}/variants"
# Beklenen: 401

curl -sk -o /dev/null -w "%{http_code}\n" "https://${HOST}/auth/login"
# Beklenen: 401

# Sentinel health
curl -sk -w "%{http_code} %{url_effective}\n" -o /dev/null "https://${HOST}/testai-healthz"
# Beklenen (sadece testai): 200

curl -sk -w "%{http_code}\n" -o /dev/null "https://${HOST}/auth/actuator/health"
# Beklenen: 200
```

### 4.2 Allow synthetic (smoke-client token)

**Prereq:** S2-B3 smoke-client Keycloak confidential client merged + Vault'ta secret + blackbox-exporter bearer_token_file mount aktif.

```bash
# 1. Token al (client_credentials veya password grant)
SMOKE_CLIENT_SECRET=<vault-inject>
TOKEN=$(curl -sk -X POST \
  "https://${HOST}/auth/realms/serban/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=smoke-client" \
  -d "client_secret=${SMOKE_CLIENT_SECRET}" \
  | jq -r .access_token)

# 2. Authenticated allow
curl -sk -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  "https://${HOST}/variants"
# Beklenen: 2xx (yetkili persona)

# 3. Unauthorized scope deny
RESTRICTED_TOKEN=<restricted-persona-token>
curl -sk -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $RESTRICTED_TOKEN" \
  "https://${HOST}/variants"
# Beklenen: 403 (persona yetkisiz)
```

### 4.3 D30 Immutable Artifact Kanıt

```bash
# Overlay tag vs pod imageID eşleşmesi
CLUSTER=test   # veya prod
OVERLAY_TAG=$(yq e '.images[] | select(.name == "permission-service") | .newTag' \
  kustomize/overlays/${CLUSTER}/kustomization.yaml)

POD_IMAGE_ID=$(kubectl --context k3d-${CLUSTER} -n platform-${CLUSTER} \
  get pod -l app.kubernetes.io/name=permission-service \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}')

echo "Overlay tag: $OVERLAY_TAG"
echo "Pod imageID: $POD_IMAGE_ID"
# Eşleşme: immutable tag (sha-<short>) pod imageID digest ile tutarlı
```

---

## 5. D29 Rapor Şablonu

Her smoke session sonunda 5-alan rapor:

```
## S1/S2 Smoke Raporu

**Hedef:** <cluster/host> (örn. k3d-test / testai.acik.com)
**Tarih:** <YYYY-MM-DD HH:MM TZ>
**Trigger:** <deploy PASS / rollback sonrası / scheduled / pre-cutover>

### Katman 1 — Up
- Pod Running: X/Y (hangi pod eksik)
- Intra TCP: 7/7 ✅ veya ❌ <hangi servis>

### Katman 2 — Functional
- Actuator health 8/8 UP: ✅ / ⚠ <hangi servis fail>
- Hub endpoint 401 JWT: ✅ / ❌
- Gateway 401 deny: ✅ / ❌

### Katman 3 — Zanzibar-ready
- External edge deny: ✅ (testai /variants 401) / ❌
- External edge allow synthetic: ⚠ bekliyor (smoke-client) / ✅ 2xx / ❌
- D30 immutable tag: ✅ (sha-<short> eşleşme) / ⚠ moving tag / ❌ drift

### Açık boşluk / next step
<liste>

### Sonuç
Up ✅ / Functional <✅|⚠|❌> / Zanzibar-ready <✅|⚠|❌>
```

---

## 6. Rollback Smoke (prod-cutover-runbook-v2.md §12 atıf)

Rollback sonrası aynı 3 katman smoke uygulanır ama hedef `ai.acik.com` compose backend:
- Katman 1: `docker ps` platform-* sayısı + healthcheck
- Katman 2: `curl https://ai.acik.com/auth/actuator/health` 200 + `/api/users` 401
- Katman 3: compose authn akış (password grant token + authenticated API)

---

## 7. S3 No-Go Gate Referansı

S3 soak sonu cutover onayı öncesi **6/6 blocker 🟢** kontrol:
1. Up (3 katman önkoşul)
2. Functional (8/8 actuator)
3. Zanzibar-ready (allow + deny synthetic)
4. D30 immutable (tüm 8 servis)
5. Observability (Prometheus target up + 4 probe success)
6. Rollback drill (dış proxy switch prova T-1h rehearsal)

Her blocker için bu runbook'un ilgili bölümü çalıştırılır.

---

## 8. Referanslar

- PLAN.md D29 Up ≠ Functional ≠ Zanzibar-ready HARD RULE
- PLAN.md D30 Immutable Artifact HARD RULE
- docs/prod-cutover-smoke-runbook.md (S4-D atomic cutover smoke)
- docs/prod-cutover-runbook-v2.md §12 (aktif same-host rollback sonrasi smoke)
- docs/S4-rollback-runbook.md (historical companion)
- docs/D32-bootstrap-runbook.md (F8 pre-cutover smoke referansı)
- docs/handoff-smoke-client-keycloak.md (smoke-client S2-B3 dev repo iş)
- docs/S3-stability-soak-pack.md No-Go gate (bu runbook altı 6 blocker)
