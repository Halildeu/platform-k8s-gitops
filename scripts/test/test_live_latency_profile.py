"""Stage profiling exports numeric diagnostics without provider content."""
import base64
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'faz24'))
import profile_test_live_latency as profile


class ProfileTests(unittest.TestCase):
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
