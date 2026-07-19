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


def verify_operator_history_contract(text: str) -> None:
    if text.count("fetch-depth: 0") != 1:
        raise ValueError("operator evidence checkout must retain complete git history")


class SignedAuthorityWorkflowContractTest(unittest.TestCase):
    def test_current_workflows_are_content_addressed_and_operator_is_unshallow(self):
        rendered = {
            name: path.read_text(encoding="utf-8") for name, path in WORKFLOWS.items()
        }
        for name, text in rendered.items():
            with self.subTest(workflow=name):
                verify_dependency_lock_contract(text)
        verify_operator_history_contract(rendered["operator"])

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

    def test_operator_fetch_depth_omission_fails_closed(self):
        original = WORKFLOWS["operator"].read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "complete git history"):
            verify_operator_history_contract(original.replace("fetch-depth: 0", "", 1))


if __name__ == "__main__":
    unittest.main()
