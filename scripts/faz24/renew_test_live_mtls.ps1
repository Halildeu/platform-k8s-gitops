# Fixed TEST certificate, no CA/key replacement and no insecure network fallback.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Apply = $false # APPLY_MARKER
$Root = 'C:\caddy\certs'
$OpenSsl = 'C:\Program Files\Git\usr\bin\openssl.exe'
$Caddy = 'C:\caddy\caddy.exe'
$Server = Join-Path $Root 'server.crt'
$ExpectedLeaf = '5b7039cb5514ff88eafe6afebdda484b9580a6ea5288a5fdce3157a5a1ed0a23'
$ExpectedCa = '723b3af2c8fdb6cc044bf0297e975c7cb9f6814d4d107c20c1ce5255dbeb17c7'
$Stage = 'preflight'
$Replaced = $false
$Report = [ordered]@{schemaVersion='faz24.testLiveMtlsRenewal.v1'; status='pending'
  apply=$Apply; privateMaterialExported=$false; caReplaced=$false; keyReplaced=$false
  serverCertificateChanged=$false; rollbackAttempted=$false; rollbackSucceeded=$false}

function Read-Certificate([string]$Path) {
  $pem = [IO.File]::ReadAllText($Path)
  $match = [regex]::Match($pem, '(?s)-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----')
  if (!$match.Success) { throw 'certificate-format-invalid' }
  $der = [Convert]::FromBase64String($match.Groups[1].Value)
  return New-Object Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList @(,$der)
}

function Certificate-Hash($Cert) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString($sha.ComputeHash($Cert.RawData)).Replace('-', '').ToLowerInvariant() }
  finally { $sha.Dispose() }
}

function Invoke-Bounded([string]$Executable, [string[]]$Arguments) {
  $info = New-Object Diagnostics.ProcessStartInfo
  $info.FileName = $Executable
  $info.Arguments = ($Arguments | ForEach-Object {
    if ($_ -match '["\r\n]') { throw 'invalid-native-argument' }
    '"' + $_ + '"'
  }) -join ' '
  $info.UseShellExecute = $false
  $info.CreateNoWindow = $true
  $info.RedirectStandardOutput = $true
  $info.RedirectStandardError = $true
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $info
  try {
    if (!$process.Start()) { throw 'native-start-failed' }
    $outTask = $process.StandardOutput.ReadToEndAsync()
    $errTask = $process.StandardError.ReadToEndAsync()
    if (!$process.WaitForExit(30000)) { $process.Kill(); $process.WaitForExit(); throw 'native-timeout' }
    $null = $outTask.GetAwaiter().GetResult()
    $null = $errTask.GetAwaiter().GetResult()
    if ($process.ExitCode -ne 0) { throw 'native-exit-failed' }
  } finally { $process.Dispose() }
}

function Restart-Caddy {
  # Admin API is deliberately disabled. Reuse only the existing owned task.
  Stop-ScheduledTask -TaskName 'CaddyI7AppMtls'
  for ($i=0; $i -lt 20; $i++) {
    $ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
      Where-Object { $_.LocalPort -in @(8243,8244) })
    if ($ports.Count -eq 0) { break }
    Start-Sleep -Milliseconds 250
  }
  if ($ports.Count -ne 0) { throw 'owned-listeners-did-not-stop' }
  Start-ScheduledTask -TaskName 'CaddyI7AppMtls'
  for ($i=0; $i -lt 30; $i++) {
    $ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
      Where-Object { $_.LocalAddress -eq '10.99.0.2' -and $_.LocalPort -in @(8243,8244) } |
      Select-Object -ExpandProperty LocalPort -Unique)
    if ($ports.Count -eq 2) { return }
    Start-Sleep -Milliseconds 500
  }
  throw 'owned-listeners-did-not-start'
}

try {
  Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
  foreach ($path in @($OpenSsl, $Caddy, $Server, (Join-Path $Root 'server.key'),
                      (Join-Path $Root 'ca.crt'), (Join-Path $Root 'ca.key'))) {
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw 'required-file-missing' }
  }
  $old = Read-Certificate $Server
  $ca = Read-Certificate (Join-Path $Root 'ca.crt')
  if ((Certificate-Hash $old) -cne $ExpectedLeaf -or (Certificate-Hash $ca) -cne $ExpectedCa) {
    throw 'observed-certificate-changed'
  }
  if ($old.NotAfter.ToUniversalTime() -ge [DateTime]::UtcNow) { throw 'leaf-is-not-expired' }
  if ($ca.NotAfter.ToUniversalTime() -lt [DateTime]::UtcNow.AddDays(91)) { throw 'ca-validity-too-short' }
  $config = [IO.File]::ReadAllText('C:\caddy\Caddyfile')
  $adminDisabled = [bool]($config -match '(?m)^\s*admin\s+off\s*$')
  if ($Apply -and $adminDisabled) {
    $task = Get-ScheduledTask -TaskName 'CaddyI7AppMtls'
    $duplicate = Get-ScheduledTask -TaskName 'Workcube-Caddy-mTLS' -ErrorAction SilentlyContinue
    if ($task.State -ne 'Running' -or $duplicate.State -eq 'Running') { throw 'unexpected-caddy-task-state' }
    $connections = @(Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue |
      Where-Object { $_.LocalPort -in @(8243,8244) })
    if ($connections.Count -ne 0) { throw 'active-mtls-connections-present' }
  }
  $Report.reloadMethod = if ($adminDisabled) { 'existing-task-restart' } else { 'graceful-reload' }
  $Report.oldSha256 = Certificate-Hash $old
  $Report.oldNotAfterUtc = $old.NotAfter.ToUniversalTime().ToString('o')
  $Stage = 'generate-public-proposal'
  $work = Join-Path $Root ('renewal-' + [Guid]::NewGuid().ToString('N'))
  $null = New-Item -ItemType Directory -Path $work
  $csr = Join-Path $work 'server.csr'
  $proposed = Join-Path $work 'server.crt'
  $backup = Join-Path $work 'previous-server.crt'
  Invoke-Bounded $OpenSsl @('x509', '-x509toreq', '-in', $Server, '-signkey', (Join-Path $Root 'server.key'),
                           '-copy_extensions', 'copyall', '-out', $csr)
  Invoke-Bounded $OpenSsl @('x509', '-req', '-in', $csr, '-CA', (Join-Path $Root 'ca.crt'),
                           '-CAkey', (Join-Path $Root 'ca.key'), '-set_serial', ('0x01' + [Guid]::NewGuid().ToString('N')),
                           '-days', '90', '-sha256', '-copy_extensions', 'copy', '-out', $proposed)
  $Stage = 'validate-public-proposal'
  Invoke-Bounded $OpenSsl @('verify', '-CAfile', (Join-Path $Root 'ca.crt'), '-purpose', 'sslserver',
                           '-verify_hostname', 'live-stt.denetim', $proposed)
  $next = Read-Certificate $proposed
  if ($next.Subject -cne $old.Subject -or $next.Issuer -cne $old.Issuer -or
      [Convert]::ToBase64String($next.GetPublicKey()) -cne [Convert]::ToBase64String($old.GetPublicKey())) {
    throw 'identity-or-key-changed'
  }
  $oldSan = @($old.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.17' })
  $newSan = @($next.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.17' })
  if ($oldSan.Count -ne 1 -or $newSan.Count -ne 1 -or
      [Convert]::ToBase64String($oldSan[0].RawData) -cne [Convert]::ToBase64String($newSan[0].RawData)) {
    throw 'subject-alternative-names-changed'
  }
  $Report.newSha256 = Certificate-Hash $next
  $Report.newNotAfterUtc = $next.NotAfter.ToUniversalTime().ToString('o')
  $Report.samePublicKey = $true
  $Report.sameSubjectAlternativeNames = $true
  $Report.proposalDirectory = $work
  $Report.status = 'dry-run-validated'
  if ($Apply) {
    $Stage = 'atomic-leaf-replacement'
    Copy-Item -LiteralPath $Server -Destination $backup
    Set-Acl -LiteralPath $proposed -AclObject (Get-Acl -LiteralPath $Server)
    $latest = Read-Certificate $Server
    if ((Certificate-Hash $latest) -cne $ExpectedLeaf) { throw 'leaf-changed-before-replacement' }
    [IO.File]::Replace($proposed, $Server, $backup)
    $Replaced = $true
    $Report.serverCertificateChanged = $true
    $Stage = 'validate-installed-leaf'
    Invoke-Bounded $Caddy @('validate', '--config', 'C:\caddy\Caddyfile')
    $Stage = 'reload-caddy'
    if ($adminDisabled) { Restart-Caddy }
    else { Invoke-Bounded $Caddy @('reload', '--config', 'C:\caddy\Caddyfile', '--force') }
    $Report.status = 'renewed'
  }
  $Report.stage = $Stage
} catch {
  $Report.status = 'failed'
  $Report.stage = $Stage
  $Report.errorClass = $_.Exception.GetType().Name
  if ($Replaced) {
    $Report.rollbackAttempted = $true
    try {
      Copy-Item -LiteralPath $backup -Destination $Server -Force
      if ($adminDisabled) { Restart-Caddy }
      else { Invoke-Bounded $Caddy @('reload', '--config', 'C:\caddy\Caddyfile', '--force') }
      $Report.rollbackSucceeded = $true
      $Report.serverCertificateChanged = $false
    } catch { $Report.rollbackSucceeded = $false }
  }
}
Write-Output ('TEST_MTLS_RENEWAL:' + ($Report | ConvertTo-Json -Depth 5 -Compress))
if ($Report.status -eq 'failed') { exit 1 }
