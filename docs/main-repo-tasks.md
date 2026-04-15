# Ana Repo Paralel İşleri — PoC Dilim 1+2+3

> **Repo:** `autonomous-orchestrator` (`/Users/halilkocoglu/Documents/dev/`)
> **Amaç:** K8s (testai.acik.com) ortamının çalışabilmesi için gereken
> backend/image tarafı değişiklikleri. `platform-k8s-gitops` repodaki
> manifest'ler tamamen hazır — sadece image'lar K8s-hazır olunca deploy
> başarılı olacak.
>
> **2026-04-15 deneme sonuçları:** `main-stable` image'lar K8s cluster'da
> RSA private key parse + Flyway migration path + Eureka bean failure ile
> crash loop'a giriyor. Runtime env override yetmiyor; image-level fix şart.
>
> **Sıralama:** Her servisin Eureka bağımsız hale gelmesi + K8s env var
> convention'una uyması gerek. Tüm 8 servis aynı pattern'de güncellenmeli.

---

## 1. auth-service değişiklikleri

### 1.1 Eureka client annotation + import temizliği

```java
// backend/auth-service/src/main/java/.../AuthServiceApplication.java (veya benzeri)
// ÖNCE:
@SpringBootApplication
@EnableEurekaClient            // ← KALDIR
@EnableDiscoveryClient          // ← KALDIR (varsa)
public class AuthServiceApplication { ... }

// SONRA:
@SpringBootApplication
public class AuthServiceApplication { ... }
```

**Grep ile tüm kullanımları bul:**
```bash
cd /Users/halilkocoglu/Documents/dev
grep -rn "@EnableEurekaClient\|@EnableDiscoveryClient" backend/auth-service/
grep -rn "@LoadBalanced" backend/auth-service/
grep -rn "EurekaClientConfig\|DiscoveryClient" backend/auth-service/
```

### 1.2 `@LoadBalanced` RestTemplate/WebClient kaldırma

```java
// ÖNCE:
@Bean
@LoadBalanced                  // ← KALDIR
public RestTemplate restTemplate() { return new RestTemplate(); }

// SONRA (LoadBalanced çıkınca K8s svc DNS direkt çalışır):
@Bean
public RestTemplate restTemplate() { return new RestTemplate(); }
```

Eğer `@LoadBalanced WebClient.Builder` kullanılıyorsa aynı şekilde `@LoadBalanced` kaldırılır.

### 1.3 Servis-arası çağrı URL'leri

auth-service başka servisleri çağırıyorsa (örn. user-service), **URL'yi config'den al ve K8s svc DNS'e point et**:

```yaml
# backend/auth-service/src/main/resources/application-k8s.yml (YENİ DOSYA)
spring:
  application:
    name: auth-service
  cloud:
    discovery:
      enabled: false                                # Eureka bağlantısı kapalı
    kubernetes:
      enabled: false                                # Spring Cloud K8s de gerekmiyor

# Actuator — K8s probe'ları için (D14)
management:
  endpoints:
    web:
      exposure:
        include: health, prometheus, info
  endpoint:
    health:
      probes:
        enabled: true
      show-details: when-authorized
  metrics:
    tags:
      application: ${spring.application.name}

# Servis-arası çağrı URL'leri — K8s svc DNS
services:
  user-service:
    url: ${USER_SERVICE_URL:http://user-service.platform-prod.svc.cluster.local:8089}
  core-data:
    url: ${CORE_DATA_URL:http://core-data-service.platform-prod.svc.cluster.local:8092}
  # ... (auth-service'in gerçekte çağırdığı servislere göre)

# Keycloak (host-level, ExternalName Service üzerinden)
keycloak:
  auth-server-url: ${KEYCLOAK_URL:http://keycloak.platform-prod.svc.cluster.local:8080}
  # svc.cluster.local → Service+Endpoints → host 10.9.10.53:8081 (prod) / 8082 (test)

# Database (host-level, ExternalName Service üzerinden)
spring:
  datasource:
    url: ${DB_URL:jdbc:postgresql://postgres.platform-prod.svc.cluster.local:5432/auth_db}
    username: ${DB_USERNAME}                        # ESO ile Vault'tan gelir
    password: ${DB_PASSWORD}

# Logging - JSON format (Loki)
logging:
  pattern:
    console: '{"ts":"%d{yyyy-MM-dd HH:mm:ss.SSS}","level":"%level","logger":"%logger","message":"%message","traceId":"%X{traceId:-}","spanId":"%X{spanId:-}"}%n'
```

### 1.4 pom.xml dependency temizliği

```xml
<!-- backend/auth-service/pom.xml -->
<!-- KALDIR: -->
<dependency>
  <groupId>org.springframework.cloud</groupId>
  <artifactId>spring-cloud-starter-netflix-eureka-client</artifactId>
</dependency>

<!-- İsteğe bağlı: ribbon/feign de kullanılmıyorsa onları da sil -->
```

**Build testi:**
```bash
cd backend/auth-service
mvn clean package -DskipTests
# BAŞARILI olmalı. Eureka dep referansı başka yerdeyse compile error alırsın.
```

### 1.5 Dockerfile güncelleme (D14: non-root user)

```dockerfile
# backend/auth-service/Dockerfile (güncelleme)
FROM eclipse-temurin:21-jre-alpine

# Non-root user (D14)
RUN addgroup -S spring && adduser -S spring -G spring
USER spring:spring

WORKDIR /app
COPY --chown=spring:spring target/auth-service-*.jar app.jar

# JVM policy (D24): explicit -Xmx, MaxRAMPercentage YOK
ENV JAVA_OPTS="-Xmx384m -XX:+UseG1GC -XX:MaxGCPauseMillis=100"

EXPOSE 8088
# HEALTHCHECK yerine K8s probe kullanılacak (startup/liveness/readiness)

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar app.jar"]
```

---

## 2. api-gateway değişiklikleri

### 2.1 Eureka client temizliği (aynı auth-service gibi)

```bash
grep -rn "@EnableEurekaClient\|@EnableDiscoveryClient\|@LoadBalanced" backend/api-gateway/
```

Bulunanları kaldır.

### 2.2 Route konfigürasyonu — `lb://` → K8s svc DNS

**ÖNCE** (Eureka):
```yaml
# backend/api-gateway/src/main/resources/application.yml (veya application-prod.yml)
spring:
  cloud:
    gateway:
      routes:
        - id: auth-service
          uri: lb://auth-service              # ← EUREKA LOOKUP
          predicates:
            - Path=/auth/**
          filters:
            - StripPrefix=1
```

**SONRA** (K8s DNS):
```yaml
# backend/api-gateway/src/main/resources/application-k8s.yml (YENİ)
spring:
  application:
    name: api-gateway
  cloud:
    discovery:
      enabled: false
    gateway:
      routes:
        # D25 PoC Dilim 1: ingress /auth → api-gateway → auth-service
        # (ingress doğrudan auth-service'e gitmez; gateway zincirini doğrular)
        - id: auth-service
          uri: ${AUTH_SERVICE_URL:http://auth-service.platform-prod.svc.cluster.local:8088}
          predicates:
            - Path=/auth/**
          filters:
            - StripPrefix=1    # /auth/actuator/health → /actuator/health (auth-service'e)
        # Actuator kendi host (gateway'in kendi sağlık probe'ları)
        - id: gateway-actuator
          uri: http://localhost:8080
          predicates:
            - Path=/actuator/**
        # Diğer servisler Dilim 2/3'te eklenir
        # - id: user-service
        #   uri: ${USER_SERVICE_URL:http://user-service...:8089}
        #   predicates: [Path=/users/**]
        #   filters: [StripPrefix=1]    # /users/... → /...
```

### 2.3 pom.xml temizliği (aynı auth-service)

### 2.4 Dockerfile (aynı auth-service pattern)

---

## 3. Docker image build + test

```bash
cd /Users/halilkocoglu/Documents/dev

# auth-service
cd backend/auth-service
mvn clean package -DskipTests
docker build -t auth-service:poc .

# api-gateway
cd ../api-gateway
mvn clean package -DskipTests
docker build -t api-gateway:poc .

# Lokal sanity test (Eureka'sız tek servis kalkabiliyor mu?)
docker run --rm -p 8088:8088 \
  -e SPRING_PROFILES_ACTIVE=k8s \
  -e DB_URL=jdbc:postgresql://host.docker.internal:5432/auth_db \
  -e KEYCLOAK_URL=http://host.docker.internal:8081 \
  auth-service:poc

# Beklenen: Eureka bağlanma hatası YOK, /actuator/health 200 döner.
curl http://localhost:8088/actuator/health
```

---

## 4. k3d cluster'a image import

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
./bootstrap/setup-clusters.sh prod     # lokal k3d-prod cluster
./bootstrap/install-calico.sh prod

# Image'ları k3d cluster'a aktar (GHCR pull şart değil PoC'de)
k3d image import auth-service:poc -c prod
k3d image import api-gateway:poc -c prod
```

---

## 5. Kabul Kriteri (PLAN D25)

Aşağıdaki maddeler **hepsi** yeşil olmadan Dilim 2'ye geçilmez:

- [ ] `api-gateway` Eureka'sız ayağa kalkar (pod READY, `/actuator/health` 200)
- [ ] `auth-service` Eureka'sız ayağa kalkar (pod READY, `/actuator/health` 200)
- [ ] `api-gateway` → `auth-service` çağrısı K8s DNS üzerinden çalışır
  ```bash
  kubectl --context k3d-prod exec deploy/api-gateway -- \
    curl -sf http://auth-service.platform-prod.svc.cluster.local:8088/actuator/health
  ```
- [ ] Host-level Keycloak'a bağlantı çalışır (host.docker.internal veya 10.9.10.53)
- [ ] Host-level PG'ye bağlantı çalışır (aynı)
- [ ] E2E: `curl https://ai.acik.com/auth/actuator/health` 200 döner (host nginx + ingress + api-gateway + auth-service zinciri)
- [ ] E2E login akışı: Keycloak OIDC redirect çalışır, token alınır
- [ ] `kubectl logs` temiz — Eureka bağlantı hatası YOK

---

## 6. Yapılmayacaklar (D26 YAPMA listesi)

- ❌ Geçici K8s içinde Eureka (D7 + D26)
- ❌ `EUREKA_ENABLED=false` env var ile geçici kapatma — annotation + dependency tamamen kaldırılır
- ❌ `@LoadBalanced` bırakıp `lb://` kullanmaya devam — eksiksiz temizlik
- ❌ HPA ekleme (D21 — MVP'de yok)
- ❌ `-XX:MaxRAMPercentage` ekleme (D24 — sadece `-Xmx` explicit)

---

## 7. 2026-04-15 K8s deneme keşifleri (TAM BACKEND için ŞART)

Bu repo manifest'lerini `main-stable` image'lara uygulayıp testai.acik.com
cluster'ında çalıştırma denemesinde **7 ayrı crash sebebi** tespit edildi.
Her biri image-level fix gerektiriyor (runtime env override yetmiyor).

### 7.1 Spring Boot env convention uyumsuzluğu
**Sorun:** ConfigMap `DB_URL` env var kullanılmış → Spring Boot bunu
`spring.datasource.url`'ye map etmez. `'url' must start with "jdbc"`.

**Fix (application-k8s.yml):**
```yaml
spring:
  datasource:
    url: ${SPRING_DATASOURCE_URL}                    # standart
    username: ${SPRING_DATASOURCE_USERNAME}
    password: ${SPRING_DATASOURCE_PASSWORD}
```
Gitops manifest'ler zaten `SPRING_DATASOURCE_*` convention kullanıyor — 
image'ın `application.yml`'si bu env isimlerini okumaya geçmeli.

### 7.2 Eureka bean autoconfig kırığı
**Sorun:** Gateway image'ı `ReactiveDiscoveryClient` bean arıyor, yokluğunda
bean resolution fail. `EUREKA_CLIENT_ENABLED=false` tek başına yetmiyor.

**Fix:** Dependency olarak `spring-cloud-starter-netflix-eureka-client`'ı
`pom.xml`/`build.gradle`'dan **tamamen kaldır** (§2 zaten diyordu ama yapılmadı).
Ayrıca:
```
@SpringBootApplication(exclude = {
  org.springframework.cloud.netflix.eureka.EurekaClientAutoConfiguration.class,
  org.springframework.cloud.client.ReactiveCommonsClientAutoConfiguration.class
})
```

### 7.3 RSA private key parse hatası
**Sorun:** `ServiceJwtConfiguration.parsePrivateKey()` env var `AUTH_SERVICE_JWT_PRIVATE_KEY`
ile gelen base64 DER içeriği parse edemiyor. Format image'ın beklediğinden farklı
(PEM bekliyor olabilir, ya da `-Dspring.config.location` file mount bekliyor).

**Fix seçenekleri (biri seçilmeli):**
1. `application-k8s.yml`'de `@Value("${auth-service.jwt.private-key}")` → Base64
   decode + PKCS#8 parse. Env olarak verilen base64 string'i doğru parse etmeli.
2. Vault PKI secret engine ile cert-style mount (file volume).
3. Runtime key generation (startup'ta keypair üret, memory'de tut) — test için OK,
   prod için redis/sticky session gerekir.

**Önerim: 1** — `application-k8s.yml`'e explicit `@Value + PKCS#8 parser`.

### 7.4 Flyway migration yokluğu + Hibernate validate fail
**Sorun:** Boş DB + `ddl-auto=validate` (default) → `missing table ...` exception.

**Fix:** 
- **Test ortamı**: `SPRING_JPA_HIBERNATE_DDL_AUTO=update` + `SPRING_FLYWAY_ENABLED=false`
  (zaten test overlay'de yapıldı)
- **Prod ortamı**: `db/migration/V*__*.sql` dosyaları `src/main/resources/`'e
  eklenmeli. Her servis için baseline migration şart.

Manifest tarafından prod overlay'de `SPRING_JPA_HIBERNATE_DDL_AUTO=validate`
varsayılan kalıyor — image'da migration olmadan prod'a gidilmemeli.

### 7.5 Actuator health endpoint Spring Security koruması
**Sorun:** `/actuator/health` auth'lu → readiness probe 401 → pod 0/1.

**Fix seçenekleri:**
1. **MANAGEMENT_SERVER_PORT=8081 (ayrı port)** — Spring Boot main port Security
   filter chain'den ayrılır. Manifest tarafından yapıldı (configmap).
   `application-k8s.yml`'de `management.server.port: 8081` ekle.
2. Security config'te `.requestMatchers("/actuator/health").permitAll()` ekle.

**Önerim: 1** + image'da ek port expose.

### 7.6 Memory limit yetersizliği
**Sorun:** 512Mi limit → OOMKilled. Spring Boot 3 + Flyway + Hikari + Tomcat
~600 MB startup needs.

**Fix:** Gitops tarafından `limits.memory: 768Mi` yapıldı. JAVA_OPTS `-Xmx384m`
kalır. Metaspace + direct buffer tampon 384m yeterli.

### 7.7 Docker bridge routing (host PG/KC erişimi)
**Sorun:** `10.9.10.53:5432` pod'dan timeout. Host NAT loopback engelli.

**Fix (altyapı):** `docker network connect platform-test-net <container>` compose
PG + KC'yi k3d bridge'ine ekler. `reconnect-compose-to-test-net.sh` otomatize
eder. Prod için compose `networks:` block'una `platform-test-net` eklemek daha
kalıcı.

Bu **ana repo değil, ops** işi — ama compose docker-compose.yml'e `networks`
eklenmesi uygun:
```yaml
services:
  postgres-db:
    networks: [default, platform-test-net]
```

---

## 8. Tahmini Efor (ana repo tam K8s-hazır image için)

| İş | Efor |
|---|---|
| 8 servis × Eureka removal (dependency + annotation + LoadBalanced) | 1-2 gün |
| 8 servis × `application-k8s.yml` profili (DB, management port, env convention) | 1 gün |
| 8 servis × Flyway baseline migration | 2-3 gün |
| RSA key handling (application-k8s.yml + @Value parsing) | 0.5 gün |
| Dockerfile non-root user (D14) | 0.5 gün |
| CI deploy-backend.yml → `main-stable` tag push (muhtemelen zaten var) | - |
| End-to-end smoke testai.acik.com | 0.5 gün |
| **TOPLAM** | **5-7 gün** |

Dilim 1 (auth + gateway) bu eforun %30'u ile yapılabilir (2 gün) ve testai'de
yeşil smoke verir. Sonra Dilim 2 (5 servis) + Dilim 3 (openfga + frontend)
paralel eklenir.

---

## 9. Manifest Hazırlık Durumu (gitops repo)

Bu repo'da (`platform-k8s-gitops`) **aşağıdaki manifest'ler TAM hazır** —
image rebuild sonrası 10 dk'da deploy edilebilir:

- ✅ 8 servis (auth, gateway, user, variant, core-data, report, schema, openfga)
- ✅ Frontend nginx
- ✅ Gateway routes ConfigMap (6 path prefix)
- ✅ Test overlay scale-to-zero (D17) her servis için
- ✅ Prod overlay image digest placeholder (CI replace edilecek)
- ✅ Ingress path routing (/, /auth, /api, /actuator, /users, /variants, /core, /reports, /schemas)
- ✅ NetworkPolicy default-deny + 5 allow rule
- ✅ ResourceQuota + LimitRange
- ✅ ServiceMonitor tüm servislerde
- ✅ Host bridge ExternalName→IP pin (reconnect script otomatize)
