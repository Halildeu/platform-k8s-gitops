# ad-cs-preflight.ps1 — Faz 22.3 AD CS infrastructure preflight (DC operator)
#
# Source-of-truth: docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md (merged 2026-05-26 PR #1078)
# Runbook: docs/runbooks/RB-faz22.3-ad-cs-setup.md
# Board issue: #1079
# Cross-AI peer review chain:
#   - ADR-0029: 12 finding F1-F5 + F1-F4 + F1-F3 absorbed (Codex 019e667f)
#   - PR #1080 iter-1 absorb: F1 (template short name) + F2 (EditFlag SAN2 + CA Manager) +
#     F3 (TPM fail-closed + -AllowSoftwareKey) + F4 (cert prune) + F5 (-Force non-interactive)
#     — Codex 019e6a4a thread
#   - PR #1080 iter-2 absorb (REVISE — 5 finding):
#     * F2-A (HIGH) Template Issuance Requirements: "authorized signatures: 1" YANLIŞTI
#       (Enrollment Agent flow semantiği) → doğru config = "Authorized signatures: 0" +
#       "CA certificate manager approval: ENABLED" (ayrı checkbox; manual sign-off pipeline)
#     * F2-B (HIGH) Pending approval ile enrollment uyumsuz → enroll-endpoint-agent-cert.ps1
#       2-fazlı: Faz 1 (-submit RequestId parse + JSON state persist) + Faz 2 (-retrieve
#       daily; duplicate guard; 7+ gün stale → operator alert)
#     * F2-C (MEDIUM) Enable-EditFlagSan2 restart fail-closed: registry SET + net stop/start
#       exit code + Get-Service Running double-check; Verify-Artifacts ayrı audit field
#     * F3-A (MEDIUM) Initialize-EndpointCA existing CA path: Test-CACryptoProvider ile
#       gerçek CSP/KSP audit; software-keyed CA tespitinde -AllowSoftwareKey yoksa throw
#       (host TPM ready olsa bile CA software CSP olabilir); Verify-Artifacts ayrı row
#     * F1-A (LOW) Runbook §5.1 HRESULT mapping canonical: 0x80094012/0x80094800/0x80092004/
#       0x80094003/0x80094004 her biri tek anlam (önceki versiyon çakışıyordu)
#   - PR #1080 iter-4 absorb (Codex iter-3 REVISE remaining 3 finding — this commit):
#     * F2-B (MEDIUM) iter-4 — Read-PendingRequestsJson fail-CLOSED (corrupt JSON →
#       throw; eski versiyon fail-OPEN olduğu için duplicate submit riski vardı);
#       Write-PendingRequestsJson atomic (temp + Move-Item NTFS rename); cross-process
#       mutex (Global\Faz22.3.PendingRequests) GPO startup + Schedule Task race önler.
#       Recovery runbook: RB-faz22.3-ad-cs-setup.md §5.4.
#       (enroll-endpoint-agent-cert.ps1 değişimi; ad-cs-preflight.ps1 etkilenmez)
#     * F2-C (MEDIUM) Enable-EditFlagSan2 idempotent skip branch: registry flag SET olsa
#       bile servis down olabilir; idempotent path'te de Get-Service CertSvc Running
#       double-check (fail-closed). Önceki versiyon false-pass üretiyordu.
#     * F1-A (MEDIUM) RB-faz22.3-ad-cs-setup.md §5.1 HRESULT tablosu yeniden yazıldı:
#       Win Error sembolik isimler ile AD CS canonical disposition semantik mapping
#       (önceki iter-2 versiyonu birkaç kodun semantiğini hâlâ karıştırıyordu).
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
#   .\ad-cs-preflight.ps1 -Force                # skip ALL confirmations + manual MMC/IIS
#                                               # checkpoints (operator post-run audit gerek).
#                                               # F5 absorb: -Force gerçekten non-interactive;
#                                               # template/CRL Read-Host'ları da skip edilir,
#                                               # WARN log basılır, operator Verify-Artifacts
#                                               # (Step 10) ile post-run sonuçları check etmeli.
#   .\ad-cs-preflight.ps1 -AllowSoftwareKey     # F3 absorb: TPM ready değilse software KSP
#                                               # fallback'e izin (degraded security; R10 risk)
#   .\ad-cs-preflight.ps1 -Step <StepName>      # run only specific step
#
# Steps:
#   1. Install ADCS-Cert-Authority Windows feature
#   2. Initialize Enterprise Root CA "ACIK Endpoint CA" (TPM-protected key — F3 absorb -AllowSoftwareKey fallback)
#   2.5 (F2 absorb) Enable EDITF_ATTRIBUTESUBJECTALTNAME2 + restart CertSvc
#       (custom URI:adcomputer SAN için; CA Manager approval pipeline mandatory)
#   3. Create "EndpointAgentMachineCert" cert template (short name; display "EndpointAgent Machine Cert" — F1 absorb)
#   4. Create "EndpointAgentCodeSigning" cert template (short name; display "EndpointAgent Code Signing")
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
    # F1 absorb (iter-1 HIGH MERGE BLOCKER): AD CS `CertificateTemplate` request
    # attribute SHORT NAME ister (display name değil). AD'de stored short name
    # hyphenless: MMC duplicate sırasında "EndpointAgent Machine Cert" display
    # name verilse de short name `EndpointAgentMachineCert` olur. Aşağıdaki
    # parametreler canonical SHORT NAME (certreq + certutil için kullanılır);
    # display name (MMC visual) ayrı parametre.
    [Parameter()][string]$MachineCertTemplate = "EndpointAgentMachineCert",
    [Parameter()][string]$CodeSigningTemplate = "EndpointAgentCodeSigning",
    [Parameter()][string]$MachineCertDisplayName = "EndpointAgent Machine Cert",
    [Parameter()][string]$CodeSigningDisplayName = "EndpointAgent Code Signing",
    [Parameter()][string]$GpoNameMachineCert = "Faz22.3-EndpointAgent-MachineCertEnroll",
    [Parameter()][string]$GpoNameSoftwareInstall = "Faz22.3-EndpointAgent-MsiInstall",
    [Parameter()][string]$SysvolShare = "\\$(([System.Net.Dns]::GetHostName()))\sysvol\$Domain\scripts\faz22-mass-deployment",
    [Parameter()][string[]]$CrlHttpUrls = @("http://crl.acik.local/CertEnroll/<CaName><CRLNameSuffix><DeltaCRLAllowed>.crl"),
    [Parameter()][ValidateSet("All", "Feature", "CaInit", "EditFlag", "TemplateMachine", "TemplateCodeSign", "Publish", "Crl", "AutoEnroll", "GpoStartup", "GpoSchedule", "Verify")][string]$Step = "All",
    [Parameter()][switch]$Force,
    # F3 absorb (iter-1 MEDIUM): TPM yoksa CA software key fallback'i explicit gerektir.
    # -AllowSoftwareKey verilmediyse + TPM not ready ise script hata atar
    # (fail-closed pattern). Bu flag verildiyse owner approval log'a yazılır.
    [Parameter()][switch]$AllowSoftwareKey,
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
# F3 absorb (iter-1 MEDIUM): TPM/KSP capability check (fail-closed pattern)
# ============================================================================
# Runbook §2.1 TPM 2.0 mandatory diyor ama script CA init aşamasında her durumda
# "Microsoft Platform Crypto Provider" zorluyordu — inconsistent. Bu function CA init
# öncesi TPM Ready check yapar; TPM yoksa -AllowSoftwareKey verilmediyse hata atar
# (fail-closed). Verildiyse owner approval log'a yazılır + software KSP fallback aktif.
# Return: $true = TPM ready, $false = software fallback authorized.

function Test-TpmCapability {
    Write-StepLog "INFO" "F3 absorb: TPM/KSP capability check"

    $tpmReady = $false
    try {
        $tpm = Get-Tpm -ErrorAction Stop
        if ($tpm.TpmPresent -and $tpm.TpmReady -and $tpm.TpmEnabled) {
            Write-StepLog "INFO" "F3: TPM 2.0 present + ready + enabled"
            $tpmReady = $true
        } else {
            Write-StepLog "WARN" ("F3: TPM degraded — TpmPresent={0} TpmReady={1} TpmEnabled={2}" -f $tpm.TpmPresent, $tpm.TpmReady, $tpm.TpmEnabled)
        }
    } catch {
        Write-StepLog "WARN" "F3: Get-Tpm failed (TPM cmdlet yok veya hardware yok): $($_.Exception.Message)"
    }

    # Plus: certutil -csplist içinde Microsoft Platform Crypto Provider görünüyor mu?
    try {
        $cspList = & certutil -csplist 2>&1 | Out-String
        $platformCspAvailable = ($cspList -match "Microsoft Platform Crypto Provider")
        Write-StepLog "INFO" "F3: 'Microsoft Platform Crypto Provider' in csplist: $platformCspAvailable"
        if (-not $platformCspAvailable) {
            Write-StepLog "WARN" "F3: Platform Crypto Provider yok — TPM-backed key impossible"
            $tpmReady = $false
        }
    } catch {
        Write-StepLog "WARN" "F3: certutil -csplist failed: $($_.Exception.Message)"
    }

    if ($tpmReady) {
        return $true
    }

    # TPM not ready — fail-closed unless -AllowSoftwareKey
    if (-not $AllowSoftwareKey) {
        $errMsg = "F3 fail-closed: TPM not ready and -AllowSoftwareKey NOT given. " +
                  "TPM 2.0 chip enable et veya `-AllowSoftwareKey` flag ile owner approval kaydı " +
                  "ile software KSP fallback'e izin ver (degraded security; R10 risk artar)."
        Write-StepLog "ERROR" $errMsg
        throw $errMsg
    }

    Write-StepLog "WARN" "F3 SOFTWARE KSP FALLBACK AUTHORIZED — owner approval recorded via -AllowSoftwareKey flag. R10 risk artar (CA private key software-stored, TPM-bound DEĞİL)."
    Write-StepLog "WARN" "F3: Recommended action: TPM hardware upgrade öncelik; software fallback geçici."
    return $false
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
# F3-A absorb (iter-2 MEDIUM): existing CA path CSP/KSP provider audit
# ============================================================================
#
# Initialize-EndpointCA existing CA varsa idempotent skip yapıyor (OK) ama
# Verify-Artifacts sadece host TPM readiness'e bakıyordu; CA'nın gerçekten
# TPM-backed CSP/KSP kullandığını doğrulamıyordu. Existing CA software key
# kullanıyor olabilir (TPM degradation, eski init, vb.).
#
# Test-CACryptoProvider certutil -getreg ca\CSP\Provider ile gerçek provider'ı
# okur; software KSP/CSP ise -AllowSoftwareKey ile owner approval check, yoksa
# throw (fail-closed). Sonuç hashtable: Provider, TpmBound.

function Test-CACryptoProvider {
    try {
        $caCspRaw = & certutil -getreg "ca\CSP\Provider" 2>&1 | Out-String
        $caCspKsp = & certutil -getreg "ca\CSP\ProviderType" 2>&1 | Out-String
        Write-StepLog "INFO" "F3-A: certutil -getreg ca\CSP\Provider output:`n$caCspRaw"
    } catch {
        Write-StepLog "WARN" "F3-A: certutil -getreg ca\CSP\Provider failed (CA not initialized?): $($_.Exception.Message)"
        return @{ Provider = "Unknown"; TpmBound = $false; Raw = "$($_.Exception.Message)" }
    }

    if ($caCspRaw -match "Microsoft Platform Crypto Provider") {
        Write-StepLog "INFO" "F3-A: CA key TPM-bound (Microsoft Platform Crypto Provider detected)"
        return @{ Provider = "Microsoft Platform Crypto Provider"; TpmBound = $true; Raw = $caCspRaw }
    }

    if ($caCspRaw -match "Microsoft Software Key Storage Provider" -or
        $caCspRaw -match "Microsoft Strong Cryptographic Provider" -or
        $caCspRaw -match "Microsoft Enhanced") {
        Write-StepLog "WARN" "F3-A: CA key SOFTWARE-stored (provider=$caCspRaw); TPM-bound DEĞİL"
        if (-not $AllowSoftwareKey) {
            throw "F3-A fail-closed: Existing CA key not TPM-bound + -AllowSoftwareKey not specified. " +
                  "CA software-keyed (provider=$caCspRaw) — security degraded (R10 risk). " +
                  "Çözüm: ya `-AllowSoftwareKey` ile yeniden çalıştır (owner approval kaydı), ya CA'yı Platform CSP ile re-init et (CA destructive — backup gerek)."
        }
        Write-StepLog "WARN" "F3-A: SOFTWARE KSP/CSP ACCEPTED via -AllowSoftwareKey (owner approval logged); R10 risk artar"
        return @{ Provider = "Software (KSP/CSP)"; TpmBound = $false; Raw = $caCspRaw }
    }

    Write-StepLog "WARN" "F3-A: CA provider UNKNOWN (could not classify): $caCspRaw"
    return @{ Provider = "Unknown"; TpmBound = $false; Raw = $caCspRaw }
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
        # F3-A absorb (iter-2 MEDIUM): existing CA path — provider audit zorunlu.
        # Software-keyed CA tespitinde -AllowSoftwareKey yoksa throw (fail-closed).
        $providerInfo = Test-CACryptoProvider
        Write-StepLog "INFO" "F3-A existing CA audit: Provider='$($providerInfo.Provider)', TpmBound=$($providerInfo.TpmBound)"
        return
    }

    # F3 absorb: TPM capability check — fail-closed unless -AllowSoftwareKey
    $tpmReady = Test-TpmCapability
    $cryptoProvider = if ($tpmReady) { "Microsoft Platform Crypto Provider" } else { "Microsoft Software Key Storage Provider" }
    $keyLength = if ($tpmReady) { 2048 } else { 4096 }  # TPM 2.0 typical max 2048 RSA; software KSP 4096 mümkün
    Write-StepLog "INFO" "Step 2: CryptoProvider selected = '$cryptoProvider' (tpmReady=$tpmReady, keyLength=$keyLength)"

    $confirmDesc = "Install-AdcsCertificationAuthority -CAType EnterpriseRootCA -CACommonName '$CAName' -KeyLength $keyLength -HashAlgorithm SHA256 -CryptoProviderName '$cryptoProvider' (tpmReady=$tpmReady)"
    if (-not (Confirm-Step "Initialize Enterprise Root CA" $confirmDesc)) {
        Write-StepLog "WARN" "Step 2: User declined; skipping"
        return
    }

    if ($PSCmdlet.ShouldProcess("$CAName", "Initialize Enterprise Root CA ($cryptoProvider)")) {
        Install-AdcsCertificationAuthority `
            -CAType EnterpriseRootCA `
            -CACommonName $CAName `
            -KeyLength $keyLength `
            -HashAlgorithm SHA256 `
            -CryptoProviderName $cryptoProvider `
            -ValidityPeriod Years `
            -ValidityPeriodUnits 10 `
            -Force | Out-Null
        if ($tpmReady) {
            Write-StepLog "INFO" "Step 2: CA '$CAName' initialized; TPM-backed key created"
        } else {
            Write-StepLog "WARN" "Step 2: CA '$CAName' initialized with SOFTWARE KSP (TPM degraded, owner approval via -AllowSoftwareKey)"
        }
    }
}

# ============================================================================
# Step 2.5: F2 absorb — Enable EDITF_ATTRIBUTESUBJECTALTNAME2 + CA Manager pipeline
# ============================================================================
#
# Template Subject Name "Supply in the request" + custom URI:adcomputer SAN için
# CA'da EDITF_ATTRIBUTESUBJECTALTNAME2 flag enable edilmeli. Bu flag ENABLE OLDUKTAN
# SONRA herhangi bir machine `adcomputer:{guid}` talep edebilir → impersonation riski.
# Mitigation: Template Issuance Requirements = "Authorized signatures: 0" +
# "CA certificate manager approval: ENABLED" checkbox → manuel sign-off pipeline
# mandatory (F2-A iter-2 absorb: "authorized signatures: 1" YANLIŞTI, Enrollment Agent
# flow semantiği; doğru config = Manager approval checkbox).
#
# Pilot scope (5 PC) için sürdürülebilir; 50/800 ramp için custom AD CS policy
# module gerek (machine objectGUID extraction + requested adcomputer GUID match enforce).

function Enable-EditFlagSan2 {
    Write-StepLog "INFO" "Step 2.5: F2 absorb — EDITF_ATTRIBUTESUBJECTALTNAME2 + CA Manager pipeline"

    # Check current EditFlags
    $currentFlags = ""
    try {
        $currentFlags = & certutil -getreg "policy\EditFlags" 2>&1 | Out-String
    } catch {
        Write-StepLog "WARN" "Step 2.5: certutil -getreg failed (CA not yet ready): $($_.Exception.Message)"
        return
    }

    if ($currentFlags -match "EDITF_ATTRIBUTESUBJECTALTNAME2") {
        Write-StepLog "INFO" "Step 2.5: EDITF_ATTRIBUTESUBJECTALTNAME2 already enabled (idempotent skip)"

        # F2-C iter-4 absorb (Codex iter-3 REVISE MEDIUM):
        # Önceki versiyon idempotent skip branch'inde Get-Service CertSvc Running check
        # ATLIYORDU. Flag set olsa bile servis down ise EditFlag etkin değil (sadece
        # registry değeri); ama Verify-Artifacts "F2 EditFlag SAN2 OK" diyordu → false-pass.
        # Şimdi idempotent path'te de Running check zorunlu (fail-closed).
        $svc = $null
        try {
            $svc = Get-Service -Name CertSvc -ErrorAction Stop
        } catch {
            throw "Step 2.5 idempotent path [F2-C iter-4]: Get-Service CertSvc query failed: $($_.Exception.Message)"
        }
        if ($svc.Status -ne "Running") {
            throw "Step 2.5 idempotent path [F2-C iter-4]: CertSvc not Running (Status=$($svc.Status)) — flag set ama servis down. Operator action: Start-Service CertSvc + re-run -Step EditFlag (post-restart Running double-check)."
        }
        Write-StepLog "INFO" "Step 2.5: CertSvc Running double-check OK (idempotent path; F2-C iter-4 fail-closed pass)"
        return
    }

    Write-Host @"

  SECURITY WARNING (F2 absorb):
  EDITF_ATTRIBUTESUBJECTALTNAME2 flag ENABLE edildiğinde CA herhangi bir requester'ın
  istediği SAN'ı kabul eder. Bu MITIGATION OLMADAN impersonation riski yaratır.

  Mitigation (mandatory):
  1. Template Subject Name = 'Supply in the request' (Step 3'te zaten OK)
  2. Template Issuance Requirements = "Authorized signatures: 0" +
     "CA certificate manager approval: ENABLED" checkbox (Step 3'te zaten OK)
     → her cert request manuel CA Manager onayı bekler (pending state)
  3. Pilot (5 PC) için sürdürülebilir; 50/800 ramp için custom AD CS policy
     module gerek (machine objectGUID extraction + requested adcomputer GUID match enforce)
"@ -ForegroundColor Yellow

    if (-not (Confirm-Step "Enable EDITF_ATTRIBUTESUBJECTALTNAME2" "certutil -setreg policy\EditFlags +EDITF_ATTRIBUTESUBJECTALTNAME2 + restart CertSvc (CA Manager approval pipeline ile birlikte mandatory)")) {
        Write-StepLog "WARN" "Step 2.5: User declined; SAN URI mekanizması calışmaz!"
        return
    }

    if ($PSCmdlet.ShouldProcess("CA policy", "Enable EDITF_ATTRIBUTESUBJECTALTNAME2 + restart CertSvc")) {
        try {
            # F2-C absorb (iter-2 MEDIUM): registry SET + restart exit code + CertSvc Running double-check.
            # Önceki versiyon `net stop/start` exit code'unu kontrol etmiyordu; restart fail olsa bile
            # Verify-Artifacts sadece registry flag'i görüp "LIVE" diyordu. Şimdi fail-closed:
            # 1) certutil -setreg exit 0 değilse throw
            # 2) net stop exit 0 değilse throw
            # 3) net start exit 0 değilse throw
            # 4) CertSvc Status != Running ise throw (post-restart bekleme + service check)

            & certutil -setreg "policy\EditFlags" "+EDITF_ATTRIBUTESUBJECTALTNAME2" 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "certutil -setreg failed (exit=$LASTEXITCODE)" }
            Write-StepLog "INFO" "Step 2.5: EDITF_ATTRIBUTESUBJECTALTNAME2 flag SET (registry write OK)"

            & net stop certsvc 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "net stop certsvc failed (exit=$LASTEXITCODE)" }
            Write-StepLog "INFO" "Step 2.5: CertSvc stopped (exit=0)"

            & net start certsvc 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "net start certsvc failed (exit=$LASTEXITCODE)" }
            Write-StepLog "INFO" "Step 2.5: CertSvc start command issued (exit=0)"

            # Wait + verify Running state (post-restart service may need a moment)
            Start-Sleep -Seconds 3
            $svc = Get-Service -Name CertSvc -ErrorAction Stop
            if ($svc.Status -ne "Running") {
                throw "CertSvc not Running after restart (Status=$($svc.Status)) — F2-C fail-closed: registry flag set ama service down → LIVE değil"
            }
            Write-StepLog "INFO" "Step 2.5: CertSvc Running verified (F2-C fail-closed pass); SAN URI custom extension acceptance LIVE (CA Manager approval mandatory)"
        } catch {
            Write-StepLog "ERROR" "Step 2.5: EditFlag SAN2 enable failed: $($_.Exception.Message)"
            throw
        }
    }
}

# ============================================================================
# Step 3: Create "EndpointAgentMachineCert" cert template (canonical short name; display "EndpointAgent Machine Cert")
# ============================================================================
#
# NOTE: AD CS cert templates are stored in AD as objects under
# CN=Certificate Templates,CN=Public Key Services,CN=Services,CN=Configuration,DC=...
# Templates are created via certtmpl.msc MMC; programmatic create is complex.
#
# F1 absorb (iter-1 HIGH): `CertificateTemplate` request attribute SHORT NAME ister
# (display name DEĞİL). Display name = "EndpointAgent Machine Cert" (visual);
# short name = "EndpointAgentMachineCert" (HYPHENLESS — AD'de stored ve certreq/certutil bunu kullanır).
#
# F2 absorb (iter-1 HIGH + iter-2 F2-A correction): Custom URI:adcomputer:{guid} SAN
# için template Subject Name = "Supply in the request" + Issuance Requirements:
# Authorized signatures = 0 + CA certificate manager approval = ENABLED checkbox
# (CA Manager manuel onay pipeline; 5 PC pilot için sürdürülebilir, 50/800 ramp için
# custom AD CS policy module gerek — bkz. RB-faz22.3-ad-cs-setup.md §3.2.5).
#
# Pattern: Duplicate "Computer" template + modify properties:
# - Subject Name: "Supply in the request" (F2 absorb; Build-from-AD değil)
# - Subject Alt Name: custom URI:adcomputer:{guid} certreq INF içinden 2.5.29.17 ile sağlanır
# - Key Usage: Digital Signature + Key Encipherment
# - EKU: Client Authentication (1.3.6.1.5.5.7.3.2)
# - Cryptography: "Microsoft Platform Crypto Provider" (TPM-only)
# - Issuance: TPM attestation required + CA certificate manager approval ENABLED (F2-A iter-2 correct semantik)

function Create-MachineCertTemplate {
    Write-StepLog "INFO" "Step 3: Machine cert template setup (display='$MachineCertDisplayName' / short='$MachineCertTemplate')"

    Write-StepLog "WARN" "Step 3: Cert template creation requires certtmpl.msc MMC (programmatic AD object creation complex)"
    Write-StepLog "INFO" "Step 3: Operator manual action required:"
    Write-Host @"

  MANUAL STEP (operator):
  1. mmc.exe -> File -> Add/Remove Snap-in -> 'Certificate Templates' -> Add
  2. Right-click 'Computer' template -> Duplicate Template
  3. Properties tab:
     - General:
         * Display name (visual) = '$MachineCertDisplayName'
         * Template short name (auto-generated, HYPHENLESS) MUST equal = '$MachineCertTemplate'
         * ÖNEMLI (F1 absorb iter-1 HIGH): AD CS request attribute `CertificateTemplate`
           short name kullanır (display name değil). MMC duplicate display name'i
           ALT-altı-çizgi/hyphen-strip ederek short name üretir. Yani display name
           '$MachineCertDisplayName' verilince short name OTOMATIK '$MachineCertTemplate' olur.
           Eğer farklı bir short name görülüyorsa Properties → General → Template name
           manual override (ARGV -MachineCertTemplate ile uyumlu olmalı).
     - Compatibility: Windows Server 2016 + Windows 10
     - Cryptography: Provider Category = 'Key Storage Provider'; Provider = 'Microsoft Platform Crypto Provider' (TPM-only)
     - Request Handling: Purpose = Signature and encryption; Key size minimum = 2048
     - Subject Name: 'Supply in the request' (F2 absorb iter-1 HIGH — custom SAN URI
                    için Build-from-AD yerine Supply-in-request; ayrıntı §3.2.5)
     - Extensions: Application Policies = 'Client Authentication' (1.3.6.1.5.5.7.3.2)
     - Issuance Requirements (F2-A absorb iter-2 HIGH MERGE BLOCKER — önceki "authorized signatures: 1" YANLIŞTI;
                              o setting Enrollment Agent signed-request flow'unu etkinleştirir,
                              biz o flow'u kullanmıyoruz; CA Manager approval AYRI checkbox):
         * `Authorized signatures: 0` (Enrollment Agent flow YOK — bizim INF/certreq akışı agent signed-request üretmiyor)
         * **`CA certificate manager approval: ENABLED`** (manual sign-off checkbox — request pending state'e geçer; CA Manager Certification Authority MMC'den approve eder)
         * 5 PC pilot scope için sürdürülebilir; 50/800 ramp için custom AD CS policy module gerek
     - Security: Domain Computers = 'Read' + 'Autoenroll' (not just 'Enroll'); add 'Authenticated Users' for read
  4. OK to save

  After saving the template, run this script again with -Step Publish to publish
  the template to the CA (or run that step here in a moment).

  See ADR-0029 Katman 1 (lines 121-160) for detailed template properties.
"@ -ForegroundColor Yellow

    if ($Force) {
        # F5 absorb (iter-1 LOW): -Force gerçek non-interactive — manual MMC checkpoint skip + WARN log.
        Write-StepLog "WARN" "Step 3 [F5 absorb]: Force mode — manual MMC step skipped; operator MUST ensure template '$MachineCertTemplate' (HYPHENLESS short name) exists post-run; verify via Step 10."
        return
    }

    $resp = Read-Host "Did you create the template short name '$MachineCertTemplate' via MMC? [y/N]"
    if ($resp -notmatch "^[yY]") {
        Write-StepLog "WARN" "Step 3: Template not confirmed; mass deploy NOT ready until template exists"
        return
    }
    Write-StepLog "INFO" "Step 3: Operator confirmed template short name '$MachineCertTemplate' created"
}

# ============================================================================
# Step 4: Create "EndpointAgentCodeSigning" cert template (canonical short name; display "EndpointAgent Code Signing")
# ============================================================================

function Create-CodeSigningCertTemplate {
    Write-StepLog "INFO" "Step 4: Code signing cert template setup (display='$CodeSigningDisplayName' / short='$CodeSigningTemplate')"

    Write-Host @"

  MANUAL STEP (operator):
  1. mmc.exe certtmpl.msc -> Duplicate 'Code Signing' template (or 'User' if Code Signing not in default list)
  2. Properties:
     - General:
         * Display name (visual) = '$CodeSigningDisplayName'
         * Template short name (auto-generated, HYPHENLESS) MUST equal = '$CodeSigningTemplate'
         * F1 absorb iter-1: certutil/certreq aşamasında '$CodeSigningTemplate' (hyphenless)
           kullanılır; display name ayrıdır.
     - Compatibility: Windows Server 2016 + Windows 10
     - Cryptography: TPM provider OK; Hash SHA256
     - Subject Name: 'Supply in the request' (manuel certreq)
     - Extensions: Application Policies = 'Code Signing' (1.3.6.1.5.5.7.3.3)
     - Issuance Requirements (F2-A absorb iter-2 HIGH MERGE BLOCKER — önceki "authorized signatures: 1" YANLIŞTI):
         * `Authorized signatures: 0` (Enrollment Agent flow YOK)
         * **`CA certificate manager approval: ENABLED`** (operator manuel sign-off pipeline; pending state → CA Manager approve)
     - Security: agent-team-restricted group 'Read' + 'Enroll' (NOT 'Autoenroll')
  3. OK to save

  Bu template R17 HARD RULE compliance için: private key TPM/HSM-backed Windows
  signing runner'da kalır; GitHub Actions PFX YOK.
"@ -ForegroundColor Yellow

    if ($Force) {
        # F5 absorb (iter-1 LOW): -Force gerçek non-interactive — manual MMC checkpoint skip + WARN log.
        Write-StepLog "WARN" "Step 4 [F5 absorb]: Force mode — manual MMC step skipped; operator MUST ensure code-signing template '$CodeSigningTemplate' (HYPHENLESS short name) exists post-run."
        return
    }

    $resp = Read-Host "Did you create the template short name '$CodeSigningTemplate' via MMC? [y/N]"
    if ($resp -notmatch "^[yY]") {
        Write-StepLog "WARN" "Step 4: Code signing template not confirmed"
        return
    }
    Write-StepLog "INFO" "Step 4: Operator confirmed code signing template short name '$CodeSigningTemplate' created"
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

        if ($Force) {
            # F5 absorb (iter-1 LOW): -Force gerçek non-interactive — manual IIS checkpoint skip + WARN log.
            Write-StepLog "WARN" "Step 6 [F5 absorb]: Force mode — IIS CRL manual checkpoint skipped; operator MUST post-run verify IIS site 'crl.acik.local' + curl reachability (R16 P0-14)."
            return
        }

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

    # F2 absorb verify: EDITF_ATTRIBUTESUBJECTALTNAME2 enabled?
    try {
        $editFlags = & certutil -getreg "policy\EditFlags" 2>&1 | Out-String
        $results["F2 EditFlag SAN2"] = if ($editFlags -match "EDITF_ATTRIBUTESUBJECTALTNAME2") {
            "OK (registry flag SET)"
        } else {
            "FAIL (run Step EditFlag; custom URI:adcomputer SAN reject olur)"
        }
    } catch {
        $results["F2 EditFlag SAN2"] = "FAIL: $($_.Exception.Message)"
    }

    # F2-C absorb verify (iter-2 MEDIUM): CertSvc Running double-check ayrı audit field.
    # Registry flag SET olsa bile service down ise EditFlag etkin değil (restart fail-closed).
    try {
        $svc = Get-Service -Name CertSvc -ErrorAction Stop
        $results["F2-C CertSvc Running"] = if ($svc.Status -eq "Running") {
            "OK (Status=Running; SAN URI accept + CA Manager approval pipeline LIVE)"
        } else {
            "FAIL (Status=$($svc.Status); EditFlag etkin DEĞİL — restart fail-closed pattern)"
        }
    } catch {
        $results["F2-C CertSvc Running"] = "FAIL: Get-Service CertSvc failed: $($_.Exception.Message)"
    }

    # F3 absorb verify (iter-1): host TPM/KSP capability state
    try {
        $tpm = Get-Tpm -ErrorAction Stop
        $tpmReady = ($tpm.TpmPresent -and $tpm.TpmReady -and $tpm.TpmEnabled)
        $results["F3 TPM Capability (host)"] = if ($tpmReady) {
            "OK (TPM 2.0 ready on host)"
        } elseif ($AllowSoftwareKey) {
            "WARN (TPM degraded; software KSP fallback authorized via -AllowSoftwareKey; R10 risk)"
        } else {
            "FAIL (TPM not ready; rerun with -AllowSoftwareKey or fix TPM hardware)"
        }
    } catch {
        $results["F3 TPM Capability (host)"] = if ($AllowSoftwareKey) { "WARN (Get-Tpm unavailable; software fallback authorized)" } else { "FAIL: Get-Tpm unavailable" }
    }

    # F3-A absorb verify (iter-2 MEDIUM): CA Key Binding — gerçek CSP/KSP provider
    # host TPM ready olsa bile CA initialize edildiğinde software CSP seçildiyse
    # (eski init, yanlış config, vb.) CA key TPM-bound DEĞİL. certutil -getreg ile
    # gerçek provider okunur; mismatch tespit edilir.
    try {
        $caCspRaw = & certutil -getreg "ca\CSP\Provider" 2>&1 | Out-String
        if ($caCspRaw -match "Microsoft Platform Crypto Provider") {
            $results["F3-A CA Key Binding"] = "OK (CA key TPM-bound; Platform CSP)"
        } elseif ($caCspRaw -match "Microsoft Software Key Storage Provider" -or
                  $caCspRaw -match "Microsoft Strong Cryptographic Provider" -or
                  $caCspRaw -match "Microsoft Enhanced") {
            $results["F3-A CA Key Binding"] = if ($AllowSoftwareKey) {
                "WARN (CA key SOFTWARE-stored; -AllowSoftwareKey owner approval; R10 risk artar)"
            } else {
                "FAIL (CA key SOFTWARE-stored; CA re-init Platform CSP veya -AllowSoftwareKey gerek)"
            }
        } else {
            $results["F3-A CA Key Binding"] = "WARN (CA provider classify edilemedi: $($caCspRaw.Trim()))"
        }
    } catch {
        $results["F3-A CA Key Binding"] = "FAIL: certutil -getreg ca\CSP\Provider failed: $($_.Exception.Message)"
    }

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
    Write-StepLog "INFO" "Step: $Step | WhatIf: $($PSCmdlet.MyInvocation.BoundParameters['WhatIf'].IsPresent) | Force: $Force | AllowSoftwareKey: $AllowSoftwareKey"
    Write-StepLog "INFO" "Log: $LogPath"
    Write-StepLog "INFO" "============================================================================"

    if ($Step -eq "All" -or $Step -eq "Feature") { Install-AdcsFeature }
    if ($Step -eq "All" -or $Step -eq "CaInit") { Initialize-EndpointCA }
    if ($Step -eq "All" -or $Step -eq "EditFlag") { Enable-EditFlagSan2 }  # F2 absorb (custom SAN URI mandatory)
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
