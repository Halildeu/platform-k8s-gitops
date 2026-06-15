# RB-faz22-3b-tpm-enrollment-e2e — TPM + Vault-PKI cihaz kaydı uçtan-uca aktivasyon + pilot

> **Tetik:** Faz 22.3B (AD-CS-less, TPM-attestation + Vault-PKI cihaz mTLS kaydı) tüm kod dilimleri MERGED + verified olduktan sonra, özelliği **kapalı-durumdan** kontrollü şekilde **5-10 PC pilotuna** almak (ADR-0039 gate-5 hazırlık + gate-6 pilot). **Disabled-by-default**; bu runbook bilinçli aktivasyon adımıdır.
>
> **Önceki runbook:** [`RB-faz22-3b-vault-pki-setup`](./RB-faz22-3b-vault-pki-setup.md) (gate-2 — Vault PKI engine). Bu runbook onun ÜZERİNE kurar (uçtan-uca aktivasyon + pilot + rollback).

## 1. AMAÇ

Tüm merged bileşenleri (backend doğrulayıcılar gate-4a..4d + agent kayıt yolu gate-3 + Vault PKI gate-2) birleştirip, bir pilot tenant + 5-10 PC için TPM-tabanlı cihaz kaydını **canlıya alma + doğrulama + geri-alma** prosedürü.

## 2. KAPSAM

- **DAHİL:** backend TPM-attest feature config + per-tenant enable + agent `--auto-enroll-tpm` kurulumu + uçtan-uca doğrulama + 5-10 PC pilot + abort/rollback.
- **HARİÇ:** AD CS yolu (dokunulmaz — paralel, primary domain-joined için); steady-state mTLS-cert-auth (3-AI kararı: steady-state = HMAC, enrollment-cert ≠ steady-state-auth — aşağı §8); certstore steady-state import (3c-3, ayrı slice).

## 3. ÖNKOŞULLAR

| # | Önkoşul | Doğrulama |
|---|---|---|
| 1 | **gate-2 Vault PKI** kuruldu (intermediate + `tpm-device` role clientAuth-only + backend AppRole least-priv) | `RB-faz22-3b-vault-pki-setup` §5 sandbox doğrulaması geçti |
| 2 | **Backend merged + deployable** (gate-4a verifiers V1-V12 + gate-4b VaultPkiClient + gate-4d /nonce+/attest) | platform-backend main'de; endpoint-admin image hazır |
| 3 | **Agent merged + buildable** (gate-3: internal/tpmenroll + `--auto-enroll-tpm`; go-tpm REAL-vTPM-verified PR #164) | platform-agent main'de; `endpoint-agent.exe` windows/amd64 |
| 4 | **Manufacturer EK-root bundle + SHA-256 pinleri** (hedef cihazların TPM üreticisi: Infineon/STM/Nuvoton… kök sertifikaları) | `endpoint-admin.tpm-attest.manufacturer-root-sha256` + `-pems` hazır |
| 5 | **Pilot tenant + 5-10 cihaz** belirlendi (owner kararı, ADR-0039 gate-6) | tenant UUID + enrollment token üretim planı |

## 4. ADIMLAR

### 4.1 Backend — TPM-attest feature config (disabled→enabled, pilot tenant)

`endpoint-admin` overlay env / ConfigMap (test→prod sıra; D29-EA disiplini):

```yaml
endpoint-admin.tpm-attest.enabled: "true"            # master flag (default false)
endpoint-admin.tpm-attest.allowed-tenant-ids: "<pilot-tenant-uuid>"   # per-tenant opt-in (boş = hiç kimse)
endpoint-admin.tpm-attest.manufacturer-root-sha256: "<pin1>,<pin2>"   # V2 EK-chain (build-time pinned)
endpoint-admin.tpm-attest.manufacturer-root-pems: |                   # actual roots (verified vs pins at startup)
  -----BEGIN CERTIFICATE----- ...
endpoint-admin.tpm-attest.vault.enabled: "true"      # gate-4b VaultPkiClient
endpoint-admin.tpm-attest.vault.* : <gate-2 AppRole + role/path from RB-faz22-3b-vault-pki-setup>
# Opsiyonel V6 PCR policy (HIGH risk sınıfı için):
# endpoint-admin.tpm-attest.pcr.required-bitmap-hex / .required-hash-alg / .allow-set
```

> **Fail-closed:** `enabled=false` (default) → her /nonce+/attest uniform-403 (FEATURE_DISABLED, audit-only). `allowed-tenant-ids` boş → hiçbir tenant kaydolamaz. Vault `enabled` ama yanlış AppRole → startup fail-fast (gate-4b). **manufacturer-root-pems pin'le eşleşmezse startup fail** (V2 trust-set genişlemez).

Deploy + **D29-EA katman doğrulaması** (HARD RULE: Up ≠ Functional ≠ Secured):

```bash
# Up: pod Running + imageID == GHCR digest
kubectl --context k3d-<env> -n platform-<env> get pod -l app=endpoint-admin -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'
# Functional: /nonce token'sız → uniform-403 (endpoint var + fail-closed).
# Edge yolu /api/v1/endpoint-agent/** — api-gateway bu prefix'i permitAll + RewritePath ile
# controller'a (/api/v1/agent/enrollments/tpm) iletir. Bu yüzden token'sız istek gateway'i GEÇER
# ve controller'ın 403'ünü görür. 401 görürsen gateway auth (yanlış yapılandırma); 404 görürsen
# yanlış path/route; 500 görürsen fail-OPEN bug — üçü de fail sinyali, beklenen tek değer 403.
curl -sk -o /dev/null -w '%{http_code}' -X POST https://<edge>/api/v1/endpoint-agent/enrollments/tpm/nonce -d '{}'   # beklenen: 403
# Secured: enabled=false iken de 403 (master flag fail-closed) — flip öncesi/sonrası fark audit'te
```

### 4.2 Agent — `--auto-enroll-tpm` kurulumu (pilot cihaz, Windows + TPM 2.0)

```powershell
# Enrollment token (bootstrap) + canonical API base; token gövdede taşınır, server-TLS bootstrap.
$env:ENDPOINT_AGENT_ENROLLMENT_TOKEN = "<pilot-token>"
# API base = gateway-public EDGE prefix (endpoint-agent). Agent suffix'i "/enrollments/tpm/{nonce,attest}"
# bu base'e ekler (wire.go url.JoinPath); gateway endpoint-agent→agent rewrite eder. /api/v1/agent
# DEĞİL (gateway'de o route yok → 404). Doğrulanmış kod-kontratı 2026-06-15.
$env:ENDPOINT_AGENT_AUTO_ENROLL_API_URL = "https://<edge>/api/v1/endpoint-agent"
# Bir-seferlik kayıt (servis modunda install.ps1 ile de verilebilir):
endpoint-agent.exe --auto-enroll-tpm
# Beklenen stdout: "tpm auto-enroll: success — issued client certificate persisted (deviceRef=<host>)"
# Her iki leg de 200 döner (ResponseEntity.ok; 201 değil). Cert artifact: %ProgramData%\EndpointAgent\tpm-client-cert.pem
```

> Cihazın TPM 2.0'ı olmalı (RSA-3072 primary opsiyonel olduğundan device key **EC P-256** — universal; PR #164). `--auto-enroll-tpm`, `--auto-enroll` (AD CS) + `--enrollment-token` ile **mutually exclusive** (fail-closed).

### 4.3 Akış (kod tarafı — referans)

`agent: NewWindowsTPMDevice (EK/AK/deviceKey TBS) → Client.Enroll`:
`POST /nonce` (EK-chain V2 + AK-restricted V11 + algo V12 → nonce + MakeCredential challenge) → `ActivateCredential` (V10 one-TPM proof) → `Quote` (V5) + `CertifyDeviceKey` (V4) + CSR(deviceKey, EKU clientAuth) → `POST /attest` (V1 consume → bind → V10 → V5 → V6 → V4 → V9 → Vault sign) → **Vault-PKI clientAuth cert**. `/nonce` transient-retry (RFC8555), `/attest` retry YOK (nonce single-use).

## 5. DOĞRULAMA (uçtan-uca, gold)

| Katman | Kontrol | Beklenen |
|---|---|---|
| Agent | stdout + `tpm-client-cert.pem` mevcut | "success" + PEM cert |
| Backend audit | enrollment audit kaydı (deny-code yok) | CONSUMED; device record `ek_pub_sha256` |
| Vault audit | `pki-int/issue/tpm-device` çağrısı | 1 cert issued, clientAuth, short-TTL, SAN `tpm:<ek_pub_sha256>` |
| Cross-language proof | (zaten PR #164'te REAL-vTPM ile kanıtlandı) | backend MakeCredential ↔ gerçek TPM ActivateCredential byte-uyumlu |
| Negatif | yanlış/expired token → /nonce | uniform-403 (oracle yok) |
| Negatif | feature disabled tenant → /nonce | uniform-403 |

## 6. PİLOT (ADR-0039 gate-6, 5-10 PC, owner-gated)

### 6.0 Canary (5-10 dalgasından ÖNCE — zorunlu)

1. **1-2 cihaz** ile kontrollü kayıt (operator gözetiminde). İlk cihazda §5'in TÜM katmanları (agent + backend audit + Vault audit) elle doğrulanmadan dalgaya geçilmez.
2. **Negatif harness (canary cihazda, dalga öncesi — her biri uniform-403 vermeli):**
   - Yanlış/expired bootstrap token → `/nonce` → **403** (oracle yok).
   - Doğru token ama **allow-list dışı tenant** → **403** (`FEATURE_DISABLED` audit; cert YOK).
   - **Yanlış manufacturer root pin** ile cihaz (mümkünse test-TPM) → `/attest` → **403** (`EK_UNTRUSTED`).
   - Tekrarlanan `/attest` (aynı nonce) → **403** (V1 single-use; replay yok).
   Herhangi biri 200/cert üretirse → **dalga BAŞLATMA, §7 rollback + kök-neden.**

### 6.1 Dalga

1. 5-10 cihaza sıralı `--auto-enroll-tpm` (dalga: 1 → 3 → 5-10).
2. **Başarı kriteri:** ≥ %90 cihaz ilk denemede cert aldı; 0 yanlış-issue; 0 cross-tenant.

### 6.2 Denetim izleme (her dalga sonrası — ölçüm yöntemi)

Backend audit log'da (endpoint-admin) **her dalga için** şu olayları say + beklenenle karşılaştır:

| Olay / deny-code | Beklenen | Anomali sinyali |
|---|---|---|
| `CONSUMED` (başarılı enroll) | == kayıt olan cihaz sayısı | fazla → çift-issue; az → sessiz fail |
| `FEATURE_DISABLED` | yalnız allow-list dışı denemeler | pilot-tenant cihazında görülürse → flag/tenant config hatası |
| `EK_UNTRUSTED` / `NONCE_INVALID` / `QUOTE_INVALID` | 0 (sağlıklı cihazda) | > 0 → cihaz TPM/clock veya pin sorunu |
| cross-tenant issue | **0 (mutlak)** | ≥ 1 → **derhal abort** |
| Vault `pki-int/issue/tpm-device` çağrısı | == `CONSUMED` sayısı | uyuşmazlık → issue-path drift |

Kopyalanabilir denetim sorguları (template — log alan adlarını gerçek JSON şemasına göre uyarla):

```bash
# Backend audit (endpoint-admin pod log'u; deny-code + CONSUMED dağılımı):
kubectl --context k3d-<env> -n platform-<env> logs deploy/endpoint-admin --since=30m \
  | grep -iE 'tpm.?attest|tpm.?enroll' \
  | grep -oE 'CONSUMED|FEATURE_DISABLED|NONCE_INVALID|EK_UNTRUSTED|AK_BINDING_FAILED|KEY_NOT_TPM_BOUND|QUOTE_INVALID|PCR_POLICY_FAILED|DEVICE_NOT_ELIGIBLE|CSR_POLICY_VIOLATION' \
  | sort | uniq -c | sort -rn
# Beklenen sağlıklı dalga: CONSUMED == kayıt sayısı; geri kalan deny-code'lar 0 (allow-list dışı denemeler hariç FEATURE_DISABLED).

# Cross-tenant kontrolü (MUTLAK 0) — pilot-tenant dışı bir tenant'a issue var mı:
kubectl --context k3d-<env> -n platform-<env> logs deploy/endpoint-admin --since=30m \
  | grep -i 'tpm' | grep -i 'issued' | grep -v '<pilot-tenant-uuid>'   # beklenen: BOŞ

# Vault tarafı (issue sayısı + TTL + EKU=clientAuth):
vault list pki-int/certs | wc -l                       # ≈ CONSUMED sayısı (+ CA)
vault read pki-int/cert/<serial>                       # notAfter kısa-TTL; ext key usage = clientAuth
```

### 6.3 Dayanıklılık (CA/Vault fail senaryosu — dalga içinde en az 1 kez)

- **Vault erişilemez** iken `/attest` → cihaz cert ALAMAZ ama backend **fail-closed 5xx/deny** vermeli (fail-open issue YOK); agent retry YOK (nonce single-use) → operator yeni `--auto-enroll-tpm` ile tekrar dener.
- **CRL/OCSP propagation gecikmesi:** bir cert revoke → propagation süresi < `auto_rebuild_grace_period` (gate-2 SLO) ölç; aşılırsa revocation güvenliği zayıf → abort eşiği.

### 6.4 Abort eşikleri

Herhangi cross-tenant issue / V2-V12 bypass / Vault least-priv ihlali / fail-open 200 / revocation-propagation SLO aşımı → **derhal §7 rollback.**

## 7. ROLLBACK (72h warm)

**Backend (anında, yeni kayıtları durdurur):**
```yaml
# 1. Master flag kapat → tüm yeni /nonce+/attest fail-closed 403 (anında)
endpoint-admin.tpm-attest.enabled: "false"
```
```bash
# 2. İhraç edilmiş pilot cert'leri revoke (Vault): her serial → pki-int/revoke
#    (revoke sonrası CRL/OCSP yayılana kadar mevcut cert geçerli — §6.3 SLO ölçümü)
# 3. Pilot device record'ları decommission (admin) — re-activation explicit operator action
```

**Cihaz tarafı (pilot PC'lerde — Codex 019eca4f: cihaz-local artefakt temizliği şart):**
```powershell
# 4. İhraç edilmiş cert artefaktını kaldır + doğrula (yoksa zaten temiz)
Remove-Item "$env:ProgramData\EndpointAgent\tpm-client-cert.pem" -ErrorAction SilentlyContinue
Test-Path "$env:ProgramData\EndpointAgent\tpm-client-cert.pem"   # beklenen: False
# NOT: TPM-resident device key (deterministik primary) TPM'de kalır — zararsız: eşleşen geçerli cert
# olmadan kullanılamaz, revoke edilen cert CRL/OCSP ile reddedilir. Yeniden kayıt = --auto-enroll-tpm.
```

**Steady-state etkisi (doğru çerçeve):**
- **Domain-joined cihazlar:** AD CS yolu primary olarak ayakta (paralel, dokunulmadı) → AD CS kimliğiyle devam ederler. TPM enrollment bunlar için zaten opsiyonel üst-katmandı.
- **Domain-LESS pilot cihazlar (22.3B asıl hedefi — AD CS YOK):** bunların "AD CS'e düşmesi" mümkün değil (AD CS üyeliği yok). TPM cert kaldırılınca steady-state API erişimleri **mevcut bootstrap/HMAC kanalına** döner (§8: steady-state = HMAC; enrollment-cert ≠ steady-state-auth). Yani cert kaybı steady-state erişimi KESMEZ — yalnız hardware-rooted identity upgrade'i geri alır.
- **72h warm:** bu süre boyunca eski yol (her cihaz sınıfı için yukarıdaki) frozen + ayakta; geri-alma tek-yönlü değil (flag tekrar açılabilir).

**Rollback sonrası beklenen after-state (kapanış doğrulaması — hepsi sağlanmalı):**

| # | Kontrol | Beklenen |
|---|---|---|
| 1 | `/nonce` edge curl (token'sız) | **403** (flag off; yeni kayıt kapalı) |
| 2 | Vault `pki-int/certs` — revoke edilen pilot serial'leri | CRL'de listeli; `vault read pki-int/cert/<serial>` → `revocation_time` set |
| 3 | Pilot device record'ları | `DECOMMISSIONED` / `REVOKED` (admin view); same-EK re-attest → `DEVICE_NOT_ELIGIBLE` |
| 4 | Pilot PC'lerde `tpm-client-cert.pem` | `Test-Path` → **False** (artifact temizlendi) |
| 5 | Pilot PC steady-state API erişimi | **kesintisiz** (HMAC kanalı; domain-less cihaz cert kaybından etkilenmez) |
| 6 | Backend audit | rollback sonrası yeni `CONSUMED` **yok**; yeni denemeler `FEATURE_DISABLED` |

## 8. GÜVENLİK NOTLARI / SINIRLAR

- **Disabled-by-default + per-tenant opt-in + fail-closed her katman** (V1-V12 uniform-403, reason audit-only — wire oracle yok).
- **steady-state = HMAC, enrollment-cert ≠ steady-state-auth** (3-AI kararı 2026-06-15, Codex `019ec723` + MiniMax: Intune SCEP/NDES + BeyondCorp + Cloudflare-mTLS normu). Issued TPM cert = enrollment/identity proof; steady-state API auth mevcut HMAC kanalı. mTLS-cert steady-state resolver (gate-4c-1) ileri-dönük hook (default-off), wiring gate-4c-2 = ertelendi.
- **3c-3'e kadar veri akışı (Codex Q4 net cevabı):** `--auto-enroll-tpm` issued cert'i **SADECE dosyaya** yazar (`%ProgramData%\EndpointAgent\tpm-client-cert.pem`) — Windows certstore'a / CNG-TPM key association'a **bağlamaz**. Dolayısıyla bu fazda **cert-tabanlı mTLS steady-state YOK**; her cihazın steady-state API auth path'i **HMAC kanalıdır**. Cert, kimlik/kayıt kanıtıdır; steady-state taşıyıcı değildir.
- **certstore steady-state import (3c-3)** = ayrı slice (Windows certstore + CNG/TPM-key association, AD-CS-coupled); device key deterministik-yeniden-türetilebilir (TPM primary) → sadece cert import gerekir. Bu slice landed olana kadar mTLS-cert steady-state path aktif edilmez.
- **AD CS yolu dokunulmadı** (paralel primary; `internal/autoenroll/` + `MachineCertExtractor` byte-for-byte korundu).

## 9. REFERANS

- ADR-0039 (charter) · `faz-22-3b-tpm-attestation-design.md` (design + V1-V12 + integration contract) · `RB-faz22-3b-vault-pki-setup` (gate-2 Vault).
- Backend: platform-backend gate-4a (#653/#654/#657/#659) + gate-4b (#660) + gate-4d (#661/#662) + gate-4c-1 resolver (#664).
- Agent: platform-agent gate-3 — tpmenroll TM2 wire (#158/#159), crypto (#160/#161/#162), orchestrator (#163), **go-tpm Windows-TBS REAL-vTPM-verified (#164)**, retry (#166), `--auto-enroll-tpm` CLI (#167).
- 3-AI: Codex thread `019ec723`/`019eca4f` + MiniMax `mvs_d6ab5b4f`.
