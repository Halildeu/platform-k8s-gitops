# build-gpo-msi-acceptance-bundle.ps1
#
# Builds a network-share-ready signed MSI / GPO pilot bundle for
# platform-k8s-gitops#1680. The bundle is non-secret and does not mutate AD,
# GPO, endpoints, or backend state. It creates deterministic install, verify,
# and rollback scripts that operators or the Domain Ops executor can place on a
# pilot-only SYSVOL/corp share.

[CmdletBinding()]
param(
    [Parameter()][string]$OutputDir = (Join-Path (Get-Location) "out\endpoint-agent-gpo-msi-acceptance"),
    [Parameter()][string]$ReleaseTag = "v0.2.10",
    [Parameter()][string]$MsiUrl = "https://github.com/Halildeu/platform-agent/releases/download/v0.2.10/EndpointAgent-0.2.10-signed.msi",
    [Parameter()][string]$MsiSha256 = "132b8990bc78c4952ccaa7d2076cf26a37f0616f81e1a82274b5570b49f24ea4",
    [Parameter()][string]$MsiManifestUrl = "https://github.com/Halildeu/platform-agent/releases/download/v0.2.10/msi-build-manifest.json",
    [Parameter()][string]$MsiManifestSha256 = "68929426674f6524e6fdbc78e2eb024920cfd686dd637573537c1717196c69ee",
    [Parameter()][string]$AutoEnrollApiUrl = "https://mtls.testai.acik.com/api/v1/endpoint-agent",
    [Parameter()][string]$AutoEnrollCertSANURIPrefix = "adcomputer:",
    [Parameter()][string]$ExpectedSignerThumbprint = "D68F4F530137EB65CE44E3405E82B46205E753E5",
    [Parameter()][string]$ExpectedMinimumAgentVersion = "0.2.10",
    [Parameter()][int]$AutoEnrollJitterSeconds = 900,
    [Parameter()][switch]$DownloadAssets,
    [Parameter()][switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[bundle] $Message"
}

function Assert-HexSha256 {
    param(
        [string]$Name,
        [string]$Value
    )
    if ($Value -notmatch '^[a-fA-F0-9]{64}$') {
        throw "$Name must be a 64-character SHA256 hex digest"
    }
}

function New-Directory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Copy-RequiredFile {
    param(
        [string]$Source,
        [string]$Destination
    )
    if (-not (Test-Path $Source)) {
        throw "Required source file missing: $Source"
    }
    Copy-Item -Path $Source -Destination $Destination -Force
}

function Save-TextFile {
    param(
        [string]$Path,
        [string]$Content
    )
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

function Get-RelativeRepoRoot {
    $here = Split-Path -Parent $PSCommandPath
    $root = (Resolve-Path (Join-Path (Join-Path $here "..") "..")).Path
    if (-not (Test-Path (Join-Path $root "AGENTS.md"))) {
        throw "Repo root sentinel missing from resolved path: $root"
    }
    return $root
}

function Get-FileHashObject {
    param([string]$Path)
    $item = Get-Item $Path
    $hash = Get-FileHash -Path $Path -Algorithm SHA256
    return [pscustomobject]@{
        path = $item.FullName
        name = $item.Name
        length = $item.Length
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}

function Assert-FileHash {
    param(
        [string]$Path,
        [string]$ExpectedSha256
    )
    if (-not (Test-Path $Path)) {
        throw "Cannot verify missing file: $Path"
    }
    $actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "SHA256 mismatch for $Path. Expected $ExpectedSha256 actual $actual"
    }
}

Assert-HexSha256 -Name "MsiSha256" -Value $MsiSha256
Assert-HexSha256 -Name "MsiManifestSha256" -Value $MsiManifestSha256

$repoRoot = Get-RelativeRepoRoot
$sourceDir = Join-Path (Join-Path $repoRoot "scripts") "faz22-mass-deployment"
$resolvedOutput = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDir)

if ((Test-Path $resolvedOutput) -and -not $Force) {
    throw "OutputDir already exists: $resolvedOutput. Use -Force to overwrite."
}

if (Test-Path $resolvedOutput) {
    Remove-Item -Path $resolvedOutput -Recurse -Force
}

$scriptsDir = Join-Path $resolvedOutput "scripts"
$assetsDir = Join-Path $resolvedOutput "assets"
$evidenceDir = Join-Path $resolvedOutput "evidence-template"
New-Directory $resolvedOutput
New-Directory $scriptsDir
New-Directory $assetsDir
New-Directory $evidenceDir

Write-Step "copy collectors"
$collectorNames = @(
    "collect-endpoint-agent-rollout-evidence.ps1",
    "validate-gpo-msi-rollout-evidence.ps1",
    "wave-preflight.ps1",
    "m5-same-day-pilot-collector.ps1",
    "m7-rollback-rehearsal-collector.ps1"
)
foreach ($name in $collectorNames) {
    Copy-RequiredFile -Source (Join-Path $sourceDir $name) -Destination (Join-Path $scriptsDir $name)
}

$msiFileName = Split-Path -Leaf ([System.Uri]$MsiUrl).AbsolutePath
$manifestFileName = Split-Path -Leaf ([System.Uri]$MsiManifestUrl).AbsolutePath
$msiPath = Join-Path $assetsDir $msiFileName
$msiManifestPath = Join-Path $assetsDir $manifestFileName

if ($DownloadAssets) {
    Write-Step "download signed MSI"
    Invoke-WebRequest -UseBasicParsing -Uri $MsiUrl -OutFile $msiPath
    Assert-FileHash -Path $msiPath -ExpectedSha256 $MsiSha256

    Write-Step "download MSI manifest"
    Invoke-WebRequest -UseBasicParsing -Uri $MsiManifestUrl -OutFile $msiManifestPath
    Assert-FileHash -Path $msiManifestPath -ExpectedSha256 $MsiManifestSha256
} else {
    Write-Step "asset download skipped; URLs and expected hashes recorded only"
}

$installScript = @'
# install-endpoint-agent-gpo-msi.ps1
#
# Pilot-only GPO startup script for EndpointAgent signed MSI install.
# Runs as SYSTEM in computer-assigned GPO context. Non-secret: tokenless mTLS
# auto-enroll only. Do not add HMAC enrollment tokens to this script or MST.

[CmdletBinding()]
param(
    [Parameter()][string]$MsiPath = "",
    [Parameter()][string]$ExpectedMsiSha256 = "__MSI_SHA256__",
    [Parameter()][string]$AutoEnrollApiUrl = "__AUTO_ENROLL_API_URL__",
    [Parameter()][string]$AutoEnrollCertSANURIPrefix = "__AUTO_ENROLL_SAN_URI_PREFIX__",
    [Parameter()][int]$AutoEnrollJitterSeconds = __AUTO_ENROLL_JITTER_SECONDS__,
    [Parameter()][string]$ExpectedSignerThumbprint = "__EXPECTED_SIGNER_THUMBPRINT__",
    [Parameter()][string]$ExpectedMinimumAgentVersion = "__EXPECTED_MINIMUM_AGENT_VERSION__",
    [Parameter()][string]$EvidenceRoot = "$env:ProgramData\EndpointAgent\rollout-evidence",
    [Parameter()][switch]$SkipPostInstallVerify
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ScriptRoot {
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        return $PSScriptRoot
    }
    if (-not [string]::IsNullOrWhiteSpace($MyInvocation.MyCommand.Path)) {
        return (Split-Path -Parent $MyInvocation.MyCommand.Path)
    }
    throw "Unable to resolve script root; pass -MsiPath explicitly."
}

function New-Dir {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Assert-Sha256 {
    param([string]$Path, [string]$Expected)
    if (-not (Test-Path $Path)) { throw "MSI not found: $Path" }
    $actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected.ToLowerInvariant()) {
        throw "MSI SHA256 mismatch. Expected=$Expected Actual=$actual Path=$Path"
    }
}

$ScriptRoot = Resolve-ScriptRoot
if ([string]::IsNullOrWhiteSpace($MsiPath)) {
    $MsiPath = Join-Path $ScriptRoot "..\assets\__MSI_FILE__"
}

New-Dir $EvidenceRoot
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$msiLog = Join-Path $EvidenceRoot "endpoint-agent-msi-install-$env:COMPUTERNAME-$stamp.log"
$summaryPath = Join-Path $EvidenceRoot "endpoint-agent-msi-install-$env:COMPUTERNAME-$stamp.json"

Assert-Sha256 -Path $MsiPath -Expected $ExpectedMsiSha256

$msiArgs = @(
    "/i", "`"$MsiPath`"",
    "/qn",
    "/norestart",
    "/l*v", "`"$msiLog`"",
    "AUTO_ENROLL=1",
    "AUTO_ENROLL_API_URL=$AutoEnrollApiUrl",
    "AUTO_ENROLL_CERT_SAN_URI_PREFIX=$AutoEnrollCertSANURIPrefix",
    "AUTO_ENROLL_JITTER_SECONDS=$AutoEnrollJitterSeconds"
)

$p = Start-Process -FilePath "msiexec.exe" -ArgumentList $msiArgs -Wait -PassThru
$exitCode = $p.ExitCode
$successExitCodes = @(0, 3010)
$installStatus = if ($successExitCodes -contains $exitCode) { "PASS" } else { "FAIL" }

$verify = $null
if (-not $SkipPostInstallVerify) {
    $verifyScript = Join-Path $ScriptRoot "verify-endpoint-agent-gpo-msi.ps1"
    if (Test-Path $verifyScript) {
        $verifyArgs = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$verifyScript`"",
            "-EvidenceRoot", "`"$EvidenceRoot`"",
            "-ExpectedSignerThumbprint", "`"$ExpectedSignerThumbprint`"",
            "-ExpectedMinimumAgentVersion", "`"$ExpectedMinimumAgentVersion`""
        )
        $vp = Start-Process -FilePath "powershell.exe" -ArgumentList $verifyArgs -Wait -PassThru
        $verifySummary = Get-ChildItem -Path $EvidenceRoot -Filter "endpoint-agent-gpo-msi-verify-$env:COMPUTERNAME-*.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        $verify = [pscustomobject]@{
            attempted = $true
            exitCode = $vp.ExitCode
            summaryJson = if ($verifySummary) { $verifySummary.FullName } else { $null }
        }
    } else {
        $verify = [pscustomobject]@{
            attempted = $false
            error = "verify script missing"
        }
    }
}

$summary = [pscustomobject]@{
    schema = "faz22.1680.gpo-msi.install.v1"
    generatedAt = (Get-Date).ToString("o")
    computerName = $env:COMPUTERNAME
    msiPath = $MsiPath
    expectedMsiSha256 = $ExpectedMsiSha256
    autoEnrollApiUrl = $AutoEnrollApiUrl
    autoEnrollCertSANURIPrefix = $AutoEnrollCertSANURIPrefix
    autoEnrollJitterSeconds = $AutoEnrollJitterSeconds
    msiexecExitCode = $exitCode
    installStatus = $installStatus
    acceptedRestartRequired = ($exitCode -eq 3010)
    msiLog = $msiLog
    verify = $verify
}

$summary | ConvertTo-Json -Depth 6 | Set-Content -Path $summaryPath -Encoding UTF8
Write-Host "EndpointAgent GPO/MSI install status=$installStatus exitCode=$exitCode summary=$summaryPath"

if ($installStatus -ne "PASS") { exit $exitCode }
exit 0
'@

$installScript = $installScript.Replace("__MSI_FILE__", $msiFileName)
$installScript = $installScript.Replace("__MSI_SHA256__", $MsiSha256.ToLowerInvariant())
$installScript = $installScript.Replace("__AUTO_ENROLL_API_URL__", $AutoEnrollApiUrl)
$installScript = $installScript.Replace("__AUTO_ENROLL_SAN_URI_PREFIX__", $AutoEnrollCertSANURIPrefix)
$installScript = $installScript.Replace("__AUTO_ENROLL_JITTER_SECONDS__", [string]$AutoEnrollJitterSeconds)
$installScript = $installScript.Replace("__EXPECTED_SIGNER_THUMBPRINT__", $ExpectedSignerThumbprint)
$installScript = $installScript.Replace("__EXPECTED_MINIMUM_AGENT_VERSION__", $ExpectedMinimumAgentVersion)
Save-TextFile -Path (Join-Path $scriptsDir "install-endpoint-agent-gpo-msi.ps1") -Content $installScript

$verifyScript = @'
# verify-endpoint-agent-gpo-msi.ps1
#
# Read-only postinstall evidence wrapper. Runs both the wave preflight and the
# broader rollout evidence collector with the current signed MSI version floor.

[CmdletBinding()]
param(
    [Parameter()][string]$ApiHost = "mtls.testai.acik.com",
    [Parameter()][string]$ExpectedSignerThumbprint = "__EXPECTED_SIGNER_THUMBPRINT__",
    [Parameter()][string]$ExpectedMinimumAgentVersion = "__EXPECTED_MINIMUM_AGENT_VERSION__",
    [Parameter()][string]$ExpectedMsiSha256 = "__MSI_SHA256__",
    [Parameter()][string]$EvidenceRoot = "$env:ProgramData\EndpointAgent\rollout-evidence",
    [Parameter()][switch]$NoRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Resolve-ScriptRoot {
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        return $PSScriptRoot
    }
    if (-not [string]::IsNullOrWhiteSpace($MyInvocation.MyCommand.Path)) {
        return (Split-Path -Parent $MyInvocation.MyCommand.Path)
    }
    throw "Unable to resolve script root."
}

if (-not (Test-Path $EvidenceRoot)) {
    New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
}

$ScriptRoot = Resolve-ScriptRoot
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$preflightOut = Join-Path $EvidenceRoot "wave-preflight-enroll-health-$env:COMPUTERNAME-$stamp.json"
$collectorOut = Join-Path $EvidenceRoot "collector-console-$env:COMPUTERNAME-$stamp.txt"

$wave = Join-Path $ScriptRoot "wave-preflight.ps1"
$collector = Join-Path $ScriptRoot "collect-endpoint-agent-rollout-evidence.ps1"

$waveArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$wave`"",
    "-Mode", "enroll-health",
    "-ApiHost", "`"$ApiHost`"",
    "-RequireMachineCert",
    "-ExpectedMinimumAgentVersion", "`"$ExpectedMinimumAgentVersion`"",
    "-ExitCodeOnFail",
    "-Json"
)

$waveOutput = & powershell.exe @waveArgs
$waveExit = $LASTEXITCODE
$waveOutput | Set-Content -Path $preflightOut -Encoding UTF8

$collectorArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$collector`"",
    "-ExpectedApiHost", "`"$ApiHost`"",
    "-ExpectedMsiSha256", "`"$ExpectedMsiSha256`"",
    "-ExpectedSignerThumbprint", "`"$ExpectedSignerThumbprint`"",
    "-ExpectedMinimumAgentVersion", "`"$ExpectedMinimumAgentVersion`"",
    "-IncludeGpResultHtml"
)
if (-not $NoRestart) {
    $collectorArgs += "-RestartService"
}

$collectorOutput = & powershell.exe @collectorArgs
$collectorExit = $LASTEXITCODE
$collectorOutput | Set-Content -Path $collectorOut -Encoding UTF8
$verifyStatus = if ($waveExit -eq 0 -and $collectorExit -eq 0) { "PASS" } else { "FAIL" }

$summary = [pscustomobject]@{
    schema = "faz22.1680.gpo-msi.verify.v1"
    generatedAt = (Get-Date).ToString("o")
    computerName = $env:COMPUTERNAME
    apiHost = $ApiHost
    expectedSignerThumbprint = $ExpectedSignerThumbprint
    expectedMinimumAgentVersion = $ExpectedMinimumAgentVersion
    expectedMsiSha256 = $ExpectedMsiSha256
    verifyStatus = $verifyStatus
    wavePreflight = [pscustomobject]@{
        exitCode = $waveExit
        output = $preflightOut
    }
    collector = [pscustomobject]@{
        exitCode = $collectorExit
        output = $collectorOut
    }
}

$summaryPath = Join-Path $EvidenceRoot "endpoint-agent-gpo-msi-verify-$env:COMPUTERNAME-$stamp.json"
$summary | ConvertTo-Json -Depth 6 | Set-Content -Path $summaryPath -Encoding UTF8
Write-Host "EndpointAgent verify summary=$summaryPath waveExit=$waveExit collectorExit=$collectorExit"

if ($waveExit -ne 0) { exit $waveExit }
if ($collectorExit -ne 0) { exit $collectorExit }
exit 0
'@

$verifyScript = $verifyScript.Replace("__EXPECTED_SIGNER_THUMBPRINT__", $ExpectedSignerThumbprint)
$verifyScript = $verifyScript.Replace("__EXPECTED_MINIMUM_AGENT_VERSION__", $ExpectedMinimumAgentVersion)
$verifyScript = $verifyScript.Replace("__MSI_SHA256__", $MsiSha256.ToLowerInvariant())
Save-TextFile -Path (Join-Path $scriptsDir "verify-endpoint-agent-gpo-msi.ps1") -Content $verifyScript

$rollbackScript = @'
# rollback-endpoint-agent-gpo-msi.ps1
#
# Pilot-only rollback helper for the signed MSI path. Finds the EndpointAgent
# MSI product code from uninstall registry, runs msiexec /x, and captures
# rollback-clean evidence. Does not mutate GPO or backend enrollment state.

[CmdletBinding()]
param(
    [Parameter()][string]$EvidenceRoot = "$env:ProgramData\EndpointAgent\rollout-evidence",
    [Parameter()][switch]$PurgeConfig
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ScriptRoot {
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        return $PSScriptRoot
    }
    if (-not [string]::IsNullOrWhiteSpace($MyInvocation.MyCommand.Path)) {
        return (Split-Path -Parent $MyInvocation.MyCommand.Path)
    }
    throw "Unable to resolve script root."
}

function New-Dir {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
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

function Get-EndpointAgentProductCode {
    $roots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($root in $roots) {
        $items = Get-ItemProperty $root -ErrorAction SilentlyContinue | Where-Object {
            $displayName = Get-ObjectPropertyValue $_ "DisplayName"
            $installLocation = Get-ObjectPropertyValue $_ "InstallLocation"
            $displayName -like "*Endpoint Agent*" -or
            $displayName -like "*EndpointAgent*" -or
            $installLocation -like "*EndpointAgent*"
        }
        foreach ($item in $items) {
            if ($item.PSChildName -match '^\{[0-9A-Fa-f-]{36}\}$') {
                return $item.PSChildName
            }
            $uninstallString = Get-ObjectPropertyValue $item "UninstallString"
            $quietUninstallString = Get-ObjectPropertyValue $item "QuietUninstallString"
            $candidate = "$uninstallString $quietUninstallString"
            $m = [regex]::Match($candidate, '\{[0-9A-Fa-f-]{36}\}')
            if ($m.Success) { return $m.Value }
        }
    }
    return $null
}

$ScriptRoot = Resolve-ScriptRoot
New-Dir $EvidenceRoot
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$summaryPath = Join-Path $EvidenceRoot "endpoint-agent-gpo-msi-rollback-$env:COMPUTERNAME-$stamp.json"
$msiLog = Join-Path $EvidenceRoot "endpoint-agent-msi-uninstall-$env:COMPUTERNAME-$stamp.log"

$productCode = Get-EndpointAgentProductCode
if ([string]::IsNullOrWhiteSpace($productCode)) {
    $summary = [pscustomobject]@{
        schema = "faz22.1680.gpo-msi.rollback.v1"
        generatedAt = (Get-Date).ToString("o")
        computerName = $env:COMPUTERNAME
        status = "FAIL"
        error = "EndpointAgent MSI product code not found"
    }
    $summary | ConvertTo-Json -Depth 4 | Set-Content -Path $summaryPath -Encoding UTF8
    Write-Host "EndpointAgent rollback failed summary=$summaryPath"
    exit 2
}

$msiArgs = @("/x", $productCode, "/qn", "/norestart", "/l*v", "`"$msiLog`"")
if ($PurgeConfig) {
    $msiArgs += "PURGE_CONFIG=1"
}

$p = Start-Process -FilePath "msiexec.exe" -ArgumentList $msiArgs -Wait -PassThru
$exitCode = $p.ExitCode
$successExitCodes = @(0, 3010, 1605)
$status = if ($successExitCodes -contains $exitCode) { "PASS" } else { "FAIL" }

$wave = Join-Path $ScriptRoot "wave-preflight.ps1"
$m7 = Join-Path $ScriptRoot "m7-rollback-rehearsal-collector.ps1"
$waveOut = Join-Path $EvidenceRoot "wave-preflight-rollback-clean-$env:COMPUTERNAME-$stamp.json"
$m7Out = Join-Path $EvidenceRoot "m7-rollback-console-$env:COMPUTERNAME-$stamp.txt"

$waveArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$wave`"",
    "-Mode", "rollback-clean",
    "-Json",
    "-ExitCodeOnFail"
)
$waveOutput = & powershell.exe @waveArgs
$waveExit = $LASTEXITCODE
$waveOutput | Set-Content -Path $waveOut -Encoding UTF8

$m7Args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$m7`"",
    "-Phase", "rollback-clean",
    "-DeviceRole", "domain-gpo",
    "-Json"
)
$m7Output = & powershell.exe @m7Args
$m7Exit = $LASTEXITCODE
$m7Output | Set-Content -Path $m7Out -Encoding UTF8

$summary = [pscustomobject]@{
    schema = "faz22.1680.gpo-msi.rollback.v1"
    generatedAt = (Get-Date).ToString("o")
    computerName = $env:COMPUTERNAME
    productCode = $productCode
    purgeConfig = [bool]$PurgeConfig
    msiexecExitCode = $exitCode
    rollbackStatus = $status
    msiLog = $msiLog
    wavePreflight = [pscustomobject]@{
        exitCode = $waveExit
        output = $waveOut
    }
    m7Collector = [pscustomobject]@{
        exitCode = $m7Exit
        output = $m7Out
    }
}

$summary | ConvertTo-Json -Depth 6 | Set-Content -Path $summaryPath -Encoding UTF8
Write-Host "EndpointAgent rollback status=$status exitCode=$exitCode summary=$summaryPath"

if ($status -ne "PASS") { exit $exitCode }
if ($waveExit -ne 0) { exit $waveExit }
if ($m7Exit -ne 0) { exit $m7Exit }
exit 0
'@
Save-TextFile -Path (Join-Path $scriptsDir "rollback-endpoint-agent-gpo-msi.ps1") -Content $rollbackScript

$readme = @"
# EndpointAgent signed MSI / GPO acceptance bundle

Tracked gate: platform-k8s-gitops#1680
Generated: $((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))

This bundle is non-secret. It is intended for a pilot-only GPO/SYSVOL or
corp-share path and must not be linked domain-wide.

## Artifact

- Release tag: $ReleaseTag
- MSI URL: $MsiUrl
- MSI SHA256: $($MsiSha256.ToLowerInvariant())
- MSI manifest URL: $MsiManifestUrl
- MSI manifest SHA256: $($MsiManifestSha256.ToLowerInvariant())
- Expected signer thumbprint: $ExpectedSignerThumbprint
- Expected minimum agent version: $ExpectedMinimumAgentVersion
- Auto-enroll API URL: $AutoEnrollApiUrl
- Auto-enroll cert SAN URI prefix: $AutoEnrollCertSANURIPrefix

## Files

- assets/$msiFileName - signed MSI, present only when generated with -DownloadAssets.
- assets/$manifestFileName - trusted signing manifest, present only when generated with -DownloadAssets.
- scripts/install-endpoint-agent-gpo-msi.ps1 - GPO startup install script.
- scripts/verify-endpoint-agent-gpo-msi.ps1 - postinstall evidence wrapper.
- scripts/rollback-endpoint-agent-gpo-msi.ps1 - MSI uninstall + rollback-clean evidence helper.
- scripts/wave-preflight.ps1 - read-only preflight/health/rollback check.
- scripts/collect-endpoint-agent-rollout-evidence.ps1 - redacted per-device collector.
- scripts/m5-same-day-pilot-collector.ps1 - same-day pilot checkpoint collector.
- scripts/m7-rollback-rehearsal-collector.ps1 - rollback rehearsal collector.

## GPO startup command

Use a pilot-only GPO startup PowerShell script entry that points to:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "\\<pilot-share>\EndpointAgent1680\scripts\install-endpoint-agent-gpo-msi.ps1"

Do not put raw enrollment tokens, JWTs, passwords, private keys, or bearer
values in this bundle, a GPO script, an MST, or issue comments.

## Acceptance boundary

Generating this bundle does not satisfy #1680. #1680 still needs constrained
pilot targeting, two managed PCs installed/upgraded through gpo-msi, per-device
service/restart/mTLS evidence, one rollback drill, failure triage, and Project
status evidence.
"@
Save-TextFile -Path (Join-Path $resolvedOutput "README.md") -Content $readme

$evidenceTemplate = @"
EVIDENCE #1680 rollout acceptance <timestamp>

Method: gpo-msi
Artifact:
- release tag: $ReleaseTag
- current version floor: $ExpectedMinimumAgentVersion
- MSI URL/share path:
- MSI SHA256: $($MsiSha256.ToLowerInvariant())
- signer thumbprint: $ExpectedSignerThumbprint
- trusted manifest SHA256: $($MsiManifestSha256.ToLowerInvariant())

Targeting:
- OU:
- security group:
- GPO:
- WMI filter:
- expected computers:

Devices:
| Device | Method applied | Service | Restart | Cert/mTLS | Backend poll/heartbeat | Rollback |
|---|---|---|---|---|---|---|
| <PC1> | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL | N/A/PASS |
| <PC2> | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL | PASS/FAIL |

Evidence files:
- bundle manifest hash:
- PC1 collector JSON hash:
- PC2 collector JSON hash:
- rollback JSON hash:

Failures:
- <none or failed-device queue link>

Non-claims:
- Does not prove 50-PC/800-PC rollout.
- Does not prove production remote support.
- Does not expose raw secrets.
"@
Save-TextFile -Path (Join-Path $evidenceDir "github-issue-comment-template.md") -Content $evidenceTemplate

$files = @()
foreach ($file in Get-ChildItem $resolvedOutput -File -Recurse | Sort-Object FullName) {
    if ($file.Name -eq "bundle-manifest.json") { continue }
    $files += Get-FileHashObject -Path $file.FullName
}

$manifest = [pscustomobject]@{
    schema = "faz22.1680.gpo-msi.acceptance-bundle.v1"
    generatedAt = (Get-Date).ToString("o")
    releaseTag = $ReleaseTag
    artifact = [pscustomobject]@{
        msiUrl = $MsiUrl
        msiSha256 = $MsiSha256.ToLowerInvariant()
        msiManifestUrl = $MsiManifestUrl
        msiManifestSha256 = $MsiManifestSha256.ToLowerInvariant()
        expectedSignerThumbprint = $ExpectedSignerThumbprint
        expectedMinimumAgentVersion = $ExpectedMinimumAgentVersion
    }
    deployment = [pscustomobject]@{
        method = "gpo-msi"
        autoEnrollApiUrl = $AutoEnrollApiUrl
        autoEnrollCertSANURIPrefix = $AutoEnrollCertSANURIPrefix
        autoEnrollJitterSeconds = $AutoEnrollJitterSeconds
        secretFree = $true
        domainWideLinkAllowed = $false
    }
    scripts = [pscustomobject]@{
        install = "scripts/install-endpoint-agent-gpo-msi.ps1"
        verify = "scripts/verify-endpoint-agent-gpo-msi.ps1"
        rollback = "scripts/rollback-endpoint-agent-gpo-msi.ps1"
        wavePreflight = "scripts/wave-preflight.ps1"
        rolloutCollector = "scripts/collect-endpoint-agent-rollout-evidence.ps1"
        evidenceVerifier = "scripts/validate-gpo-msi-rollout-evidence.ps1"
        m5Collector = "scripts/m5-same-day-pilot-collector.ps1"
        m7Collector = "scripts/m7-rollback-rehearsal-collector.ps1"
    }
    acceptanceBoundary = [pscustomobject]@{
        closesIssue1680 = $false
        remaining = @(
            "M3 constrained pilot targeting evidence",
            "M4 two managed PCs installed/upgraded through gpo-msi",
            "M5 per-device service and restart evidence",
            "M6 per-device mTLS/tokenless and backend heartbeat evidence",
            "M7 rollback drill on at least one PC",
            "M8 failed-device triage",
            "M9 Project status evidence"
        )
    }
    files = $files
}

$manifestPath = Join-Path $resolvedOutput "bundle-manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $manifestPath -Encoding UTF8
$bundleManifestHash = (Get-FileHash -Path $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Step "bundle created"
Write-Host ""
Write-Host "OutputDir: $resolvedOutput"
Write-Host "Manifest: $manifestPath"
Write-Host "ManifestSha256: $bundleManifestHash"
Write-Host "DownloadAssets: $([bool]$DownloadAssets)"
Write-Host ""
Write-Host "Next: copy the whole OutputDir to a pilot-only share and link scripts/install-endpoint-agent-gpo-msi.ps1 from a pilot-only GPO startup script."
