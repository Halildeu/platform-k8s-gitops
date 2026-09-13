#!/usr/bin/env python3
"""Keep the TEST ATS deployment and acceptance/recovery evidence pins aligned."""
import pathlib
import subprocess
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


def document(path):
    return yaml.safe_load((ROOT / path).read_text())


class AtsPolicyPromotion(unittest.TestCase):
    def test_acceptance_and_recovery_pin_the_deployed_artifact(self):
        overlay = document("kustomize/overlays/test/activation/ats-interview-evidence/kustomization.yaml")
        pin = next(x["digest"] for x in overlay["images"] if x["name"] == "ghcr.io/halildeu/ats-app-boot")
        self.assertRegex(pin, r"^sha256:[0-9a-f]{64}$")
        acceptance = document(".github/workflows/faz25-fullats-live-browser-acceptance.yml")
        recovery = document(".github/workflows/faz25-fullats-test-recovery.yml")
        self.assertEqual(pin, acceptance["jobs"]["live-browser"]["env"]["EXPECTED_ATS_DIGEST"])
        self.assertEqual(pin, recovery["env"]["EXPECTED_ATS_DIGEST"])
        rendered = list(yaml.safe_load_all(subprocess.check_output(
            ["kustomize", "build", "kustomize/overlays/test"], cwd=ROOT, text=True)))
        deployment = next(x for x in rendered if x and x.get("kind") == "Deployment"
                          and x["metadata"]["name"] == "ats-interview-evidence")
        self.assertIn("ghcr.io/halildeu/ats-app-boot@" + pin,
                      [x["image"] for x in deployment["spec"]["template"]["spec"]["containers"]])


if __name__ == "__main__":
    unittest.main()
