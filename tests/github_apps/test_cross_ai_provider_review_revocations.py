from __future__ import annotations

import base64
import copy
import importlib.util
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    EvidenceVerifier,
    REVOCATIONS_PAYLOAD_TYPE,
)
from scripts.github_apps.cross_ai_deployment_policy.dsse import pae
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts/ops/build_cross_ai_provider_review_revocations.py"
)
SPEC = importlib.util.spec_from_file_location("provider_review_revocations", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load provider-review revocation release module")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StaticSigner:
    def __init__(self, key_id: str, key: Ed25519PrivateKey) -> None:
        self._key_id = key_id
        self.key = key

    @property
    def key_id(self) -> str:
        return self._key_id

    def sign_json_envelope(self, *, payload_type, payload):
        payload_bytes = canonical_bytes(payload)
        return {
            "payloadType": payload_type,
            "payload": base64.b64encode(payload_bytes).decode("ascii"),
            "signatures": [
                {
                    "keyid": self.key_id,
                    "sig": base64.b64encode(
                        self.key.sign(pae(payload_type, payload_bytes))
                    ).decode("ascii"),
                }
            ],
        }


class ProviderReviewRevocationReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = FixtureFactory("v2")
        self.trust_root = self.factory.trust_root()
        self.signer = StaticSigner(
            self.factory.REVOCATION_KEY_ID,
            self.factory.keys[self.factory.REVOCATION_KEY_ID],
        )
        self.release_input = {
            "schemaVersion": MODULE.RELEASE_INPUT_SCHEMA,
            "entries": [],
        }

    def build(self, **overrides):
        values = {
            "trust_root": self.trust_root,
            "expected_trust_root_sha256": sha256_digest(self.trust_root),
            "release_input": self.release_input,
            "revocation_set_id": "20000000-0000-4000-8000-000000000099",
            "issued_at": "2026-07-18T20:00:00Z",
            "next_update": "2026-07-18T21:00:00Z",
            "signer": self.signer,
        }
        values.update(overrides)
        return MODULE.build_signed_revocations(**values)

    def test_builds_signed_bounded_revocations_accepted_by_pinned_verifier(self) -> None:
        envelope = self.build()
        verifier = EvidenceVerifier(
            trust_root=self.trust_root,
            revocations_envelope=envelope,
            now=self.factory.now,
            expected_trust_root_sha256=sha256_digest(self.trust_root),
        )
        self.assertEqual(verifier.revocations["entries"], [])
        self.assertEqual(envelope["payloadType"], REVOCATIONS_PAYLOAD_TYPE)

    def test_sorts_entries_and_rejects_duplicate_revocation_identity(self) -> None:
        self.release_input["entries"] = [
            {
                "type": "review",
                "id": "sha256:" + ("b" * 64),
                "effectiveAt": "2026-07-18T20:00:00Z",
                "reasonCode": "REVIEW_COMPROMISED",
            },
            {
                "type": "key",
                "id": self.factory.OPENAI_KEY_ID,
                "effectiveAt": "2026-07-18T20:00:00Z",
                "reasonCode": "KEY_ROTATED",
            },
        ]
        envelope = self.build()
        import json

        payload = json.loads(base64.b64decode(envelope["payload"], validate=True))
        self.assertEqual([item["type"] for item in payload["entries"]], ["key", "review"])

        duplicate = copy.deepcopy(self.release_input)
        duplicate["entries"].append(copy.deepcopy(duplicate["entries"][0]))
        with self.assertRaisesRegex(PolicyError, "REVOCATION_RELEASE_INPUT_INVALID"):
            self.build(release_input=duplicate)

    def test_rejects_stale_window_wrong_pin_and_wrong_signer(self) -> None:
        with self.assertRaisesRegex(PolicyError, "REVOCATION_RELEASE_LIFETIME_INVALID"):
            self.build(next_update="2026-07-18T21:00:01Z")
        with self.assertRaisesRegex(PolicyError, "REVOCATION_RELEASE_ROOT_PIN_MISMATCH"):
            self.build(expected_trust_root_sha256="sha256:" + ("0" * 64))
        wrong = StaticSigner(
            self.factory.OPENAI_KEY_ID,
            self.factory.keys[self.factory.OPENAI_KEY_ID],
        )
        with self.assertRaisesRegex(PolicyError, "REVOCATION_RELEASE_SIGNER_INVALID"):
            self.build(signer=wrong)

    def test_verifier_rejects_revocation_interval_outside_root_or_signer_validity(self) -> None:
        trust_root = copy.deepcopy(self.trust_root)
        trust_root["expiresAt"] = "2026-07-18T20:30:00Z"
        with self.assertRaisesRegex(PolicyError, "REVOCATION_RELEASE_LIFETIME_INVALID"):
            self.build(
                trust_root=trust_root,
                expected_trust_root_sha256=sha256_digest(trust_root),
            )

        trust_root = copy.deepcopy(self.trust_root)
        signer_entry = next(
            item for item in trust_root["keys"] if item["role"] == "revocation"
        )
        signer_entry["notAfter"] = "2026-07-18T20:30:00Z"
        with self.assertRaisesRegex(PolicyError, "REVOCATION_RELEASE_SIGNER_INVALID"):
            self.build(
                trust_root=trust_root,
                expected_trust_root_sha256=sha256_digest(trust_root),
            )

    def test_rejects_forged_signature(self) -> None:
        wrong_key = Ed25519PrivateKey.from_private_bytes(b"\x7f" * 32)
        forged = StaticSigner(self.factory.REVOCATION_KEY_ID, wrong_key)
        with self.assertRaisesRegex(PolicyError, "DSSE_SIGNATURE_INVALID"):
            self.build(signer=forged)


if __name__ == "__main__":
    unittest.main()
