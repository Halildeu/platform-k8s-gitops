"""gitops#3807: the I7 app-mTLS Caddy task must come back after a reboot.

The fixture is the read-only export of the live TEST GPU-host task (2026-09-23).
The behaviour test runs the real PowerShell transform with pwsh; CI must have it.
"""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "faz24" / "ensure_caddy_boot_retry.ps1"
RENEW = ROOT / "scripts" / "faz24" / "renew_test_live_mtls.ps1"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "caddy-i7-task-export.xml"

BEHAVIOUR = r"""
$ErrorActionPreference = 'Stop'
. $env:CADDY_RETRY_SCRIPT
$original = [IO.File]::ReadAllText($env:CADDY_RETRY_FIXTURE)
if (Test-CaddyBootRetryTaskXml $original) { throw 'fixture must start without retry triggers' }
$converted = ConvertTo-CaddyBootRetryTaskXml $original
if (-not (Test-CaddyBootRetryTaskXml $converted)) { throw 'converted definition must satisfy the retry contract' }
if ((ConvertTo-CaddyBootRetryTaskXml $converted) -cne $converted) { throw 'conversion must be idempotent' }
$o = [xml]$original; $c = [xml]$converted
if ($o.Task.Actions.OuterXml -cne $c.Task.Actions.OuterXml) { throw 'owned action changed' }
if ($o.Task.Principals.OuterXml -cne $c.Task.Principals.OuterXml) { throw 'principal changed' }
if ($o.Task.Settings.RestartOnFailure.OuterXml -cne $c.Task.Settings.RestartOnFailure.OuterXml) { throw 'restart settings changed' }
if ($c.Task.Triggers.BootTrigger.Delay -cne 'PT1M') { throw 'boot delay missing' }
if ($c.Task.Triggers.TimeTrigger.Repetition.Interval -cne 'PT5M') { throw 'repeat interval missing' }
$tampered = $original.Replace('run --config', 'run --watch --config')
$refused = $false
try { [void](ConvertTo-CaddyBootRetryTaskXml $tampered) } catch { $refused = $_.Exception.Message -eq 'caddy-task-action-changed' }
if (-not $refused) { throw 'a changed action must be refused' }
$indefinite = $converted.Replace('<Duration>P3650D</Duration>', '')
if (-not (Test-CaddyBootRetryTaskXml $indefinite)) { throw 'an indefinite readback must satisfy the contract' }
$noRepeat = $converted.Replace('<Interval>PT5M</Interval>', '<Interval>PT1H</Interval>')
if (Test-CaddyBootRetryTaskXml $noRepeat) { throw 'a slower repeat must not satisfy the contract' }
'CONTRACT_OK'
"""


class CaddyBootRetryContract(unittest.TestCase):
    def test_script_never_rewrites_actions_or_deletes_tasks(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("New-ScheduledTaskAction", "Unregister-ScheduledTask", "Set-ScheduledTask"):
            self.assertNotIn(forbidden, text)
        self.assertIn("[ValidateSet('Verify', 'Apply')][string]$Mode = 'Verify'", text)
        self.assertIn("Disable-ScheduledTask -TaskName $script:CaddyDuplicateTaskName", text)
        self.assertIn("if ($duplicateState -eq 'Running') { throw 'duplicate-caddy-task-running' }", text)
        self.assertIn("if ($MyInvocation.InvocationName -ne '.')", text)

    def test_renewal_still_restarts_the_same_owned_task(self) -> None:
        renew = RENEW.read_text(encoding="utf-8")
        self.assertIn("Stop-ScheduledTask -TaskName 'CaddyI7AppMtls'", renew)
        self.assertIn("Start-ScheduledTask -TaskName 'CaddyI7AppMtls'", renew)
        self.assertIn("Get-ScheduledTask -TaskName 'Workcube-Caddy-mTLS'", renew)

    def test_transform_on_the_live_task_export(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            if os.environ.get("CI") == "true":
                self.fail("pwsh is required in CI for the Caddy task behaviour contract")
            self.skipTest("pwsh is not installed on this workstation")
        env = dict(os.environ, CADDY_RETRY_SCRIPT=str(SCRIPT), CADDY_RETRY_FIXTURE=str(FIXTURE))
        result = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-Command", BEHAVIOUR],
            capture_output=True, text=True, timeout=120, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CONTRACT_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
