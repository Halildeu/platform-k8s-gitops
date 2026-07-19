#!/usr/bin/env python3
"""Signed carrier verification and transport-boundary regressions."""

from __future__ import annotations

import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.ai import post_cross_ai_evidence as POST
from scripts.ai.trusted_cross_ai_evidence import (
    GITHUB_COMMENT_MAX_CHARS,
    TrustedEvidenceError,
    canonical_bytes,
    validate_github_comment_transport,
    validate_evidence,
    validate_response_hygiene,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.provider import CODEX_ROUTINE_MODEL
from tests.ai.signed_evidence_fixture import make_signed_evidence


class EvidenceValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = make_signed_evidence()

    def validate(self, evidence=None):
        return validate_evidence(
            evidence or self.fixture.evidence,
            trust_root=self.fixture.authority.trust_root,
            revocations_envelope=self.fixture.authority.revocations_envelope,
            expected_trust_root_sha256=(
                self.fixture.authority.expected_trust_root_sha256
            ),
            codex_executable_policy=(
                self.fixture.authority.codex_executable_policy
            ),
            expected_bindings=self.fixture.bindings,
            scope_bytes=self.fixture.scope_bytes,
            now=self.fixture.factory.now,
            require_agree=True,
        )

    def test_accepts_exact_signed_launch_subject_prompt_response_and_authority(self) -> None:
        validated = self.validate()
        self.assertEqual(validated["review"]["providerFamily"], "openai")
        self.assertEqual(validated["review"]["modelId"], "gpt-5.6-sol")
        self.assertEqual(
            validated["review"]["modelIdentityClass"],
            "trusted-launch-attested",
        )

    def test_github_comment_transport_is_bounded_to_actual_65536_limit(self) -> None:
        validate_github_comment_transport("x" * GITHUB_COMMENT_MAX_CHARS)
        with self.assertRaisesRegex(TrustedEvidenceError, "65536-character"):
            validate_github_comment_transport("x" * (GITHUB_COMMENT_MAX_CHARS + 1))
        # A character-count pass cannot smuggle an oversized UTF-8 payload.
        with self.assertRaisesRegex(TrustedEvidenceError, "65536-character"):
            validate_github_comment_transport("ş" * GITHUB_COMMENT_MAX_CHARS)

    def test_rejects_response_repackaging_even_when_outer_text_is_well_formed(self) -> None:
        evidence = copy.deepcopy(self.fixture.evidence)
        evidence["response"] = (
            "P0\nNone\nP1\n"
            "- P1-REPACKAGED_RESPONSE | scripts/ai/example.py:10 | "
            "A different canonical response was repackaged.\n"
            "P2\nNone\nVERDICT: REVISE"
        )
        with self.assertRaisesRegex(TrustedEvidenceError, "leaf binding mismatch"):
            validate_evidence(
                evidence,
                trust_root=self.fixture.authority.trust_root,
                revocations_envelope=self.fixture.authority.revocations_envelope,
                expected_trust_root_sha256=(
                    self.fixture.authority.expected_trust_root_sha256
                ),
                codex_executable_policy=(
                    self.fixture.authority.codex_executable_policy
                ),
                expected_bindings=self.fixture.bindings,
                scope_bytes=self.fixture.scope_bytes,
                now=self.fixture.factory.now,
                require_agree=False,
            )

    def test_rejects_sensitive_response_before_transport_or_signature_binding(self) -> None:
        sensitive_values = (
            "".join(("candidate", "@example.com")),
            "".join(("+90 532 ", "123 45 67")),
            "".join(("-----BEGIN ", "PRIVATE KEY-----")),
            "".join(("Bearer ", "abcdefghijklmnopqrstuvwxyz")),
            "".join(("eyJabcdefgh.", "abcdefgh.abcdefgh")),
            "".join(("ghp_", "abcdefghijklmnopqrstuvwxyz")),
            "".join(("client_", "secret=supersecretvalue")),
            "".join(("https://example.com/", "hooks/secret-value")),
            "".join(("Cook", "ie: session=secretvalue")),
        )
        for value in sensitive_values:
            with self.subTest(value=value.split("=")[0]):
                with self.assertRaisesRegex(
                    TrustedEvidenceError, "contains sensitive data"
                ):
                    validate_response_hygiene(f"finding contains {value}")

        evidence = copy.deepcopy(self.fixture.evidence)
        evidence["response"] = (
            "P0\nNone\nP1\n"
            "- P1-SENSITIVE_RESPONSE | scripts/ai/example.py:10 | "
            f"{sensitive_values[3]}\n"
            "P2\nNone\nVERDICT: REVISE"
        )
        with self.assertRaisesRegex(TrustedEvidenceError, "contains sensitive data"):
            validate_evidence(
                evidence,
                trust_root=self.fixture.authority.trust_root,
                revocations_envelope=self.fixture.authority.revocations_envelope,
                expected_trust_root_sha256=(
                    self.fixture.authority.expected_trust_root_sha256
                ),
                codex_executable_policy=(
                    self.fixture.authority.codex_executable_policy
                ),
                expected_bindings=self.fixture.bindings,
                scope_bytes=self.fixture.scope_bytes,
                now=self.fixture.factory.now,
                require_agree=False,
            )

    def test_rejects_prompt_or_scope_rebinding_and_unrelated_subject(self) -> None:
        wrong_scope = self.fixture.scope_bytes + b"unrelated\n"
        with self.assertRaisesRegex(TrustedEvidenceError, "scope bytes"):
            validate_evidence(
                self.fixture.evidence,
                trust_root=self.fixture.authority.trust_root,
                revocations_envelope=self.fixture.authority.revocations_envelope,
                expected_trust_root_sha256=(
                    self.fixture.authority.expected_trust_root_sha256
                ),
                codex_executable_policy=(
                    self.fixture.authority.codex_executable_policy
                ),
                expected_bindings=self.fixture.bindings,
                scope_bytes=wrong_scope,
                now=self.fixture.factory.now,
                require_agree=True,
            )
        evidence = copy.deepcopy(self.fixture.evidence)
        evidence["subject"]["promptSha256"] = "sha256:" + ("0" * 64)
        with self.assertRaisesRegex(TrustedEvidenceError, "subject or prompt"):
            self.validate(evidence)

    def test_rejects_session_reuse_leaf_copied_to_another_subject(self) -> None:
        evidence = copy.deepcopy(self.fixture.evidence)
        evidence["subject"]["headSha"] = "d" * 40
        bindings = dict(self.fixture.bindings)
        bindings["head_sha"] = "d" * 40
        with self.assertRaisesRegex(
            (PolicyError, TrustedEvidenceError),
            "REVIEW_SUBJECT_MISMATCH|subject or prompt",
        ):
            validate_evidence(
                evidence,
                trust_root=self.fixture.authority.trust_root,
                revocations_envelope=self.fixture.authority.revocations_envelope,
                expected_trust_root_sha256=(
                    self.fixture.authority.expected_trust_root_sha256
                ),
                codex_executable_policy=(
                    self.fixture.authority.codex_executable_policy
                ),
                expected_bindings=bindings,
                scope_bytes=self.fixture.scope_bytes,
                now=self.fixture.factory.now,
                require_agree=True,
            )

    def test_rejects_forged_envelope_and_tampered_capability(self) -> None:
        forged = copy.deepcopy(self.fixture.evidence)
        forged["review_envelope"]["signatures"][0]["sig"] = base64.b64encode(
            b"x" * 64
        ).decode("ascii")
        from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest

        forged["review_envelope_sha256"] = sha256_digest(forged["review_envelope"])
        with self.assertRaisesRegex(PolicyError, "DSSE_SIGNATURE_INVALID"):
            self.validate(forged)

        capability = copy.deepcopy(self.fixture.evidence)
        capability["capability_snapshot"]["sandbox"] = "workspace-write"
        with self.assertRaisesRegex(TrustedEvidenceError, "fixed route"):
            self.validate(capability)

    def test_verifier_rejects_executable_provenance_outside_its_own_policy(self) -> None:
        policy = copy.deepcopy(self.fixture.authority.codex_executable_policy)
        policy["allowedExecutables"][0]["cliSha256"] = "sha256:" + ("0" * 64)
        with self.assertRaisesRegex(TrustedEvidenceError, "independently pinned"):
            validate_evidence(
                self.fixture.evidence,
                trust_root=self.fixture.authority.trust_root,
                revocations_envelope=self.fixture.authority.revocations_envelope,
                expected_trust_root_sha256=(
                    self.fixture.authority.expected_trust_root_sha256
                ),
                codex_executable_policy=policy,
                expected_bindings=self.fixture.bindings,
                scope_bytes=self.fixture.scope_bytes,
                now=self.fixture.factory.now,
                require_agree=True,
            )

    def test_loader_requires_exact_canonical_create_once_carrier_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_bytes(canonical_bytes(self.fixture.evidence))
            self.assertEqual(POST.load_canonical_evidence(path), self.fixture.evidence)
            path.write_text(json.dumps(self.fixture.evidence), encoding="utf-8")
            with self.assertRaises(SystemExit):
                POST.load_canonical_evidence(path)

    def test_transport_can_self_verify_the_fixed_routine_model_without_reclassifying_it(self) -> None:
        fixture = make_signed_evidence(model=CODEX_ROUTINE_MODEL)
        validated = validate_evidence(
            fixture.evidence,
            trust_root=fixture.authority.trust_root,
            revocations_envelope=fixture.authority.revocations_envelope,
            expected_trust_root_sha256=fixture.authority.expected_trust_root_sha256,
            codex_executable_policy=fixture.authority.codex_executable_policy,
            expected_bindings=fixture.bindings,
            scope_bytes=fixture.scope_bytes,
            now=fixture.factory.now,
            require_agree=True,
            expected_model=CODEX_ROUTINE_MODEL,
        )
        self.assertEqual(validated["review"]["modelId"], CODEX_ROUTINE_MODEL)


if __name__ == "__main__":
    unittest.main()
