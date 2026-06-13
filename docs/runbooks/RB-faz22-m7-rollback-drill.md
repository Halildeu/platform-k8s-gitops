# RB Faz 22.5 M7 — Rollback Drill (MSI uninstall + enrollment revoke + GPO rollback + backend pause)

> **Status**: WAVE-GATE PREP — agent docs-only. Canlı drill **operatör + 1 pilot cihaz** gerektirir (operator-gated).
> **Tracked by**: [#1379](https://github.com/Halildeu/platform-k8s-gitops/issues/1379) (Faz 22.5 M7 — Rollback drill gate).
> **Source of truth**: `docs/faz-22-software-deployment-plan.md` §0.5.3 (MSI/GPO rollback), §0.5.7 (Rollback ve Communications gate), §0.5.9 (full-consensus protocol — M7 mandatory gate).
> **Scope sınırı**: Bu runbook rollback drill'in **tekrar edilebilir prosedürü + evidence template**'idir. "Rollback prove edildi" iddiası **ancak 1 pilot cihazda canlı drill koşulup evidence template doldurulduktan sonra** geçerlidir (§0.5.9 stop-line rule 3: rollback drill failure stops the next wave). PR merge tek başına gate kapatmaz.
> **İlişkili**: `RB-faz22-m5-2pc-pilot.md` (M5 pilot), `RB-faz22-m6-50pc-capacity.md` (M6 wave), `RB-faz22.3-ad-cs-setup.md` (AD CS), `scripts/faz22-mass-deployment/wave-preflight.ps1` (cihaz sağlık check).

---

## 1. Amaç ve kapsam

Rollback bir **kapıdır, sonradan-akla-gelen değil** (§0.5.7). M5'ten itibaren rollback prove edilmeden hiçbir dalga büyütülmez. Bu drill, 800-PC filo ölçeğine çıkmadan önce **kontrollü çıkış yolunun gerçekten çalıştığını** 1 pilot cihazda kanıtlar.

### 1.1 Neyi kanıtlar

- MSI uninstall + reinstall drill tek pilot cihazda temiz çalışır (service, scheduled task, HKLM Mode/Environment, log/cache beklenen halde).
- Enrollment revoke (decommission) yolu çalışır: revoked cihaz **yeniden tokenless enroll olmadan komut alamaz**.
- GPO unlink / security-filter rollback etkisi ve propagation süresi ölçülür (operatör AD action).
- Backend command dispatch durdurulabilir: yeni install command üretimi durur.
- Failed-device bundle + audit row retention politikasına uygun saklanır.
- IT/help-desk comms + escalation owner yazılı.

### 1.2 Neyi KANITLAMAZ (hard scope sınırı)

- **Domain-wide rollback** — tek cihaz uninstall code path'i domain rollback'i kanıtlamaz (#1379 acceptance "an uninstall code path alone does not prove domain rollback").
- **Otomatik kitlesel rollback** — GPO-driven mass uninstall ayrı kapı; bu drill manuel + tek cihaz.
- **Trusted-signing / EDR allowlist üretim davranışı** — AG-018 LIVE (internal CA) ama Trusted Publisher GPO push operatör-gated.

---

## 2. Ön koşullar

| # | Ön koşul | Doğrulama | Sorumlu |
|---|---|---|---|
| P1 | Signed MSI mevcut (production tier) | `signtool verify /pa EndpointAgent-<ver>-signed.msi` exit 0 (AG-018 v0.2.1+ LIVE, internal CA) | agent (LIVE) |
| P2 | 1 pilot cihaz enrolled + heartbeat veriyor | endpoint-admin device grid: cihaz `ONLINE`, son heartbeat <10dk | operatör + agent supervise |
| P3 | endpoint-admin **MANAGER** token (revoke/dispatch için) | decommission/reactivate/rollout MANAGER ister; `GET /api/v1/admin/endpoint-devices` 200 yalnız VIEWER'ı kanıtlar — MANAGER yetkisi ancak revoke (D3) çağrısı 200/409 dönerse (403 değil) kanıtlanır | operatör (kullanıcı yetkili token) |
| P4 | GPO link mevcut (pilot OU) — GPO rollback adımı için | `gpresult /r` cihazda policy görünür | operatör (AD) |
| P5 | Cihaz state-verify yolu hazır | D2 manuel kontrolleri canonical; `wave-preflight.ps1` opsiyonel otomasyon **M5 PR'ında gelir** (drill zamanı mevcut olur) | agent (M5 slice) |
| P6 | Backup/recovery: cihazın system restore point veya VM snapshot | snapshot alındı | operatör |

> **No Fake Work**: P1 agent-doable + LIVE; P5 (manuel D2 kontrolleri) agent-doable; P2/P3/P4/P6 operatör-gated. Bu runbook drill'i sıralar; canlı koşum P2-P6 hazır olunca yapılır. **P3 dikkat**: VIEWER token decommission/rollout'u kanıtlamaz — gerçek MANAGER yetkisi D3'te görülür.

---

## 3. Drill adımları

Her adım: **tetik → komut → beklenen → fail-sinyali → devam eşiği**. Adımlar sıralı; bir adım fail ederse **dur**, root-cause kaydet, sonraki dalga AÇILMAZ (§0.5.9 stop-line).

### D1 — MSI uninstall + reinstall drill (~10 dk)

**Tetik**: pilot cihaz enrolled, drill başlangıcı.

**Komut** (pilot cihazda, elevated PowerShell — `LocalSystem` veya local admin):
```powershell
# 1a. ProductCode'u bul (uninstall için stable identity)
$p = Get-CimInstance Win32_Product -Filter "Name LIKE 'EndpointAgent%'" |
     Select-Object Name, Version, IdentifyingNumber
$p | Format-Table -AutoSize
# IdentifyingNumber = {GUID} = ProductCode

# 1b. MSI uninstall (silent, no reboot, verbose log)
$code = $p.IdentifyingNumber
msiexec /x "$code" /qn /norestart /l*v "C:\ProgramData\EndpointAgent\logs\uninstall-msi-$(Get-Date -Format yyyyMMdd-HHmmss).log"
echo "msiexec exit: $LASTEXITCODE"   # beklenen 0 (3010 = reboot-pending, kabul edilebilir)

# 1c. Reinstall (same signed MSI, same UpgradeCode)
#     Domain/GPO path = TOKENLESS auto-enroll (machine cert / mTLS), ADR-0029.
#     ENROLL_RESPONSE_FILE KULLANMA — o, MSI wrapper'ın okuyup kullanım sonrası
#     SHRED ettiği kısa-ömürlü LAB HMAC token dosyasıdır (run-agent-install.ps1),
#     kalıcı bir response JSON değil.
msiexec /i "EndpointAgent-<ver>-signed.msi" /qn /norestart `
  AUTO_ENROLL=1 `
  /l*v "C:\ProgramData\EndpointAgent\logs\reinstall-msi-$(Get-Date -Format yyyyMMdd-HHmmss).log"
echo "msiexec exit: $LASTEXITCODE"   # beklenen 0
# (HMAC lab fallback gerekiyorsa: ayrı KISA-ÖMÜRLÜ temp token dosyası ver,
#  ENROLL_RESPONSE_FILE=<temp>; wrapper kullanım sonrası dosyayı siler.)
```

> **Not**: `Win32_Product` enumerate yavaş + her satırda consistency-check tetikler; alternatif olarak `Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' | Where DisplayName -like 'EndpointAgent*'` ile `PSChildName` (= ProductCode) okunabilir (daha hızlı, yan etkisiz).

**MSI uninstall iç akışı** (M4 ps1-wrapper model, `installers/windows/`): MSI deferred CA → `run-agent-install.ps1 -Uninstall` → `uninstall.ps1`. `uninstall.ps1` adımları (canonical SoT, doğrulandı):
1. `HKLM\SYSTEM\CurrentControlSet\Services\EndpointAgent\Environment` regkey **temizlenir** (stale Mode/env guard — #108/#109 sınıfı).
2. Binary mevcutsa: `endpoint-agent.exe service uninstall --name EndpointAgent` (maintenance token + sha256 verildiyse iletilir). **Bu çağrı nonzero dönerse `uninstall.ps1` throw eder — fallback'e DÜŞMEZ.**
3. Yalnız binary **yoksa** fallback: `Stop-Service -Force` + `sc.exe delete EndpointAgent` (uninstall.ps1 `else` dalı).
4. `Wait-AgentProcessExit -InstallPath` (watchdog child handle yarışını önler — locked-binary `Access denied` guard) → ardından dir removal.
5. Config store (`config\hmac-credential.dpapi`) + Machine env **korunur** (`-RemoveConfig`/`PURGE_CONFIG=1` verilirse Machine env + HMAC blob da temizlenir).

**Beklenen**: uninstall exit 0/3010; service kayıt yok; reinstall exit 0; reinstall sonrası service `Running`.

**Fail-sinyali**: uninstall exit 1603 (genel fail — `-l*v` log tail oku: çoğunlukla locked binary / pending-delete); reinstall "another version is already installed" (ProductCode/UpgradeCode drift → M4 stop §0.5.4).

**Devam eşiği**: uninstall + reinstall ikisi de exit 0/3010 → D2.

---

### D2 — Post-rollback cihaz state verify (~3 dk)

**Tetik**: D1 uninstall tamamlandı (reinstall ÖNCESİ uninstall state'i, VE reinstall SONRASI çalışır state'i ayrı doğrulanır).

**Komut** (manuel kontroller — **canonical** yol; `wave-preflight.ps1 -Mode rollback-clean -Json` M5 PR'ında gelen opsiyonel otomasyondur):
```powershell
Get-Service EndpointAgent -ErrorAction SilentlyContinue           # uninstall sonrası: yok
Get-ScheduledTask -TaskName "EndpointAgent*" -EA SilentlyContinue # varsa: yok
# Service kayıt anahtarı + service env (uninstall.ps1 temizler):
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\EndpointAgent' -EA SilentlyContinue  # yok
# AGENT MODE/CONFIG anahtarı — AutoEnroll install bunu yazar (install.ps1 Set-AgentAutoEnrollRegistry):
Get-ItemProperty 'HKLM:\SOFTWARE\EndpointAgent' -EA SilentlyContinue  # Mode/ApiUrl/EnrollmentJitterSeconds
Test-Path "$env:ProgramFiles\EndpointAgent\endpoint-agent.exe"    # uninstall sonrası: False
Test-Path "$env:ProgramData\EndpointAgent\logs"                  # log retention: True (korunur)
Test-Path "$env:ProgramData\EndpointAgent\config\hmac-credential.dpapi"  # -RemoveConfig yoksa: True
```

**Beklenen** (uninstall sonrası temiz state): service yok, scheduled task yok, HKLM `Services\EndpointAgent` yok, **exe yok**, **log dizini korunur** (evidence retention), config store `-RemoveConfig` verilmediyse korunur. `HKLM:\SOFTWARE\EndpointAgent` Mode key: reinstall AutoEnroll ise `Mode=auto-enroll` döner (reinstall sonrası), HMAC reinstall ise farklı/absent — drill bu key'in **beklenen reinstall mode'una eşitliğini** doğrular (stale Mode guard, #108/#109 sınıfı).

**Fail-sinyali**: orphan service (`sc query EndpointAgent` STATE!=1060), orphan scheduled task, stale HKLM `Services\EndpointAgent\Environment` regkey kalıntısı, **stale `HKLM:\SOFTWARE\EndpointAgent\Mode`** (önceki enroll mode reinstall mode'uyla çelişiyor), exe locked (`Wait-AgentProcessExit` timeout → manuel `taskkill /F /IM endpoint-agent.exe`).

**Devam eşiği**: orphan yok + reinstall sonrası service `Running` → D3.

---

### D3 — Enrollment revoke (decommission) + "komut alamaz" verify + reactivate (~8 dk)

**Tetik**: pilot cihaz reinstall sonrası enrolled + ONLINE.

**Mekanizma** (backend doğrulandı — `EndpointDeviceLifecycleService` + `EndpointDeviceLifecycleCascade`, Codex thread `019ea789`): enrollment revoke = **device decommission** (KVKK: deactivate-not-delete, reversible). Decommission cascade'i **pending agent work'ü iptal eder** (cascade counts: `cancelledCommands` / `revokedTokens` / `finalizedUninstalls`; secret clear bir yan-etkidir, ayrı count yok) ve "decommissioned device cannot act OR revive itself" invariant'ı `EndpointDeviceWriteGuard.loadActiveForUpdate` ile enforce edilir: decommissioned cihaza yeni operasyon yaratma **409** döner ("Endpoint device is decommissioned; reactivate it before creating new operations.").

**Komut** (operatör MANAGER token ile; `$BASE=https://testai.acik.com`):
```bash
# 3a. Revoke = decommission (pending komutları cascade-cancel eder)
DEVICE_ID="<uuid>"
curl -sS -X POST "$BASE/api/v1/admin/endpoint-devices/$DEVICE_ID/decommission" \
  -H "Authorization: Bearer $MGR_TOKEN" -H "Content-Type: application/json" \
  -d '{"reason":"M7 rollback drill — revoke verify"}' | jq '.status'
# beklenen: "DECOMMISSIONED" (409 = zaten decommissioned)

# 3b. "Komut alamaz" verify — revoked cihaza yeni komut POST et.
#     DTO field adı 'type' (CommandType), 'commandType' DEĞİL — yanlış field 400
#     validation döner ve "decommissioned reddedildi" diye SAHTE PASS yazdırır.
curl -sS -X POST "$BASE/api/v1/admin/endpoint-devices/$DEVICE_ID/commands" \
  -H "Authorization: Bearer $MGR_TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"COLLECT_INVENTORY","reason":"M7 revoke verify"}' -w "\nHTTP %{http_code}\n"
# beklenen: SPESIFIK 409 + "Endpoint device is decommissioned..." (EndpointDeviceWriteGuard).
# 400 = field adı yanlış (validation), guard'ı kanıtlamaz → FAIL/retry. RAW payload loglanmaz.

# 3c. Agent-side: revoked cihaz heartbeat/poll denediğinde komut almaz
#     (cihazda) endpoint-agent --once → "device decommissioned" / komut kuyruğu boş

# 3d. Reactivate (drill sonrası cihazı geri al)
curl -sS -X POST "$BASE/api/v1/admin/endpoint-devices/$DEVICE_ID/reactivate" \
  -H "Authorization: Bearer $MGR_TOKEN" -H "Content-Type: application/json" \
  -d '{"reason":"M7 rollback drill complete — restore"}' | jq '.status'
# beklenen: "OFFLINE" (credential/enrolledAt varsa) veya "PENDING_ENROLLMENT"; ONLINE bir sonraki gerçek heartbeat'le kazanılır
```

**Beklenen**: decommission → `DECOMMISSIONED`; revoked cihaza komut yaratma **409** (`type` field doğru gönderildiğinde); reactivate → `OFFLINE`/`PENDING_ENROLLMENT`; reactivate sonrası gerçek heartbeat → `ONLINE`.

**Fail-sinyali**: decommission sonrası komut yaratma 200 döner (cascade/guard bug → backend triage, M7 stop); 3b'de **400** dönerse field adı yanlış (`commandType` yazılmış) — guard kanıtlanmamış, düzelt+tekrar; reactivate 409 (lifecycle state mismatch).

**Devam eşiği**: revoke → 409-komut-reddi → reactivate zinciri yeşil → D4.

> **Audit kanıtı**: decommission/reactivate her ikisi de `endpoint_device_lifecycle_audit` (who/when/why + cascade counts `cancelledCommands`/`revokedTokens`/`finalizedUninstalls`) + hash-chained `endpoint_audit_events` (`ENDPOINT_DEVICE_DECOMMISSIONED`/`ENDPOINT_DEVICE_REACTIVATED`) yazar. Drill evidence'ında bu row'lar (PII-redacted) referanslanır.

---

### D4 — GPO rollback (operatör AD action, ~propagation-bound)

**Tetik**: D1-D3 yeşil; GPO-driven deployment senaryosunda rollback test edilir.

**Komut** (operatör, AD yönetim makinesinde — agent yapamaz):
```text
# 4a. GPO unlink (pilot OU'dan link kaldır VEYA security-filter'dan cihazı çıkar)
#     GPMC → EndpointPilot OU → "Endpoint Agent Deployment" GPO → Link Enabled OFF
#     veya: GPO → Scope → Security Filtering → pilot cihaz computer object REMOVE

# 4b. Propagation
gpupdate /force            # pilot cihazda (manuel hızlandırma)
# doğal refresh: 90 dk + 0-30 dk random offset (kaydedilir)

# 4c. Assigned-MSI ise MSI otomatik uninstall YALNIZ GPO Software Installation
#     paketinde "Uninstall this application when it falls out of the scope of
#     management" SEÇENEĞİ AÇIKSA olur. Bu seçenek kapalıysa unlink paketi
#     KALDIRMAZ — manuel uninstall (D1) gerekir. Evidence'a hangi davranışın
#     geçerli olduğu yazılır (configured / not-configured → manuel).
gpresult /r                # GPO artık uygulanmıyor doğrula
```

**Beklenen**: unlink sonrası GPO cihazda görünmez (`gpresult /r`); assigned-MSI + "uninstall on scope exit" AÇIK ise paket otomatik kalkar, AKSİ HALDE manuel uninstall (D1) kullanılır; propagation süresi kaydedilir.

**Fail-sinyali**: "uninstall on scope exit" açık olmasına rağmen paket kalkmıyor; unlink sonrası MSI hâlâ reinstall ediliyor (accidental ikinci link — `gpresult /r` ile tüm GPO'lar denetlenir); propagation > pencere.

**Devam eşiği**: GPO unlink etkisi + propagation süresi kaydedildi → D5.

> **Operatör-gated**: bu adım AD ortamı + GPO link gerektirir; agent bu adımı **organize eder** (komut + beklenen + kayıt formatı) ama koşamaz. spawn_task chip ile takip edilir.

---

### D5 — Backend dark / pause (yeni install command üretimini durdur)

**Tetik**: dalga sırasında abort tetiklenirse veya drill kapsamında.

**Mekanizma doğrulaması (kaynak)**: endpoint-admin'de **global tek-tık dispatch kill-switch endpoint'i YOK**. Ayrıca **rollout ring agent claim sorgusunu filtrelemez** — `requiredDeploymentRing` yalnız **komut YARATMA** anında kontrol edilir (`EndpointAdminCommandService`), agent'ın `GET /api/v1/agent/commands/next` claim sorgusu (`EndpointCommandRepository`) yalnız device status + visibility + approval + status'a bakar, ring'e BAKMAZ. Sonuç: ring de-assign **yeni ring-hedefli komut yaratımını** durdurur ama **zaten QUEUED edilmiş** komutlar ring değişiminden sonra hâlâ claim edilebilir. Backend pause bu nedenle **operasyonel + kademeli**:

| Pause katmanı | Mekanizma (kaynak-doğru) | Komut |
|---|---|---|
| **1. Yeni komut üretimini durdur** (PRIMARY — #1379 "stops new install commands") | Admin-initiated `POST /endpoint-commands` durdurulur; agent yalnız poll eder — kuyruğa yeni komut girmezse yeni iş yok | (operasyonel — yeni POST atma) |
| **2. Rollout-ring de-assign** (yalnız YARATMA-zamanı gate) | Dalga cihazlarını dar ring'e çek → bundan SONRA o cihazlar için ring-hedefli **yeni** komut yaratılmaz; zaten queued komutları DURDURMAZ | `PATCH /api/v1/admin/endpoint-devices/{id}/rollout` `{"deploymentRing":"PILOT"}` |
| **3. Zaten-queued işi iptal et** (decommission cascade) | Pending/queued komutları gerçekten iptal eden **tek** mevcut yol — D3 decommission cascade (`cancelledCommands`) | `POST .../{id}/decommission` |

```bash
# Katman 3 — in-flight queued komutları iptal et (ring değil, cascade durdurur)
curl -sS -X POST "$BASE/api/v1/admin/endpoint-devices/$DEVICE_ID/decommission" \
  -H "Authorization: Bearer $MGR_TOKEN" -H "Content-Type: application/json" \
  -d '{"reason":"M7 wave pause — cancel queued"}' | jq '.status'   # -> DECOMMISSIONED
```

**Beklenen**: katman 1 sonrası yeni install command üretilmiyor (PRIMARY pause); katman 3 (decommission) zaten-queued komutları cascade-cancel eder; katman 2 yalnız sonraki yaratımları engeller (mevcut kuyruğu boşaltmaz).

**Fail-sinyali**: yeni POST durdurulmasına rağmen yeni komut görünüyor (başka admin/automation hâlâ POST ediyor); decommission sonrası cihaz hâlâ queued komut çekiyor (cascade bug → M7 stop).

**Devam eşiği**: katman 1 (+gerekirse 3) etkisi gözlendi → D6.

> **Gelecek hardening (board backlog)**: explicit `POST /api/v1/admin/rollout/pause` atomic global kill-switch endpoint'i M6/M7 öncesi eklenebilir (şu an operasyonel pause yeterli ama atomic değil + ring claim'i filtrelemediği için tek-tık dalga-durdurma yok). Bu runbook mevcut **gerçek** yüzeyi belgeler; uydurma endpoint YAZMAZ. Backlog'a yakalanır.

---

### D6 — Evidence retention + comms (~5 dk)

**Tetik**: D1-D5 tamamlandı.

**Yapılacaklar**:
1. Failed-device bundle (varsa) + audit row referansları (PII-redacted) `docs/faz-22-evidence/templates/m7-rollback-evidence.md` template'ine kaydet.
2. IT/help-desk comms (§7) gönderildi mi doğrula.
3. Drill recommendation: PASS → M5/M6 expansion açılabilir; FAIL → gate kapalı + root-cause class.

---

## 4. Rollback-of-rollback (drill'in kendisi fail ederse kurtarma)

| Drill fail | Kurtarma |
|---|---|
| Uninstall locked binary (1603) | `taskkill /F /IM endpoint-agent.exe` (tüm child'lar) → uninstall retry; hâlâ fail ise VM snapshot/restore point geri yükle |
| Reinstall ProductCode drift | Eski sürüm `Win32_Product` enumerate → manuel `msiexec /x <old-code>` → temiz reinstall |
| Decommission cascade cihazı kilitledi | `reactivate` ile geri al; reactivate de fail ediyorsa (409) backend lifecycle state DB'den incele (operatör) |
| GPO unlink MSI loop | İkinci accidental link kontrolü (`gpresult /r` tüm GPO'lar); link guard (§0.5.3 "accidental link guard") |

---

## 5. IT / help-desk comms template (§0.5.7)

> Dalga başlamadan **önce** IT owner + help-desk triage class'ları + escalation SLA yazılı olmalı.

```text
Konu: Endpoint Agent — rollback prosedürü ve kullanıcı etkisi (Faz 22.5 M7)

Owner: <IT owner adı>
Help-desk escalation SLA: <ör. P1 < 1 saat, P2 < 4 saat>

Kullanıcı etkisi:
- Rollback sırasında agent servisi durur; kullanıcı oturumu / dosyaları ETKİLENMEZ (agent read-only + komut-tabanlı).
- Reboot gerektirmez (msiexec /norestart); pending-reboot (exit 3010) varsa kullanıcı bilgilendirilir.

Triage class'ları (failed-device queue, §0.5.5):
- DNS/edge mTLS · Cert identity · Installer/MSI · Service/HMAC/mode · Backend result-submit · EDR/network

Eskalasyon: <kanal — Microsoft Teams kanalı; NOT Slack>
```

---

## 6. Acceptance eşlemesi (#1379)

| #1379 acceptance | Bu runbook |
|---|---|
| MSI uninstall + reinstall drill passes on one pilot device | D1 |
| Service, scheduled task, HKLM mode/env, log/cache verified after rollback | D2 |
| Enrollment revoke (HMAC or cert-bound); revoked device cannot receive commands until re-enrolled | D3 |
| GPO unlink/security-filter rollback + propagation time recorded | D4 |
| Backend rollout/dispatch pause stops new install commands | D5 |
| IT/help-desk communication + escalation owner documented | §5 |
| Rollback evidence attached before M6/M7 expansion | D6 + evidence template |

---

## 7. Agent-prepared vs operator-executed sınırı

| Hazırlık (agent — bu runbook + LIVE) | Canlı koşum (operatör-gated) |
|---|---|
| Runbook + komut + beklenen + fail-sinyal + evidence template (D2 manuel kontroller canonical) | 1 pilot cihaz + VM snapshot (P2/P6) |
| `wave-preflight.ps1 -Mode rollback-clean` opsiyonel otomasyon (**M5 PR**'ında gelir; drill zamanı mevcut) | endpoint-admin MANAGER token (P3) |
| Signed MSI (AG-018 LIVE) | GPO link + AD action (D4, P4) |
| Backend revoke/pause mekanizma doğrulaması (D3 decommission/reactivate + D5 katmanları kaynak-doğru) | Canlı drill koşumu + evidence doldurma |

---

## 8. Referanslar

- `docs/faz-22-software-deployment-plan.md` §0.5.3 / §0.5.7 / §0.5.9
- Backend revoke: `endpoint-admin-service` `AdminEndpointDeviceController` (`/decommission`, `/reactivate`), `EndpointDeviceLifecycleService` (Codex `019ea789`)
- Agent uninstall: `platform-agent` `installers/windows/uninstall.ps1` + `run-agent-install.ps1` (M4 ps1-wrapper, memory `project_faz225_m4_wix_msi`)
- Signed MSI: AG-018 internal-CA pipeline (memory `project_ag018_linux_signing_pivot`, v0.2.1 LIVE)
- Evidence template: `docs/faz-22-evidence/templates/m7-rollback-evidence.md`
- Cross-AI: implementer Claude ≠ reviewer Codex (HARD RULE)
