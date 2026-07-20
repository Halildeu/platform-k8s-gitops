"""Regression tests for catalog-driven image and JWT runtime contracts."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.catalog_runtime_contracts import (  # noqa: E402
    compare_image_digests,
    desired_image_digests,
    jwt_config_findings,
)
from lib.services_catalog import ServicesCatalog  # noqa: E402


def catalog() -> ServicesCatalog:
    return ServicesCatalog.from_dict(
        {
            "services": [
                {
                    "name": "ethics-service",
                    "workload_kind": "Deployment",
                    "runtime_class": "spring-backend",
                    "probe_contract": "spring-actuator",
                    "jwt_validates": True,
                    "environments": {"test": "enabled", "prod": "deferred"},
                },
                {
                    "name": "etik-speak-public",
                    "workload_kind": "Deployment",
                    "runtime_class": "nginx",
                    "probe_contract": "http-healthz",
                    "jwt_validates": False,
                    "environments": {"test": "enabled", "prod": "deferred"},
                },
                {
                    "name": "etik-speak-manager",
                    "workload_kind": "Deployment",
                    "runtime_class": "nginx",
                    "probe_contract": "http-healthz",
                    "jwt_validates": False,
                    "environments": {"test": "enabled", "prod": "deferred"},
                },
            ]
        }
    )


def deployment(name: str, digest: str) -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "labels": {"app.kubernetes.io/name": name}},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {"name": name, "image": f"ghcr.io/halildeu/{name}@{digest}"}
                    ]
                }
            }
        },
    }


class CatalogRuntimeContractsTest(unittest.TestCase):
    def test_isolated_web_workloads_are_in_image_parity_scope(self):
        documents = [
            deployment("ethics-service", "sha256:" + "a" * 64),
            deployment("etik-speak-public", "sha256:" + "b" * 64),
            deployment("etik-speak-manager", "sha256:" + "c" * 64),
        ]
        digests = desired_image_digests(documents, catalog(), "test")
        self.assertEqual(
            set(digests),
            {"ethics-service", "etik-speak-public", "etik-speak-manager"},
        )

    def test_manager_and_public_digest_mismatches_are_p1_findings(self):
        desired = {
            "etik-speak-public": "sha256:" + "b" * 64,
            "etik-speak-manager": "sha256:" + "c" * 64,
        }
        live = {
            "etik-speak-public": "sha256:" + "d" * 64,
            "etik-speak-manager": "sha256:" + "e" * 64,
        }
        findings = compare_image_digests(desired, live)
        self.assertEqual([finding.code for finding in findings], ["digest_drift"] * 2)
        self.assertTrue(any("etik-speak-public" in finding.message for finding in findings))
        self.assertTrue(any("etik-speak-manager" in finding.message for finding in findings))

    def test_ethics_service_accepts_security_jwt_pair(self):
        documents = [
            {
                "kind": "ConfigMap",
                "metadata": {"name": "ethics-service-config"},
                "data": {
                    "SECURITY_JWT_ISSUER": "https://testai.acik.com/realms/platform-test",
                    "SECURITY_JWT_JWK_SET_URI": "http://keycloak:8080/realms/platform-test/protocol/openid-connect/certs",
                },
            }
        ]
        self.assertEqual(jwt_config_findings(documents, catalog(), "test"), [])

    def test_ethics_service_missing_jwks_is_rejected(self):
        documents = [
            {
                "kind": "ConfigMap",
                "metadata": {"name": "ethics-service-config"},
                "data": {
                    "SECURITY_JWT_ISSUER": "https://testai.acik.com/realms/platform-test"
                },
            }
        ]
        findings = jwt_config_findings(documents, catalog(), "test")
        self.assertEqual([finding.code for finding in findings], ["configmap_jwt_missing"])
        self.assertIn("SECURITY_JWT_JWK_SET_URI", findings[0].message)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
