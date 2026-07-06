# verify-machine-cert.ps1 — Faz 22.3 P0-23 verify gate (cert SAN URI:adcomputer:{guid})
#
# Source-of-truth: docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md
# P0-23 acceptance: certutil -store -enterprise My + DirectorySearcher cross-check
# Iter-6 F1 absorb: LocalMachine\My (not CurrentUser); RSAT-free DirectorySearcher
#
# PR #1080 iter-2 not: F2-B 2-fazlı enrollment ile cert pending durumunda bu script
# "Cert found: False" döner (henüz install edilmemiş). Operator check için pending state:
#   Get-Content "$env:ProgramData\faz22.3-pending-requests.json"
# Pending entry varsa cert henüz CA Manager approval bekliyor; runbook §3.2.5 + §5.1.
#
# Usage:
#   .\verify-machine-cert.ps1                  # interactive output
#   .\verify-machine-cert.ps1 -Json            # JSON output (for automation)
#   .\verify-machine-cert.ps1 -ExitCodeOnFail  # script returns non-zero on fail

[CmdletBinding()]
param(
    [Parameter()][switch]$Json,
    [Parameter()][switch]$ExitCodeOnFail
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$result = [PSCustomObject]@{
    computer_name      = $env:COMPUTERNAME
    domain             = (Get-WmiObject Win32_ComputerSystem).Domain
    domain_joined      = (Get-WmiObject Win32_ComputerSystem).PartOfDomain
    ad_object_guid     = $null
    machine_cert_found = $false
    san_uri_match      = $false
    cert_thumbprint    = $null
    cert_not_before    = $null
    cert_not_after     = $null
    cert_template      = $null
    days_to_expiry     = $null
    verify_pass        = $false
    error              = $null
}

try {
    if (-not $result.domain_joined) {
        $result.error = "PC not domain-joined (22.3 scope domain-joined only; 22.2.A non-domain ayrı identity model)"
        throw $result.error
    }

    # 1. AD computer object lookup (DirectorySearcher, RSAT-free)
    $searcher = [System.DirectoryServices.DirectorySearcher]::new()
    $searcher.Filter = "(&(objectClass=computer)(name=$env:COMPUTERNAME))"
    $searcher.PropertiesToLoad.Add("objectGUID") | Out-Null
    $adResult = $searcher.FindOne()
    if (-not $adResult) {
        $result.error = "Computer object not found in AD"
        throw $result.error
    }
    $guidBytes = $adResult.Properties["objectguid"][0]
    $result.ad_object_guid = ([System.Guid]::new($guidBytes)).ToString().ToLower()

    # 2. Find machine cert with matching SAN URI in LocalMachine\My
    $dnsName = "$env:COMPUTERNAME.$($result.domain)"
    $candidateCerts = Get-ChildItem Cert:\LocalMachine\My | Where-Object {
        $_.Subject -like "CN=$dnsName*"
    }

    $matchingCert = $candidateCerts | Where-Object {
        $sanExt = $_.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" }
        if (-not $sanExt) { return $false }
        $sanExt.Format($false) -match "URL=adcomputer:$($result.ad_object_guid)"
    } | Sort-Object NotBefore -Descending | Select-Object -First 1

    if ($matchingCert) {
        $result.machine_cert_found = $true
        $result.san_uri_match = $true
        $result.cert_thumbprint = $matchingCert.Thumbprint
        $result.cert_not_before = $matchingCert.NotBefore.ToString("yyyy-MM-ddTHH:mm:ssK")
        $result.cert_not_after = $matchingCert.NotAfter.ToString("yyyy-MM-ddTHH:mm:ssK")
        $result.days_to_expiry = [int]($matchingCert.NotAfter - (Get-Date)).TotalDays

        # Extract template name from cert extension OID 1.3.6.1.4.1.311.21.7 (cert template info)
        $templateExt = $matchingCert.Extensions | Where-Object { $_.Oid.Value -eq "1.3.6.1.4.1.311.21.7" }
        if ($templateExt) {
            $result.cert_template = $templateExt.Format($false)
        }

        $result.verify_pass = ($result.days_to_expiry -gt 0)
    } elseif ($candidateCerts) {
        $result.machine_cert_found = $true
        $result.san_uri_match = $false
        $result.error = "Cert found but SAN URI:adcomputer:$($result.ad_object_guid) MISSING — F2/iter-5 mekanizma sorunu"
    } else {
        $result.error = "No machine cert found in LocalMachine\My with CN=$dnsName — enrollment not yet completed"
    }

} catch {
    if (-not $result.error) {
        $result.error = $_.Exception.Message
    }
}

# Output
if ($Json) {
    $result | ConvertTo-Json -Depth 5
} else {
    Write-Host ""
    Write-Host "════════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host " P0-23 Verify — Faz 22.3 Cert SAN URI:adcomputer:{guid}" -ForegroundColor Cyan
    Write-Host "════════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ("  Computer:       {0}" -f $result.computer_name)
    Write-Host ("  Domain:         {0}" -f $result.domain)
    Write-Host ("  Domain-joined:  {0}" -f $result.domain_joined)
    Write-Host ("  AD objectGUID:  {0}" -f $result.ad_object_guid)
    Write-Host ("  Cert found:     {0}" -f $result.machine_cert_found)
    Write-Host ("  SAN URI match:  {0}" -f $result.san_uri_match)
    Write-Host ("  Thumbprint:     {0}" -f $result.cert_thumbprint)
    Write-Host ("  NotBefore:      {0}" -f $result.cert_not_before)
    Write-Host ("  NotAfter:       {0}" -f $result.cert_not_after)
    Write-Host ("  Days to expiry: {0}" -f $result.days_to_expiry)
    Write-Host ("  Template:       {0}" -f $result.cert_template)
    Write-Host ""
    if ($result.verify_pass) {
        Write-Host "  ✓ P0-23 PASS" -ForegroundColor Green
    } else {
        Write-Host "  ✗ P0-23 FAIL" -ForegroundColor Red
        if ($result.error) {
            Write-Host "    Error: $($result.error)" -ForegroundColor Red
        }
    }
    Write-Host "════════════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""

    # Plus certutil cross-check (operator readable)
    if ($result.cert_thumbprint) {
        Write-Host "  certutil cross-check (LocalMachine\My):" -ForegroundColor Yellow
        & certutil -store -enterprise My $result.cert_thumbprint 2>&1 | Select-String "URL=|Subject:|Cert Hash"
        Write-Host ""
    }
}

if ($ExitCodeOnFail -and -not $result.verify_pass) {
    exit 1
}
exit 0
