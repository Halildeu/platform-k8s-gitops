from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / "docs/faz-24-evidence/2026-07-18-finalization-source-ci.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE = load_module(
    "faz24_finalization_source_evidence",
    ROOT / "scripts/test/verify-faz24-finalization-source-evidence.py",
)
REMOTE = load_module(
    "faz24_finalization_remote_evidence",
    ROOT / "scripts/test/verify-faz24-finalization-remote-evidence.py",
)


def load_evidence() -> dict:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def provider_history(
    receipts: list[dict] | None = None, *, verified: bool = False
) -> dict:
    return {
        "status": "verified" if verified else "tracked-pending",
        "acceptanceEffect": "excluded-from-source-and-runtime-claims",
        "attestationBoundary": "operator-captured-provider-unsigned",
        "requiredReceiptSchema": "cross-ai-provider-evidence/v1",
        "requiredProviderOrder": ["anthropic", "minimax", "openai"],
        "receipts": [] if receipts is None else receipts,
    }


def receipt_ledger(index: int, provider: str, model: str) -> dict:
    return {
        "provider": provider,
        "requestedModel": model,
        "actualModel": model,
        "baseTipSha": REMOTE.REVIEW_BASE_COMMIT,
        "baseSha": REMOTE.REVIEW_BASE_COMMIT,
        "headSha": REMOTE.REVIEWED_SOURCE_COMMIT,
        "scopeSha256": REMOTE.REVIEW_SCOPE_SHA256,
        "verdict": "AGREE",
        "responseSha256": f"{index + 1:064x}",
        "apiUrl": f"{REMOTE.API_ROOT}/issues/comments/{1000 + index}",
        "bodySha256": f"{index + 11:064x}",
        "createdAt": f"2026-07-18T06:00:0{index}Z",
    }


def three_ledgers() -> list[dict]:
    return [
        receipt_ledger(index, provider, model)
        for index, (provider, model) in enumerate(REMOTE.PROVIDER_ORDER, start=1)
    ]


def remote_receipts(response_override: dict[str, str] | None = None):
    ledgers: list[dict] = []
    comments: dict[str, dict] = {}
    overrides = response_override or {}
    for index, (provider, model) in enumerate(REMOTE.PROVIDER_ORDER, start=1):
        response = overrides.get(
            provider,
            "P0\nNone\n\nP1\nNone\n\nP2\nNone\n\nVERDICT: AGREE",
        )
        response_sha256 = hashlib.sha256(response.encode("utf-8")).hexdigest()
        body_value = {
            "schema": "cross-ai-provider-evidence/v1",
            "provider": provider,
            "requested_model": model,
            "actual_model": model,
            "base_tip_sha": REMOTE.REVIEW_BASE_COMMIT,
            "base_sha": REMOTE.REVIEW_BASE_COMMIT,
            "head_sha": REMOTE.REVIEWED_SOURCE_COMMIT,
            "scope_sha256": REMOTE.REVIEW_SCOPE_SHA256,
            "verdict": "AGREE",
            "response_sha256": response_sha256,
            "response": response,
        }
        body = json.dumps(body_value, ensure_ascii=False, separators=(",", ":"))
        api_url = f"{REMOTE.API_ROOT}/issues/comments/{2000 + index}"
        created_at = f"2026-07-18T07:00:0{index}Z"
        ledger = {
            "provider": provider,
            "requestedModel": model,
            "actualModel": model,
            "baseTipSha": REMOTE.REVIEW_BASE_COMMIT,
            "baseSha": REMOTE.REVIEW_BASE_COMMIT,
            "headSha": REMOTE.REVIEWED_SOURCE_COMMIT,
            "scopeSha256": REMOTE.REVIEW_SCOPE_SHA256,
            "verdict": "AGREE",
            "responseSha256": response_sha256,
            "apiUrl": api_url,
            "bodySha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "createdAt": created_at,
        }
        ledgers.append(ledger)
        comments[api_url] = {
            "url": api_url,
            "body": body,
            "user": {"login": "Halildeu"},
            "author_association": "OWNER",
            "created_at": created_at,
            "updated_at": created_at,
        }
    return ledgers, comments


class SourceEvidenceVerifierTests(unittest.TestCase):
    def run_source(self, evidence: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            with mock.patch.object(sys, "argv", ["verifier", str(path)]):
                SOURCE.main()

    def test_current_pending_provider_state_passes_without_consensus(self) -> None:
        self.run_source(load_evidence())

    def test_self_attested_test_count_is_rejected(self) -> None:
        evidence = load_evidence()
        evidence["invariants"][0]["tests"][0]["assertions"] = 12
        with self.assertRaisesRegex(SystemExit, "counts/assertions"):
            self.run_source(evidence)

    def test_root_level_self_attested_test_count_is_rejected(self) -> None:
        evidence = load_evidence()
        evidence["testCounts"] = {"passed": 99}
        with self.assertRaisesRegex(SystemExit, "unknown/self-attested"):
            self.run_source(evidence)

    def test_test_cannot_move_between_invariants(self) -> None:
        evidence = load_evidence()
        moved = evidence["invariants"][0]["tests"].pop()
        evidence["invariants"][1]["tests"].append(moved)
        with self.assertRaisesRegex(SystemExit, "invariant-to-test"):
            self.run_source(evidence)

    def test_owner_summary_review_history_is_rejected(self) -> None:
        evidence = load_evidence()
        evidence["reviewHistory"] = {"attestationLevel": "owner-summary"}
        with self.assertRaisesRegex(SystemExit, "unknown/self-attested"):
            self.run_source(evidence)

    def test_partial_provider_receipt_set_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "exactly three"):
            SOURCE.require_provider_evidence(
                provider_history(three_ledgers()[:2]), True
            )

    def test_three_distinct_strictly_ordered_receipts_are_accepted(self) -> None:
        SOURCE.require_provider_evidence(
            provider_history(three_ledgers(), verified=True), True
        )

    def test_duplicate_provider_refs_are_rejected(self) -> None:
        receipts = three_ledgers()
        receipts[1]["apiUrl"] = receipts[0]["apiUrl"]
        with self.assertRaisesRegex(SystemExit, "refs must be unique"):
            SOURCE.require_provider_evidence(
                provider_history(receipts, verified=True), True
            )

    def test_wrong_provider_order_is_rejected(self) -> None:
        receipts = three_ledgers()
        receipts[0], receipts[1] = receipts[1], receipts[0]
        with self.assertRaisesRegex(SystemExit, "model/scope/verdict"):
            SOURCE.require_provider_evidence(
                provider_history(receipts, verified=True), True
            )

    def test_requested_and_actual_models_must_both_be_exact(self) -> None:
        receipts = three_ledgers()
        receipts[1]["actualModel"] = "minimax/MiniMax-M2"
        with self.assertRaisesRegex(SystemExit, "model/scope/verdict"):
            SOURCE.require_provider_evidence(
                provider_history(receipts, verified=True), True
            )


class RemoteEvidenceVerifierTests(unittest.TestCase):
    def test_run_event_attempt_is_bound_to_hardcoded_contract(self) -> None:
        expected = REMOTE.EXPECTED_RUNS["testRun"]
        pinned = REMOTE.expected_evidence_run(expected)
        pinned["jobs"] = copy.deepcopy(expected["jobs"])
        pinned["event"] = "workflow_dispatch"
        with self.assertRaisesRegex(SystemExit, "immutable expected run"):
            REMOTE.require_run("testRun", pinned)

    def test_exact_job_name_is_bound_to_hardcoded_contract(self) -> None:
        jobs = copy.deepcopy(REMOTE.EXPECTED_RUNS["authContractRun"]["jobs"])
        jobs[0]["name"] = "self-attested passing job"
        with self.assertRaisesRegex(SystemExit, "job id/name/step"):
            REMOTE.require_jobs("authContractRun", jobs)

    def test_unbound_test_assertion_field_is_rejected_remotely(self) -> None:
        evidence = load_evidence()
        evidence["invariants"][0]["tests"][0]["testCount"] = 99
        with self.assertRaisesRegex(SystemExit, "counts/assertions"):
            REMOTE.invariant_records(evidence)

    def test_backend_path_blob_sha_is_bound_to_hardcoded_contract(self) -> None:
        evidence = load_evidence()
        evidence["implementationContracts"][0]["blobSha"] = "0" * 40
        with self.assertRaisesRegex(SystemExit, "implementation path/blob"):
            REMOTE.require_source_blobs(evidence, {})

    def test_workflow_path_blob_sha_is_bound_to_hardcoded_contract(self) -> None:
        evidence = load_evidence()
        tree = {path: blob_sha for path, blob_sha in REMOTE.EXPECTED_IMPLEMENTATIONS}
        for expected in REMOTE.EXPECTED_RUNS.values():
            tree[expected["path"]] = expected["workflowBlobSha"]
        for tests in REMOTE.EXPECTED_INVARIANTS.values():
            for path, blob_sha, _method in tests:
                tree[path] = blob_sha
        tree[REMOTE.EXPECTED_RUNS["testRun"]["path"]] = "0" * 40
        with self.assertRaisesRegex(SystemExit, "backend path"):
            REMOTE.require_source_blobs(evidence, tree)

    def test_image_digest_requires_matching_job_log(self) -> None:
        backend = load_evidence()["backend"]

        def fake_json(url: str) -> dict:
            artifact_id = int(url.rsplit("/", 1)[-1])
            expected = next(
                item
                for item in REMOTE.EXPECTED_IMAGES.values()
                if item["artifactId"] == artifact_id
            )
            return {
                "id": artifact_id,
                "name": expected["artifactName"],
                "expired": False,
                "workflow_run": {
                    "id": REMOTE.EXPECTED_RUNS["buildRun"]["id"],
                    "head_sha": REMOTE.ARTIFACT_COMMIT,
                },
            }

        with (
            mock.patch.object(REMOTE, "github_json", side_effect=fake_json),
            mock.patch.object(REMOTE, "github_text", return_value="unrelated log"),
            self.assertRaisesRegex(SystemExit, "digest is not bound"),
        ):
            REMOTE.require_image_provenance(backend)

    def test_structured_remote_receipts_pass(self) -> None:
        ledgers, comments = remote_receipts()
        with mock.patch.object(REMOTE, "github_json", side_effect=comments.__getitem__):
            REMOTE.require_provider_evidence(
                provider_history(ledgers, verified=True), True
            )

    def test_response_digest_mismatch_is_rejected(self) -> None:
        ledgers, comments = remote_receipts()
        ledgers[1]["responseSha256"] = "0" * 64
        with (
            mock.patch.object(REMOTE, "github_json", side_effect=comments.__getitem__),
            self.assertRaisesRegex(
                SystemExit, "model/scope/verdict|full response digest"
            ),
        ):
            REMOTE.require_provider_evidence(
                provider_history(ledgers, verified=True), True
            )

    def test_subagent_response_is_rejected(self) -> None:
        ledgers, comments = remote_receipts(
            {
                "openai": (
                    "P0\nNone\n\nP1\nNone\n\nP2\n"
                    "OpenAI Codex subagent result.\n\nVERDICT: AGREE"
                )
            }
        )
        with (
            mock.patch.object(REMOTE, "github_json", side_effect=comments.__getitem__),
            self.assertRaisesRegex(SystemExit, "subagent/self-attestation"),
        ):
            REMOTE.require_provider_evidence(
                provider_history(ledgers, verified=True), True
            )

    def test_equal_provider_timestamps_are_rejected(self) -> None:
        ledgers, comments = remote_receipts()
        second_old = ledgers[1]["createdAt"]
        second_new = ledgers[0]["createdAt"]
        ledgers[1]["createdAt"] = second_new
        comments[ledgers[1]["apiUrl"]]["created_at"] = second_new
        comments[ledgers[1]["apiUrl"]]["updated_at"] = second_new
        self.assertNotEqual(second_old, second_new)
        with (
            mock.patch.object(REMOTE, "github_json", side_effect=comments.__getitem__),
            self.assertRaisesRegex(SystemExit, "strict Claude < MiniMax < Codex"),
        ):
            REMOTE.require_provider_evidence(
                provider_history(ledgers, verified=True), True
            )


if __name__ == "__main__":
    unittest.main()
