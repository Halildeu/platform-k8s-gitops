#!/usr/bin/env python3

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Faz25P5ProductAcceptanceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (
            ROOT / ".github/workflows/verify-faz25-p5-product-surface.yml"
        ).read_text()
        cls.spec = (
            ROOT / "tests/smoke/faz25-p5-product-surface.spec.ts"
        ).read_text()
        cls.collector = (
            ROOT / "scripts/deploy/collect-faz25-p5-frontend-lineage.sh"
        ).read_text()
        cls.product_schema = json.loads(
            (ROOT / "tests/smoke/faz25-p5-product-surface.schema.json").read_text()
        )
        cls.manifest_schema = json.loads(
            (ROOT / "tests/smoke/faz25-p5-evidence-manifest.schema.json").read_text()
        )

    def test_workflow_is_main_only_and_uses_protected_environment_secrets(self):
        self.assertIn('[[ "$GITHUB_REF" == "refs/heads/main" ]]', self.workflow)
        self.assertIn(
            '[[ "$harness_revision" == "$(git rev-parse refs/remotes/origin/main)" ]]',
            self.workflow,
        )
        self.assertIn('canonical_main_at_end=true', self.workflow)
        self.assertIn("environment: testai-product-acceptance", self.workflow)
        self.assertIn("secrets.P5_SMOKE_AUTH_USERNAME", self.workflow)
        self.assertIn("secrets.P5_SMOKE_AUTH_PASSWORD", self.workflow)
        self.assertNotIn("secrets.SMOKE_AUTH_USERNAME", self.workflow)
        self.assertNotIn("secrets.SMOKE_AUTH_PASSWORD", self.workflow)
        self.assertIn("application window not used", self.workflow)
        self.assertIn("Prepare sanitized incomplete-contract diagnostics", self.workflow)
        self.assertIn("Upload sanitized incomplete-contract diagnostics", self.workflow)
        self.assertIn('terminalAcceptance: false', self.workflow)

    def test_browser_contract_binds_pkce_origin_and_exact_product_sets(self):
        for marker in (
            "callbackCode === exchangeCode",
            "calculatedChallenge === authorizeCodeChallenge",
            "url.origin === issuerOrigin",
            "url.origin === appOrigin",
            "interactiveControlIds).toEqual(expectedInteractiveControlIds)",
            "expect(gateIds).toEqual(expectedGateIds)",
            "expect(headerLabels).toEqual(expectedHeaderLabels)",
            "maxRedirects: 0",
            "expect(buildInfoResponse.url()).toBe(buildInfoUrl)",
            "expect(buildInfoResponse.headers()['content-type']).toMatch",
            "expect(Object.keys(buildInfo).sort()).toEqual",
        ):
            self.assertIn(marker, self.spec)

    def test_lineage_collector_binds_owner_chain_and_observed_image_id(self):
        self.assertIn('.metadata.ownerReferences[]?', self.collector)
        self.assertIn('.imageID | endswith("@" + $digest)', self.collector)
        self.assertIn("EXPECTED_BUILD_RUN_ID", self.collector)
        self.assertIn('observed_digest="$(jq -r', self.collector)
        self.assertIn('mv "$report_tmp" "$REPORT_PATH"', self.collector)
        self.assertIn("EXPECTED_CLUSTER_CA_SHA256", self.collector)
        self.assertIn("EXPECTED_KUBE_SYSTEM_UID", self.collector)
        self.assertIn("buildProvenanceReceiptSha256", self.collector)
        self.assertIn("slsaProvenanceDigest", self.collector)

    def test_pass_schema_requires_terminal_product_evidence(self):
        then_clause = self.product_schema["allOf"][0]["then"]
        self.assertEqual(
            then_clause["required"],
            ["authz", "product", "responsive", "accessibility", "runtime"],
        )
        self.assertEqual(
            then_clause["properties"]["product"]["allOf"][1]["properties"]
            ["ownerAcceptance"]["const"],
            "0/8",
        )
        self.assertEqual(
            then_clause["properties"]["accessibility"]["allOf"][1]["properties"]
            ["blockingViolationCount"]["const"],
            0,
        )
        self.assertIn(
            "loginBlockingViolationCount",
            self.product_schema["definitions"]["authentication"]["required"],
        )

    def test_manifest_schema_requires_one_child_of_each_source(self):
        children_rules = self.manifest_schema["allOf"][2]["properties"]["children"]
        kinds = {
            rule["contains"]["properties"]["kind"]["const"]
            for rule in children_rules["allOf"]
        }
        self.assertEqual(kinds, {"browser", "lineage-pre", "lineage-post"})

    def test_manifest_fail_branch_is_strict_diagnostic_only(self):
        self.assertFalse(self.manifest_schema["additionalProperties"])
        fail_then = self.manifest_schema["allOf"][1]["then"]
        self.assertEqual(
            fail_then["properties"]["artifactKind"]["const"],
            "diagnostic",
        )
        binding = self.manifest_schema["properties"]["binding"]
        self.assertFalse(binding["additionalProperties"])
        self.assertEqual(
            set(binding["required"]),
            {
                "canonicalMainAtStart",
                "canonicalMainAtEnd",
                "prePostSameSession",
                "freshWithinRun",
                "strictChildSchemas",
                "sensitiveValueScanPassed",
            },
        )


if __name__ == "__main__":
    unittest.main()
