# S2-A1 Shortname Refactor — Apply Plan

> **Source:** K8s-6 S2 (2026-04-19)
> **Status:** Git commit `eb13cb2` tamamlandı, canlı apply **bekliyor**
> **Codex Tur 2 + S2-A1 uzlaşı:** Git-only bugün, apply **smoke-client (S2-B3) sonrası**
> **Sıra:** S2-B3 → S2-X2 (nginx edge migration) → **S2-A1 apply** → S2-B/C/D

---

## 1. Commit İçeriği (`eb13cb2`)

- 8 ConfigMap (api-gateway, auth, user, variant, core-data, report, schema, openfga)
- 2 overlay kustomization (test + prod)
- 23 → 0 PLACEHOLDER_NS match (base'te)
- 16+10 → 0 `.platform-[test|prod].svc.cluster.local` FQDN (overlay'lerde)
- Build render temiz, tüm intra-ns URL shortname

## 2. Apply Etkisi (canlı `kubectl apply`)

### 2.1 ConfigMap Güncellemesi
- `kubectl apply -k overlays/test` → 8 ConfigMap `configured` (shortname değer)
- **Pod restart gerekli** — ConfigMap envFrom değişikliği pod'a otomatik propagate olmaz
- 7 backend + gateway rolling restart → 30-60s her servis için

### 2.2 Gateway Route Revize
- `SPRING_CLOUD_GATEWAY_ROUTES_*_URI` değişimi → gateway pod restart zorunlu (Spring Cloud Gateway hot-reload değil, restart)
- Rolling update ile kısa kesinti (yeni pod Ready öncesi trafik api-gateway'e eski pod'a yönlenir)

### 2.3 Risk Analizi

| Madde | Risk | Mitigasyon |
|---|---|---|
| Pod restart mevcut 9/9 Running pod'ları etkiler | Orta | Rolling update strategy (maxSurge 1, maxUnavailable 0) — yeni pod Ready sonrası eski terminate |
| Gateway restart kısa 502/504 | Düşük | Spring Cloud Gateway terminationGracePeriodSeconds 45 + preStop sleep 5 |
| Caller ConfigMap değişimi authz zincirini geçici kesebilir | Düşük | Pod restart sırasında new ConfigMap env pickup; soft-fail davranış (auth login `Set.of()`, core-data `buildContext` 403) |
| Compose `ai.acik.com` etki | SIFIR | Compose ayrı track, dokunulmadı |

## 3. Apply Sırası (Sonraki Session)

### 3.1 Prerequisites
- [ ] S2-B3 smoke-client merged (authenticated allow synthetic kanıt)
- [ ] S1 acceptance allow synthetic PASS (D29 full Zanzibar-ready)
- [ ] S2-X2 nginx edge migration YAPILDI veya geçici fix stabil 48h

### 3.2 Apply Adımları

**ADIM 1 — Git pull + build doğrula:**
```bash
cd /home/halil/platform-k8s-gitops
git pull
kubectl --context k3d-test kustomize overlays/test > /tmp/s2-a1-apply.yaml
diff /tmp/s2-a1-apply.yaml $(kubectl kustomize overlays/test 2>/dev/null) || echo "git+live render eşit"
```

**ADIM 2 — Smoke-client token ile allow synthetic baseline:**
```bash
TOKEN=$(curl ... smoke-client token)
curl -sk -H "Authorization: Bearer $TOKEN" https://testai.acik.com/variants → 2xx (baseline)
curl -sk -H "Authorization: Bearer $TOKEN" https://testai.acik.com/authz/me → 200
```

**ADIM 3 — Selective apply (ConfigMap + Deployment):**
```bash
# Selective: sadece değişen ConfigMap'ler
kubectl --context k3d-test -n platform-test apply -f <(kubectl kustomize overlays/test | yq e 'select(.kind == "ConfigMap" and (.metadata.name | test("(api-gateway|auth|user|variant|core-data|report|schema|openfga)-config")))' -)
```

**ADIM 4 — Rolling restart (kontrollü):**
```bash
# Gateway önce (routes güncellemesi)
kubectl --context k3d-test -n platform-test rollout restart deploy/api-gateway
kubectl --context k3d-test -n platform-test rollout status deploy/api-gateway --timeout=120s

# Sonra backend'ler sırayla (bağımlılık sırası: auth önce, sonra diğerleri)
for svc in auth-service user-service variant-service core-data-service report-service schema-service permission-service; do
  kubectl --context k3d-test -n platform-test rollout restart deploy/$svc
  kubectl --context k3d-test -n platform-test rollout status deploy/$svc --timeout=120s
done

# OpenFGA (StatefulSet)
kubectl --context k3d-test -n platform-test rollout restart statefulset/openfga
```

**ADIM 5 — Smoke tekrar:**
```bash
# Hub smoke
kubectl --context k3d-test -n platform-test exec smoke-perm -- curl -sk http://permission-service:8081/actuator/health → 200

# Enforcement smoke (deny)
curl -sk -H "Host: testai.acik.com" https://127.0.0.1/variants → 401 JSON

# Enforcement smoke (allow, smoke-client token)
curl -sk -H "Authorization: Bearer $TOKEN" -H "Host: testai.acik.com" https://127.0.0.1/variants → 2xx
```

**ADIM 6 — Env doğrulama:**
```bash
# Yeni pod env'de shortname var mı
kubectl --context k3d-test -n platform-test exec deploy/auth-service -- env | grep -E "KEYCLOAK_URL|SPRING_DATASOURCE_URL"
# beklenen: KEYCLOAK_URL=http://keycloak:8080, jdbc:postgresql://postgres:5432/auth_db
```

## 4. Rollback Senaryosu

```bash
git revert eb13cb2
kubectl --context k3d-test -n platform-test apply -k overlays/test
kubectl rollout restart deploy --all  # tüm backend'ler eski FQDN+PLACEHOLDER_NS'e dön
```

**Rollback downtime:** Aynı rolling strategy, 2-3 dk total.

## 5. Kabul Kriteri

- [ ] 9 pod (veya 10 permission-service dahil) Ready, 0 restart (rolling tamamlandı)
- [ ] Pod env shortname (KEYCLOAK_URL, SPRING_DATASOURCE_URL, SPRING_CLOUD_GATEWAY_ROUTES_*)
- [ ] Hub smoke PASS (cluster-direct)
- [ ] Authoritative edge smoke PASS (deny 401 + allow 2xx)
- [ ] Metric restart delta: rollout penceresi içinde beklenen, dışında 0

## 6. Codex İstişare

Apply öncesi **Codex pre-apply ping-pong zorunlu** (feedback kuralı + D18 swap benzeri risk). Özellikle:
- Rolling restart sıra (gateway vs backend)
- Caller ConfigMap değişimi sırasında authz zinciri kesintisi
- Post-apply Zanzibar smoke kapsamı

## 7. Apply Zamanlama

- **Bugün apply yok** (Codex Tur 2 + ping-pong #2 + S1 acceptance partial)
- **Önerilen pencere:** S2-B3 smoke-client merged + S2-X2 nginx stabil + S3 soak başlangıcı öncesi
- S3-B3 smoke-client paralel ilerlerse, **S2-A1 apply S3 pre-flight** olarak yapılabilir
