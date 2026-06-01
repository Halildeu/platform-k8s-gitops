# RB-endpoint-agent-binary-upgrade

> ⛔ **LAB ONLY — Faz 22.1**. Domain-joined, IT-owned, production veya real-user
> pilot cihazda **KULLANMA**. Production IT-owned pilot Faz 22.2'de Azure
> Trusted Signing + remote PowerShell session pattern ile **ayrı runbook**.
> Bu runbook **single-operator + isolated lab device** scope'unda fail-closed.

Endpoint Agent Windows binary upgrade (in-place service stop + replace +
start). Codex `019e83ef-bc8e-71c3-ac6d-fb92e5d4235f` REVISE iter-1
(9 must-fix + 3 nice-to-have) + iter-2 (4 must-fix + 3 nice-to-have)
absorb edildi (2026-06-01).

**PowerShell preamble (zorunlu — R2-MF-01)**:

```powershell
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
```

Tüm mutation cmdlet'leri explicit `-ErrorAction Stop` ile çağrılır; native
`.exe` çağrıları sonrası `$LASTEXITCODE` kontrol edilir.

**Tetik**: Yeni binary release (örn. PR #25 absorb sha-1e915a2) cihaza
deploy edilmeli + agent yeni davranışla heartbeat etmeli.

**Ön koşul**:
- Hedef cihaz Endpoint Agent zaten kurulu (eski sürüm çalışıyor)
- Çalışan tek bir `EndpointAgent` Windows servisi var
- **Cihaz domain'e bağlı DEĞİL** (lab-isolated)
- **Lab allowlist** (R2-NH-02 — scope metadata table):

| Hostname | Owner | Device class | PartOfDomain | Lab auth date |
|---|---|---|---|---|
| `HALILKOOLUB735` | Halil | Parallels W11 lab VM (Mac host) | False | 2026-04-22 |
| `SRB-AIDENETIMPC` | Halil | Lab desktop pilot (HARD RULE — Pre-Production Full Authority) | False | 2026-04-29 |

> SRB-AIDENETIMPC pre-production lab pilot. Production cihaz değildir;
> Faz 22.2 production runbook'a IT-owned pilot başlayınca bu liste
> revize edilir.

- Operator elevated PowerShell + lokal admin yetkisine sahip

**Geri alma**: Pre-upgrade snapshot (Adım 0) zorunlu. Backup binary + hash
+ PID + ACL kaydedilmeden upgrade başlamaz.

---

## ⛔ Preflight gate (mutation ÖNCESİ — abort senaryoları)

```powershell
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# PF-1: Domain-join guard (MF-09)
$cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
if ($cs.PartOfDomain) {
    throw "ABORT: PartOfDomain=True. Bu runbook lab-only; domain-joined cihazlar Faz 22.2 production runbook için."
}

# PF-2: Hostname allowlist (MF-09)
$LabHostAllowlist = @('HALILKOOLUB735', 'SRB-AIDENETIMPC')
if ($env:COMPUTERNAME -notin $LabHostAllowlist) {
    throw "ABORT: $($env:COMPUTERNAME) lab allowlist'te değil. Allowlist'i runbook'ta açık güncelle ve cross-AI review tekrar al."
}

# PF-3: Concurrency lock — atomic acquisition (R2-MF-03)
$LockDir = 'C:\ProgramData\EndpointAgent'
$LockFile = Join-Path $LockDir 'upgrade.lock'
New-Item -ItemType Directory -Force -Path $LockDir -ErrorAction Stop | Out-Null

$LockBody = ConvertTo-Json -Compress @{
    operator     = $env:USERNAME
    computerName = $env:COMPUTERNAME
    pid          = $PID
    runbook      = 'RB-endpoint-agent-binary-upgrade.md v2 (Codex 019e83ef iter-2 absorb)'
    timestamp    = (Get-Date -Format o)
}

# Atomic create — fails terminating-error if file already exists.
# Check-then-write race YASAK; existing lock = başka operator var.
try {
    New-Item -Path $LockFile -ItemType File -Value $LockBody -ErrorAction Stop | Out-Null
} catch [System.IO.IOException] {
    # File already exists; surface owner for triage
    $existing = (Get-Content -LiteralPath $LockFile -ErrorAction SilentlyContinue) -join ' '
    throw "ABORT: Upgrade lock zaten var: $existing. Başka operator çalıştırıyor olabilir. Orphan ise: Remove-Item $LockFile -Force"
}

try {
    # PF-4: ACL preflight (MF-07) — observational + non-destructive WRITE PROBE (R2-MF-04)
    icacls 'C:\Program Files\EndpointAgent' | Out-Default
    icacls 'C:\Program Files\EndpointAgent\endpoint-agent.exe' | Out-Default

    # Non-destructive write probe: create + delete unique temp file in install dir.
    # If write fails here (DACL deny), abort BEFORE service stop — no down-time risk.
    $InstallDir = 'C:\Program Files\EndpointAgent'
    $WriteProbe = Join-Path $InstallDir ".upgrade-write-probe-$([guid]::NewGuid().Guid).tmp"
    try {
        New-Item -Path $WriteProbe -ItemType File -ErrorAction Stop | Out-Null
        Remove-Item -LiteralPath $WriteProbe -Force -ErrorAction Stop
    } catch {
        throw "ABORT: Install dir write probe FAIL — DACL deny veya disk full. Service stop YAPILMADI. icacls çıktısını incele; gerekirse break-glass (aşağıda)."
    }

    # PF-5: Service single-instance check
    $svc = Get-Service EndpointAgent -ErrorAction Stop
    if ($svc.Status -ne 'Running') {
        throw "ABORT: Service Status=$($svc.Status). Beklenen=Running. Önce mevcut state debug et."
    }
} catch {
    if (Test-Path $LockFile) { Remove-Item $LockFile -Force }
    throw
}
```

> **Eğer PF-4 ACL preflight'ta Administrators write yetkisi yoksa**: install.ps1
> tarafından konulan SYSTEM-only DACL devrede. Lab break-glass:
> ```powershell
> takeown /F 'C:\Program Files\EndpointAgent\endpoint-agent.exe'
> icacls 'C:\Program Files\EndpointAgent\endpoint-agent.exe' /grant Administrators:M
> # ... mutation ...
> # Sonra original ACL restore:
> icacls 'C:\Program Files\EndpointAgent\endpoint-agent.exe' /reset
> ```
> Bu break-glass production'da YASAK; Faz 22.2 supported maintenance-token /
> LocalSystem context pattern kullanır.

---

## Operator action (sıralı adımlar)

### 0. Pre-upgrade snapshot (MF-04 zorunlu)

```powershell
# Snapshot dizini (timestamped)
$Ts = (Get-Date -Format 'yyyyMMdd-HHmmss')
$SnapDir = "C:\ProgramData\EndpointAgent\upgrade-snapshots\$Ts"
New-Item -ItemType Directory -Force -Path $SnapDir -ErrorAction Stop | Out-Null

$InstallDir   = 'C:\Program Files\EndpointAgent'
$InstalledExe = Join-Path $InstallDir 'endpoint-agent.exe'
$BackupExe    = Join-Path $InstallDir "endpoint-agent.exe.bak-$Ts"  # R2-MF-02: double-quote expansion

# Old binary backup + hash
Copy-Item -LiteralPath $InstalledExe -Destination (Join-Path $SnapDir 'endpoint-agent.exe.bak') -Force -ErrorAction Stop
$OldHash = (Get-FileHash -LiteralPath $InstalledExe -Algorithm SHA256).Hash
$OldVer  = (Get-Item -LiteralPath $InstalledExe).VersionInfo.FileVersion
$OldSvc  = Get-CimInstance Win32_Service -Filter "Name='EndpointAgent'" -ErrorAction Stop
$OldPid  = $OldSvc.ProcessId
$OldPath = $OldSvc.PathName

@{
    timestamp     = $Ts
    installedExe  = $InstalledExe
    oldHash       = $OldHash
    oldVersion    = $OldVer
    oldPid        = $OldPid
    oldPath       = $OldPath
    operator      = $env:USERNAME
    computerName  = $env:COMPUTERNAME
    backupPath    = $BackupExe
} | ConvertTo-Json | Out-File -LiteralPath (Join-Path $SnapDir 'pre-upgrade.json') -Encoding UTF8 -ErrorAction Stop

icacls $InstalledExe > (Join-Path $SnapDir 'old-acl.txt')

Write-Host "Snapshot:  $SnapDir"
Write-Host "OldHash:   $OldHash"
Write-Host "OldPid:    $OldPid"
Write-Host "BackupExe: $BackupExe"
```

### 1. Fresh enrollment token üret

Web UI: `https://testai.acik.com/endpoint-admin/enrollments` → **+ Yeni
Enrollment Oluştur** → Açıklama: `<HOSTNAME> binary upgrade re-enroll`
→ **Oluştur** → token'ı **hemen kopyala** (tek-defa-görünür reveal
pattern; modal kapatılınca tekrar gösterilmez).

Token TTL default 60 dakika. Adım 4'e kadar zaman var.

**Token hijyeni** (NH-03):
- Token'ı clipboard veya bir terminal scrollback'e echo etme
- PowerShell history'ye düşmesini engelle:
  ```powershell
  Set-PSReadlineOption -HistorySaveStyle SaveNothing
  ```
- Token sadece Adım 4'te `$EnrollmentToken` variable'a atanır + Adım 7'de Machine env'den `$null` ile **temizlenir** (MF-01).

### 2. Binary'yi indir + SHA256 verify (MF-02)

İki yol:

**Yol A — GitHub Actions artifact**:

```
https://github.com/Halildeu/platform-agent/actions/runs/<RUN_ID>
```

`endpoint-agent-lab-evidence-<RUN_ID>` artifact'ını indir, zip aç.
İçinde:

- `endpoint-agent.exe` (signed lab cert, ~7 MB)
- `SHA256SUMS` (expected hash manifest)
- `SIGNING-EVIDENCE.md` (lab cert thumbprint + signtool verify çıktısı)

```powershell
$StagedExe   = 'C:\Path\To\downloaded\endpoint-agent.exe'   # zip aç dizini
$ExpectedSha = '<SHA256SUMS dosyasından oku>'               # 64-hex char

# R2-NH-01: 22.1 LAB — SHA256 = HARD GATE; signtool = WARN-only capture.
$StagedHash = (Get-FileHash -LiteralPath $StagedExe -Algorithm SHA256).Hash
if ($StagedHash -ne $ExpectedSha) {
    throw "ABORT: Staged binary hash mismatch. Expected=$ExpectedSha Got=$StagedHash"
}

# Optional signtool capture (lab cert için /pa /v WARN-only — exit code logged, not gated).
$Signtool = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe'
if (Test-Path $Signtool) {
    & $Signtool verify /pa /v $StagedExe 2>&1 | Tee-Object -FilePath (Join-Path $SnapDir 'signtool.log')
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "signtool verify non-zero (exit=$LASTEXITCODE). 22.1 lab unsigned-SHA-pinned exception — devam (WARN-only). 22.2 production runbook hard gate."
    }
} else {
    Write-Warning "signtool.exe yok — SHA256 pinning yeterli (22.1 lab); 22.2 production'da hard gate gerekecek."
}
```

**Yol B — Operator portal download** (gelecekte, BL-016 binary
distribution UI): henüz aktif değil. Şu an Yol A.

### 3. Service stop — fail-closed (MF-03)

```powershell
Stop-Service EndpointAgent -Force -ErrorAction Stop

# Polling (toplam ~30s)
$tries = 0
while ((Get-Service EndpointAgent -ErrorAction Stop).Status -ne 'Stopped' -and $tries -lt 15) {
    Start-Sleep -Seconds 2
    $tries++
}

$finalStatus = (Get-Service EndpointAgent -ErrorAction Stop).Status
if ($finalStatus -ne 'Stopped') {
    # FAIL-CLOSED: mutation yapma; eski binary yerinde
    sc.exe queryex EndpointAgent | Out-Default
    Write-Host "Service didn't stop. Status=$finalStatus. Snapshot=$SnapDir"
    # Recovery: yeniden Start (eski binary)
    Start-Service EndpointAgent -ErrorAction SilentlyContinue
    if (Test-Path $LockFile) { Remove-Item $LockFile -Force -ErrorAction SilentlyContinue }
    throw "ABORT: Service stop timeout. Original binary intact. Bkz $SnapDir."
}
```

> **Lab break-glass** (force-kill): normal path YASAK. Operator açık
> confirmation + post-kill file-lock check yapacaksa ayrı blokta uygula.
> Production runbook (Faz 22.2) Service Control Manager API ile graceful
> shutdown + force-kill quarantine kullanır.

### 4. Atomic binary replace — staged + try/catch/finally (MF-05)

```powershell
# Not: $InstallDir + $InstalledExe + $BackupExe Adım 0'da set edildi.
$TempExe = Join-Path $InstallDir 'endpoint-agent.exe.new'
$BadExe  = Join-Path $InstallDir 'endpoint-agent.exe.bad'

try {
    # 4a. Yeni binary'yi temp path'e kopyala (aynı volume; atomic rename için)
    Copy-Item -LiteralPath $StagedExe -Destination $TempExe -Force -ErrorAction Stop

    # 4b. Temp hash re-verify
    $TempHash = (Get-FileHash -LiteralPath $TempExe -Algorithm SHA256).Hash
    if ($TempHash -ne $ExpectedSha) {
        Remove-Item -LiteralPath $TempExe -Force -ErrorAction SilentlyContinue
        throw "ABORT: Temp binary hash mismatch after copy. Expected=$ExpectedSha Got=$TempHash"
    }

    # 4c. Mevcut exe backup'a Move (R2-MF-02: full-path $BackupExe, expansion safe)
    Move-Item -LiteralPath $InstalledExe -Destination $BackupExe -ErrorAction Stop

    # 4d. Temp → final path (aynı directory atomic)
    Move-Item -LiteralPath $TempExe -Destination $InstalledExe -ErrorAction Stop

    Unblock-File -LiteralPath $InstalledExe -ErrorAction SilentlyContinue

    # 4e. Installed hash re-verify
    $InstalledHash = (Get-FileHash -LiteralPath $InstalledExe -Algorithm SHA256).Hash
    if ($InstalledHash -ne $ExpectedSha) {
        # Rollback inline (R2-MF-02: full-path Move with $BackupExe)
        Move-Item -LiteralPath $InstalledExe -Destination $BadExe -Force -ErrorAction Stop
        Move-Item -LiteralPath $BackupExe -Destination $InstalledExe -Force -ErrorAction Stop
        throw "ABORT: Installed hash mismatch after move. Restored old binary. Bkz $SnapDir."
    }

    Write-Host "Replace OK. New hash: $InstalledHash"
}
catch {
    # Rollback fail-safe (R2-MF-01: explicit -ErrorAction SilentlyContinue OK after primary throw)
    if (Test-Path $TempExe) { Remove-Item -LiteralPath $TempExe -Force -ErrorAction SilentlyContinue }
    if (-not (Test-Path $InstalledExe) -and (Test-Path $BackupExe)) {
        Move-Item -LiteralPath $BackupExe -Destination $InstalledExe -Force -ErrorAction SilentlyContinue
    }
    # Servisi yeniden başlat (eski binary)
    Start-Service EndpointAgent -ErrorAction SilentlyContinue
    if (Test-Path $LockFile) { Remove-Item $LockFile -Force -ErrorAction SilentlyContinue }
    throw
}
```

### 5. Token & service start

> **Failure routing (R3-NH-01)**: Adım 5 sonrasında herhangi bir throw =
> mutation sonrası fail. Lock dosyasını **elle silme**; önce **Rollback
> section** uygula, rollback verify (eski hash + Service Running) sonrası
> lock release. Orphan-lock triage ile gerçek in-flight/failed-upgrade
> ayrılmalı.

**Service env regkey canonical (R3-MF-01)**: agent canonical olarak
`HKLM:\SYSTEM\CurrentControlSet\Services\EndpointAgent\Environment`
REG_MULTI_SZ kullanır (`platform-agent/installers/windows/install.ps1`
satır 247 `Set-ServiceEnvironmentRegkey`, satır 278
`Remove-ServiceEnvironmentEntry`, satır 556 "Set-ServiceEnvironmentRegkey
write is the SOLE source of"). Machine env yalnız defensive cleanup
amaçlı; source-of-truth değildir.

```powershell
# Helper: service env regkey upsert (REG_MULTI_SZ, mevcut entries preserve, key upsert)
function Set-ServiceEnvironmentEntry {
    param([string]$Name, [string]$Key, [string]$Value)
    $servicePath = "HKLM:\SYSTEM\CurrentControlSet\Services\$Name"
    $escapedKey = [regex]::Escape($Key)  # FINAL-NH-02 hardening
    $existing = (Get-ItemProperty -Path $servicePath -Name 'Environment' -ErrorAction SilentlyContinue).Environment
    if ($null -eq $existing) { $existing = @() }
    $filtered = @($existing | Where-Object { $_ -notmatch "^$escapedKey=" })
    $filtered += "$Key=$Value"
    Set-ItemProperty -Path $servicePath -Name 'Environment' -Value ([string[]]$filtered) -Type MultiString -ErrorAction Stop
}

# Helper: service env regkey single-key remove
function Remove-ServiceEnvironmentEntry {
    param([string]$Name, [string]$Key)
    $servicePath = "HKLM:\SYSTEM\CurrentControlSet\Services\$Name"
    $escapedKey = [regex]::Escape($Key)  # FINAL-NH-02 hardening
    $existing = (Get-ItemProperty -Path $servicePath -Name 'Environment' -ErrorAction SilentlyContinue).Environment
    if ($null -eq $existing) { return }
    $filtered = @($existing | Where-Object { $_ -notmatch "^$escapedKey=" })
    if ($filtered.Count -eq 0) {
        Remove-ItemProperty -Path $servicePath -Name 'Environment' -ErrorAction SilentlyContinue
    } else {
        Set-ItemProperty -Path $servicePath -Name 'Environment' -Value ([string[]]$filtered) -Type MultiString -ErrorAction Stop
    }
}

# Fresh enrollment token'ı service env regkey'e yaz (canonical source)
Set-ServiceEnvironmentEntry -Name 'EndpointAgent' -Key 'ENDPOINT_AGENT_ENROLLMENT_TOKEN' -Value $EnrollmentToken

# Defensive: Machine env'de stale token varsa temizle (Adım 7'de tekrar verify)
$residualMachine = [Environment]::GetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', 'Machine')
if ($residualMachine) {
    Write-Warning "Machine env'de stale token bulundu (length=$($residualMachine.Length)); siliniyor — service regkey artık source-of-truth."
    [Environment]::SetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', $null, 'Machine')
}

# Service env regkey'de fresh token doğrulandı mı?
$svcEnv = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EndpointAgent' -Name 'Environment' -ErrorAction Stop).Environment
if (-not ($svcEnv | Where-Object { $_ -match '^ENDPOINT_AGENT_ENROLLMENT_TOKEN=.+$' })) {
    throw "ABORT: Service env regkey'de ENDPOINT_AGENT_ENROLLMENT_TOKEN yok. Set-ServiceEnvironmentEntry fail oldu."
}

# Servisi başlat
Start-Service EndpointAgent -ErrorAction Stop
Start-Sleep -Seconds 5

$post = Get-Service EndpointAgent -ErrorAction Stop
if ($post.Status -ne 'Running') {
    throw "ABORT: Post-replace service not Running. Status=$($post.Status). Snapshot=$SnapDir."
}
```

### 6. Live verify (exact predicates — NH-01)

```powershell
# 6a. Service + PID verify
$newSvc = Get-CimInstance Win32_Service -Filter "Name='EndpointAgent'" -ErrorAction Stop
$newPid = $newSvc.ProcessId
Write-Host "OldPid=$OldPid NewPid=$newPid"
if ($newPid -eq $OldPid) {
    Write-Warning "PID değişmedi — service process tazelendi mi şüpheli."
}

# 6b. Installed binary hash + version
$liveHash = (Get-FileHash -LiteralPath $InstalledExe -Algorithm SHA256).Hash
$liveVer  = (Get-Item -LiteralPath $InstalledExe).VersionInfo.FileVersion
Write-Host "InstalledHash=$liveHash (expected $ExpectedSha)"

# 6c. Diagnose winget-egress (wire shape) — exact JSON predicate
$diagJson = & $InstalledExe diagnose winget-egress | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "FAIL: diagnose exit=$LASTEXITCODE. Output: $diagJson"
}
$diag = $diagJson | ConvertFrom-Json
if (-not $diag.supported)         { throw "FAIL: diagnose supported=false" }
if ($diag.schemaVersion -ne 1)    { throw "FAIL: schemaVersion != 1" }
if (-not $diag.egress.dns -or $diag.egress.dns.Count -lt 1)     { throw "FAIL: dns null/empty (eski binary AG-026A bug)" }
if (-not $diag.egress.tcp -or $diag.egress.tcp.Count -lt 1)     { throw "FAIL: tcp null/empty" }
if (-not $diag.egress.https -or $diag.egress.https.Count -lt 1) { throw "FAIL: https null/empty" }
Write-Host "Wire shape OK: dns=$($diag.egress.dns.Count) tcp=$($diag.egress.tcp.Count) https=$($diag.egress.https.Count)"
```

### 7. Token cleanup (MF-01 zorunlu)

**Acceptance gate ayrımı (R3-MF-03)**:

> Token cleanup'tan ÖNCE: **DPAPI persistence proof = HARD GATE**
> (canonical DPAPI credential file exists + nonzero).
>
> Token-less restart cleanup'tan SONRA: **future-start acceptance gate**
> (cleanup'ın gelecekteki start'ları kırmadığını ispatlar — `agent_id`
> subject ile auth devam).
>
> UI `CONSUMED` + backend `agent:<deviceUuid>` audit subject: destekleyici
> evidence; tek başına HARD GATE değil.

```powershell
# 7a. HARD GATE: DPAPI credential file (canonical path — R3-MF-02)
# Source: platform-agent/internal/hmacstore/hmacstore.go:142-151 +
#         platform-agent/installers/windows/uninstall.ps1:182-189
$CredFile = Join-Path $env:ProgramData 'EndpointAgent\config\hmac-credential.dpapi'
if (-not (Test-Path -LiteralPath $CredFile)) {
    throw "FAIL: HMAC credential dosyası yok: $CredFile. Agent henüz enroll-confirm yapmadı; token clear YAPMA."
}
$credSize = (Get-Item -LiteralPath $CredFile -ErrorAction Stop).Length
if ($credSize -le 0) {
    throw "FAIL: HMAC credential dosyası boş ($credSize bytes). Token clear YAPMA."
}
Write-Host "HMAC persistence OK: $CredFile ($credSize bytes)"

# 7b. Destekleyici evidence (operator manuel kontrol — non-gating):
#     - Web UI enrollments → açıklama satırı → Durum=CONSUMED + Cihaz dolu
#     - Backend audit subject (opsiyonel):
#       ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
#         logs deploy/endpoint-admin-service --since=2m 2>&1 | \
#         grep 'agent:<deviceUuid>' | head -5"

# 7c. Token clear — service env regkey (canonical source) + Machine env (defensive)
Remove-ServiceEnvironmentEntry -Name 'EndpointAgent' -Key 'ENDPOINT_AGENT_ENROLLMENT_TOKEN'
[Environment]::SetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', $null, 'Machine')

# 7d. Verify — service env regkey'de token kalmadı
$svcEnvPost = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\EndpointAgent' -Name 'Environment' -ErrorAction SilentlyContinue).Environment
if ($svcEnvPost -and ($svcEnvPost | Where-Object { $_ -match '^ENDPOINT_AGENT_ENROLLMENT_TOKEN=' })) {
    throw "FAIL: Service env regkey'de hâlâ token kaldı. Remove-ServiceEnvironmentEntry fail."
}

# 7e. Verify — Machine env'de token kalmadı (defensive)
$residualMachine = [Environment]::GetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', 'Machine')
if ($residualMachine) {
    throw "FAIL: Machine env'de hâlâ token var (length=$($residualMachine.Length))."
}

# 7f. PowerShell session'da da temizle
Remove-Item Env:ENDPOINT_AGENT_ENROLLMENT_TOKEN -ErrorAction SilentlyContinue
$EnrollmentToken = $null

# 7g. POST-CLEANUP acceptance gate — token-less restart future-start kanıt
Restart-Service EndpointAgent -ErrorAction Stop
Start-Sleep -Seconds 10
$post = Get-Service EndpointAgent -ErrorAction Stop
if ($post.Status -ne 'Running') {
    throw "FAIL: Token-less restart sonrası service NOT Running. Cleanup gelecekteki start'ları kırdı."
}
$postDiagJson = & $InstalledExe diagnose winget-egress | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "FAIL: Token-less restart sonrası diagnose exit=$LASTEXITCODE."
}
$postDiag = $postDiagJson | ConvertFrom-Json
if (-not $postDiag.supported) {
    throw "FAIL: Token-less restart sonrası supported=false."
}
Write-Host "Token-less restart OK: supported=true, schemaVersion=$($postDiag.schemaVersion)"
# Heartbeat backend'e 1-2 dakika içinde tekrar gelmeli (backend log + UI verify)
```

### 8. Lock release + history cleanup (NH-03)

```powershell
# Lock dosyasını sil
if (Test-Path $LockFile) { Remove-Item $LockFile -Force -ErrorAction SilentlyContinue }

# Snapshot dizini operator referansı için kalır.
Write-Host "Upgrade DONE. Snapshot: $SnapDir"

# PowerShell history temizle (oturum boyunca token-related ifadeler için)
Clear-History
```

---

## Backend verify (observer)

```bash
# 1-2 dakika bekle, agent heartbeat + COLLECT_INVENTORY çalıştırsın
DEVICE_ID="<from UI>"
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  logs deploy/endpoint-admin-service --since=2m 2>&1 | \
  grep -E 'Hardware inventory snapshot persisted device_id=$DEVICE_ID' | head -5"
```

**Expected predicates** (NH-01):
- En az 1 satır snapshot persisted log'u
- HTTP token/JWT/Bearer log'a düşmemeli (gitleaks-clean)
- UI: `https://testai.acik.com/endpoint-admin/devices` → cihaz seç → **Donanım** → "Toplama Zamanı" güncel (≤ 5 dakika)

---

## Rollback (mutation sonrası fail tetiklenirse)

```powershell
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Adım 0 snapshot dosyasından oku
$Snap = Get-Content -LiteralPath (Join-Path $SnapDir 'pre-upgrade.json') -ErrorAction Stop | ConvertFrom-Json

Stop-Service EndpointAgent -Force -ErrorAction Stop
Start-Sleep -Seconds 5

# Backup'tan restore (Copy-Item — backup dosyasını snapshot dizininde koruyalım)
Copy-Item -LiteralPath (Join-Path $SnapDir 'endpoint-agent.exe.bak') -Destination $InstalledExe -Force -ErrorAction Stop

# Hash verify (eski hash ile match)
$restoredHash = (Get-FileHash -LiteralPath $InstalledExe -Algorithm SHA256).Hash
if ($restoredHash -ne $Snap.oldHash) {
    throw "FAIL: Restored hash mismatch. Expected=$($Snap.oldHash) Got=$restoredHash"
}

# Token clear — service env regkey (canonical) + Machine env (defensive)
Remove-ServiceEnvironmentEntry -Name 'EndpointAgent' -Key 'ENDPOINT_AGENT_ENROLLMENT_TOKEN'
[Environment]::SetEnvironmentVariable('ENDPOINT_AGENT_ENROLLMENT_TOKEN', $null, 'Machine')

# ACL restore (eğer break-glass yapıldıysa)
# icacls 'C:\Program Files\EndpointAgent\endpoint-agent.exe' /reset
# icacls 'C:\Program Files\EndpointAgent\endpoint-agent.exe' /grant 'NT AUTHORITY\SYSTEM:F'
# Note: original ACL snapshot dosyasında ($SnapDir\old-acl.txt) — manuel set.

Start-Service EndpointAgent -ErrorAction Stop
# PID/service verify (Adım 6 ile aynı predicate'ler)
```

---

## Historical evidence (acceptance kriteri **DEĞİL** — MF-08)

2026-05-29 HALILKOOLUB735 Parallels W11 lab single-shot run kanıtları
(reproducible olmayan, historical):

| Field | Value |
|---|---|
| Date | 2026-05-29 |
| Device | HALILKOOLUB735 |
| Binary size | 7491072 → 7195456 bytes |
| Service PID | 5644 → 2832 |
| Diagnose wire shape | populated dns/tcp/https arrays |
| Enrollment status | token CONSUMED → device d0efb00a-... rebound |
| Backend ingest | BE-022 V14 hardware snapshot a4d68420 persisted |
| UI Donanım tab | "Toplama Zamanı" 10:22:09 |

**Acceptance kriteri** (bu run'da operator dolduracak):

| Field | Value |
|---|---|
| Date | `<YYYY-MM-DD HH:MM>` |
| Device | `<HOSTNAME>` |
| Old SHA256 | `<from $SnapDir\pre-upgrade.json>` |
| Expected SHA256 | `<from SHA256SUMS>` |
| New installed SHA256 | `<Adım 6 liveHash — Expected ile MATCH zorunlu>` |
| Service PID delta | `OldPid=<X> NewPid=<Y> (Y ≠ X assertion)` |
| Wire shape | `supported=true, schemaVersion=1, dns ≥ 1, tcp ≥ 1, https ≥ 1` |
| Token CONSUMED | `Web UI enrollments → CONSUMED + device bound` |
| Service env token clear + defensive Machine env clear | `HKLM:\SYSTEM\CurrentControlSet\Services\EndpointAgent\Environment içinde ENDPOINT_AGENT_ENROLLMENT_TOKEN yok (Adım 7d) + Machine residual=null (Adım 7e)` |
| Token-less restart | `service Running + diagnose dolu (Adım 7e)` |
| Backend snapshot | `device_id=<X> + log line + UI Toplama Zamanı ≤ 5min` |

---

## Bilinen sorunlar

### Enrollment token stale loop

Agent service restart sonrası in-memory HMAC credentials kayboluyor.
Eski token Machine env'inde kalırsa agent sonsuz redeem retry yapar
(409 "Enrollment token is not pending"). Bu yüzden upgrade akışında
**her zaman fresh token** + **Adım 7 cleanup** zorunlu.

Gelecek fix (out-of-scope this runbook): agent 2 başarısız enroll
sonrası persist marker yazsın, 3. denemede env token'ı clear etsin.

### Tamper protection ACL — refine edilmiş claim (MF-07)

`install.ps1` `Protect-AgentDirectories` install path'i SYSTEM-only
DACL ile koruyor. Bu, **service stop = file replace right** garanti
ETMEZ. Adım PF-4'te `icacls` çıktısı kontrol edilir; eğer
`BUILTIN\Administrators` write yetkisi yoksa break-glass takeown +
icacls grant gerekir (lab-only). Production runbook (Faz 22.2)
maintenance-token veya LocalSystem context kullanır; takeown YASAK.

### UAC dialog

Elevated PowerShell başlatmak için UAC dialog "Evet" tıklanması gerek.
Otomasyon mümkün değil (security boundary). Operator açık RDP / yerel
oturumda manuel tıklar.

### Single-operator constraint (MF-06)

Aynı cihazda iki operator paralel çalıştırırsa race + corruption riski
var. `$LockFile` (PF-3) bu race'i engeller; lock dosyası varsa abort.
Multi-operator pattern Faz 22.2 production runbook scope'unda.

---

## Cross-AI peer review chain

- **Codex iter-0**: `019e72a1` (referans) — runbook taslak çıkarımı
- **Codex iter-1**: `019e83ef-bc8e-71c3-ac6d-fb92e5d4235f` REVISE 9 must-fix
  + 3 nice-to-have (2026-06-01) — **absorb edildi** (MF-01..MF-09 +
  NH-01..NH-03)
- **Codex iter-4 (FINAL)**: aynı thread **AGREE** verdict + 2 non-blocking
  polish (FINAL-NH-01 acceptance table label + FINAL-NH-02 helper regex
  hardening) — **absorb edildi** in iter-4 commit
- **Codex iter-3**: aynı thread REVISE 3 must-fix + 1 nice-to-have —
  **absorb edildi** (R3-MF-01..R3-MF-03 + R3-NH-01):
  - R3-MF-01 Token transport service env regkey (HKLM\...\Services\EndpointAgent\Environment
    REG_MULTI_SZ canonical; `Set-ServiceEnvironmentEntry` / `Remove-ServiceEnvironmentEntry`
    helpers; Machine env defensive cleanup only). Source: install.ps1:247/278/556.
  - R3-MF-02 DPAPI credential canonical path:
    `%ProgramData%\EndpointAgent\config\hmac-credential.dpapi`
    (Source: internal/hmacstore/hmacstore.go:142-151 + uninstall.ps1:182-189)
  - R3-MF-03 HMAC predicate wording: DPAPI = HARD GATE pre-clear;
    token-less restart = POST-cleanup acceptance gate; UI CONSUMED +
    backend audit = supporting evidence (gate değil)
  - R3-NH-01 Failure routing: Adım 5 öncesi açık not — Step 5+ throw =
    mutation sonrası fail; Rollback section önce, lock release sonra
- **Codex iter-2**: aynı thread REVISE 4 must-fix + 3 nice-to-have —
  **absorb edildi** (R2-MF-01..R2-MF-04 + R2-NH-01..R2-NH-03):
  - R2-MF-01 PowerShell error semantics: `$ErrorActionPreference='Stop'`
    + `Set-StrictMode -Version Latest` + explicit `-ErrorAction Stop`
  - R2-MF-02 Backup rename variable expansion: `$BackupExe` full path +
    `Move-Item -Destination`
  - R2-MF-03 Lock acquisition atomic: `New-Item -Path $LockFile -ItemType File`
    + IOException catch (check-then-write race kaldırıldı)
  - R2-MF-04 ACL preflight write probe: install dir'de unique temp file
    create/delete (service stop ÖNCESİ fail edersek down-time yok)
  - R2-NH-01 signtool 22.1 lab WARN-only (SHA256 hard gate)
  - R2-NH-02 Lab allowlist scope metadata table (owner/class/PartOfDomain/auth-date)
  - R2-NH-03 HMAC persistence acceptance predicate (DPAPI file OR backend
    audit subject OR token-less restart heartbeat)
- **Faz 22.2 production runbook** ayrı PR'da: Azure Trusted Signing +
  remote PowerShell session + maintenance-token replacement + multi-
  operator coordination + signed manifest

---

## Ref

- platform-agent PR [#25](https://github.com/Halildeu/platform-agent/pull/25)
  — AG-026A defensive wire shape (commit `1e915a2d`)
- HALILKOOLUB735 LIVE evidence: `docs/state/current-state.md`
  "Live Delta — Faz 22.5.2 Hardware ingest end-to-end LIVE (2026-05-29)"
- install.ps1: `platform-agent/installers/windows/install.ps1`
- ADR-0012-EA: Endpoint Admin Governance Charter
- Codex 019e83ef adversarial review verdict: REVISE → 9 must-fix absorb
