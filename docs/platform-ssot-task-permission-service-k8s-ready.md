# Task Hand-off: `permission-service` K8s-Ready

> **Kaynak:** K8s-6 session (platform-k8s-gitops, 2026-04-17..19)
> **Hedef:** platform-ssot (Zanzibar-26 veya ardıl session)
> **Öncelik:** P0 — K8s Seviye 1 "Zanzibar runtime aktivasyonu" için blocker prereq

---

## 1. Bağlam (kısa)

Zanzibar-25'te Dilim 1+2 K8s-ready yapıldı (commit'ler `d6e0aa8b` Dilim 1, `fb3a94bc` Dilim 2). **Permission-service** bu kapsam dışında kaldı. K8s-6 tarafında 4-tur Codex mutabakatı (thread `019d9a75-4299-7313-85bb-003a7de680eb`) sonrası:

- **D-003 TRANSFORMED karar**: permission-service OpenFGA authorization hub, kaldırılmayacak (Zanzibar `decisions/topics/zanzibar-openfga.v1.json` D-003 FINAL)
- **K8s-6 PLAN.md D29 (2026-04-17)**: "Zanzibar-ready" seviyesi kanıtı = permission-service hub yayında + OpenFGA `enabled=true` + `/authz/me` + `/authz/version` + synthetic allow/deny enforce
- **K8s-6 Seviye 1 blocker**: permission-service'in K8s'te deploy edilebilmesi için `application-k8s.yml` profile + Eureka temizliği + Dockerfile non-root + CI build gerekli

**Mevcut durum (dev repo):**
- 7/8 servis `application-k8s.yml` var (auth, api-gateway, user, variant, core-data, report, schema)
- `backend/permission-service/src/main/resources/application-k8s.yml` **YOK**
- `GHCR ghcr.io/halildeu/platform-ssot-permission-service:main-stable` image yayında değil

---

## 2. İstenen İş (PR kapsamı)

### 2.1 `backend/permission-service/src/main/resources/application-k8s.yml` yaz

**Referans pattern:** `user-service/application-k8s.yml` (63 satır). Permission-service için özelleştirilmiş taslak:

```yaml
# application-k8s.yml — permission-service (platform-k8s-gitops uyumlu)
# D7 Eureka kaldırıldı, D18 management port 8081, D19 host Service+Endpoints
# D-003 TRANSFORMED: OpenFGA authorization hub
# NOT: Primary datasource PostgreSQL (D31)

spring:
  application:
    name: permission-service
  threads:
    virtual:
      enabled: true
  cloud:
    vault:
      enabled: false                   # K8s'te ESO Secret inject ediyor
    discovery:
      enabled: false                   # Eureka kaldırıldı (D7)
    service-registry:
      auto-registration:
        enabled: false
  datasource:
    driver-class-name: org.postgresql.Driver
    hikari:
      maximum-pool-size: ${DB_POOL_MAX:5}
      minimum-idle: 2
      connection-timeout: 30000
  jpa:
    hibernate:
      ddl-auto: ${SPRING_JPA_HIBERNATE_DDL_AUTO:validate}
    open-in-view: false
    show-sql: ${SPRING_JPA_SHOW_SQL:false}
  flyway:
    enabled: ${SPRING_FLYWAY_ENABLED:true}
    baseline-on-migrate: true
    locations: classpath:db/migration
  security:
    oauth2:
      resourceserver:
        jwt:
          issuer-uri: ${KEYCLOAK_ISSUER_URI}
          jwk-set-uri: ${KEYCLOAK_JWKS_URI}

server:
  port: ${SERVER_PORT:8084}            # Container port 8084 (Dockerfile EXPOSE)

management:
  server:
    port: ${MANAGEMENT_SERVER_PORT:8081}
  endpoints:
    web:
      exposure:
        include: ${MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE:health,info,prometheus}
  endpoint:
    health:
      probes:
        enabled: true
      show-details: never
  tracing:
    enabled: ${MANAGEMENT_TRACING_ENABLED:false}
    sampling:
      probability: ${MANAGEMENT_TRACING_SAMPLING_PROBABILITY:0.1}

# OpenFGA (D-008 Hub config)
openfga:
  api-url: ${ERP_OPENFGA_API_URL:http://openfga.platform-test.svc.cluster.local:8080}
  store-id: ${ERP_OPENFGA_STORE_ID:}
  authorization-model-id: ${ERP_OPENFGA_MODEL_ID:}
  enabled: ${ERP_OPENFGA_ENABLED:true}

# Security (Zanzibar D-003 hub kontratı)
security:
  legacy-api-key:
    enabled: ${SECURITY_LEGACY_API_KEY_ENABLED:false}
  internal-api-key:
    enabled: ${SECURITY_INTERNAL_API_KEY_ENABLED:true}
    value: ${PERMISSION_SERVICE_INTERNAL_API_KEY}

logging:
  level:
    root: ${LOGGING_LEVEL_ROOT:INFO}
    com.acik: ${LOGGING_LEVEL_COM_ACIK:INFO}
```

**Not:** `openfga:` prefix'i dev repoda `erp.openfga.*` ise (OpenFgaProperties bean tanımına bak), prefix'i koru. Yukarıdaki `openfga.*` değilse, `erp.openfga.*` olarak ayarla.

### 2.2 Eureka temizliği

- **pom.xml:** `spring-cloud-starter-netflix-eureka-client` dependency varsa kaldır
- **Java kodu:** `@EnableEurekaClient`, `@LoadBalanced` annotation'ları kaldır
- **Java importlar:** `org.springframework.cloud.netflix.eureka.*` temizle
- **Dilim 1+2 pattern'i takip:** `d6e0aa8b` commit'teki auth-service/api-gateway temizliği

### 2.3 Dockerfile Güncelleme

**Pattern:** `auth-service/Dockerfile` + cd44904 commit (JAVA_TOOL_OPTIONS fix):
- Non-root: `USER 1000:1000`
- JVM env: **`JAVA_TOOL_OPTIONS`** (`JAVA_OPTS` değil — exec form ENTRYPOINT uyumu)
- `EXPOSE 8084 8081`
- `ENTRYPOINT ["java", "-jar", "/app/app.jar"]` (exec form)

### 2.4 CI build + GHCR push

`.github/workflows/deploy-backend.yml` matrix'ine permission-service ekle (muhtemelen zaten var, sadece K8s dilim'lerinde atlandı).

**Beklenen image:** `ghcr.io/halildeu/platform-ssot-permission-service:main-stable` (Dilim 1+2 ile aynı pattern)

### 2.5 auth/user/variant/core services — `PERMISSION_SERVICE_BASE_URL` drift fix

K8s-6 4-tur istişare tespit etti: `auth-service/application-k8s.yml:99` hardcoded `platform-prod.svc` kullanıyor. Test namespace'te override imkansız (ConfigMap'te override yok).

**Düzeltme:** Zaten `${PERMISSION_SERVICE_BASE_URL:...}` env-driven görünüyor. K8s-gitops tarafında (K8s-6 Seviye 1) ConfigMap'e test namespace ekleyeceğim. Ama **user-service, variant-service, core-data-service'te** aynı pattern varsa kontrol et (Dilim 2 commit'te eksik olabilir):

```bash
grep -n "permission-service.platform-" backend/*/src/main/resources/application-k8s.yml
grep -n "user-service.platform-" backend/*/src/main/resources/application-k8s.yml
```

Hardcoded varsa `${SVC_BASE_URL:default}` pattern'ine çevir.

---

## 3. Kabul Kriteri (bu PR için)

- [ ] `backend/permission-service/src/main/resources/application-k8s.yml` dosyası commit'lendi
- [ ] `permission-service/pom.xml` Eureka dependency yok
- [ ] Java kodunda Eureka annotation yok (`@EnableEurekaClient` vb.)
- [ ] `Dockerfile` non-root user + `JAVA_TOOL_OPTIONS` kullanıyor
- [ ] CI build PASS + GHCR image yayında: `ghcr.io/halildeu/platform-ssot-permission-service:main-stable` (latest tag + commit-based tag)
- [ ] `auth/user/variant/core` servislerinde `permission-service.platform-prod.svc` hardcoded yok (env-driven)
- [ ] Local `mvn test -pl permission-service` yeşil
- [ ] Deploy-backend workflow başarılı

---

## 4. K8s-Gitops Tarafında Beklenen İş (ben yapacağım, bilginiz olsun)

Bu PR merge + image yayında olunca K8s-6 Seviye 1:

1. `kustomize/base/apps/permission-service/` oluştur:
   - `deployment.yaml` (8084 http + 8081 management, readiness/liveness, resources `limits: 512Mi/750m`, `JAVA_TOOL_OPTIONS -Xmx256m` test overlay)
   - `service.yaml` (port **8090** → targetPort **8084**, management port 8081)
   - `configmap.yaml` (`SPRING_DATASOURCE_URL: jdbc:postgresql://postgres.PLACEHOLDER_NS.svc:5432/permission_db`, `ERP_OPENFGA_API_URL: http://openfga.PLACEHOLDER_NS.svc:8080`, `ERP_OPENFGA_ENABLED: "true"`, `KEYCLOAK_ISSUER_URI`)
   - `serviceaccount.yaml` + `imagePullSecrets: ghcr-pull`
   - `externalsecret.yaml` (ESO) veya stub `secret.yaml` (PG creds + PERMISSION_SERVICE_INTERNAL_API_KEY + KC client secret)
   - `networkpolicy.yaml` (ingress auth/user/variant/core/report + egress PG/KC/OpenFGA/DNS)
   - `servicemonitor.yaml` (Prometheus scrape `/actuator/prometheus`)
2. Overlay `test/` + `prod/` kustomization.yaml'a image pin + namespace patch
3. ConfigMap patch: `auth/user/variant/core` ConfigMap'lerine `PERMISSION_SERVICE_BASE_URL: http://permission-service.platform-test.svc.cluster.local:8090` + `ERP_OPENFGA_ENABLED: "true"` + `ERP_OPENFGA_API_URL`
4. Deploy testai + Zanzibar smoke tuple:
   - `/authz/me` 200
   - `/authz/version` 200
   - synthetic allow (auth'lı user → core endpoint 2xx)
   - synthetic deny (unauthorized scope → 403)
5. **Yeni PG database:** `permission_db` staging PG'de yaratılmalı (compose PG'de var mı kontrol)

---

## 5. K8s-6 4-tur Codex Mutabakatı Referansları

**Dosyalar:**
- K8s-6 PLAN.md (D-003 drift kapatma, D28-D31, Up≠Functional≠Zanzibar-ready): `PLAN.md` line 38-60 + D28-D31 tablosu
- K8s-6 handoff v3 (drift teşhis): `docs/session-handoff-2026-04-17.md`
- Zanzibar karar registry: `dev/decisions/topics/zanzibar-openfga.v1.json` (D-003 FINAL)
- ADR-0013 Hub role: `dev/docs/02-architecture/services/ops/ADR/ADR-0013-permission-service-hub-role.md`

**Dilim 1+2 pattern commit'leri** (kopya için):
- `d6e0aa8b` — auth-service + api-gateway K8s-ready (Dilim 1)
- `fb3a94bc` — 5 backend K8s-ready (Dilim 2)

---

## 6. Codex İstişare Önerisi (Zanzibar-25/26 kuralı gereği)

Feedback memory kuralı: **Plan istişaresi (Codex MCP ping-pong 2-3 tur) UYGULAMADAN ÖNCE**. Özellikle:

1. **OpenFGA config prefix** — `openfga.*` mı `erp.openfga.*` mı? Bean tanımlarını kontrol et.
2. **PG database adı** — `permission_db` mi `permissions_db` mi? Dev compose env kontrol.
3. **Internal API key güvenlik modeli** — ESO inject mi yoksa per-caller Vault rotation mi?
4. **Multi-datasource** — permission-service'in MSSQL secondary bağlantısı var mı (D31 kapsamı)?

Tamamlanma Codex review'u (kural gereği) CI push öncesi.

---

## 7. Bu Hand-off'u İletme

Kullanıcı bu dosyayı Zanzibar session'ına prompt olarak iletecek. İçerik kendi-içinde yeterli (bağlam + kontrat + kabul kriteri + referanslar). Soru varsa K8s-6 thread (`019d9a75-4299-7313-85bb-003a7de680eb`) üzerinden döner.
