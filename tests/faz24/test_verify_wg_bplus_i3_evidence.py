#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ I3 evidence validator."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify-wg-bplus-i3-evidence.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class WgBplusI3EvidenceValidatorTest(unittest.TestCase):
    def run_validator(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(path)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_fixture_prints_who_when_what_summary(self):
        result = self.run_validator(FIXTURES / "wg-bplus-i3-valid.json")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz24 WG-B+ I3 evidence: PASS", result.stdout)
        self.assertIn("openssh-event-log: who=svc-denetim-agent", result.stdout)
        self.assertIn("staging-connection-log:", result.stdout)
        self.assertNotIn("Bearer ", result.stdout)

    def test_missing_required_check_fails(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"] = [check for check in data["checks"] if check["id"] != "time-sync"]

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing required check 'time-sync'", result.stderr)

    def test_secret_like_key_or_value_fails(self):
        result = self.run_validator(FIXTURES / "wg-bplus-i3-secret-leak.json")

        self.assertNotEqual(0, result.returncode)
        self.assertIn("forbidden_key", result.stderr)

    def test_secret_like_value_fails_without_committed_secret_fixture(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        jwt_parts = [
            "eyJhbGciOiJIUzI1NiJ9",
            "eyJzdWIiOiJzbW9rZSJ9",
            "fakefakefake",
        ]
        data["notes"] = "Bearer " + ".".join(jwt_parts)

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("secret_like_value", result.stderr)

    def test_redaction_flags_must_be_false(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["redaction"]["rawTranscriptIncluded"] = True

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("redaction.rawTranscriptIncluded must be false", result.stderr)

    def test_timestamp_and_evidence_ref_are_bounded(self):
        data = json.loads((FIXTURES / "wg-bplus-i3-valid.json").read_text(encoding="utf-8"))
        data["checks"][0]["when"] = "yesterday"
        data["checks"][0]["evidenceRef"] = "../../secret.txt"

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            result = self.run_validator(Path(tmp.name))

        self.assertNotEqual(0, result.returncode)
        self.assertIn("when must use UTC format", result.stderr)
        self.assertIn("evidenceRef must be a relative path", result.stderr)


if __name__ == "__main__":
    unittest.main()
