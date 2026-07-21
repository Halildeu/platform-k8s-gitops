# RUNBOOK – Zanzibar Canary Deployment

ID: RB-zanzibar-canary
Service: permission-service, core-data-service, user-service, variant-service, openfga
Status: Active (Rev 22 — Synthetic Canary)
Owner: @halil
Last updated: 2026-04-16

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

Zanzibar authorization sisteminin production'a feature-flag ile kademeli geçişini
yönetmek. Rev 22'de **synthetic canary** doctrine'ine geçildi: staging'de gerçek
kullanıcı trafiği yok → fiziksel 48h pencere anlamsız → k6 persona matrix + cold/warm
iki faz + restricted probe ile deterministik **Evidence PASS** üretilir.

**Referanslar:**
- CNS-20260411-001 (ilk tasarım)
- CNS-20260414-001/002 (Rev 19 blocker round)
- CNS-20260415-003 (Rev 22 synthetic canary doctrine)
- CNS-20260415-004 (5 persona matrix tasarım)
- CNS-20260416-001 (PR-1 review, 3 tur ping-pong)
- CNS-20260416-002 (PR-2 polish)

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- **Sorumlu:** Platform Engineering (operasyon), @halil (owner).
- **Ortamlar:** stage (canary), prod (rollout).
- **Servisler:** permission-service (port 8090, OpenFGA Hub — D-008),
  core-data-service, user-service, variant-service, report-service, openfga.
- **SLA hedefleri:** Authz check p95 < 50ms, error rate < 0.5%, deny rate < 10%
  (persona intent'i ayrı sinyal katmanında).

### Ön Koşullar (Pre-conditions)

- [x] **Dalga 0 BLOCKER fix'leri merged:** PR #365 (B1-B5 + 4/4 canary metric wiring)
- [x] **Dalga 1 Stage 1:** Deploy dry-run PASS (22 container healthy, 2026-04-15)
- [x] **Dalga 2 prod-candidate:** PR #394, #396 (Explain UX + ZanzibarGate tooltip)
- [x] **Dalga 3 prep:** PR #397/398/399 (auth-service temizlik + report-service deprecated)
- [x] **Dalga 1 Stage 2 altyapı:** PR #406 (k6 persona matrix runner + setup + wrapper + guardrail extensions)
- [x] **PR-2 polish:** CNS-20260416-002 (bu PR — collector phase + outbox + openfga_up + guardrail tanımları + probe canary-load client)
- [x] **Infra stable:** Vault auto-unseal watcher, OpenFGA v1.11.2 pinned, compose project `platform` izole, smoke workflow containment aktif (PR #392)
- [x] **Canary metric wiring (4+3/7):** `authz_decisions_total` (Counter), `tuple_sync_outbox_failed_total` (Counter), `openfga_circuit_breaker_state` (Gauge), `scope_cache_*` (Gauge) + PR-2 collector ek: `authz_me_p95`, `outbox_pending/oldest_age`, `openfga_up`
- [ ] **STORY-0319** (staging prod-like profile): **Stage 2 gerçek run için ZORUNLU.**
  Local/dev profile permitAll → OpenFGA disabled → tüm check'ler ALLOW → deny_rate
  anlamsız. Local smoke lokal makinede ESTIMATE_ONLY + LOCAL_PERMIT_ALL ile yapılır
  ama staging Evidence PASS için STORY-0319 gerekli.

### Dalga Durumu (Rev 22 post-session)

| Dalga | Durum | Referans |
|---|---|---|
| 0 — Canary Readiness | ✅ | PR #365 |
| 1 Stage 1 — Deploy dry-run | ✅ | 2026-04-15 |
| 1 Stage 2 — Synthetic Canary | ⏸ STORY-0319 bekliyor | RB §3.2 |
| 1 Stage 3 — Evidence PASS | ⏸ Stage 2 sonrası | RB §3.3 |
| 2 — Explain UX | ✅ prod-candidate (E2E pending) | PR #394, #396 |
| 3 prep — PR6a/b/c-0 | ✅ | PR #397/398/399 |
| 3 complete — PR6c-1 | ⏸ ayrı story | TB-11 |
| 4 — Backlog | 14 madde | master-plan Rev 22 §4 |

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

### 3.1 Stage 1 — Deploy (Flags ON, verify health)

**Amaç:** Stack'in Zanzibar özellikleri aktif şekilde ayağa kalkabildiğini
doğrulamak. Yeni image rollout'u + compose healthy check. 2026-04-15'te başarıyla
kapatıldı (dry-run).

```bash
# Step A — Merge sonrası staging'de
ssh staging-sw
cd /home/halil/platform/repo/backend
docker compose pull
docker compose up -d

# Step B — Stack sağlığı
docker ps --filter name=platform- --format '{{.Names}}\t{{.Status}}' | sort
# Beklenen: 22 container, hepsi (healthy)

# Step C — Zanzibar feature flag doğrulaması
docker exec platform-permission-service-1 env | grep ERP_OPENFGA_ENABLED
# Beklenen: ERP_OPENFGA_ENABLED=true

# Step D — Endpoint smoke
curl -sI https://ai.acik.com/
curl -s https://ai.acik.com/api/v1/authz/version
# Beklenen: 200 + {"authzVersion":N}

# Step E — Doctor
bash backend/scripts/doctor-zanzibar.sh --quick
# Beklenen: PASS 61/0/N uyarı
```

**Rollback:** Önceki image tag'ine dön (`docker compose up -d --force-recreate` +
eski GHCR tag). ~1 dk.

### 3.1.A Pre-flight Checklist — Stage 2 Gate (ZORUNLU)

STORY-0319 PR #5 (AppRole setup) sonrası canlı run öncesi tek sefer
PASS olmalı. Herhangi bir FAIL canary run'ı bloklar.

```
[ ] Staging compose healthy — en az 22 platform-* container, unhealthy yok
    docker ps --filter name=platform- --format '{{.Names}}\t{{.Status}}' | wc -l

[ ] doctor-infra.sh A-L PASS (FAIL 0)
    bash backend/scripts/doctor-infra.sh
    Beklenen:
      L1 tüm 7 servis için SPRING_PROFILES_ACTIVE=prod,docker (local yok)
      L2 /authz/check token'sız → 401 veya 403
      L3-L8 ERP_OPENFGA_* + SECURITY_JWT_ISSUER(S) + PERMISSION_SERVICE_BASE_URL
           + AUTHZ_USER_TABLE non-blank

[ ] AppRole setup PASS (RB-vault-approle-setup-stage.md §6 checklist)
    vault read auth/approle/role/backend-deploy-stage/role-id
    Beklenen: 200 (role-id döner)

[ ] Canonical env AppRole-first
    grep -E '^(SPRING_CLOUD_VAULT_ENABLED|VAULT_AUTH_METHOD)=' /home/halil/platform/env/backend.env
    Beklenen:
      SPRING_CLOUD_VAULT_ENABLED=true
      VAULT_AUTH_METHOD=APPROLE

[ ] Auth + permission container actuator Vault health UP (PR #3b wiring)
    curl -fsS http://localhost:8088/actuator/health/vault | jq -r .status
    curl -fsS http://localhost:8090/actuator/health/vault | jq -r .status
    Beklenen: "UP" her ikisi için

[ ] OpenFGA store + model erişilebilir (staging re-init ID'leri)
    curl -fsS http://localhost:4000/stores/${OPENFGA_STORE_ID:-01KPBM48614TZ2F3ZR5AKVXC7B} >/dev/null
    curl -fsS http://localhost:4000/stores/${OPENFGA_STORE_ID}/authorization-models/${OPENFGA_MODEL_ID:-01KPBM488WJK8P7XHK751MDNGG} >/dev/null

[ ] canary-load KC client ulaşılabilir
    curl -fsS -X POST http://localhost:8081/realms/serban/protocol/openid-connect/token \
      -d grant_type=client_credentials \
      -d client_id=canary-load \
      -d client_secret=canary-load-secret-2026 >/dev/null

[ ] 5 persona seed hazır (super_admin, read_only, restricted, multi_role_deny, scope_less)
    mkdir -p .cache/reports/zanzibar-canary/${RUN_ID:?set RUN_ID}
    node backend/scripts/ci/canary/zanzibar-canary-setup.mjs \
      --output .cache/reports/zanzibar-canary/${RUN_ID}/persona-tokens.json
    jq -e '.tokens.super_admin and .tokens.read_only and .tokens.restricted and .tokens.multi_role_deny and .tokens.scope_less' \
      .cache/reports/zanzibar-canary/${RUN_ID}/persona-tokens.json

[ ] k6 binary + Prometheus endpoint erişilebilir
    command -v k6
    curl -fsS ${CANARY_PROM_URL:-http://localhost:9090/api/v1/status/config} >/dev/null

[ ] Evidence artifact dizini mevcut
    test -d .cache/reports/zanzibar-canary/${RUN_ID}
```

**Not — Repo script uyumu:**
- `zanzibar-canary-setup.mjs` `--output <path>` argument destekler (line 26,
  71). AC/TP-0320'de geçen `--use-hybrid-b=false` flag **repo script'inde
  implement edilmemiş**; canonical path (Hybrid B kaldırıldı) zaten default
  davranış. Operator bu farkı evidence'a not düşmeli.
- `CANARY_PROM_URL` env değişkeni repo'da implicit default yok; operator
  Prometheus endpoint'i explicit set etmeli (staging'de
  `http://localhost:9090/api/v1/status/config` sağlıklı response verir).

### 3.1.B Pre-flight Helper (opsiyonel, tek komut)

Operatör tüm checklist'i tek komutla doğrulamak isterse:

```bash
#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
export RUN_ID
VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_TOKEN="${VAULT_TOKEN:?root token required}"
OPENFGA_STORE_ID="${OPENFGA_STORE_ID:-01KPBM48614TZ2F3ZR5AKVXC7B}"
OPENFGA_MODEL_ID="${OPENFGA_MODEL_ID:-01KPBM488WJK8P7XHK751MDNGG}"
CANARY_PROM_URL="${CANARY_PROM_URL:-http://localhost:9090/api/v1/status/config}"

# Step A — Compose healthy
test "$(docker ps --filter name=platform- --format '{{.Names}}' | wc -l)" -ge 22

# Step B — doctor-infra PASS
bash backend/scripts/doctor-infra.sh

# Step C — AppRole PASS
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "X-Vault-Token: ${VAULT_TOKEN}" \
  "${VAULT_ADDR%/}/v1/auth/approle/role/backend-deploy-stage/role-id")" = "200"

# Step D — Canonical env AppRole-first
grep -q '^SPRING_CLOUD_VAULT_ENABLED=true$' /home/halil/platform/env/backend.env
grep -q '^VAULT_AUTH_METHOD=APPROLE$' /home/halil/platform/env/backend.env

# Step E — Actuator Vault health UP
test "$(curl -fsS http://localhost:8088/actuator/health/vault | jq -r .status)" = "UP"
test "$(curl -fsS http://localhost:8090/actuator/health/vault | jq -r .status)" = "UP"

# Step F — OpenFGA store + model
curl -fsS "http://localhost:4000/stores/${OPENFGA_STORE_ID}" >/dev/null
curl -fsS "http://localhost:4000/stores/${OPENFGA_STORE_ID}/authorization-models/${OPENFGA_MODEL_ID}" >/dev/null

# Step G — canary-load KC
curl -fsS -X POST 'http://localhost:8081/realms/serban/protocol/openid-connect/token' \
  -d grant_type=client_credentials \
  -d client_id=canary-load \
  -d client_secret=canary-load-secret-2026 >/dev/null

# Step H — Persona seed
mkdir -p ".cache/reports/zanzibar-canary/${RUN_ID}"
node backend/scripts/ci/canary/zanzibar-canary-setup.mjs \
  --output ".cache/reports/zanzibar-canary/${RUN_ID}/persona-tokens.json" >/dev/null
jq -e '.tokens.super_admin and .tokens.read_only and .tokens.restricted and .tokens.multi_role_deny and .tokens.scope_less' \
  ".cache/reports/zanzibar-canary/${RUN_ID}/persona-tokens.json" >/dev/null

# Step I — k6 + Prom
command -v k6
curl -fsS "${CANARY_PROM_URL}" >/dev/null

echo "[preflight] PASS RUN_ID=${RUN_ID}"
```

### 3.2 Stage 2 — Synthetic Canary (k6 persona matrix + cold/warm)

**Amaç:** Auth-enabled ortamda 5 persona üzerinden synthetic load üretip
operasyonel (Prometheus) + fonksiyonel (k6 custom) iki sinyal katmanında
Evidence PASS almak.

**Ön koşul:** §3.1.A Pre-flight Checklist PASS (AppRole setup + profile
migration + actuator health + persona seed + evidence dizin). Aksi halde
deny_rate = 0 veya persona mismatch, canary sinyal anlamsız.

**Runner:**
```bash
bash backend/scripts/perf/run-zanzibar-canary.sh
```

**Flow:**
```
setup (idempotent seed + write-path version verify, 120s timeout)
  → probe pre-check
  → [ESTIMATE_ONLY=1 → exit] — calibration için
  → k6 cold phase (~30dk, PHASE=cold, SUMMARY_PATH=cold-k6-summary.json)
  → k6 warm phase (cold hemen sonrası, version bump YOK, PHASE=warm)
  → probe post-check
  → Prometheus metrics pull (pull-grafana-metrics.mjs --phase warm)
  → guardrail-check --zanzibar-canary --phase warm
```

**Guardrail ENV (auth-enabled run için ZORUNLU):**

```bash
export CANARY_PROM_URL='http://prometheus.staging:9090'
export CANARY_AUTHZ_CHECK_QUERY='histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket{uri=~"/v1/authz/check|/api/v1/authz/check|/v1/authz/batch-check|/api/v1/authz/batch-check"}[5m]))) * 1000'
export CANARY_AUTHZ_DENY_QUERY='sum(rate(authz_decisions_total{allowed="false"}[5m])) / clamp_min(sum(rate(authz_decisions_total[5m])), 0.001) * 100'
export CANARY_AUTHZ_ERROR_QUERY='sum(rate(http_server_requests_seconds_count{uri=~"/api/v1/authz/.*",status=~"5.."}[5m])) / clamp_min(sum(rate(http_server_requests_seconds_count{uri=~"/api/v1/authz/.*"}[5m])), 0.001) * 100'
export CANARY_AUTHZ_CACHE_MISS_QUERY='authz_cache_miss_count{cache="scope_context"} / clamp_min(authz_cache_hit_count{cache="scope_context"} + authz_cache_miss_count{cache="scope_context"}, 1) * 100'
export CANARY_AUTHZ_DECISIONS_QUERY='sum(increase(authz_decisions_total[35m]))'            # >= 1000 (NO_SIGNAL guard)
export CANARY_OPENFGA_CB_QUERY='max(openfga_circuit_breaker_state)'                        # 0 = CLOSED
export CANARY_AUTHZ_ME_P95_QUERY='histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket{uri="/api/v1/authz/me"}[5m]))) * 1000'
export CANARY_OUTBOX_PENDING_QUERY='sum(tuple_sync_outbox_pending)'                        # drift guard
export CANARY_OUTBOX_OLDEST_AGE_QUERY='max(tuple_sync_outbox_oldest_age_seconds)'          # 5dk üstü = gecikme
export CANARY_OUTBOX_FAILED_QUERY='sum(tuple_sync_outbox_failed_total)'                    # dead-letter guard
export CANARY_OPENFGA_UP_QUERY='min(up{job=~".*openfga.*"})'                               # 1 = up

export KC_CANARY_CLIENT_ID='canary-load'
export KC_CANARY_CLIENT_SECRET='<stage-vault-secret>'
export CANARY_PASSWORD='CanaryPass123!'
```

**5 Persona Matrix (CNS-20260415-004 Codex tasarımı):**

| Persona | Rol / Granule | Scope | Yük (seq/min) | Check/seq | Intentional deny | Beklenen outcome |
|---|---|---|---:|---:|---:|---|
| super-admin | OpenFGA org admin (raw tuple) | COMPANY:1 | 10 | 6 | 0 | Tüm check allow |
| read-only | CANARY_READ_ONLY (5 MODULE VIEW) | COMPANY:1 | 8 | 5 | ~2/min | Read allow, manage deny |
| restricted | CANARY_RESTRICTED (ACCESS/REPORT/COMPANY VIEW; THEME/AUDIT yok) | COMPANY:1 | 6 | 4 | ~2/min | THEME deny, company:2 scope deny |
| multi-role+DENY | CANARY_PURCHASE_MANAGER + CANARY_DENY_DELETE (deny-wins) | COMPANY:1 | 5 | 4 | ~1.7/min | CREATE_PO allow, DELETE_PO blocked |
| scope-less | CANARY_SCOPELESS (VIEW granule; hiç scope yok) | — | 4 | 3 | ~1/min | Feature allow, data scope deny |

**Toplam:** ~160 decisions/min × 30dk ≈ **4800+ decisions** → `authz_decisions_total >= 1000` NO_SIGNAL guard'ı karşılanır. Intentional deny aggregate ~%4-5.

**İki Sinyal Katmanı (CNS-004 uzlaşısı):**

- **Operasyonel guardrail** (Prometheus/Micrometer): persona-agnostic
   - `authz_decisions_total >= 1000`
   - `authz_check_p95_ms < 50`
   - `authz_error_rate_pct < 0.5`
   - `authz_cache_miss_rate_pct_warm < 50` (cold'da soften)
   - `openfga_circuit_breaker_state == 0` (CLOSED)
   - `tuple_sync_outbox_pending_total < 50`, `oldest_age_s < 300`
   - `openfga_up == 1`
- **Fonksiyonel persona** (k6 custom tag'leri): persona intent doğrulaması
   - `authz_persona_outcome{persona, phase, expected, actual, reason}` Counter
   - `authz_persona_mismatch: rate < 0.01` (expected ≠ actual = regresyon)
   - `authz_persona_latency` (persona+phase bazlı p95)

**Ayrım neden önemli:** restricted persona intentional ~%33-70 deny üretir. Aggregate `authz_deny_rate_pct < 10` kırılır — bu TEST TASARIMI ÇAKIŞMASI, sistem arızası DEĞİL. Persona metric intent'i ayırır, aggregate threshold operasyonel.

**Cold vs Warm iki ayrı run:**
- **Cold:** permission-service restart sonrası cache boş; miss rate yüksek doğal.
  `guardrail-check --phase cold` → cache miss threshold soften (log-only).
- **Warm:** cold'dan hemen sonra (version bump YOK); cache ısınmış.
  `guardrail-check --phase warm` → cache miss < 50% STRICT.

**Local smoke (STORY-0319 öncesi "pre-evidence / local calibration"):**

Aşağıdaki modlar Stage 3 Evidence PASS YERİNE GEÇMEZ. Sadece wrapper'ın runnable
olduğunu + decision floor projeksiyonunun doğru hesaplandığını + persona seed
pattern'inin tutarlı olduğunu gösterir. Gerçek Evidence PASS için auth-enabled
staging + STORY-0319 ZORUNLU.

```bash
# Pre-evidence #1 — Sadece projeksiyon (HTTP yok, tahmini decisions/min hesabı)
LOCAL_PERMIT_ALL=1 ESTIMATE_ONLY=1 \
  bash backend/scripts/perf/run-zanzibar-canary.sh
# Beklenen: estimate.json — persona profile × duration → totalDecisionsProjected
# NoSignalRisk: LOW/HIGH flag + intentional deny % band

# Pre-evidence #2 — Traffic smoke (permitAll'da, decision count gerçekten üretir)
LOCAL_PERMIT_ALL=1 SKIP_METRICS=1 SKIP_PROBE=1 SKIP_WRITE_VERIFY=1 \
  bash backend/scripts/perf/run-zanzibar-canary.sh
# Beklenen: cold-k6-summary.json + warm-k6-summary.json
# Note: LOCAL_PERMIT_ALL=1 intentional deny'yi expected=allow'a override eder → mismatch 0
# Guardrail SKIP_METRICS=1 atlanır (permitAll'da deny_rate = 0 anlamsız).
```

**Rollback:**
```bash
ssh staging-sw "cd /home/halil/platform/repo/backend && \
  ERP_OPENFGA_ENABLED=false docker compose up -d permission-service core-data-service"
# ~1 dk, OpenFGA feature flag kapatır, PermitAll fallback aktif değil (C-007 → 401/403)
```

### 3.3 Stage 3 — Synthetic Canary Evidence PASS

**Amaç:** Stage 2 run artifact'lerinin audit checklist'e göre PASS olduğunu belgelemek. **Fiziksel 48h pencere DEĞİL** (Rev 22 doctrine); statik doctor + üretilmiş metric + restricted probe + persona mismatch + cold/warm raporlar.

**Checklist:**

- [ ] `doctor-zanzibar.sh` (full) PASS — tüm A bölümü check'ler
- [ ] Smoke workflow yeşil (manual dispatch: `gh workflow run smoke-zanzibar.yml`)
- [ ] Restricted probe pre ve post **PASS** (superAdmin=false, THEME deny, ACCESS allow)
- [ ] `authz_decisions_total` 30dk window ≥ 1000
- [ ] `authz_persona_mismatch` rate < 0.01 (cold + warm)
- [ ] `openfga_circuit_breaker_state` = 0 (tüm servislerde)
- [ ] `tuple_sync_outbox_pending` < 50, `oldest_age_s` < 300
- [ ] `tuple_sync_outbox_failed_total` artış YOK (baseline sabit)
- [ ] `openfga_up` = 1
- [ ] Cold + Warm raporlar artifact altında: `prom-cold.json`, `prom-warm.json`, `cold-k6-summary.json`, `warm-k6-summary.json`
- [ ] STORY-0319 tamamlandı (staging `SPRING_PROFILES_ACTIVE=prod,docker`)
- [ ] (opsiyonel) Vault KMS auto-unseal story PASS — prod seal stratejisi (Rev 22 backlog #13)

**Prod-trafiği canary (post-STORY-0319 ayrı story):**
Synthetic canary gerçek prod trafik dağılımını (multi-role+DENY çakışmaları, scope cardinality, cache eviction, tuple write churn, Keycloak token/session variant, p99/p999 tail latency) TAM simule ETMEZ. Prod'a geçiş için ileride prod-trafiği bazlı canary story'si gerekecek.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

### 4.1 Guardrail Tablosu

| Metric | Threshold | Cold | Warm | Action on Breach |
|---|---|---|---|---|
| `authz_check_p95_ms` | > 50ms | strict | strict | investigate, cache warm-up |
| `authz_check_p95_ms` | > 150ms | strict | strict | **rollback** |
| `authz_deny_rate_pct` | > 10% | log | strict | tuple sync check (persona intent ayrı!) |
| `authz_error_rate_pct` | > 0.5% | strict | strict | **rollback** |
| `authz_cache_miss_rate_pct` | > 50% | soften | strict | TTL + cache size incele |
| `authz_decisions_total` | < 1000 (30dk) | strict | strict | NO_SIGNAL — yük üretimi başarısız |
| `openfga_circuit_breaker_state` | > 0 | strict | strict | OPEN → **rollback**, HALF_OPEN → monitor |
| `authz_me_p95_ms` | > 100ms | log | strict | /authz/me slowdown |
| `tuple_sync_outbox_pending` | > 50 | strict | strict | outbox poller check |
| `tuple_sync_outbox_oldest_age_s` | > 300 | strict | strict | sync gecikmesi — rollback düşün |
| `tuple_sync_outbox_failed_total` | > 5 artış | strict | strict | dead-letter — manuel inceleme |
| `openfga_up` | < 1 | strict | strict | OpenFGA down — **rollback** |

### 4.2 Log İnceleme

```bash
# Permission-service (hub)
ssh staging-sw "docker logs platform-permission-service-1 --tail 200"

# OpenFGA
ssh staging-sw "docker logs platform-openfga-1 --tail 200"

# Tuple sync outbox
ssh staging-sw "docker logs platform-permission-service-1 2>&1 | grep -iE 'outbox|tuplesync'"

# Authz decision counter (son 5dk)
ssh staging-sw "docker logs platform-permission-service-1 --since 5m 2>&1 | grep -iE 'authz.*decision'"
```

### 4.3 Prometheus Queries (Ad-hoc)

```
# Decision rate
sum(rate(authz_decisions_total[5m]))

# Deny rate
sum(rate(authz_decisions_total{allowed="false"}[5m])) / sum(rate(authz_decisions_total[5m])) * 100

# CB state per service
max by (job) (openfga_circuit_breaker_state)

# Outbox health
sum(tuple_sync_outbox_pending)
sum(tuple_sync_outbox_failed_total)
```

Grafana dashboard: `authz-zanzibar` (infra/grafana/provisioning/dashboards/authz-zanzibar.json)
Alert kuralları: `infra/prometheus/rules/authz-zanzibar-rules.yml`

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

### 5.1 OpenFGA Down

**Belirti:** `up{job=~".*openfga.*"} == 0` veya `openfga_circuit_breaker_state == 1` (OPEN).

**Tanı:**
```bash
docker logs platform-openfga-1 --tail 50
docker exec platform-openfga-1 wget -qO- http://localhost:8080/healthz
```

**Adım:**
- OpenFGA container crashed ise `docker compose restart openfga`
- Fail-closed aktif (`check → false`) — servisler deny-all davranışı.
- 2dk içinde sağlıklı değilse: `ERP_OPENFGA_ENABLED=false` + restart → legacy path'e düş.
- Root cause (memory/DB connection/network partition) incele.

### 5.2 Yüksek Deny Rate (Aggregate)

**Belirti:** `authz_deny_rate_pct > 10%` sustained.

**İlk kontrol:** **Persona matrix çalışıyor mu?** Eğer synthetic canary aktifse, restricted/scope-less persona intentional deny üretir — bu normal. `authz_persona_mismatch` rate'e bak (gerçek regresyon göstergesi).

**Tuple sync tanısı:**
```bash
# En son propagate edilmiş rol
docker exec platform-permission-service-1 curl -s localhost:8080/actuator/metrics/tuple_sync_outbox_pending

# Doctor
bash backend/scripts/doctor-zanzibar.sh --section tuple-sync
```

**Rollback:** `ERP_OPENFGA_ENABLED=false` + restart.

### 5.3 Cache Miss Storm

**Belirti:** `authz_cache_miss_rate_pct > 50%` sustained (warm phase).

**Tanı:**
```bash
docker logs platform-permission-service-1 --since 10m | grep -iE 'cache|version'
# Version bump loop arayın — 1dk'da >5 artış sorunludur.
```

**Adım:**
- Cache TTL düşükse: `SCOPE_CACHE_TTL_SECONDS=60` (default 30) + restart.
- Version bump loop varsa: TupleSyncOutboxPoller fail ediyor olabilir; outbox_failed metric'ine bak.

### 5.4 Outbox Backlog

**Belirti:** `tuple_sync_outbox_pending > 50` veya `oldest_age_s > 300`.

**Tanı:**
```bash
ssh staging-sw "docker exec platform-postgres-db-1 psql -U postgres -d platform -c \
  \"SELECT status, count(*), MIN(created_at) FROM permission_service.tuple_sync_outbox GROUP BY status;\""
```

**Adım:**
- Poller çalışıyor mu? `grep TupleSyncOutboxPoller` logda.
- `SELECT FOR UPDATE SKIP LOCKED` deadlock yok mu? Retry counter 5'i aşmış entry'leri manuel FAIL'e al veya silinmiş role referans ise remove.

### 5.5 Persona Seed Sorunları (Synthetic Canary)

**Belirti:** Setup script exit 1, persona token üretilmemiş, k6 fallback AUTH_TOKEN'a düşmüş.

**Tanı:**
```bash
cat .cache/zanzibar-canary/<RUN_ID>/setup.log
```

**Adım:**
- KC admin token başarısız → `KC_CANARY_CLIENT_SECRET` doğru mu, Keycloak realm `serban` açık mı?
- `POST /api/v1/authz/users/{id}/assignments` 500 → backend NPE? `fix(permission): granule-only role permissions (NPE guard)` PR #406 merged olmalı.
- Write-path version bump timeout → outbox poller gecikmesi, `SKIP_WRITE_VERIFY=1` ile devam edilebilir ama kanıt olarak handoff'ta belirtilmeli.

### 5.6 Canary-Load Client Eksik

**Belirti:** Restricted probe fail; "client_not_found" veya "direct access grants not enabled".

**Adım:**
- **Durable setup (Evidence PASS zorunlu):** `canary-load` client Keycloak realm
   export'una eklenmeli → `infra/keycloak/realm-serban.json` altında Terraform
   veya realm JSON ile deploy edilmeli. STORY-0319 scope'unda bu config durable
   olmalı — hızlı `kc_post` bootstrap sadece geçici.
- Realm'de `canary-load` client tanımlı + Direct Access Grants: Enabled + confidential (secret'li).
- Client secret'i Vault'ta (stage tier): `vault kv get secret/stage/keycloak/canary-load`.
- Fallback: geliştirme için `CLIENT_ID=smoke-client` + Vault `kv/platform/keycloak/smoke-client` (A2a substrate, A2b.1 token contract). `frontend` client'ı A2c cutover sonrası `directAccessGrantsEnabled=false` olduğu için ROPC dönmez; ayrıca smoke-client audience'a `canary-load` YOK, kısa-vadeli test dışında Evidence PASS için kabul edilmez.

### 5.7 Rollback Prosedürü (Stage 2 / 3 detay)

#### Hızlı Rollback (< 1 dk)

```bash
ssh staging-sw
cd /home/halil/platform/repo/backend
# Flag off + selective restart (iki servis)
ERP_OPENFGA_ENABLED=false docker compose up -d permission-service core-data-service
# Verify
curl -s https://ai.acik.com/api/v1/authz/version
# /authz/version 503 dönerse fallback aktif değil, C-007 catch-all authenticated() →
# legacy path /api/permissions üzerinden yetki verir.
```

#### Önceki Image'e Dön (Deploy-Level Rollback)

```bash
ssh staging-sw
cd /home/halil/platform/repo/backend
# Son başarılı SHA'yı bul
cat .env | grep -E "PERMISSION_SERVICE_TAG|CORE_DATA_TAG|USER_SERVICE_TAG"
# Eski tag'e dön
sed -i "s/^PERMISSION_SERVICE_TAG=.*/PERMISSION_SERVICE_TAG=sha-PREVIOUS/" .env
docker compose up -d permission-service core-data-service user-service
```

#### Baseline Yeniden Alma (Canary Sonrası)

Rollback sonrası yeni baseline alırken:
- PR6a/b (Dalga 3) merged durumundaysa, auth bootstrap değişikliği baseline etkilemiş olabilir.
- `backend/scripts/perf/run-zanzibar-canary.sh` tekrar çalıştır → yeni `prom-cold.json`/`prom-warm.json` baseline.
- Değişiklikleri handoff'ta belgele.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- **3 Stage:** Deploy (Stage 1 ✅) → Synthetic Canary (Stage 2, STORY-0319 bekliyor) → Evidence PASS (Stage 3).
- **Rollback < 1 dk** her stage'de (flag OFF + restart).
- **5 persona + cold/warm iki faz** — CNS-20260415-004 tasarım.
- **İki sinyal katmanı:** operasyonel Prometheus + fonksiyonel k6 custom.
- **Evidence PASS = statik doctor + üretilmiş metric + probe + persona mismatch + cold/warm raporlar**.
- **Synthetic ≠ prod traffic** — prod'a geçiş için ayrı story gerekli.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- **Master plan:** `.claude/plans/zanzibar-master-plan.md` (Rev 22)
- **Decision registry:** `decisions/topics/zanzibar-openfga.v1.json` (D-001..D-008 FINAL, C-001..C-008)
- **ADR-0013:** `docs/02-architecture/services/ops/ADR/ADR-0013-permission-service-hub-role.md`
- **TB-11:** `docs/04-operations/TB-11-legacy-permission-inventory.md`
- **Guardrail config:** `backend/scripts/ci/canary/zanzibar-guardrails.json`
- **k6 script:** `backend/scripts/perf/k6-zanzibar-check.js`
- **Setup script:** `backend/scripts/ci/canary/zanzibar-canary-setup.mjs`
- **Orchestration:** `backend/scripts/perf/run-zanzibar-canary.sh`
- **Collector:** `backend/scripts/ci/canary/pull-grafana-metrics.mjs`
- **Guardrail checker:** `backend/scripts/ci/canary/guardrail-check.mjs`
- **Restricted probe:** `backend/scripts/ci/canary/zanzibar-restricted-probe.sh`
- **Doctor:** `backend/scripts/doctor-zanzibar.sh`
- **Smoke isolation:** `docs/04-operations/RUNBOOKS/RB-smoke-isolation.md`
