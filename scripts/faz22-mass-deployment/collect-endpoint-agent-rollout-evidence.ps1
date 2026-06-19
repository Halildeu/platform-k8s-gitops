# collect-endpoint-agent-rollout-evidence.ps1
#
# Collects redacted per-device evidence for platform-k8s-gitops#1680.
# Designed for Windows PowerShell 5.1 on managed Windows pilot endpoints.

[CmdletBinding()]
param(
    [Parameter()][string]$OutputDir = "$env:ProgramData\EndpointAgent\rollout-evidence",
    [Parameter()][string]$ExpectedApiHost = "mtls.testai.acik.com",
    [Parameter()][string]$ExpectedZipSha256 = "",
    [Parameter()][string]$ExpectedMsiSha256 = "",
    [Parameter()][string]$ExpectedSignerThumbprint = "",
    [Parameter()][string]$ExpectedMinimumAgentVersion = "",
    [Parameter()][int]$TcpTimeoutMs = 3000,
    [Parameter()][int]$LogTailLines = 260,
    [Parameter()][switch]$RestartService,
    [Parameter()][switch]$IncludeGpResultHtml
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function New-EvidenceDirectory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force $Path | Out-Null
    }
}

function Redact-Text {
    param([string]$Text)
    if ($null -eq $Text) { return "" }
    $value = $Text
    $value = $value -replace '(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+', '$1<redacted>'
    $value = $value -replace '(?i)(token\s*[=:]\s*)[^ \t\r\n;]+', '$1<redacted>'
    $value = $value -replace '(?i)(secret\s*[=:]\s*)[^ \t\r\n;]+', '$1<redacted>'
    $value = $value -replace '(?i)(password\s*[=:]\s*)[^ \t\r\n;]+', '$1<redacted>'
    $value = $value -replace '(?i)(enrollment[_-]?token\s*[=:]\s*)[^ \t\r\n;]+', '$1<redacted>'
    return $value
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

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutMs
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $ok) {
            return [PSCustomObject]@{
                host = $HostName
                port = $Port
                open = $false
                error = "timeout"
            }
        }
        try {
            $client.EndConnect($async)
            return [PSCustomObject]@{
                host = $HostName
                port = $Port
                open = $true
                error = $null
            }
        } catch {
            return [PSCustomObject]@{
                host = $HostName
                port = $Port
                open = $false
                error = $_.Exception.Message
            }
        }
    } finally {
        $client.Close()
    }
}

function ConvertTo-AgentVersion {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    $m = [regex]::Match($Value, '(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?')
    if (-not $m.Success) { return $null }
    $build = "0"
    if ($m.Groups[4].Success) { $build = $m.Groups[4].Value }
    try {
        return [version]::Parse(("{0}.{1}.{2}.{3}" -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value, $build))
    } catch {
        return $null
    }
}

function Get-AdObjectGuid {
    try {
        $searcher = [System.DirectoryServices.DirectorySearcher]::new()
        $searcher.Filter = "(&(objectClass=computer)(name=$env:COMPUTERNAME))"
        [void]$searcher.PropertiesToLoad.Add("objectGUID")
        $adResult = $searcher.FindOne()
        if ($null -eq $adResult) {
            return $null
        }
        $guidBytes = $adResult.Properties["objectguid"][0]
        return ([System.Guid]::new($guidBytes)).ToString().ToLowerInvariant()
    } catch {
        return $null
    }
}

function Get-EndpointServiceRows {
    $rows = @()
    $services = Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq "EndpointAgent" -or
            $_.DisplayName -like "*Endpoint Agent*" -or
            $_.PathName -like "*endpoint-agent*"
        }
    foreach ($svc in $services) {
        $rows += [PSCustomObject]@{
            name = $svc.Name
            displayName = $svc.DisplayName
            state = $svc.State
            startMode = $svc.StartMode
            startName = $svc.StartName
            exitCode = $svc.ExitCode
            serviceSpecificExitCode = $svc.ServiceSpecificExitCode
            pathName = $svc.PathName
        }
    }
    return $rows
}

function Get-ServiceEnvironmentRows {
    $rows = @()
    $serviceKey = "HKLM:\SYSTEM\CurrentControlSet\Services\EndpointAgent"
    $raw = (Get-ItemProperty -Path $serviceKey -Name Environment -ErrorAction SilentlyContinue).Environment
    if ($null -eq $raw) {
        return $rows
    }
    foreach ($entry in $raw) {
        $parts = $entry -split "=", 2
        $key = $parts[0]
        $value = ""
        if ($parts.Count -gt 1) { $value = $parts[1] }
        $redacted = $false
        $shownValue = $value
        if ($key -like "*TOKEN*" -or $key -like "*SECRET*" -or $key -like "*KEY*" -or $key -like "*PASSWORD*") {
            $shownValue = "<redacted>"
            $redacted = $true
        }
        $rows += [PSCustomObject]@{
            key = $key
            present = -not [string]::IsNullOrWhiteSpace($value)
            length = $value.Length
            value = $shownValue
            redacted = $redacted
        }
    }
    return $rows
}

function Get-EndpointBinaryEvidence {
    $candidates = @(
        "C:\Program Files\EndpointAgent\endpoint-agent.exe",
        "C:\Program Files\Endpoint Agent\endpoint-agent.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            $item = Get-Item $path
            $hash = Get-FileHash $path -Algorithm SHA256
            $fileVersion = $item.VersionInfo.FileVersion
            $productVersion = $item.VersionInfo.ProductVersion
            return [PSCustomObject]@{
                path = $item.FullName
                length = $item.Length
                lastWriteTime = $item.LastWriteTime.ToString("o")
                sha256 = $hash.Hash
                fileVersion = $fileVersion
                productVersion = $productVersion
                versionOutput = $productVersion
            }
        }
    }
    return $null
}

function Get-InstalledProductRows {
    $rows = @()
    $uninstallRoots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($root in $uninstallRoots) {
        $items = Get-ItemProperty $root -ErrorAction SilentlyContinue |
            Where-Object {
                $displayName = Get-ObjectPropertyValue $_ "DisplayName"
                $installLocation = Get-ObjectPropertyValue $_ "InstallLocation"
                $displayName -like "*Endpoint Agent*" -or
                $displayName -like "*EndpointAgent*" -or
                $installLocation -like "*EndpointAgent*"
            }
        foreach ($item in $items) {
            $displayName = Get-ObjectPropertyValue $item "DisplayName"
            $displayVersion = Get-ObjectPropertyValue $item "DisplayVersion"
            $publisher = Get-ObjectPropertyValue $item "Publisher"
            $installLocation = Get-ObjectPropertyValue $item "InstallLocation"
            $uninstallString = Get-ObjectPropertyValue $item "UninstallString"
            $quietUninstallString = Get-ObjectPropertyValue $item "QuietUninstallString"
            $windowsInstaller = Get-ObjectPropertyValue $item "WindowsInstaller"
            $rows += [PSCustomObject]@{
                displayName = $displayName
                displayVersion = $displayVersion
                publisher = $publisher
                installLocation = $installLocation
                uninstallString = Redact-Text $uninstallString
                quietUninstallString = Redact-Text $quietUninstallString
                windowsInstaller = $windowsInstaller
                psPath = $item.PSPath
            }
        }
    }
    return $rows
}

function Get-AgentVersionFloorEvidence {
    param(
        $Binary,
        $InstalledProducts,
        [string]$ExpectedMinimumVersion
    )

    $candidates = @()
    if ($null -ne $Binary) {
        $candidates += [PSCustomObject]@{
            source = "binary.productVersion"
            value = $Binary.productVersion
            parsed = ConvertTo-AgentVersion $Binary.productVersion
        }
        $candidates += [PSCustomObject]@{
            source = "binary.fileVersion"
            value = $Binary.fileVersion
            parsed = ConvertTo-AgentVersion $Binary.fileVersion
        }
        $candidates += [PSCustomObject]@{
            source = "binary.versionOutput"
            value = $Binary.versionOutput
            parsed = ConvertTo-AgentVersion $Binary.versionOutput
        }
    }

    foreach ($product in $InstalledProducts) {
        $candidates += [PSCustomObject]@{
            source = "installedProduct.displayVersion"
            value = $product.displayVersion
            parsed = ConvertTo-AgentVersion $product.displayVersion
        }
    }

    if ([string]::IsNullOrWhiteSpace($ExpectedMinimumVersion)) {
        return [PSCustomObject]@{
            status = "SKIP"
            expectedMinimumVersion = ""
            selectedVersion = $null
            selectedSource = $null
            message = "ExpectedMinimumAgentVersion not set"
            candidates = $candidates
        }
    }

    $expected = ConvertTo-AgentVersion $ExpectedMinimumVersion
    if ($null -eq $expected) {
        return [PSCustomObject]@{
            status = "FAIL"
            expectedMinimumVersion = $ExpectedMinimumVersion
            selectedVersion = $null
            selectedSource = $null
            message = "Cannot parse ExpectedMinimumAgentVersion"
            candidates = $candidates
        }
    }

    $parsedCandidates = @($candidates | Where-Object { $null -ne $_.parsed } | Sort-Object parsed -Descending)
    if ($parsedCandidates.Count -eq 0) {
        return [PSCustomObject]@{
            status = "FAIL"
            expectedMinimumVersion = $ExpectedMinimumVersion
            selectedVersion = $null
            selectedSource = $null
            message = "No parseable installed EndpointAgent version metadata found"
            candidates = $candidates
        }
    }

    $selected = $parsedCandidates[0]
    $status = "PASS"
    $message = "Installed version meets minimum version floor"
    if ($selected.parsed -lt $expected) {
        $status = "FAIL"
        $message = "Installed version is below minimum version floor"
    }

    return [PSCustomObject]@{
        status = $status
        expectedMinimumVersion = $ExpectedMinimumVersion
        selectedVersion = $selected.value
        selectedSource = $selected.source
        selectedParsedVersion = $selected.parsed.ToString()
        message = $message
        candidates = $candidates
    }
}

function Get-ClientAuthCertRows {
    param([string]$ExpectedGuid)
    $rows = @()
    $certs = Get-ChildItem Cert:\LocalMachine\My -ErrorAction SilentlyContinue |
        Where-Object {
            $_.HasPrivateKey -and
            $_.EnhancedKeyUsageList.ObjectId -contains "1.3.6.1.5.5.7.3.2"
        } |
        Sort-Object NotBefore -Descending

    foreach ($cert in $certs) {
        $sanExt = $cert.Extensions |
            Where-Object { $_.Oid.Value -eq "2.5.29.17" } |
            Select-Object -First 1
        $sanText = ""
        if ($sanExt) { $sanText = $sanExt.Format($false) }

        $templateExt = $cert.Extensions |
            Where-Object { $_.Oid.Value -eq "1.3.6.1.4.1.311.21.7" } |
            Select-Object -First 1
        $templateText = ""
        if ($templateExt) { $templateText = $templateExt.Format($false) }

        $hasExpectedAdComputerSan = $false
        if (-not [string]::IsNullOrWhiteSpace($ExpectedGuid)) {
            $hasExpectedAdComputerSan = ($sanText -match "adcomputer:$ExpectedGuid")
        }

        $rows += [PSCustomObject]@{
            subject = $cert.Subject
            issuer = $cert.Issuer
            thumbprint = $cert.Thumbprint
            notBefore = $cert.NotBefore.ToString("o")
            notAfter = $cert.NotAfter.ToString("o")
            hasPrivateKey = $cert.HasPrivateKey
            enhancedKeyUsage = (($cert.EnhancedKeyUsageList | ForEach-Object { "$($_.FriendlyName) ($($_.ObjectId))" }) -join "; ")
            template = $templateText
            san = $sanText
            hasExpectedAdComputerSan = $hasExpectedAdComputerSan
        }
    }
    return $rows
}

function Write-RedactedLogTail {
    param(
        [string]$Path,
        [int]$TailLines,
        [string]$OutFile
    )
    $lines = @()
    $files = Get-ChildItem $Path -ErrorAction SilentlyContinue
    foreach ($file in $files) {
        $lines += "===== $($file.FullName) ====="
        $tail = Get-Content $file.FullName -Tail $TailLines -ErrorAction SilentlyContinue
        foreach ($line in $tail) {
            $lines += (Redact-Text $line)
        }
    }
    $lines | Set-Content -Path $OutFile -Encoding UTF8
}

New-EvidenceDirectory $OutputDir
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$jsonPath = Join-Path $OutputDir "endpoint-agent-rollout-evidence-$env:COMPUTERNAME-$timestamp.json"
$logTailPath = Join-Path $OutputDir "endpoint-agent-logtail-$env:COMPUTERNAME-$timestamp.txt"
$gpTextPath = Join-Path $OutputDir "gpresult-$env:COMPUTERNAME-$timestamp.txt"
$gpHtmlPath = Join-Path $OutputDir "gpresult-$env:COMPUTERNAME-$timestamp.html"

$startedAt = (Get-Date).ToString("o")
$computerSystem = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
$os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
$adGuid = Get-AdObjectGuid

$restartEvidence = [PSCustomObject]@{
    requested = [bool]$RestartService
    attempted = $false
    success = $false
    error = $null
    stateAfter = $null
}

if ($RestartService) {
    $restartEvidence.attempted = $true
    try {
        Restart-Service EndpointAgent -Force -ErrorAction Stop
        Start-Sleep -Seconds 30
        $svcAfter = Get-Service EndpointAgent -ErrorAction Stop
        $restartEvidence.stateAfter = $svcAfter.Status.ToString()
        $restartEvidence.success = ($svcAfter.Status.ToString() -eq "Running")
    } catch {
        $restartEvidence.error = $_.Exception.Message
    }
}

$dnsRows = @()
try {
    $records = Resolve-DnsName $ExpectedApiHost -ErrorAction Stop
    foreach ($record in $records) {
        $dnsRows += [PSCustomObject]@{
            name = $record.Name
            type = $record.Type
            ipAddress = $record.IPAddress
            nameTarget = $record.NameTarget
        }
    }
} catch {
    $dnsRows += [PSCustomObject]@{
        name = $ExpectedApiHost
        type = "ERROR"
        ipAddress = $null
        nameTarget = $_.Exception.Message
    }
}

$tcp443 = Test-TcpPort -HostName $ExpectedApiHost -Port 443 -TimeoutMs $TcpTimeoutMs
$serviceRows = @(Get-EndpointServiceRows)
$envRows = @(Get-ServiceEnvironmentRows)
$binary = Get-EndpointBinaryEvidence
$installedProducts = @(Get-InstalledProductRows)
$versionFloor = Get-AgentVersionFloorEvidence -Binary $binary -InstalledProducts $installedProducts -ExpectedMinimumVersion $ExpectedMinimumAgentVersion
$certRows = @(Get-ClientAuthCertRows -ExpectedGuid $adGuid)

$processRows = @()
$processes = Get-Process endpoint-agent -ErrorAction SilentlyContinue
foreach ($process in $processes) {
    $processRows += [PSCustomObject]@{
        processName = $process.ProcessName
        id = $process.Id
        startTime = $process.StartTime.ToString("o")
        workingSet64 = $process.WorkingSet64
        path = $process.Path
    }
}

try {
    gpresult /r /scope computer > $gpTextPath 2>&1
} catch {
    "gpresult failed: $($_.Exception.Message)" | Set-Content -Path $gpTextPath -Encoding UTF8
}

if ($IncludeGpResultHtml) {
    try {
        gpresult /h $gpHtmlPath /scope computer /f > $null 2>&1
    } catch {
        "gpresult html failed: $($_.Exception.Message)" | Set-Content -Path "$gpHtmlPath.error.txt" -Encoding UTF8
    }
}

Write-RedactedLogTail -Path "C:\ProgramData\EndpointAgent\logs\*.log" -TailLines $LogTailLines -OutFile $logTailPath

$completedAt = (Get-Date).ToString("o")

$summary = [PSCustomObject]@{
    schema = "faz22.5-endpoint-agent-rollout-evidence-v1"
    generatedAt = $completedAt
    computerName = $env:COMPUTERNAME
    user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    expected = [PSCustomObject]@{
        apiHost = $ExpectedApiHost
        zipSha256 = $ExpectedZipSha256
        msiSha256 = $ExpectedMsiSha256
        signerThumbprint = $ExpectedSignerThumbprint
        minimumAgentVersion = $ExpectedMinimumAgentVersion
    }
    host = [PSCustomObject]@{
        domain = $computerSystem.Domain
        domainJoined = $computerSystem.PartOfDomain
        manufacturer = $computerSystem.Manufacturer
        model = $computerSystem.Model
        osCaption = $os.Caption
        osVersion = $os.Version
        osBuildNumber = $os.BuildNumber
        adObjectGuid = $adGuid
    }
    network = [PSCustomObject]@{
        dns = $dnsRows
        tcp443 = $tcp443
    }
    endpointAgent = [PSCustomObject]@{
        services = $serviceRows
        processes = $processRows
        serviceEnvironment = $envRows
        binary = $binary
        installedProducts = $installedProducts
        versionFloor = $versionFloor
        restart = $restartEvidence
        clientAuthCerts = $certRows
    }
    evidenceFiles = [PSCustomObject]@{
        json = $jsonPath
        gpresultText = $gpTextPath
        gpresultHtml = $(if ($IncludeGpResultHtml) { $gpHtmlPath } else { $null })
        redactedLogTail = $logTailPath
    }
    timings = [PSCustomObject]@{
        startedAt = $startedAt
        completedAt = $completedAt
    }
}

$summary | ConvertTo-Json -Depth 8 | Set-Content -Path $jsonPath -Encoding UTF8

Write-Host ""
Write-Host "=== ENDPOINT AGENT ROLLOUT EVIDENCE SUMMARY ==="
Write-Host "Computer: $env:COMPUTERNAME"
Write-Host "Domain: $($computerSystem.Domain)"
Write-Host "DomainJoined: $($computerSystem.PartOfDomain)"
Write-Host "APIHost: $ExpectedApiHost TCP443=$($tcp443.open)"
Write-Host "ServiceCount: $($serviceRows.Count)"
Write-Host "ClientAuthCertCount: $($certRows.Count)"
Write-Host "VersionFloor: $($versionFloor.status) $($versionFloor.message)"
Write-Host "RestartRequested: $($restartEvidence.requested) RestartSuccess: $($restartEvidence.success)"
Write-Host "JSON: $jsonPath"
Write-Host "RedactedLogTail: $logTailPath"
Write-Host "GPResultText: $gpTextPath"
if ($IncludeGpResultHtml) {
    Write-Host "GPResultHtml: $gpHtmlPath"
}

if ($serviceRows.Count -eq 0) {
    exit 2
}

$running = $false
foreach ($svc in $serviceRows) {
    if ($svc.name -eq "EndpointAgent" -and $svc.state -eq "Running") {
        $running = $true
    }
}

if (-not $running) {
    exit 3
}

if ($RestartService -and -not $restartEvidence.success) {
    exit 4
}

if ($versionFloor.status -eq "FAIL") {
    exit 5
}

exit 0
