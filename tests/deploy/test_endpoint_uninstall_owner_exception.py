"""The consumed #2828 owner grant must not remain active in desired state."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "kustomize/overlays/test"
PATCH = OVERLAY / "endpoint-uninstall-owner-exception.yaml"
PREFIX = "ENDPOINT_ADMIN_UNINSTALL_OWNER_EXCEPTION_"


class OwnerExceptionScopeTest(unittest.TestCase):
    def test_consumed_grant_patch_removed(self):
        self.assertFalse(PATCH.exists())
        test = yaml.safe_load((OVERLAY / "kustomization.yaml").read_text())
        self.assertNotIn({"path": PATCH.name}, test["patches"])

    def test_no_active_owner_exception_configuration(self):
        for root in (ROOT / "kustomize/base", ROOT / "kustomize/overlays"):
            for path in root.rglob("*.yaml"):
                with self.subTest(path=path.relative_to(ROOT)):
                    content = path.read_text()
                    self.assertNotIn(PREFIX, content)
                    self.assertNotIn("endpoint-admin.acik.io/owner-exception", content)


if __name__ == "__main__":
    unittest.main()
