"""ADR-0011 BG-1 unit tests — PR boundary declaration CI gate."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "governance" / "check_pr_boundary_declaration.py"

spec = importlib.util.spec_from_file_location("check_pr_boundary_declaration", SCRIPT_PATH)
check_bg1 = importlib.util.module_from_spec(spec)
sys.modules["check_pr_boundary_declaration"] = check_bg1
spec.loader.exec_module(check_bg1)


def _make_body(marked: list[str], with_evidence: bool = False, evidence_value: str = "https://github.com/example/issues/1") -> str:
    """Helper: build PR body with selectively marked boundary classes."""
    lines = [
        "## Summary",
        "Test PR.",
        "",
        "## Boundary declaration (ADR-0011 §2.3)",
        "",
        "This PR includes:",
    ]
    for cls in check_bg1.EXPECTED_CLASSES:
        check = "[x]" if cls in marked else "[ ]"
        suffix = " (Codex consensus only)" if cls == "none of the above" else ""
        lines.append(f"- {check} {cls}{suffix}")
    if with_evidence:
        lines.extend([
            "",
            f"User-approval evidence: {evidence_value}",
        ])
    return "\n".join(lines)


class TestBlockPresence(unittest.TestCase):
    def test_missing_heading_fails(self) -> None:
        body = "## Summary\nNo boundary block here."
        report = check_bg1.run_all_checks(body, [])
        self.assertEqual(report.overall, "FAIL")
        c = next(c for c in report.checks if c.name == "boundary_block_present")
        self.assertFalse(c.passed)

    def test_block_with_seven_classes_passes_presence(self) -> None:
        body = _make_body(marked=["none of the above"])
        report = check_bg1.run_all_checks(body, [])
        c = next(c for c in report.checks if c.name == "seven_classes_present")
        self.assertTrue(c.passed)


class TestNoneExclusivity(unittest.TestCase):
    def test_none_alone_passes(self) -> None:
        body = _make_body(marked=["none of the above"])
        report = check_bg1.run_all_checks(body, [])
        c = next(c for c in report.checks if c.name == "none_exclusivity")
        self.assertTrue(c.passed)

    def test_none_with_other_class_fails(self) -> None:
        body = _make_body(marked=["none of the above", "credential-read"])
        report = check_bg1.run_all_checks(body, ["user-approval-required"])
        c = next(c for c in report.checks if c.name == "none_exclusivity")
        self.assertFalse(c.passed)
        self.assertIn("credential-read", " ".join(c.details))


class TestUserApprovalEvidence(unittest.TestCase):
    def test_credential_read_requires_evidence(self) -> None:
        body = _make_body(marked=["credential-read"])  # no evidence
        report = check_bg1.run_all_checks(body, ["user-approval-required"])
        c = next(c for c in report.checks if c.name == "user_approval_evidence")
        self.assertFalse(c.passed)

    def test_credential_read_with_link_passes(self) -> None:
        body = _make_body(marked=["credential-read"], with_evidence=True)
        report = check_bg1.run_all_checks(body, ["user-approval-required"])
        c = next(c for c in report.checks if c.name == "user_approval_evidence")
        self.assertTrue(c.passed)

    def test_credential_write_with_na_fails(self) -> None:
        body = _make_body(
            marked=["credential-write"], with_evidence=True, evidence_value="N/A"
        )
        report = check_bg1.run_all_checks(body, ["user-approval-required"])
        c = next(c for c in report.checks if c.name == "user_approval_evidence")
        self.assertFalse(c.passed)


class TestUserApprovalLabel(unittest.TestCase):
    def test_credential_read_without_label_fails(self) -> None:
        body = _make_body(marked=["credential-read"], with_evidence=True)
        report = check_bg1.run_all_checks(body, [])  # no label
        c = next(c for c in report.checks if c.name == "user_approval_label")
        self.assertFalse(c.passed)

    def test_credential_read_with_label_passes(self) -> None:
        body = _make_body(marked=["credential-read"], with_evidence=True)
        report = check_bg1.run_all_checks(body, ["user-approval-required"])
        c = next(c for c in report.checks if c.name == "user_approval_label")
        self.assertTrue(c.passed)

    def test_state_mutation_test_no_label_required(self) -> None:
        """state-mutation (test cluster) is NOT a user-approval class."""
        body = _make_body(marked=["state-mutation (test cluster)"])
        report = check_bg1.run_all_checks(body, [])
        c = next(c for c in report.checks if c.name == "user_approval_label")
        self.assertTrue(c.passed)


class TestAtLeastOneMarked(unittest.TestCase):
    def test_no_class_marked_fails(self) -> None:
        body = _make_body(marked=[])
        report = check_bg1.run_all_checks(body, [])
        c = next(c for c in report.checks if c.name == "at_least_one_marked")
        self.assertFalse(c.passed)


class TestEventPayloadParser(unittest.TestCase):
    def test_event_payload_extraction(self) -> None:
        body = _make_body(marked=["none of the above"])
        payload = {
            "pull_request": {
                "body": body,
                "labels": [{"name": "feature"}, {"name": "size/M"}],
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(payload, tmp)
            tmp_path = tmp.name

        try:
            extracted_body, extracted_labels = check_bg1.read_event_payload(tmp_path)
            self.assertEqual(extracted_body, body)
            self.assertEqual(extracted_labels, ["feature", "size/M"])
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_event_payload_missing_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            check_bg1.read_event_payload("/tmp/nonexistent-event-payload.json")


class TestRealBoundaryFromOurOwnPR(unittest.TestCase):
    """Smoke: verify our own boundary block format passes."""

    def test_our_pr_format_passes(self) -> None:
        body = """## Summary
Test summary.

## Boundary declaration (ADR-0011 §2.3)

This PR includes:
- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [x] none of the above (Codex consensus only — read-only static analysis)
"""
        report = check_bg1.run_all_checks(body, [])
        for c in report.checks:
            if not c.passed:
                print(f"\n  ✗ {c.name}: {c.message}")
                for d in c.details:
                    print(f"      → {d}")
        self.assertEqual(report.overall, "PASS")


class TestUserCommunicationClass(unittest.TestCase):
    """ADR-0013 D45 BG-NOTIFY-1: user-communication class added."""

    def test_user_communication_in_expected_classes(self) -> None:
        self.assertIn("user-communication", check_bg1.EXPECTED_CLASSES)

    def test_user_communication_requires_user_approval(self) -> None:
        self.assertIn("user-communication", check_bg1.USER_APPROVAL_CLASSES)

    def test_user_communication_marked_requires_evidence(self) -> None:
        body = _make_body(marked=["user-communication"])
        report = check_bg1.run_all_checks(body, ["user-approval-required"])
        c = next(c for c in report.checks if c.name == "user_approval_evidence")
        self.assertFalse(c.passed)

    def test_user_communication_with_evidence_and_label_passes(self) -> None:
        body = _make_body(marked=["user-communication"], with_evidence=True)
        report = check_bg1.run_all_checks(body, ["user-approval-required"])
        c = next(c for c in report.checks if c.name == "user_approval_evidence")
        self.assertTrue(c.passed)
        c = next(c for c in report.checks if c.name == "user_approval_label")
        self.assertTrue(c.passed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
