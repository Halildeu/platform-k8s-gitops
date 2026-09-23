"""Stage profiling exports numeric diagnostics without provider content."""
import base64
import contextlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'faz24'))
import profile_test_live_latency as profile


class ProfileTests(unittest.TestCase):
    def test_managed_config_without_host_uses_launcher_default(self):
        self.assertEqual(profile.local_host({'MAI_OLLAMA_MODEL': 'qwen3.8:27b'}), 'http://localhost:11434')
        self.assertEqual(profile.local_host({'MAI_OLLAMA_HOST': 'http://127.0.0.1:11434'}), 'http://127.0.0.1:11434')
        with self.assertRaises(ValueError):
            profile.local_host({'MAI_OLLAMA_HOST': 'https://external.invalid'})

    def test_partial_http_evidence_survives_remote_failure_without_raw_error(self):
        output = io.StringIO()
        with patch.object(profile, 'probe', return_value={'samples': [12.3]}), patch.object(
                profile.ceremony, 'remote', side_effect=RuntimeError('PRIVATE')), contextlib.redirect_stdout(output):
            self.assertEqual(profile.main(), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result['http'], {'samples': [12.3]})
        self.assertEqual(result['phase'], 'isolated-stages')
        self.assertEqual(result['errorClass'], 'RuntimeError')
        self.assertFalse(result['phoneAccepted'])
        self.assertNotIn('PRIVATE', output.getvalue())

    def test_export_accepts_actual_runtime_dictionary_and_omits_secrets(self):
        shell = shutil.which('pwsh') or shutil.which('powershell')
        if not shell:
            self.skipTest('PowerShell is unavailable')
        script = profile.remote_script()
        export = script[script.index('  $public=[ordered]@{}'):script.index('  $proc=New-Object Diagnostics.Process;')]
        fixture = r'''
$ErrorActionPreference='Stop'
$values=New-Object 'Collections.Generic.Dictionary[string,string]'([StringComparer]::OrdinalIgnoreCase)
$values['MAI_OLLAMA_MODEL']='test-model'
$values['MAI_INGESTION_AUTH_TOKEN']='PRIVATE'
$psi=New-Object Diagnostics.ProcessStartInfo
'''
        result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', fixture + export +
                                 "\nWrite-Output $psi.EnvironmentVariables['LIVE_PROFILE_SETTINGS']"],
                                capture_output=True, text=True, timeout=20, check=True)
        self.assertEqual(json.loads(result.stdout), {'MAI_OLLAMA_MODEL': 'test-model'})

    def test_provider_content_is_not_exported(self):
        self.assertEqual(profile.envelope_metadata({
            'response': 'PRIVATE', 'thinking': 'PRIVATE', 'load_duration': 2_000_000_000,
            'eval_duration': -1, 'prompt_eval_count': True, 'eval_count': 12,
        }), {'loadSeconds': 2.0, 'eval_count': 12})

    def test_exact_source_and_test_boundary_in_generated_launcher(self):
        script = profile.remote_script()
        self.assertIn(profile.candidate.SOURCE_COMMIT, script)
        self.assertIn('test-environment-required', script)
        self.assertIn('LIVE_PROFILE_SETTINGS', script)
        self.assertNotIn('Import-MeetingAiRuntimeEnvironment', script)
        self.assertNotIn('MAI_INGESTION_AUTH_TOKEN', script)
        self.assertNotIn('Enable-ScheduledTask', script)

    def test_embedded_python_is_valid_and_does_not_pull_or_unload_models(self):
        script = profile.remote_script()
        encoded = re.search(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", script)[1]
        body = base64.b64decode(encoded).decode()
        compile(body, '<profile>', 'exec')
        self.assertNotIn('/api/pull', body)
        self.assertNotIn("'keep_alive':0", body)
        self.assertIn('httpx.get, httpx.post = native_get, native_post', body)


if __name__ == '__main__':
    unittest.main()
