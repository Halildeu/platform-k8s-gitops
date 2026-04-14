# Ana Repo Paralel İşleri — PoC Dilim 1

> **Repo:** `autonomous-orchestrator` (`/Users/halilkocoglu/Documents/dev/`)
> **Amaç:** PoC Dilim 1 (`api-gateway + auth-service`) için kod tarafını K8s'e
> hazırla. Bu işler bittiğinde `platform-k8s-gitops` repodaki manifest'lerle
> deploy edilmeye hazır image'lar olacak.
>
> **Sıralama önemi:** Her iki servis için de değişiklikler aynı PR'da gitmeli
> (Eureka kaldırılınca `auth-service` tek başına Eureka registry'ye kayıt
> olmaz → eski `api-gateway` onu bulamaz). Bu yüzden **`api-gateway` ve
> `auth-service` birlikte güncellenir**.

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
        - id: auth-service
          uri: ${AUTH_SERVICE_URL:http://auth-service.platform-prod.svc.cluster.local:8088}
          predicates:
            - Path=/auth/**
          filters:
            - StripPrefix=1
        # Diğer servisler Dilim 2/3'te eklenir
        # - id: user-service
        #   uri: ${USER_SERVICE_URL:http://user-service...:8089}
        #   predicates: [Path=/users/**]
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
