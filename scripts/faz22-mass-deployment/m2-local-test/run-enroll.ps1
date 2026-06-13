# Faz 22.5 M2 — Win11 guest cross-machine enroll against the Mac backend.
# Runs INSIDE the Parallels "Windows 11" guest; reaches the Mac at 10.211.55.2:8096
# (Parallels shared net). Presents a test machine cert via the forward-header path
# (X-Client-Cert). Domain-FREE: no AD CS, no AD join, no prod DNS.
$ErrorActionPreference = 'Stop'
$mac     = '10.211.55.2'
$enroll  = "http://$mac`:8096/api/v1/endpoint-agent/endpoint-enrollments/auto"
$certDir = 'C:\Mac\Home\m2-win11\certs'
$tenantA = '00000000-0000-0000-0000-000000000001'

Write-Output "=== reachability ==="
$code = (curl.exe -s -o NUL -w '%{http_code}' "http://$mac`:8096/actuator/health")
Write-Output "actuator/health -> $code"
if ($code -ne '200') { Write-Output 'UNREACHABLE — abort'; exit 1 }

Add-Type -AssemblyName System.Web
$run = [guid]::NewGuid().ToString().Substring(0,8)
$body = (@{
  machineFingerprint = "FP-WIN11VM-$run"
  hostname           = "WIN11-VM-$run"
  osName             = 'Windows 11'
  osVersion          = '23H2'
  osBuild            = '22631'
  domain             = 'WORKGROUP'
  architecture       = 'x64'
  agentVersion       = '0.1.1-lab.2'
  schemaVersion      = 1
} | ConvertTo-Json -Compress)

function Enroll($name, $certFile, $tenant) {
  $pem = Get-Content (Join-Path $certDir $certFile) -Raw
  $enc = [System.Web.HttpUtility]::UrlEncode($pem)   # form-urlencoding == Java URLDecoder
  $headers = @{ 'X-Tenant-Id' = $tenant; 'X-Client-Cert' = $enc; 'Content-Type' = 'application/json' }
  try {
    $r = Invoke-WebRequest -Uri $enroll -Method Post -Headers $headers -Body $body -UseBasicParsing
    Write-Output ("{0,-26} -> {1}  {2}" -f $name, [int]$r.StatusCode, ($r.Content.Substring(0,[Math]::Min(160,$r.Content.Length))))
  } catch {
    $resp = $_.Exception.Response
    if ($resp) {
      $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
      $txt = $sr.ReadToEnd()
      Write-Output ("{0,-26} -> {1}  {2}" -f $name, [int]$resp.StatusCode, $txt.Substring(0,[Math]::Min(160,$txt.Length)))
    } else { Write-Output ("{0,-26} -> ERR {1}" -f $name, $_.Exception.Message) }
  }
}

Write-Output "`n=== Win11 guest -> Mac enroll (run=$run) ==="
Enroll 'positive(dev,tenantA)'   'dev.crt'   $tenantA
Enroll 'no-clientAuth-EKU'       'noeku.crt' $tenantA
Enroll 'no-adcomputer-SAN'       'nosan.crt' $tenantA
