import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
WORKFLOWS = {
    "apply": ROOT / ".github/workflows/apply-view-only-viewer-pilot-enable.yml",
    "operator": ROOT / ".github/workflows/faz22-6-view-only-viewer-operator-evidence.yml",
    "product": ROOT
    / ".github/workflows/faz22-6-view-only-viewer-product-evidence-verify.yml",
}
LOCK_PATH = "scripts/github_apps/cross_ai_deployment_policy/requirements.lock"
TERMINATION_WORKFLOW = (
    ROOT / ".github/workflows/faz22-6-view-only-viewer-termination-collector.yml"
)


def verify_dependency_lock_contract(text: str) -> None:
    required = (
        "--require-hashes",
        "--only-binary=:all:",
        f"--requirement {LOCK_PATH}",
    )
    for token in required:
        if text.count(token) != 1:
            raise ValueError(f"hash-pinned dependency contract missing: {token}")
    if "pip install --quiet jsonschema" in text or "pip install --quiet cryptography" in text:
        raise ValueError("version-only signed-authority dependency install is forbidden")


def verify_history_contract(text: str) -> None:
    if text.count("fetch-depth: 0") != 1:
        raise ValueError("signed authority checkout must retain complete git history")


def verify_runtime_advisory_contract(text: str) -> None:
    required = (
        "advisory_comment_id:",
        'ADVISORY_COMMENT_ID: ${{ inputs.advisory_comment_id }}',
        'advisory_comment_id="${ADVISORY_COMMENT_ID:-}"',
        '.status == "tracked_pending"',
        '.aiAdvisory.consensusVerdict == "PENDING"',
    )
    if any(token not in text for token in required):
        raise ValueError("runtime advisory binding contract is missing")
    if "jq -er '.aiAdvisory.commentId'" in text:
        raise ValueError("circular policy advisory binding is forbidden")


def verify_legacy_archive_contract(text: str) -> None:
    required_counts = {
        'legacy = {"SHA256SUMS", "protected-authorization.json"}': 1,
        'current = legacy | {"advisory-comment.json"}': 1,
        'if set(names) == current:': 1,
        'elif set(names) == legacy:': 1,
        '[ "$archive_mode" = v2 ]': 2,
        '[ "$archive_mode" = v1 ]': 1,
    }
    if any(text.count(token) != count for token, count in required_counts.items()):
        raise ValueError("legacy/current authorization archive contract is missing")


class SignedAuthorityWorkflowContractTest(unittest.TestCase):
    def test_current_workflows_are_content_addressed_and_operator_is_unshallow(self):
        rendered = {
            name: path.read_text(encoding="utf-8") for name, path in WORKFLOWS.items()
        }
        for name, text in rendered.items():
            with self.subTest(workflow=name):
                verify_dependency_lock_contract(text)
        for text in rendered.values():
            verify_history_contract(text)
        verify_runtime_advisory_contract(rendered["apply"])

    def test_each_dependency_lock_omission_fails_closed(self):
        for name, path in WORKFLOWS.items():
            original = path.read_text(encoding="utf-8")
            for token in (
                "--require-hashes",
                "--only-binary=:all:",
                f"--requirement {LOCK_PATH}",
            ):
                with self.subTest(workflow=name, omitted=token):
                    mutated = original.replace(token, "", 1)
                    with self.assertRaisesRegex(ValueError, "contract missing"):
                        verify_dependency_lock_contract(mutated)

    def test_fetch_depth_omission_fails_closed(self):
        for name, path in WORKFLOWS.items():
            original = path.read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                with self.assertRaisesRegex(ValueError, "complete git history"):
                    verify_history_contract(
                        original.replace("fetch-depth: 0", "", 1)
                    )

    def test_runtime_advisory_input_or_pending_policy_omission_fails_closed(self):
        original = WORKFLOWS["apply"].read_text(encoding="utf-8")
        for token in (
            "advisory_comment_id:",
            'ADVISORY_COMMENT_ID: ${{ inputs.advisory_comment_id }}',
            'advisory_comment_id="${ADVISORY_COMMENT_ID:-}"',
            '.status == "tracked_pending"',
            '.aiAdvisory.consensusVerdict == "PENDING"',
        ):
            with self.subTest(omitted=token):
                with self.assertRaisesRegex(ValueError, "contract is missing"):
                    verify_runtime_advisory_contract(original.replace(token, "", 1))
        with self.assertRaisesRegex(ValueError, "circular policy"):
            verify_runtime_advisory_contract(
                original + "\njq -er '.aiAdvisory.commentId'\n"
            )

    def test_termination_accepts_only_exact_legacy_or_current_archive_sets(self):
        original = TERMINATION_WORKFLOW.read_text(encoding="utf-8")
        verify_legacy_archive_contract(original)
        for token in (
            'legacy = {"SHA256SUMS", "protected-authorization.json"}',
            'current = legacy | {"advisory-comment.json"}',
            '[ "$archive_mode" = v2 ]',
            '[ "$archive_mode" = v1 ]',
        ):
            with self.subTest(omitted=token):
                with self.assertRaisesRegex(ValueError, "archive contract is missing"):
                    verify_legacy_archive_contract(original.replace(token, "", 1))


if __name__ == "__main__":
    unittest.main()
