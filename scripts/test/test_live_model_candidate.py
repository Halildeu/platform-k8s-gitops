"""Candidate downloads fail closed before inference or service reconfiguration."""
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'faz24'))
import qualify_test_live_model as candidate
from live_incremental_latency_probe import SOURCE, metadata


def response(body, content=b''):
    result = Mock()
    result.json.return_value = body
    result.content = content
    return result


class CandidateTests(unittest.TestCase):
    def test_installed_wrong_digest_never_downloads(self):
        inventory = response({'models': [{'name': candidate.PROFILES[0][0], 'digest': 'wrong'}]})
        with patch('httpx.get', return_value=inventory), patch('httpx.post') as post:
            with self.assertRaisesRegex(RuntimeError, 'inventory-digest'):
                candidate.prepare_candidate()
            post.assert_not_called()

    def test_changed_registry_manifest_never_downloads(self):
        with patch('httpx.get', side_effect=[response({'models': []}), response({}, b'changed')]), \
                patch('httpx.post') as post:
            with self.assertRaisesRegex(RuntimeError, 'registry-digest'):
                candidate.prepare_candidate()
            post.assert_not_called()

    def test_disk_budget_blocks_download(self):
        manifest = {'config': {'size': 10}, 'layers': [{'size': 1000}]}
        content = json.dumps(manifest).encode()
        profiles = [('qwen3.5:4b', hashlib.sha256(content).hexdigest())]
        with patch.object(candidate, 'PROFILES', profiles), \
                patch('httpx.get', side_effect=[response({'models': []}), response(manifest, content)]), \
                patch('shutil.disk_usage', return_value=types.SimpleNamespace(free=1)), \
                patch('httpx.post') as post:
            with self.assertRaisesRegex(RuntimeError, 'disk-budget'):
                candidate.prepare_candidate()
            post.assert_not_called()

    def test_successful_pull_still_requires_exact_local_digest(self):
        manifest = {'config': {'size': 10}, 'layers': [{'size': 1000}]}
        content = json.dumps(manifest).encode()
        profiles = [('qwen3.5:4b', hashlib.sha256(content).hexdigest())]
        with patch.object(candidate, 'PROFILES', profiles), \
                patch('httpx.get', side_effect=[response({'models': []}), response(manifest, content),
                    response({'models': [{'name': profiles[0][0], 'digest': 'moved'}]})]), \
                patch('shutil.disk_usage', return_value=types.SimpleNamespace(free=20_000_000_000)), \
                patch('httpx.post', return_value=response({'status': 'success'})):
            with self.assertRaisesRegex(RuntimeError, 'downloaded-digest'):
                candidate.prepare_candidate()

    def test_quality_diagnostics_do_not_weaken_or_export_content(self):
        body = {'is_partial': True, 'version': 1, 'decisions': [],
                'action_items': [{'text': SOURCE[0], 'owner': 'Ayşe', 'due_date': 'cuma günü'}],
                'ungrounded_count': 0, 'grounding_policy': 'verified_only', 'live_cursor': {}}
        self.assertTrue(metadata(body, 1, [], [0], 1)['qualityPass'])
        body['action_items'][0]['owner'] = 'wrong-owner'
        result = metadata(body, 1, [], [0], 1)
        self.assertFalse(result['qualityPass'])
        self.assertTrue(result['qualityChecks']['actionText'])
        self.assertFalse(result['qualityChecks']['actionOwnerDate'])
        self.assertNotIn('wrong-owner', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
