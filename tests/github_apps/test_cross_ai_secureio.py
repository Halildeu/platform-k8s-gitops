from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.secureio import (
    read_private_text,
    write_private_json_exclusive,
)


class SecureIOTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_private_input_requires_exact_owner_only_regular_file(self) -> None:
        prompt = self.root / "prompt"
        prompt.write_text("review exact scope", encoding="utf-8")
        prompt.chmod(0o600)
        self.assertEqual(
            read_private_text(prompt, label="prompt", maximum=1024),
            "review exact scope",
        )
        prompt.chmod(0o640)
        with self.assertRaisesRegex(PolicyError, "PRIVATE_INPUT_INVALID"):
            read_private_text(prompt, label="prompt", maximum=1024)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires O_NOFOLLOW")
    def test_private_input_rejects_symlink(self) -> None:
        prompt = self.root / "prompt"
        prompt.write_text("review exact scope", encoding="utf-8")
        prompt.chmod(0o600)
        link = self.root / "prompt-link"
        link.symlink_to(prompt)
        with self.assertRaisesRegex(PolicyError, "PRIVATE_INPUT_INVALID"):
            read_private_text(link, label="prompt", maximum=1024)

    def test_private_output_is_create_once_and_mode_0600(self) -> None:
        output = self.root / "evidence.json"
        write_private_json_exclusive(output, {"value": "signed"})
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(output.read_bytes(), b'{"value":"signed"}')
        with self.assertRaisesRegex(PolicyError, "PRIVATE_OUTPUT_INVALID"):
            write_private_json_exclusive(output, {"value": "replacement"})


if __name__ == "__main__":
    unittest.main()
