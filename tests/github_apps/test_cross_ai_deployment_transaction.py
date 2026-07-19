from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.dsse import verify_json_envelope
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    IntentRegistry,
)
from scripts.github_apps.cross_ai_deployment_policy.outcome import (
    OUTCOME_PAYLOAD_TYPE,
)
from scripts.github_apps.cross_ai_deployment_policy.reconciler import (
    GitHubOutcomeReconciler,
)
from scripts.github_apps.cross_ai_deployment_policy.transaction import (
    transaction_evidence_digest,
    verify_transaction_final,
    verify_transaction_preflight,
)
from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.policy import StagePolicy
from scripts.github_apps.cross_ai_deployment_policy.workflow import (
    inspect_transaction_workflow,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory, digest


WORKFLOW = b"""name: transaction-test
on:
  workflow_dispatch:
    inputs:
      confirm: {description: confirm, required: true, type: string}
      device_id: {description: device, required: true, type: string}
      device_hostname: {description: hostname, required: true, type: string}
      pilot_seconds:
        description: seconds
        required: true
        default: "300"
        type: choice
        options: ["300", "600", "900", "1200", "1800"]
      mask_rect_bps:
        description: mask
        required: true
        default: "7500,7500,2500,2500"
        type: string
      preflight_only:
        description: negative
        required: true
        default: false
        type: boolean
permissions:
  actions: read
  contents: read
  issues: read
concurrency:
  group: endpoint-admin-remote-bridge-activation
  cancel-in-progress: false
env:
  WORK: /tmp/${{ github.run_id }}-${{ github.run_attempt }}
jobs:
  preflight:
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    outputs:
      preflight_artifact_name: ${{ steps.finalize.outputs.name }}
      preflight_run_attempt: ${{ github.run_attempt }}
      preflight_sha256: ${{ steps.finalize.outputs.sha }}
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10
      - id: finalize
        run: echo faz22-view-only-transaction-preflight-${{ github.run_id }}-${{ github.run_attempt }}
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: faz22-view-only-transaction-preflight-${{ github.run_id }}-${{ github.run_attempt }}
          path: /tmp/preflight
  transaction:
    needs: preflight
    if: ${{ !inputs.preflight_only }}
    runs-on: [self-hosted, staging-sw, testai-deploy]
    timeout-minutes: 75
    environment:
      name: faz22-view-only-pilot
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10
      - uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093
        with:
          name: ${{ needs.preflight.outputs.preflight_artifact_name }}
          path: /tmp/preflight
      - run: echo ${{ needs.preflight.outputs.preflight_run_attempt }} ${{ needs.preflight.outputs.preflight_sha256 }}
"""


def archive(payload: dict) -> bytes:
    raw = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    checksum = f"{hashlib.sha256(raw).hexdigest()}  ./preflight.json\n".encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("preflight.json", raw)
        bundle.writestr("SHA256SUMS", checksum)
    return output.getvalue()


def runtime_archive() -> bytes:
    payload = {
        "schemaVersion": "faz22.6.viewOnlyRuntimeEvidence.v1",
        "bindingHandoffEnvelope": {"fixture": "binding"},
        "evaluationPreflightEnvelope": {"fixture": "evaluation"},
        "redemptionPreflightEnvelope": {"fixture": "redemption"},
        "leaseEnvelope": {"fixture": "lease"},
        "checkpointEnvelopes": [{"fixture": "terminal"}],
    }
    output = io.BytesIO()
    info = zipfile.ZipInfo("runtime-evidence.json", date_time=(2026, 7, 18, 20, 30, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(info, canonical_bytes(payload))
    return output.getvalue()


class FakeRuntimeVerifier:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def verify_chain(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            lease=SimpleNamespace(envelope_sha256=digest("runtime-lease")),
            terminal=SimpleNamespace(envelope_sha256=digest("runtime-terminal")),
        )


class StaticSigner:
    def __init__(self, factory: FixtureFactory) -> None:
        self.factory = factory
        self.key_id = factory.COORDINATOR_KEY_ID

    def sign_json_envelope(self, *, payload_type: str, payload: dict):
        return self.factory.sign(payload_type, payload, self.key_id)


class TransactionGitHub:
    def __init__(self, run: dict, jobs: tuple[dict, ...]) -> None:
        self.run = run
        self.jobs = jobs

    def workflow_run_attempt(self, *_args):
        return self.run

    def workflow_jobs(self, *_args):
        return self.jobs


class TransactionArtifacts:
    def __init__(self, artifacts: dict[str, tuple[int | None, bytes]]) -> None:
        self.artifacts = artifacts

    def fetch(self, **kwargs) -> bytes:
        artifact_id, value = self.artifacts[kwargs["artifact_name"]]
        expected_id = kwargs.get("expected_artifact_id")
        if expected_id is not None and expected_id != artifact_id:
            raise PolicyError("ARTIFACT_ID_MISMATCH", "artifact id differs")
        return value


class TransactionPreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = FixtureFactory("v3")
        self.fixture = self.factory.build()
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        self.subject = bundle["subject"]
        self.grant = bundle["grant"]
        self.run_id = 987654
        self.run_attempt = 1
        self.payload = {
            "schemaVersion": "faz22.6.viewOnlyTransactionPreflight.v1",
            "repository": self.subject["repository"],
            "workflowRef": (
                f"{self.subject['repository']}/"
                ".github/workflows/faz22-6-view-only-viewer-transaction.yml@"
                f"{self.subject['intentRef']}"
            ),
            "headSha": self.subject["headSha"],
            "runId": self.run_id,
            "runAttempt": self.run_attempt,
            "endpointIdSha256": self.subject["endpointIdSha256"],
            "deviceHostnameSha256": self.subject["deviceHostnameSha256"],
            "policySha256": self.subject["pilotOwnerPolicySha256"],
            "maskPolicySha256": self.subject["maskPolicySha256"],
            "expectedImageDigest": self.subject["runtimeImageDigest"],
            "pilotSeconds": self.subject["pilotSeconds"],
            "observedAt": "2026-07-18T20:20:00Z",
            "mutationCount": 0,
            "attendedConsentAttempted": False,
            "staleWatchdogReclaimRequired": False,
            "staleWatchdogAuthorizationSha256": None,
            "verdict": "PASS",
        }

    def verify(self, payload: dict):
        return verify_transaction_preflight(
            archive(payload),
            repository=self.subject["repository"],
            workflow_path=".github/workflows/faz22-6-view-only-viewer-transaction.yml",
            intent_ref=self.subject["intentRef"],
            head_sha=self.subject["headSha"],
            run_id=self.run_id,
            run_attempt=self.run_attempt,
            subject=self.subject,
            grant=self.grant,
            observed_at=self.fixture.now,
            max_clock_skew_seconds=60,
        )

    def test_permit_binds_bundle_and_same_run_preflight(self) -> None:
        verified = self.verify(self.payload)
        evidence = transaction_evidence_digest(
            bundle_sha256=digest("bundle"),
            preflight=verified,
        )
        self.assertRegex(verified.preflight_sha256, r"^sha256:[a-f0-9]{64}$")
        self.assertRegex(evidence, r"^sha256:[a-f0-9]{64}$")

    def test_deny_replay_attempt_and_subject_tamper(self) -> None:
        for field, value in (
            ("runAttempt", 2),
            ("headSha", "f" * 40),
            ("endpointIdSha256", digest("wrong-endpoint")),
            ("mutationCount", 1),
            ("attendedConsentAttempted", True),
        ):
            with self.subTest(field=field):
                tampered = dict(self.payload)
                tampered[field] = value
                with self.assertRaisesRegex(
                    PolicyError, "TRANSACTION_PREFLIGHT_BINDING_MISMATCH"
                ):
                    self.verify(tampered)

    def test_deny_ambiguous_stale_watchdog_observation(self) -> None:
        tampered = dict(self.payload)
        tampered["staleWatchdogReclaimRequired"] = True
        with self.assertRaisesRegex(
            PolicyError, "TRANSACTION_PREFLIGHT_STALE_WATCHDOG_INVALID"
        ):
            self.verify(tampered)

    def final_archive(self, *, failed_clean: bool = False) -> tuple[bytes, bytes]:
        rollback_stdout = b'{"cleanup":"verified"}\n'
        rollback_sha256 = f"sha256:{hashlib.sha256(rollback_stdout).hexdigest()}"
        pre_rollback_archive = b"immutable-pre-rollback-artifact"
        receipt = {
            "schemaVersion": "faz22.6.viewOnlyTransactionArtifactUploadReceipt.v1",
            "artifactId": 7654321,
            "artifactDigest": (
                f"sha256:{hashlib.sha256(pre_rollback_archive).hexdigest()}"
            ),
            "artifactUrl": (
                "https://github.com/Halildeu/platform-k8s-gitops/"
                "actions/runs/987654/artifacts/7654321"
            ),
            "packageSha256": digest("pre-rollback-package"),
            "headSha": self.subject["headSha"],
            "runId": self.run_id,
            "runAttempt": self.run_attempt,
            "observedAt": "2026-07-18T20:21:00Z",
        }
        receipt_raw = json.dumps(receipt, sort_keys=True, indent=2).encode() + b"\n"
        receipt_sha256 = f"sha256:{hashlib.sha256(receipt_raw).hexdigest()}"
        workflow_ref = (
            f"{self.subject['repository']}/"
            ".github/workflows/faz22-6-view-only-viewer-transaction.yml@"
            f"{self.subject['intentRef']}"
        )
        binding = {
            "repository": self.subject["repository"],
            "workflowRef": workflow_ref,
            "headSha": self.subject["headSha"],
            "runId": self.run_id,
            "runAttempt": self.run_attempt,
            "endpointIdSha256": self.subject["endpointIdSha256"],
            "deviceHostnameSha256": self.subject["deviceHostnameSha256"],
            "policySha256": self.subject["pilotOwnerPolicySha256"],
            "maskPolicySha256": self.subject["maskPolicySha256"],
            "pilotSeconds": self.subject["pilotSeconds"],
            "preflightSha256": self.verified_preflight.preflight_sha256,
            "authorizationSha256": digest("protected-authorization"),
            "watchdogExpiresEpoch": int(
                datetime(2026, 7, 18, 21, 25, tzinfo=timezone.utc).timestamp()
            ),
            "sessionSha256": None if failed_clean else digest("attended-session"),
        }
        states = [
            ("INIT", "transaction-initialized", self.verified_preflight.preflight_sha256),
            ("PREFLIGHT_VERIFIED", "preflight-verified", self.verified_preflight.preflight_sha256),
            ("DECISION_AUTHORIZED", "decision-authorized", binding["authorizationSha256"]),
            ("LIVE_REVALIDATED", "live-revalidated", digest("live-revalidation")),
            ("ACTIVATED", "viewer-activated", digest("activation")),
        ]
        if failed_clean:
            states.append(("FAILURE_CAPTURED", "transaction-step-failed", digest("failure")))
        else:
            states.extend(
                [
                    ("CONSENT_PENDING", "consent-pending", digest("consent-pending")),
                    ("EVIDENCE_COLLECTED", "evidence-collected", digest("evidence")),
                    ("EVIDENCE_VERIFIED", "evidence-verified", digest("evidence")),
                ]
            )
        states.extend(
            [
                ("ARTIFACTS_STAGED", "artifacts-uploaded", receipt_sha256),
                ("ROLLBACK_PENDING", "rollback-pending", digest("rollback-pending")),
                ("ROLLED_BACK", "rollback-verified", rollback_sha256),
                (
                    "FAILED_CLEAN" if failed_clean else "COMPLETED",
                    "transaction-failed-clean" if failed_clean else "transaction-completed",
                    rollback_sha256,
                ),
            ]
        )
        checkpoints = []
        previous = None
        authorization_seen = False
        evidence_seen = False
        started = datetime(2026, 7, 18, 20, 20, tzinfo=timezone.utc)
        for sequence, (state, reason, payload_sha256) in enumerate(states):
            if state == "DECISION_AUTHORIZED":
                authorization_seen = True
            if state == "EVIDENCE_COLLECTED":
                evidence_seen = True
            historical_binding = dict(binding)
            if not authorization_seen:
                historical_binding["authorizationSha256"] = None
                historical_binding["watchdogExpiresEpoch"] = None
            if not evidence_seen:
                historical_binding["sessionSha256"] = None
            checkpoint = {
                "sequence": sequence,
                "state": state,
                "observedAt": (
                    started + timedelta(seconds=sequence * 10)
                ).isoformat().replace("+00:00", "Z"),
                "reasonCode": reason,
                "payloadSha256": payload_sha256,
                "bindingSha256": sha256_digest(historical_binding),
                "previousCheckpointSha256": previous,
            }
            checkpoint["checkpointSha256"] = sha256_digest(checkpoint)
            previous = checkpoint["checkpointSha256"]
            checkpoints.append(checkpoint)
        state = {
            "schemaVersion": "faz22.6.viewOnlyTransactionState.v1",
            "binding": binding,
            "currentState": states[-1][0],
            "sequence": len(states) - 1,
            "reasonCode": states[-1][1],
            "checkpoints": checkpoints,
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("state.json", json.dumps(state, indent=2) + "\n")
            bundle.writestr("rollback.stdout", rollback_stdout)
            bundle.writestr("rollback.stderr", b"")
            bundle.writestr("pre-rollback-upload-receipt.json", receipt_raw)
        return output.getvalue(), pre_rollback_archive

    def verify_final(self, final_archive: bytes):
        return verify_transaction_final(
            final_archive,
            repository=self.subject["repository"],
            workflow_path=".github/workflows/faz22-6-view-only-viewer-transaction.yml",
            intent_ref=self.subject["intentRef"],
            head_sha=self.subject["headSha"],
            run_id=self.run_id,
            run_attempt=self.run_attempt,
            subject=self.subject,
            grant=self.grant,
            preflight_sha256=self.verified_preflight.preflight_sha256,
            observed_at=self.fixture.now,
            max_clock_skew_seconds=60,
        )

    def test_final_success_requires_hash_chained_rollback_and_upload_receipt(self) -> None:
        self.verified_preflight = self.verify(self.payload)
        final_archive, pre_rollback_archive = self.final_archive()
        verified = self.verify_final(final_archive)
        self.assertEqual(verified.target_state, "Succeeded")
        self.assertEqual(verified.conclusion, "success")
        self.assertEqual(verified.pre_rollback_artifact_id, 7654321)
        self.assertEqual(
            verified.pre_rollback_artifact_digest,
            f"sha256:{hashlib.sha256(pre_rollback_archive).hexdigest()}",
        )

    def test_final_failed_clean_is_a_verified_rollback_not_success(self) -> None:
        self.verified_preflight = self.verify(self.payload)
        final_archive, _ = self.final_archive(failed_clean=True)
        verified = self.verify_final(final_archive)
        self.assertEqual(verified.target_state, "RolledBack")
        self.assertEqual(verified.conclusion, "rolled-back")

    def test_final_denies_tampered_checkpoint_and_missing_rollback_receipt(self) -> None:
        self.verified_preflight = self.verify(self.payload)
        final_archive, _ = self.final_archive()
        with zipfile.ZipFile(io.BytesIO(final_archive)) as original:
            state = json.loads(original.read("state.json"))
            receipt = original.read("pre-rollback-upload-receipt.json")
        state["checkpoints"][3]["payloadSha256"] = digest("tampered")
        tampered = io.BytesIO()
        with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("state.json", json.dumps(state))
            bundle.writestr("rollback.stdout", b'{"cleanup":"verified"}\n')
            bundle.writestr("rollback.stderr", b"")
            bundle.writestr("pre-rollback-upload-receipt.json", receipt)
        with self.assertRaisesRegex(PolicyError, "TRANSACTION_FINAL_STATE_INVALID"):
            self.verify_final(tampered.getvalue())

        missing = io.BytesIO()
        with zipfile.ZipFile(missing, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("state.json", json.dumps(state))
            bundle.writestr("rollback.stderr", b"")
        with self.assertRaisesRegex(PolicyError, "TRANSACTION_FINAL_ARCHIVE_INVALID"):
            self.verify_final(missing.getvalue())

    def test_reconciler_signs_and_persists_exact_terminal_artifact_receipt(self) -> None:
        self.verified_preflight = self.verify(self.payload)
        final_archive, pre_rollback_archive = self.final_archive()
        verified_bundle = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
            expected_bundle_contract="v3",
        ).verify_bundle(self.fixture.bundle_envelope)
        subject = verified_bundle.payload["subject"]
        stage = verified_bundle.payload["workflowStages"][0]
        with tempfile.TemporaryDirectory() as directory:
            registry = IntentRegistry(
                Path(directory) / "registry.sqlite3",
                ContentAddressedStore(Path(directory) / "cas"),
            )
            try:
                registry.register(
                    envelope=self.fixture.bundle_envelope,
                    verified=verified_bundle,
                    registration_principal=(
                        "spiffe://acik/platform/trusted-dispatcher"
                    ),
                    registered_at=self.fixture.now,
                )
                registry.finalize_ref(
                    request_id=verified_bundle.request_id,
                    ref_object_id="a" * 40,
                    resolved_head_sha=subject["headSha"],
                    finalized_at=self.fixture.now,
                )
                registry.reserve_stage(
                    request_id=verified_bundle.request_id,
                    stage="transaction",
                    run_id=self.run_id,
                    run_attempt=self.run_attempt,
                    app_rule_id=4322193,
                    now=self.fixture.now,
                )
                run = {
                    "id": self.run_id,
                    "run_attempt": self.run_attempt,
                    "event": "workflow_dispatch",
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": subject["headSha"],
                    "head_branch": subject["intentRef"].removeprefix("refs/tags/"),
                    "path": stage["workflowPath"],
                    "run_started_at": "2026-07-18T20:20:00Z",
                    "repository": {
                        "id": subject["repositoryId"],
                        "full_name": subject["repository"],
                    },
                    "head_repository": {
                        "id": subject["repositoryId"],
                        "full_name": subject["repository"],
                    },
                }
                jobs = (
                    {
                        "name": "preflight",
                        "run_attempt": self.run_attempt,
                        "status": "completed",
                        "conclusion": "success",
                        "steps": [
                            {
                                "number": 1,
                                "name": "read-only preflight",
                                "status": "completed",
                                "conclusion": "success",
                            }
                        ],
                    },
                    {
                        "name": "transaction",
                        "run_attempt": self.run_attempt,
                        "status": "completed",
                        "conclusion": "success",
                        "steps": [
                            {
                                "number": 1,
                                "name": "protected transaction and rollback",
                                "status": "completed",
                                "conclusion": "success",
                            }
                        ],
                    },
                )
                prefix = f"{self.run_id}-{self.run_attempt}"
                artifacts = TransactionArtifacts(
                    {
                        f"faz22-view-only-transaction-preflight-{prefix}": (
                            None,
                            archive(self.payload),
                        ),
                        f"faz22-view-only-transaction-final-{prefix}": (
                            None,
                            final_archive,
                        ),
                        f"faz22-view-only-transaction-runtime-{prefix}": (
                            None,
                            runtime_archive(),
                        ),
                        f"faz22-view-only-transaction-pre-rollback-{prefix}": (
                            7654321,
                            pre_rollback_archive,
                        ),
                    }
                )
                runtime_verifier = FakeRuntimeVerifier()
                reconciler = GitHubOutcomeReconciler(
                    installation_id=147158710,
                    registry=registry,
                    github=TransactionGitHub(run, jobs),
                    artifact_source=artifacts,
                    trust_root=self.fixture.trust_root,
                    expected_trust_root_sha256=sha256_digest(
                        self.fixture.trust_root
                    ),
                    revocations_loader=lambda: self.fixture.revocations_envelope,
                    bundle_contract_version="v3",
                    outcome_signer=StaticSigner(self.factory),
                    runtime_verifier_loader=lambda *_args: runtime_verifier,
                    now=lambda: self.fixture.now,
                )
                outcome = reconciler.reconcile(
                    request_id=verified_bundle.request_id,
                    stage="transaction",
                )
                self.assertEqual(outcome.target_state, "Succeeded")
                self.assertIsNotNone(outcome.receipt_digest)
                self.assertEqual(len(runtime_verifier.calls), 1)
                self.assertEqual(
                    outcome.payload["runtimeTerminalReceiptSha256"],
                    digest("runtime-terminal"),
                )
                receipt_digest, receipt_envelope = (
                    registry.get_stage_outcome_receipt(
                        verified_bundle.request_id, "transaction"
                    )
                )
                self.assertEqual(receipt_digest, outcome.receipt_digest)
                receipt = verify_json_envelope(
                    receipt_envelope,
                    expected_payload_type=OUTCOME_PAYLOAD_TYPE,
                    allowed_keys={
                        self.factory.COORDINATOR_KEY_ID: base64.b64decode(
                            next(
                                item["publicKeyBase64"]
                                for item in self.fixture.trust_root["keys"]
                                if item["keyId"]
                                == self.factory.COORDINATOR_KEY_ID
                            ),
                            validate=True,
                        )
                    },
                    required_key_ids={self.factory.COORDINATOR_KEY_ID},
                )
                self.assertEqual(
                    receipt.payload["sourceArchiveSha256"],
                    outcome.payload["sourceArchiveSha256"],
                )
            finally:
                registry.close()


class TransactionWorkflowTest(unittest.TestCase):
    def policy(self) -> StagePolicy:
        return StagePolicy(
            stage="transaction",
            workflow_path=".github/workflows/faz22-6-view-only-viewer-transaction.yml",
            required_preflight_runs_on_labels=("ubuntu-24.04",),
            required_runs_on_labels=(
                "self-hosted",
                "staging-sw",
                "testai-deploy",
            ),
            require_runner_group=False,
            requires_same_run_preflight=True,
            requires_one_protected_environment_gate=True,
        )

    def test_accepts_one_unprotected_preflight_and_one_protected_transaction(self) -> None:
        result = inspect_transaction_workflow(
            WORKFLOW,
            stage_policy=self.policy(),
            environment="faz22-view-only-pilot",
        )
        self.assertEqual(result.preflight_job, "preflight")
        self.assertEqual(result.governed_job, "transaction")
        self.assertRegex(result.workflow_sha256, r"^sha256:[a-f0-9]{64}$")

    def test_rejects_secret_or_environment_in_preflight(self) -> None:
        for tampered in (
            WORKFLOW.replace(
                b"    runs-on: [self-hosted, staging-sw, testai-deploy]\n",
                b"    environment: faz22-view-only-pilot\n    runs-on: [self-hosted, staging-sw, testai-deploy]\n",
                1,
            ),
            WORKFLOW.replace(
                b"      - id: finalize\n",
                b"      - env: {TOKEN: ${{ secrets.NOT_ALLOWED }}}\n        run: echo denied\n      - id: finalize\n",
            ),
        ):
            with self.subTest():
                with self.assertRaises(PolicyError):
                    inspect_transaction_workflow(
                        tampered,
                        stage_policy=self.policy(),
                        environment="faz22-view-only-pilot",
                    )


if __name__ == "__main__":
    unittest.main()
