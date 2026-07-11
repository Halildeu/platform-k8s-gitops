from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts/automation/validate-test-overlay-frontend-diff.sh"
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
OLD_DIGEST = "1" * 64
NEW_DIGEST = "2" * 64


def content(sha: str, tag: str, digest: str, extra: str = "") -> str:
    return (
        "images:\n"
        "  - name: frontend\n"
        "    newName: ghcr.io/halildeu/platform-web-frontend-testai\n"
        f"    # sourceRevision: {sha}\n"
        f"    newTag: sha-{tag}\n"
        f"    digest: sha256:{digest}\n"
        f"{extra}"
    )


class FrontendDiffGuardTests(unittest.TestCase):
    def repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        target = root / "kustomize/overlays/test/kustomization.yaml"
        target.parent.mkdir(parents=True)
        target.write_text(content(OLD_SHA, "aaaaaaa", OLD_DIGEST), encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
        return root, target

    def run_guard(self, root: Path):
        return subprocess.run(
            ["bash", str(GUARD), "kustomize/overlays/test/kustomization.yaml"],
            cwd=root,
            text=True,
            capture_output=True,
        )

    def test_accepts_only_atomic_frontend_pin_rewrite(self):
        root, target = self.repo()
        target.write_text(content(NEW_SHA, "bbbbbbb", NEW_DIGEST), encoding="utf-8")
        result = self.run_guard(root)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_rejects_unrelated_replica_change(self):
        root, target = self.repo()
        target.write_text(
            content(NEW_SHA, "bbbbbbb", NEW_DIGEST, "    replicas: 2\n"),
            encoding="utf-8",
        )
        result = self.run_guard(root)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("outside sourceRevision/newTag/digest", result.stderr)


if __name__ == "__main__":
    unittest.main()
