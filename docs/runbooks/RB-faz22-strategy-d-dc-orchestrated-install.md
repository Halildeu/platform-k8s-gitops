# RB Faz 22 Strategy D — DC-orchestrated domain-joined PC install runbook

> **Scope**: Faz 22.2.B IT pilot (acik.local) — Active Directory Domain Controller (DC) üzerinden PowerShell Remoting (`Invoke-Command`) ile **domain-joined corp Windows 10/11 PC'lere** Endpoint Agent install + smoke + soak observation + sanitized evidence.
>
> **NOT** scope: DC üzerine agent install (YASAK — critical infrastructure); domain-wide GPO Software Installation rollout (Faz 22.3 production tier); BYOD/personal device (A2 scope; ayrı `RB-faz22-non-domain-windows-pilot.md` §12+§14.6 appendix).
>
> **Cross-references**:
> - ADR-0012-EA "Strategy D decision (2026-05-25)" sub-section
> - `RB-faz22-non-domain-windows-pilot.md` §14 evidence template (Strategy D rollup ile cross-reference)
> - `RB-faz22-acik-local-vpn-routing-setup.md` Gate 0 VPN/routing prerequisites
> - Codex thread (yeni — Strategy D karar log için submission)
> - HARD RULE — Pre-Production Full Authority (CLAUDE.md global, 2026-04-29)

---

## 1. Scope

### 1.1 Strateji bağlamı

| Strategy | Tanım | Status |
|---|---|---|
| **Strategy A** | Fresh Mac Parallels VM domain join | DEFER (disk constraint) |
| **Strategy B** | Mevcut HALILKOOLUB735 Mac VM domain'e al | Historical (PR #1063 doc kalır; gerek YOK çünkü A1 baseline koruma + Strategy D primary) |
| **Strategy C** | RDP'deki corp PC = lab device | Düzeltildi (RDP target DC olduğu için yanlış senaryo idi) |
| **Strategy D (this RB)** | **DC üzerinden PowerShell Remoting ile domain-joined corp PC'lere agent install** | **Primary** |

### 1.2 Strategy D pilot scope

| Pilot tier | Hedef | Acceptance gate |
|---|---|---|
| **Single-PC IT pilot smoke** | 1 domain-joined corp Windows 10/11 PC | Install + enroll + heartbeat + COLLECT_INVENTORY + audit verify |
| **Multi-PC IT pilot smoke** | 2-3 domain-joined corp Windows 10/11 PC (paralel) | Per-PC smoke + 24-72h soak + multi-PC rollup evidence |
| **A1 multi-VM (#1044) alternative** | Domain-joined N-PC variant (workgroup multi-VM yerine) | Acceptance formula `pass_devices >= ceil(2 × N / 3)` Strategy D context'te |

### 1.3 Out of scope

- **DC üzerine agent install** (YASAK — critical infrastructure; domain-wide etki riski)
- **Destructive commands** (LOCK_USER_LOGIN/DISABLE_LOCAL_USER/password reset) — corp domain user'larında YASAK; non-destructive only (COLLECT_INVENTORY/inventory_refresh)
- **GPO Software Installation rollout** (Faz 22.3 restricted tier)
- **Trusted Signing MANDATORY (Codex iter-1 HIGH #1 düzeltme)** — 22.2 IT-owned `acik.local` pilot için trusted signing kontratı ADR-0012-EA §138'de **şart**. Real install öncesi `signtool verify /pa /v /tw <agent.exe>` PASS + Trusted Signing tenant subject match + RFC 3161 timestamp valid + thumbprint allowlist match (hard gate). A1 SHA-pinned lab-only-evidence istisnası **Strategy D kapsamında UYGULANMAZ** (A1 lab-only-evidence workgroup Mac Parallels smoke için; Strategy D corp PC A1 kapsamı değil).
- **BYOD/personal device** — A2 scope; consent + KVKK + uninstall self-service A2 BYOD ile (`RB-faz22-non-domain-windows-pilot.md` §12+§14.6)

---

## 2. Prerequisites (4 hard gate)

### 2.1 WinRM enabled hedef PC'lerde

**Test** (DC PowerShell admin, per-target):
```powershell
Test-WSMan -ComputerName <target-hostname>
```

**Beklenen**: WSMan response (ProductVendor + ProductVersion).
**Fail** (Codex iter-2 MEDIUM #2 düzeltme): **Domain-wide WinRM enable YASAK** (HIGH risk — §10.1). Alternatifler:
- **EndpointPilot OU scoped GPO** (sadece pilot OU'da WinRM enable; TTL süreli)
- **Per-target enable with TTL** (`Enable-PSRemoting -Force` per-target; pilot bitince `Disable-PSRemoting -Force`)
- **WinRM HTTPS 5986 with cert** (HTTP 5985 yerine; corp PKI cert deploy)

### 2.2 JIT/Scoped installer admin (Codex iter-1 HIGH #2 düzeltme — Domain Admin YASAK pilot install)

**Önceki yanlış pattern** (KALDIRILDI): "DC RDP session zaten Domain Admin context'inde; Invoke-Command default current user credential". Bu **HIGH severity risk** — Domain Admin credential pilot install + remoting = domain-wide blast radius.

**Doğru pattern** (Codex HIGH #2 mitigation):
- **JIT/scoped installer admin account** oluştur (örn. `acik\svc-endpoint-installer-2026-05-25`)
- Time-bound (sadece pilot install + smoke window — 24-48h)
- **EndpointPilot OU scoped** (sadece hedef PC'lerde admin yetki)
- Domain Admin değil — Local Administrators on target OU only
- PowerShell Remoting (`Invoke-Command`) bu hesapla çalıştır:

```powershell
# Create JIT installer admin (AD admin görevi, runbook scope dışı; reference)
# New-ADUser + Add-ADGroupMember (EndpointPilot OU Local Admins group)

# Pilot install zamanında JIT credential
$jitCred = Get-Credential -Message "JIT installer admin for Strategy D pilot (NOT Domain Admin)"
Invoke-Command -ComputerName <target> -Credential $jitCred -ScriptBlock { ... }

# Post-pilot: JIT admin disable + revoke OU membership + delete account
# (AD admin görevi; runbook §9 Rollback kapsamı)
```

**PowerShell transcription + script block logging** (audit zorunlu):
```powershell
# GPO veya per-target: Group Policy → Computer Config → Admin Templates → Windows Components → PowerShell
# - Turn on PowerShell Transcription → Enabled (output directory: \\dc\transcripts$)
# - Turn on PowerShell Script Block Logging → Enabled
# Per-session inline alternative:
Start-Transcript -Path "C:\Temp\strategy-d-install-$(Get-Date -Format yyyyMMdd-HHmmss).log"
```

**Post-pilot disable/revert** (rollback §9 + Codex HIGH #2):
- JIT installer admin disable + delete
- WinRM GPO scope kaldır (EndpointPilot OU dışında domain-wide enabled DEĞİL)
- WinRM enabled per-target ise per-target disable (`Disable-PSRemoting`)
- Transcription log archive (audit retention)

### 2.3 Hedef PC backend reachable

**Test** (JIT credential zorunlu — Codex iter-2 HIGH absorb):
```powershell
$jitCred = Get-Credential -Message "JIT installer admin for Strategy D pilot"
Invoke-Command -ComputerName <target> -Credential $jitCred -ScriptBlock {
  Test-NetConnection -ComputerName testai.acik.com -Port 443 -InformationLevel Quiet
}
```

**Beklenen**: `True` (HTTPS 443 reachable; proxy varsa override config gerek — IT'den teyit).
**Fail**: backend pin (test cluster) farklı; IT proxy config / DNS resolution kontrol.

### 2.4 IT/SOC onayı + Trusted Signing verify (Codex iter-1 HIGH #1 + MEDIUM #5 absorb)

**EDR allowlist coordination (10-item, Codex MEDIUM #5)**:
- Agent SHA256 (binary hash)
- **Signer/thumbprint** (Trusted Signing tenant cert subject + thumbprint allowlist)
- Service display name `EndpointAgent`
- Install path `C:\Program Files\EndpointAgent`
- **Process tree** (`powershell.exe` / `wsmprovhost.exe` parent context for Invoke-Command sessions; `endpoint-agent.exe` for runtime)
- **Parent context** (Invoke-Command session = WinRM remote; allowlist parent process chain)
- **Service creation** (Windows service install event 7045 audit allowlist)
- **Install script hash** (`install.ps1` SHA256 + signer if signed)
- Network destination `testai.acik.com:443` (prod scope ayrı kapı `ai.acik.com:443`)
- **Proxy/TLS inspection** (corp proxy MITM cert chain; SSL inspect bypass veya cert validation policy)
- **Detection outcome explicit** (per-target: allowed/alarmed/blocked; SOC ticket reference; baseline vs install delta)

**Trusted Signing pre-install hard gate (Codex HIGH #1)**:

```powershell
# Mac-side (pre-transfer): private release artifact fetch + Authenticode verify (precheck)
shasum -a 256 endpoint-agent.exe
# Mac-side precheck (operator workstation tooling); authoritative gate Windows signtool
osslsigncode verify endpoint-agent.exe   # CN/O capture

# Hedef PC üzerinde install ÖNCESİ (path C:\Temp\endpoint-agent.exe — pre-install transfer location; install sonrası C:\Program Files\EndpointAgent\)
Invoke-Command -ComputerName <target> -Credential $jitCred -ScriptBlock {
  signtool verify /pa /v /tw "C:\Temp\endpoint-agent.exe"
}
# Expected output:
#   "Successfully verified" (Authenticode)
#   "The signature is timestamped" (RFC 3161)
#   Signer subject: CN=<Trusted Signing tenant>, O=<org>
#   Thumbprint: <thumbprint> (must match operator allowlist)

# Operator runbook check: subject + thumbprint Trusted Signing tenant allowlist match
# Authoritative gate Windows signtool (Mac-side osslsigncode sadece precheck)
```

**Fail = install YASAK** — signed artifact yoksa pilot install başlamaz. A1 SHA-pinned lab-only-evidence istisnası Strategy D scope DIŞI.

---

## 3. Discovery (DC üzerinde, read-only — 2dk)

### 3.1 AD computer inventory

```powershell
# Tüm domain computer'ları (count + OS breakdown)
$allComputers = Get-ADComputer -Filter * -Properties Enabled,OperatingSystem,LastLogonDate
$allComputers | Group-Object -Property OperatingSystem | Select-Object Count,Name | Sort-Object Count -Descending

# Windows 10/11 workstation adayları (Server hariç)
$windows1011 = Get-ADComputer -Filter {
  OperatingSystem -like "*Windows 10*" -or OperatingSystem -like "*Windows 11*"
} -Properties OperatingSystem,LastLogonDate,Enabled
$windows1011 | Where-Object { $_.Enabled -and $_.LastLogonDate -gt (Get-Date).AddDays(-7) } |
  Select-Object Name,OperatingSystem,LastLogonDate |
  Sort-Object LastLogonDate -Descending |
  Format-Table -AutoSize

# OU yapısı (EndpointPilot OU varsa)
Get-ADOrganizationalUnit -Filter * | Select-Object Name,DistinguishedName
```

### 3.2 Aday PC seçimi

Operator/IT seçer (1-3 PC):
- EndpointPilot OU varsa → o OU'daki Windows 10/11 PC'ler
- EndpointPilot OU yoksa → IT'den lab/test designated PC'ler
- LastLogonDate aktif (son 7 gün) PC'ler tercih (kullanıcı offline değil)
- Domain user'larının agent install farkındalığı (notification opsiyonel ama iyi pratik)

### 3.3 WinRM enabled probe (per-target)

```powershell
$targets = @("LAB-W10-01", "LAB-W11-02")   # operator seçimi

$winrmResults = $targets | ForEach-Object {
  try {
    $wsman = Test-WSMan -ComputerName $_ -ErrorAction Stop
    [PSCustomObject]@{ Target = $_; WinRM = "PASS"; ProductVendor = $wsman.ProductVendor }
  } catch {
    [PSCustomObject]@{ Target = $_; WinRM = "FAIL"; Error = $_.Exception.Message }
  }
}
$winrmResults | Format-Table -AutoSize
```

**Acceptance gate**: TÜM hedef PC'ler WinRM PASS olmalı. Fail varsa GPO ile enable veya per-target `Enable-PSRemoting`.

---

## 4. Agent installer transfer (Mac → DC → hedef PC)

### 4.1 Mac → DC transfer (3 opsiyon)

**Codex iter-1 MEDIUM #5 absorb — DC'ye credential taşımak YASAK; Mac-side authenticated fetch primary**.

**Option A — Mac-side authenticated fetch + RDP file drop** (default, recommended):
1. Mac terminal — `platform-agent` private release artifact fetch (GitHub Auth Mac-side):
   ```bash
   gh release download <tag> --repo Halildeu/platform-agent --pattern '*windows-amd64*' --dir /tmp/agent
   shasum -a 256 /tmp/agent/endpoint-agent.exe   # SHA256 baseline
   # Authenticode verify (Mac-side osslsigncode veya operator visual review)
   osslsigncode verify /tmp/agent/endpoint-agent.exe   # CN/O capture
   ```
2. Mac RDP client → Configure → Folders → Add local folder (read-only)
3. RDP session DC içinde → `\\tsclient\<drive>\<path>` ile Mac folder erişim
4. Agent installer copy DC'ye: `Copy-Item \\tsclient\<drive>\<path>\install.ps1 C:\Temp\install.ps1`
5. Plus binary: `Copy-Item \\tsclient\<drive>\<path>\endpoint-agent.exe C:\Temp\endpoint-agent.exe`
6. **DC'de credential YOK** — sadece transfer; GitHub auth Mac-side

**Option B — Mac-side fetch + SMB share** (corp network varsa):
1. Mac terminal — Option A Step 1 (authenticated fetch + SHA + Authenticode verify)
2. Mac → DC SMB upload (`smbclient //dc/agent-installer$ -U <admin>`)
3. DC'de credential YOK

**Option C — Public download** (NOT pilot default per Codex MEDIUM #5):
**YASAK pilot default**. `platform-agent` private repo + private release artifact (ADR-0012-EA §603); DC'ye GitHub auth credential taşımak gerekir, bu güvenlik ihlali. Public download sadece OSS public release durumunda kabul edilebilir (ADR contract değişimi gerekir).

**Çağrı sırası** (Codex preference):
1. **Option A** (Mac-side authenticated fetch → RDP file drop) — recommended
2. **Option B** (Mac-side authenticated fetch → SMB share) — corp network mature olursa
3. **Option C** — YASAK pilot default (ADR contract değişimi gerek)

**Plus SHA256 verify her transfer hop'ta**:
```powershell
# Mac'te
shasum -a 256 endpoint-agent.exe

# DC'de
Get-FileHash -Algorithm SHA256 C:\Temp\endpoint-agent.exe
# SHA256 karşılaştır — match olmalı
```

### 4.2 DC → hedef PC transfer (PowerShell Remoting)

```powershell
$targets = @("LAB-W10-01", "LAB-W11-02")
$installerSource = "C:\Temp\endpoint-agent.exe"   # DC'de
$installScript = "C:\Temp\install.ps1"
$installerDest = "C:\Temp\endpoint-agent.exe"     # hedef PC'de (aynı path tercih)

# JIT credential (Codex iter-2 HIGH — tüm remoting JIT credential; Codex iter-3 duplicate removal)
$jitCred = Get-Credential -Message "JIT installer admin for Strategy D pilot"

# Hedef PC'de C:\Temp dir oluştur (yoksa) — JIT credential
$targets | ForEach-Object {
  Invoke-Command -ComputerName $_ -Credential $jitCred -ScriptBlock {
    New-Item -Path "C:\Temp" -ItemType Directory -Force | Out-Null
  }
}

# Installer + script copy (PowerShell Remoting + JIT credential)
$targets | ForEach-Object {
  $session = New-PSSession -ComputerName $_ -Credential $jitCred
  Copy-Item -Path $installerSource -Destination $installerDest -ToSession $session
  Copy-Item -Path $installScript -Destination "C:\Temp\install.ps1" -ToSession $session
  Remove-PSSession $session
}

# SHA256 verify hedef PC'de (JIT credential)
$targets | ForEach-Object {
  Write-Host "=== $_ ==="
  Invoke-Command -ComputerName $_ -Credential $jitCred -ScriptBlock {
    Get-FileHash -Algorithm SHA256 C:\Temp\endpoint-agent.exe
  }
}
```

---

## 5. Pilot install (per-target, sıralı veya paralel)

### 5.1 Per-target single-use enrollment token mint (Codex iter-1 MEDIUM #4 absorb)

**Önceki yanlış pattern** (KALDIRILDI): "Bir token mint, echo göster, tüm hedef PC'lere aynı token paste". Bu **enrollment token boundary ihlali** — token never logged + single-use predecessor policy ihlali.

**Doğru pattern** (per-target single-use):

```bash
# Mac terminal — backend admin REST (test cluster context)
ADMIN_TOKEN=$(./scripts/get-admin-jwt.sh c5persona-admin-9001)

# Per-target mint + target hash'li description (raw token evidence'a girMEZ)
TARGETS=("LAB-W10-01" "LAB-W11-02")

declare -A TARGET_TOKENS
declare -A TARGET_TOKEN_IDS   # Codex iter-2 MEDIUM #3 — id capture for revoke
for TARGET in "${TARGETS[@]}"; do
  TARGET_HASH=$(printf '%s' "$TARGET" | shasum -a 256 | cut -c1-12)
  TOKEN_RESPONSE=$(curl -fsX POST \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    "https://testai.acik.com/api/v1/endpoint-admin/endpoint-enrollments" \
    -d "{\"description\":\"Strategy D pilot 2026-05-25 target=$TARGET_HASH\",\"singleUse\":true}")
  TOKEN=$(printf '%s' "$TOKEN_RESPONSE" | jq -er '.token')
  TOKEN_ID=$(printf '%s' "$TOKEN_RESPONSE" | jq -er '.id')
  TARGET_TOKENS["$TARGET"]="$TOKEN"
  TARGET_TOKEN_IDS["$TARGET"]="$TOKEN_ID"
  # Token SHA truncate (evidence için; raw token logged DEĞİL)
  TOKEN_SHA=$(printf '%s' "$TOKEN" | shasum -a 256 | cut -c1-16)
  echo "Target=$TARGET_HASH TokenID=$TOKEN_ID TokenSHA=$TOKEN_SHA mintedAt=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
done

# Token TTL policy (Codex iter-2 MEDIUM #3 + iter-4 separate snippet):
# - Default TTL 24h (install + smoke window)
# - Install başarılıysa: token consumed (single-use) — DELETE gerek değil
# - Install failed veya skipped target için: unused revoke (ayrı snippet §5.1.x sonu)
# - Multi-day soak için: enrollment tek seferlik (post-enroll heartbeat/command JWT ayrı)
# - Expired before install → new per-target mint + old token DELETE; TTL extend YOK
```

### 5.1.x Post-pilot unused token revoke (separate snippet — Codex iter-4 REVISE absorb)

> **ÖNEMLİ**: Bu snippet §5.1 mint bloğunun parçası DEĞİL. Mint sırasında otomatik çalışmaz. Pilot install bittikten **sonra**, install fail/skip olan target'lar için operator manuel çalıştırır. `singleUse=true` token install başarılı olduğunda consumed; sadece **unused** (failed install / retry / skipped) tokenlar için DELETE gerek.

```bash
# Post-pilot / failed-install only — operator çalıştırır install bittikten sonra
# UNUSED_TOKEN_IDS array'i: install fail/skip olan target'ların token id'leri
UNUSED_TOKEN_IDS=()   # operator dolduracak (örn. "${TARGET_TOKEN_IDS[LAB-W10-FAIL-01]}")

for TOKEN_ID in "${UNUSED_TOKEN_IDS[@]}"; do
  curl -fsX DELETE \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "https://testai.acik.com/api/v1/endpoint-admin/endpoint-enrollments/$TOKEN_ID"
  echo "Unused token revoked: $TOKEN_ID"
done

# Alternative: TARGET_TOKEN_IDS map kullan + UNUSED_TARGETS over loop
# UNUSED_TARGETS=("LAB-W10-FAIL-01")
# for TARGET in "${UNUSED_TARGETS[@]}"; do
#   TOKEN_ID="${TARGET_TOKEN_IDS[$TARGET]}"
#   curl -fsX DELETE -H "Authorization: Bearer $ADMIN_TOKEN" \
#     "https://testai.acik.com/api/v1/endpoint-admin/endpoint-enrollments/$TOKEN_ID"
# done
```

**Semantic**: Install başarılı + device JWT aktif olan hedefin enrollment token'ı `singleUse=true` ile zaten consumed; backend taraf 2. kullanım reddeder. Sadece `unused`/`retry`/`failed install` tokenları DELETE edilir (orphan token sprawl önle).

**Plus evidence retention policy** (Codex MEDIUM #4):
- Raw enrollment token **NEVER logged in evidence docs** — sadece SHA truncate + mintedAt + targetHash
- Unused token revoke (post-pilot) — admin REST `DELETE /endpoint-enrollments/<id>`
- Target hash'li description audit trail

### 5.2 Per-target install (PowerShell Remoting + JIT credential)

```powershell
# JIT installer admin credential (Codex HIGH #2)
$jitCred = Get-Credential -Message "JIT installer admin for Strategy D pilot"

# Per-target install (per-target token + JIT cred)
$apiUrl = "https://testai.acik.com"
$targets = @{
  "LAB-W10-01" = "<token-1 from Mac per-target mint>"
  "LAB-W11-02" = "<token-2 from Mac per-target mint>"
}

foreach ($target in $targets.Keys) {
  $token = $targets[$target]
  Write-Host "==================== Installing on $target ===================="

  # Trusted Signing pre-install verify (Codex HIGH #1)
  $verifyResult = Invoke-Command -ComputerName $target -Credential $jitCred -ScriptBlock {
    signtool verify /pa /v /tw "C:\Temp\endpoint-agent.exe" 2>&1
  }
  if ($verifyResult -notmatch "Successfully verified") {
    Write-Host "❌ Trusted Signing verify FAIL on $target — install YASAK"
    continue
  }

  # Install
  Invoke-Command -ComputerName $target -Credential $jitCred -ScriptBlock {
    param($url, $token)
    & "C:\Temp\install.ps1" -ApiUrl $url -EnrollmentToken $token -Start
    Start-Sleep -Seconds 30
    Get-Service EndpointAgent | Select-Object Name,Status,StartType
    Get-Content "C:\ProgramData\EndpointAgent\logs\agent.log" -Tail 20
  } -ArgumentList $apiUrl, $token
}
```

### 5.3 Backend enrollment verify (Mac terminal — per-target canonical API path)

```bash
# Mac terminal — admin REST device list (canonical path: endpoint-devices)
curl -fsH "Authorization: Bearer $ADMIN_TOKEN" \
  "https://testai.acik.com/api/v1/endpoint-admin/endpoint-devices" | \
  jq -e '.devices[] | select(.hostname | startswith("LAB-")) | {id, hostname, lastHeartbeatAt, status}'
```

**Acceptance**: TÜM hedef PC'ler için `lastHeartbeatAt` 30sn-2dk içinde (heartbeat poll period); `status=ENROLLED`.

---

## 6. Post-install smoke (per-target)

### 6.1 COLLECT_INVENTORY command (non-destructive, ~90-120sn p95 turnaround)

> **Codex iter-1 MEDIUM #3 absorb**: API path canonical düzeltme (`endpoint-devices`) + bash syntax error fix (proper variable assignment + `curl -f` + `jq -e` fail-fast).

```bash
# Mac terminal — admin REST command create per-device

# Önce device ID'leri al (canonical path: endpoint-devices)
DEVICE_IDS=$(curl -fsH "Authorization: Bearer $ADMIN_TOKEN" \
  "https://testai.acik.com/api/v1/endpoint-admin/endpoint-devices" | \
  jq -er '.devices[] | select(.hostname | startswith("LAB-")) | .id')

# Per-device COLLECT_INVENTORY command create
declare -A DEVICE_COMMANDS
for DEVICE_ID in $DEVICE_IDS; do
  CMD_RESPONSE=$(curl -fsX POST \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    "https://testai.acik.com/api/v1/endpoint-admin/endpoint-devices/$DEVICE_ID/commands" \
    -d '{"type":"COLLECT_INVENTORY","parameters":{}}')
  CMD_ID=$(printf '%s' "$CMD_RESPONSE" | jq -er '.id')
  DEVICE_COMMANDS["$DEVICE_ID"]="$CMD_ID"
  echo "Device $DEVICE_ID Command $CMD_ID created"
done

# 120sn bekle (agent poll + execute + result submit; Codex MEDIUM #3 p95 threshold)
sleep 120

# Command lifecycle + result verify per-device
for DEVICE_ID in "${!DEVICE_COMMANDS[@]}"; do
  CMD_ID="${DEVICE_COMMANDS[$DEVICE_ID]}"
  curl -fsH "Authorization: Bearer $ADMIN_TOKEN" \
    "https://testai.acik.com/api/v1/endpoint-admin/endpoint-devices/$DEVICE_ID/commands/$CMD_ID" | \
    jq -e '. | {id, type, status, createdAt, deliveredAt, startedAt, completedAt, resultSizeBytes}'
done
```

**Acceptance per-target**:
- `status: SUCCEEDED`
- `deliveredAt` + `startedAt` + `completedAt` mevcut
- `resultSizeBytes > 0`
- `completedAt - createdAt <= 120sn p95` (Codex MEDIUM #3 — Strategy D context'inde WinRM overhead bekleyebilir)
- Audit row: `ENDPOINT_COMMAND_CREATED` event

### 6.2 Audit chain verify (Mac terminal — canonical API path)

```bash
# Backend audit events (canonical path)
curl -fsH "Authorization: Bearer $ADMIN_TOKEN" \
  "https://testai.acik.com/api/v1/endpoint-admin/endpoint-audit-events?eventType=ENDPOINT_COMMAND_CREATED&limit=10" | \
  jq -e '.events[] | {id, eventType, deviceId, performedBySubject, createdAt}'
```

**Acceptance**: Her hedef PC için ENDPOINT_COMMAND_CREATED audit event mevcut + `performedBySubject` = c5persona-admin-9001 forensic correlation.

---

## 7. 24-72h soak observation (multi-PC)

### 7.1 Heartbeat continuity monitoring

```bash
# Mac terminal — periodic check (cron veya manuel)
while true; do
  curl -sH "Authorization: Bearer $ADMIN_TOKEN" \
    https://testai.acik.com/api/v1/endpoint-admin/devices | \
    jq -r '.devices[] | select(.hostname | startswith("LAB-")) | "\(.hostname) heartbeat:\(.lastHeartbeatAt) status:\(.status)"'
  sleep 60
done
```

### 7.2 Soak acceptance (per-target, 24-72h)

`RB-faz22-non-domain-windows-pilot.md` §11 soak observation kriterleri Strategy D context'te uygulanır:
- Min 24h heartbeat continuous (planned reboot/sleep windows declared)
- Offline gap > 30 dk → flag (acceptance: 0 unexplained)
- Tüm planned non-destructive commands accounted (CREATED → SUCCEEDED veya FAILED-with-reason)
- Agent service no unexplained crash/uninstall/tamper events

### 7.3 Soak gap incidents (multi-PC aggregate)

§14.5 aggregate metric formula Strategy D context'te:
- `unexplained_gaps_total = sum(unexplained gaps per device)` — acceptance: **0**
- `heartbeat_success_rate >= 99%` per-target
- `command_success_rate >= 95%` per-target

---

## 8. Multi-PC evidence rollup (Strategy D context)

### 8.1 Per-device evidence doc path

```
docs/faz-22-evidence/YYYY-MM-DD-strategy-d-pilot-<device-hash>.md
```

### 8.2 Required fields (per-device)

`RB-faz22-non-domain-windows-pilot.md` §14.2 template Strategy D context'te uyarlanır:
- Section 1: Bağlam + ortam (DC hostname hash + RDP transport + target PC hostname hash)
- Section 2: Identity classification (B1 Hybrid Azure AD-joined veya B2 acik.local AD domain-joined per ADR-0012-EA tier)
- Section 3: Backend reachability + install + enroll + heartbeat + command lifecycle
- Section 4: Audit chain + sanitized output
- Section 5: Soak observation (heartbeat + commands + gaps)
- Section 6: Rollback evidence (varsa)
- Cross-AI peer review chain

### 8.3 Pilot-wide rollup (multi-PC)

`RB-faz22-non-domain-windows-pilot.md` §14.3+§14.4+§14.5 rollup template Strategy D context'te uygulanır:
- §14.4 6-bölüm rollup template + Strategy D-specific addendum:
  - **§D1 DC orchestration evidence**: DC RDP transport + PowerShell Remoting log per-target + WinRM session log + installer SHA256 verify per-target
  - **§D2 EDR allowlist coverage**: SOC ticket per-target + agent allowlist verify per-target
  - **§D3 Multi-PC heartbeat aggregate**: per-target heartbeat success rate + soak gaps
- Verdict matrix `pass_devices >= ceil(2 × N / 3)` (3→2, 2→2)

---

## 9. Rollback (per-target uninstall)

### 9.1 Per-target uninstall via PowerShell Remoting

```powershell
$jitCred = Get-Credential -Message "JIT installer admin for uninstall (Codex HIGH absorb)"
$targets = @("LAB-W10-01", "LAB-W11-02")

$targets | ForEach-Object {
  Write-Host "==================== Uninstalling on $_ ===================="
  Invoke-Command -ComputerName $_ -Credential $jitCred -ScriptBlock {
    # Agent service stop (maintenance token gerek olabilir; BE-013)
    Stop-Service EndpointAgent -Force -ErrorAction SilentlyContinue
    # Uninstall via installer
    & "C:\Temp\install.ps1" -Uninstall
    # Verify service removed
    Get-Service EndpointAgent -ErrorAction SilentlyContinue
    # Cleanup install dir + log dir
    Remove-Item "C:\Program Files\EndpointAgent" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item "C:\ProgramData\EndpointAgent" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item "C:\Temp\endpoint-agent.exe" -Force -ErrorAction SilentlyContinue
    Remove-Item "C:\Temp\install.ps1" -Force -ErrorAction SilentlyContinue
  }
}

# Post-pilot JIT admin disable + revoke (Codex iter-2 HIGH absorb)
# - JIT installer admin disable + delete (AD admin görevi)
# - WinRM GPO EndpointPilot OU scope kaldır (eğer scoped enable)
# - Per-target Disable-PSRemoting (eğer per-target enable yapıldıysa)
$targets | ForEach-Object {
  Invoke-Command -ComputerName $_ -Credential $jitCred -ScriptBlock {
    # Sadece per-target WinRM enable yapıldıysa
    # Disable-PSRemoting -Force
  }
}
# Transcript share ACL + log retention owner (audit retention SOC ile koordine)
```

### 9.2 Backend device decommission (Mac terminal — canonical API path)

```bash
# Mac bash — proper variable iteration (Codex MEDIUM #3 bash syntax fix)
for DEVICE_ID in $DEVICE_IDS; do
  curl -fsX DELETE \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    "https://testai.acik.com/api/v1/endpoint-admin/endpoint-devices/$DEVICE_ID"
done

# Verify decommissioned
curl -fsH "Authorization: Bearer $ADMIN_TOKEN" \
  "https://testai.acik.com/api/v1/endpoint-admin/endpoint-devices" | \
  jq -e '.devices[] | select(.hostname | startswith("LAB-"))'   # empty bekleniyor
```

### 9.3 AD computer object — UNCHANGED

**Önemli**: Strategy D uninstall AD computer object'ı **etkilemez**. Hedef PC'ler domain-joined kalır (corp-managed device); sadece agent install/uninstall scope. Strategy B'den (snapshot+AD cleanup zorunlu) farklı.

### 9.4 SOC EDR allowlist remove (opsiyonel)

Eğer pilot kapanıyorsa SOC'a allowlist remove ticket; eğer Faz 22.3'e geçiş planı varsa allowlist korunur.

---

## 10. Risk + boundary

### 10.1 Strategy D-specific risks (ADR-0012-EA cross-reference)

| Risk | Severity | Mitigation |
|---|:---:|---|
| **WinRM blast radius / Domain Admin credential compromise = domain-wide attack surface** | **HIGH** (Codex iter-1 HIGH #2) | **JIT/scoped installer admin** (separate account, time-bound, EndpointPilot OU scope, NOT Domain Admin) + **EndpointPilot OU scoped WinRM/GPO** (no domain-wide WinRM enable) + **PowerShell transcription + script block logging** (audit zorunlu) + **target allowlist** (per-pilot session) + **post-pilot disable/revert** (JIT admin delete + WinRM GPO scope kaldır + per-target Disable-PSRemoting) |
| **Trusted Signing verify gap** (signed artifact yoksa install) | **HIGH** (Codex iter-1 HIGH #1) | Real install öncesi `signtool verify /pa /v /tw` PASS + Trusted Signing tenant subject match + RFC 3161 timestamp + thumbprint allowlist match (hard gate; install YASAK if fail); ADR-0012-EA §138 22.2 IT pilot Authenticode contract enforced |
| **EDR allowlist coverage gap** (per-target SOC ticket eksikliği) | Medium | SOC pre-coordination + per-target 10-item allowlist (agent SHA + signer/thumbprint + service name + install path + process tree + parent context + service creation + install script hash + network destination + proxy/TLS inspection + detection outcome explicit) |
| Multi-PC consent/awareness (corp-managed but user impact) | Low | IT/manager pre-notification + agent service description açıklayıcı |
| **Agent installer transfer security** (Mac → DC → target chain tamper riski) | Low | **Mac-side authenticated fetch** (private release artifact + GitHub Auth) + **SHA256 + Authenticode verify** her hop'ta + **DC'ye credential taşımaz** (Mac-side download, DC RDP/SMB transfer only) + transit security (RDP encryption + WinRM HTTPS 5986) |
| Hedef PC offline / sleep (soak gap) | Medium | declared sleep/reboot windows + offline >30dk flag + 24-72h soak window + per-target heartbeat ≥99% acceptance (not aggregate) |
| Backend testai.acik.com reachability (proxy/firewall block) | Medium | Pre-install Test-NetConnection per-target + IT proxy config teyit + corp MITM cert chain handling |
| **Unused enrollment token sprawl** (post-pilot revoke unutulursa) | Low | Per-target single-use mint + unused token DELETE post-pilot + token SHA truncate evidence (raw token NEVER logged) |

### 10.2 Boundary (HARD constraints)

- **NOT production-ready** — pilot scope 1-3 lab PC; ~800 device domain rollout Faz 22.3+ ayrı kapı
- **NOT password-reset-ready** — Faz 22.2.B scope dışı (BE-017 destructive command fixture-only proven)
- **NOT GPO-mandatory** — pilot install ad-hoc per-target; GPO Software Installation Faz 22.3 restricted tier
- **Trusted Signing MANDATORY pilot install** — signed artifact + Authenticode + Trusted Signing tenant subject match + RFC 3161 timestamp + thumbprint allowlist match hard gate; A1 SHA-pinned lab-only-evidence istisnası Strategy D scope DIŞI (ADR-0012-EA §138 + Codex iter-1 HIGH #1)
- **Non-destructive commands ONLY** — COLLECT_INVENTORY/inventory_refresh; LOCK_USER_LOGIN/DISABLE/password reset YASAK pilot scope'ta (BE-017 dual-control test cluster fixture only)
- **DC üzerine agent install YASAK** — critical infrastructure; domain-wide etki riski
- **AD computer object scope** — Strategy D uninstall AD object'i etkilemez; corp-managed device domain-joined kalır

---

## 11. Cross-AI peer review chain

| Document/PR | Implementer | Reviewer | Codex thread |
|---|---|---|---|
| This RB (Strategy D karar log) | Claude (Anthropic) — Session 51 | Codex (OpenAI) — yeni thread submission | TBD post-impl review |
| ADR-0012-EA "Strategy D decision" sub-section | Claude (Anthropic) | Codex (OpenAI) | aynı thread |
| Per-target evidence doc PR (post-pilot) | Claude (Anthropic) | Codex (OpenAI) | per-evidence thread |
| Multi-PC rollup evidence PR (post-soak) | Claude (Anthropic) | Codex (OpenAI) | per-rollup thread |

---

## 12. Status

**Status**: Active — Strategy D karar log canonical (this PR scope). Operator action chain pending:
1. ⏳ Hedef PC seçim + WinRM probe (operator + IT)
2. ⏳ Backend reachability per-target
3. ⏳ IT/SOC EDR allowlist coordination
4. ⏳ Agent installer transfer (Mac → DC → target)
5. ⏳ Pilot install + smoke + soak
6. ⏳ Per-target + multi-PC rollup evidence PR

**Tracked by**:
- ADR-0012-EA "Strategy D decision (2026-05-25)" sub-section
- #1037 gitops (Faz 22.2 IT pilot acik.local — Strategy D unblocks Gate 0)
- #1015 gitops (IT pilot readiness umbrella — Strategy D path)
- #1044 gitops (A1 multi-VM — Strategy D N-PC variant alternative)
- RB-faz22-non-domain-windows-pilot.md §14 (evidence template; Strategy D rollup ile cross-reference)
- HARD RULE — Pre-Production Full Authority (CLAUDE.md global, 2026-04-29)
