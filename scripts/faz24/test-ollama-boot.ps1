# TEST-only Ollama dependency for GitOps #3790. Install never starts the task.
# Keep the approved model store and meeting-ai runtime configuration unchanged.
# Run this file with Windows PowerShell 5.1. Dot-sourcing only loads functions.
[CmdletBinding()]
param(
    [ValidateSet('Verify', 'Install', 'Run')][string]$Mode = 'Verify',
    [switch]$TestOnly,
    [string]$ExecutablePath = '',
    [string]$ExecutableSha256 = '',
    [string]$SignerThumbprint = '',
    [string]$LauncherSha256 = '',
    [string]$ModelStore = '',
    [string]$RuntimeHome = '',
    [string]$ModelManifestPath = '',
    [string]$ModelManifestSha256 = '',
    [string]$RunAsUserSid = '',
    [Security.SecureString]$RegistrationPassword
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:OllamaTaskName = 'platform-ai-ollama-test'
$script:OllamaTaskOwner = 'platform-ai-ollama-test/v1; tracked-by=gitops#3790'
$script:OllamaStage = 'configuration'

function Assert-OllamaLocalPath([string]$Path) {
    if ($Path -notmatch '^[A-Za-z]:\\' -or $Path.Substring(2) -match '[\x00-\x1f"<>|?*:%]' -or
        @($Path.Split('\') | Where-Object { $_ -in @('.', '..', '') }).Count -gt 0 -or
        $Path.EndsWith('\') -or $Path -match '/') {
        throw 'Expected an absolute local path without ambiguous components.'
    }
}

function Get-OllamaCurrentSid {
    return [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
}

function Test-OllamaElevated {
    $principal = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-OllamaPlatform {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'Windows is required; no remote or portable execution fallback.'
    }
}

function Assert-OllamaNoReparse([string]$Path) {
    $current = Get-Item -LiteralPath $Path -Force
    while ($null -ne $current) {
        if (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Reparse paths are not allowed.'
        }
        if ($current -is [IO.DirectoryInfo]) { $current = $current.Parent }
        else { $current = $current.Directory }
    }
}

function Assert-OllamaFileHash([string]$Path, [string]$Expected) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Expected) {
        throw 'Pinned local artifact hash mismatch.'
    }
}

function Assert-OllamaArtifacts($Config) {
    $script:OllamaStage = 'artifact_paths'
    foreach ($path in @($Config.ExecutablePath, $Config.LauncherPath,
            $Config.ModelStore, $Config.ModelManifestPath, $Config.RuntimeHome)) {
        Assert-OllamaNoReparse $path
    }
    if (-not (Test-Path -LiteralPath $Config.ModelStore -PathType Container)) {
        throw 'The existing model store must be a directory.'
    }
    if (-not (Test-Path -LiteralPath $Config.RuntimeHome -PathType Container)) {
        throw 'The isolated runtime home must already exist.'
    }
    $script:OllamaStage = 'executable_hash'
    Assert-OllamaFileHash $Config.ExecutablePath $Config.ExecutableSha256
    $script:OllamaStage = 'launcher_hash'
    Assert-OllamaFileHash $Config.LauncherPath $Config.LauncherSha256
    $script:OllamaStage = 'model_manifest_hash'
    Assert-OllamaFileHash $Config.ModelManifestPath $Config.ModelManifestSha256
    $script:OllamaStage = 'executable_signature'
    $signature = Get-AuthenticodeSignature -LiteralPath $Config.ExecutablePath
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
        $signature.SignerCertificate.Thumbprint.ToLowerInvariant() -cne $Config.SignerThumbprint) {
        throw 'Executable signature or pinned signer mismatch.'
    }
}

function New-OllamaBootConfig {
    param([hashtable]$Values, [switch]$TestOnly)
    if (-not $TestOnly) { throw 'Explicit -TestOnly is required.' }
    foreach ($key in @('ExecutablePath', 'LauncherPath', 'ModelStore', 'ModelManifestPath', 'RuntimeHome')) {
        Assert-OllamaLocalPath ([string]$Values[$key])
    }
    foreach ($key in @('ExecutableSha256', 'LauncherSha256', 'ModelManifestSha256')) {
        if ([string]$Values[$key] -cnotmatch '^[a-f0-9]{64}$') { throw 'Expected a lowercase SHA256 pin.' }
    }
    if ([string]$Values.SignerThumbprint -cnotmatch '^[a-f0-9]{40}$') {
        throw 'Expected a lowercase signer certificate thumbprint.'
    }
    if ([string]$Values.RunAsUserSid -notmatch '^S-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+$') {
        throw 'A local user SID is required; SYSTEM and service identities are forbidden.'
    }
    if (-not ([string]$Values.ModelManifestPath).StartsWith(
            ([string]$Values.ModelStore + '\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Manifest must be inside the existing model store.'
    }
    return [pscustomobject]$Values
}

function ConvertTo-OllamaXml([string]$Value) {
    return [Security.SecurityElement]::Escape($Value)
}

function Get-OllamaPowerShellPath {
    return Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\powershell.exe'
}

function New-OllamaTaskXml($Config) {
    $tokens = @('-NoProfile', '-NonInteractive',
        '-File', $Config.LauncherPath, '-Mode', 'Run', '-TestOnly')
    foreach ($key in @('ExecutablePath', 'ExecutableSha256', 'SignerThumbprint',
            'LauncherSha256', 'ModelStore', 'RuntimeHome', 'ModelManifestPath', 'ModelManifestSha256', 'RunAsUserSid')) {
        $tokens += @(('-' + $key), [string]$Config.$key)
    }
    # Path validation excludes quotes, control characters and trailing slashes.
    $arguments = ($tokens | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $command = Get-OllamaPowerShellPath
    $description = ConvertTo-OllamaXml $script:OllamaTaskOwner
    $sid = ConvertTo-OllamaXml $Config.RunAsUserSid
    $command = ConvertTo-OllamaXml $command
    $arguments = ConvertTo-OllamaXml $arguments
    return @"
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>$description</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
  <Principals><Principal id="User"><UserId>$sid</UserId><LogonType>S4U</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="User"><Exec><Command>$command</Command><Arguments>$arguments</Arguments></Exec></Actions>
</Task>
"@
}

function Read-OllamaTaskXml([string]$Xml) {
    $document = New-Object Xml.XmlDocument
    $document.XmlResolver = $null
    if ($Xml -match '<!DOCTYPE|<!ENTITY') { throw 'DTD is forbidden.' }
    $document.LoadXml($Xml)
    return ,$document
}

function ConvertTo-OllamaXmlShape($Node) {
    $attributes = @($Node.Attributes | Where-Object { $_.Name -notmatch '^xmlns(:|$)' } |
        ForEach-Object { $_.LocalName + '=' + $_.Value } | Sort-Object)
    $children = @($Node.ChildNodes | Where-Object { $_ -is [Xml.XmlElement] })
    $content = if ($children.Count -gt 0) {
        (@($children | ForEach-Object { ConvertTo-OllamaXmlShape $_ } | Sort-Object) -join '|')
    } else { $Node.InnerText }
    return ConvertTo-Json -Compress -Depth 8 -InputObject ([ordered]@{
        name = $Node.LocalName; ns = $Node.NamespaceURI
        attributes = $attributes; content = $content
    })
}

function Assert-OllamaTaskDefinition([string]$Actual, [string]$Expected) {
    $actualDoc = Read-OllamaTaskXml $Actual
    $expectedDoc = Read-OllamaTaskXml $Expected
    # Scheduler exports omit schema defaults. Restore only known defaults,
    # never a missing identity, action, trigger, owner or nondefault policy.
    $defaults = @{
        Principal = @{ RunLevel = 'LeastPrivilege' }
        BootTrigger = @{ Enabled = 'true' }
        Settings = @{ AllowHardTerminate = 'true'; AllowStartOnDemand = 'true'
            Enabled = 'true'; Hidden = 'false'; RunOnlyIfNetworkAvailable = 'false'
            RunOnlyIfIdle = 'false'; WakeToRun = 'false'; Priority = '7' }
    }
    foreach ($doc in @($actualDoc, $expectedDoc)) {
        foreach ($parentName in $defaults.Keys) {
            foreach ($parentNode in $doc.SelectNodes("//*[local-name()='$parentName']")) {
                foreach ($name in $defaults[$parentName].Keys) {
                    if ($null -eq $parentNode.SelectSingleNode("*[local-name()='$name']")) {
                        $child = $doc.CreateElement($name, $parentNode.NamespaceURI)
                        $child.InnerText = $defaults[$parentName][$name]
                        $parentNode.AppendChild($child) | Out-Null
                    }
                }
            }
        }
    }
    # Compare critical subtrees semantically; scheduler-added RegistrationInfo fields
    # and root schema version do not alter execution. Added actions/triggers do.
    foreach ($section in @('Triggers', 'Principals', 'Actions')) {
        $a = $actualDoc.SelectNodes("/*[local-name()='Task']/*[local-name()='$section']")
        $e = $expectedDoc.SelectSingleNode("/*[local-name()='Task']/*[local-name()='$section']")
        if ($a.Count -ne 1 -or (ConvertTo-OllamaXmlShape $a[0]) -cne (ConvertTo-OllamaXmlShape $e)) {
            throw 'Task definition collision: execution contract differs.'
        }
    }
    foreach ($node in $expectedDoc.SelectNodes("//*[local-name()='Settings']//*[not(*)] | //*[local-name()='Description']")) {
        $parent = $node.ParentNode.LocalName
        $path = "//*[local-name()='$parent']/*[local-name()='$($node.LocalName)']"
        $actualNodes = $actualDoc.SelectNodes($path)
        if ($actualNodes.Count -ne 1 -or $actualNodes[0].InnerText -cne $node.InnerText) {
            throw 'Task definition collision: owner or scheduling policy differs.'
        }
    }
}

function Get-OllamaExistingTask {
    # Enumerate the root task folder so access/read errors never mean "not found".
    return @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop |
        Where-Object { $_.TaskName -eq $script:OllamaTaskName })
}

function Register-OllamaTask($Config, [string]$Xml, [Security.SecureString]$RegistrationPassword) {
    if ($null -eq $RegistrationPassword) {
        Register-ScheduledTask -TaskName $script:OllamaTaskName -TaskPath '\' -Xml $Xml -ErrorAction Stop | Out-Null
        return
    }
    # Windows requires credentials when an admin registers another user's S4U
    # task. Supply only in memory to COM; S4U stores no logon password.
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($RegistrationPassword)
    try {
        $service.GetFolder('\').RegisterTask($script:OllamaTaskName, $Xml, 2,
            $Config.RunAsUserSid, [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer), 2, $null) | Out-Null
    } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function Install-OrVerifyOllamaTask($Config, [string]$Mode, [Security.SecureString]$RegistrationPassword) {
    $script:OllamaStage = 'provision_identity'
    Assert-OllamaPlatform
    $operatorSid = Get-OllamaCurrentSid
    if ($operatorSid -cne $Config.RunAsUserSid -and
        ($operatorSid -notmatch '^S-1-5-21-' -or -not (Test-OllamaElevated))) {
        throw 'Provisioning requires the selected user or a local administrative operator.'
    }
    Assert-OllamaArtifacts $Config
    $script:OllamaStage = 'task_definition'
    $expected = New-OllamaTaskXml $Config
    $existing = @(Get-OllamaExistingTask)
    if ($existing.Count -gt 1) { throw 'Ambiguous existing task.' }
    if ($existing.Count -eq 0) {
        if ($Mode -ne 'Install') { throw 'Owned task does not exist.' }
        if ($operatorSid -cne $Config.RunAsUserSid -and $null -eq $RegistrationPassword) {
            throw 'Cross-account S4U registration requires an in-memory credential.'
        }
        $script:OllamaStage = 'task_registration'
        Register-OllamaTask $Config $expected $RegistrationPassword
    } else {
        Assert-OllamaTaskDefinition (Export-ScheduledTask -TaskName $script:OllamaTaskName -TaskPath '\' -ErrorAction Stop) $expected
    }
    $script:OllamaStage = 'task_readback'
    $readback = Export-ScheduledTask -TaskName $script:OllamaTaskName -TaskPath '\' -ErrorAction Stop
    Assert-OllamaTaskDefinition $readback $expected
    Assert-OllamaArtifacts $Config
    [pscustomobject]@{ Task = $script:OllamaTaskName; DefinitionVerified = $true; StartRequested = $false; ModelManifestPreserved = $true }
}

function Invoke-OllamaNativeServer([string]$ExecutablePath) {
    Assert-OllamaLocalPath $ExecutablePath
    $command = Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\cmd.exe'
    # Native stderr becomes a terminating error in Windows PowerShell 5.1.
    # Drain both streams at cmd level, without recording model/runtime content.
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $command
    $start.Arguments = '/d /v:off /s /c ""' + $ExecutablePath + '" serve >NUL 2>&1"'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $process = [Diagnostics.Process]::Start($start)
    try {
        $process.WaitForExit()
        return $process.ExitCode
    } finally { $process.Dispose() }
}

function Invoke-OllamaTestServer($Config) {
    $script:OllamaStage = 'runtime_identity'
    Assert-OllamaPlatform
    if ((Get-OllamaCurrentSid) -cne $Config.RunAsUserSid -or (Test-OllamaElevated)) {
        throw 'Ollama must run as the selected non-elevated local user.'
    }
    $handles = @()
    try {
        $script:OllamaStage = 'artifact_read_locks'
        # Deny replacement/write for the checked executable, launcher and manifest
        # throughout this server lifetime. No model or credential file is changed.
        foreach ($path in @($Config.ExecutablePath, $Config.LauncherPath, $Config.ModelManifestPath)) {
            $handles += [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        }
        Assert-OllamaArtifacts $Config
        $script:OllamaStage = 'listener_collision'
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
            Where-Object { $_.LocalPort -eq 11434 })
        if ($listeners.Count -gt 0) { throw 'Port 11434 is already owned; refusing a second server.' }
        Get-ChildItem Env: | Where-Object { $_.Name -like 'OLLAMA_*' } |
            ForEach-Object { [Environment]::SetEnvironmentVariable($_.Name, $null, 'Process') }
        $env:OLLAMA_HOST = '127.0.0.1:11434'
        $env:OLLAMA_MODELS = $Config.ModelStore
        $env:OLLAMA_NOPRUNE = 'true'
        $env:OLLAMA_DEBUG = 'false'
        $env:USERPROFILE = $Config.RuntimeHome
        $env:HOME = $Config.RuntimeHome
        $script:OllamaStage = 'serve_process'
        $code = Invoke-OllamaNativeServer $Config.ExecutablePath
        if ($code -ne 0) { throw 'Owned Ollama server exited unsuccessfully.' }
        # A server should remain running until the task is stopped. Unexpected
        # clean exit must also activate Task Scheduler's restart policy.
        throw 'Owned Ollama server exited unexpectedly.'
    } finally {
        foreach ($handle in $handles) { $handle.Dispose() }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
    $values = @{
        ExecutablePath = $ExecutablePath; ExecutableSha256 = $ExecutableSha256
        SignerThumbprint = $SignerThumbprint; LauncherPath = $PSCommandPath
        LauncherSha256 = $LauncherSha256; ModelStore = $ModelStore; RuntimeHome = $RuntimeHome
        ModelManifestPath = $ModelManifestPath; ModelManifestSha256 = $ModelManifestSha256
        RunAsUserSid = $RunAsUserSid
    }
    $config = New-OllamaBootConfig -Values $values -TestOnly:$TestOnly
    if ($Mode -eq 'Run') { Invoke-OllamaTestServer $config }
    else { Install-OrVerifyOllamaTask $config $Mode $RegistrationPassword }
    } catch {
        # Only a fixed stage code reaches diagnostics, never exception bodies,
        # arguments, identities, credentials, model content or transcripts.
        [Console]::Error.WriteLine('OLLAMA_TEST_BOOT_FAILURE stage=' + $script:OllamaStage)
        try {
            Assert-OllamaLocalPath $RuntimeHome
            $failurePath = Join-Path $RuntimeHome 'ollama-test-failure.json'
            Assert-OllamaNoReparse (Split-Path -Parent $failurePath)
            if (Test-Path -LiteralPath $failurePath) { Assert-OllamaNoReparse $failurePath }
            $diagnostic = [ordered]@{ stage = $script:OllamaStage; at = [DateTime]::UtcNow.ToString('o') }
            [IO.File]::WriteAllText($failurePath, (ConvertTo-Json -Compress -InputObject $diagnostic))
        } catch { }
        exit 1
    }
}
