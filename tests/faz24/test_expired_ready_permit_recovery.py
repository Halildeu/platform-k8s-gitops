import base64
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from subprocess import CompletedProcess
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/faz24'))
import recover_test_ready_permit as recovery


class SameKeyRenewalTest(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 9, 23, tzinfo=dt.timezone.utc)
        self.key = base64.b64encode(bytes(range(32))).decode()
        self.old = {'schemaVersion': 'faz24.transcriptReadyPermitTrustRoot.v1',
                    'algorithm': 'ed25519', 'keyId': 'vault-transit://meeting-ai/transcript-ready-permit#v1',
                    'publicKeyBase64': self.key, 'allowedAppEnvironments': ['test'],
                    'notBefore': '2026-08-01T00:00:00Z', 'notAfter': '2026-09-01T00:00:00Z'}
        self.data = {'type': 'ed25519', 'derived': False, 'exportable': False,
                     'allow_plaintext_backup': False, 'deletion_allowed': False,
                     'supports_signing': True, 'latest_version': 1,
                     'keys': {'1': {'public_key': self.key}}}

    def renew(self, old=None, data=None, pin=None):
        raw = json.dumps(old or self.old).encode()
        with tempfile.TemporaryDirectory() as temp:
            return recovery.same_key_renewal(raw, pin or hashlib.sha256(raw).hexdigest(),
                                            data or self.data, 'test-cluster', Path(temp), self.now)

    def test_same_pinned_key_renews_bounded_test_window(self):
        raw, report = self.renew()
        root = json.loads(raw)
        self.assertEqual(root['publicKeyBase64'], self.key)
        self.assertEqual(root['allowedAppEnvironments'], ['test'])
        self.assertEqual(root['notAfter'], '2026-12-22T00:00:00Z')
        self.assertTrue(report['samePinnedKey'])

    def test_changed_vault_key_rejected(self):
        data = copy.deepcopy(self.data)
        data['keys']['1']['public_key'] = base64.b64encode(b'x' * 32).decode()
        with self.assertRaisesRegex(ValueError, 'existing-independent-pin'):
            self.renew(data=data)

    def test_fingerprint_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'old-root-pin-mismatch'):
            self.renew(pin='0' * 64)

    def test_production_scope_rejected(self):
        old = dict(self.old, allowedAppEnvironments=['prod'])
        with self.assertRaisesRegex(ValueError, 'test-ed25519'):
            self.renew(old=old)

    def test_still_valid_root_rejected(self):
        old = dict(self.old, notAfter='2026-10-01T00:00:00Z')
        with self.assertRaisesRegex(ValueError, 'not-expired'):
            self.renew(old=old)

    def test_exportable_key_rejected(self):
        with self.assertRaises(RuntimeError):
            self.renew(data=dict(self.data, exportable=True))

    def test_ceremony_failure_exposes_only_check_names(self):
        result = CompletedProcess([], 1, stdout='credential-do-not-echo',
                                  stderr=' - host.disabled | sensitive message | fix\n'
                                         ' - redis.pending | private details | fix\n')
        with patch.object(recovery.subprocess, 'run', return_value=result):
            with self.assertRaises(recovery.CeremonyRejected) as caught:
                recovery.issue_permit(Path('root.json'), Path('permit.json'))
        self.assertEqual(caught.exception.names, ['host.disabled', 'redis.pending'])
        self.assertEqual(str(caught.exception), 'pre-enable-evidence-rejected')

    def test_partial_stage_failure_fences_tasks_without_credential_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'report.json'
            public = {'trustRootBase64': base64.b64encode(json.dumps(self.old).encode()).decode(),
                      'trustRootSha256': hashlib.sha256(json.dumps(self.old).encode()).hexdigest()}
            commands = ['a' * 40, 'credential-do-not-echo', json.dumps({'data': self.data}),
                        json.dumps({'sealed': False, 'cluster_id': 'test-cluster'})]
            with patch.object(sys, 'argv', ['recovery', '--apply', '--output', str(output)]), \
                 patch.object(recovery, 'command', side_effect=commands), \
                 patch.object(recovery, 'remote', side_effect=[public, RuntimeError('stage-rejected'),
                                                               {'phase': 'fenced-after-error'}]) as remote, \
                 patch('builtins.print'):
                self.assertEqual(recovery.main(), 1)
            report = json.loads(output.read_text())
            self.assertEqual(report['containment']['phase'], 'fenced-after-error')
            self.assertFalse(report['runtimeAccepted'])
            self.assertEqual(remote.call_args.args[0], recovery.FENCE)
            self.assertNotIn('credential-do-not-echo', output.read_text())

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell stage contract')
    def test_stage_executes_and_retains_existing_config_values(self):
        stubs = r'''
$ErrorActionPreference='Stop'
$configPath='synthetic-unused-path'; $head='synthetic-source'
$values=@{MAI_READY_CONSUMER_ENABLED='true'; KEEP_DPAPI='synthetic-encrypted-value'; KEEP_PIN='synthetic-pin'}
function Get-ScheduledTask { param($TaskName); return @{State='Disabled'} }
function Read-MeetingAiConfigFile { param($Path); return $values.Clone() }
function Write-MeetingAiConfigAtomic {
  param($Path,$Content)
  if ($Path -cne $configPath -or $Content -cnotmatch 'MAI_READY_CONSUMER_ENABLED=false' -or
      $Content -cnotmatch 'KEEP_DPAPI=synthetic-encrypted-value' -or
      $Content -cnotmatch 'KEEP_PIN=synthetic-pin') { throw 'config-was-not-preserved' }
  $script:written=$true
}
function Enable-ScheduledTask { param($TaskName); if($TaskName -cne 'platform-ai-meeting-ai') {throw 'wrong-task'} }
function Start-ScheduledTask { param($TaskName); if(!$script:written) {throw 'write-required'} }
function Invoke-RestMethod { param($Uri,$TimeoutSec); return @{ready_consumer=@{enabled=$false;worker_running=$false}} }
function Emit { param($Value); if($Value.acceptance -ne $false) {throw 'premature-acceptance'} }
'''
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / 'stage.ps1'
            script.write_text(stubs + recovery.STAGE[len(recovery.HEADER):], encoding='utf-8')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(script)],
                                    capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
