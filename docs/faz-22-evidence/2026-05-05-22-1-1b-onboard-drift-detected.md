# Faz 22.1.1b Onboard Drift Detection — 2026-05-05

> **Status**: STOP-THE-LINE (live verification PRE-merge tespiti)
> **Trigger**: PR #365 merge sonrası test cluster live verify (kullanıcı 2026-05-05 "tam yetki ile uzun vadeli stabil" mandate)
> **Kategori**: Manifest schema drift (gitops desired ↔ live cluster actual)

## Bağlam

PR #56 (platform-backend) + PR #363 + #364 + #365 (gitops) + drift gate heuristic fix tüm **3-tier drift** (code MODULE / seed JSON relation / live OpenFGA) kapatıyor. Image build + GHCR push + digest pin sırası tamam:

| Adım | Status |
|---|---|
| platform-backend PR #56 (3-tier drift fix) | MERGED 56cc0c9+bd1e5c8 |
| Image build run 25387160094 | SUCCESS — 10/10 service PASS |
| endpoint-admin-service GHCR | sha-bd1e5c8 → sha256:047fc16a |
| gitops PR #363 seed JSON | MERGED |
| gitops PR #364 digest pin | MERGED |
| gitops PR #365 FULL onboard configmap+secret patch | MERGED |
| Drift gate heuristic fix (≥80% threshold) | INCLUDED in #365 |

## Live Verify (ssh staging-sw + kubectl)

Test cluster (k3d-test platform-test ns) state:

```
NAME                                      READY   STATUS      RESTARTS   AGE
endpoint-admin-service-7b5594cd7d-6b6fg   1/1     Running     0          6d20h
```

**Pod imageID**:
```
ghcr.io/halildeu/platform-backend-endpoint-admin-service@sha256:05692ae314db4268a85870872318dc876e5606d028824511e770b807c2225b16
```

→ **Eski digest** (PR #56 öncesi). Pod 6 gün 20 saat öncesinden Running, "compose-era leftover / unmanaged" pattern.

## ConfigMap Schema Drift

### Live cluster ConfigMap (uygulama-spesifik kontrat — 30+ key)

```
KEYCLOAK_ISSUER_URI: https://testai.acik.com/realms/platform-test     ← external URL
KEYCLOAK_JWKS_URI:   http://keycloak:8080/realms/platform-test/protocol/openid-connect/certs  ← internal service host
SERVER_PORT: 8096
SPRING_DATASOURCE_URL: jdbc:postgresql://postgres:5432/endpoint_admin
SPRING_FLYWAY_ENABLED: false                                            ← uygulama Flyway kullanmıyor
SPRING_JPA_HIBERNATE_DDL_AUTO: update
ENDPOINT_ADMIN_DB_SCHEMA: endpoint_admin_service
ENDPOINT_ADMIN_AGENT_AUTH_NONCE_TTL_SECONDS: 600
ENDPOINT_ADMIN_AGENT_AUTH_TIMESTAMP_WINDOW_SECONDS: 300
ENDPOINT_ADMIN_COMMAND_CLAIM_TTL_SECONDS: 300
ENDPOINT_ADMIN_ENROLLMENT_*: (rate limit + TTL)
ENDPOINT_ADMIN_SECRET_*: (encryption key + rotation)
EUREKA_CLIENT_ENABLED: false
SECURITY_AUTH_ALLOWED_CLIENT_IDS: frontend,admin-cli,serban-web,account
SECURITY_JWT_AUDIENCE: endpoint-admin-service,frontend,account,serban-web
DB_POOL_MAX: 5
LOGGING_LEVEL_ROOT: INFO
LOGGING_LEVEL_COM_EXAMPLE_ENDPOINTADMIN: INFO
MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE: health,info,prometheus
MANAGEMENT_ENDPOINT_HEALTH_PROBES_ENABLED: true
MANAGEMENT_ENDPOINT_HEALTH_SHOW_DETAILS: never
MANAGEMENT_SERVER_PORT: 8081
MANAGEMENT_TRACING_ENABLED: false
MANAGEMENT_TRACING_SAMPLING_PROBABILITY: 0.1
SERVER_SHUTDOWN: graceful
SPRING_DATASOURCE_HIKARI_MAXIMUM_POOL_SIZE: 5
SPRING_DATASOURCE_HIKARI_MINIMUM_IDLE: 2
SPRING_LIFECYCLE_TIMEOUT_PER_SHUTDOWN_PHASE: 30s
SPRING_CLOUD_DISCOVERY_ENABLED: false
SPRING_CLOUD_SERVICE_REGISTRY_AUTO_REGISTRATION_ENABLED: false
```

### Gitops PR #365 manifest (charter skeleton — 18 key)

```
APP_NAME: endpoint-admin-service
APP_VERSION: 0.0.0-skeleton
HTTP_PORT: 8080                                                         ← yanlış (uygulama 8096)
MANAGEMENT_PORT: 8081
PERMISSION_SERVICE_BASE_URL: http://permission-service:8084
AUTHZ_USER_TABLE: users
KEYCLOAK_ISSUER_URI: http://platform-keycloak.platform-test.svc.cluster.local:8080/...  ← yanlış (live external URL bekliyor)
KEYCLOAK_JWKS_URI: aynı pattern (yanlış — live internal service host bekliyor)
ADMIN_AUTH_CLIENT_ID: endpoint-admin-portal
AUDIT_LOG_BACKEND: loki                                                ← uygulamada YOK
AUDIT_LOG_RETENTION_DAYS: 365                                          ← uygulamada YOK
PILOT_TIER: lab                                                        ← uygulamada YOK
DISCOVERY_LOCAL_WINDOWS_ENABLED: true                                  ← uygulamada YOK
DISCOVERY_AD_*, DISCOVERY_ENTRA_*, DISCOVERY_M365_*                    ← uygulamada YOK
COSIGN_KEY_REF, COSIGN_LAB_ONLY_EVIDENCE                               ← uygulamada YOK
LOG_LEVEL: INFO                                                        ← uygulama LOGGING_LEVEL_ROOT/COM_EXAMPLE_ENDPOINTADMIN bekliyor
```

## Mismatch Sonuç

PR #365 manifest live cluster'a apply edilirse:

1. **JWT validation FAIL**: `KEYCLOAK_ISSUER_URI` external URL'den internal URL'ye değişir → JWT issuer claim eşleşmez → 401 her request
2. **Readiness probe FAIL**: `SERVER_PORT 8080` ama uygulama 8096'da listen ediyor → probe HTTP 8080 → connection refused → CrashLoopBackOff
3. **Datasource FAIL**: `SPRING_DATASOURCE_URL` env eksik → uygulama default localhost:5432'ye bağlanmaya çalışır → fail
4. **Schema mismatch**: `SPRING_JPA_HIBERNATE_DDL_AUTO=update` eksik (manifest validate kullanır) → schema farklı = fail
5. **Audit/discovery/cosign**: uygulamada bind edilmemiş key'ler — silent ignore ama no benefit

**Sonuç**: PR #365 manifest **canlı uygulama kontratıyla uyumsuz**. Live deploy yapılmamalı.

## Root Cause

Gitops `kustomize/base/apps/endpoint-admin-service/` **charter skeleton scope**ta yazıldı (Faz 22 PR #312 sprint PR-9). Gerçek `endpoint-admin-service` Spring Boot uygulaması **farklı config kontratı** kullanıyor (live cluster pod ile aynı kontrata bağlı).

Faz 22 onboard sprint planı (services.yaml comment):
> "Faz 22.x onboard task: bring endpoint-admin-service into gitops (kustomize base + test overlay), then flip test→enabled here. Until then catalog reflects gitops-governed state, not cluster-actual state."

Bu yazılmış; **uygulanmamış** — manifest skeleton kalmış, gerçek live uygulama kontratına hizalanmamış.

## Aksiyon

### Bu PR (drift dürüstlüğü)

- `services.yaml` `endpoint-admin-service.environments.test`: `enabled` → `deferred` geri (gerçeği yansıt)
- Bu evidence dosyası eklendi
- Onboard sprint pending durumu netleştirildi

### Faz 22.1.1b Onboard Sprint (ayrı, gelecek)

1. **Live ConfigMap → gitops base reverse engineering**:
   - 30+ uygulama-spesifik key live'dan kopyala
   - OVERLAY_MUST_OVERRIDE pattern sadece gerçekten env-specific olanlar için (KEYCLOAK_ISSUER_URI, JWKS_URI, SECURITY_JWT_AUDIENCE, SPRING_DATASOURCE_URL)
2. **Live Secret → gitops secret-stub reverse engineering**:
   - `kubectl get secret endpoint-admin-service-secrets -o yaml` → stringData key set
   - Vault path planning (`kv/platform/endpoint-admin/*`)
3. **ESO ExternalSecret manifest** (`kustomize/overlays/test/eso/endpoint-admin/`)
   - Vault populate runbook (operatör/kullanıcı)
4. **Image digest sync**:
   - Live pod sha256:05692ae3 → gitops pin
   - VEYA: PR #56 yeni image (sha256:047fc16a) live'a manuel selective apply (rolling restart)
5. **D29-EA-Functional smoke** (allow/deny/unauth/fail-closed)
6. **services.yaml** `test: enabled` re-flip (gerçek kanıtlanmış live verify sonrası)

### Cross-Repo Bağlantı

- **Faz 23.1 (notification-orchestrator) Faz 22.1.1b live verified BEKLER** (Codex `019df86f` Q5 PARTIAL absorb): "merge/deploy kapısı açılmamalı until 22.1.1b live acceptance evidence verified"
- Faz 23.1 PR1 Foundation kod hazırlığı paralel ilerleyebilir, **draft state — merge bekliyor**

## D29-EA Ladder Status (truthful — auto mode "no fake work" kuralı)

| Tier | Önceki iddia (yanlış) | Doğru status |
|---|---|---|
| D29-EA-Up | "test=enabled FULL onboard" (PR #365) | ❌ NOT VERIFIED — pod gitops manifest ile değil unmanaged. Manifest live ile uyumsuz |
| D29-EA-Functional | (claim yapılmamış) | ❌ NOT VERIFIED — D29-EA-Up gerek |
| D29-EA-Authorized | (claim yapılmamış) | ❌ NOT VERIFIED |

## Cross-Reference

- platform-backend PR #56 (MERGED) — code drift fix kanıt
- gitops PR #362 (MERGED) — Faz 23.0 charter ACTIVE
- gitops PR #363/#364/#365 (MERGED) — 3-tier drift kapanışı (kod+seed+digest pin)
- bu PR — onboard drift dürüstlüğü
- ADR-0011 BG-1 boundary class: `state-mutation (test cluster)` — onboard sprint sırasında apply
- ADR-0013 D43 outage fallback bypass — Faz 23 notification için aynı disiplin
- RB-faz-23-1-kernel-impl-checklist.md — 22.1.1b live verified önkoşul (geçerli)
