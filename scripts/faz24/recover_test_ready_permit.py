#!/usr/bin/env python3
"""Renew an expired TEST trust root with the SAME pinned key, then reauthorize.

The temporary disabled-consumer phase is the existing pre-enable ceremony,
never acceptance. No stream/DB row is removed. Full GPU recovery runs separately.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from gpu_mtls_metadata import governed_ssh_paths
from run_gpu_host_exact_sha_rollout import encode_remote_input, ssh_command
from build_transcript_ready_permit_trust_root import build_trust_root
from transcript_ready_pre_enable_contract import canonical_json, load_strict_json

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))
from bootstrap_faz24_transcript_ready_permit_transit import public_key_record  # noqa: E402

SOURCE = "e386b996cae22f08294a83d840f0e92d4a82cd53"
POLICY = ROOT / "config/faz24-transcript-ready-pre-enable-policy.v1.json"
MARKER = "TEST_READY_RECOVERY:"
HEADER = r"""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$env:GIT_CONFIG_COUNT='1'; $env:GIT_CONFIG_KEY_0='safe.directory'; $env:GIT_CONFIG_VALUE_0='C:/platform-ai'
$repo='C:\platform-ai'
$configPath='C:\ProgramData\Acik\platform-ai\meeting-ai.env'
. "$repo\deploy\gpu-host\meeting-ai-runtime-env.ps1"
. "$repo\deploy\gpu-host\task-action-contract.ps1"
$head=([string](& git -C $repo rev-parse HEAD)).Trim()
if ($LASTEXITCODE -ne 0 -or $head -cne '__SOURCE__') { throw 'source-mismatch' }
$values=Read-MeetingAiConfigFile -Path $configPath
Assert-MeetingAiConfigValues -Values $values
if ($values['MAI_APP_ENV'] -cne 'test') { throw 'test-environment-required' }
$task=Get-ScheduledTask -TaskName 'platform-ai-meeting-ai'
$contract=Get-GpuHostTaskActionContract -TaskName 'platform-ai-meeting-ai' `
  -Execute $task.Actions[0].Execute -Arguments $task.Actions[0].Arguments
if (!$contract.Valid -or $contract.AppEnv -cne 'test' -or
    !(Test-GpuHostSameLocalPath -Left $repo -Right $contract.RepoRoot)) { throw 'task-contract-mismatch' }
$python=$contract.PythonExe
function Emit($value) { Write-Output ('TEST_READY_RECOVERY:' + ($value | ConvertTo-Json -Depth 12 -Compress)) }
""".replace("__SOURCE__", SOURCE)

PREFLIGHT = HEADER + r"""
foreach ($name in @('platform-ai-live-stt','platform-ai-meeting-ai')) {
  if ((Get-ScheduledTask -TaskName $name).State -ne 'Disabled') { throw 'both-tasks-must-be-fenced' }
}
if ($values['MAI_READY_CONSUMER_ENABLED'] -cne 'true') { throw 'original-consumer-must-be-enabled' }
$path=Assert-MeetingAiRuntimePath -Path $values['MAI_READY_PERMIT_TRUST_ROOT_PATH'] -Purpose 'Pinned public root'
Assert-MeetingAiAcl -Path $path
$bytes=[IO.File]::ReadAllBytes($path)
if ($bytes.Length -gt 65536) { throw 'public-root-too-large' }
$sha=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sha -cne $values['MAI_READY_EXPECTED_PERMIT_TRUST_ROOT_SHA256']) { throw 'existing-pin-mismatch' }
Emit @{source=$head; trustRootBase64=[Convert]::ToBase64String($bytes); trustRootSha256=$sha}
"""

STAGE = HEADER + r"""
foreach ($name in @('platform-ai-live-stt','platform-ai-meeting-ai')) {
  if ((Get-ScheduledTask -TaskName $name).State -ne 'Disabled') { throw 'both-tasks-must-be-fenced' }
}
if ($values['MAI_READY_CONSUMER_ENABLED'] -cne 'true') { throw 'original-consumer-must-be-enabled' }
# Retain existing encrypted credentials and public pins. The only staged change
# is the consumer flag; the canonical atomic writer preserves an ACL-protected backup.
$mutex=New-Object Threading.Mutex($false,'Global\platform-ai-meeting-ai-config-v1')
$locked=$false
try {
  $locked=$mutex.WaitOne([TimeSpan]::FromSeconds(20))
  if (!$locked) { throw 'config-lock-unavailable' }
  $values=Read-MeetingAiConfigFile -Path $configPath
  if ($values['MAI_READY_CONSUMER_ENABLED'] -cne 'true') { throw 'config-state-changed' }
  $values['MAI_READY_CONSUMER_ENABLED']='false'
  Write-MeetingAiConfigAtomic -Path $configPath -Content (ConvertTo-MeetingAiConfigContent -Values $values)
} finally { if ($locked) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
Enable-ScheduledTask -TaskName 'platform-ai-meeting-ai' | Out-Null
Start-ScheduledTask -TaskName 'platform-ai-meeting-ai'
$ok=$false
$clock=[Diagnostics.Stopwatch]::StartNew()
while ($clock.Elapsed.TotalSeconds -lt 100) {
  try {
    $health=Invoke-RestMethod 'http://127.0.0.1:8300/health' -TimeoutSec 10
    if ($health.ready_consumer.enabled -eq $false -and $health.ready_consumer.worker_running -eq $false) {
      $ok=$true; break
    }
  } catch { }
  Start-Sleep -Seconds 2
}
if (!$ok) { throw 'disabled-consumer-health-unavailable' }
Emit @{phase='staged-disabled'; source=$head; consumerEnabled=$false; acceptance=$false}
"""

ACTIVATE = HEADER + r"""
if ($values['MAI_READY_CONSUMER_ENABLED'] -cne 'false') { throw 'consumer-must-be-disabled' }
$incoming=Initialize-MeetingAiDirectory -Path 'C:\ProgramData\Acik\platform-ai\permits\incoming'
$nonce=[Guid]::NewGuid().ToString('N')
$permitPath=Join-Path $incoming ('renewal-'+$nonce+'.dsse.json')
$rootPath=Join-Path $incoming ('renewal-'+$nonce+'.root.json')
try {
  foreach ($pair in @(@{path=$permitPath; data='__PERMIT__'},@{path=$rootPath; data='__ROOT__'})) {
    [IO.File]::WriteAllBytes($pair.path,@())
    Set-Acl -LiteralPath $pair.path -AclObject (New-MeetingAiAcl)
    [IO.File]::WriteAllBytes($pair.path,[Convert]::FromBase64String($pair.data))
    Assert-MeetingAiAcl -Path $pair.path
  }
  & "$repo\deploy\gpu-host\configure-meeting-ai.ps1" -RuntimeAppEnv test -ReadyConsumerEnabled true `
    -ReadyPermitSourcePath $permitPath -ReadyPermitTrustRootSourcePath $rootPath `
    -ExpectedGitopsCommit '__GITOPS__' -ExpectedPolicySha256 '__POLICY__' `
    -ExpectedProducerImageDigest '__PRODUCER__' -ExpectedPermitTrustRootSha256 '__ROOT_SHA__' `
    -PythonExe $python | Out-Null
  $fresh=Read-MeetingAiConfigFile -Path $configPath
  $params=@{
    PermitPath=$fresh['MAI_READY_PRE_ENABLE_PERMIT_PATH']; TrustRootPath=$fresh['MAI_READY_PERMIT_TRUST_ROOT_PATH']
    ExpectedTrustRootSha256='__ROOT_SHA__'; ExpectedGitopsCommit='__GITOPS__'; ExpectedPolicySha256='__POLICY__'
    ExpectedProducerImageDigest='__PRODUCER__'; RepoRoot=$repo; StartupScriptPath="$repo\deploy\gpu-host\start-meeting-ai.ps1"
    PythonExe=$python; AppEnv='test'
  }
  $null=Assert-TranscriptReadyPermitFile @params -SkipFreshness
  Assert-TranscriptReadyActivationReceiptFile @params -ReceiptPath $fresh['MAI_READY_ACTIVATION_RECEIPT_PATH']
  # Canonical full recovery will restart both tasks and prove runtime behavior.
  Stop-ScheduledTask -TaskName 'platform-ai-meeting-ai'
  Disable-ScheduledTask -TaskName 'platform-ai-meeting-ai' | Out-Null
  Emit @{phase='fresh-permit-installed'; source=$head; permitValidated=$true; acceptance=$false}
} finally {
  foreach ($path in @($permitPath,$rootPath)) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
  }
}
"""

FENCE = r"""
$ErrorActionPreference='Stop'
foreach ($name in @('platform-ai-live-stt','platform-ai-meeting-ai')) {
  Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  Disable-ScheduledTask -TaskName $name | Out-Null
}
Write-Output 'TEST_READY_RECOVERY:{"phase":"fenced-after-error"}'
"""

READY = HEADER + r"""
if ($values['MAI_READY_CONSUMER_ENABLED'] -cne 'true') { throw 'consumer-not-enabled' }
foreach ($name in @('platform-ai-live-stt','platform-ai-meeting-ai')) {
  if ((Get-ScheduledTask -TaskName $name).State -ne 'Running') { throw 'runtime-task-not-running' }
}
$health=Invoke-RestMethod 'http://127.0.0.1:8300/health' -TimeoutSec 15
$ready=$health.ready_consumer
if ($ready.enabled -ne $true -or $ready.worker_running -ne $true -or $ready.redis_group_ready -ne $true) {
  throw 'enabled-consumer-not-ready'
}
Emit @{consumerEnabled=$true; workerRunning=$true; redisGroupReady=$true; source=$head}
"""


class CeremonyRejected(RuntimeError):
    def __init__(self, names):
        super().__init__('pre-enable-evidence-rejected')
        self.names = names


def issue_permit(root_path, permit_path):
    result = subprocess.run(['bash', str(ROOT / 'scripts/faz24/issue-transcript-ready-permit.sh'),
                             '--trust-root', str(root_path), '--output', str(permit_path)],
                            capture_output=True, text=True, timeout=360, check=False)
    if result.returncode:
        # Only check identifiers, never raw output, messages or credentials.
        names = sorted(set(re.findall(r'^ - ([A-Za-z0-9_.-]{1,100}) \|', result.stderr, re.MULTILINE)))
        raise CeremonyRejected(names)


def command(argv, *, input=None, timeout=60):
    result = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        # Never expose subprocess output (Vault and config calls may contain credentials).
        raise RuntimeError(f"command-failed-{Path(argv[0]).name}-{result.returncode}")
    return result.stdout


def remote(script, *, timeout=150):
    config, hosts = governed_ssh_paths()
    wrapped = "try {\n" + script + r"""
} catch {
  $safe=if ($_.Exception.Message -cmatch '^[a-z0-9-]{1,100}$') { $_.Exception.Message } else { 'host-operation-rejected' }
  Write-Output ('TEST_READY_RECOVERY:' + (@{status='failed'; reason=$safe; errorClass=$_.Exception.GetType().Name} | ConvertTo-Json -Compress))
  exit 1
}
"""
    result = subprocess.run(ssh_command(config, hosts), input=encode_remote_input(wrapped),
                            capture_output=True, text=True, timeout=timeout, check=False)
    records = [line[len(MARKER):] for line in result.stdout.splitlines() if line.startswith(MARKER)]
    if len(records) != 1:
        raise RuntimeError("remote-metadata-unavailable")
    record = json.loads(records[0])
    if result.returncode or record.get("status") == "failed":
        reason = record.get("reason", "remote-operation-failed")
        raise RuntimeError(reason if re.fullmatch(r"[a-z0-9-]{1,100}", reason) else "remote-operation-failed")
    return record


def same_key_renewal(old_raw, old_pin, key_data, cluster_id, work, now):
    if hashlib.sha256(old_raw).hexdigest() != old_pin:
        raise ValueError("old-root-pin-mismatch")
    old = json.loads(old_raw)
    if old.get("allowedAppEnvironments") != ["test"] or old.get("algorithm") != "ed25519":
        raise ValueError("test-ed25519-root-required")
    expiry = dt.datetime.strptime(old["notAfter"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    if expiry >= now:
        raise ValueError("root-is-not-expired")
    receipt = public_key_record(data=key_data, vault_origin="https://127.0.0.1:8302",
                                cluster_id=cluster_id, verified_at=now)
    if receipt["publicKeyBase64"] != old.get("publicKeyBase64") or receipt["keyId"] != old.get("keyId"):
        raise ValueError("vault-key-differs-from-existing-independent-pin")
    raw = canonical_json(receipt)
    receipt_path = work / "public-receipt.json"
    receipt_path.write_bytes(raw)
    root = build_trust_root(receipt_path=receipt_path, expected_receipt_sha256=hashlib.sha256(raw).hexdigest(),
                            allowed_app_environments=["test"], not_before=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            not_after=(now + dt.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"), now=now)
    return canonical_json(root), {"oldTrustRootSha256": old_pin, "oldNotAfter": old["notAfter"],
                                 "newNotAfter": root["notAfter"], "samePinnedKey": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"schemaVersion": "faz24.testReadyPermitRecovery.v1", "source": SOURCE,
              "runtimeAccepted": False, "rawCredentialsIncluded": False}
    staged = False
    try:
        commit = command(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("gitops-commit-invalid")
        policy_bytes, policy = load_strict_json(POLICY, "policy")
        if not any(g["platformAiCommit"] == SOURCE for g in policy["hostStartupGuards"]):
            raise ValueError("source-not-allowlisted")
        preflight = remote(PREFLIGHT)
        with tempfile.TemporaryDirectory(prefix="faz24-root-renewal-") as temp:
            work = Path(temp)
            os.chmod(work, 0o700)
            # Fixed TEST container only. Token enters docker stdin, never argv/output.
            token = command(["sudo", "-n", "jq", "-r", ".root_token", "/srv/platform/secrets/backup-auth/vault-init-test.json"]).strip()
            try:
                raw_key = command(["docker", "exec", "-i", "platform-vault-test", "sh", "-c",
                                   'read -r VAULT_TOKEN; export VAULT_TOKEN; vault read -format=json meeting-ai/keys/transcript-ready-permit'],
                                  input=token + "\n")
            finally:
                token = None
            health = json.loads(command(["docker", "exec", "platform-vault-test", "vault", "status", "-format=json"]))
            if health.get("sealed") is not False or not health.get("cluster_id"):
                raise ValueError("test-vault-unavailable")
            now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
            root_raw, renewal = same_key_renewal(base64.b64decode(preflight["trustRootBase64"], validate=True),
                                                preflight["trustRootSha256"], json.loads(raw_key)["data"],
                                                health["cluster_id"], work, now)
            root_sha = hashlib.sha256(root_raw).hexdigest()
            report.update(renewal, newTrustRootSha256=root_sha, gitopsCommit=commit)
            if not args.apply:
                report["status"] = "preflight-only"
            else:
                root_path = work / "root.json"
                root_path.write_bytes(root_raw)
                # Mark before the call so partial staging is fenced on any error.
                staged = True
                report["stage"] = remote(STAGE)
                permit_path = work / "permit.json"
                issue_permit(root_path, permit_path)
                permit_raw = permit_path.read_bytes()
                if len(permit_raw) > 1048576:
                    raise ValueError("permit-too-large")
                script = ACTIVATE
                replacements = {"__PERMIT__": base64.b64encode(permit_raw).decode(), "__ROOT__": base64.b64encode(root_raw).decode(),
                                "__GITOPS__": commit, "__POLICY__": hashlib.sha256(policy_bytes).hexdigest(),
                                "__PRODUCER__": policy["producerCapabilities"][0]["transcriptImageDigest"], "__ROOT_SHA__": root_sha}
                for key, value in replacements.items():
                    script = script.replace(key, value)
                report["activation"] = remote(script)
                report["status"] = "permit-installed-runtime-recovery-required"
                staged = False
    except Exception as error:
        report["status"] = "failed"
        report["errorClass"] = type(error).__name__
        if isinstance(error, CeremonyRejected):
            report['failedCheckNames'] = error.names
        # Only fixed, metadata-safe categories; no exception/native output.
        if isinstance(error, (ValueError, RuntimeError)) and re.fullmatch(r"[a-z0-9-]{1,100}", str(error)):
            report["reason"] = str(error)
        if staged:
            try:
                report["containment"] = remote(FENCE)
            except Exception:
                report["containment"] = {"phase": "fence-unverified"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
