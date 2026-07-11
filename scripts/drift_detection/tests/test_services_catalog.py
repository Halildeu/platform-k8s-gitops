"""Unit tests for lib.services_catalog — loads the real services.yaml."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.services_catalog import (  # noqa: E402
    CatalogValidationError,
    ServicesCatalog,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES_YAML = REPO_ROOT / "docs" / "operations" / "services.yaml"


class TestRealServicesCatalog(unittest.TestCase):
    """Smoke against the actual catalog — ensures all entries are valid."""

    @classmethod
    def setUpClass(cls):
        cls.catalog = ServicesCatalog.from_yaml(SERVICES_YAML)

    def test_loads_without_error(self):
        self.assertGreater(len(self.catalog), 0)

    def test_all_have_workload_kind_and_probe_contract(self):
        for svc in self.catalog:
            self.assertIsNotNone(svc.workload_kind, f"{svc.name}: workload_kind None")
            self.assertIsNotNone(svc.probe_contract, f"{svc.name}: probe_contract None")
            self.assertIsNotNone(svc.runtime_class, f"{svc.name}: runtime_class None")

    def test_spring_backends_enabled_in_test(self):
        enabled = {s.name for s in self.catalog.enabled_in("test")}
        # Sanity: key backend services exist
        self.assertIn("api-gateway", enabled)
        self.assertIn("auth-service", enabled)
        self.assertIn("user-service", enabled)
        self.assertIn("endpoint-admin-service", enabled)

    def test_endpoint_admin_enabled_in_prod(self):
        # Prod activation became canonical on 2026-06-06 (gitops #1241 ESO +
        # #1242 workload/config MERGED; activation-time Up + Functional +
        # Zanzibar-ready acceptance).
        # This guard asserts only the catalog's prod CLASSIFICATION — that it
        # stays `enabled` and cannot silently regress to `deferred`. It does NOT
        # claim current runtime health (live Deployment / ArgoCD sync / a fresh
        # D29 pass live on the prod cluster). Was test_endpoint_admin_deferred_in_prod.
        svc = self.catalog.get("endpoint-admin-service")
        self.assertIsNotNone(svc)
        self.assertTrue(svc.is_enabled_in("prod"))
        self.assertFalse(svc.is_deferred_in("prod"))

    def test_jvm_warmup_extra_set_for_known_services(self):
        auth = self.catalog.get("auth-service")
        endpoint_admin = self.catalog.get("endpoint-admin-service")
        api_gateway = self.catalog.get("api-gateway")
        self.assertTrue(auth.jvm_warmup_extra)
        self.assertTrue(endpoint_admin.jvm_warmup_extra)
        self.assertFalse(api_gateway.jvm_warmup_extra)


class TestCatalogValidation(unittest.TestCase):
    def test_invalid_workload_kind_raises(self):
        data = {
            "services": [
                {
                    "name": "broken",
                    "workload_kind": "FrobnicatorSet",  # invalid
                    "runtime_class": "spring-backend",
                    "probe_contract": "spring-actuator",
                    "environments": {"test": "enabled"},
                }
            ]
        }
        with self.assertRaises(CatalogValidationError):
            ServicesCatalog.from_dict(data)

    def test_invalid_probe_contract_raises(self):
        data = {
            "services": [
                {
                    "name": "broken",
                    "workload_kind": "Deployment",
                    "runtime_class": "spring-backend",
                    "probe_contract": "made-up-contract",
                    "environments": {"test": "enabled"},
                }
            ]
        }
        with self.assertRaises(CatalogValidationError):
            ServicesCatalog.from_dict(data)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
