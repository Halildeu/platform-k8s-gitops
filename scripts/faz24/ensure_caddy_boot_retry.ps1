# gitops#3807 — TEST GPU host: make the I7 app-mTLS Caddy task survive a reboot.
#
# 2026-09-15: after a reboot caddy.exe started before WireGuard assigned 10.99.0.2,
# exited 1 on the bind error and never came back. Task Scheduler's RestartOnFailure
# only covers a failed *launch*, not a non-zero exit, so the existing "5 x 1 min"
# setting never fired. The duplicate Workcube-Caddy-mTLS task (same Caddyfile, also a
# boot trigger) failed the same way.
#
# Fix without touching the owned action (renew_test_live_mtls.ps1 stops/starts this
# exact task and expects the duplicate to stay stopped):
#   - boot trigger delayed by PT1M (WireGuard's own boot task waits PT30S),
#   - a 5-minute re-launch trigger; MultipleInstancesPolicy IgnoreNew makes it a
#     no-op while Caddy runs and brings Caddy back within 5 minutes after any exit,
#   - the duplicate task stays disabled (never deleted).
#
# Usage (Windows PowerShell 5.1, elevated): -Mode Verify (default, read-only) | -Mode Apply
# Dot-sourcing only loads the functions (used by tests/faz24/test_caddy_boot_retry_contract.py).
[CmdletBinding()]
param([ValidateSet('Verify', 'Apply')][string]$Mode = 'Verify')

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:CaddyTaskName = 'CaddyI7AppMtls'
$script:CaddyDuplicateTaskName = 'Workcube-Caddy-mTLS'
$script:CaddyBootDelay = 'PT1M'
$script:CaddyRepeatInterval = 'PT5M'
$script:CaddyRepeatDuration = 'P3650D'
$script:CaddyTaskNamespace = 'http://schemas.microsoft.com/windows/2004/02/mit/task'

function Read-CaddyTaskXml([string]$Xml) {
    $document = New-Object Xml.XmlDocument
    $document.XmlResolver = $null
    $document.LoadXml($Xml)
    $manager = New-Object Xml.XmlNamespaceManager($document.NameTable)
    $manager.AddNamespace('t', $script:CaddyTaskNamespace)
    return @{ Document = $document; Manager = $manager }
}

function Get-CaddyNodeText($Parent, [string]$Path, $Manager) {
    $node = $Parent.SelectSingleNode($Path, $Manager)
    if ($null -eq $node) { return $null }
    return $node.InnerText.Trim()
}

function ConvertTo-CaddyNormalizedPath([string]$Value) {
    # The live task was registered with doubled backslashes; Windows accepts both.
    return ([string]$Value -replace '\\\\', '\')
}

function Assert-CaddyOwnedTaskShape([string]$Xml) {
    $parsed = Read-CaddyTaskXml $Xml
    $document = $parsed.Document; $manager = $parsed.Manager
    $execs = @($document.SelectNodes('/t:Task/t:Actions/t:Exec', $manager))
    if ($execs.Count -ne 1) { throw 'caddy-task-action-count' }
    $command = ConvertTo-CaddyNormalizedPath (Get-CaddyNodeText $execs[0] 't:Command' $manager)
    $arguments = ConvertTo-CaddyNormalizedPath (Get-CaddyNodeText $execs[0] 't:Arguments' $manager)
    if ($command -cne 'C:\caddy\caddy.exe' -or $arguments -cne 'run --config C:\caddy\Caddyfile') {
        throw 'caddy-task-action-changed'
    }
    $user = Get-CaddyNodeText $document '/t:Task/t:Principals/t:Principal/t:UserId' $manager
    if ($user -notin @('S-1-5-18', 'SYSTEM', 'NT AUTHORITY\SYSTEM')) { throw 'caddy-task-principal-changed' }
}

function Test-CaddyBootRetryTaskXml([string]$Xml) {
    Assert-CaddyOwnedTaskShape $Xml
    $parsed = Read-CaddyTaskXml $Xml
    $document = $parsed.Document; $manager = $parsed.Manager
    if ((Get-CaddyNodeText $document '/t:Task/t:Settings/t:MultipleInstancesPolicy' $manager) -cne 'IgnoreNew') {
        return $false
    }
    $triggers = @($document.SelectNodes('/t:Task/t:Triggers/*', $manager))
    if ($triggers.Count -ne 2) { return $false }
    $boot = @($triggers | Where-Object { $_.LocalName -eq 'BootTrigger' })
    $time = @($triggers | Where-Object { $_.LocalName -eq 'TimeTrigger' })
    if ($boot.Count -ne 1 -or $time.Count -ne 1) { return $false }
    foreach ($trigger in @($boot[0], $time[0])) {
        $enabled = Get-CaddyNodeText $trigger 't:Enabled' $manager
        if ($null -ne $enabled -and $enabled -cne 'true') { return $false }
    }
    if ((Get-CaddyNodeText $boot[0] 't:Delay' $manager) -cne $script:CaddyBootDelay) { return $false }
    $repetition = $time[0].SelectSingleNode('t:Repetition', $manager)
    if ($null -eq $repetition) { return $false }
    if ((Get-CaddyNodeText $repetition 't:Interval' $manager) -cne $script:CaddyRepeatInterval) { return $false }
    $duration = Get-CaddyNodeText $repetition 't:Duration' $manager
    if ($null -ne $duration -and $duration -cne $script:CaddyRepeatDuration) { return $false }
    $stop = Get-CaddyNodeText $repetition 't:StopAtDurationEnd' $manager
    if ($null -ne $stop -and $stop -cne 'false') { return $false }
    return $true
}

function Add-CaddyElement($Document, $Parent, [string]$Name, [string]$Text) {
    $element = $Document.CreateElement($Name, $script:CaddyTaskNamespace)
    if ($PSBoundParameters.ContainsKey('Text')) { $element.InnerText = $Text }
    [void]$Parent.AppendChild($element)
    return $element
}

function ConvertTo-CaddyBootRetryTaskXml([string]$Xml) {
    # Only Triggers and MultipleInstancesPolicy change; the action, principal and all
    # other settings are carried over byte-for-byte from the exported definition.
    Assert-CaddyOwnedTaskShape $Xml
    $parsed = Read-CaddyTaskXml $Xml
    $document = $parsed.Document; $manager = $parsed.Manager
    $settings = $document.SelectSingleNode('/t:Task/t:Settings', $manager)
    if ($null -eq $settings) { throw 'caddy-task-settings-missing' }
    $policy = $settings.SelectSingleNode('t:MultipleInstancesPolicy', $manager)
    if ($null -eq $policy) { $policy = Add-CaddyElement $document $settings 'MultipleInstancesPolicy' }
    $policy.InnerText = 'IgnoreNew'

    $triggers = $document.SelectSingleNode('/t:Task/t:Triggers', $manager)
    if ($null -eq $triggers) { throw 'caddy-task-triggers-missing' }
    while ($triggers.HasChildNodes) { [void]$triggers.RemoveChild($triggers.FirstChild) }
    $boot = Add-CaddyElement $document $triggers 'BootTrigger'
    [void](Add-CaddyElement $document $boot 'Delay' $script:CaddyBootDelay)
    $time = Add-CaddyElement $document $triggers 'TimeTrigger'
    [void](Add-CaddyElement $document $time 'StartBoundary' '2026-01-01T00:00:00')
    $repetition = Add-CaddyElement $document $time 'Repetition'
    [void](Add-CaddyElement $document $repetition 'Interval' $script:CaddyRepeatInterval)
    [void](Add-CaddyElement $document $repetition 'Duration' $script:CaddyRepeatDuration)
    [void](Add-CaddyElement $document $repetition 'StopAtDurationEnd' 'false')
    return $document.OuterXml
}

function Get-CaddyListenerPorts {
    return @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -eq '10.99.0.2' -and $_.LocalPort -in @(8243, 8244) } |
        Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
}

if ($MyInvocation.InvocationName -ne '.') {
    $null = Get-ScheduledTask -TaskName $script:CaddyTaskName
    $changed = $false
    $current = Export-ScheduledTask -TaskName $script:CaddyTaskName
    $retryPresent = Test-CaddyBootRetryTaskXml $current
    $duplicate = Get-ScheduledTask -TaskName $script:CaddyDuplicateTaskName -ErrorAction SilentlyContinue
    $duplicateState = if ($null -eq $duplicate) { 'absent' } else { [string]$duplicate.State }

    if ($Mode -eq 'Apply') {
        if ($duplicateState -eq 'Running') { throw 'duplicate-caddy-task-running' }
        if ($duplicateState -notin @('absent', 'Disabled')) {
            Disable-ScheduledTask -TaskName $script:CaddyDuplicateTaskName | Out-Null
            $changed = $true
        }
        if (-not $retryPresent) {
            $desired = ConvertTo-CaddyBootRetryTaskXml $current
            Register-ScheduledTask -TaskName $script:CaddyTaskName -Xml $desired -Force | Out-Null
            $changed = $true
        }
        $current = Export-ScheduledTask -TaskName $script:CaddyTaskName
        $retryPresent = Test-CaddyBootRetryTaskXml $current
        $duplicate = Get-ScheduledTask -TaskName $script:CaddyDuplicateTaskName -ErrorAction SilentlyContinue
        $duplicateState = if ($null -eq $duplicate) { 'absent' } else { [string]$duplicate.State }
    }

    $report = [ordered]@{
        mode = $Mode
        changed = $changed
        retryTriggersPresent = $retryPresent
        taskState = [string](Get-ScheduledTask -TaskName $script:CaddyTaskName).State
        duplicateState = $duplicateState
        listeners = @(Get-CaddyListenerPorts)
    }
    Write-Output ('CADDY_BOOT_RETRY: ' + (ConvertTo-Json -Compress -InputObject $report))
    if (-not $retryPresent -or $duplicateState -notin @('absent', 'Disabled')) { exit 1 }
}
