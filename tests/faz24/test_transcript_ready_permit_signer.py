from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
FAZ24 = ROOT / "scripts/faz24"
if str(FAZ24) not in sys.path:
    sys.path.insert(0, str(FAZ24))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import build_transcript_ready_permit_trust_root as trust_builder  # noqa: E402
import sign_transcript_ready_pre_enable_permit as permit_signer  # noqa: E402
import verify_transcript_ready_pre_enable_evidence as verdict_producer  # noqa: E402
from scripts.github_apps.cross_ai_deployment_policy.dsse import pae  # noqa: E402
from scripts.github_apps.cross_ai_deployment_policy.errors import (  # noqa: E402
    PolicyError,
)
from scripts.github_apps.cross_ai_deployment_policy.github import (  # noqa: E402
    HTTPResponse,
)
from transcript_ready_pre_enable_contract import (  # noqa: E402
    ContractError,
    PERMIT_PAYLOAD_TYPE,
    canonical_json,
)

NOW = dt.datetime(2026, 7, 20, 8, 0, tzinfo=dt.timezone.utc)
GITOPS_COMMIT = "a" * 40
BACKEND_COMMIT = "b" * 40
AI_COMMIT = "c" * 40
POLICY_SHA = "d" * 64
EVIDENCE_SHA = "e" * 64
IMAGE_DIGEST = "sha256:" + ("1" * 64)
STARTUP_SHA = "2" * 64
KEY_ID = "vault-transit://meeting-ai/transcript-ready-permit#v3"


class TransitTransport:
    def __init__(self, key: Ed25519PrivateKey, version: int = 3) -> None:
        self.key = key
        self.version = version
        self.calls: list[tuple] = []

    def request(self, method, url, *, headers, body=None, timeout=10.0):
        self.calls.append((method, url, dict(headers), body))
        request = json.loads(body)
        message = base64.b64decode(request["input"], validate=True)
        signature = self.key.sign(message)
        return HTTPResponse(
            200,
            {},
            canonical_json(
                {
                    "data": {
                        "signature": (
                            f"vault:v{self.version}:"
                            + base64.b64encode(signature).decode("ascii")
                        )
                    }
                }
            ),
        )


class TranscriptReadyPermitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.key = Ed25519PrivateKey.from_private_bytes(b"\x09" * 32)
        self.public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.token = self.root / "token"
        self.token.write_text("hvs." + ("t" * 40), encoding="ascii")
        self.token.chmod(0o600)
        self.receipt = self.root / "receipt.json"
        receipt = {
            "schemaVersion": "faz24.transcriptReadyPermitTransitReceipt.v1",
            "scope": "test-only",
            "vaultOrigin": "https://vault.test.example",
            "vaultClusterId": "test-cluster-1",
            "mount": "meeting-ai",
            "keyName": "transcript-ready-permit",
            "keyVersion": 3,
            "keyId": KEY_ID,
            "publicKeyBase64": base64.b64encode(self.public).decode("ascii"),
            "keyType": "ed25519",
            "derived": False,
            "exportable": False,
            "allowPlaintextBackup": False,
            "deletionAllowed": False,
            "supportsSigning": True,
            "verifiedAt": "2026-07-20T07:59:00Z",
            "requiresOutOfBandOwnerPin": True,
        }
        self.receipt.write_bytes(canonical_json(receipt))
        self.receipt_sha = hashlib.sha256(self.receipt.read_bytes()).hexdigest()
        self.trust_root = self.root / "trust-root.json"
        trust_root = trust_builder.build_trust_root(
            receipt_path=self.receipt,
            expected_receipt_sha256=self.receipt_sha,
            allowed_app_environments=["test"],
            not_before="2026-07-20T07:58:00Z",
            not_after="2026-07-21T08:00:00Z",
            now=NOW,
        )
        self.trust_root.write_bytes(canonical_json(trust_root))
        self.trust_sha = hashlib.sha256(self.trust_root.read_bytes()).hexdigest()
        self.verdict_path = self.root / "verdict.json"
        self.verdict = verdict_producer.build_verdict(
            checks=[
                verdict_producer.Check(
                    "all_live_bindings", True, "all exact live bindings passed"
                )
            ],
            context={
                "producerCapability": {
                    "transcriptImageDigest": IMAGE_DIGEST,
                    "backendCommit": BACKEND_COMMIT,
                },
                "liveTranscriptPod": {
                    "podUid": "11111111-1111-4111-8111-111111111111",
                    "imageDigest": IMAGE_DIGEST,
                    "observedAt": "2026-07-20T07:59:56Z",
                },
                "hostStartupGuard": {
                    "platformAiCommit": AI_COMMIT,
                    "startupScriptSha256": STARTUP_SHA,
                    "permitRequired": True,
                },
            },
            policy={"environment": {"appEnv": "test"}},
            expected_gitops_commit=GITOPS_COMMIT,
            policy_digest=POLICY_SHA,
            evidence_digest=EVIDENCE_SHA,
            generated_at=NOW,
        )
        self.verdict_path.write_text(
            json.dumps(self.verdict, indent=2, sort_keys=True), encoding="utf-8"
        )
        self.transport = TransitTransport(self.key)

    def sign(self, **overrides):
        arguments = {
            "verdict_path": self.verdict_path,
            "trust_root_path": self.trust_root,
            "expected_trust_root_sha256": self.trust_sha,
            "app_env": "test",
            "expected_gitops_commit": GITOPS_COMMIT,
            "expected_policy_sha256": POLICY_SHA,
            "expected_producer_image_digest": IMAGE_DIGEST,
            "vault_origin": "https://vault.test.example",
            "vault_token_file": self.token,
            "vault_mount": "meeting-ai",
            "vault_key_name": "transcript-ready-permit",
            "vault_key_version": 3,
            "now": NOW + dt.timedelta(seconds=30),
            "transport": self.transport,
        }
        arguments.update(overrides)
        return permit_signer.sign_permit(**arguments)

    def write_verdict(self, value: dict) -> None:
        self.verdict_path.write_text(
            json.dumps(value, indent=2, sort_keys=True), encoding="utf-8"
        )

    def test_v2_verdict_signs_and_signature_verifies(self) -> None:
        envelope, payload_bytes, envelope_bytes = self.sign()
        self.assertEqual(canonical_json(self.verdict), payload_bytes)
        self.assertEqual(canonical_json(envelope), envelope_bytes)
        signature = base64.b64decode(envelope["signatures"][0]["sig"])
        self.key.public_key().verify(
            signature, pae(PERMIT_PAYLOAD_TYPE, payload_bytes)
        )
        self.assertEqual(KEY_ID, envelope["signatures"][0]["keyid"])
        self.assertEqual(4, self.verdict["binding"]["evidenceAgeSeconds"])
        self.assertEqual("", self.verdict["checks"][0]["remediation"])
        call = self.transport.calls[0]
        self.assertEqual(
            "https://vault.test.example/v1/meeting-ai/sign/transcript-ready-permit",
            call[1],
        )
        self.assertNotIn(self.token.read_bytes().strip(), call[3])
        self.assertNotIn(b"private", envelope_bytes.lower())

    def test_rejected_or_stale_verdict_is_never_sent_to_vault(self) -> None:
        rejected = copy.deepcopy(self.verdict)
        rejected["status"] = "rejected"
        rejected["enableAuthorized"] = False
        self.write_verdict(rejected)
        with self.assertRaisesRegex(ContractError, "only an accepted"):
            self.sign()
        self.assertEqual([], self.transport.calls)

        self.write_verdict(self.verdict)
        with self.assertRaisesRegex(ContractError, "freshness"):
            self.sign(now=NOW + dt.timedelta(minutes=16))
        self.assertEqual([], self.transport.calls)

    def test_trust_pin_and_dedicated_key_binding_fail_closed(self) -> None:
        with self.assertRaisesRegex(ContractError, "out-of-band pin"):
            self.sign(expected_trust_root_sha256="0" * 64)
        with self.assertRaisesRegex(ContractError, "dedicated Transit key"):
            self.sign(vault_mount="cross-ai")
        with self.assertRaisesRegex(ContractError, "dedicated key version"):
            self.sign(vault_key_version=2)
        self.transport.version = 4
        with self.assertRaisesRegex(PolicyError, "VAULT_SIGN_VERSION_MISMATCH"):
            self.sign()

    def test_extra_fields_and_runtime_binding_mismatch_are_rejected(self) -> None:
        altered = copy.deepcopy(self.verdict)
        altered["unexpected"] = True
        self.write_verdict(altered)
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            self.sign()
        altered = copy.deepcopy(self.verdict)
        altered["binding"]["evidenceAgeSeconds"] = 3
        self.write_verdict(altered)
        with self.assertRaisesRegex(ContractError, "evidence age"):
            self.sign()

    def test_insecure_token_file_is_rejected_before_vault_call(self) -> None:
        self.token.chmod(0o644)
        with self.assertRaisesRegex(ContractError, "owner-only"):
            self.sign()
        self.assertEqual([], self.transport.calls)

    def test_unsafe_or_unpinned_public_receipt_is_rejected(self) -> None:
        receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
        receipt["exportable"] = True
        self.receipt.write_bytes(canonical_json(receipt))
        digest = hashlib.sha256(self.receipt.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ContractError, "safe dedicated key"):
            trust_builder.build_trust_root(
                receipt_path=self.receipt,
                expected_receipt_sha256=digest,
                allowed_app_environments=["test"],
                not_before="2026-07-20T07:58:00Z",
                not_after="2026-07-21T08:00:00Z",
                now=NOW,
            )
        receipt["exportable"] = False
        receipt["privateKey"] = "forbidden"
        self.receipt.write_bytes(canonical_json(receipt))
        digest = hashlib.sha256(self.receipt.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            trust_builder.build_trust_root(
                receipt_path=self.receipt,
                expected_receipt_sha256=digest,
                allowed_app_environments=["test"],
                not_before="2026-07-20T07:58:00Z",
                not_after="2026-07-21T08:00:00Z",
                now=NOW,
            )

    def test_public_root_and_permit_outputs_use_expected_modes(self) -> None:
        root_out = self.root / "public" / "trust.json"
        permit_out = self.root / "private" / "permit.json"
        trust_builder._write_public(root_out, self.trust_root.read_bytes())
        envelope, _payload_bytes, envelope_bytes = self.sign()
        permit_signer._atomic_write(permit_out, envelope_bytes)
        self.assertEqual(0o644, os.stat(root_out).st_mode & 0o777)
        self.assertEqual(0o600, os.stat(permit_out).st_mode & 0o777)
        self.assertEqual(envelope_bytes, permit_out.read_bytes())


if __name__ == "__main__":
    unittest.main()
