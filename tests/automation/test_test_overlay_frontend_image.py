from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "automation" / "test-overlay-frontend-image.py"
SPEC = importlib.util.spec_from_file_location(
    "test_overlay_frontend_image", MODULE_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


SHA = "29ebe18c8197fee7621cc3130c11d893ab9ecd3b"
SHORT = "29ebe18"
IMAGE = "ghcr.io/halildeu/platform-web-frontend-testai"
TAG = "sha-29ebe18"
DIGEST = "sha256:4ff08fd67234e11f655487d8524351abdc739713dcc6e15fd7472dcefd6a201b"


def fixture(
    *,
    tag: str | None = "sha-a8254d7",
    source_sha: str | None = "a8254d7aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    duplicate_digest: bool = False,
    max_surge: int = 1,
    max_unavailable: int = 0,
    progress_deadline: int | None = 300,
) -> str:
    tag_line = f"    newTag: {tag}\n" if tag else ""
    source_line = f"    # sourceRevision: {source_sha}\n" if source_sha else ""
    duplicate = "    digest: sha256:" + "1" * 64 + "\n" if duplicate_digest else ""
    deadline_patch = (
        "      - op: add\n"
        "        path: /spec/progressDeadlineSeconds\n"
        f"        value: {progress_deadline}\n"
        if progress_deadline is not None
        else ""
    )
    return (
        "images:\n"
        "  - name: frontend\n"
        f"    newName: {IMAGE}\n"
        "    # provenance must survive byte-for-byte\n"
        f"{source_line}"
        f"{tag_line}"
        "    digest: sha256:044153775992f6af6231b419a63f54959b8d65c35c8b99b3a216411cf7885a4f\n"
        f"{duplicate}"
        "  - name: auth-service\n"
        "    newName: ghcr.io/halildeu/platform-backend-auth-service\n"
        "    digest: sha256:" + "2" * 64 + "\n"
        "patches:\n"
        "  - target:\n"
        "      kind: Deployment\n"
        "      name: frontend\n"
        "    patch: |-\n"
        "      - op: replace\n"
        "        path: /spec/replicas\n"
        "        value: 1\n"
        "      - op: replace\n"
        "        path: /spec/strategy/rollingUpdate/maxSurge\n"
        f"        value: {max_surge}\n"
        "      - op: replace\n"
        "        path: /spec/strategy/rollingUpdate/maxUnavailable\n"
        f"        value: {max_unavailable}\n"
        f"{deadline_patch}"
    )


class FrontendImagePinTests(unittest.TestCase):
    def apply(self, text: str, **overrides: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "kustomization.yaml"
        path.write_text(text, encoding="utf-8")
        kwargs = {
            "sha": SHA,
            "short_sha": SHORT,
            "image": IMAGE,
            "tag": TAG,
            "digest": DIGEST,
        }
        kwargs.update(overrides)
        changes = MODULE.apply_pin(path, **kwargs)
        return path, changes

    def test_updates_tag_and_digest_without_touching_comments(self):
        path, changes = self.apply(fixture())
        updated = path.read_text(encoding="utf-8")
        self.assertEqual(3, len(changes))
        self.assertIn("# provenance must survive byte-for-byte", updated)
        self.assertIn(f"newTag: {TAG}", updated)
        self.assertIn(f"# sourceRevision: {SHA}", updated)
        self.assertIn(f"digest: {DIGEST}", updated)
        self.assertIn("platform-backend-auth-service", updated)

    def test_inserts_missing_tag_immediately_before_digest(self):
        path, _ = self.apply(fixture(tag=None, source_sha=None))
        updated = path.read_text(encoding="utf-8")
        self.assertIn(
            f"    # sourceRevision: {SHA}\n    newTag: {TAG}\n    digest: {DIGEST}",
            updated,
        )

    def test_check_reports_changes_without_writing(self):
        original = fixture()
        path, changes = self.apply(original)
        path.write_text(original, encoding="utf-8")
        changes = MODULE.apply_pin(
            path,
            sha=SHA,
            short_sha=SHORT,
            image=IMAGE,
            tag=TAG,
            digest=DIGEST,
            check=True,
        )
        self.assertEqual(3, len(changes))
        self.assertEqual(original, path.read_text(encoding="utf-8"))

    def test_rejects_sha_tag_mismatch_without_writing(self):
        original = fixture()
        with self.assertRaises(MODULE.ContractError):
            self.apply(original, tag="sha-fffffff")

    def test_rejects_noncanonical_image(self):
        with self.assertRaises(MODULE.ContractError):
            self.apply(fixture(), image="ghcr.io/example/frontend")

    def test_rejects_duplicate_digest_fields(self):
        with self.assertRaises(MODULE.ContractError):
            self.apply(fixture(duplicate_digest=True))

    def test_inspect_requires_exactly_one_frontend_entry(self):
        with self.assertRaises(MODULE.ContractError):
            MODULE.inspect_lines((fixture() + fixture()).splitlines(keepends=True))

    def test_inspect_includes_rollout_contract_fingerprint(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "kustomization.yaml"
        path.write_text(fixture(), encoding="utf-8")
        inspected = MODULE.inspect_contract_file(path)
        self.assertEqual(
            {
                "replicas": "1",
                "max_surge": "1",
                "max_unavailable": "0",
                "progress_deadline_seconds": "300",
            },
            inspected["rollout"],
        )

    def test_rollout_fingerprint_detects_legacy_strategy(self):
        current = MODULE.inspect_rollout_contract(fixture())
        legacy = MODULE.inspect_rollout_contract(
            fixture(max_surge=0, max_unavailable=1, progress_deadline=None)
        )
        self.assertNotEqual(current, legacy)


if __name__ == "__main__":
    unittest.main()
