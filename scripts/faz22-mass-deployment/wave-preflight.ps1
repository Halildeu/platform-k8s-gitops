<#
.SYNOPSIS
  Faz 22.5 wave preflight / health / rollback-verify gate for the Windows
  endpoint agent. Read-only device health check used before a 2-PC pilot (M5)
  or a 50-PC wave (M6), and after a rollback drill (M7).

.DESCRIPTION
  Emits a structured per-check result (PASS/FAIL/WARN/INFO) plus an overall
  verdict. Read-only: inspects service state, the installed binary version
  (PE VersionInfo - the agent has NO `version` subcommand), the HKLM mode
  registry, the HMAC config store, the machine certificate (tokenless enroll),
  the Authenticode signature, backend TCP reachability and pending-reboot
  state. It does NOT enroll, install, uninstall, mutate state or read secrets.

  Modes:
    preinstall-readiness  BEFORE MSI push: a fresh device has NO service/exe yet,
                          so their absence is expected (not a FAIL). Checks
                          backend reachability + machine cert + pending reboot.
    enroll-health (default) AFTER install/enroll: service Running + exe version +
                          HKLM Mode + config/cert + Authenticode signature +
                          reachability.
    rollback-clean        AFTER uninstall: service/exe/scheduled-task/service-env
                          regkey ABSENT, logs PRESERVED. No backend reachability
                          requirement (a rolled-back/offline device may be off-net).

  Hard-require switches (turn WARN into FAIL where the wave demands it):
    -RequireMachineCert   a Client-Auth machine cert MUST be present (tokenless M2)
    -RequireSignature     the installed exe signature MUST be Valid (+ match
                          -ExpectedSignerThumbprint if given). Default: WARN only,
                          because a Trusted-Publisher root GPO may still be pending.
    -ExpectedMinimumAgentVersion
                          the installed endpoint-agent.exe metadata MUST be at
                          least this version in enroll-health mode. Use the
                          current release-manifest floor to prevent downgrade
                          acceptance when signed MSI lags ZIP/EXE current.

.NOTES
  PS5.1-compatible, ASCII-only code. Companion cert tools:
  verify-machine-cert.ps1 / ad-cs-preflight.ps1 / enroll-endpoint-agent-cert.ps1.
  Runbooks: RB-faz22-gpo-pilot-5pc.md (M5), RB-faz22.5-m6-capacity-baseline.md (M6),
  RB-faz22.5-m7-rollback-drill.md (M7).
  IMPORTANT: uninstall.ps1 does NOT remove HKLM\SOFTWARE\EndpointAgent by default
  (reinstall overwrites it; only -RemoveConfig purges Machine env + HMAC blob). So
  rollback-clean treats that key as INFO (stale-mode advisory), not a hard FAIL.
#>
[CmdletBinding()]
param(
    [ValidateSet('preinstall-readiness', 'enroll-health', 'rollback-clean')]
    [string]$Mode = 'enroll-health',
    [switch]$Json,
    [switch]$ExitCodeOnFail,
    [switch]$RequireMachineCert,
    [switch]$RequireSignature,
    [string]$ServiceName = 'EndpointAgent',
    [string]$InstallDir = (Join-Path $env:ProgramFiles 'EndpointAgent'),
    [string]$LogDir = (Join-Path $env:ProgramData 'EndpointAgent\logs'),
    [string]$ConfigStorePath = (Join-Path $env:ProgramData 'EndpointAgent\config\hmac-credential.dpapi'),
    [string]$ApiHost = 'testai.acik.com',
    [int]$ApiPort = 443,
    [int]$ReachabilityTimeoutMs = 4000,
    [string]$ExpectedMinimumAgentVersion = '',
    # Optional: assert the installed exe is signed by this leaf thumbprint
    # (AG-018 internal-CA). Empty = report signer; with -RequireSignature any
    # Valid trusted signer passes unless a thumbprint is given to pin it.
    [string]$ExpectedSignerThumbprint = ''
)

$ErrorActionPreference = 'Stop'
$checks = New-Object System.Collections.ArrayList

function Add-Check {
    param(
        [string]$Name,
        [ValidateSet('PASS', 'FAIL', 'WARN', 'INFO')][string]$Status,
        [string]$Detail
    )
    $null = $checks.Add([pscustomobject]@{ check = $Name; status = $Status; detail = $Detail })
}

function Get-AgentExePath { Join-Path $InstallDir 'endpoint-agent.exe' }

function ConvertTo-AgentVersion {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    $m = [regex]::Match($Value, '(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?')
    if (-not $m.Success) { return $null }
    $build = '0'
    if ($m.Groups[4].Success) { $build = $m.Groups[4].Value }
    try {
        return [version]::Parse(('{0}.{1}.{2}.{3}' -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value, $build))
    } catch {
        return $null
    }
}

function Get-ObjectPropertyValue {
    param(
        $InputObject,
        [string]$Name
    )
    if ($null -eq $InputObject) { return $null }
    $prop = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Get-InstalledEndpointAgentProducts {
    $rows = @()
    $roots = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($root in $roots) {
        $items = Get-ItemProperty $root -ErrorAction SilentlyContinue | Where-Object {
            $displayName = Get-ObjectPropertyValue $_ 'DisplayName'
            $installLocation = Get-ObjectPropertyValue $_ 'InstallLocation'
            $displayName -like '*Endpoint Agent*' -or
            $displayName -like '*EndpointAgent*' -or
            $installLocation -like '*EndpointAgent*'
        }
        foreach ($item in $items) {
            $rows += [pscustomobject]@{
                displayName = Get-ObjectPropertyValue $item 'DisplayName'
                displayVersion = Get-ObjectPropertyValue $item 'DisplayVersion'
                publisher = Get-ObjectPropertyValue $item 'Publisher'
                installLocation = Get-ObjectPropertyValue $item 'InstallLocation'
                psPath = $item.PSPath
            }
        }
    }
    return $rows
}

function Get-AgentVersionCandidate {
    param([string]$ExePath)
    if (-not (Test-Path $ExePath)) { return $null }
    $vi = (Get-Item $ExePath).VersionInfo
    $candidates = @(
        [pscustomobject]@{ source = 'ProductVersion'; value = $vi.ProductVersion; parsed = ConvertTo-AgentVersion $vi.ProductVersion },
        [pscustomobject]@{ source = 'FileVersion'; value = $vi.FileVersion; parsed = ConvertTo-AgentVersion $vi.FileVersion }
    )
    foreach ($product in (Get-InstalledEndpointAgentProducts)) {
        $candidates += [pscustomobject]@{
            source = 'installedProduct.displayVersion'
            value = $product.displayVersion
            parsed = ConvertTo-AgentVersion $product.displayVersion
        }
    }
    $parsed = @($candidates | Where-Object { $null -ne $_.parsed } | Sort-Object parsed -Descending)
    if ($parsed.Count -gt 0) { return $parsed[0] }
    return [pscustomobject]@{ source = 'unparsed'; value = (($candidates | ForEach-Object { "$($_.source)=$($_.value)" }) -join '; '); parsed = $null }
}

# --- Probes (read-only) ----------------------------------------------------

function Test-BackendReachable {
    param([string]$TargetHost, [int]$Port, [int]$TimeoutMs)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return @{ ok = $false; detail = "timeout after ${TimeoutMs}ms" }
        }
        $client.EndConnect($iar)
        return @{ ok = $true; detail = "TCP ${TargetHost}:${Port} reachable" }
    } catch {
        return @{ ok = $false; detail = $_.Exception.Message }
    } finally {
        $client.Close()
    }
}

function Test-PendingReboot {
    $keys = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
    )
    foreach ($k in $keys) { if (Test-Path $k) { return $true } }
    $pfro = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' `
        -Name PendingFileRenameOperations -ErrorAction SilentlyContinue
    return [bool]$pfro.PendingFileRenameOperations
}

function Get-MachineClientAuthCert {
    # Client Authentication EKU = 1.3.6.1.5.5.7.3.2 (tokenless mTLS enroll)
    Get-ChildItem Cert:\LocalMachine\My -ErrorAction SilentlyContinue | Where-Object {
        $_.HasPrivateKey -and ($_.EnhancedKeyUsageList.ObjectId -contains '1.3.6.1.5.5.7.3.2') `
            -and $_.NotAfter -gt (Get-Date)
    } | Sort-Object NotAfter -Descending | Select-Object -First 1
}

# --- Individual checks -----------------------------------------------------

function Invoke-ServiceCheck {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    switch ($Mode) {
        'rollback-clean' {
            if ($null -eq $svc) { Add-Check 'service-state' 'PASS' 'service absent (rollback clean)' }
            else { Add-Check 'service-state' 'FAIL' "orphan service present: $($svc.Status)" }
        }
        'preinstall-readiness' {
            if ($null -eq $svc) { Add-Check 'service-state' 'INFO' 'service not installed yet (expected pre-install)' }
            else { Add-Check 'service-state' 'INFO' "service already present: $($svc.Status)" }
        }
        default {
            if ($null -eq $svc) { Add-Check 'service-state' 'FAIL' 'service not installed' }
            elseif ($svc.Status -eq 'Running') { Add-Check 'service-state' 'PASS' 'Running' }
            else { Add-Check 'service-state' 'FAIL' "not Running: $($svc.Status)" }
        }
    }
}

function Invoke-BinaryVersionCheck {
    $exe = Get-AgentExePath
    switch ($Mode) {
        'rollback-clean' {
            if (Test-Path $exe) { Add-Check 'agent-binary' 'FAIL' 'exe still present after uninstall' }
            else { Add-Check 'agent-binary' 'PASS' 'exe absent (rollback clean)' }
        }
        'preinstall-readiness' {
            if (Test-Path $exe) { Add-Check 'agent-binary' 'INFO' 'exe already present (pre-install run on installed device)' }
            else { Add-Check 'agent-binary' 'INFO' 'exe not installed yet (expected pre-install)' }
        }
        default {
            if (-not (Test-Path $exe)) { Add-Check 'agent-binary' 'FAIL' "exe missing: $exe"; return }
            # The agent has NO `version` subcommand (it hangs into default mode).
            $fv = (Get-Item $exe).VersionInfo.FileVersion
            Add-Check 'agent-version' 'INFO' "FileVersion=$fv"
            if (-not [string]::IsNullOrWhiteSpace($ExpectedMinimumAgentVersion)) {
                $expected = ConvertTo-AgentVersion $ExpectedMinimumAgentVersion
                $actual = Get-AgentVersionCandidate $exe
                if ($null -eq $expected) {
                    Add-Check 'agent-version-floor' 'FAIL' "cannot parse ExpectedMinimumAgentVersion=$ExpectedMinimumAgentVersion"
                } elseif ($null -eq $actual -or $null -eq $actual.parsed) {
                    $detail = if ($null -eq $actual) { 'no version metadata found' } else { "cannot parse installed version metadata: $($actual.value)" }
                    Add-Check 'agent-version-floor' 'FAIL' $detail
                } elseif ($actual.parsed -lt $expected) {
                    Add-Check 'agent-version-floor' 'FAIL' "installed $($actual.value) from $($actual.source) is below required $ExpectedMinimumAgentVersion"
                } else {
                    Add-Check 'agent-version-floor' 'PASS' "installed $($actual.value) from $($actual.source) meets required $ExpectedMinimumAgentVersion"
                }
            }
        }
    }
}

function Invoke-ModeRegistryCheck {
    if ($Mode -eq 'preinstall-readiness') { return }
    $mode = Get-ItemProperty 'HKLM:\SOFTWARE\EndpointAgent' -ErrorAction SilentlyContinue
    if ($Mode -eq 'rollback-clean') {
        # uninstall.ps1 does NOT remove this key by default -> INFO, not FAIL.
        if ($null -eq $mode) { Add-Check 'hklm-mode' 'INFO' 'HKLM\SOFTWARE\EndpointAgent absent (-RemoveConfig path)' }
        else { Add-Check 'hklm-mode' 'INFO' "Mode=$($mode.Mode) (default uninstall keeps this; reinstall overwrites; verify not stale)" }
        return
    }
    if ($null -eq $mode) { Add-Check 'hklm-mode' 'WARN' 'HKLM\SOFTWARE\EndpointAgent absent (HMAC-only install?)' }
    else { Add-Check 'hklm-mode' 'INFO' "Mode=$($mode.Mode) ApiUrl=$($mode.ApiUrl)" }
}

function Invoke-ServiceEnvRegkeyCheck {
    if ($Mode -ne 'rollback-clean') { return }
    $path = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"
    $prop = Get-ItemProperty -Path $path -Name 'Environment' -ErrorAction SilentlyContinue
    if ($null -eq $prop) { Add-Check 'service-env-regkey' 'PASS' 'service Environment regkey cleared' }
    else { Add-Check 'service-env-regkey' 'FAIL' 'stale service Environment regkey present' }
}

function Invoke-ScheduledTaskCheck {
    if ($Mode -ne 'rollback-clean') { return }
    $tasks = Get-ScheduledTask -TaskName 'EndpointAgent*' -ErrorAction SilentlyContinue
    if ($null -eq $tasks) { Add-Check 'scheduled-task' 'PASS' 'no EndpointAgent scheduled task' }
    else { Add-Check 'scheduled-task' 'FAIL' "orphan scheduled task: $($tasks.TaskName -join ',')" }
}

function Invoke-ConfigStoreCheck {
    $present = Test-Path $ConfigStorePath
    if ($Mode -eq 'rollback-clean') {
        Add-Check 'config-store' 'INFO' ("hmac-credential.dpapi present=$present (preserved unless -RemoveConfig)")
        return
    }
    if ($Mode -eq 'preinstall-readiness') { return }
    if ($present) { Add-Check 'config-store' 'INFO' 'HMAC credential store present' }
    else { Add-Check 'config-store' 'INFO' 'no HMAC store (tokenless/mTLS path expected)' }
}

function Invoke-MachineCertCheck {
    if ($Mode -eq 'rollback-clean') { return }
    $cert = Get-MachineClientAuthCert
    if ($null -eq $cert) {
        if ($RequireMachineCert) {
            Add-Check 'machine-cert' 'FAIL' 'no Client-Auth machine cert but -RequireMachineCert set (tokenless mTLS needs M2 cert)'
        } else {
            Add-Check 'machine-cert' 'WARN' 'no Client-Auth machine cert (HMAC fallback only; tokenless mTLS needs M2 cert)'
        }
    } else {
        Add-Check 'machine-cert' 'INFO' ("Client-Auth cert thumbprint=$($cert.Thumbprint) notAfter=$($cert.NotAfter.ToString('yyyy-MM-dd'))")
    }
}

function Invoke-SignatureCheck {
    if ($Mode -ne 'enroll-health') { return }
    $exe = Get-AgentExePath
    if (-not (Test-Path $exe)) {
        if ($RequireSignature) { Add-Check 'exe-signature' 'FAIL' 'exe missing; cannot verify required signature' }
        return
    }
    $sig = Get-AuthenticodeSignature -FilePath $exe
    $thumb = if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { '<none>' }
    if ($sig.Status -ne 'Valid') {
        if ($RequireSignature) {
            Add-Check 'exe-signature' 'FAIL' "signature status=$($sig.Status) signer=$thumb but -RequireSignature set"
        } else {
            Add-Check 'exe-signature' 'WARN' "signature status=$($sig.Status) signer=$thumb (Trusted-Publisher root GPO may be pending)"
        }
        return
    }
    if ($ExpectedSignerThumbprint -and ($thumb -ne $ExpectedSignerThumbprint)) {
        if ($RequireSignature) {
            Add-Check 'exe-signature' 'FAIL' "signer thumbprint $thumb != expected $ExpectedSignerThumbprint"
        } else {
            Add-Check 'exe-signature' 'WARN' "signer thumbprint $thumb != expected $ExpectedSignerThumbprint"
        }
    } else {
        Add-Check 'exe-signature' 'PASS' "Valid; signer=$thumb"
    }
}

function Invoke-ReachabilityCheck {
    # A rolled-back / offline device need not reach the backend -> skip in rollback-clean.
    if ($Mode -eq 'rollback-clean') { return }
    $r = Test-BackendReachable -TargetHost $ApiHost -Port $ApiPort -TimeoutMs $ReachabilityTimeoutMs
    if ($r.ok) { Add-Check 'backend-reachability' 'PASS' $r.detail }
    else { Add-Check 'backend-reachability' 'FAIL' $r.detail }
}

function Invoke-RebootCheck {
    if (Test-PendingReboot) { Add-Check 'pending-reboot' 'WARN' 'pending reboot detected' }
    else { Add-Check 'pending-reboot' 'PASS' 'no pending reboot' }
}

function Invoke-LogRetentionCheck {
    if ($Mode -ne 'rollback-clean') { return }
    if (Test-Path $LogDir) { Add-Check 'log-retention' 'PASS' 'log dir preserved (evidence retention)' }
    else { Add-Check 'log-retention' 'WARN' 'log dir absent after rollback (retention gap)' }
}

# --- Run -------------------------------------------------------------------

Invoke-ServiceCheck
Invoke-BinaryVersionCheck
Invoke-ModeRegistryCheck
Invoke-ServiceEnvRegkeyCheck
Invoke-ScheduledTaskCheck
Invoke-ConfigStoreCheck
Invoke-MachineCertCheck
Invoke-SignatureCheck
Invoke-ReachabilityCheck
Invoke-RebootCheck
Invoke-LogRetentionCheck

# @(...) forces array context: in PS5.1 a single-match Where-Object returns a
# scalar whose .Count serializes as $null -> a LONE FAIL/WARN would read as
# count=null and `$null -gt 0` is false -> overall mislabeled PASS (gate-masking,
# a single real FAIL silently passes). Caught by the live Win11 VM smoke: the
# 1-WARN preinstall-readiness run reported warnCount=null + overall=PASS.
[int]$failCount = @($checks | Where-Object { $_.status -eq 'FAIL' }).Count
[int]$warnCount = @($checks | Where-Object { $_.status -eq 'WARN' }).Count
$overall = if ($failCount -gt 0) { 'FAIL' } elseif ($warnCount -gt 0) { 'PASS-WITH-WARN' } else { 'PASS' }

$result = [pscustomobject]@{
    mode      = $Mode
    timestamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    host      = $env:COMPUTERNAME
    overall   = $overall
    failCount = $failCount
    warnCount = $warnCount
    checks    = @($checks)
}

if ($Json) {
    $result | ConvertTo-Json -Depth 4
} else {
    Write-Host "wave-preflight [$Mode] on $($result.host) -> $overall (FAIL=$failCount WARN=$warnCount)"
    $checks | Format-Table check, status, detail -AutoSize | Out-String | Write-Host
}

if ($ExitCodeOnFail -and $failCount -gt 0) { exit 1 }
exit 0
