"""Source promotion must retain preflight, fresh activation and compensation."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'faz24'))
import promote_test_live_analysis as promotion


class PromotionTests(unittest.TestCase):
    def test_exact_sources_required_for_remote_header(self):
        for source in (promotion.BASE, promotion.TARGET):
            self.assertRegex(source, r'^[0-9a-f]{40}$')
            self.assertIn("$head -cne '" + source + "'", promotion.header(source))
        with self.assertRaises(ValueError):
            promotion.header('f' * 40)
        self.assertIn("$meeting.status -cne 'ok'", promotion.PREFLIGHT)

    def run_fixture(self, *, apply, candidate_fails=False):
        root = b'{"fixture":"public-root"}'
        policy = {
            'hostStartupGuards': [
                {'platformAiCommit': source, 'startupScriptSha256': promotion.STARTUP_SHA,
                 'permitRequired': True} for source in (promotion.BASE, promotion.TARGET)],
            'producerCapabilities': [{'transcriptImageDigest': 'sha256:' + 'a' * 64}],
        }

        def remote(script, **kwargs):
            if script == promotion.PREFLIGHT:
                return {'source': promotion.BASE,
                        'trustRootBase64': base64.b64encode(root).decode()}
            return {'source': promotion.TARGET}

        def accept(source, output):
            if source == promotion.TARGET and candidate_fails:
                raise RuntimeError('full-runtime-rejected')
            return {'consumerEnabled': True, 'workerRunning': True, 'redisGroupReady': True}

        with tempfile.TemporaryDirectory() as work, patch.object(
                promotion, 'ROOT_SHA', hashlib.sha256(root).hexdigest()), patch.object(
                promotion.ceremony, 'command', return_value='b' * 40), patch.object(
                promotion.ceremony, 'load_strict_json', return_value=(json.dumps(policy).encode(), policy)), patch.object(
                promotion.ceremony, 'remote', side_effect=remote) as host, patch.object(
                promotion, 'activate', return_value={'phase': 'activated'}) as activate, patch.object(
                promotion, 'accept', side_effect=accept) as verify:
            result = promotion.perform(apply=apply, output=Path(work) / 'result.json')
        return result, host, activate, verify

    def test_dry_preflight_never_stages_or_activates(self):
        result, host, activate, verify = self.run_fixture(apply=False)
        self.assertEqual(result['status'], 'preflight-only')
        self.assertFalse(result['runtimeAccepted'])
        self.assertEqual(host.call_count, 1)
        activate.assert_not_called()
        verify.assert_not_called()

    def test_candidate_requires_full_acceptance(self):
        result, _, activate, verify = self.run_fixture(apply=True)
        self.assertTrue(result['runtimeAccepted'])
        self.assertFalse(result['phoneAccepted'])
        self.assertEqual(activate.call_args.args[0], promotion.TARGET)
        self.assertEqual(verify.call_args.args[0], promotion.TARGET)

    def test_failed_candidate_reauthorizes_and_verifies_original_source(self):
        result, _, activate, verify = self.run_fixture(apply=True, candidate_fails=True)
        self.assertEqual(result['status'], 'candidate-rejected-baseline-reaccepted')
        self.assertFalse(result['runtimeAccepted'])
        self.assertEqual([call.args[0] for call in activate.call_args_list],
                         [promotion.TARGET, promotion.BASE])
        self.assertEqual([call.args[0] for call in verify.call_args_list],
                         [promotion.TARGET, promotion.BASE])


if __name__ == '__main__':
    unittest.main()
