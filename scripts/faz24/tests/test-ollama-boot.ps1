# Offline behavioral tests: no tasks, daemon, model, network or Windows mutation.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\test-ollama-boot.ps1')
$script:Checks = 0
function Assert-True($Value, [string]$Message) {
    if (-not $Value) { throw $Message }
    $script:Checks++
}
function Assert-Throws([scriptblock]$Action, [string]$Message) {
    $caught = $false
    try { & $Action | Out-Null } catch { $caught = $true }
    Assert-True $caught $Message
}
function Test-Values {
    return @{
        ExecutablePath = 'C:\Users\tester\Local Programs\ollama.exe'
        ExecutableSha256 = 'a' * 64; SignerThumbprint = 'b' * 40
        LauncherPath = 'C:\Users\tester\review\test-ollama-boot.ps1'
        LauncherSha256 = 'c' * 64; ModelStore = 'C:\Users\tester\.ollama\models'
        RuntimeHome = 'C:\Users\tester\ollama-home'
        ModelManifestPath = 'C:\Users\tester\.ollama\models\manifests\qwen\27b'
        ModelManifestSha256 = 'd' * 64; RunAsUserSid = 'S-1-5-21-11-22-33-1002'
    }
}

Assert-Throws { New-OllamaBootConfig (Test-Values) } 'Missing test flag must fail.'
$config = New-OllamaBootConfig (Test-Values) -TestOnly
foreach ($sid in @('S-1-5-18', 'SYSTEM', 'S-1-5-19', 'S-1-5-20')) {
    $v = Test-Values; $v.RunAsUserSid = $sid
    Assert-Throws { New-OllamaBootConfig $v -TestOnly } 'Service identities must fail.'
}
foreach ($path in @('relative.exe', '\\server\file.exe', 'C:\x\..\bad.exe',
        'C:\x\evil".exe', 'C:\x\a.exe:stream', 'C:\x\a*.exe', 'C:\x\', 'C:\%TEMP%\a.exe')) {
    $v = Test-Values; $v.ExecutablePath = $path
    Assert-Throws { New-OllamaBootConfig $v -TestOnly } 'Unsafe path must fail.'
}
$v = Test-Values; $v.ModelManifestPath = 'C:\different\manifest'
Assert-Throws { New-OllamaBootConfig $v -TestOnly } 'Unrelated manifest must fail.'
$v = Test-Values; $v.ExecutableSha256 = 'wrong'
Assert-Throws { New-OllamaBootConfig $v -TestOnly } 'Unpinned executable must fail.'

# Exercise artifact validation with real local files and a fake Authenticode result.
$root = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root) | Out-Null
try {
    $file = Join-Path $root 'artifact'
    [IO.File]::WriteAllText($file, 'synthetic artifact')
    $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-OllamaFileHash $file $hash
    Assert-Throws { Assert-OllamaFileHash $file ('0' * 64) } 'Hash mismatch must fail.'
    Assert-Throws { Assert-OllamaFileHash (Join-Path $root 'missing') $hash } 'Missing artifact must fail.'
    function Get-AuthenticodeSignature {
        return [pscustomobject]@{ Status = $script:SignatureStatus
            SignerCertificate = [pscustomobject]@{ Thumbprint = $script:SignatureThumbprint } }
    }
    $script:SignatureStatus = 'Valid'; $script:SignatureThumbprint = 'b' * 40
    $artifactConfig = [pscustomobject]@{
        ExecutablePath = $file; LauncherPath = $file; ModelManifestPath = $file
        ModelStore = $root; RuntimeHome = $root; ExecutableSha256 = $hash; LauncherSha256 = $hash
        ModelManifestSha256 = $hash; SignerThumbprint = 'b' * 40
    }
    Assert-OllamaArtifacts $artifactConfig
    $script:SignatureStatus = 'NotSigned'
    Assert-Throws { Assert-OllamaArtifacts $artifactConfig } 'Unsigned executable must fail.'
    $script:SignatureStatus = 'Valid'; $script:SignatureThumbprint = 'e' * 40
    Assert-Throws { Assert-OllamaArtifacts $artifactConfig } 'Wrong signer must fail.'
} finally { [IO.Directory]::Delete($root, $true) }

function Get-OllamaPowerShellPath { return 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' }
$expected = New-OllamaTaskXml $config
Assert-True ($expected.Contains('&quot;-ExecutablePath&quot; &quot;C:\Users\tester\Local Programs\ollama.exe&quot;')) 'Parameter names and values must be separate argv tokens.'
Assert-OllamaTaskDefinition $expected $expected
$normalized = $expected.Replace('<RunLevel>LeastPrivilege</RunLevel>', '').Replace('<Enabled>true</Enabled>', '').Replace('<Priority>7</Priority>', '').Replace('<AllowHardTerminate>true</AllowHardTerminate>', '')
Assert-OllamaTaskDefinition $normalized $expected
$script:Checks++
Assert-Throws { Assert-OllamaTaskDefinition ($normalized.Replace('<Principal id="User">', '<Principal id="User"><RunLevel>HighestAvailable</RunLevel>')) $expected } 'An explicit elevated run level must still fail.'
Assert-Throws { Assert-OllamaTaskDefinition ($normalized.Replace('<BootTrigger>', '<BootTrigger><Enabled>false</Enabled>')) $expected } 'An explicit disabled trigger must still fail.'
$reordered = $expected.Replace('<LogonType>S4U</LogonType><RunLevel>LeastPrivilege</RunLevel>',
    '<RunLevel>LeastPrivilege</RunLevel><LogonType>S4U</LogonType>')
Assert-OllamaTaskDefinition $reordered $expected
$script:Checks++
Assert-True ($expected.Contains('<LogonType>S4U</LogonType>')) 'S4U must be explicit.'
Assert-True ($expected.Contains('<RunLevel>LeastPrivilege</RunLevel>')) 'Limited task required.'
Assert-True (-not $expected.Contains('ExecutionPolicy')) 'Do not override execution policy.'
Assert-True ($expected.Contains('<BootTrigger>')) 'Boot trigger required.'
Assert-True ($expected.Contains('<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>')) 'No task time limit.'
Assert-True ($expected.Contains('<Count>999</Count>')) 'Restart policy required.'
foreach ($pair in @(
        @('S4U', 'Password'), @('LeastPrivilege', 'HighestAvailable'),
        @('PT1M', 'PT10M'), @('PT0S', 'PT72H'),
        @($script:OllamaTaskOwner, 'other owner'), @('BootTrigger', 'LogonTrigger'),
        @('IgnoreNew', 'Parallel'), @('27b', 'another-model'))) {
    $changed = $expected.Replace($pair[0], $pair[1])
    Assert-Throws { Assert-OllamaTaskDefinition $changed $expected } 'Definition drift must fail.'
}
$extra = $expected.Replace('</Actions>', '<Exec><Command>evil.exe</Command></Exec></Actions>')
Assert-Throws { Assert-OllamaTaskDefinition $extra $expected } 'Extra action must fail.'
Assert-Throws { Read-OllamaTaskXml '<!DOCTYPE Task [<!ENTITY x SYSTEM "file:///x">]><Task/>' } 'DTD must fail.'

# Mock only operating-system boundaries; execute the real install/readback workflow.
function Assert-OllamaPlatform { }
function Get-OllamaCurrentSid { return $script:CurrentSid }
function Assert-OllamaArtifacts { $script:ArtifactChecks++ }
function Get-OllamaExistingTask {
    if ($null -ne $script:StoredXml) { return [pscustomobject]@{ TaskName = $script:OllamaTaskName } }
}
function Register-ScheduledTask {
    param($TaskName, $TaskPath, $Xml, $ErrorAction)
    $script:RegisterCalls++; $script:StoredXml = $Xml
}
function Export-ScheduledTask { return $script:StoredXml }
function Start-ScheduledTask { throw 'Installation must never start a task.' }
$script:CurrentSid = $config.RunAsUserSid; $script:StoredXml = $null
$script:RegisterCalls = 0; $script:ArtifactChecks = 0
Assert-Throws { Install-OrVerifyOllamaTask $config 'Verify' } 'Verify cannot install a missing task.'
$result = Install-OrVerifyOllamaTask $config 'Install'
Assert-True ($result.DefinitionVerified -and -not $result.StartRequested) 'Install readback without start.'
Assert-True ($script:RegisterCalls -eq 1) 'Create exactly one task.'
$result = Install-OrVerifyOllamaTask $config 'Install'
Assert-True ($script:RegisterCalls -eq 1) 'Matching install must be idempotent.'
$script:StoredXml = $expected.Replace('PT1M', 'PT10M')
Assert-Throws { Install-OrVerifyOllamaTask $config 'Install' } 'Collision must not be overwritten.'
Assert-True ($script:RegisterCalls -eq 1) 'Collision does not register.'
$script:StoredXml = $null
function Export-ScheduledTask { return $expected.Replace('S4U', 'Password') }
Assert-Throws { Install-OrVerifyOllamaTask $config 'Install' } 'Incorrect authoritative readback must fail.'
$script:CurrentSid = 'S-1-5-18'
Assert-Throws { Install-OrVerifyOllamaTask $config 'Install' } 'SYSTEM cannot provision for the user.'
Assert-Throws { Invoke-OllamaTestServer $config } 'SYSTEM cannot launch user-writable executable.'
$script:CurrentSid = 'S-1-5-21-11-22-33-1003'
function Test-OllamaElevated { return $false }
Assert-Throws { Install-OrVerifyOllamaTask $config 'Install' } 'Another unprivileged user cannot provision.'
function Test-OllamaElevated { return $true }
$script:StoredXml = $null
Assert-Throws { Install-OrVerifyOllamaTask $config 'Install' } 'Cross-account registration needs an in-memory credential.'
function Export-ScheduledTask { return $script:StoredXml }
function Register-OllamaTask($Config, [string]$Xml, [Security.SecureString]$RegistrationPassword) {
    Assert-True ($null -ne $RegistrationPassword) 'Registration keeps a SecureString boundary.'
    $script:StoredXml = $Xml
}
$testCredential = ConvertTo-SecureString 'synthetic-fixture-only' -AsPlainText -Force
try {
    $result = Install-OrVerifyOllamaTask $config 'Install' $testCredential
    Assert-True ($result.DefinitionVerified -and -not $result.StartRequested) 'Admin can provision the isolated low-privilege account without starting it.'
} finally { $testCredential.Dispose() }
$script:CurrentSid = $config.RunAsUserSid
function Test-OllamaElevated { return $true }
Assert-Throws { Invoke-OllamaTestServer $config } 'Elevated launch must fail before artifact execution.'

# Exercise real Windows native stderr/exit propagation without a daemon.
if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
    $nativeRoot = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($nativeRoot) | Out-Null
    try {
        $nativeFile = Join-Path $nativeRoot 'fake server.cmd'
        [IO.File]::WriteAllText($nativeFile, "@echo off`r`necho synthetic-diagnostic 1>&2`r`nexit /b 7`r`n")
        Assert-True ((Invoke-OllamaNativeServer $nativeFile) -eq 7) 'Native stderr must not hide the child exit code.'
        [IO.File]::WriteAllText($nativeFile, "@echo off`r`necho synthetic-diagnostic 1>&2`r`nexit /b 0`r`n")
        Assert-True ((Invoke-OllamaNativeServer $nativeFile) -eq 0) 'Native diagnostic output must not turn success into a PowerShell exception.'
    } finally { [IO.Directory]::Delete($nativeRoot, $true) }
}

# Run the lifecycle against a synthetic child script, never against Ollama.
function Invoke-OllamaNativeServer([string]$ExecutablePath) {
    & $ExecutablePath serve
    return $LASTEXITCODE
}
function Test-OllamaElevated { return $false }
function Get-NetTCPConnection {
    if ($script:PortBusy) { return [pscustomobject]@{ LocalPort = 11434 } }
}
$root = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root) | Out-Null
try {
    $fake = Join-Path $root 'fake-server.ps1'
    [IO.File]::WriteAllText($fake, @'
param($Command)
if ($Command -ne 'serve' -or $env:OLLAMA_HOST -ne '127.0.0.1:11434' -or
    $env:OLLAMA_NOPRUNE -ne 'true' -or $env:OLLAMA_DEBUG -ne 'false') { throw 'Wrong child contract' }
$global:OllamaInvoked++
exit 7
'@)
    $runConfig = [pscustomobject]@{
        RunAsUserSid = $config.RunAsUserSid; ExecutablePath = $fake
        LauncherPath = $fake; ModelManifestPath = $fake; ModelStore = $root; RuntimeHome = $root
    }
    $script:PortBusy = $true; $global:OllamaInvoked = 0
    Assert-Throws { Invoke-OllamaTestServer $runConfig } 'Port collision must fail.'
    Assert-True ($global:OllamaInvoked -eq 0) 'Port collision cannot execute child.'
    $script:PortBusy = $false
    $env:OLLAMA_DEBUG = 'true'; $env:OLLAMA_HOST = '0.0.0.0:1234'
    $env:OLLAMA_UNAPPROVED = 'inherited'
    Assert-Throws { Invoke-OllamaTestServer $runConfig } 'Child nonzero exit must fail task.'
    Assert-True ($global:OllamaInvoked -eq 1) 'Exactly one synthetic serve child.'
    Assert-True ($env:OLLAMA_MODELS -eq $root) 'Use the explicit existing store.'
    Assert-True ($env:USERPROFILE -eq $root -and $env:HOME -eq $root) 'Use only the isolated writable home.'
    Assert-True ($null -eq [Environment]::GetEnvironmentVariable('OLLAMA_UNAPPROVED')) 'Clear inherited Ollama overrides.'
} finally { [IO.Directory]::Delete($root, $true) }
Write-Output "PASS: $script:Checks offline checks; no Windows task or daemon was started."
# Negative child fixtures intentionally leave LASTEXITCODE nonzero. Only a
# completed assertion suite reports success to the GitHub PowerShell wrapper.
exit 0
