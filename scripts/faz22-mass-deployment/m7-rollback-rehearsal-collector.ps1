<#
.SYNOPSIS
  Faz 22.5 M7 same-day rollback rehearsal evidence collector.

.DESCRIPTION
  PS5.1-compatible read-only collector for the owner-approved 2-device
  rollback rehearsal lane. It creates a structured JSON evidence bundle for
  three phases:

    baseline             Before rollback: service/cert/backend/GPO state.
    rollback-clean       After uninstall/rollback: service and binary absent,
                         service Environment cleared, logs preserved.
    reinstall-continuity After reinstall: service running again and backend
                         reachable.

  This script does not install, uninstall, decommission, reactivate, mutate GPO,
  read secrets, or submit data to the backend. It is evidence capture only.

  Full M7 closure still requires the destructive runbook acceptance in
  RB-faz22.5-m7-rollback-drill.md. A 2-device rehearsal can reduce risk but
  cannot close the 50-PC/800-PC rollout gates.

.EXAMPLES
  .\m7-rollback-rehearsal-collector.ps1 -Phase baseline -DeviceRole domain-gpo -RequireMachineCert -Json
  .\m7-rollback-rehearsal-collector.ps1 -Phase rollback-clean -DeviceRole domain-gpo -Json
  .\m7-rollback-rehearsal-collector.ps1 -Phase reinstall-continuity -DeviceRole audit -RequireMachineCert -Json
#>
[CmdletBinding()]
param(
    [ValidateSet('baseline', 'rollback-clean', 'reinstall-continuity')]
    [string]$Phase = 'baseline',

    [ValidateSet('domain-gpo', 'audit', 'local-control')]
    [string]$DeviceRole = 'domain-gpo',

    [string]$ApiHost = 'mtls.testai.acik.com',
    [int]$ApiPort = 443,
    [int]$TcpTimeoutMs = 4000,

    [string]$ServiceName = 'EndpointAgent',
    [string]$InstallDir = (Join-Path $env:ProgramFiles 'EndpointAgent'),
    [string]$LogDir = (Join-Path $env:ProgramData 'EndpointAgent\logs'),
    [string]$OutputRoot = (Join-Path $env:ProgramData 'EndpointAgent\evidence\m7-rollback-rehearsal'),

    [switch]$RequireMachineCert,
    [switch]$RequireSignature,
    [string]$ExpectedSignerThumbprint = '',
    [int]$LogTail = 160,
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
$checks = New-Object System.Collections.ArrayList

function Add-Check {
    param(
        [string]$Name,
        [ValidateSet('PASS', 'FAIL', 'WARN', 'INFO')][string]$Status,
        [string]$Detail
    )
    $null = $checks.Add([pscustomobject]@{
        name = $Name
        status = $Status
        detail = $Detail
    })
}

function Test-TcpReachable {
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

function Get-EndpointExePath {
    Join-Path $InstallDir 'endpoint-agent.exe'
}

function Get-MachineClientAuthCert {
    Get-ChildItem Cert:\LocalMachine\My -ErrorAction SilentlyContinue | Where-Object {
        $_.HasPrivateKey -and
        ($_.EnhancedKeyUsageList.ObjectId -contains '1.3.6.1.5.5.7.3.2') -and
        $_.NotAfter -gt (Get-Date)
    } | Sort-Object NotAfter -Descending | Select-Object -First 1
}

function Protect-LogLine {
    param([string]$Line)
    if ($null -eq $Line) { return $Line }
    $x = $Line
    $x = $x -replace '(?i)(authorization:\s*bearer\s+)[A-Za-z0-9\._\-]+', '$1<redacted>'
    $x = $x -replace '(?i)(token|secret|password|credential|jwt|bearer)(=|:)\S+', '$1$2<redacted>'
    return $x
}

function Get-SafeLogTail {
    if (-not (Test-Path $LogDir)) { return @() }
    $files = Get-ChildItem $LogDir -Filter '*.log' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 3
    $lines = @()
    foreach ($file in $files) {
        $lines += Get-Content $file.FullName -Tail $LogTail -ErrorAction SilentlyContinue |
            ForEach-Object { Protect-LogLine $_ }
    }
    return $lines
}

function Get-ComputerGpResult {
    try {
        $out = & gpresult.exe /r /scope computer 2>&1
        return ($out | ForEach-Object { "$_" })
    } catch {
        return @("gpresult failed: $($_.Exception.Message)")
    }
}

function Get-RecentEndpointEvents {
    $since = (Get-Date).AddHours(-12)
    try {
        Get-WinEvent -FilterHashtable @{ LogName = 'Application'; StartTime = $since } -ErrorAction Stop |
            Where-Object {
                $_.ProviderName -like '*MsiInstaller*' -or
                $_.Message -like '*EndpointAgent*' -or
                $_.Message -like '*endpoint-agent*'
            } |
            Select-Object -First 60 TimeCreated, ProviderName, Id, LevelDisplayName, Message
    } catch {
        @([pscustomobject]@{ error = $_.Exception.Message })
    }
}

function Get-ServiceEnvState {
    $serviceKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"
    $prop = Get-ItemProperty -Path $serviceKey -Name Environment -ErrorAction SilentlyContinue
    if ($null -eq $prop) {
        return [pscustomobject]@{ present = $false; entryCount = 0; redactedKeys = @() }
    }

    $keys = @()
    foreach ($entry in @($prop.Environment)) {
        $parts = $entry -split '=', 2
        if ($parts.Count -gt 0) { $keys += $parts[0] }
    }
    return [pscustomobject]@{
        present = $true
        entryCount = @($prop.Environment).Count
        redactedKeys = @($keys | Sort-Object)
    }
}

function Get-EndpointSignatureState {
    $exe = Get-EndpointExePath
    if (-not (Test-Path $exe)) { return $null }
    try {
        $sig = Get-AuthenticodeSignature -FilePath $exe
        return [pscustomobject]@{
            status = "$($sig.Status)"
            statusMessage = "$($sig.StatusMessage)"
            signerThumbprint = if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { $null }
            signerSubject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { $null }
        }
    } catch {
        return [pscustomobject]@{
            status = 'Error'
            statusMessage = $_.Exception.Message
            signerThumbprint = $null
            signerSubject = $null
        }
    }
}

function Invoke-PhaseChecks {
    $exe = Get-EndpointExePath
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $cert = Get-MachineClientAuthCert
    $tcp = Test-TcpReachable -TargetHost $ApiHost -Port $ApiPort -TimeoutMs $TcpTimeoutMs
    $serviceEnv = Get-ServiceEnvState
    $signature = Get-EndpointSignatureState

    if ($Phase -ne 'rollback-clean') {
        if ($tcp.ok) { Add-Check 'backend-tcp' 'PASS' $tcp.detail }
        else { Add-Check 'backend-tcp' 'FAIL' $tcp.detail }
    } else {
        Add-Check 'backend-tcp' 'INFO' 'skipped for rollback-clean phase'
    }

    if ($cert) {
        Add-Check 'machine-cert' 'PASS' "Client-Auth cert thumbprint=$($cert.Thumbprint) notAfter=$($cert.NotAfter.ToString('yyyy-MM-dd'))"
    } elseif ($RequireMachineCert -or $DeviceRole -ne 'local-control') {
        Add-Check 'machine-cert' 'FAIL' "no Client-Auth machine cert for role=$DeviceRole"
    } else {
        Add-Check 'machine-cert' 'INFO' 'no Client-Auth machine cert (allowed for local-control)'
    }

    switch ($Phase) {
        'baseline' {
            if ($svc -and $svc.Status -eq 'Running') { Add-Check 'service-running' 'PASS' 'EndpointAgent service Running' }
            elseif ($svc) { Add-Check 'service-running' 'FAIL' "EndpointAgent service not running: $($svc.Status)" }
            else { Add-Check 'service-running' 'FAIL' 'EndpointAgent service missing' }

            if (Test-Path $exe) { Add-Check 'agent-binary' 'PASS' "binary present: $exe" }
            else { Add-Check 'agent-binary' 'FAIL' "binary missing: $exe" }
        }
        'rollback-clean' {
            if ($svc) { Add-Check 'service-removed' 'FAIL' "service still present: $($svc.Status)" }
            else { Add-Check 'service-removed' 'PASS' 'service absent' }

            if (Test-Path $exe) { Add-Check 'agent-binary-removed' 'FAIL' "binary still present: $exe" }
            else { Add-Check 'agent-binary-removed' 'PASS' 'binary absent' }

            if ($serviceEnv.present) { Add-Check 'service-env-cleared' 'FAIL' 'service Environment regkey still present' }
            else { Add-Check 'service-env-cleared' 'PASS' 'service Environment regkey absent' }

            $tasks = Get-ScheduledTask -TaskName 'EndpointAgent*' -ErrorAction SilentlyContinue
            if ($null -eq $tasks) { Add-Check 'scheduled-task' 'PASS' 'no EndpointAgent scheduled task' }
            else { Add-Check 'scheduled-task' 'FAIL' "orphan scheduled task: $($tasks.TaskName -join ',')" }

            if (Test-Path $LogDir) { Add-Check 'log-retention' 'PASS' 'log dir preserved' }
            else { Add-Check 'log-retention' 'WARN' 'log dir absent after rollback' }
        }
        'reinstall-continuity' {
            if ($svc -and $svc.Status -eq 'Running') { Add-Check 'service-running' 'PASS' 'EndpointAgent service Running after reinstall' }
            elseif ($svc) { Add-Check 'service-running' 'FAIL' "EndpointAgent service not running after reinstall: $($svc.Status)" }
            else { Add-Check 'service-running' 'FAIL' 'EndpointAgent service missing after reinstall' }

            if (Test-Path $exe) { Add-Check 'agent-binary' 'PASS' "binary present after reinstall: $exe" }
            else { Add-Check 'agent-binary' 'FAIL' "binary missing after reinstall: $exe" }
        }
    }

    if ($Phase -ne 'rollback-clean') {
        if ($signature) {
            $pinOk = [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint) -or
                ($signature.signerThumbprint -eq $ExpectedSignerThumbprint)
            if ($signature.status -eq 'Valid' -and $pinOk) {
                Add-Check 'exe-signature' 'PASS' "signature valid signer=$($signature.signerThumbprint)"
            } elseif ($RequireSignature) {
                Add-Check 'exe-signature' 'FAIL' "signature status=$($signature.status) signer=$($signature.signerThumbprint) pinOk=$pinOk"
            } else {
                Add-Check 'exe-signature' 'WARN' "signature status=$($signature.status) signer=$($signature.signerThumbprint) pinOk=$pinOk"
            }
        } elseif ($RequireSignature) {
            Add-Check 'exe-signature' 'FAIL' 'signature required but binary missing'
        }
    }

    return [pscustomobject]@{
        servicePresent = [bool]$svc
        serviceStatus = if ($svc) { "$($svc.Status)" } else { $null }
        serviceStartType = if ($svc) { "$($svc.StartType)" } else { $null }
        binaryPath = $exe
        binaryPresent = Test-Path $exe
        logDir = $LogDir
        serviceEnvironment = $serviceEnv
        machineCertSubject = if ($cert) { $cert.Subject } else { $null }
        machineCertIssuer = if ($cert) { $cert.Issuer } else { $null }
        machineCertThumbprint = if ($cert) { $cert.Thumbprint } else { $null }
        machineCertNotAfter = if ($cert) { $cert.NotAfter.ToString('o') } else { $null }
        exeSignature = $signature
    }
}

New-Item -ItemType Directory -Force $OutputRoot | Out-Null

$cs = Get-CimInstance Win32_ComputerSystem
$phaseState = Invoke-PhaseChecks

[int]$failCount = @($checks | Where-Object { $_.status -eq 'FAIL' }).Count
[int]$warnCount = @($checks | Where-Object { $_.status -eq 'WARN' }).Count
$overall = if ($failCount -gt 0) { 'FAIL' } elseif ($warnCount -gt 0) { 'PASS-WITH-WARN' } else { 'PASS' }

$result = [pscustomobject]@{
    schema = 'faz22.m7.rollback-rehearsal.collector.v1'
    collectedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    phase = $Phase
    deviceRole = $DeviceRole
    overall = $overall
    failCount = $failCount
    warnCount = $warnCount
    facts = [pscustomobject]@{
        computerName = $env:COMPUTERNAME
        domain = $cs.Domain
        partOfDomain = [bool]$cs.PartOfDomain
        apiHost = $ApiHost
        apiPort = $ApiPort
        serviceName = $ServiceName
        installDir = $InstallDir
        outputRoot = $OutputRoot
    }
    phaseState = $phaseState
    checks = @($checks)
    gpresultComputer = @(Get-ComputerGpResult)
    recentEndpointEvents = @(Get-RecentEndpointEvents)
    recentEndpointAgentLogTail = @(Get-SafeLogTail)
}

$safeHost = ($env:COMPUTERNAME -replace '[^A-Za-z0-9_.-]', '_')
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmssZ')
$outFile = Join-Path $OutputRoot ("{0}-{1}-{2}.json" -f $stamp, $safeHost, $Phase)
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $outFile -Encoding UTF8

if ($Json) {
    $result | ConvertTo-Json -Depth 8
} else {
    Write-Host ("M7 rollback rehearsal collector [{0}/{1}] on {2} -> {3} (FAIL={4} WARN={5})" -f $DeviceRole, $Phase, $env:COMPUTERNAME, $overall, $failCount, $warnCount)
    Write-Host "Evidence: $outFile"
}

if ($failCount -gt 0) { exit 1 }
exit 0
