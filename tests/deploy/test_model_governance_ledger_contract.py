from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "scripts/ats/verify-model-governance-ledger.py"
LEGACY_ENTRY_HASH = "a" * 64
ARTIFACT_ENTRY_HASH = "b" * 64
GENESIS_HASH = "0" * 64


def legacy_row() -> str:
    return "|".join(
        (
            "0",
            "mgt_25260000-0000-4000-8000-000000000001",
            "mapr_549a8e22a2c6f3c445be3e2405262bba5b80a78d72047fd95fa03deaa66a732d",
            "TRANSCRIBE",
            "UNINITIALIZED",
            "APPROVED",
            "cross-ai/faz25/2526",
            "INITIAL_APPROVAL",
            LEGACY_ENTRY_HASH,
            GENESIS_HASH,
        )
    )


def artifact_row(previous_hash: str = LEGACY_ENTRY_HASH) -> str:
    return "|".join(
        (
            "1",
            "mgt_25260000-0000-4000-8000-000000000002",
            "mapr_04cabd439b5b51992e86e215b9796f64d27b91dd951acdf542ab6635d517fc43",
            "TRANSCRIBE",
            "UNINITIALIZED",
            "APPROVED",
            "cross-ai/faz25/2526",
            "INITIAL_APPROVAL",
            ARTIFACT_ENTRY_HASH,
            previous_hash,
        )
    )


def verify(rows: list[str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(VERIFIER), *args],
        input="\n".join(rows) + ("\n" if rows else ""),
        text=True,
        capture_output=True,
        check=False,
    )


class ModelGovernanceLedgerContractTests(unittest.TestCase):
    def test_first_append_preserves_legacy_and_links_sequence_one(self):
        before = verify([legacy_row()], "--phase", "before")
        self.assertEqual(0, before.returncode, before.stderr)
        self.assertIn("state=legacy-only", before.stdout)

        after = verify(
            [legacy_row(), artifact_row()],
            "--phase",
            "after",
            "--append-sequence",
            "1",
            "--append-hash",
            ARTIFACT_ENTRY_HASH,
        )
        self.assertEqual(0, after.returncode, after.stderr)
        self.assertIn("state=artifact-approved", after.stdout)

    def test_idempotent_replay_accepts_the_same_exact_two_row_chain(self):
        rows = [legacy_row(), artifact_row()]
        before = verify(rows, "--phase", "before")
        self.assertEqual(0, before.returncode, before.stderr)
        after = verify(
            rows,
            "--phase",
            "after",
            "--append-sequence",
            "1",
            "--append-hash",
            ARTIFACT_ENTRY_HASH,
        )
        self.assertEqual(0, after.returncode, after.stderr)

    def test_rejects_empty_or_reset_ledger(self):
        result = verify([], "--phase", "before")
        self.assertNotEqual(0, result.returncode)

    def test_rejects_artifact_genesis_or_broken_previous_hash(self):
        for bad_previous in (GENESIS_HASH, "c" * 64):
            with self.subTest(previous_hash=bad_previous):
                result = verify(
                    [legacy_row(), artifact_row(bad_previous)],
                    "--phase",
                    "after",
                )
                self.assertNotEqual(0, result.returncode)

    def test_rejects_extra_rows(self):
        result = verify(
            [legacy_row(), artifact_row(), artifact_row()],
            "--phase",
            "after",
        )
        self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
