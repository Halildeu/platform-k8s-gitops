# RB — Faz 22.5 M2 mTLS auto-enroll: DOMAIN-FREE local test

> **Amaç:** M2 (tokensız mTLS auto-enroll) kabul testini **operatörün AD CS / prod
> DNS'i gelmeden**, tamamen lokalde (bu Mac + lokal Win11 VM) koşmak. Sadece
> **production go-live** gerçek AD CS PKI + passthrough mTLS edge ister; **kabul
> testi istemez**. Test CA, AD CS'in yerine geçer.
>
> **Tetik:** M2 mantığını/regresyonu doğrulamak; operatör beklerken ilerlemek.
> **Kapsam:** backend enroll mantığı + güvenlik negatifleri + (opsiyonel) gerçek
> Windows istemci. **Kapsam dışı:** prod cutover, gerçek AD CS issuance.
>
> ⚠️ **SECURITY — yalnız izole lokal lab.** Forward-header modu + `/auto` permitAll
> ile **çıplak backend prod/staging'de ASLA açılmaz**. Bu modda backend `X-Client-Cert`
> header'ına güvenir + zinciri doğrulamaz → açıkta spoof yüzeyi. Prod'da gateway/ingress
> mTLS'i **terminate + zincir doğrula** eder ve dışarıdan gelen `X-Client-Cert`'i **strip
> edip** yalnız doğrulanmış handshake sonrası kendi enjekte eder (ADR-0029 #1501: passthrough
> canonical; forward-header lab fallback). Bu runbook bu modu yalnız Mac↔Parallels izole
> ağında kullanır.

---

## Neden domain-free çalışıyor

`MachineCertExtractor` cert kimliğini Java `getSubjectAlternativeNames()` (GeneralName
type 6 = URI) ile okur ve `URI:adcomputer:{lowercase-guid}` + EKU clientAuth + geçerli
pencere arar. Bunların hiçbiri bir **AD ortamı** ya da **gerçek CA güveni** gerektirmez:

- **Forward-header modunda** (`endpoint-admin.mtls.forward-header.enabled=true`) backend
  zinciri **doğrulamaz** — `parseForwardedPem` sadece byte'ları parse eder; zincir
  doğrulama gateway'in işidir. Yani test CA'nın gerçek trust anchor olması gerekmez.
- macOS LibreSSL `openssl verify` `adcomputer:` URI şemasını reddeder (error 53). Bu
  **yalnız CLI parser kaprisi** — Java backend `URI:adcomputer:` SAN'ını sorunsuz okur.

> Forward-header path passthrough ile **aynı `MachineCertAutoEnrollService` mantığını**
> çalıştırır (tenant binding, fingerprint dedupe, decommission guard, audit). Gerçek TLS
> handshake'li **passthrough** (:8443) reconcile'i Step-2'dir (ADR-0029 #1501; paralel
> #611/#612 arkasına sıralı). Bu runbook M2'nin **mantık + wire** kabulünü domain-free verir.

---

## 3 doğrulama seviyesi

| Seviye | Ne kanıtlar | Bağımlılık |
|---|---|---|
| **L1 — unit/slice** | Tüm extractor + service + controller mantığı, her negatif | sadece JDK + Maven (Docker yok) |
| **L2 — local wire** | Gerçek HTTP → güvenlik zinciri → service → PG persistence | throwaway PG (Docker) + servis |
| **L3 — Win11 cross-machine** | Gerçek Windows istemci, ağ üzerinden, gerçek cert | L2 + Parallels "Windows 11" guest |

---

## L1 — backend mantık (Docker'sız)

```bash
cd <platform-backend>/endpoint-admin-service
mvn -o test -DfailIfNoTests=false \
  -Dtest='MachineCertExtractorTest,MachineCertAutoEnrollServiceTest,AgentMachineCertEnrollmentControllerTest,AgentMachineCertEnrollmentControllerHeaderDisabledTest'
```
**Beklenen:** `Tests run: 36 … BUILD SUCCESS`. **Fail sinyali:** herhangi Failures/Errors > 0.

---

## L2 — local wire (throwaway PG + servis + matrix)

### 1) İzole PG
```bash
docker run -d --name m2-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=endpoint_admin -p 55432:5432 postgres:16
docker exec m2-pg psql -U postgres -d endpoint_admin -c "CREATE SCHEMA IF NOT EXISTS endpoint_admin_service;"
```
**Beklenen:** `pg_isready` OK + `CREATE SCHEMA`.

### 2) Backend'i forward-header AÇIK başlat
```bash
cd <platform-backend>/endpoint-admin-service
SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:55432/endpoint_admin \
SPRING_DATASOURCE_USERNAME=postgres SPRING_DATASOURCE_PASSWORD=postgres \
ENDPOINT_ADMIN_SECRET_ENCRYPTION_KEY="$(openssl rand -base64 32)" \
ENDPOINT_ADMIN_ENROLLMENT_TOKEN_PEPPER=localtestpepper \
mvn spring-boot:run -Dspring-boot.run.arguments="\
--eureka.client.enabled=false --spring.cloud.discovery.enabled=false \
--endpoint-admin.mtls.forward-header.enabled=true --spring.flyway.create-schemas=true"
```
**Beklenen log:** `Successfully applied 56 migrations … v57`, `X-Client-Cert forwarded-header mode ENABLED`, `Tomcat started on port 8096`. **Fail sinyali:** `APPLICATION FAILED TO START` / Flyway error.
> Default profile (`!local & !dev`) → `MtlsSecurityConfig` aktif → `/auto` permitAll (JWT/Keycloak gerekmez). `local`/`dev` profili bu chain'i KAPATIR — kullanma.

### 3) Matrix (test CA + 8 vaka — status + body stable-code assert)
```bash
cd <platform-k8s-gitops>/scripts/faz22-mass-deployment/m2-local-test
./run-matrix.sh        # fresh cert+fp+hostname her koşuda -> persistent DB'ye karşı tekrar-koşulabilir
```
> Her vaka HEM HTTP status HEM body'deki stable error code'u assert eder (örn. T8'in
> `409`'u gerçekten `FINGERPRINT_CONFLICT` mi, yoksa `DEVICE_RACE`/`ENROLLMENT_RACE` mi —
> ayırt edilir). Bu **seçili** wire negatif kümesidir; **expired cert / ambiguous SAN /
> decommissioned / insert-race** negatifleri L1 (unit/slice) katmanında kapsanır.
> **`CERTS=<dir>` override uyarısı:** önceden üretilmiş cert dizini verirsen SAN GUID'leri
> tekrar kullanılır → persistent DB'ye karşı **tekrar-koşulabilir DEĞİL** (T1 idempotent/
> conflict'e kayar). Her koşu için taze dizin kullan ya da `CERTS`'i hiç verme.

**Beklenen:** `TOTAL: pass=8 fail=0`

| # | Vaka | Beklenen |
|---|---|---|
| T1 | positive (dev, tenantA) | **201** enrolled |
| T2 | idempotent (dev, tenantA) | **200** already-enrolled (aynı deviceId) |
| T3 | tenant-boundary (dev, tenantB) | **403** TENANT_BOUNDARY |
| T4 | no-clientAuth-EKU | **401** CERT_EKU_MISSING_CLIENT_AUTH |
| T5 | no-adcomputer-SAN | **401** CERT_SAN_URI_MISSING |
| T6 | missing-cert (header yok) | **401** MTLS_CERT_MISSING |
| T7 | missing-tenant-header | **400** TENANT_HEADER_REQUIRED |
| T8 | fingerprint-conflict (devb, aynı fp) | **409** FINGERPRINT_CONFLICT |

### 4) Persistence doğrula
```bash
docker exec m2-pg psql -U postgres -d endpoint_admin -c \
"SELECT hostname,status,os_type FROM endpoint_admin_service.endpoint_devices;
 SELECT event_type,count(*) FROM endpoint_admin_service.endpoint_audit_events GROUP BY 1;"
```
**Beklenen:** device satırı `ONLINE`; audit `MACHINE_CERT_AUTO_ENROLL_SUCCESS` + `..._FAILED` (reddedilen enroll'lar dahi hash-chain'de — `noRollbackFor` tasarımı).

---

## L2b — passthrough variant (real :8443 mTLS handshake, Step-2)

Canonical passthrough (ADR-0029 #1501; backend PR #621): the backend terminates
mTLS on `:8443` (clientAuth=NEED), identity from the TLS peer cert, `X-Tenant-Id`
IGNORED (fixed-tenant authority). Domain-free with the test CA. All behind
`endpoint-admin.mtls.passthrough.enabled` (default off).

### 1) Server keystore + CA truststore
```bash
cd <platform-k8s-gitops>/scripts/faz22-mass-deployment/m2-local-test
./gen-test-certs.sh ./certs                  # test CA + client certs (if not already)
./gen-server-keystore.sh ./certs changeit    # server-keystore.p12 + truststore.p12 (+ prints backend cmd)
```

### 2) Start backend with passthrough (forward-header OFF)
Use the command `gen-server-keystore.sh` prints (`passthrough.enabled=true` +
key-store/trust-store paths + `fixed-tenant-id` + `forward-header.enabled=false`).
**Beklenen log:** `Added passthrough mTLS connector on port 8443 (clientAuth=NEED)`,
`Tomcat started on ports 8096 (http), 8443 (https)`, validator pass.
Mutual-exclusion: `passthrough.enabled` + `forward-header.enabled` birlikte → startup **FAIL**.

### 3) Passthrough matrix (real handshake — no `-k`)
```bash
CERTS=./certs ./run-passthrough.sh
```
**Beklenen:** `TOTAL: pass=6 fail=0` (docker PG erişilebilirse — T1b koşar); PG yoksa `pass=5 fail=0` + `SKIP T1b` (DB tenant'ı runbook adım 4'te manuel doğrula).

| # | Vaka | Beklenen |
|---|---|---|
| T1 | valid cert + FORGED `X-Tenant-Id` | **201** enrolled — header ignored (DB tenant T1b'de kontrol edilir) |
| T1b | (ops.) DB tenant binding | device `tenant_id==org_id==fixed` — forged header etkisiz (PG yoksa SKIP) |
| T2 | no client cert | TLS **handshake refused** (clientAuth=NEED; curl exit 56) |
| T3 | wrong-CA client cert | TLS **handshake refused** (truststore = dedicated CA only) |
| T4 | plain `:8096` endpoint-agent | **403** MTLS_CONNECTOR_REQUIRED (guard; never reaches business path) |
| T5 | non-agent path on `:8443` | **404** (guard least-privilege) |

### 4) Forged-tenant persistence verify
```bash
docker exec m2-pg psql -U postgres -d endpoint_admin -c \
"SELECT hostname,tenant_id,org_id FROM endpoint_admin_service.endpoint_devices WHERE hostname LIKE 'WIN11-PT-%';"
```
**Beklenen:** `tenant_id = org_id = fixed-tenant-id` (forged `X-Tenant-Id`'in etkisi YOK).

---

## L3 — Win11 cross-machine (Parallels guest → Mac)

Önkoşul: L2 servisi açık (`*:8096` tüm arayüzlere bind), Parallels "Windows 11" guest çalışıyor.
Guest Mac'i **shared net**'te `10.211.55.2` adresinde görür; Mac home → guest `C:\Mac\Home\…`.

```bash
# Mac: cert'i paylaşıma mint et + guest içinde enroll PS'i koştur
SHARE=~/m2-win11; mkdir -p "$SHARE"
<platform-k8s-gitops>/scripts/faz22-mass-deployment/m2-local-test/gen-test-certs.sh "$SHARE/certs"
# (run-enroll.ps1 -> $SHARE/run-enroll.ps1, repo'daki örnekten)
prlctl exec "Windows 11" powershell -ExecutionPolicy Bypass -File "C:\Mac\Home\m2-win11\run-enroll.ps1"
```
**Beklenen:** `actuator/health -> 200`, `positive(dev,tenantA) -> 201 enrolled`, `noeku -> 401`, `nosan -> 401`.
**Local DNS opsiyonu:** guest `hosts` dosyasına `10.211.55.2 mtls.local.test` → isimle erişim 200.
Bu yalnız izole lab alias'ıdır; production/test canonical host'ları
`mtls.testai.acik.com` ve `mtls.ai.acik.com` olarak kalır.
PowerShell `[System.Web.HttpUtility]::UrlEncode` form-urlencoding üretir = Java `URLDecoder` ile bire bir uyumlu.

---

## Rollback / teardown

```bash
# bg servisi durdur (mvn spring-boot:run process'i), sonra:
docker rm -f m2-pg
# guest hosts temizliği (opsiyonel):
prlctl exec "Windows 11" powershell -Command "(Get-Content C:\Windows\System32\drivers\etc\hosts) | Where-Object {$_ -notmatch 'mtls.local.test'} | Set-Content C:\Windows\System32\drivers\etc\hosts"
```

## Bu runbook NE kanıtlamaz (prod go-live için kalan)

- **Gerçek AD CS issuance** (SAN URI:adcomputer:{objectGUID} otomatik, EKU template-OID) — operator gate.
- **Passthrough mTLS edge** (:8443 connector, `client-auth=need`, gerçek TLS handshake kimliği) — **Step-2**, ADR-0029 #1501; paralel #611/#612 arkasına sıralı + Codex plan-time design review.
- **prod DNS subhost** (`mtls.<env>` canonicalized as `mtls.testai.acik.com`
  for test/pilot and `mtls.ai.acik.com` for prod) — operator gate.

## Referans
- Backend: `endpoint-admin-service` — `AgentMachineCertEnrollmentController`, `MachineCertAutoEnrollService`, `MachineCertExtractor`, `MtlsSecurityConfig`
- ADR-0029 #1501 (passthrough canonical, forward-header lab-fallback-only)
- Scripts: `scripts/faz22-mass-deployment/m2-local-test/{gen-test-certs,run-matrix}.sh`
- L1 36/36 + L2 8/8 + L3 (Win11 201) — ilk koşum 2026-06-13
