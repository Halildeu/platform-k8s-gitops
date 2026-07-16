#!/usr/bin/env python3

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/verify-faz25-p5-canonical-main-equivalence.sh"


class Faz25P5CanonicalMainEquivalenceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        self.run_cmd("git", "init", "-q")
        self.run_cmd("git", "config", "user.name", "Contract Test")
        self.run_cmd("git", "config", "user.email", "contract@example.invalid")
        target = self.repo / "scripts/ci/verify-faz25-p5-canonical-main-equivalence.sh"
        target.parent.mkdir(parents=True)
        shutil.copy2(SCRIPT, target)
        seeded_authority = {
            "tests/smoke/faz25-p5-product-surface.spec.ts": "baseline spec\n",
            "tests/smoke/faz25-p5-runtime/package-lock.json": "{}\n",
            "kustomize/overlays/test/kustomization.yaml": "resources: []\n",
            "argocd/applications/root.yaml": "kind: Application\n",
            "argocd/applications/platform-test.yaml": "kind: Application\n",
        }
        for relative_path, content in seeded_authority.items():
            path = self.repo / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.commit_all("baseline")
        self.baseline = self.rev_parse("HEAD")

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_cmd(self, *args, check=True):
        return subprocess.run(
            args,
            cwd=self.repo,
            check=check,
            capture_output=True,
            text=True,
        )

    def commit_all(self, message):
        self.run_cmd("git", "add", ".")
        self.run_cmd("git", "commit", "-q", "-m", message)

    def rev_parse(self, ref):
        return self.run_cmd("git", "rev-parse", ref).stdout.strip()

    def verify(self, baseline, candidate, check=True):
        return self.run_cmd(
            "bash",
            str(SCRIPT),
            baseline,
            candidate,
            check=check,
        )

    def test_exact_head_passes(self):
        result = json.loads(self.verify(self.baseline, self.baseline).stdout)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["mode"], "EXACT_HEAD")
        self.assertEqual(result["baselineRevision"], self.baseline)
        self.assertEqual(result["candidateRevision"], self.baseline)
        self.assertEqual(
            result["baselineAuthorityTreeSha256"],
            result["candidateAuthorityTreeSha256"],
        )
        self.assertEqual(
            result["authorityTreeSha256"],
            result["candidateAuthorityTreeSha256"],
        )

    def test_unrelated_descendant_passes(self):
        path = self.repo / "scripts/faz24/unrelated.py"
        path.parent.mkdir(parents=True)
        path.write_text("print('unrelated')\n")
        self.commit_all("unrelated descendant")
        candidate = self.rev_parse("HEAD")

        result = json.loads(self.verify(self.baseline, candidate).stdout)
        self.assertEqual(result["mode"], "AUTHORITY_EQUIVALENT_DESCENDANT")
        self.assertRegex(result["authorityPathSetSha256"], r"^[a-f0-9]{64}$")
        self.assertRegex(result["authorityTreeSha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(
            result["baselineAuthorityTreeSha256"],
            result["candidateAuthorityTreeSha256"],
        )

    def test_acceptance_authority_drift_fails(self):
        path = self.repo / "tests/smoke/faz25-p5-product-surface.spec.ts"
        path.write_text("test('changed authority')\n")
        self.commit_all("authority drift")

        result = self.verify(self.baseline, "HEAD", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("acceptance authority drift detected", result.stderr)
        self.assertIn(str(path.relative_to(self.repo)), result.stderr)

    def test_platform_test_desired_state_drift_fails(self):
        path = self.repo / "kustomize/overlays/test/kustomization.yaml"
        path.write_text("resources: [changed.yaml]\n")
        self.commit_all("desired state drift")

        result = self.verify(self.baseline, "HEAD", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("acceptance authority drift detected", result.stderr)
        self.assertIn(str(path.relative_to(self.repo)), result.stderr)

    def test_argocd_platform_test_drift_fails(self):
        path = self.repo / "argocd/applications/platform-test.yaml"
        path.write_text("kind: Application\nmetadata:\n  name: changed\n")
        self.commit_all("platform test Argo drift")

        result = self.verify(self.baseline, "HEAD", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("acceptance authority drift detected", result.stderr)
        self.assertIn(str(path.relative_to(self.repo)), result.stderr)

    def test_argocd_root_drift_fails(self):
        path = self.repo / "argocd/applications/root.yaml"
        path.write_text("kind: Application\nspec:\n  project: changed\n")
        self.commit_all("Argo app of apps drift")

        result = self.verify(self.baseline, "HEAD", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("acceptance authority drift detected", result.stderr)
        self.assertIn(str(path.relative_to(self.repo)), result.stderr)

    def test_runtime_dependency_drift_fails(self):
        path = self.repo / "tests/smoke/faz25-p5-runtime/package-lock.json"
        path.write_text('{"changed": true}\n')
        self.commit_all("runtime dependency drift")

        result = self.verify(self.baseline, "HEAD", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("acceptance authority drift detected", result.stderr)
        self.assertIn(str(path.relative_to(self.repo)), result.stderr)

    def test_non_descendant_fails(self):
        self.run_cmd("git", "checkout", "-q", "--orphan", "other")
        self.run_cmd("git", "rm", "-q", "-rf", ".")
        (self.repo / "unrelated.txt").write_text("other root\n")
        self.commit_all("unrelated root")

        result = self.verify(self.baseline, "HEAD", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a descendant", result.stderr)


if __name__ == "__main__":
    unittest.main()
