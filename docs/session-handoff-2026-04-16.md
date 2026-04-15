# Session Handoff — 2026-04-16 (Codex Tur-3+4 follow-up fixleri)

> Bir önceki session ([2026-04-15](./session-handoff-2026-04-15.md)) Codex review'unda flag'lenmiş 6 follow-up maddesinin çözüldüğü ve bu turda çıkan 2 yeni maddenin açıldığı session. Kural gereği her tamamlanmış iş Codex MCP review'dan geçti (thread `019d92c6-eff5-7351-ad56-d299269a40b1`, 4 tur).

---

## ⚠️ Kritik Not — Auth-Service Intentionally Degraded

```
auth-service intentionally scaled to 0 in k3d-test due to JWT private key secret parse failure.
Current 401 responses are gateway-level fallback, not backend-auth E2E validation.
Do NOT treat testai auth path as fully validated until #8 is fixed and auth replicas > 0.
```

Bu session'da auth-service Spring bean creation'da `IllegalArgumentException: Illegal base64 character 24` ile patlıyordu (handoff 2026-04-15 §7.3 known issue). `AUTH_SERVICE_JWT_PRIVATE_KEY` env secret bozuk/stub olabilir — `ServiceJwtConfiguration.decodePem` decode edemiyor. Fix **ayrı iş** (aşağıda #8).

`replicas=0` ile CrashLoop durduruldu. Gateway Spring Security reactive chain (`SecurityConfig.java` EndpointRequest.to permitAll olmayan path'lerde `.anyExchange().authenticated()`) JWT olmayan istekleri 401 ile reddediyor — backend'e hiç ulaşmadan. Canlıda smoke 7/7 korundu ama bu "backend auth E2E sağlıklı" demek değil.

---

## 🎯 Bu Session'da Tamamlananlar

### #3 — NetworkPolicy enforcement (gitops commit `241421f`)

**Teşhis**: Calico gerçekten enforce ediyor; ama `allow-egress-intra-ns` var, `allow-ingress-intra-ns` YOK → asimetrik. Tüm gateway → backend test'leri 5s timeout.

**Fix**: `kustomize/base/netpol/allow-ingress-intra-ns.yaml` — platform `part-of` label'lı pod'lar arasına ingress allow. `allow-egress-intra-ns` ile simetrik.

**Sonuç**:
- gateway → auth:8088 → önce timeout, sonra backend cevabı ✅
- backend → backend ingress allow ✅  
- Dışarı (kubernetes.default) hâlâ timeout ✅ (doğru)

### #4 — api-gateway actuator dead config temizliği (aynı commit)

`MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE` listesinden `gateway` kaldırıldı. Spring Cloud Gateway Server API dependency mevcut image'da yok → `/actuator/gateway` zaten 404. Dead config; ileride dependency eklenirse auto-unauth riski.

### #6 — Rolling restart 30s 502 fix (gitops commit `d47c06c`)

7 deployment + 7 ConfigMap:
- `spec.minReadySeconds: 10` — endpoint propagation penceresi
- `lifecycle.preStop.exec: ["sh","-c","sleep 5"]` — endpoint deregister süresi
- `SERVER_SHUTDOWN: graceful` + `SPRING_LIFECYCLE_TIMEOUT_PER_SHUTDOWN_PHASE: 30s`

Ek (Codex Tur-4 önerisi): `terminationGracePeriodSeconds: 30 → 45` — preStop 5s + Spring 30s + buffer (gitops commit pending, bu PR).

### PG Connection Overflow Hotfix (gitops commit `bb06e5e`)

Wave B rollout sırasında auth-service `remaining connection slots reserved` — breakdown:
```
platform @172.19.0.2 (k3d-test)      40 conn (7×10 pool, rolling + 2 rs)
postgres @172.18.x.x (compose prod)  50 conn
misc                                 16 conn
TOTAL 106 / max_connections=100
```

**Runtime hotfix**: `ALTER SYSTEM SET max_connections = 200` + `docker restart platform-postgres-db-1` — ~30s compose prod kesintisi, Hikari auto-reconnect.

**Gitops baseline**: 7 ConfigMap'e `HIKARI_MAXIMUM_POOL_SIZE=5, MINIMUM_IDLE=2` (was default 10). Yeni teori: 7×5=35 steady, ~70 rolling peak. PG compose command kalıcılığı → **follow-up #7**.

### #5 — auth-service /env 500 → 404 (ana repo **PR #410** OPEN)

**Root cause**: gateway StripPrefix=1 → auth main port 8088 receives `/actuator/health` (actuator serving on 8081 due to `MANAGEMENT_SERVER_PORT=8081`) → Spring MVC finds no handler → `NoResourceFoundException` → `GlobalExceptionHandler.handleGeneric(Exception)` wraps as 500.

**Fix**: `@ExceptionHandler(NoResourceFoundException.class)` → 404 JSON. 1 file, 10 lines.

**Live validation BLOCKED**: RSA private key parse (follow-up #8). PR body'de açık not.

---

## 📋 Sonraki Session — Açık Follow-up'lar

### 🔴 #7 — PG max_connections kalıcı fix

Ana repo `backend/docker-compose.yml` postgres service'ine `command` ekle:

```yaml
services:
  postgres-db:
    command: ["postgres", "-c", "max_connections=200"]
```

(Ya da mevcut command'a `-c max_connections=200` ekle.)

Runtime `ALTER SYSTEM` kalıcı olabilir (volume persistence) ama **source of truth compose olmalı**. Compose restart = ~30s prod kesintisi, kabul edilebilir.

### 🔴 #8 — RSA Private Key Parse (auth-service)

`AUTH_SERVICE_JWT_PRIVATE_KEY` env value `ServiceJwtConfiguration.decodePem`'de `Illegal base64 character 24` (0x18 CAN control char).

**Debug sırası (Codex önerisi)**:
1. K8s Secret app'e tam olarak ne veriyor? (raw PEM / base64 PEM / DER base64 / stub string)
2. Kod tam olarak ne bekliyor? decodePem PEM header/footer strip edip body base64 decode mu?
3. ESO/Vault şeması: `stringData` raw PEM mi, `data` base64-encoded raw PEM mi?

K8s Secret nüans: YAML `data` base64'tür ama pod env decode edilmiş gelir. Uygulama kendi base64 decode yapıyorsa **double encoding** sorusu net olmalı.

Illegal char 24 (CAN, 0x18) PEM header değil; **bozuk/binary/stub value** ihtimali yüksek. Handoff'ta `auth-service-secrets` stub olarak `platform/change-me-local-only` yazıyordu → muhtemelen bu.

Kod tarafında defensive parsing:
- raw PEM kabul et
- tek satır escaped `\n` PEM kabul et  
- base64 DER/PKCS8 açık algıla
- hatada secret içeriğini loglama (format/length/prefix sınıfı yeter)

İlk aksiyon: **Secret format doğrulaması** (kubectl get secret -o jsonpath, sonra base64 -d | head).

### 🟡 #1 — Dilim 1+2 PR (backup branch `k8s-migration-dilim1-full`)

Feature execution contract `delivery_scope:uncovered_change` için Dockerfile + application.properties için delivery gate pattern gerek. `extensions/PRJ-PM-SUITE/contract/feature_execution_contract.v1.json` revizyon veya ayrı story metadata.

### 🟡 #2 — GitOps drift (CI multi-arch + immutable digest)

Overlay `main-stable` ↔ canlı `k8s-poc` tag tutarsızlığı. CI'da `linux/amd64` build + GHCR digest push + GitOps repo image update. Büyük iş, ayrı session.

### 🟡 Yeni Codex bulguları

- **Host bridge egress 0.0.0.0/0** — sadece host CIDR'ye daraltma
- **Namespace pod-create RBAC** — label-NetPol bypass riskini kapama
- **Backend arası port-specific NetPol** — intra-ns `from.podSelector` geniş, prod için daralt
- **#6 live rolling test** — k3d-test tek replica yetersiz; geçici replicas=2 + continuous curl altında gözlem

---

## 🔨 Bu Session Commit'leri

**platform-k8s-gitops (main)**:
- `241421f` — #3 NetPol + #4 gateway expose cleanup
- `d47c06c` — #6 graceful + minReadySeconds
- `bb06e5e` — Hikari pool 5/min 2 baseline
- (pending) `terminationGracePeriodSeconds 30→45` (Codex Tur-4 net önerisi)
- (pending) bu handoff dosyası

**platform-ssot (autonomous-orchestrator)**:
- PR **#410** OPEN — auth-service NoResourceFoundException handler (#5)
- PR **#407** MERGED squash `5929c6b8` — actuator permit hardening (dün)

---

## 🚀 Sonraki Session — İlk Komutlar

```bash
# Durum özeti
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git log --oneline -5

cd /Users/halilkocoglu/Documents/dev
git branch --show-current  # bekleniyor: fix-auth-env-404 veya main
gh pr view 410 --json state,mergeable,mergeStateStatus

# Canlı durum
ssh staging-sw 'export PATH=$HOME/.local/bin:$PATH; \
  kubectl --context k3d-test -n platform-test get pods; \
  curl -sk -o /dev/null -w "testai-hz: %{http_code}\n" https://testai.acik.com/testai-healthz; \
  curl -sk -o /dev/null -w "ai: %{http_code}\n" https://ai.acik.com/; \
  docker exec platform-postgres-db-1 psql -U postgres -tAc "SHOW max_connections;"'

# Eğer auth deployment'ı restart gerekiyorsa (not: hâlâ RSA key sorunu devam ediyor)
ssh staging-sw 'kubectl --context k3d-test -n platform-test scale deployment/auth-service --replicas=1'
# Fakat Secret fix'i olmadan yine CrashLoop — #8 işi ilk.
```

---

## 🛡️ Güvenlik & İzolasyon Durumu

- `ai.acik.com` (compose) HİÇ dokunulmadı, 200 ✅
- `testai.acik.com` intranet-only, 7/7 401 + healthz 200 ✅
- Sectigo wildcard cert paylaşılıyor
- **NetworkPolicy artık GERÇEKTEN enforce** (intra-ns allow + default-deny + ingress-nginx + monitoring scrape)
- SSH deploy key read-only
- Git remotes: `git@github.com:Halildeu/platform-k8s-gitops.git`, `github.com/Halildeu/platform-ssot.git`

---

## 📊 Kaynak Durumu (staging-sw)

```
4 vCPU · 24 GiB RAM · ~97 GiB disk
k3d-test cluster: 9 deployment (auth r=0 currently, 6 backend + openfga + frontend + gateway r=1)
PG max_connections: 200 (runtime ALTER SYSTEM; compose command patch follow-up #7)
PG active conn: ~78
platform-test-net bridge: postgres + keycloak bağlı (Codex'in Bash 3 uyumluluk uyarısı: reconnect script macOS için hâlâ `declare -A`)
```

---

## 🌙 Son Söz

Codex Tur-3+4'teki 6 follow-up'ın 4'ü tamamen çözüldü (#3, #4, #6, #5). 2 yeni kritik (#7 PG compose, #8 RSA key) açıldı. #1 ve #2 büyük işler (Dilim 1+2 PR delivery contract + GitOps digest drift) → ayrı session.

Auth scale=0 kabul edilebilir ara durum; gateway 401 fallback zinciri prod cutover için **yeterli değil** (valid JWT E2E yolu yok). #8 çözülmeden prod kurulumu değerlendirme dışı.

Tüm iş Codex review'dan geçirildi (kural gereği), thread `019d92c6-eff5-7351-ad56-d299269a40b1`, 4 tur.

Sonraki session: #8 RSA key (en kritik blocker) + #7 PG compose kalıcılık + Dilim 1+2 PR.
