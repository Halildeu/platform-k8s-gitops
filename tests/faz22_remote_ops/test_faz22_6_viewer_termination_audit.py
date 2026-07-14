import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

from tests.faz22_remote_ops import test_faz22_6_viewer_audit_summary as audit_fixtures


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/build-view-only-viewer-termination-audit.py"
SPEC = importlib.util.spec_from_file_location("viewer_termination_audit", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def recording_row(seq, kind, content_hash, previous=MODULE.GENESIS_HASH):
    row = {
        "chainId": audit_fixtures.SESSION,
        "seq": seq,
        "timestampMillis": 1783987560000 + seq,
        "kind": kind,
        "contentHash": content_hash,
        "previousHash": previous,
        "entryHash": "0" * 64,
    }
    row["entryHash"] = MODULE.recording_entry_hash(row)
    return row


def recording_chain(kill_ack=False):
    first = recording_row(0, "POLICY_EVENT", hashlib.sha256(b"permit").hexdigest())
    rows = [first]
    if kill_ack:
        rows.append(recording_row(
            1, "POLICY_EVENT", hashlib.sha256(MODULE.KILL_ACK_EVENT.encode()).hexdigest(),
            first["entryHash"],
        ))
    return ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode()


class ViewerTerminationAuditTest(unittest.TestCase):
    def build(self, case_name, raw_recording=None):
        return MODULE.build(
            audit_fixtures.raw_chain(),
            raw_recording or recording_chain(case_name == "killOrRevoke"),
            case_name,
            audit_fixtures.SESSION,
            audit_fixtures.browser()["binding"],
            "a" * 40,
            "2026-07-14T00:06:01Z",
        )

    def test_verifies_view_stop_and_operator_kill_ack_chains(self):
        result = self.build("killOrRevoke")
        self.assertTrue(result["chainVerified"])
        self.assertEqual("VIEW_STOP", result["eventType"])
        self.assertEqual(101, result["framesDelivered"])
        self.assertEqual("tenant-audit-chain-builder", result["verificationSource"])
        self.assertNotIn(audit_fixtures.SESSION, json.dumps(result))
        self.assertNotIn(audit_fixtures.OPERATOR, json.dumps(result))

    def test_non_kill_case_accepts_chain_without_operator_ack(self):
        result = self.build("heartbeatLoss")
        self.assertEqual("heartbeatLoss", result["caseName"])

    def test_rejects_kill_case_without_durable_ack(self):
        with self.assertRaisesRegex(ValueError, "exactly one durable"):
            self.build("killOrRevoke", recording_chain(False))

    def test_rejects_non_kill_case_with_operator_ack(self):
        with self.assertRaisesRegex(ValueError, "unexpected operator KILL ACK"):
            self.build("ttlExpiry", recording_chain(True))

    def test_rejects_tampered_session_chain(self):
        rows = [json.loads(line) for line in recording_chain(True).splitlines()]
        rows[0]["contentHash"] = "tampered"
        raw = ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode()
        with self.assertRaisesRegex(ValueError, "entry hash mismatch"):
            self.build("killOrRevoke", raw)

    def test_rejects_wrong_session_binding(self):
        binding = dict(audit_fixtures.browser()["binding"])
        binding["sessionSha256"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(ValueError, "session binding mismatch"):
            MODULE.build(
                audit_fixtures.raw_chain(), recording_chain(False), "localAbort",
                audit_fixtures.SESSION, binding, "a" * 40, "2026-07-14T00:06:01Z",
            )


if __name__ == "__main__":
    unittest.main()
