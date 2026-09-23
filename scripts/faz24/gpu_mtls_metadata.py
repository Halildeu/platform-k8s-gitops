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
  Where-Object { $_.LocalPort -in @(8243,8244,8300) } |
  ForEach-Object { @{port=$_.LocalPort; localAddress=$_.LocalAddress} })
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
  pathMissing='Cannot find path'
  commandMissing='is not recognized as the name'
  powershellParseError='ParserError'
  parameterError='ParameterBindingException'
  legacyConfigRejected='env.local.ps1'
  modelManifestRejected='model manifest'
  pinnedModelMissing='pinned streaming model directory'
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
      foreach ($line in $lines) {
        if ($line -match '^\s*File "[^"]+[\\/]([A-Za-z_][A-Za-z0-9_]{0,80}\.py)", line ([0-9]{1,6}), in ([A-Za-z_][A-Za-z0-9_]{0,80})\s*$') {
          $frames += @{module=$Matches[1]; line=[int]$Matches[2]; function=$Matches[3]}
        }
        if ($line -match '\[WinError ([0-9]{1,8})\]') { $winErrors += [int]$Matches[1] }
      }
      $startupLogs += [ordered]@{service=($pattern.Split('-')[0]); bytes=$file.Length
        modifiedUtc=$file.LastWriteTimeUtc.ToString('o'); readable=$true; markerCounts=$counts
        tracebackFrames=@($frames | Select-Object -Last 16); winErrorCodes=@($winErrors | Select-Object -Unique)}
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
  }
  $publicBindings.Clear()
}
$bindings = @()
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
  startupPermitValidation=$permitMetadata}
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
