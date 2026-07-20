from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROVISIONER = (ROOT / "scripts/ats/provision-test-keycloak.sh").read_text()
SMOKE = (ROOT / "scripts/ats/d29-smoke.sh").read_text()
RUNBOOK = (ROOT / "docs/RB-ats-39d-testai.md").read_text()

# 15 normal permissions = 13 mevcut ana perms (main baseline) + 2 screening (Faz 25 #2441)
NORMAL_PERMISSIONS = {
    "ats.consent.write",
    "ats.recording.write",
    "ats.transcription.write",
    "ats.transcript.read",
    "ats.citation.write",
    "ats.screening.write",
    "ats.screening.read",
    "ats.review.write",
    "ats.review.read",
    "ats.application.read",
    "ats.application.status.write",
    "ats.export.read",
    "ats.export.write",
    "ats.dsar.write",
    "ats.erasure.execute",
}
READER_ROLES = {"ats.transcript.read", "ats.screening.read", "ats.review.read"}
REVIEWER_ROLES = {
    "ats.consent.write",
    "ats.recording.write",
    "ats.transcription.write",
    "ats.transcript.read",
    "ats.citation.write",
    "ats.screening.write",
    "ats.screening.read",
    "ats.review.write",
    "ats.review.read",
}
RECRUITER_ROLES = {"ats.application.read", "ats.application.status.write"}


def shell_assignment(name: str) -> str:
    match = re.search(rf'^{re.escape(name)}="([^"]+)"$', PROVISIONER, re.MULTILINE)
    if not match:
        raise AssertionError(f"shell assignment missing: {name}")
    return match.group(1)


def grant_set(variable: str) -> set[str]:
    match = re.search(
        rf'^grant "\${re.escape(variable)}" ([^\n]+)$', PROVISIONER, re.MULTILINE
    )
    if not match:
        raise AssertionError(f"grant line missing: {variable}")
    return set(match.group(1).split())


def asserted_role_set(variable: str) -> set[str]:
    match = re.search(
        rf'^assert_roles_exact "\${re.escape(variable)}" [^ ]+ ([^\n]+)$',
        PROVISIONER,
        re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"assert_roles_exact line missing: {variable}")
    return set(match.group(1).split())


class ScreeningScopeDeliveryContractTest(unittest.TestCase):
    def test_normal_permission_set_is_exact_and_repair_stays_outside(self) -> None:
        self.assertEqual(set(shell_assignment("PERMS").split()), NORMAL_PERMISSIONS)
        self.assertEqual(shell_assignment("REPAIR_PERM"), "ats.export.repair")
        self.assertNotIn("ats.export.repair", NORMAL_PERMISSIONS)
        self.assertIn("for p in $PERMS $REPAIR_PERM", PROVISIONER)
        self.assertIn("for name in ats-api-audience $PERMS $REPAIR_PERM", PROVISIONER)

    def test_persona_matrix_is_exact_least_privilege(self) -> None:
        self.assertEqual(grant_set("READER_UID"), READER_ROLES)
        self.assertEqual(grant_set("REVIEWER_UID"), REVIEWER_ROLES)
        self.assertEqual(grant_set("RECRUITER_UID"), RECRUITER_ROLES)
        self.assertEqual(asserted_role_set("READER_UID"), READER_ROLES)
        self.assertEqual(asserted_role_set("REVIEWER_UID"), REVIEWER_ROLES)
        self.assertEqual(asserted_role_set("RECRUITER_UID"), RECRUITER_ROLES)
        self.assertEqual(len(NORMAL_PERMISSIONS), 15)
        self.assertNotIn("ats.screening.write", READER_ROLES)
        self.assertNotIn("ats.screening.write", RECRUITER_ROLES)
        self.assertNotIn("ats.screening.read", RECRUITER_ROLES)
        self.assertTrue(REVIEWER_ROLES.isdisjoint({
            "ats.export.read",
            "ats.export.write",
            "ats.dsar.write",
            "ats.erasure.execute",
            "ats.application.read",
            "ats.application.status.write",
        }))
        self.assertNotRegex(PROVISIONER, r"grant[^\n]*(?:ats\.export\.repair|\$REPAIR_PERM)")

    def test_exact_role_and_default_scope_counts_fail_closed(self) -> None:
        self.assertIn('[ "$ROLE_N" -eq 16 ]', PROVISIONER)
        self.assertIn('[ "$BOUND_N" -eq 17 ]', PROVISIONER)
        self.assertIn("ASSERT OK: 16 rol + 17 default-scope", PROVISIONER)

    def test_screening_runtime_smoke_is_explicit_and_proves_split_authority(self) -> None:
        for needle in (
            'ATS_SCREENING_EXPECTED:-0',
            'X-ATS-Idempotency-Key',
            'x-ats-replay: false',
            'x-ats-replay: true',
            'reader screening.read -> 200',
            'reader screening.write -> 403',
            'roleless screening.read -> 403',
            'screening response pointer-only',
            'TOP_KEYS =',
            'SOURCE_KEYS =',
            'FINDING_KEYS =',
            'SPAN_KEYS =',
            'cmp -s "$T/d29-screen-create.json" "$T/d29-screen-replay.json"',
        ):
            self.assertIn(needle, SMOKE)

    def test_runbook_states_current_counts_and_non_activation_boundary(self) -> None:
        self.assertIn("16 client-role", RUNBOOK)
        self.assertIn("17 default-scope", RUNBOOK)
        self.assertIn("ATS_SCREENING_EXPECTED=1", RUNBOOK)
        self.assertIn("prod'a HİÇBİR adım uygulanmaz", RUNBOOK)


if __name__ == "__main__":
    unittest.main()
