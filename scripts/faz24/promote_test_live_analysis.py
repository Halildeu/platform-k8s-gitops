#!/usr/bin/env python3
"""Fixed TEST source promotion with a fresh exact-source consumer permit.

Source staging is not acceptance. Failure compensates by reauthorizing the
original source and running the same full verifier, or leaves both tasks fenced.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import recover_test_ready_permit as ceremony
import recover_test_ready_dead_letter as recovery
from run_gpu_host_exact_sha_rollout import main as rollout
from verify_gpu_host_exact_sha_rollout_evidence import verify

BASE = ceremony.SOURCE
TARGET = recovery.CORRECTED_SOURCE
ROOT_SHA = '44ac2425ded67086cfc20871e7b777b04a9fb98999f46a66220e8cf11f0a7cb7'
STARTUP_SHA = 'd6974b9b6c5d8c034bec6d81ffe9176d96d7b0c1770344c49164024ebb39d17e'


def header(source):
    if source not in (BASE, TARGET):
        raise ValueError('unapproved-source')
    return ceremony.HEADER.replace(BASE, source)


PREFLIGHT = header(BASE) + r'''
foreach ($name in @('platform-ai-live-stt','platform-ai-meeting-ai')) {
  if ((Get-ScheduledTask -TaskName $name).State -ne 'Running') { throw 'baseline-not-running' }
}
if ($values['MAI_READY_CONSUMER_ENABLED'] -cne 'true') { throw 'baseline-consumer-disabled' }
$live=Invoke-RestMethod 'http://127.0.0.1:8200/ready' -TimeoutSec 15
$meeting=Invoke-RestMethod 'http://127.0.0.1:8300/ready' -TimeoutSec 15
if ($live.status -cne 'ready' -or $live.runtime_commit -cne $head -or !$live.workers_healthy -or
    !$meeting.ready_consumer.enabled -or !$meeting.ready_consumer.ready -or
    !$meeting.analysis_delivery.ready -or $meeting.analysis_delivery.status -cne 'ok' -or
    $meeting.status -cnotin @('ok','degraded')) { throw 'baseline-dependencies-not-ready' }
$repairRequired=$meeting.status -ceq 'degraded'
if ($repairRequired -and ($meeting.ready_consumer.dead_letter -ne 1 -or
    $meeting.ready_consumer.received -ne 0 -or $meeting.ready_consumer.processing -ne 0 -or
    $meeting.ready_consumer.error_code)) { throw 'unreviewed-baseline-degradation' }
$path=Assert-MeetingAiRuntimePath -Path $values['MAI_READY_PERMIT_TRUST_ROOT_PATH'] -Purpose 'Pinned public root'
Assert-MeetingAiAcl -Path $path
$sha=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sha -cne '__ROOT_SHA__' -or $sha -cne $values['MAI_READY_EXPECTED_PERMIT_TRUST_ROOT_SHA256']) {
  throw 'independent-root-pin-mismatch'
}
$bytes=[IO.File]::ReadAllBytes($path)
if ($bytes.Length -gt 65536) { throw 'public-root-too-large' }
Emit @{source=$head; trustRootBase64=[Convert]::ToBase64String($bytes); trustRootSha256=$sha; repairRequired=$repairRequired}
'''.replace('__ROOT_SHA__', ROOT_SHA)

# Use the tested atomic flag-only staging operation, but stop both running tasks
# first. Task registrations remain enabled until the canonical updater has pinned
# source; no custom Git reset or hand-written deployment ledger is used.
STOP_AND_STAGE = r'''
foreach ($name in @('platform-ai-live-stt','platform-ai-meeting-ai')) {
  Stop-ScheduledTask -TaskName $name
}
$deadline=[DateTime]::UtcNow.AddSeconds(30)
while (@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalPort -in @(8200,8300) }).Count -gt 0) {
  if ([DateTime]::UtcNow -gt $deadline) { throw 'stale-runtime-listener' }
  Start-Sleep -Seconds 1
}
# Enabling a stopped registration is only for the updater's NoRestart staging
# contract. No task is launched until the source is pinned and flag is false.
foreach ($name in @('platform-ai-live-stt','platform-ai-meeting-ai')) {
  Enable-ScheduledTask -TaskName $name | Out-Null
}
$mutex=New-Object Threading.Mutex($false,'Global\platform-ai-meeting-ai-config-v1')
$locked=$false
try {
  $locked=$mutex.WaitOne([TimeSpan]::FromSeconds(20))
  if (!$locked) { throw 'config-lock-unavailable' }
  $values=Read-MeetingAiConfigFile -Path $configPath
  Assert-MeetingAiConfigValues -Values $values
  $values['MAI_READY_CONSUMER_ENABLED']='false'
  $lines=@('# platform-ai meeting-ai runtime config v1',
    '# Secret fields are DPAPI LocalMachine ciphertext. Do not copy to another host.')
  foreach ($name in $values.Keys) { $lines += '{0}={1}' -f $name,$values[$name] }
  Write-MeetingAiConfigAtomic -Path $configPath -Content (($lines -join "`r`n")+"`r`n")
  $lines=$null
} finally { if ($locked) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
Emit @{phase='stopped-consumer-disabled'; acceptance=$false; source=$head}
'''

PIN = r"""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$env:GIT_CONFIG_COUNT='1'; $env:GIT_CONFIG_KEY_0='safe.directory'; $env:GIT_CONFIG_VALUE_0='C:/platform-ai'
$repo='C:\platform-ai'
$target='__TARGET__'
$controller=Join-Path $env:TEMP ('platform-ai-permit-controller-'+[Guid]::NewGuid().ToString('N'))
$childPath=Join-Path $env:TEMP ('platform-ai-permit-pin-'+[Guid]::NewGuid().ToString('N')+'.ps1')
$stdout=$childPath+'.out'; $stderr=$childPath+'.err'
$created=$false
function Git-Silent([string[]]$argsList) {
  $old=$ErrorActionPreference
  try { $ErrorActionPreference='Continue'; & git @argsList 1>$null 2>$null; return $LASTEXITCODE }
  finally { $ErrorActionPreference=$old }
}
try {
  if ((Git-Silent @('-C',$repo,'fetch','--prune','origin')) -ne 0) { throw 'source-fetch-rejected' }
  if ((Git-Silent @('-C',$repo,'merge-base','--is-ancestor',$target,'origin/main')) -ne 0) { throw 'source-ancestry-rejected' }
  if ((Git-Silent @('-C',$repo,'worktree','add','--detach',$controller,$target)) -ne 0) { throw 'controller-rejected' }
  $created=$true
  $updater=Join-Path $controller 'deploy\gpu-host\update.ps1'
  foreach ($mode in @('-WhatIf','-NoRestart')) {
    $content='$ErrorActionPreference=''Stop''; $ConfirmPreference=''None''; $global:LASTEXITCODE=0; & '''+
      $updater.Replace("'","''")+''' -RepoRoot ''C:\platform-ai'' -TargetCommit '''+$target+''' '+
      $mode+' -Confirm:$false; exit $LASTEXITCODE'
    [IO.File]::WriteAllText($childPath,$content,(New-Object Text.UTF8Encoding($false)))
    $process=Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-NonInteractive',
      '-ExecutionPolicy','Bypass','-File',('"'+$childPath+'"')) -WindowStyle Hidden -Wait -PassThru `
      -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if ($null -eq $process.ExitCode -or $process.ExitCode -ne 0) { throw 'canonical-source-pin-rejected' }
  }
  $head=([string](& git -C $repo rev-parse HEAD)).Trim()
  if ($LASTEXITCODE -ne 0 -or $head -cne $target) { throw 'source-pin-readback-rejected' }
  Write-Output ('TEST_READY_RECOVERY:{"phase":"source-pinned-not-accepted","source":"'+$target+'","acceptance":false}')
} finally {
  foreach ($path in @($childPath,$stdout,$stderr)) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
  }
  if ($created) {
    $resolved=[IO.Path]::GetFullPath($controller)
    $tempRoot=[IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')+'\'
    if (!$resolved.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolved) -cnotmatch '^platform-ai-permit-controller-[0-9a-f]{32}$') {
      throw 'controller-cleanup-path-rejected'
    }
    if ((Git-Silent @('-C',$repo,'worktree','remove',$resolved)) -ne 0) { throw 'controller-cleanup-rejected' }
  }
}
"""

START_DISABLED = ceremony.STAGE[ceremony.STAGE.index("Enable-ScheduledTask -TaskName 'platform-ai-meeting-ai'"):]

# A fresh exact-source activation is required before this repair-only startup.
# The strict updater/verifier still runs after the reviewed event is OUTBOXED.
START_FOR_REPAIR = r'''
if ($values['MAI_READY_CONSUMER_ENABLED'] -cne 'true') { throw 'repair-consumer-not-enabled' }
Enable-ScheduledTask -TaskName 'platform-ai-meeting-ai' | Out-Null
Start-ScheduledTask -TaskName 'platform-ai-meeting-ai'
$deadline=[DateTime]::UtcNow.AddSeconds(100)
$ready=$false
while ([DateTime]::UtcNow -lt $deadline) {
  try {
    $health=Invoke-RestMethod 'http://127.0.0.1:8300/ready' -TimeoutSec 10
    if ($health.ready_consumer.enabled -and $health.ready_consumer.ready -and $health.analysis_delivery.ready) {
      $ready=$true; break
    }
  } catch {}
  Start-Sleep -Seconds 2
}
if (!$ready) { throw 'repair-consumer-startup-failed' }
Emit @{phase='repair-only-started'; source=$head; acceptance=$false}
'''

FINISH_REPAIR = r'''
$health=Invoke-RestMethod 'http://127.0.0.1:8300/ready' -TimeoutSec 15
if ($health.status -cne 'ok' -or !$health.ready_consumer.ready -or
    $health.ready_consumer.dead_letter -ne 0 -or !$health.analysis_delivery.ready) {
  throw 'repair-did-not-restore-health'
}
Stop-ScheduledTask -TaskName 'platform-ai-meeting-ai'
Disable-ScheduledTask -TaskName 'platform-ai-meeting-ai' | Out-Null
Emit @{phase='reviewed-repair-verified'; acceptance=$false}
'''


def activate(source, root, work, commit, policy_bytes, producer):
    ceremony.remote(header(source) + START_DISABLED)
    permit = work / f'{source}.permit.json'
    ceremony.issue_permit(root, permit)
    data = permit.read_bytes()
    if len(data) > 1048576:
        raise ValueError('permit-too-large')
    script = ceremony.ACTIVATE.replace(BASE, source)
    substitutions = {'__PERMIT__': base64.b64encode(data).decode(),
                     '__ROOT__': base64.b64encode(root.read_bytes()).decode(),
                     '__GITOPS__': commit, '__POLICY__': hashlib.sha256(policy_bytes).hexdigest(),
                     '__PRODUCER__': producer, '__ROOT_SHA__': ROOT_SHA}
    for key, value in substitutions.items():
        script = script.replace(key, value)
    return ceremony.remote(script)


def accept(source, output):
    config, hosts = ceremony.governed_ssh_paths()
    result = rollout(['--target-commit', source, '--ssh-config', str(config),
                      '--ssh-known-hosts', str(hosts), '--recover-fenced-runtime',
                      '--timeout-seconds', '4200', '--output', str(output)])
    if result:
        raise RuntimeError('full-runtime-rejected')
    verify(json.loads(output.read_text()), source)
    ready = ceremony.remote(ceremony.READY.replace(BASE, source))
    if not all(ready.get(k) is True for k in ('consumerEnabled','workerRunning','redisGroupReady')):
        raise RuntimeError('enabled-consumer-not-ready')
    return ready


def safe_error(error):
    result = {'errorClass': type(error).__name__}
    if re.fullmatch(r'[a-z0-9-]{1,100}', str(error)):
        result['reason'] = str(error)
    if isinstance(error, ceremony.CeremonyRejected):
        result['failedCheckNames'] = error.names
    return result


def perform(*, apply, output):
    report = {'schemaVersion':'faz24.testLiveAnalysisPromotion.v1', 'target':TARGET,
              'original':BASE, 'runtimeAccepted':False, 'phoneAccepted':False,
              'secretMaterialIncluded':False}
    mutated = False
    phase_source = BASE
    try:
        commit = ceremony.command(['git','-C',str(ceremony.ROOT),'rev-parse','HEAD']).strip()
        if not re.fullmatch(r'[0-9a-f]{40}',commit):
            raise ValueError('gitops-commit-invalid')
        policy_bytes, policy = ceremony.load_strict_json(ceremony.POLICY,'policy')
        for source in (BASE,TARGET):
            if not any(g['platformAiCommit'] == source and g['startupScriptSha256'] == STARTUP_SHA
                       and g['permitRequired'] is True for g in policy['hostStartupGuards']):
                raise ValueError('source-not-allowlisted')
        public = ceremony.remote(PREFLIGHT)
        repair_required = public.get('repairRequired') is True
        if repair_required:
            report['repairPreflight'] = recovery.corrected_source_recovery(BASE, apply=False)
        root_raw = base64.b64decode(public['trustRootBase64'],validate=True)
        if hashlib.sha256(root_raw).hexdigest() != ROOT_SHA:
            raise ValueError('independent-root-pin-mismatch')
        report['gitopsCommit'] = commit
        if not apply:
            report['status']='preflight-only'
            return report
        with tempfile.TemporaryDirectory(prefix='faz24-live-promotion-') as temp:
            work=Path(temp)
            os.chmod(work,0o700)
            root=work/'root.json'
            root.write_bytes(root_raw)
            producer=policy['producerCapabilities'][0]['transcriptImageDigest']
            try:
                mutated=True
                ceremony.remote(header(BASE)+STOP_AND_STAGE)
                # If pinning fails, its canonical updater may have changed HEAD.
                # Compensation below reads and validates the actual allowed HEAD.
                ceremony.remote(PIN.replace('__TARGET__',TARGET),timeout=300)
                phase_source=TARGET
                report['activation']=activate(TARGET,root,work,commit,policy_bytes,producer)
                if repair_required:
                    ceremony.remote(header(TARGET)+START_FOR_REPAIR)
                    report['reviewedRecovery'] = recovery.corrected_source_recovery(TARGET, apply=True)
                    ceremony.remote(header(TARGET)+FINISH_REPAIR)
                report['consumer']=accept(TARGET,output.parent/'candidate-runtime.json')
                report['runtimeAccepted']=True
                report['status']='runtime-accepted-live-latency-required'
                mutated=False
            except Exception as error:
                report.update(status='candidate-rejected', failure=safe_error(error))
                if isinstance(error, subprocess.TimeoutExpired):
                    # An uncertain in-flight host mutation must not race a second
                    # updater. Fence and retain metadata for explicit inspection.
                    raise RuntimeError('host-mutation-completion-unknown') from error
                # Never restore consumed/revoked permit bytes. Re-run the full
                # strict ceremony for the original exact source and verify it.
                read_head = r'''
$ErrorActionPreference='Stop'
$env:GIT_CONFIG_COUNT='1'; $env:GIT_CONFIG_KEY_0='safe.directory'; $env:GIT_CONFIG_VALUE_0='C:/platform-ai'
$head=([string](& git -C C:\platform-ai rev-parse HEAD)).Trim()
if ($head -cnotmatch '^[0-9a-f]{40}$') { throw 'source-read-failed' }
Write-Output ('TEST_READY_RECOVERY:{"source":"'+$head+'"}')
'''
                phase_source=ceremony.remote(read_head)['source']
                ceremony.remote(header(phase_source)+STOP_AND_STAGE)
                ceremony.remote(PIN.replace('__TARGET__',BASE),timeout=300)
                activate(BASE,root,work,commit,policy_bytes,producer)
                report['rollback']=accept(BASE,output.parent/'rollback-runtime.json')
                report['status']='candidate-rejected-baseline-reaccepted'
                mutated=False
    except Exception as error:
        report.update(status='failed',failure=safe_error(error))
    finally:
        if mutated:
            try:
                report['containment']=ceremony.remote(ceremony.FENCE)
            except Exception:
                report['containment']={'phase':'fence-unverified'}
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    report=perform(apply=args.apply,output=args.output)
    args.output.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps(report,sort_keys=True))
    return 0 if report['status'] in ('preflight-only','runtime-accepted-live-latency-required') else 1


if __name__ == '__main__':
    raise SystemExit(main())
