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
# PR #1080 iter-1 F1 + F4 absorb (Codex 019e6a4a):
#   - F1: Template short name (HYPHENLESS canonical) = `EndpointAgentMachineCert`
#         (display name "EndpointAgent Machine Cert" MMC visual only)
#   - F4: Post-install old cert prune (same SAN URI, different thumbprint) →
#         LocalMachine\My deterministic single-cert state; agent ambiguity engellenir
#
# PR #1080 iter-2 F2-B absorb (Codex iter-2 HIGH MERGE BLOCKER):
#   - CA Manager approval ENABLED (F2-A absorb iter-2) → certreq -submit "request taken
#     under submission, RequestId=N" döner; cert hemen hazır değil.
#   - 2-fazlı enrollment: Faz 1 (initial submit → RequestId parse → JSON state persist)
#     + Faz 2 (daily retry: certreq -retrieve → cert hazır ise -accept + state remove;
#     pending ise warn + skip; denied ise alert).
#   - Pending state file: $env:ProgramData\faz22.3-pending-requests.json
#   - Duplicate guard: aynı PC için pending request varsa yeni submit YASAK
#   - Stale guard: pending > 7 gün → operator alert (manuel inspection gerek)
#
# PR #1080 iter-4 absorb (Codex iter-3 REVISE remaining 3 finding):
#   - F2-B (MEDIUM) iter-4 hardening: Read-PendingRequestsJson fail-CLOSED (corrupt
#     JSON → throw; eski versiyon fail-OPEN olduğu için duplicate submit riski vardı);
#     Write-PendingRequestsJson atomic (temp + Move-Item NTFS rename); cross-process
#     mutex (Global\Faz22.3.PendingRequests) GPO startup + Schedule Task race önler.
#     Recovery runbook: RB-faz22.3-ad-cs-setup.md §5.4.
#   - F2-C (MEDIUM) Enable-EditFlagSan2 idempotent path: registry flag SET ama servis
#     down olabilir; idempotent skip branch'inde Get-Service CertSvc Running check.
#   - F1-A (MEDIUM) HRESULT mapping canonical disposition semantik düzeltildi
#     (RB §5.1 tablosu).
#
# Deployment: SYSVOL via GPO startup script + GPO schedule task (daily renewal)
# Trigger:    Computer boot + daily 03:00 schedule task
# Context:    SYSTEM account (GPO startup runs as NT AUTHORITY\SYSTEM)
# Idempotent: existing valid cert (SAN URI match + not expired + not near-expiry) → skip
#             pending request varsa yeniden submit ETME (CA approval bekleniyor)
#
# Cross-AI peer review: Codex 019e667f-98a5-7980-8f80-613fc1a1ed82 iter-7 AGREE (ADR-0029)
#                       Codex 019e6a4a-... iter-1 5 finding absorb (PR #1080)
#                       Codex iter-2 — F2-A/F2-B/F2-C/F3-A/F1-A absorb (PR #1080 commit 806a513)
#                       Codex iter-3 REVISE — F2-B (atomic+fail-closed+mutex) + F2-C (idempotent
#                         Running check) + F1-A (HRESULT canonical) absorb (this commit)
# Board issue: #1079

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()][string]$CAConfig = "ACIKDC01\ACIK Endpoint CA",
    # F1 absorb (iter-1 HIGH MERGE BLOCKER): AD CS request attribute
    # `CertificateTemplate` SHORT NAME ister (display name değil). AD'de
    # stored short name hyphenless: 'EndpointAgentMachineCert'. Display name
    # ('EndpointAgent Machine Cert') sadece MMC visual; certreq inf bu kanonik
    # short name'i kullanır. Override gerekirse yine HYPHENLESS short name verin.
    [Parameter()][string]$Template = "EndpointAgentMachineCert",
    [Parameter()][string]$LogPath = "$env:ProgramData\faz22.3-enroll-cert.log",
    [Parameter()][int]$NearExpiryDays = 30,
    # F2-B absorb (iter-2 HIGH MERGE BLOCKER): CA Manager approval ENABLED ile
    # certreq -submit hemen cert döndürmez; "request taken under submission, RequestId=N"
    # döner. Bu RequestId persistence + daily retry için JSON state file.
    [Parameter()][string]$PendingRequestsPath = "$env:ProgramData\faz22.3-pending-requests.json",
    # Pending request > $StalePendingDays gün ise operator alert (manuel inspection gerek);
    # default 7 gün.
    [Parameter()][int]$StalePendingDays = 7
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
# F2-B absorb (iter-2 HIGH MERGE BLOCKER) — Pending request state management
# ============================================================================
#
# CA Manager approval ENABLED (F2-A) → certreq -submit hemen cert döndürmez;
# "request taken under submission, RequestId=N" döner. RequestId persistence +
# daily retry için JSON state file.
#
# Schema (faz22.3-pending-requests.json):
# {
#   "ACIKDC01": {                              # machine name (case-insensitive key)
#     "request_id": 12345,
#     "submitted_at": "2026-05-27T03:00:12Z",
#     "dns_name": "ACIKDC01.acik.local",
#     "guid": "abc12345-...",
#     "template": "EndpointAgentMachineCert"
#   }
# }
#
# Operations:
# - Get-PendingRequest: bu PC için pending var mı?
# - Save-PendingRequest: yeni submit sonrası RequestId persist
# - Remove-PendingRequest: success/denied sonrası temizle
# - Test-PendingStale: pending > $StalePendingDays gün mü?

# ============================================================================
# F2-B iter-4 absorb (Codex REVISE remaining 3 finding)
# ============================================================================
#
# Önceki versiyon (iter-3) `Read-PendingRequestsJson` corrupt JSON durumunda
# fail-OPEN davranıyordu: try/catch ile parse hatası yutuluyor + `@{}` return
# ediliyordu. Bu, `Get-PendingRequest` `$null` döndürmesine yol açıyordu →
# `Invoke-CertReqEnrollment` "no pending" branch'ine girip YENİ submit
# yapıyordu. Senaryo: state corrupt + cert hâlâ CA queue'da pending → duplicate
# request → CA Manager queue'da iki entry → karışıklık.
#
# Plus: `Write-PendingRequestsJson` `Out-File -Force` ile direkt yazıyordu;
# yazım sırasında process kill / disk dolu / NTFS metadata flush race olursa
# JSON kısmi yazılmış olabilir → corrupt state bir sonraki run'da fail-open
# kuyruğunu tetikler.
#
# Fix:
# 1. `Read-PendingRequestsJson` fail-CLOSED: parse hatası, eksik schema field,
#    veya beklenen veri tipinde değişiklik → throw. Operator manuel inspect/reset
#    gerek. Sadece "dosya yok" durumu empty {} sayılır (initial state).
# 2. `Save-PendingRequest` / `Remove-PendingRequest` atomic write: temp file
#    + Move-Item -Force (NTFS rename atomic semantic). Move-Item fail durumunda
#    temp file cleanup.
# 3. Cross-process mutex (`Global\Faz22.3.PendingRequests`) ile aynı PC üzerinde
#    GPO startup + Schedule Task tetiklerinin race condition'ını engelle. Mutex
#    finally block'unda release.

function Read-PendingRequestsJson {
    if (-not (Test-Path $PendingRequestsPath)) {
        return @{}
    }
    try {
        $raw = Get-Content $PendingRequestsPath -Raw -ErrorAction Stop
    } catch {
        Write-EnrollLog "ERROR" "F2-B iter-4: pending-requests.json read I/O failure: $($_.Exception.Message)"
        throw "F2-B fail-closed: pending-requests.json okuma I/O hatası — operator inspect: $PendingRequestsPath"
    }

    if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }

    try {
        $obj = $raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Write-EnrollLog "ERROR" "F2-B iter-4 fail-closed: pending-requests.json corrupt JSON: $($_.Exception.Message)"
        Write-EnrollLog "ERROR" "F2-B iter-4: Operator action required — backup + reset:"
        Write-EnrollLog "ERROR" "  Copy-Item '$PendingRequestsPath' '$PendingRequestsPath.corrupt-$(Get-Date -Format yyyyMMdd-HHmmss)'"
        Write-EnrollLog "ERROR" "  Remove-Item '$PendingRequestsPath'"
        Write-EnrollLog "ERROR" "  Sonraki run yeni submit yapacak; CA queue'da duplicate pending varsa operator manuel deny edebilir (certutil -view -restrict 'Disposition=9')"
        throw "F2-B fail-closed: pending-requests.json corrupt; duplicate guard bypass YOK — operator manuel reset gerek"
    }

    # Convert PSCustomObject to hashtable for in-place edit + schema validate
    $ht = @{}
    foreach ($prop in $obj.PSObject.Properties) {
        $value = $prop.Value
        # Schema validation: her entry zorunlu field'lara sahip olmalı
        if (-not $value) {
            Write-EnrollLog "ERROR" "F2-B iter-4 fail-closed: pending entry null for key='$($prop.Name)'"
            throw "F2-B fail-closed: pending entry corrupt (null value, key='$($prop.Name)')"
        }
        $requiredFields = @('request_id', 'submitted_at', 'dns_name', 'guid', 'template')
        foreach ($field in $requiredFields) {
            $hasField = $false
            try {
                $hasField = $null -ne ($value.PSObject.Properties[$field])
            } catch { $hasField = $false }
            if (-not $hasField) {
                Write-EnrollLog "ERROR" "F2-B iter-4 fail-closed: pending entry missing field='$field' for key='$($prop.Name)'"
                throw "F2-B fail-closed: pending entry schema incomplete (missing '$field', key='$($prop.Name)')"
            }
        }
        $ht[$prop.Name] = $value
    }
    return $ht
}

function Write-PendingRequestsJson {
    param([hashtable]$Data)

    # F2-B iter-4 absorb: atomic write — temp file + Move-Item (NTFS atomic rename)
    $tempFile = "$PendingRequestsPath.tmp"
    try {
        $json = $Data | ConvertTo-Json -Depth 5
        # Out-File -Force temp'e yaz (partial-write riski temp'te kalır; main file korunur)
        $json | Out-File -FilePath $tempFile -Encoding UTF8 -Force -ErrorAction Stop

        # Atomic rename: NTFS rename single inode swap (no half-state visible to next reader)
        Move-Item -Path $tempFile -Destination $PendingRequestsPath -Force -ErrorAction Stop
    } catch {
        Write-EnrollLog "ERROR" "F2-B iter-4: pending-requests.json atomic write failed: $($_.Exception.Message)"
        # Temp file cleanup (move failed → temp orphan kalmasın)
        if (Test-Path $tempFile) {
            Remove-Item $tempFile -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

# F2-B iter-4 absorb: cross-process mutex helper (file lock pattern).
# GPO startup script + Schedule Task aynı anda tetiklenebilir (boot + 03:00 race);
# mutex aynı PC üzerinde tek bir enroll script instance'ı garanti eder.
function Enter-PendingMutex {
    $mutexName = "Global\Faz22.3.PendingRequests"
    # F2-B iter-5 absorb: Mutex acquisition exception vs timeout ayrımı.
    # - Timeout (WaitOne false) = concurrent run detected → idempotent skip OK
    # - Acquisition exception (Mutex.new fail; UnauthorizedAccess, environment policy)
    #   → throw (operator-visible failure; sessizce skip etmek policy/permission
    #   sorununu maskeler ve enrollment her run'da kaybolur)
    try {
        $mutex = [System.Threading.Mutex]::new($false, $mutexName)
    } catch {
        # F2-B iter-5: acquisition exception fail-closed (önceki versiyon
        # sessizce null return ediyordu → enrollment sürekli skip + sessiz fail)
        Write-EnrollLog "ERROR" "F2-B iter-5: Mutex CREATE failed (acquisition exception; operator-visible failure): $($_.Exception.Message)"
        throw "Mutex acquisition failed (Global\Faz22.3.PendingRequests) — operator action: check WindowsIdentity privileges + Global namespace ACL + Mandatory Integrity Level. Skipping silently would hide enrollment failure."
    }

    try {
        # WaitOne timeout: 30 saniye — diğer instance kısa süre içinde bitirir;
        # sürmüyorsa (contention timeout) enroll script idempotent olduğu için skip OK.
        $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds(30))
        if (-not $acquired) {
            Write-EnrollLog "WARN" "F2-B iter-4: Mutex contention timeout (30s) — concurrent enroll script detected; skipping this run (next daily retry)"
            $mutex.Dispose()
            return $null
        }
        Write-EnrollLog "INFO" "F2-B iter-4: Mutex '$mutexName' acquired"
        return $mutex
    } catch {
        # WaitOne exception (AbandonedMutexException, etc.) — log + dispose + throw
        Write-EnrollLog "ERROR" "F2-B iter-5: Mutex WAIT failed: $($_.Exception.Message)"
        try { $mutex.Dispose() } catch { }
        throw "Mutex WaitOne failed — operator action: check OS state + Mutex provider health"
    }
}

function Exit-PendingMutex {
    param($Mutex)
    if (-not $Mutex) { return }
    try {
        $Mutex.ReleaseMutex()
        $Mutex.Dispose()
        Write-EnrollLog "INFO" "F2-B iter-4: Mutex released"
    } catch {
        Write-EnrollLog "WARN" "F2-B iter-4: Mutex release failed (non-fatal): $($_.Exception.Message)"
    }
}

function Get-PendingRequest {
    $all = Read-PendingRequestsJson
    if ($all.ContainsKey($env:COMPUTERNAME)) {
        return $all[$env:COMPUTERNAME]
    }
    return $null
}

function Save-PendingRequest {
    param(
        [int]$RequestId,
        [string]$DnsName,
        [string]$Guid
    )
    $all = Read-PendingRequestsJson
    $all[$env:COMPUTERNAME] = [PSCustomObject]@{
        request_id    = $RequestId
        submitted_at  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        dns_name      = $DnsName
        guid          = $Guid
        template      = $Template
    }
    Write-PendingRequestsJson -Data $all
    Write-EnrollLog "INFO" "F2-B: Pending request saved (RequestId=$RequestId, machine=$env:COMPUTERNAME)"
}

function Remove-PendingRequest {
    $all = Read-PendingRequestsJson
    if ($all.ContainsKey($env:COMPUTERNAME)) {
        $all.Remove($env:COMPUTERNAME)
        Write-PendingRequestsJson -Data $all
        Write-EnrollLog "INFO" "F2-B: Pending request removed for $env:COMPUTERNAME"
    }
}

function Test-PendingStale {
    param([PSCustomObject]$Pending)
    try {
        $submitted = [DateTime]::Parse($Pending.submitted_at)
        $age = ((Get-Date).ToUniversalTime() - $submitted).TotalDays
        return ($age -gt $StalePendingDays)
    } catch {
        Write-EnrollLog "WARN" "F2-B: Test-PendingStale parse failed; treating as stale: $($_.Exception.Message)"
        return $true
    }
}

# ============================================================================
# Step 3: certreq 2-fazlı flow (iter-5 F1 + iter-2 F2-B absorb)
# ============================================================================
#
# Faz 1 (initial submit): no pending → certreq -new + -submit → RequestId parse
#   if RequestId döndü (pending) → state persist + exit (cert henüz yok)
#   if cert hemen geldiyse (CA approval bypass durumu) → -accept + state-free
#
# Faz 2 (pending retrieve): pending exists →
#   certreq -retrieve $RequestId → if cert hazır: -accept + remove pending
#                                   if hâlâ pending: warn + skip (next daily retry)
#                                   if denied: error + alert (operator inspection)
#                                   if stale (>7 gün): operator alert

function Install-Cert {
    param(
        [string]$CerFile,
        [string]$DnsName,
        [string]$Guid
    )

    Write-EnrollLog "INFO" "Install-Cert: certreq -accept -machine $CerFile"
    if ($PSCmdlet.ShouldProcess("certreq -accept", "Install cert to LocalMachine\My")) {
        $acceptOutput = & certreq.exe -accept -q -f -machine $CerFile 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            Write-EnrollLog "ERROR" "Install-Cert: certreq -accept failed (exit=$LASTEXITCODE): $acceptOutput"
            throw "certreq -accept failed — private key binding issue"
        }
        Write-EnrollLog "INFO" "Install-Cert: Cert installed to LocalMachine\My (private key TPM-bound)"
    }

    # Verify cert exists in store post-install
    $installedCert = Get-ChildItem Cert:\LocalMachine\My | Where-Object {
        $_.Subject -eq "CN=$DnsName" -and
        ($_.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" -and ($_.Format($false) -match "URL=adcomputer:$Guid") })
    } | Sort-Object NotBefore -Descending | Select-Object -First 1

    if (-not $installedCert) {
        Write-EnrollLog "ERROR" "Install-Cert: Post-install verify failed — cert not found in LocalMachine\My with matching SAN URI"
        throw "Cert install verify failed"
    }
    Write-EnrollLog "INFO" "Install-Cert: Verified — Thumbprint=$($installedCert.Thumbprint), NotAfter=$($installedCert.NotAfter)"

    # F4 absorb (iter-1 MEDIUM): Prune old/superseded certs (same SAN URI, different thumbprint).
    try {
        $oldCerts = Get-ChildItem Cert:\LocalMachine\My | Where-Object {
            $_.Subject -like "CN=$DnsName*" -and
            $_.Thumbprint -ne $installedCert.Thumbprint -and
            ($_.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" -and ($_.Format($false) -match "URL=adcomputer:$Guid") })
        }
        foreach ($old in $oldCerts) {
            Write-EnrollLog "INFO" "F4 prune: Removing superseded cert thumbprint=$($old.Thumbprint) NotAfter=$($old.NotAfter) (superseded by $($installedCert.Thumbprint))"
            Remove-Item "Cert:\LocalMachine\My\$($old.Thumbprint)" -Force -ErrorAction SilentlyContinue
        }
        if ($oldCerts.Count -gt 0) {
            Write-EnrollLog "INFO" "F4 prune: $($oldCerts.Count) old cert(s) removed; LocalMachine\My now contains single valid cert for SAN URI adcomputer:$Guid"
        } else {
            Write-EnrollLog "INFO" "F4 prune: No old certs to prune (clean state)"
        }
    } catch {
        Write-EnrollLog "WARN" "F4 prune failed (non-fatal): $($_.Exception.Message)"
    }
}

function Invoke-PendingRetrieve {
    param(
        [PSCustomObject]$Pending,
        [string]$DnsName,
        [string]$Guid
    )

    Write-EnrollLog "INFO" "F2-B Faz 2: pending request retrieve (RequestId=$($Pending.request_id), submitted_at=$($Pending.submitted_at))"

    # Stale guard
    if (Test-PendingStale -Pending $Pending) {
        Write-EnrollLog "ERROR" "F2-B STALE: Pending request RequestId=$($Pending.request_id) is older than $StalePendingDays days — operator action required (CA Manager approval missing / denied silently)"
        Write-EnrollLog "ERROR" "F2-B STALE: Manual inspection: certutil -view -restrict 'RequestId=$($Pending.request_id)' on CA"
        # State'i tutuyoruz — operator manuel temizleyene kadar yeniden submit etmiyoruz
        return $false
    }

    $cerFile = "$env:TEMP\endpoint-agent-retrieve-$(Get-Random).cer"
    try {
        Write-EnrollLog "INFO" "F2-B: certreq -retrieve -config '$CAConfig' $($Pending.request_id) $cerFile"
        if ($PSCmdlet.ShouldProcess("certreq -retrieve", "Retrieve pending request $($Pending.request_id)")) {
            $retrieveOutput = & certreq.exe -retrieve -q -f -config $CAConfig $Pending.request_id $cerFile 2>&1 | Out-String

            # certreq -retrieve disposition classification (F1-A iter-5/6 absorb):
            # AD CS canonical disposition'a göre output text bazlı (HRESULT semantik güvenilmez).
            # ÖNEMLİ — Disposition iki ayrı katmanda farklı code'lar (F1-A iter-6/7 absorb):
            #   * API ICertRequest::Submit return value (certreq output): CR_DISP_* (canonical, dökümante)
            #     - CR_DISP_DENIED = 2, CR_DISP_ISSUED = 3, CR_DISP_UNDER_SUBMISSION = 5
            #   * CA database "Disposition" column (certutil -view): farklı integer set
            #     - Pending: column=9 (evidence-derived, pattern-confirmed)
            #     - Issued: column=20 (evidence-derived, pattern-confirmed)
            #     - Denied: column değeri AD CS docs ile cross-verify edilmedi (iter-7 hardcoded
            #       kaldırıldı). Operator live lookup: `certutil -view -restrict "RequestId=<id>"`
            # certreq output API disposition kullanır (script bunu parse eder, güvenilir).
            # Aşağıdaki regex'ler certreq output'unu parse ettiği için API CR_DISP_* değerleri canonical:
            # - LASTEXITCODE=0 + cer file non-empty → CR_DISP_ISSUED=3 (cert hazır)
            # - output "denied" text → CR_DISP_DENIED=2 (CA Manager reject)
            # - output "taken under submission" → CR_DISP_UNDER_SUBMISSION=5
            # - diğer → transient error (transient network/CA outage; next run retry)
            if ($LASTEXITCODE -eq 0 -and (Test-Path $cerFile) -and ((Get-Item $cerFile).Length -gt 0)) {
                Write-EnrollLog "INFO" "F2-B: Cert retrieved (Disposition=3 issued) — proceeding to -accept"
                Install-Cert -CerFile $cerFile -DnsName $DnsName -Guid $Guid
                Remove-PendingRequest
                return $true
            }

            # Output text-based classification (F1-A iter-5/6 absorb: HRESULT semantik güvenilmez;
            # API CR_DISP_* certreq output'ta görünür ama unambiguous text match daha sağlam)
            if ($retrieveOutput -match "denied|Disposition: 2") {
                Write-EnrollLog "ERROR" "F2-B DENIED (API CR_DISP_DENIED=2): RequestId=$($Pending.request_id) was denied by CA Manager — operator inspection required (live lookup: `certutil -view -restrict 'RequestId=$($Pending.request_id)' -out 'RequestId,Disposition,DispositionMessage,RequesterName'`)"
                Write-EnrollLog "ERROR" "F2-B DENIED output: $retrieveOutput"
                # State'i temizle ki next run yeni submit yapabilsin (CA Manager intentional reject ise admin manuel)
                Remove-PendingRequest
                return $false
            }

            if ($retrieveOutput -match "taken under submission|Disposition: 5|pending") {
                Write-EnrollLog "WARN" "F2-B PENDING (API CR_DISP_UNDER_SUBMISSION=5; CA DB Disposition column=9): RequestId=$($Pending.request_id) hâlâ pending; CA Manager approval bekleniyor (next daily run retry; `certutil -view -restrict 'Disposition=9'`)"
                return $false
            }

            Write-EnrollLog "WARN" "F2-B: certreq -retrieve unexpected output (exit=$LASTEXITCODE): $retrieveOutput"
            return $false
        }
    } finally {
        Remove-Item $cerFile -Force -ErrorAction SilentlyContinue
    }
    return $false
}

function Invoke-CertReqEnrollment {
    param([string]$Guid, [string]$DnsName)

    # F2-B Faz 2: pending request varsa önce onu retrieve etmeyi dene
    $pending = Get-PendingRequest
    if ($pending) {
        Write-EnrollLog "INFO" "F2-B: Existing pending request detected (RequestId=$($pending.request_id)); attempting retrieve before new submit"
        $retrieved = Invoke-PendingRetrieve -Pending $pending -DnsName $DnsName -Guid $Guid
        if ($retrieved) {
            Write-EnrollLog "INFO" "F2-B: Pending retrieve succeeded; cert installed"
            return
        }
        # Hâlâ pending veya stale → yeni submit YASAK (duplicate request engelle)
        Write-EnrollLog "INFO" "F2-B: Pending unresolved; skip new submit (duplicate guard)"
        return
    }

    # F2-B Faz 1: no pending → yeni submit
    Write-EnrollLog "INFO" "Step 3: certreq submit flow start (template short name='$Template', CA=$CAConfig)"

    $infFile = "$env:TEMP\endpoint-agent-cert-$(Get-Random).inf"
    $reqFile = "$env:TEMP\endpoint-agent-cert-$(Get-Random).req"
    $cerFile = "$env:TEMP\endpoint-agent-cert-$(Get-Random).cer"

    # F1 absorb: CertificateTemplate request attribute SHORT NAME alır (display değil).
    # `$Template` = HYPHENLESS canonical (default "EndpointAgentMachineCert").
    # F2 absorb: Template Subject Name = "Supply in the request" → INF subject + custom SAN URI
    # mandatory. CA Manager approval pipeline (F2-A: "CA certificate manager approval: ENABLED")
    # → -submit RequestId döndürür; F2-B 2-fazlı retry mekanizması ile cert hazır olduğunda alınır.
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

        # Step 3b: -submit (submit to CA; with CA Manager approval ENABLED, returns RequestId not cert)
        Write-EnrollLog "INFO" "Step 3b: certreq -submit -config '$CAConfig' $reqFile $cerFile"
        if ($PSCmdlet.ShouldProcess("certreq -submit", "Submit request to CA")) {
            $submitOutput = & certreq.exe -submit -q -f -config $CAConfig $reqFile $cerFile 2>&1 | Out-String
            Write-EnrollLog "INFO" "Step 3b output (exit=$LASTEXITCODE): $submitOutput"

            # F2-B: RequestId parse — output formatı "RequestId: <int>" veya "Request Id: <int>"
            $requestIdMatch = [regex]::Match($submitOutput, "Request\s?(?:ID|Id):\s*(\d+)", "IgnoreCase")

            # Check: cert hemen geldi mi (cer file size > 0 + exit 0)?
            $cerImmediate = (Test-Path $cerFile) -and ((Get-Item $cerFile).Length -gt 0)

            if ($cerImmediate -and $LASTEXITCODE -eq 0) {
                # CA Manager approval bypass durumu (örn. template'de approval disable) — direkt -accept
                Write-EnrollLog "INFO" "Step 3b: Cert returned immediately (CA Manager approval bypass detected); proceeding to -accept"
                Install-Cert -CerFile $cerFile -DnsName $DnsName -Guid $Guid
                return
            }

            if ($requestIdMatch.Success) {
                # F2-B Faz 1: pending — RequestId persist + exit (next daily run retrieve)
                $requestId = [int]$requestIdMatch.Groups[1].Value
                Write-EnrollLog "INFO" "F2-B: Request submitted, taken under submission (RequestId=$requestId); CA Manager approval pending"
                Save-PendingRequest -RequestId $requestId -DnsName $DnsName -Guid $Guid
                Write-EnrollLog "INFO" "F2-B: Cert not yet available; daily schedule task will retrieve when CA Manager approves"
                return
            }

            # Neither immediate cert nor parseable RequestId → genuine failure
            Write-EnrollLog "ERROR" "Step 3b: certreq -submit failed (no RequestId parsed, no cer file): $submitOutput"
            throw "certreq -submit failed — no RequestId parsed and no cert returned; check CA reachability + template permission"
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
    Write-EnrollLog "INFO" "F2-B PendingRequestsPath: $PendingRequestsPath | StalePendingDays: $StalePendingDays"
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

    # F2-B iter-4 absorb: cross-process mutex — GPO startup + Schedule Task aynı anda
    # tetiklenmesi durumunda tek instance garanti. Idempotent check + JSON state operations
    # mutex altında çalışır; release finally block'unda garanti edilir.
    $mutex = Enter-PendingMutex
    if (-not $mutex) {
        Write-EnrollLog "WARN" "F2-B iter-4: Mutex acquire failed — concurrent run; skipping this invocation (idempotent — next daily retry)"
        Write-EnrollLog "INFO" "============================================================================"
        exit 0
    }

    try {
        # Step 2: Idempotent check (valid cert varsa erken çıkış; F2-B: pending leftover varsa temizle)
        if (Test-ExistingValidCert -Guid $guid -DnsName $dnsName) {
            # Valid cert var → eğer pending state file'da bu PC için entry varsa (eski stale),
            # cert zaten mint edildiği için pending entry artık ihtiyaç yok → temizle.
            $pending = Get-PendingRequest
            if ($pending) {
                Write-EnrollLog "INFO" "F2-B: Valid cert exists + stale pending entry detected (RequestId=$($pending.request_id)); removing"
                Remove-PendingRequest
            }
            Write-EnrollLog "INFO" "Idempotent skip — valid existing cert"
            Write-EnrollLog "INFO" "============================================================================"
            exit 0
        }

        # Step 3: certreq enrollment (F2-B 2-fazlı: pending varsa retrieve dener, yoksa yeni submit)
        Invoke-CertReqEnrollment -Guid $guid -DnsName $dnsName

        Write-EnrollLog "INFO" "Enrollment flow COMPLETE — (cert installed | pending CA Manager approval | skipped)"
        Write-EnrollLog "INFO" "============================================================================"
        exit 0
    } finally {
        Exit-PendingMutex -Mutex $mutex
    }

} catch {
    Write-EnrollLog "ERROR" "FATAL: $($_.Exception.Message)"
    Write-EnrollLog "ERROR" "Stack: $($_.ScriptStackTrace)"
    Write-EnrollLog "ERROR" "============================================================================"
    exit 1
}
