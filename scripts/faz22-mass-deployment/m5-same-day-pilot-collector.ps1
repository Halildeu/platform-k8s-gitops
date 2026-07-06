<#
.SYNOPSIS
  Faz 22.5 M5 same-day pilot evidence collector.

.DESCRIPTION
  Read-only collector for the owner-approved no-24h M5 pilot path. Run this on
  each selected Windows device before install, after GPO/MSI install, and after
  rollback/reinstall drills. It does not install, uninstall, enroll, mutate GPO,
  read secrets, or submit data to the backend.

  The script writes a JSON evidence file under:
    C:\ProgramData\EndpointAgent\evidence\m5-same-day

  Device roles:
    domain-gpo    Domain-joined GPO pilot device; machine cert is required.
    audit         Audit/denetim pilot device; machine cert is required when domain-joined.
    local-control Local Parallels/control device; machine cert is advisory only.

.EXAMPLES
  .\m5-same-day-pilot-collector.ps1 -Phase preinstall -Role domain-gpo -Json
  .\m5-same-day-pilot-collector.ps1 -Phase postinstall -Role audit -RequireSignature -ExpectedMinimumAgentVersion 0.2.10 -Json
  .\m5-same-day-pilot-collector.ps1 -Phase rollback-clean -Role domain-gpo -Json
#>
[CmdletBinding()]
param(
    [ValidateSet('preinstall', 'postinstall', 'rollback-clean')]
    [string]$Phase = 'postinstall',

    [ValidateSet('domain-gpo', 'audit', 'local-control')]
    [string]$Role = 'domain-gpo',

    [string]$ApiHost = 'mtls.testai.acik.com',
    [int]$ApiPort = 443,

    [string]$ServiceName = 'EndpointAgent',
    [string]$InstallDir = (Join-Path $env:ProgramFiles 'EndpointAgent'),
    [string]$LogDir = (Join-Path $env:ProgramData 'EndpointAgent\logs'),
    [string]$OutputRoot = (Join-Path $env:ProgramData 'EndpointAgent\evidence\m5-same-day'),

    [switch]$RequireSignature,
    [string]$ExpectedSignerThumbprint = '',
    [string]$ExpectedMinimumAgentVersion = '',
    [int]$TcpTimeoutMs = 4000,
    [int]$LogTail = 120,
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

function Get-MachineClientAuthCert {
    Get-ChildItem Cert:\LocalMachine\My -ErrorAction SilentlyContinue | Where-Object {
        $_.HasPrivateKey -and ($_.EnhancedKeyUsageList.ObjectId -contains '1.3.6.1.5.5.7.3.2') -and $_.NotAfter -gt (Get-Date)
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
    $files = Get-ChildItem $LogDir -Filter '*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3
    $lines = @()
    foreach ($file in $files) {
        $lines += Get-Content $file.FullName -Tail $LogTail -ErrorAction SilentlyContinue | ForEach-Object { Protect-LogLine $_ }
    }
    return $lines
}

function Get-RecentEventSummary {
    $since = (Get-Date).AddHours(-8)
    try {
        Get-WinEvent -FilterHashtable @{ LogName = 'Application'; StartTime = $since } -ErrorAction Stop |
            Where-Object {
                $_.ProviderName -like '*MsiInstaller*' -or
                $_.ProviderName -like '*Application Error*' -or
                $_.Message -like '*EndpointAgent*' -or
                $_.Message -like '*endpoint-agent*'
            } |
            Select-Object -First 40 TimeCreated, ProviderName, Id, LevelDisplayName, Message
    } catch {
        @([pscustomobject]@{ error = $_.Exception.Message })
    }
}

function Get-GpResultText {
    try {
        $out = & gpresult.exe /r /scope computer 2>&1
        return ($out | ForEach-Object { "$_" })
    } catch {
        return @("gpresult failed: $($_.Exception.Message)")
    }
}

function Get-EndpointAgentSignature {
    param([string]$ExePath)
    if (-not (Test-Path $ExePath)) { return $null }
    try { return Get-AuthenticodeSignature -FilePath $ExePath }
    catch { return [pscustomobject]@{ Status = 'Error'; StatusMessage = $_.Exception.Message; SignerCertificate = $null } }
}

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

function Get-EndpointAgentVersionCandidate {
    param([string]$ExePath)
    if (-not (Test-Path $ExePath)) { return $null }
    $vi = (Get-Item $ExePath).VersionInfo
    $candidates = @(
        [pscustomobject]@{ source = 'ProductVersion'; value = $vi.ProductVersion; parsed = ConvertTo-AgentVersion $vi.ProductVersion },
        [pscustomobject]@{ source = 'FileVersion'; value = $vi.FileVersion; parsed = ConvertTo-AgentVersion $vi.FileVersion }
    )
    $parsed = @($candidates | Where-Object { $null -ne $_.parsed } | Sort-Object parsed -Descending)
    if ($parsed.Count -gt 0) { return $parsed[0] }
    return [pscustomobject]@{ source = 'unparsed'; value = (($candidates | ForEach-Object { "$($_.source)=$($_.value)" }) -join '; '); parsed = $null }
}

function Invoke-CoreChecks {
    $cs = Get-CimInstance Win32_ComputerSystem
    $exe = Join-Path $InstallDir 'endpoint-agent.exe'
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $cert = Get-MachineClientAuthCert
    $tcp = Test-TcpReachable -TargetHost $ApiHost -Port $ApiPort -TimeoutMs $TcpTimeoutMs

    if ($tcp.ok) { Add-Check 'backend-tcp' 'PASS' $tcp.detail }
    else { Add-Check 'backend-tcp' 'FAIL' $tcp.detail }

    if ($Role -eq 'local-control') {
        if ($cert) { Add-Check 'machine-cert' 'INFO' "Client-Auth cert thumbprint=$($cert.Thumbprint)" }
        else { Add-Check 'machine-cert' 'INFO' 'no Client-Auth machine cert (allowed for local-control)' }
    } else {
        if ($cert) { Add-Check 'machine-cert' 'PASS' "Client-Auth cert thumbprint=$($cert.Thumbprint) notAfter=$($cert.NotAfter.ToString('yyyy-MM-dd'))" }
        else { Add-Check 'machine-cert' 'FAIL' "no Client-Auth machine cert for role=$Role" }
    }

    switch ($Phase) {
        'preinstall' {
            if ($svc) { Add-Check 'service-preinstall' 'INFO' "service already present: $($svc.Status)" }
            else { Add-Check 'service-preinstall' 'INFO' 'service absent before install' }
            if (Test-Path $exe) { Add-Check 'binary-preinstall' 'INFO' "binary already present: $exe" }
            else { Add-Check 'binary-preinstall' 'INFO' 'binary absent before install' }
        }
        'postinstall' {
            if ($svc -and $svc.Status -eq 'Running') { Add-Check 'service-running' 'PASS' 'EndpointAgent service Running' }
            elseif ($svc) { Add-Check 'service-running' 'FAIL' "EndpointAgent service not running: $($svc.Status)" }
            else { Add-Check 'service-running' 'FAIL' 'EndpointAgent service missing' }

            if (Test-Path $exe) { Add-Check 'agent-binary' 'PASS' "binary present: $exe" }
            else { Add-Check 'agent-binary' 'FAIL' "binary missing: $exe" }

            if (-not [string]::IsNullOrWhiteSpace($ExpectedMinimumAgentVersion)) {
                $expected = ConvertTo-AgentVersion $ExpectedMinimumAgentVersion
                $actual = Get-EndpointAgentVersionCandidate $exe
                if ($null -eq $expected) {
                    Add-Check 'agent-version-floor' 'FAIL' "cannot parse ExpectedMinimumAgentVersion=$ExpectedMinimumAgentVersion"
                } elseif ($null -eq $actual -or $null -eq $actual.parsed) {
                    $detail = if ($null -eq $actual) { 'no endpoint-agent.exe version metadata found' } else { "cannot parse installed version metadata: $($actual.value)" }
                    Add-Check 'agent-version-floor' 'FAIL' $detail
                } elseif ($actual.parsed -lt $expected) {
                    Add-Check 'agent-version-floor' 'FAIL' "installed $($actual.value) from $($actual.source) is below required $ExpectedMinimumAgentVersion"
                } else {
                    Add-Check 'agent-version-floor' 'PASS' "installed $($actual.value) from $($actual.source) meets required $ExpectedMinimumAgentVersion"
                }
            }

            $sig = Get-EndpointAgentSignature -ExePath $exe
            if ($sig) {
                $thumb = if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { '<none>' }
                $pinOk = [string]::IsNullOrWhiteSpace($ExpectedSignerThumbprint) -or ($thumb -eq $ExpectedSignerThumbprint)
                if ($sig.Status -eq 'Valid' -and $pinOk) { Add-Check 'exe-signature' 'PASS' "signature valid signer=$thumb" }
                elseif ($RequireSignature) { Add-Check 'exe-signature' 'FAIL' "signature status=$($sig.Status) signer=$thumb pinOk=$pinOk" }
                else { Add-Check 'exe-signature' 'WARN' "signature status=$($sig.Status) signer=$thumb pinOk=$pinOk" }
            } elseif ($RequireSignature) {
                Add-Check 'exe-signature' 'FAIL' 'signature required but binary missing'
            }
        }
        'rollback-clean' {
            if ($svc) { Add-Check 'service-removed' 'FAIL' "service still present: $($svc.Status)" }
            else { Add-Check 'service-removed' 'PASS' 'service absent' }
            if (Test-Path $exe) { Add-Check 'binary-removed' 'FAIL' "binary still present: $exe" }
            else { Add-Check 'binary-removed' 'PASS' 'binary absent' }
        }
    }

    return [pscustomobject]@{
        computerName = $env:COMPUTERNAME
        domain = $cs.Domain
        partOfDomain = [bool]$cs.PartOfDomain
        role = $Role
        phase = $Phase
        apiHost = $ApiHost
        servicePresent = [bool]$svc
        serviceStatus = if ($svc) { "$($svc.Status)" } else { $null }
        installDir = $InstallDir
        logDir = $LogDir
        machineCertThumbprint = if ($cert) { $cert.Thumbprint } else { $null }
        machineCertSubject = if ($cert) { $cert.Subject } else { $null }
        machineCertIssuer = if ($cert) { $cert.Issuer } else { $null }
        machineCertNotAfter = if ($cert) { $cert.NotAfter.ToString('o') } else { $null }
    }
}

New-Item -ItemType Directory -Force $OutputRoot | Out-Null

$facts = Invoke-CoreChecks
$failCount = ($checks | Where-Object { $_.status -eq 'FAIL' } | Measure-Object).Count
$warnCount = ($checks | Where-Object { $_.status -eq 'WARN' } | Measure-Object).Count
$overall = if ($failCount -gt 0) { 'FAIL' } elseif ($warnCount -gt 0) { 'WARN' } else { 'PASS' }

$result = [pscustomobject]@{
    schema = 'faz22.m5.same-day-pilot.collector.v1'
    collectedAt = (Get-Date).ToString('o')
    overall = $overall
    failCount = $failCount
    warnCount = $warnCount
    facts = $facts
    checks = @($checks)
    edrServices = @(Get-Service -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like '*ESET*' -or $_.DisplayName -like '*ESET*' -or
        $_.Name -like '*ERA*' -or $_.DisplayName -like '*ERA*' -or
        $_.Name -like '*Sense*' -or $_.DisplayName -like '*Defender*' -or
        $_.Name -like '*CrowdStrike*' -or $_.DisplayName -like '*CrowdStrike*'
    } | Select-Object Name, DisplayName, Status, StartType)
    gpresultComputer = @(Get-GpResultText)
    recentEvents = @(Get-RecentEventSummary)
    recentEndpointAgentLogTail = @(Get-SafeLogTail)
}

$safeHost = ($env:COMPUTERNAME -replace '[^A-Za-z0-9_.-]', '_')
$stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
$outFile = Join-Path $OutputRoot ("{0}-{1}-{2}.json" -f $stamp, $safeHost, $Phase)
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $outFile -Encoding UTF8

if ($Json) {
    $result | ConvertTo-Json -Depth 8
} else {
    Write-Host ("M5 same-day collector [{0}/{1}] on {2} -> {3} (FAIL={4} WARN={5})" -f $Role, $Phase, $env:COMPUTERNAME, $overall, $failCount, $warnCount)
    Write-Host "Evidence: $outFile"
}

if ($overall -eq 'FAIL') { exit 1 }
