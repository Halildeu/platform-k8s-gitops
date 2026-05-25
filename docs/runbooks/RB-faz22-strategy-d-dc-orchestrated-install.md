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
- **Trusted Signing mandatory enforcement** — corp-managed device A1 SHA-pinned lab-only-evidence kabul edilebilir (operator + IT karar; A2 BYOD'dan farklı, oradaki trusted signing mandatory ayrı kapı)
- **BYOD/personal device** — A2 scope; consent + KVKK + uninstall self-service A2 BYOD ile (`RB-faz22-non-domain-windows-pilot.md` §12+§14.6)

---

## 2. Prerequisites (4 hard gate)

### 2.1 WinRM enabled hedef PC'lerde

**Test** (DC PowerShell admin, per-target):
```powershell
Test-WSMan -ComputerName <target-hostname>
```

**Beklenen**: WSMan response (ProductVendor + ProductVersion).
**Fail**: per-target `Enable-PSRemoting -Force` (Group Policy ile domain-wide enable tercih).

### 2.2 Domain Admin / Local Admin credential

DC RDP session zaten Domain Admin context'inde (user 2026-05-25). PowerShell Remoting `Invoke-Command` default current user credential kullanır.

**Alternatif** (explicit credential):
```powershell
$cred = Get-Credential -Message "Domain admin for agent install"
Invoke-Command -ComputerName <target> -Credential $cred -ScriptBlock { ... }
```

### 2.3 Hedef PC backend reachable

**Test**:
```powershell
Invoke-Command -ComputerName <target> -ScriptBlock {
  Test-NetConnection -ComputerName testai.acik.com -Port 443 -InformationLevel Quiet
}
```

**Beklenen**: `True` (HTTPS 443 reachable; proxy varsa override config gerek — IT'den teyit).
**Fail**: backend pin (test cluster) farklı; IT proxy config / DNS resolution kontrol.

### 2.4 IT/SOC onayı

EDR allowlist coordination (Strategy D risk register — Severity Medium):
- Agent SHA256 (binary hash)
- Service display name `EndpointAgent`
- Install path `C:\Program Files\EndpointAgent`
- Network destination `testai.acik.com:443` (prod scope ayrı kapı `ai.acik.com:443`)
- SOC ticket reference per-target

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

**Option A — RDP file drop** (default — Mac Microsoft Remote Desktop client):
1. Mac RDP client → Configure → Folders → Add local folder (read-only — security)
2. RDP session DC içinde → `\\tsclient\<drive>\<path>` ile Mac folder erişim
3. Agent installer copy: `Copy-Item \\tsclient\<drive>\<path>\install.ps1 C:\Temp\install.ps1`
4. Plus binary: `Copy-Item \\tsclient\<drive>\<path>\endpoint-agent.exe C:\Temp\endpoint-agent.exe`

**Option B — SMB share** (corp network varsa):
1. DC'de paylaşımlı network share (`\\dc\agent-installer$`) varsa
2. Mac → DC SMB upload (`smbclient //dc/agent-installer$ -U <admin>`)
3. Yoksa Option A daha kolay

**Option C — Public download** (release artifact public ise):
```powershell
# DC'de doğrudan indir (GitHub Releases public ise)
Invoke-WebRequest -Uri "https://github.com/Halildeu/platform-agent/releases/download/<tag>/endpoint-agent-windows-amd64.zip" -OutFile "C:\Temp\agent.zip"
Expand-Archive C:\Temp\agent.zip -DestinationPath C:\Temp\
```

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

# Hedef PC'de C:\Temp dir oluştur (yoksa)
$targets | ForEach-Object {
  Invoke-Command -ComputerName $_ -ScriptBlock {
    New-Item -Path "C:\Temp" -ItemType Directory -Force | Out-Null
  }
}

# Installer + script copy (PowerShell Remoting üzerinden file transfer)
$targets | ForEach-Object {
  $session = New-PSSession -ComputerName $_
  Copy-Item -Path $installerSource -Destination $installerDest -ToSession $session
  Copy-Item -Path $installScript -Destination "C:\Temp\install.ps1" -ToSession $session
  Remove-PSSession $session
}

# SHA256 verify hedef PC'de
$targets | ForEach-Object {
  Write-Host "=== $_ ==="
  Invoke-Command -ComputerName $_ -ScriptBlock {
    Get-FileHash -Algorithm SHA256 C:\Temp\endpoint-agent.exe
  }
}
```

---

## 5. Pilot install (per-target, sıralı veya paralel)

### 5.1 Enrollment token mint (Mac terminal — c5persona-admin-9001 JWT)

Mac terminal'de backend admin REST'e enrollment token request:
```bash
# Mac terminal — backend admin REST (test cluster context)
ADMIN_TOKEN=$(./scripts/get-admin-jwt.sh c5persona-admin-9001)   # operator script veya manuel kubectl exec
ENROLL_TOKEN=$(curl -sX POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  https://testai.acik.com/api/v1/endpoint-admin/enrollment-tokens \
  -d '{"description":"Strategy D pilot 2026-05-25"}' | jq -r '.token')
echo "ENROLL_TOKEN=$ENROLL_TOKEN"   # Mac terminal'de göster; DC'ye paste
```

**Plus enrollment token expiry** ~24h default; pilot install + smoke aynı pencerede.

### 5.2 Per-target install (PowerShell Remoting)

```powershell
$enrollToken = "<paste from Mac>"
$apiUrl = "https://testai.acik.com"
$targets = @("LAB-W10-01", "LAB-W11-02")

$targets | ForEach-Object {
  Write-Host "==================== Installing on $_ ===================="
  Invoke-Command -ComputerName $_ -ScriptBlock {
    param($url, $token)
    # Agent install via install.ps1 script
    & "C:\Temp\install.ps1" -ApiUrl $url -EnrollmentToken $token -Start
    Start-Sleep -Seconds 30
    # Verify service
    Get-Service EndpointAgent | Select-Object Name,Status,StartType
    # Verify enroll + heartbeat log
    Get-Content "C:\ProgramData\EndpointAgent\logs\agent.log" -Tail 20
  } -ArgumentList $apiUrl, $enrollToken
}
```

### 5.3 Backend enrollment verify (Mac terminal — per-target)

```bash
# Mac terminal — admin REST device list
curl -sH "Authorization: Bearer $ADMIN_TOKEN" \
  https://testai.acik.com/api/v1/endpoint-admin/devices | \
  jq '.devices[] | select(.hostname | startswith("LAB-")) | {id, hostname, lastHeartbeatAt, status}'
```

**Acceptance**: TÜM hedef PC'ler için `lastHeartbeatAt` 30sn-2dk içinde (heartbeat poll period); `status=ENROLLED`.

---

## 6. Post-install smoke (per-target)

### 6.1 COLLECT_INVENTORY command (non-destructive, ~65sn turnaround)

Mac terminal — admin REST command create per-device:

```bash
# Her hedef PC için
$DEVICE_IDS = jq -r '.devices[] | select(.hostname | startswith("LAB-")) | .id'

for DEVICE_ID in $DEVICE_IDS; do
  CMD_ID=$(curl -sX POST \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    https://testai.acik.com/api/v1/endpoint-admin/devices/$DEVICE_ID/commands \
    -d '{"type":"COLLECT_INVENTORY","parameters":{}}' | jq -r '.id')
  echo "Device $DEVICE_ID Command $CMD_ID created"
done

# 60sn bekle (agent poll + execute + result submit)
sleep 60

# Command lifecycle + result verify
for DEVICE_ID in $DEVICE_IDS; do
  curl -sH "Authorization: Bearer $ADMIN_TOKEN" \
    https://testai.acik.com/api/v1/endpoint-admin/devices/$DEVICE_ID/commands | \
    jq '.commands[0] | {id, type, status, createdAt, deliveredAt, startedAt, completedAt, resultSizeBytes}'
done
```

**Acceptance per-target**:
- `status: SUCCEEDED`
- `deliveredAt` + `startedAt` + `completedAt` mevcut
- `resultSizeBytes > 0`
- Audit row: `ENDPOINT_COMMAND_CREATED` event

### 6.2 Audit chain verify (Mac terminal — backend DB veya admin REST)

```bash
# Backend audit events
curl -sH "Authorization: Bearer $ADMIN_TOKEN" \
  "https://testai.acik.com/api/v1/endpoint-admin/audit-events?eventType=ENDPOINT_COMMAND_CREATED&limit=10" | \
  jq '.events[] | {id, eventType, deviceId, performedBySubject, createdAt}'
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
$targets = @("LAB-W10-01", "LAB-W11-02")

$targets | ForEach-Object {
  Write-Host "==================== Uninstalling on $_ ===================="
  Invoke-Command -ComputerName $_ -ScriptBlock {
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
```

### 9.2 Backend device decommission (Mac terminal — admin REST)

```bash
$DEVICE_IDS | ForEach-Object {
  curl -sX DELETE \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    https://testai.acik.com/api/v1/endpoint-admin/devices/$_
}
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
| WinRM blast radius (Domain Admin credential compromise = domain-wide attack surface) | Medium | Credential rotation post-pilot + WinRM session audit log + minimum required privilege per-target |
| EDR allowlist coverage gap (per-target SOC ticket eksikliği) | Medium | SOC pre-coordination + per-target allowlist verify + EDR alarm monitor |
| Multi-PC consent/awareness (corp-managed but user impact) | Low | IT/manager pre-notification + agent service description açıklayıcı |
| Agent installer transfer security (Mac → DC → target chain tamper riski) | Low | SHA256 verify her hop'ta + transit security (RDP encryption + WinRM HTTPS) |
| Hedef PC offline / sleep (soak gap) | Medium | declared sleep/reboot windows + offline >30dk flag + 24-72h soak window |
| Backend testai.acik.com reachability (proxy/firewall block) | Medium | Pre-install Test-NetConnection per-target + IT proxy config teyit |

### 10.2 Boundary (HARD constraints)

- **NOT production-ready** — pilot scope 1-3 lab PC; ~800 device domain rollout Faz 22.3+ ayrı kapı
- **NOT password-reset-ready** — Faz 22.2.B scope dışı (BE-017 destructive command fixture-only proven)
- **NOT GPO-mandatory** — pilot install ad-hoc per-target; GPO Software Installation Faz 22.3 restricted tier
- **NOT trusted-signing-mandatory pilot** — corp-managed device A1 SHA-pinned lab-only-evidence kabul edilebilir (operator + IT karar); A2 BYOD'dan farklı, oradaki trusted signing zorunlu kapı ayrı
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
