# ad-cs-preflight.ps1 — Faz 22.3 AD CS infrastructure preflight (DC operator)
#
# Source-of-truth: docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md (merged 2026-05-26 PR #1078)
# Runbook: docs/runbooks/RB-faz22.3-ad-cs-setup.md
# Board issue: #1079
# Cross-AI peer review chain: 12 finding F1-F5 + F1-F4 + F1-F3 absorbed (Codex 019e667f)
#
# Purpose: DC üzerinde AD CS infrastructure'ı initialize edip Faz 22.3 mass
# deployment için hazır hale getirmek. Operator (IT) çalıştırır; interactive
# prompt'larla onay alır; her adım idempotent + log basar.
#
# Prerequisites (operator manual check before run):
# - Windows Server 2019+ DC (Enterprise Root CA gerek)
# - Domain Admin + Enterprise Admin yetkisi
# - TPM 2.0 chip (Microsoft Platform Crypto Provider TPM-backed key için)
# - DC disk free > 5 GB (CRL + cert DB için)
# - Backup taken (system state + AD)
#
# Usage:
#   .\ad-cs-preflight.ps1                       # interactive (default)
#   .\ad-cs-preflight.ps1 -WhatIf               # dry-run, show mutations
#   .\ad-cs-preflight.ps1 -Force                # skip confirmations
#   .\ad-cs-preflight.ps1 -Step <StepName>      # run only specific step
#
# Steps:
#   1. Install ADCS-Cert-Authority Windows feature
#   2. Initialize Enterprise Root CA "ACIK Endpoint CA" (TPM-protected key)
#   3. Create "EndpointAgent-MachineCert" cert template
#   4. Create "EndpointAgent-CodeSigning" cert template
#   5. Publish templates to enterprise CA
#   6. Configure CRL Distribution Points (HTTP + LDAP)
#   7. Configure AutoEnrollment GPO (Computer Configuration)
#   8. Deploy Enroll-EndpointAgentCert.ps1 GPO startup script
#   9. Deploy Schedule Task GPO (daily renewal trigger)
#  10. Verify all artifacts created (P0-23 baseline check)

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()][string]$CAName = "ACIK Endpoint CA",
    [Parameter()][string]$Domain = "acik.local",
    [Parameter()][string]$TemplateBase = "Computer",
    [Parameter()][string]$MachineCertTemplate = "EndpointAgent-MachineCert",
    [Parameter()][string]$CodeSigningTemplate = "EndpointAgent-CodeSigning",
    [Parameter()][string]$GpoNameMachineCert = "Faz22.3-EndpointAgent-MachineCertEnroll",
    [Parameter()][string]$GpoNameSoftwareInstall = "Faz22.3-EndpointAgent-MsiInstall",
    [Parameter()][string]$SysvolShare = "\\$(([System.Net.Dns]::GetHostName()))\sysvol\$Domain\scripts\faz22-mass-deployment",
    [Parameter()][string[]]$CrlHttpUrls = @("http://crl.acik.local/CertEnroll/<CaName><CRLNameSuffix><DeltaCRLAllowed>.crl"),
    [Parameter()][ValidateSet("All", "Feature", "CaInit", "TemplateMachine", "TemplateCodeSign", "Publish", "Crl", "AutoEnroll", "GpoStartup", "GpoSchedule", "Verify")][string]$Step = "All",
    [Parameter()][switch]$Force,
    [Parameter()][string]$LogPath = "$env:ProgramData\faz22.3-ad-cs-preflight.log"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ============================================================================
# Logging helpers
# ============================================================================

function Write-StepLog {
    param([string]$Level, [string]$Message)
    $timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss.fffK")
    $line = "[$timestamp] [$Level] $Message"
    Write-Host $line -ForegroundColor $(if ($Level -eq "ERROR") { "Red" } elseif ($Level -eq "WARN") { "Yellow" } else { "Green" })
    Add-Content -Path $LogPath -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}

function Confirm-Step {
    param([string]$StepName, [string]$Description)
    if ($Force) { return $true }
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "STEP: $StepName" -ForegroundColor Cyan
    Write-Host "$Description" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    $resp = Read-Host "Continue? [Y/n]"
    return ($resp -eq "" -or $resp -match "^[yY]")
}

function Test-Operator-Privilege {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Bu script Administrator yetkisi ile çalıştırılmalı. PowerShell as Administrator açın."
    }
    Write-StepLog "INFO" "Administrator privilege: OK ($($current.Name))"
}

# ============================================================================
# Step 1: Install ADCS-Cert-Authority Windows feature
# ============================================================================

function Install-AdcsFeature {
    Write-StepLog "INFO" "Step 1: ADCS-Cert-Authority Windows feature install check"

    $feature = Get-WindowsFeature -Name "ADCS-Cert-Authority"
    if ($feature.Installed) {
        Write-StepLog "INFO" "Step 1: ADCS-Cert-Authority already installed (skip)"
        return
    }

    if (-not (Confirm-Step "Install AD CS Feature" "Install-WindowsFeature ADCS-Cert-Authority -IncludeManagementTools")) {
        Write-StepLog "WARN" "Step 1: User declined; skipping"
        return
    }

    if ($PSCmdlet.ShouldProcess("ADCS-Cert-Authority feature", "Install")) {
        Install-WindowsFeature -Name "ADCS-Cert-Authority" -IncludeManagementTools | Out-Null
        Write-StepLog "INFO" "Step 1: ADCS-Cert-Authority installed; reboot may be required"
    }
}

# ============================================================================
# Step 2: Initialize Enterprise Root CA "ACIK Endpoint CA"
# ============================================================================

function Initialize-EndpointCA {
    Write-StepLog "INFO" "Step 2: Enterprise Root CA initialize check"

    # Check if CA already initialized
    $caExists = $false
    try {
        $existingCa = certutil -getconfig 2>&1 | Out-String
        if ($existingCa -match $CAName) {
            $caExists = $true
        }
    } catch {
        # ignore - CA not initialized
    }

    if ($caExists) {
        Write-StepLog "INFO" "Step 2: CA '$CAName' already initialized (skip)"
        return
    }

    if (-not (Confirm-Step "Initialize Enterprise Root CA" "Install-AdcsCertificationAuthority -CAType EnterpriseRootCA -CACommonName '$CAName' -KeyLength 4096 -HashAlgorithm SHA256 -CryptoProviderName 'Microsoft Platform Crypto Provider' (TPM-backed)")) {
        Write-StepLog "WARN" "Step 2: User declined; skipping"
        return
    }

    if ($PSCmdlet.ShouldProcess("$CAName", "Initialize Enterprise Root CA")) {
        Install-AdcsCertificationAuthority `
            -CAType EnterpriseRootCA `
            -CACommonName $CAName `
            -KeyLength 4096 `
            -HashAlgorithm SHA256 `
            -CryptoProviderName "Microsoft Platform Crypto Provider" `
            -ValidityPeriod Years `
            -ValidityPeriodUnits 10 `
            -Force | Out-Null
        Write-StepLog "INFO" "Step 2: CA '$CAName' initialized; TPM-backed key created"
    }
}

# ============================================================================
# Step 3: Create "EndpointAgent-MachineCert" cert template
# ============================================================================
#
# NOTE: AD CS cert templates are stored in AD as objects under
# CN=Certificate Templates,CN=Public Key Services,CN=Services,CN=Configuration,DC=...
# Templates are created via certtmpl.msc MMC; programmatic create is complex.
#
# Pattern: Duplicate "Computer" template + modify properties:
# - Subject Name: Build from AD (CN = DNSHostName)
# - Subject Alt Name: Build from AD (DNS name) — custom URI:adcomputer added via GPO startup script (iter-5 F1)
# - Key Usage: Digital Signature + Key Encipherment
# - EKU: Client Authentication (1.3.6.1.5.5.7.3.2)
# - Cryptography: "Microsoft Platform Crypto Provider" (TPM-only)
# - Issuance: TPM attestation required

function Create-MachineCertTemplate {
    Write-StepLog "INFO" "Step 3: Machine cert template '$MachineCertTemplate' setup"

    Write-StepLog "WARN" "Step 3: Cert template creation requires certtmpl.msc MMC (programmatic AD object creation complex)"
    Write-StepLog "INFO" "Step 3: Operator manual action required:"
    Write-Host @"

  MANUAL STEP (operator):
  1. mmc.exe -> File -> Add/Remove Snap-in -> 'Certificate Templates' -> Add
  2. Right-click 'Computer' template -> Duplicate Template
  3. Properties tab:
     - General: Display name = '$MachineCertTemplate' (template name auto = EndpointAgentMachineCert)
     - Compatibility: Windows Server 2016 + Windows 10
     - Cryptography: Provider Category = 'Key Storage Provider'; Provider = 'Microsoft Platform Crypto Provider' (TPM-only)
     - Request Handling: Purpose = Signature and encryption; Key size minimum = 2048
     - Subject Name: 'Build from this Active Directory information':
                    Subject name format = 'Common name'
                    Include this information in alternate subject name: DNS name (UPN optional)
     - Extensions: Application Policies = 'Client Authentication' (1.3.6.1.5.5.7.3.2)
     - Issuance Requirements: 'This number of authorized signatures: 0'; ensure TPM attestation can be required (Windows Server 2016+)
     - Security: Domain Computers = 'Read' + 'Autoenroll' (not just 'Enroll'); add 'Authenticated Users' for read
  4. OK to save

  After saving the template, run this script again with -Step Publish to publish
  the template to the CA (or run that step here in a moment).

  See ADR-0029 Katman 1 (lines 121-160) for detailed template properties.
"@ -ForegroundColor Yellow

    $resp = Read-Host "Did you create the template '$MachineCertTemplate' via MMC? [y/N]"
    if ($resp -notmatch "^[yY]") {
        Write-StepLog "WARN" "Step 3: Template not confirmed; mass deploy NOT ready until template exists"
        return
    }
    Write-StepLog "INFO" "Step 3: Operator confirmed template '$MachineCertTemplate' created"
}

# ============================================================================
# Step 4: Create "EndpointAgent-CodeSigning" cert template
# ============================================================================

function Create-CodeSigningCertTemplate {
    Write-StepLog "INFO" "Step 4: Code signing cert template '$CodeSigningTemplate' setup"

    Write-Host @"

  MANUAL STEP (operator):
  1. mmc.exe certtmpl.msc -> Duplicate 'Code Signing' template (or 'User' if Code Signing not in default list)
  2. Properties:
     - General: Display name = '$CodeSigningTemplate'
     - Compatibility: Windows Server 2016 + Windows 10
     - Cryptography: TPM provider OK; Hash SHA256
     - Subject Name: 'Supply in the request' (manuel certreq)
     - Extensions: Application Policies = 'Code Signing' (1.3.6.1.5.5.7.3.3)
     - Issuance Requirements: 'This number of authorized signatures: 1' (CA Manager approval — operator manual sign-off pipeline)
     - Security: agent-team-restricted group 'Read' + 'Enroll' (NOT 'Autoenroll')
  3. OK to save

  Bu template R17 HARD RULE compliance için: private key TPM/HSM-backed Windows
  signing runner'da kalır; GitHub Actions PFX YOK.
"@ -ForegroundColor Yellow

    $resp = Read-Host "Did you create the template '$CodeSigningTemplate' via MMC? [y/N]"
    if ($resp -notmatch "^[yY]") {
        Write-StepLog "WARN" "Step 4: Code signing template not confirmed"
        return
    }
    Write-StepLog "INFO" "Step 4: Operator confirmed code signing template created"
}

# ============================================================================
# Step 5: Publish templates to enterprise CA
# ============================================================================

function Publish-CertTemplates {
    Write-StepLog "INFO" "Step 5: Publish templates to enterprise CA"

    if (-not (Confirm-Step "Publish Cert Templates" "certutil -setcatemplates +$MachineCertTemplate,$CodeSigningTemplate")) {
        return
    }

    if ($PSCmdlet.ShouldProcess("Enterprise CA", "Publish templates $MachineCertTemplate + $CodeSigningTemplate")) {
        try {
            $result = certutil -setcatemplates "+$MachineCertTemplate,$CodeSigningTemplate" 2>&1 | Out-String
            Write-StepLog "INFO" "Step 5: certutil output:`n$result"
        } catch {
            Write-StepLog "ERROR" "Step 5: Template publish failed: $($_.Exception.Message)"
            throw
        }
    }
}

# ============================================================================
# Step 6: Configure CRL Distribution Points
# ============================================================================

function Configure-CrlDistribution {
    Write-StepLog "INFO" "Step 6: CRL Distribution Points config"

    if (-not (Confirm-Step "Configure CRL DPs" "Add HTTP CRL URL: $($CrlHttpUrls -join ', ')")) {
        return
    }

    if ($PSCmdlet.ShouldProcess("CA CRL config", "Add HTTP CRL distribution points")) {
        # AD CS CRL Distribution Points (CDP) are managed via certutil + registry
        foreach ($url in $CrlHttpUrls) {
            try {
                # Add to existing CDPs (don't replace; preserves default LDAP)
                $current = certutil -getreg ca\CRLPublicationURLs 2>&1 | Out-String
                if ($current -notmatch [regex]::Escape($url)) {
                    Write-StepLog "INFO" "Step 6: Adding CRL URL: $url"
                    # Note: actual CDP config via Certificate Authority MMC -> CA Properties -> Extensions tab
                    # Programmatic via certutil -setreg complex; operator manual recommended
                    Write-Host "  MANUAL STEP: Add via certsrv.msc -> Properties -> Extensions tab -> Add: $url" -ForegroundColor Yellow
                } else {
                    Write-StepLog "INFO" "Step 6: CRL URL already configured: $url"
                }
            } catch {
                Write-StepLog "ERROR" "Step 6: CRL DP config failed: $($_.Exception.Message)"
            }
        }

        # IIS site for HTTP CRL distribution (operator-bound)
        Write-Host @"

  MANUAL STEP (operator): IIS site for HTTP CRL publishing
  1. Install-WindowsFeature Web-Server -IncludeManagementTools (if not already)
  2. New IIS site 'crl.acik.local' -> physical path C:\inetpub\crl
  3. Copy CRL files: certutil -getconfig | findstr /i ConfigString
                     CRL output: %SystemRoot%\System32\CertSrv\CertEnroll\*.crl
                     -> sync to C:\inetpub\crl via scheduled task or symlink
  4. DNS: A record crl.acik.local -> DC IP
  5. Test: curl http://crl.acik.local/CertEnroll/...crl from corp PC

  Eski IIS CRL endpoint hâlâ varsa skip; R16 P0-14 reachability check için gerekli.
"@ -ForegroundColor Yellow

        $resp = Read-Host "CRL HTTP IIS site ready? [y/N/skip]"
        if ($resp -match "^[yY]") {
            Write-StepLog "INFO" "Step 6: CRL HTTP IIS confirmed"
        }
    }
}

# ============================================================================
# Step 7: Configure AutoEnrollment GPO (Computer Configuration)
# ============================================================================

function Configure-AutoEnrollmentGpo {
    Write-StepLog "INFO" "Step 7: AutoEnrollment GPO config"

    Import-Module GroupPolicy -ErrorAction SilentlyContinue

    if (-not (Confirm-Step "Create AutoEnrollment GPO" "GPO: '$GpoNameMachineCert' linked to OU containing pilot PCs")) {
        return
    }

    # Check if GPO exists
    $gpo = $null
    try {
        $gpo = Get-GPO -Name $GpoNameMachineCert -ErrorAction SilentlyContinue
    } catch { }

    if (-not $gpo) {
        if ($PSCmdlet.ShouldProcess($GpoNameMachineCert, "Create GPO")) {
            $gpo = New-GPO -Name $GpoNameMachineCert -Comment "Faz 22.3 AD CS AutoEnrollment + GPO startup script for EndpointAgent machine cert (ADR-0029)"
            Write-StepLog "INFO" "Step 7: Created GPO: $($gpo.DisplayName) (Id=$($gpo.Id))"
        }
    } else {
        Write-StepLog "INFO" "Step 7: GPO already exists: $($gpo.DisplayName) (Id=$($gpo.Id))"
    }

    # Set AutoEnrollment policy via registry pol (Computer Config > Windows Settings > Security > Public Key Policies)
    Write-Host @"

  MANUAL STEP (operator): AutoEnrollment GPO policy enable
  GPO: $GpoNameMachineCert
  Path: Computer Configuration > Windows Settings > Security Settings > Public Key Policies >
        Certificate Services Client - Auto-Enrollment
  Set:  Enabled
        [x] Renew expired certificates, update pending certificates, and remove revoked certificates
        [x] Update certificates that use certificate templates

  Bu BUILT-IN AD cert renewal pattern. URI SAN extension için ek GPO startup script (Step 8).
"@ -ForegroundColor Yellow
}

# ============================================================================
# Step 8: Deploy Enroll-EndpointAgentCert.ps1 GPO startup script
# ============================================================================

function Deploy-EnrollGpoStartup {
    Write-StepLog "INFO" "Step 8: GPO startup script deploy ($SysvolShare\enroll-endpoint-agent-cert.ps1)"

    if (-not (Confirm-Step "Deploy GPO Startup Script" "Copy enroll-endpoint-agent-cert.ps1 to SYSVOL + GPO link as Computer Startup Script")) {
        return
    }

    # Ensure SYSVOL target directory exists
    if (-not (Test-Path $SysvolShare)) {
        if ($PSCmdlet.ShouldProcess($SysvolShare, "Create SYSVOL faz22-mass-deployment directory")) {
            New-Item -Path $SysvolShare -ItemType Directory -Force | Out-Null
            Write-StepLog "INFO" "Step 8: Created SYSVOL directory: $SysvolShare"
        }
    }

    # Source script location (relative to this preflight script)
    $scriptDir = $PSScriptRoot
    $srcScript = Join-Path $scriptDir "enroll-endpoint-agent-cert.ps1"

    if (-not (Test-Path $srcScript)) {
        Write-StepLog "ERROR" "Step 8: Source script not found: $srcScript"
        Write-Host "  This script should be deployed alongside ad-cs-preflight.ps1" -ForegroundColor Red
        return
    }

    if ($PSCmdlet.ShouldProcess($SysvolShare, "Copy enroll-endpoint-agent-cert.ps1")) {
        Copy-Item -Path $srcScript -Destination "$SysvolShare\enroll-endpoint-agent-cert.ps1" -Force
        Write-StepLog "INFO" "Step 8: Copied script to SYSVOL"
    }

    Write-Host @"

  MANUAL STEP (operator): GPO startup script link
  GPO: $GpoNameMachineCert
  Path: Computer Configuration > Policies > Windows Settings > Scripts (Startup/Shutdown) > Startup
  Add:  PowerShell Scripts tab -> Add ->
        Script Name: \\$Domain\sysvol\$Domain\scripts\faz22-mass-deployment\enroll-endpoint-agent-cert.ps1
        Script Parameters: (none — script reads $env:COMPUTERNAME)
  Run script options: For this GPO, run scripts in the following order: PowerShell scripts first

  Bu script DirectorySearcher ile RSAT-free objectGUID query + certreq 3-step flow
  (iter-5 F1 absorb). Idempotent: existing cert SAN URI match olsa exit 0.

  GPO link target: OU containing pilot PCs (5 PC initial, ramp 50 → 800)
  Initial OU: OU=EndpointPilot,DC=acik,DC=local
"@ -ForegroundColor Yellow
}

# ============================================================================
# Step 9: Deploy Schedule Task GPO (daily renewal trigger)
# ============================================================================

function Deploy-ScheduleTaskGpo {
    Write-StepLog "INFO" "Step 9: Schedule Task GPO config (daily renewal at 03:00)"

    Write-Host @"

  MANUAL STEP (operator): Schedule Task GPO
  GPO: $GpoNameMachineCert (same GPO as Step 7-8)
  Path: Computer Configuration > Preferences > Control Panel Settings > Scheduled Tasks
  Action: Create -> 'Scheduled Task (At least Windows 7)'
  General tab:
    Action: Update
    Name: Faz22.3-EndpointAgentCertRenewal
    When running the task, use the following user account: NT AUTHORITY\SYSTEM
    Run with highest privileges: checked
    Configure for: Windows 10
  Triggers tab:
    Daily, Start: 03:00, Recur every: 1 days
  Actions tab:
    Action: Start a program
    Program/script: powershell.exe
    Arguments: -ExecutionPolicy Bypass -NoProfile -File \\$Domain\sysvol\$Domain\scripts\faz22-mass-deployment\enroll-endpoint-agent-cert.ps1
  Settings tab:
    Allow task to be run on demand: checked
    Run task as soon as possible after a scheduled start is missed: checked

  Bu renewal pattern: enroll-endpoint-agent-cert.ps1 idempotent (existing cert + valid >30 gün
  ise exit 0; expired/missing/near-expiry ise certreq mint). Cert near-expiry için F2 R24
  bounded grace formula uygulanır (backend tarafı).
"@ -ForegroundColor Yellow
}

# ============================================================================
# Step 10: Verify all artifacts created (P0-23 baseline check)
# ============================================================================

function Verify-Artifacts {
    Write-StepLog "INFO" "Step 10: Final verification (P0-1..P0-23 baseline)"

    $results = @{}

    # CA initialized check
    try {
        $caInfo = certutil -getconfig 2>&1 | Out-String
        $results["CA Initialized"] = if ($caInfo -match $CAName) { "OK" } else { "FAIL" }
    } catch {
        $results["CA Initialized"] = "FAIL: $($_.Exception.Message)"
    }

    # Templates published
    try {
        $templates = certutil -catemplates 2>&1 | Out-String
        $results["Machine Cert Template"] = if ($templates -match $MachineCertTemplate) { "OK" } else { "FAIL (publish via Step 5)" }
        $results["Code Signing Template"] = if ($templates -match $CodeSigningTemplate) { "OK" } else { "FAIL (publish via Step 5)" }
    } catch {
        $results["Machine Cert Template"] = "FAIL: $($_.Exception.Message)"
    }

    # GPO exists
    try {
        $gpo = Get-GPO -Name $GpoNameMachineCert -ErrorAction SilentlyContinue
        $results["AutoEnrollment GPO"] = if ($gpo) { "OK (Id=$($gpo.Id))" } else { "FAIL (create via Step 7)" }
    } catch {
        $results["AutoEnrollment GPO"] = "FAIL: $($_.Exception.Message)"
    }

    # SYSVOL script deployed
    $sysvolScript = Join-Path $SysvolShare "enroll-endpoint-agent-cert.ps1"
    $results["SYSVOL Script"] = if (Test-Path $sysvolScript) { "OK ($sysvolScript)" } else { "FAIL (deploy via Step 8)" }

    # Print results
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host " VERIFICATION RESULTS" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    foreach ($key in $results.Keys | Sort-Object) {
        $val = $results[$key]
        $color = if ($val -like "OK*") { "Green" } else { "Red" }
        Write-Host ("  {0,-30} {1}" -f $key, $val) -ForegroundColor $color
    }
    Write-Host "════════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""

    Write-Host @"

  NEXT STEPS (operator action):
  1. Link GPO '$GpoNameMachineCert' to OU=EndpointPilot,DC=acik,DC=local
  2. Add 5 pilot computers to OU=EndpointPilot,DC=acik,DC=local
  3. gpupdate /force on pilot PC (or wait 90-120 min for GPO refresh)
  4. Wait for GPO startup script + AutoEnrollment to mint machine cert
  5. Verify on pilot PC: run verify-machine-cert.ps1 (P0-23 check)
  6. Phase 0 P0-1..P0-23 evidence collection (RB-faz22.3-ad-cs-setup.md §3)
  7. Backend mTLS endpoint deploy ready → P0-13 ingress mTLS passthrough verify
  8. MSI WiX build + AD CS signing → ready for GPO Software Installation deploy

  Cumulative chain: ADR-0029 §"Acceptance gates" + RB-faz22.3-ad-cs-setup.md
  Cross-AI peer review: Codex 019e667f iter-7 AGREE (PR #1078 MERGED 2026-05-26)
"@ -ForegroundColor Cyan

    Write-StepLog "INFO" "Step 10: Verification complete"
}

# ============================================================================
# Main execution flow
# ============================================================================

try {
    Test-Operator-Privilege

    Write-StepLog "INFO" "============================================================================"
    Write-StepLog "INFO" "Faz 22.3 AD CS Preflight — Mass Deployment Infrastructure Setup"
    Write-StepLog "INFO" "ADR-0029 (PR #1078 MERGED 2026-05-26) Plan A owner-approved"
    Write-StepLog "INFO" "Step: $Step | WhatIf: $($PSCmdlet.MyInvocation.BoundParameters['WhatIf'].IsPresent) | Force: $Force"
    Write-StepLog "INFO" "Log: $LogPath"
    Write-StepLog "INFO" "============================================================================"

    if ($Step -eq "All" -or $Step -eq "Feature") { Install-AdcsFeature }
    if ($Step -eq "All" -or $Step -eq "CaInit") { Initialize-EndpointCA }
    if ($Step -eq "All" -or $Step -eq "TemplateMachine") { Create-MachineCertTemplate }
    if ($Step -eq "All" -or $Step -eq "TemplateCodeSign") { Create-CodeSigningCertTemplate }
    if ($Step -eq "All" -or $Step -eq "Publish") { Publish-CertTemplates }
    if ($Step -eq "All" -or $Step -eq "Crl") { Configure-CrlDistribution }
    if ($Step -eq "All" -or $Step -eq "AutoEnroll") { Configure-AutoEnrollmentGpo }
    if ($Step -eq "All" -or $Step -eq "GpoStartup") { Deploy-EnrollGpoStartup }
    if ($Step -eq "All" -or $Step -eq "GpoSchedule") { Deploy-ScheduleTaskGpo }
    if ($Step -eq "All" -or $Step -eq "Verify") { Verify-Artifacts }

    Write-StepLog "INFO" "============================================================================"
    Write-StepLog "INFO" "ad-cs-preflight.ps1 COMPLETE — operator next steps in Verify-Artifacts output"
    Write-StepLog "INFO" "============================================================================"

} catch {
    Write-StepLog "ERROR" "Script failed: $($_.Exception.Message)"
    Write-StepLog "ERROR" "Stack: $($_.ScriptStackTrace)"
    exit 1
}
