"""Keep the temporary #2828 owner exception bound to the approved TEST request."""
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "kustomize/overlays/test"
PATCH = OVERLAY / "endpoint-uninstall-owner-exception.yaml"
PREFIX = "ENDPOINT_ADMIN_UNINSTALL_OWNER_EXCEPTION_"


class OwnerExceptionScopeTest(unittest.TestCase):
    def test_exact_scope_and_bounded_expiry(self):
        config, deployment = list(yaml.safe_load_all(PATCH.read_text()))
        data = config["data"]
        expected = {
            "TENANT_ID": "00000000-0000-0000-0000-000000000001",
            "DEVICE_ID": "423b6fc3-7497-4083-bd2f-5e2fe543bfe9",
            "CATALOG_ITEM_ID": "b5e44c47-b764-40fc-b00c-0d53ac2df6ce",
            "REQUEST_ID": "f8b2c5f2-f442-42b1-a09d-d9bec3432c14",
            "ACTOR_ID": "3520324b-3035-4510-8fca-a8a18dbd1da2",
            "DECISION_REF": "https://github.com/Halildeu/platform-k8s-gitops/issues/2828#issuecomment-5560173707",
        }
        for key, value in expected.items():
            self.assertEqual(data[PREFIX + key], value)
        issued = datetime.fromisoformat(data[PREFIX + "ISSUED_AT"])
        expires = datetime.fromisoformat(data[PREFIX + "EXPIRES_AT"])
        self.assertEqual(expires - issued, timedelta(hours=12))
        self.assertEqual(deployment["metadata"]["name"], "endpoint-admin-service")
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertEqual(env, [{"name": "POD_NAMESPACE", "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}}}])

    def test_only_test_overlay_activates_grant(self):
        test = yaml.safe_load((OVERLAY / "kustomization.yaml").read_text())
        self.assertIn({"path": PATCH.name}, test["patches"])
        for path in (ROOT / "kustomize/base").rglob("*.yaml"):
            self.assertNotIn(PREFIX, path.read_text())
        for path in (ROOT / "kustomize/overlays/prod").rglob("*.yaml"):
            self.assertNotIn(PREFIX, path.read_text())
            self.assertNotIn(PATCH.name, path.read_text())


if __name__ == "__main__":
    unittest.main()
