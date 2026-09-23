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
foreach ($name in @('platform-ai-live-stt', 'platform-ai-meeting-ai')) {
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  foreach ($action in @($task.Actions)) {
    if ($action.Arguments -match '-PythonExe\s+"([^"]+)"') {
      $path = $Matches[1]
      $python += @{task=$name; path=$path; present=(Test-Path -LiteralPath $path -PathType Leaf)}
    }
  }
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
  caddyAdminDisabled=[bool]($config -match '(?m)^\s*admin\s+off\s*$')}
Write-Output ('GPU_MTLS_METADATA:' + ($result | ConvertTo-Json -Depth 8 -Compress))
"""


def collect():
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
