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
    image_contract_findings,
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

    def test_catalog_workload_moving_tag_is_rejected(self):
        documents = [deployment("ethics-service", "sha256:" + "a" * 64)]
        documents[0]["spec"]["template"]["spec"]["containers"][0][
            "image"
        ] = "openfga/openfga:v1.11.2"
        findings = image_contract_findings(documents, catalog(), "test")
        self.assertTrue(any(f.code == "image_digest_unpinned" for f in findings))

    def test_multiple_unnamed_primary_containers_are_rejected(self):
        documents = [
            deployment("ethics-service", "sha256:" + "a" * 64),
            deployment("etik-speak-public", "sha256:" + "b" * 64),
            deployment("etik-speak-manager", "sha256:" + "c" * 64),
        ]
        documents[0]["spec"]["template"]["spec"]["containers"].append(
            {
                "name": "primary-b",
                "image": "example/sidecar@sha256:" + "d" * 64,
            }
        )
        documents[0]["spec"]["template"]["spec"]["containers"][0][
            "name"
        ] = "primary-a"
        findings = image_contract_findings(documents, catalog(), "test")
        self.assertTrue(any(f.code == "image_primary_ambiguous" for f in findings))

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

    def test_etikspeak_authz_network_policy_is_bidirectional_and_narrow(self):
        root = Path(__file__).resolve().parents[3]
        permission_service = yaml.safe_load(
            (root / "kustomize/base/apps/permission-service/service.yaml").read_text()
        )
        permission_deployment = yaml.safe_load(
            (root / "kustomize/base/apps/permission-service/deployment.yaml").read_text()
        )
        policies = list(
            yaml.safe_load_all(
                (
                    root
                    / "kustomize/overlays/test/activation/etik-speak/netpol.yaml"
                ).read_text()
            )
        )
        by_name = {policy["metadata"]["name"]: policy for policy in policies}
        service_http = next(
            port
            for port in permission_service["spec"]["ports"]
            if port["name"] == "http"
        )
        self.assertEqual(service_http["port"], 8090)
        target_port = service_http["targetPort"]
        container_http = next(
            port
            for container in permission_deployment["spec"]["template"]["spec"][
                "containers"
            ]
            for port in container["ports"]
            if port["name"] == target_port
        )
        self.assertEqual(container_http["containerPort"], 8084)

        ethics = by_name["ethics-service"]["spec"]
        egress_ports = {
            port["port"]
            for rule in ethics["egress"]
            for port in rule.get("ports", [])
        }
        self.assertTrue({8080, target_port}.issubset(egress_ports))
        for target, port in (("openfga", 8080), ("permission-service", target_port)):
            policy = by_name[f"allow-ethics-service-to-{target}"]["spec"]
            self.assertEqual(
                policy["podSelector"]["matchLabels"]["app.kubernetes.io/name"],
                target,
            )
            source = policy["ingress"][0]["from"][0]["podSelector"]["matchLabels"]
            self.assertEqual(
                source,
                {
                    "app.kubernetes.io/name": "ethics-service",
                    "app.kubernetes.io/part-of": "etik-speak",
                },
            )
            self.assertEqual(policy["ingress"][0]["ports"], [{"port": port, "protocol": "TCP"}])

    def test_openfga_and_migration_job_use_exact_digest_with_safe_job_recreation(self):
        root = Path(__file__).resolve().parents[3]
        expected = (
            "openfga/openfga@sha256:"
            "e5891e4676e5a8b4659c010c50aabf487397844b18f66ef7510e5ad00935949f"
        )
        for relative in (
            "kustomize/base/apps/openfga/statefulset.yaml",
            "kustomize/base/apps/openfga/migrate-job.yaml",
        ):
            self.assertIn(f"image: {expected}", (root / relative).read_text())
        migration_job = yaml.safe_load(
            (root / "kustomize/base/apps/openfga/migrate-job.yaml").read_text()
        )
        annotations = migration_job["metadata"]["annotations"]
        self.assertEqual(annotations["argocd.argoproj.io/hook"], "PreSync")
        self.assertEqual(
            set(annotations["argocd.argoproj.io/hook-delete-policy"].split(",")),
            {"BeforeHookCreation", "HookSucceeded"},
        )
        self.assertEqual(annotations["argocd.argoproj.io/sync-wave"], "-1")

    def test_rollback_contract_forbids_activation_resource_removal(self):
        root = Path(__file__).resolve().parents[3]
        runbook = (
            root / "docs/runbooks/RB-faz35-etik-speak-test-activation.md"
        ).read_text()
        self.assertNotIn("removal of the test activation resource", runbook)
        self.assertIn(
            "`activation/etik-speak` with `deactivation/etik-speak`", runbook
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
