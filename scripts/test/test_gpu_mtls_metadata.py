"""Guard fixed target, host key checks and redacted failures of read-only SSH."""
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'faz24'))
import gpu_mtls_metadata as module


def response(out='', code=0, err=''):
    return types.SimpleNamespace(stdout=out, returncode=code, stderr=err)


CONFIG = ('hostname 10.99.0.2\nuser denetimpc\nidentityfile /fixed/id_denetim\n'
          'userknownhostsfile /fixed/known_hosts\n')


class MetadataTests(unittest.TestCase):
    def test_wrong_target_is_rejected_before_remote_execution(self):
        with patch.object(module.subprocess, 'run', return_value=response(CONFIG.replace('10.99.0.2', 'other'))) as run:
            with self.assertRaisesRegex(RuntimeError, 'unexpected-governed'):
                module.collect()
            self.assertEqual(run.call_count, 1)

    def test_host_key_is_required_and_remote_errors_are_not_forwarded(self):
        for pin_code in (1, 0):
            with self.subTest(pin_code=pin_code), patch.object(module.Path, 'is_file', return_value=True), \
                 patch.object(module.Path, 'stat', return_value=types.SimpleNamespace(st_mode=0o600)), \
                 patch.object(module.subprocess, 'run', side_effect=[response(CONFIG), response(code=pin_code),
                              response('private output', 1, 'private error')]) as run:
                if pin_code:
                    with self.assertRaisesRegex(RuntimeError, 'host-key-pin-missing'):
                        module.collect()
                    self.assertEqual(run.call_count, 2)
                else:
                    result = module.collect()
                    self.assertNotIn('private', json.dumps(result))
                    command = run.call_args.args[0]
                    self.assertIn('StrictHostKeyChecking=yes', command)
                    self.assertIn('denetim-pc', command)
                    self.assertNotIn('Set-ScheduledTask', module.REMOTE_SCRIPT)


if __name__ == '__main__':
    unittest.main()
