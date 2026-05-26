# enroll-endpoint-agent-cert.ps1 — Faz 22.3 GPO startup script for AD CS machine cert
#
# Source-of-truth: docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md (PR #1078 MERGED 2026-05-26)
# Iter-4 F2 + iter-5 F1 + iter-6 F1 absorb:
#   - RSAT-free DirectorySearcher (built-in .NET LDAP)
#   - certreq 3-step flow (-new + -submit + -accept)
#   - LocalMachine\My store (machine cert, NOT CurrentUser)
#   - Idempotent: existing cert SAN URI match → exit 0
#   - URI:adcomputer:{objectGUID} custom extension via certreq inf
#
# Deployment: SYSVOL via GPO startup script + GPO schedule task (daily renewal)
# Trigger:    Computer boot + daily 03:00 schedule task
# Context:    SYSTEM account (GPO startup runs as NT AUTHORITY\SYSTEM)
# Idempotent: existing valid cert (SAN URI match + not expired + not near-expiry) → skip
#
# Cross-AI peer review: Codex 019e667f-98a5-7980-8f80-613fc1a1ed82 iter-7 AGREE
# Board issue: #1079

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()][string]$CAConfig = "ACIKDC01\ACIK Endpoint CA",
    [Parameter()][string]$Template = "EndpointAgent-MachineCert",
    [Parameter()][string]$LogPath = "$env:ProgramData\faz22.3-enroll-cert.log",
    [Parameter()][int]$NearExpiryDays = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ============================================================================
# Logging
# ============================================================================

function Write-EnrollLog {
    param([string]$Level, [string]$Message)
    $timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffK")
    $line = "[$timestamp] [$Level] [$env:COMPUTERNAME] $Message"
    Add-Content -Path $LogPath -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    # GPO startup runs in SYSTEM context (no console); rely on log file
}

# ============================================================================
# Step 1: Lookup AD computer object via DirectorySearcher (RSAT-free, iter-5 F1)
# ============================================================================

function Get-MachineObjectGuid {
    Write-EnrollLog "INFO" "Step 1: DirectorySearcher LDAP query for $env:COMPUTERNAME"

    try {
        $searcher = [System.DirectoryServices.DirectorySearcher]::new()
        $searcher.Filter = "(&(objectClass=computer)(name=$env:COMPUTERNAME))"
        $searcher.PropertiesToLoad.Add("objectGUID") | Out-Null
        $result = $searcher.FindOne()
    } catch {
        Write-EnrollLog "ERROR" "Step 1: DirectorySearcher failed: $($_.Exception.Message)"
        throw "AD lookup failed — is this PC domain-joined? Domain status: $((Get-WmiObject Win32_ComputerSystem).PartOfDomain)"
    }

    if (-not $result) {
        Write-EnrollLog "ERROR" "Step 1: Computer object not found in AD"
        throw "Computer '$env:COMPUTERNAME' not found in AD (DirectorySearcher returned null)"
    }

    $guidBytes = $result.Properties["objectguid"][0]
    $guid = ([System.Guid]::new($guidBytes)).ToString().ToLower()
    Write-EnrollLog "INFO" "Step 1: objectGUID resolved: $guid"
    return $guid
}

# ============================================================================
# Step 2: Idempotent check — existing valid cert with matching SAN URI
# ============================================================================

function Test-ExistingValidCert {
    param([string]$Guid, [string]$DnsName)

    Write-EnrollLog "INFO" "Step 2: Idempotent check — existing valid cert for SAN URI adcomputer:$Guid"

    $existing = Get-ChildItem Cert:\LocalMachine\My | Where-Object {
        $_.Subject -like "CN=$DnsName*"
    }

    foreach ($cert in $existing) {
        # Check SAN extension contains URI:adcomputer:<guid>
        $sanExt = $cert.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" }
        if (-not $sanExt) { continue }

        $sanFormatted = $sanExt.Format($false)
        if ($sanFormatted -notmatch "URL=adcomputer:$Guid") { continue }

        # Check not expired + not near-expiry
        $now = Get-Date
        $daysToExpiry = ($cert.NotAfter - $now).TotalDays

        if ($daysToExpiry -le 0) {
            Write-EnrollLog "WARN" "Step 2: Existing cert EXPIRED ($($cert.Thumbprint), NotAfter=$($cert.NotAfter)); will mint new"
            continue
        }

        if ($daysToExpiry -le $NearExpiryDays) {
            Write-EnrollLog "WARN" "Step 2: Existing cert near-expiry ($($cert.Thumbprint), days=$daysToExpiry); will mint new for rollover"
            continue
        }

        Write-EnrollLog "INFO" "Step 2: VALID existing cert found ($($cert.Thumbprint), days_to_expiry=$daysToExpiry); idempotent skip"
        return $true
    }

    Write-EnrollLog "INFO" "Step 2: No valid cert found; proceed to mint new"
    return $false
}

# ============================================================================
# Step 3: certreq 3-step flow (iter-5 F1 absorb — valid syntax)
# ============================================================================

function Invoke-CertReqEnrollment {
    param([string]$Guid, [string]$DnsName)

    Write-EnrollLog "INFO" "Step 3: certreq 3-step flow start (template=$Template, CA=$CAConfig)"

    $infFile = "$env:TEMP\endpoint-agent-cert-$(Get-Random).inf"
    $reqFile = "$env:TEMP\endpoint-agent-cert-$(Get-Random).req"
    $cerFile = "$env:TEMP\endpoint-agent-cert-$(Get-Random).cer"

    $inf = @"
[NewRequest]
Subject = "CN=$DnsName"
KeySpec = 1
KeyLength = 2048
Exportable = FALSE
MachineKeySet = TRUE
ProviderName = "Microsoft Platform Crypto Provider"
RequestType = PKCS10

[RequestAttributes]
CertificateTemplate = "$Template"

[Extensions]
2.5.29.17 = "{text}"
_continue_ = "dns=$DnsName&"
_continue_ = "URL=adcomputer:$Guid"
"@

    try {
        $inf | Out-File -FilePath $infFile -Encoding ASCII -Force
        Write-EnrollLog "INFO" "Step 3: INF file written: $infFile"

        # Step 3a: -new (create request from INF)
        Write-EnrollLog "INFO" "Step 3a: certreq -new $infFile $reqFile"
        if ($PSCmdlet.ShouldProcess("certreq -new", "Create request from INF")) {
            $newOutput = & certreq.exe -new -q -f $infFile $reqFile 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Write-EnrollLog "ERROR" "Step 3a: certreq -new failed (exit=$LASTEXITCODE): $newOutput"
                throw "certreq -new failed"
            }
            Write-EnrollLog "INFO" "Step 3a: REQ file created: $reqFile"
        }

        # Step 3b: -submit (submit to CA, get cert)
        Write-EnrollLog "INFO" "Step 3b: certreq -submit -config '$CAConfig' $reqFile $cerFile"
        if ($PSCmdlet.ShouldProcess("certreq -submit", "Submit request to CA")) {
            $submitOutput = & certreq.exe -submit -q -f -config $CAConfig $reqFile $cerFile 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Write-EnrollLog "ERROR" "Step 3b: certreq -submit failed (exit=$LASTEXITCODE): $submitOutput"
                throw "certreq -submit failed — CA reachability + template permission check"
            }
            Write-EnrollLog "INFO" "Step 3b: CER file received: $cerFile"
        }

        # Step 3c: -accept (install cert to LocalMachine\My with private key binding)
        Write-EnrollLog "INFO" "Step 3c: certreq -accept -machine $cerFile"
        if ($PSCmdlet.ShouldProcess("certreq -accept", "Install cert to LocalMachine\My")) {
            $acceptOutput = & certreq.exe -accept -q -f -machine $cerFile 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                Write-EnrollLog "ERROR" "Step 3c: certreq -accept failed (exit=$LASTEXITCODE): $acceptOutput"
                throw "certreq -accept failed — private key binding issue"
            }
            Write-EnrollLog "INFO" "Step 3c: Cert installed to LocalMachine\My (private key TPM-bound)"
        }

        # Verify cert exists in store post-install
        $installedCert = Get-ChildItem Cert:\LocalMachine\My | Where-Object {
            $_.Subject -eq "CN=$DnsName" -and
            ($_.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" -and ($_.Format($false) -match "URL=adcomputer:$Guid") })
        } | Sort-Object NotBefore -Descending | Select-Object -First 1

        if ($installedCert) {
            Write-EnrollLog "INFO" "Step 3: Cert installed and verified — Thumbprint=$($installedCert.Thumbprint), NotAfter=$($installedCert.NotAfter)"
        } else {
            Write-EnrollLog "ERROR" "Step 3: Post-install verify failed — cert not found in LocalMachine\My with matching SAN URI"
            throw "Cert install verify failed"
        }

    } finally {
        Remove-Item $infFile, $reqFile, $cerFile -Force -ErrorAction SilentlyContinue
    }
}

# ============================================================================
# Main flow
# ============================================================================

try {
    Write-EnrollLog "INFO" "============================================================================"
    Write-EnrollLog "INFO" "enroll-endpoint-agent-cert.ps1 START"
    Write-EnrollLog "INFO" "Computer: $env:COMPUTERNAME"
    Write-EnrollLog "INFO" "Domain: $((Get-WmiObject Win32_ComputerSystem).Domain)"
    Write-EnrollLog "INFO" "Template: $Template | CA: $CAConfig | NearExpiryDays: $NearExpiryDays"
    Write-EnrollLog "INFO" "WhatIf: $($PSCmdlet.MyInvocation.BoundParameters['WhatIf'].IsPresent)"

    # Pre-check: domain-joined?
    $cs = Get-WmiObject Win32_ComputerSystem
    if (-not $cs.PartOfDomain) {
        Write-EnrollLog "ERROR" "PC not domain-joined; AD CS auto-enrollment requires domain membership"
        throw "Not domain-joined (this is 22.3 mass deployment scope; 22.2.A non-domain uses different identity model)"
    }

    $dnsName = "$env:COMPUTERNAME.$($cs.Domain)"
    Write-EnrollLog "INFO" "DNS Name: $dnsName"

    # Step 1: AD computer object lookup
    $guid = Get-MachineObjectGuid

    # Step 2: Idempotent check
    if (Test-ExistingValidCert -Guid $guid -DnsName $dnsName) {
        Write-EnrollLog "INFO" "Idempotent skip — valid existing cert"
        Write-EnrollLog "INFO" "============================================================================"
        exit 0
    }

    # Step 3: certreq 3-step enrollment
    Invoke-CertReqEnrollment -Guid $guid -DnsName $dnsName

    Write-EnrollLog "INFO" "Enrollment COMPLETE — cert ready for agent --auto-enroll mTLS"
    Write-EnrollLog "INFO" "============================================================================"
    exit 0

} catch {
    Write-EnrollLog "ERROR" "FATAL: $($_.Exception.Message)"
    Write-EnrollLog "ERROR" "Stack: $($_.ScriptStackTrace)"
    Write-EnrollLog "ERROR" "============================================================================"
    exit 1
}
