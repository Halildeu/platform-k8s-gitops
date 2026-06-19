# validate-gpo-msi-rollout-evidence.ps1
#
# Read-only evidence verifier for platform-k8s-gitops#1680. It validates that a
# signed MSI / GPO pilot evidence folder contains the minimum live acceptance
# artifacts for the two-managed-PC rollout gate. It does not mutate AD, GPO,
# endpoints, backend state, GitHub issues, or Project fields.

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$EvidenceRoot,
    [Parameter()][string]$BundleManifestPath = "",
    [Parameter()][string]$ExpectedMsiSha256 = "132b8990bc78c4952ccaa7d2076cf26a37f0616f81e1a82274b5570b49f24ea4",
    [Parameter()][string]$ExpectedMsiManifestSha256 = "68929426674f6524e6fdbc78e2eb024920cfd686dd637573537c1717196c69ee",
    [Parameter()][string]$ExpectedSignerThumbprint = "D68F4F530137EB65CE44E3405E82B46205E753E5",
    [Parameter()][string]$ExpectedMinimumAgentVersion = "0.2.10",
    [Parameter()][string]$ExpectedApiHost = "mtls.testai.acik.com",
    [Parameter()][int]$RequiredDeviceCount = 2,
    [Parameter()][int]$RequiredRollbackDeviceCount = 1,
    [Parameter()][int]$MaxTextScanBytes = 3145728,
    [Parameter()][switch]$Json,
    [Parameter()][switch]$ExitCodeOnFail
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:VerifierChecks = New-Object System.Collections.ArrayList

function Add-Check {
    param(
        [string]$Name,
        [ValidateSet("PASS", "FAIL", "WARN", "INFO")][string]$Status,
        [string]$Detail,
        [object]$Data = $null
    )
    $null = $script:VerifierChecks.Add([pscustomobject]@{
        name = $Name
        status = $Status
        detail = $Detail
        data = $Data
    })
}

function Assert-HexSha256 {
    param([string]$Name, [string]$Value)
    if ($Value -notmatch '^[a-fA-F0-9]{64}$') {
        throw "$Name must be a 64-character SHA256 hex digest"
    }
}

function Normalize-String {
    param([object]$Value)
    if ($null -eq $Value) { return "" }
    return [string]$Value
}

function Same-Text {
    param([object]$Actual, [object]$Expected)
    return ((Normalize-String $Actual).ToLowerInvariant() -eq (Normalize-String $Expected).ToLowerInvariant())
}

function Get-Field {
    param(
        [object]$Object,
        [string]$Path
    )
    if ($null -eq $Object) { return $null }
    $cursor = $Object
    foreach ($part in ($Path -split '\.')) {
        if ($null -eq $cursor) { return $null }
        $property = $cursor.PSObject.Properties[$part]
        if ($null -eq $property) { return $null }
        $cursor = $property.Value
    }
    return $cursor
}

function Get-DeviceName {
    param([object]$Data)
    $paths = @("computerName", "facts.computerName", "host", "result.host")
    foreach ($path in $paths) {
        $value = Get-Field -Object $Data -Path $path
        if (-not [string]::IsNullOrWhiteSpace([string]$value)) {
            return [string]$value
        }
    }
    return ""
}

function Read-JsonEvidence {
    param([string]$Root)
    $docs = @()
    $files = Get-ChildItem -Path $Root -Recurse -File -Filter "*.json" -ErrorAction SilentlyContinue |
        Sort-Object FullName
    foreach ($file in $files) {
        try {
            $raw = Get-Content -Path $file.FullName -Raw -ErrorAction Stop
            $data = $raw | ConvertFrom-Json -ErrorAction Stop
            $docs += [pscustomobject]@{
                path = $file.FullName
                data = $data
                schema = Normalize-String (Get-Field -Object $data -Path "schema")
            }
        } catch {
            Add-Check "json-parse:$($file.Name)" "FAIL" $_.Exception.Message
        }
    }
    return @($docs)
}

function Find-DocsBySchema {
    param(
        [object[]]$Docs,
        [string]$Schema
    )
    return @($Docs | Where-Object { $_.schema -eq $Schema })
}

function Get-UniqueNames {
    param([string[]]$Names)
    return @($Names | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)
}

function Test-AnyServiceRunning {
    param([object]$Services)
    foreach ($svc in @($Services)) {
        if ((Same-Text (Get-Field $svc "name") "EndpointAgent") -and
            (Same-Text (Get-Field $svc "state") "Running")) {
            return $true
        }
    }
    return $false
}

function Test-ServiceStartMode {
    param([object]$Services)
    foreach ($svc in @($Services)) {
        if ((Same-Text (Get-Field $svc "name") "EndpointAgent") -and
            ((Same-Text (Get-Field $svc "startMode") "Auto") -or (Same-Text (Get-Field $svc "startMode") "Automatic"))) {
            return $true
        }
    }
    return $false
}

function Test-ServiceStartName {
    param([object]$Services)
    foreach ($svc in @($Services)) {
        $startName = Normalize-String (Get-Field $svc "startName")
        if ((Same-Text (Get-Field $svc "name") "EndpointAgent") -and
            ($startName -match '^(LocalSystem|NT AUTHORITY\\LocalSystem)$')) {
            return $true
        }
    }
    return $false
}

function Test-ClientAuthCert {
    param([object]$Certs)
    foreach ($cert in @($Certs)) {
        $eku = Normalize-String (Get-Field $cert "enhancedKeyUsage")
        $hasPrivateKey = [bool](Get-Field $cert "hasPrivateKey")
        if ($hasPrivateKey -and $eku -match '1\.3\.6\.1\.5\.5\.7\.3\.2') {
            return $true
        }
    }
    return $false
}

function Test-CheckStatus {
    param(
        [object]$Checks,
        [string]$Name,
        [string]$Status
    )
    foreach ($check in @($Checks)) {
        $checkName = Normalize-String (Get-Field $check "check")
        if ([string]::IsNullOrWhiteSpace($checkName)) {
            $checkName = Normalize-String (Get-Field $check "name")
        }
        if ($checkName -eq $Name -and (Same-Text (Get-Field $check "status") $Status)) {
            return $true
        }
    }
    return $false
}

function Test-NoFailures {
    param([object]$Checks)
    foreach ($check in @($Checks)) {
        if (Same-Text (Get-Field $check "status") "FAIL") {
            return $false
        }
    }
    return $true
}

function Invoke-SecretScan {
    param([string]$Root, [int]$MaxBytes)
    $violations = @()
    $patterns = @(
        '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
        '(?i)authorization:\s*bearer\s+(?!<redacted>)[A-Za-z0-9._~+/=-]{12,}',
        '(?i)(enrollment[_-]?token|password|secret|jwt|bearer)\s*[:=]\s*(?!"?<redacted>"?)(?!null)(?!false)[^,\s"'';]{8,}'
    )
    $files = Get-ChildItem -Path $Root -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @(".json", ".txt", ".md", ".log") -and $_.Length -le $MaxBytes }
    foreach ($file in $files) {
        $text = Get-Content -Path $file.FullName -Raw -ErrorAction SilentlyContinue
        foreach ($pattern in $patterns) {
            if ($text -match $pattern) {
                $violations += $file.FullName
                break
            }
        }
    }
    $violations = @($violations | Sort-Object -Unique)
    if ($violations.Count -gt 0) {
        Add-Check "secret-scan" "FAIL" "Possible raw secret material found in evidence files" $violations
    } else {
        Add-Check "secret-scan" "PASS" "No raw token/password/bearer/private-key pattern found in scanned evidence files"
    }
}

function Validate-BundleManifest {
    param([object[]]$Docs, [string]$ExplicitPath)
    $manifestDoc = $null
    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        if (-not (Test-Path $ExplicitPath)) {
            Add-Check "M1-bundle-manifest" "FAIL" "BundleManifestPath not found: $ExplicitPath"
            return
        }
        try {
            $data = (Get-Content -Path $ExplicitPath -Raw) | ConvertFrom-Json
            $manifestDoc = [pscustomobject]@{ path = (Resolve-Path $ExplicitPath).Path; data = $data }
        } catch {
            Add-Check "M1-bundle-manifest" "FAIL" "Cannot parse bundle manifest: $($_.Exception.Message)"
            return
        }
    } else {
        $matches = @(Find-DocsBySchema -Docs $Docs -Schema "faz22.1680.gpo-msi.acceptance-bundle.v1")
        if ($matches.Count -gt 0) { $manifestDoc = $matches[0] }
    }

    if ($null -eq $manifestDoc) {
        Add-Check "M1-bundle-manifest" "FAIL" "Missing bundle manifest schema faz22.1680.gpo-msi.acceptance-bundle.v1"
        return
    }

    $m = $manifestDoc.data
    $failures = @()
    if (-not (Same-Text (Get-Field $m "schema") "faz22.1680.gpo-msi.acceptance-bundle.v1")) { $failures += "schema" }
    if (-not (Same-Text (Get-Field $m "artifact.msiSha256") $ExpectedMsiSha256)) { $failures += "artifact.msiSha256" }
    if (-not (Same-Text (Get-Field $m "artifact.msiManifestSha256") $ExpectedMsiManifestSha256)) { $failures += "artifact.msiManifestSha256" }
    if (-not (Same-Text (Get-Field $m "artifact.expectedSignerThumbprint") $ExpectedSignerThumbprint)) { $failures += "artifact.expectedSignerThumbprint" }
    if (-not (Same-Text (Get-Field $m "artifact.expectedMinimumAgentVersion") $ExpectedMinimumAgentVersion)) { $failures += "artifact.expectedMinimumAgentVersion" }
    if (-not (Same-Text (Get-Field $m "deployment.method") "gpo-msi")) { $failures += "deployment.method" }
    if (-not (Same-Text (Get-Field $m "deployment.autoEnrollApiUrl") "https://$ExpectedApiHost/api/v1/endpoint-agent")) { $failures += "deployment.autoEnrollApiUrl" }
    if (-not (Same-Text (Get-Field $m "deployment.autoEnrollCertSANURIPrefix") "adcomputer:")) { $failures += "deployment.autoEnrollCertSANURIPrefix" }
    if (-not [bool](Get-Field $m "deployment.secretFree")) { $failures += "deployment.secretFree" }
    if ([bool](Get-Field $m "deployment.domainWideLinkAllowed")) { $failures += "deployment.domainWideLinkAllowed" }
    if ([bool](Get-Field $m "acceptanceBoundary.closesIssue1680")) { $failures += "acceptanceBoundary.closesIssue1680" }

    if ($failures.Count -gt 0) {
        Add-Check "M1-bundle-manifest" "FAIL" ("Bundle manifest guardrail mismatch: " + ($failures -join ", ")) $manifestDoc.path
    } else {
        Add-Check "M1-bundle-manifest" "PASS" "Pinned v0.2.10 signed MSI bundle manifest matches expected guardrails" $manifestDoc.path
    }
}

function Validate-Targeting {
    param([object[]]$Docs)
    $docs = @(Find-DocsBySchema -Docs $Docs -Schema "faz22.1680.gpo-msi.targeting.v1")
    if ($docs.Count -eq 0) {
        Add-Check "M3-targeting" "FAIL" "Missing pilot targeting evidence schema faz22.1680.gpo-msi.targeting.v1"
        return
    }
    $data = $docs[0].data
    $expected = @(Get-UniqueNames @((Get-Field $data "expectedComputers")))
    $actual = @(Get-UniqueNames @((Get-Field $data "actualComputers")))
    $broadApply = [bool](Get-Field $data "broadTargetingDetected") -or
        [bool](Get-Field $data "domainWideLinkAllowed") -or
        [bool](Get-Field $data "authenticatedUsersApplyAllowed")
    $missing = @($expected | Where-Object { $actual -notcontains $_ })
    if (-not (Same-Text (Get-Field $data "status") "PASS")) {
        Add-Check "M3-targeting" "FAIL" "Targeting evidence status is not PASS"
    } elseif (-not (Same-Text (Get-Field $data "method") "gpo-msi")) {
        Add-Check "M3-targeting" "FAIL" "Targeting evidence method is not gpo-msi"
    } elseif ($expected.Count -lt $RequiredDeviceCount) {
        Add-Check "M3-targeting" "FAIL" "Targeting evidence has fewer than $RequiredDeviceCount expected computers" $expected
    } elseif ($missing.Count -gt 0) {
        Add-Check "M3-targeting" "FAIL" "Targeting actualComputers is missing expected computers" $missing
    } elseif ($broadApply) {
        Add-Check "M3-targeting" "FAIL" "Targeting evidence indicates domain-wide or Authenticated Users apply path"
    } else {
        Add-Check "M3-targeting" "PASS" "Pilot OU/security-filter targeting evidence is constrained" $actual
    }
}

function Validate-InstallEvidence {
    param([object[]]$Docs)
    $docs = @(Find-DocsBySchema -Docs $Docs -Schema "faz22.1680.gpo-msi.install.v1")
    $passing = @()
    foreach ($doc in $docs) {
        $d = $doc.data
        $device = Get-DeviceName $d
        $exitCode = [int](Get-Field $d "msiexecExitCode")
        if ((Same-Text (Get-Field $d "installStatus") "PASS") -and
            ($exitCode -in @(0, 3010)) -and
            (Same-Text (Get-Field $d "expectedMsiSha256") $ExpectedMsiSha256) -and
            (Same-Text (Get-Field $d "autoEnrollApiUrl") "https://$ExpectedApiHost/api/v1/endpoint-agent") -and
            (Same-Text (Get-Field $d "autoEnrollCertSANURIPrefix") "adcomputer:")) {
            $passing += $device
        }
    }
    $devices = @(Get-UniqueNames $passing)
    if ($devices.Count -lt $RequiredDeviceCount) {
        Add-Check "M4-install-evidence" "FAIL" "Need $RequiredDeviceCount passing gpo-msi install summaries; found $($devices.Count)" $devices
    } else {
        Add-Check "M4-install-evidence" "PASS" "Found passing install summaries for $($devices.Count) managed PCs" $devices
    }
}

function Validate-VerifyEvidence {
    param([object[]]$Docs)
    $docs = @(Find-DocsBySchema -Docs $Docs -Schema "faz22.1680.gpo-msi.verify.v1")
    $passing = @()
    foreach ($doc in $docs) {
        $d = $doc.data
        $device = Get-DeviceName $d
        if ((Same-Text (Get-Field $d "apiHost") $ExpectedApiHost) -and
            (Same-Text (Get-Field $d "verifyStatus") "PASS") -and
            (Same-Text (Get-Field $d "expectedSignerThumbprint") $ExpectedSignerThumbprint) -and
            (Same-Text (Get-Field $d "expectedMinimumAgentVersion") $ExpectedMinimumAgentVersion) -and
            (Same-Text (Get-Field $d "expectedMsiSha256") $ExpectedMsiSha256) -and
            ([int](Get-Field $d "wavePreflight.exitCode") -eq 0) -and
            ([int](Get-Field $d "collector.exitCode") -eq 0)) {
            $passing += $device
        }
    }
    $devices = @(Get-UniqueNames $passing)
    if ($devices.Count -lt $RequiredDeviceCount) {
        Add-Check "M4-verify-wrapper" "FAIL" "Need $RequiredDeviceCount passing verify wrapper summaries; found $($devices.Count)" $devices
    } else {
        Add-Check "M4-verify-wrapper" "PASS" "Found passing verify wrapper summaries for $($devices.Count) managed PCs" $devices
    }
}

function Validate-WavePreflight {
    param([object[]]$Docs)
    $candidates = @($Docs | Where-Object {
        (Same-Text (Get-Field $_.data "mode") "enroll-health") -and
        -not [string]::IsNullOrWhiteSpace((Normalize-String (Get-Field $_.data "overall")))
    })
    $passing = @()
    foreach ($doc in $candidates) {
        $d = $doc.data
        $device = Get-DeviceName $d
        $checks = @(Get-Field $d "checks")
        $overall = Normalize-String (Get-Field $d "overall")
        $overallOk = (Same-Text $overall "PASS") -or (Same-Text $overall "PASS-WITH-WARN")
        if ($overallOk -and
            ([int](Get-Field $d "failCount") -eq 0) -and
            (Test-CheckStatus -Checks $checks -Name "service-state" -Status "PASS") -and
            (Test-CheckStatus -Checks $checks -Name "agent-version-floor" -Status "PASS") -and
            (Test-CheckStatus -Checks $checks -Name "backend-reachability" -Status "PASS") -and
            (Test-NoFailures -Checks $checks)) {
            $passing += $device
        }
    }
    $devices = @(Get-UniqueNames $passing)
    if ($devices.Count -lt $RequiredDeviceCount) {
        Add-Check "M4-M6-wave-preflight" "FAIL" "Need $RequiredDeviceCount passing enroll-health preflight JSON files; found $($devices.Count)" $devices
    } else {
        Add-Check "M4-M6-wave-preflight" "PASS" "Found passing enroll-health preflight evidence for $($devices.Count) managed PCs" $devices
    }
}

function Validate-RolloutCollector {
    param([object[]]$Docs)
    $docs = @(Find-DocsBySchema -Docs $Docs -Schema "faz22.5-endpoint-agent-rollout-evidence-v1")
    $passing = @()
    foreach ($doc in $docs) {
        $d = $doc.data
        $device = Get-DeviceName $d
        $services = @(Get-Field $d "endpointAgent.services")
        $certs = @(Get-Field $d "endpointAgent.clientAuthCerts")
        $restartRequested = [bool](Get-Field $d "endpointAgent.restart.requested")
        $restartSuccess = [bool](Get-Field $d "endpointAgent.restart.success")
        if ((Same-Text (Get-Field $d "expected.apiHost") $ExpectedApiHost) -and
            (Same-Text (Get-Field $d "expected.msiSha256") $ExpectedMsiSha256) -and
            (Same-Text (Get-Field $d "expected.signerThumbprint") $ExpectedSignerThumbprint) -and
            (Same-Text (Get-Field $d "expected.minimumAgentVersion") $ExpectedMinimumAgentVersion) -and
            ([bool](Get-Field $d "host.domainJoined")) -and
            ([bool](Get-Field $d "network.tcp443.open")) -and
            (Test-AnyServiceRunning -Services $services) -and
            (Test-ServiceStartMode -Services $services) -and
            (Test-ServiceStartName -Services $services) -and
            (Same-Text (Get-Field $d "endpointAgent.versionFloor.status") "PASS") -and
            $restartRequested -and $restartSuccess -and
            (Test-ClientAuthCert -Certs $certs)) {
            $passing += $device
        }
    }
    $devices = @(Get-UniqueNames $passing)
    if ($devices.Count -lt $RequiredDeviceCount) {
        Add-Check "M5-M6-rollout-collector" "FAIL" "Need $RequiredDeviceCount passing rollout collector JSON files; found $($devices.Count)" $devices
    } else {
        Add-Check "M5-M6-rollout-collector" "PASS" "Found service/restart/mTLS collector evidence for $($devices.Count) managed PCs" $devices
    }
}

function Validate-RollbackEvidence {
    param([object[]]$Docs)
    $rollbackDocs = @(Find-DocsBySchema -Docs $Docs -Schema "faz22.1680.gpo-msi.rollback.v1")
    $passingRollback = @()
    foreach ($doc in $rollbackDocs) {
        $d = $doc.data
        $device = Get-DeviceName $d
        if ((Same-Text (Get-Field $d "rollbackStatus") "PASS") -and
            ([int](Get-Field $d "msiexecExitCode") -in @(0, 3010, 1605)) -and
            ([int](Get-Field $d "wavePreflight.exitCode") -eq 0) -and
            ([int](Get-Field $d "m7Collector.exitCode") -eq 0)) {
            $passingRollback += $device
        }
    }
    $rollbackDevices = @(Get-UniqueNames $passingRollback)

    $m7Rollback = @(Find-DocsBySchema -Docs $Docs -Schema "faz22.m7.rollback-rehearsal.collector.v1" | Where-Object {
        (Same-Text (Get-Field $_.data "phase") "rollback-clean") -and
        (Same-Text (Get-Field $_.data "overall") "PASS") -and
        ([int](Get-Field $_.data "failCount") -eq 0) -and
        (Test-CheckStatus -Checks @(Get-Field $_.data "checks") -Name "service-removed" -Status "PASS") -and
        (Test-CheckStatus -Checks @(Get-Field $_.data "checks") -Name "agent-binary-removed" -Status "PASS") -and
        (Test-CheckStatus -Checks @(Get-Field $_.data "checks") -Name "service-env-cleared" -Status "PASS")
    } | ForEach-Object { Get-DeviceName $_.data })
    $m7RollbackDevices = @(Get-UniqueNames $m7Rollback)

    $m7Reinstall = @(Find-DocsBySchema -Docs $Docs -Schema "faz22.m7.rollback-rehearsal.collector.v1" | Where-Object {
        (Same-Text (Get-Field $_.data "phase") "reinstall-continuity") -and
        (Same-Text (Get-Field $_.data "overall") "PASS") -and
        ([int](Get-Field $_.data "failCount") -eq 0) -and
        (Test-CheckStatus -Checks @(Get-Field $_.data "checks") -Name "service-running" -Status "PASS") -and
        (Test-CheckStatus -Checks @(Get-Field $_.data "checks") -Name "agent-binary" -Status "PASS")
    } | ForEach-Object { Get-DeviceName $_.data })
    $m7ReinstallDevices = @(Get-UniqueNames $m7Reinstall)

    $eligible = @()
    foreach ($device in $rollbackDevices) {
        if ($m7RollbackDevices -contains $device -and $m7ReinstallDevices -contains $device) {
            $eligible += $device
        }
    }
    $eligible = @(Get-UniqueNames $eligible)
    if ($eligible.Count -lt $RequiredRollbackDeviceCount) {
        Add-Check "M7-rollback-drill" "FAIL" "Need rollback summary + rollback-clean + reinstall-continuity evidence for $RequiredRollbackDeviceCount device(s); found $($eligible.Count)" @{
            rollbackSummaryDevices = $rollbackDevices
            rollbackCleanDevices = $m7RollbackDevices
            reinstallContinuityDevices = $m7ReinstallDevices
        }
    } else {
        Add-Check "M7-rollback-drill" "PASS" "Found rollback and reinstall continuity evidence for $($eligible.Count) device(s)" $eligible
    }
}

function Validate-FailureTriage {
    param([object[]]$Docs)
    $docs = @(Find-DocsBySchema -Docs $Docs -Schema "faz22.1680.gpo-msi.failed-device-triage.v1")
    if ($docs.Count -eq 0) {
        Add-Check "M8-failed-device-triage" "FAIL" "Missing failed-device triage evidence schema faz22.1680.gpo-msi.failed-device-triage.v1"
        return
    }
    $d = $docs[0].data
    if (-not (Same-Text (Get-Field $d "status") "PASS")) {
        Add-Check "M8-failed-device-triage" "FAIL" "Failed-device triage status is not PASS"
    } elseif (-not [bool](Get-Field $d "silentFailureGuard")) {
        Add-Check "M8-failed-device-triage" "FAIL" "silentFailureGuard is not true"
    } elseif ([string]::IsNullOrWhiteSpace((Normalize-String (Get-Field $d "triageSurface")))) {
        Add-Check "M8-failed-device-triage" "FAIL" "triageSurface is missing"
    } else {
        Add-Check "M8-failed-device-triage" "PASS" "Failed-device triage surface is recorded and fail-closed" @{
            triageSurface = Get-Field $d "triageSurface"
            observedFailures = Get-Field $d "observedFailures"
        }
    }
}

Assert-HexSha256 -Name "ExpectedMsiSha256" -Value $ExpectedMsiSha256
Assert-HexSha256 -Name "ExpectedMsiManifestSha256" -Value $ExpectedMsiManifestSha256

if (-not (Test-Path $EvidenceRoot)) {
    throw "EvidenceRoot not found: $EvidenceRoot"
}

$resolvedRoot = (Resolve-Path $EvidenceRoot).Path
$docs = @(Read-JsonEvidence -Root $resolvedRoot)

Add-Check "evidence-root" "INFO" "Loaded $($docs.Count) JSON evidence document(s)" $resolvedRoot

Invoke-SecretScan -Root $resolvedRoot -MaxBytes $MaxTextScanBytes
Validate-BundleManifest -Docs $docs -ExplicitPath $BundleManifestPath
Validate-Targeting -Docs $docs
Validate-InstallEvidence -Docs $docs
Validate-VerifyEvidence -Docs $docs
Validate-WavePreflight -Docs $docs
Validate-RolloutCollector -Docs $docs
Validate-RollbackEvidence -Docs $docs
Validate-FailureTriage -Docs $docs

[int]$failCount = @($script:VerifierChecks | Where-Object { $_.status -eq "FAIL" }).Count
[int]$warnCount = @($script:VerifierChecks | Where-Object { $_.status -eq "WARN" }).Count
$overall = if ($failCount -gt 0) { "FAIL" } elseif ($warnCount -gt 0) { "PASS-WITH-WARN" } else { "PASS" }

$result = [pscustomobject]@{
    schema = "faz22.1680.gpo-msi.evidence-verifier.v1"
    generatedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    evidenceRoot = $resolvedRoot
    expected = [pscustomobject]@{
        msiSha256 = $ExpectedMsiSha256.ToLowerInvariant()
        msiManifestSha256 = $ExpectedMsiManifestSha256.ToLowerInvariant()
        signerThumbprint = $ExpectedSignerThumbprint
        minimumAgentVersion = $ExpectedMinimumAgentVersion
        apiHost = $ExpectedApiHost
        requiredDeviceCount = $RequiredDeviceCount
        requiredRollbackDeviceCount = $RequiredRollbackDeviceCount
    }
    overall = $overall
    failCount = $failCount
    warnCount = $warnCount
    checks = @($script:VerifierChecks)
    acceptanceBoundary = [pscustomobject]@{
        verifiesEvidencePackageOnly = $true
        mutatesAdGpoEndpointsBackendOrGithub = $false
        closesIssue1680 = $false
        requiresHumanOrDomainOpsExecutionForLiveEvidence = $true
    }
}

if ($Json) {
    $result | ConvertTo-Json -Depth 10
} else {
    Write-Host "GPO/MSI rollout evidence verifier -> $overall (FAIL=$failCount WARN=$warnCount)"
    $script:VerifierChecks | Select-Object name, status, detail | Format-Table -AutoSize | Out-String | Write-Host
}

if ($ExitCodeOnFail -and $failCount -gt 0) { exit 1 }
exit 0
