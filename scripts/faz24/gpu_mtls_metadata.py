"""Fixed-target, read-only certificate metadata; no private material is read/exported."""
import json
import os
from pathlib import Path
import stat
import subprocess

from run_gpu_host_exact_sha_rollout import encode_remote_input, ssh_command


REMOTE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:GIT_CONFIG_COUNT = '1'
$env:GIT_CONFIG_KEY_0 = 'safe.directory'
$env:GIT_CONFIG_VALUE_0 = 'C:/platform-ai'
$root = 'C:\caddy'
$certs = @()
$keys = @()
foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Recurse -Depth 2)) {
  if ($file.Extension -eq '.key') { $keys += $file.FullName.Substring($root.Length); continue }
  if ($file.Extension -notin @('.crt', '.cer')) { continue }
  $pem = [IO.File]::ReadAllText($file.FullName)
  $matches = [regex]::Matches($pem, '(?s)-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----')
  foreach ($match in $matches) {
    $der = [Convert]::FromBase64String($match.Groups[1].Value)
    $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList @(,$der)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($sha.ComputeHash($cert.RawData)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
    $certs += [ordered]@{
      relativePath=$file.FullName.Substring($root.Length)
      subject=$cert.Subject; issuer=$cert.Issuer
      notBeforeUtc=$cert.NotBefore.ToUniversalTime().ToString('o')
      notAfterUtc=$cert.NotAfter.ToUniversalTime().ToString('o')
      expired=($cert.NotAfter.ToUniversalTime() -lt [DateTime]::UtcNow)
      sha256=$hash
    }
    $cert.Dispose()
  }
}
$tasks = @()
foreach ($name in @('CaddyI7AppMtls', 'Workcube-Caddy-mTLS')) {
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if (!$task) { $tasks += @{name=$name; present=$false}; continue }
  $info = $task | Get-ScheduledTaskInfo
  $tasks += [ordered]@{name=$name; present=$true; state=[string]$task.State
    lastResult=$info.LastTaskResult; lastRunUtc=$info.LastRunTime.ToUniversalTime().ToString('o')
    restartCount=$task.Settings.RestartCount; restartInterval=$task.Settings.RestartInterval}
}
$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPort -in @(8200,8243,8244,8300) } |
  ForEach-Object { @{port=$_.LocalPort; localAddress=$_.LocalAddress} })
$netstatLines = @(& netstat.exe -ano -p TCP 2> $null)
$netstatMetadata = @{exitCode=$LASTEXITCODE; lineCount=$netstatLines.Count; states=@()}
foreach ($line in $netstatLines) {
  if ($line -match '^\s*TCP\s+\S+:(8200|8243|8244|8300)\s+\S+\s+([^\s]{1,30})\s+\d+\s*$') {
    $state = if ($Matches[2] -eq 'LISTENING') { 'LISTENING' } else { 'other' }
    $netstatMetadata.states += @{port=[int]$Matches[1]; state=$state}
  }
}
$openssl = Get-Command openssl -ErrorAction SilentlyContinue
$tools = @()
foreach ($candidate in @('C:\Program Files\Git\usr\bin\openssl.exe', 'C:\Program Files\OpenSSL-Win64\bin\openssl.exe')) {
  $tools += @{path=$candidate; present=(Test-Path -LiteralPath $candidate -PathType Leaf)}
}
$python = @()
$runtimeTasks = @()
foreach ($name in @('platform-ai-live-stt', 'platform-ai-meeting-ai')) {
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  if (!$task) { $runtimeTasks += @{name=$name; present=$false}; continue }
  $info = $task | Get-ScheduledTaskInfo
  $runtimeTasks += [ordered]@{name=$name; present=$true; state=[string]$task.State
    enabled=[bool]$task.Settings.Enabled; lastResult=$info.LastTaskResult
    lastRunUtc=$info.LastRunTime.ToUniversalTime().ToString('o')
    logonType=[string]$task.Principal.LogonType}
  foreach ($action in @($task.Actions)) {
    if ($action.Arguments -match '(?i)(?:^|\s)-Port\s+([0-9]{1,5})(?:\s|$)') {
      $runtimeTasks[-1]['configuredPort'] = [int]$Matches[1]
    }
    if ($action.Arguments -match '(?i)(?:^|\s)-PythonExe\s+(?:"([^"]+)"|([^\s"]+))') {
      $path = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
      $python += @{task=$name; path=$path; present=(Test-Path -LiteralPath $path -PathType Leaf)}
    }
  }
}
$startupLogs = @()
$logRoot = 'C:\platform-ai\deploy\gpu-host\logs'
$markers = [ordered]@{
  runtimeConfigRejected='[startup] Runtime config rejected'
  runtimeConfigMissing='[startup] Required runtime config is unavailable'
  environmentRejected='[startup] Runtime config environment rejected'
  permitRejected='[startup] Transcript-ready pre-enable permit rejected'
  ollamaUnavailable='[startup] Ollama readiness check failed'
  permissionDenied='PermissionError'
  missingFile='FileNotFoundError'
  missingModule='ModuleNotFoundError'
  importFailed='ImportError'
  syntaxError='SyntaxError'
  validationError='ValidationError'
  nativeAbort='forrtl: error'
  addressInUse='address already in use'
  started='Application startup complete'
  uvicornListening='Uvicorn running on'
  startupWaiting='Waiting for application startup'
  shutdown='Shutting down'
  startupPreload='streaming model preload started'
  pathMissing='Cannot find path'
  commandMissing='is not recognized as the name'
  powershellParseError='ParserError'
  parameterError='ParameterBindingException'
  legacyConfigRejected='env.local.ps1'
  modelManifestRejected='model manifest'
  pinnedModelMissing='pinned streaming model directory'
  workerTimeout='WorkerTimeoutError'
  workerCrash='WorkerCrashedError'
  workerReadinessChanged='worker readiness changed'
  workerInferenceTimeout='worker exceeded timeout'
  workerQueueTimeout='worker queue exceeded timeout'
  workerExited='worker exited before response'
  cudaOutOfMemory='CUDA out of memory'
  allocationFailed='failed to allocate'
}
foreach ($pattern in @('live-stt-*.log', 'meeting-ai-*.log')) {
  $files = @(Get-ChildItem -LiteralPath $logRoot -Filter $pattern -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 2)
  foreach ($file in $files) {
    try {
      $lines = @(Get-Content -LiteralPath $file.FullName -Tail 160 -ErrorAction Stop |
        ForEach-Object { if ($_.Length -gt 8192) { $_.Substring(0,8192) } else { $_ } })
      $counts = [ordered]@{}
      foreach ($entry in $markers.GetEnumerator()) {
        $counts[$entry.Key] = @($lines | Where-Object { $_.Contains($entry.Value) }).Count
      }
      $frames = @()
      $winErrors = @()
      $listeningPorts = @()
      foreach ($line in $lines) {
        if ($line -match 'Uvicorn running on http://(?:127\.0\.0\.1|0\.0\.0\.0):([0-9]{1,5})') {
          $listeningPorts += [int]$Matches[1]
        }
        if ($line -match '^\s*File "[^"]+[\\/]([A-Za-z_][A-Za-z0-9_]{0,80}\.py)", line ([0-9]{1,6}), in ([A-Za-z_][A-Za-z0-9_]{0,80})\s*$') {
          $frames += @{module=$Matches[1]; line=[int]$Matches[2]; function=$Matches[3]}
        }
        if ($line -match '\[WinError ([0-9]{1,8})\]') { $winErrors += [int]$Matches[1] }
      }
      $startupLogs += [ordered]@{service=($pattern.Split('-')[0]); bytes=$file.Length
        modifiedUtc=$file.LastWriteTimeUtc.ToString('o'); readable=$true; markerCounts=$counts
        tracebackFrames=@($frames | Select-Object -Last 16); winErrorCodes=@($winErrors | Select-Object -Unique)
        listeningPorts=@($listeningPorts | Select-Object -Unique); createdUtc=$file.CreationTimeUtc.ToString('o')}
    } catch {
      $startupLogs += @{service=($pattern.Split('-')[0]); readable=$false}
    }
  }
}
$permitMetadata = [ordered]@{checked=$false}
$runtimeRoot = 'C:\ProgramData\Acik\platform-ai'
$envPath = Join-Path $runtimeRoot 'meeting-ai.env'
if (Test-Path -LiteralPath $envPath -PathType Leaf) {
  $publicBindings = @{}
  foreach ($line in [IO.File]::ReadLines($envPath)) {
    if ($line -match '^(MAI_READY_(?:ACTIVATION_RECEIPT_PATH|PRE_ENABLE_PERMIT_PATH|PERMIT_TRUST_ROOT_PATH|EXPECTED_(?:GITOPS_COMMIT|POLICY_SHA256|PRODUCER_IMAGE_DIGEST|PERMIT_TRUST_ROOT_SHA256))|MAI_APP_ENV)=(.*)$') {
      $publicBindings[$Matches[1]] = $Matches[2]
    }
  }
  try {
    . 'C:\platform-ai\deploy\gpu-host\meeting-ai-runtime-env.ps1'
    $servicePython = @($python | Where-Object task -eq 'platform-ai-meeting-ai')[0].path
    $params = @{
      PermitPath=$publicBindings['MAI_READY_PRE_ENABLE_PERMIT_PATH']
      TrustRootPath=$publicBindings['MAI_READY_PERMIT_TRUST_ROOT_PATH']
      ExpectedTrustRootSha256=$publicBindings['MAI_READY_EXPECTED_PERMIT_TRUST_ROOT_SHA256']
      ExpectedGitopsCommit=$publicBindings['MAI_READY_EXPECTED_GITOPS_COMMIT']
      ExpectedPolicySha256=$publicBindings['MAI_READY_EXPECTED_POLICY_SHA256']
      ExpectedProducerImageDigest=$publicBindings['MAI_READY_EXPECTED_PRODUCER_IMAGE_DIGEST']
      RepoRoot='C:\platform-ai'; StartupScriptPath='C:\platform-ai\deploy\gpu-host\start-meeting-ai.ps1'
      PythonExe=$servicePython; AppEnv=$publicBindings['MAI_APP_ENV']
    }
    $null = Assert-TranscriptReadyPermitFile @params -SkipFreshness
    Assert-TranscriptReadyActivationReceiptFile @params -ReceiptPath $publicBindings['MAI_READY_ACTIVATION_RECEIPT_PATH']
    $permitMetadata = @{checked=$true; valid=$true}
  } catch {
    $knownReasons = @(
      'Transcript-ready signed permit verification failed.',
      'Transcript-ready pre-enable permit host binding does not match.',
      'Transcript-ready activation receipt binding does not match.',
      'Platform-ai repository identity could not be read.',
      'Platform-ai repository worktree is not clean.',
      'Platform-ai repository worktree contains untracked deployed content.'
    )
    $reason = if ($knownReasons -contains $_.Exception.Message) { $_.Exception.Message } else { 'validation-rejected' }
    $permitMetadata = @{checked=$true; valid=$false; reason=$reason; errorClass=$_.Exception.GetType().Name}
    if ($reason -eq 'Transcript-ready signed permit verification failed.') {
      $verifyArgs = @('C:\platform-ai\deploy\gpu-host\verify-transcript-ready-permit.py',
        '--envelope', $params.PermitPath, '--trust-root', $params.TrustRootPath,
        '--expected-trust-root-sha256', $params.ExpectedTrustRootSha256,
        '--app-env', $params.AppEnv, '--expected-gitops-commit', $params.ExpectedGitopsCommit,
        '--expected-policy-sha256', $params.ExpectedPolicySha256,
        '--expected-producer-image-digest', $params.ExpectedProducerImageDigest, '--skip-freshness')
      $oldEap=$ErrorActionPreference
      try {
        . 'C:\platform-ai\deploy\gpu-host\task-action-contract.ps1'
        $psi = New-Object Diagnostics.ProcessStartInfo
        $psi.FileName=$servicePython
        $psi.Arguments=($verifyArgs | ForEach-Object { ConvertTo-GpuHostWindowsArgument -Value ([string]$_) }) -join ' '
        $psi.UseShellExecute=$false
        $psi.CreateNoWindow=$true
        $psi.RedirectStandardOutput=$true
        $psi.RedirectStandardError=$true
        $proc=New-Object Diagnostics.Process
        $proc.StartInfo=$psi
        $null=$proc.Start()
        $outRead=$proc.StandardOutput.ReadToEndAsync()
        $errRead=$proc.StandardError.ReadToEndAsync()
        if (!$proc.WaitForExit(15000)) { $proc.Kill(); throw 'Bounded permit verifier timed out.' }
        $verifierLines=@(($outRead.Result + "`n" + $errRead.Result) -split "`r?`n" | Where-Object { $_ })
        $permitMetadata.verifierExitCode=$proc.ExitCode
        $proc.Dispose()
        # This verifier receives only PUBLIC permit/trust-root paths and public
        # binding hashes. It never imports runtime secrets or meeting content.
        # Include its bounded stderr to distinguish Python/argv failures from
        # signature rejection; this is not an application log export.
        $publicDiagnostic=[string]$errRead.Result
        $permitMetadata.verifierPublicDiagnostic=$publicDiagnostic.Substring(0,[Math]::Min(2048,$publicDiagnostic.Length))
        $permitMetadata.verifierCapture='redirected-process-streams-v1'
        $permitMetadata.verifierOutputCount=$verifierLines.Count
        foreach ($entry in $verifierLines) {
          if ([string]$entry -match 'permit verification rejected: ([A-Z0-9_]{3,80})(?:\s|$)') {
            $permitMetadata.verifierReason=$Matches[1]
          }
          if ([string]$entry -match 'error: argument (--[a-z-]{1,60}):') {
            $permitMetadata.verifierArgumentError=$Matches[1]
          }
          if ([string]$entry -match 'can.t open file') { $permitMetadata.verifierScriptMissing=$true }
        }
      } finally { $ErrorActionPreference=$oldEap }
    }
  }
  $publicBindings.Clear()
}
$bindings = @()
$deadMetadata = @{checked=$false}
$deadStage='load-runtime-schema'
try {
  . 'C:\platform-ai\deploy\gpu-host\meeting-ai-runtime-env.ps1'
  . 'C:\platform-ai\deploy\gpu-host\task-action-contract.ps1'
  $storePath=[string](Read-MeetingAiConfigFile -Path $envPath)['MAI_INGESTION_STORE_PATH']
  $deadStage='validate-store-boundary'
  $null=Assert-MeetingAiRuntimePath -Path $storePath -Purpose 'Existing outbox metadata'
  # SQLite children inherit the hardened directory ACL, as in the canonical
  # runtime loader. Config-file ACL inheritance rules do not apply to the DB.
  Assert-MeetingAiAcl -Path (Split-Path -Parent $storePath) -Directory
  $deadStage='read-metadata'
  $code=@'
import json,sqlite3,sys,re
from pathlib import Path
db=sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True,timeout=3)
try:
 rows=db.execute("SELECT event_key_digest,failure_count,dead_reason,last_error_code,updated_at,redrive_count FROM meeting_transcript_ready_inbox WHERE state='DEAD' ORDER BY updated_at DESC LIMIT 10").fetchall()
 safe=[]
 for fingerprint,failures,reason,code,updated,redrives in rows:
  safe.append({'lookupFingerprint':fingerprint if re.fullmatch('[0-9a-f]{64}',str(fingerprint)) else 'invalid',
   'failureCount':int(failures),'reason':reason if reason in ('RETRY_EXHAUSTED','TERMINAL','CONFLICT','POISON') else 'unknown',
   'errorCode':code if re.fullmatch('[a-zA-Z_]{3,80}',str(code)) else 'redacted',
   'updatedAtEpoch':float(updated),'redriveCount':int(redrives)})
 print(json.dumps({'checked':True,'readOnly':True,'rows':safe}))
finally:
 db.close()
'@
  $servicePython=@($python | Where-Object task -eq 'platform-ai-meeting-ai')[0].path
  $psi=New-Object Diagnostics.ProcessStartInfo
  $psi.FileName=$servicePython
  $psi.Arguments=(@('-c',$code,$storePath) | ForEach-Object {
    ConvertTo-GpuHostWindowsArgument -Value ([string]$_)
  }) -join ' '
  $psi.UseShellExecute=$false; $psi.CreateNoWindow=$true
  $psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true
  $proc=New-Object Diagnostics.Process; $proc.StartInfo=$psi; $null=$proc.Start()
  $outRead=$proc.StandardOutput.ReadToEndAsync(); $errRead=$proc.StandardError.ReadToEndAsync()
  if (!$proc.WaitForExit(12000)) { $proc.Kill(); throw 'bounded-database-read-timeout' }
  if ($proc.ExitCode -ne 0) {
    $pythonError='unclassified'
    if ($errRead.Result -match '(?m)^(?:sqlite3\.)?([A-Za-z]+Error):') { $pythonError=$Matches[1] }
    $deadMetadata=@{checked=$false; stage=$deadStage; pythonErrorClass=$pythonError; exitCode=$proc.ExitCode}
  } else {
  $deadMetadata=$outRead.Result | ConvertFrom-Json
  }
  $proc.Dispose()
} catch { $deadMetadata=@{checked=$false; stage=$deadStage; errorClass=$_.Exception.GetType().Name} }
$readiness = @()
foreach ($port in @(8200,8300)) {
  $entry = [ordered]@{port=$port; reachable=$false}
  try {
    $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$port/ready")
    $request.Timeout=12000
    try { $response=$request.GetResponse() }
    catch [Net.WebException] {
      if (!$_.Exception.Response) { throw }
      $response=$_.Exception.Response
    }
    $entry.httpStatus=[int]$response.StatusCode
    $reader=New-Object IO.StreamReader($response.GetResponseStream())
    try { $body=$reader.ReadToEnd() | ConvertFrom-Json }
    finally { $reader.Dispose(); $response.Dispose() }
    $entry.reachable=$true
    $allowedStatuses=@('ok','loading','ready','failed','unhealthy','disabled','degraded','pending','stopping')
    if ($body.status -in $allowedStatuses) { $entry.status=$body.status }
    foreach ($key in @('streaming_preload_enabled','workers_healthy')) {
      if ($body.PSObject.Properties.Name -contains $key -and $body.$key -is [bool]) { $entry[$key]=$body.$key }
    }
    foreach ($group in @('roles','analysis_delivery','ready_consumer')) {
      if ($body.PSObject.Properties.Name -notcontains $group) { continue }
      if (!$body.$group) { continue }
      $safe=[ordered]@{}
      foreach ($key in @('ready','enabled','worker_running','redis_group_ready')) {
        if ($body.$group.PSObject.Properties.Name -contains $key -and $body.$group.$key -is [bool]) { $safe[$key]=$body.$group.$key }
      }
      foreach ($key in @('pending','in_flight','dead_letter','received','processing','outboxed',
                         'oldest_unfinished_age_sec','oldest_pending_age_sec')) {
        if ($body.$group.PSObject.Properties.Name -notcontains $key) { continue }
        $value=$body.$group.$key
        if (($value -is [int] -or $value -is [long] -or $value -is [double]) -and
            $value -ge 0 -and $value -le 1e12) { $safe[$key]=$value }
      }
      foreach ($key in @('live','final','status')) {
        if ($body.$group.PSObject.Properties.Name -notcontains $key) { continue }
        if ($body.$group.$key -in $allowedStatuses) { $safe[$key]=$body.$group.$key }
      }
      # Error codes are enumerated service codes, not exception messages.
      if ($body.$group.PSObject.Properties.Name -contains 'error_code' -and
          $body.$group.error_code -cmatch '^[A-Z][A-Z0-9_]{2,80}$') {
        $safe.error_code=$body.$group.error_code
      }
      $entry[$group]=$safe
    }
  } catch { $entry.errorClass=$_.Exception.GetType().Name }
  $readiness += $entry
}
$config = [IO.File]::ReadAllText('C:\caddy\Caddyfile')
foreach ($line in ($config -split "`n")) {
  if ($line -match '^\s*tls\s+(\S+)\s+(\S+)\s*\{?\s*$') {
    $bindings += @{certificatePath=$Matches[1]; privateKeyPath=$Matches[2]}
  }
}
$result = [ordered]@{schemaVersion='faz24.gpuMtlsMetadata.v1'; runtimeMutation=$false
  privateMaterialRead=$false; rawConfigIncluded=$false; utc=[DateTime]::UtcNow.ToString('o')
  certificates=$certs; keyFileNames=$keys; tasks=$tasks; listeners=$listeners
  tlsBindings=$bindings; opensslAvailable=[bool]$openssl; toolFiles=$tools; pythonExecutables=$python
  caddyAdminDisabled=[bool]($config -match '(?m)^\s*admin\s+off\s*$')
  runtimeTasks=$runtimeTasks; startupLogMetadata=$startupLogs; rawLogsIncluded=$false
  startupPermitValidation=$permitMetadata; dependencyReadiness=$readiness; deadLetterMetadata=$deadMetadata}
$result['netstatComparison']=$netstatMetadata
Write-Output ('GPU_MTLS_METADATA:' + ($result | ConvertTo-Json -Depth 8 -Compress))
"""


def governed_ssh_paths():
    config = Path('/home/aiadmin/.ssh/config')
    resolved = subprocess.run(['ssh', '-F', str(config), '-G', 'denetim-pc'],
                              capture_output=True, text=True, timeout=10, check=False)
    if resolved.returncode:
        raise RuntimeError('governed-ssh-config-unavailable')
    fields = {}
    for line in resolved.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            fields.setdefault(parts[0].lower(), parts[1])
    if fields.get('hostname') != '10.99.0.2' or fields.get('user') != 'denetimpc':
        raise RuntimeError('unexpected-governed-ssh-target')
    identity = Path(os.path.expanduser(fields.get('identityfile', '')))
    known_hosts = Path(os.path.expanduser(fields.get('userknownhostsfile', '').split(' ')[0]))
    if 'id_denetim' not in identity.name or not identity.is_file() or stat.S_IMODE(identity.stat().st_mode) != 0o600:
        raise RuntimeError('governed-ssh-identity-metadata-invalid')
    pin = subprocess.run(['ssh-keygen', '-F', '10.99.0.2', '-f', str(known_hosts)],
                         capture_output=True, text=True, timeout=10, check=False)
    if pin.returncode:
        raise RuntimeError('governed-host-key-pin-missing')
    return config, known_hosts


def collect():
    config, known_hosts = governed_ssh_paths()
    result = subprocess.run(ssh_command(config, known_hosts), input=encode_remote_input(REMOTE_SCRIPT),
                            capture_output=True, text=True, timeout=60, check=False)
    records = [line.removeprefix('GPU_MTLS_METADATA:') for line in result.stdout.splitlines()
               if line.startswith('GPU_MTLS_METADATA:')]
    if result.returncode or len(records) != 1:
        # Deliberately do not forward raw SSH/PowerShell output.
        return {'status': 'read-failed', 'exitCode': result.returncode,
                'stdoutBytes': len(result.stdout), 'stderrBytes': len(result.stderr)}
    return json.loads(records[0])


if __name__ == '__main__':
    try:
        print(json.dumps(collect(), sort_keys=True))
    except Exception as error:
        print(json.dumps({'status': 'error', 'errorClass': type(error).__name__}))
        raise SystemExit(1)
