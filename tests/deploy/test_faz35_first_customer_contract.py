from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/contracts/faz35-first-customer-journey.v1.json"
CHARTER = ROOT / "docs/faz-35-etik-speak-product-charter.md"


class Faz35FirstCustomerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text())
        cls.journey = cls.contract["journey"]
        cls.surfaces = {
            surface["id"]: surface for surface in cls.contract["surfaces"]
        }

    def test_identity_priority_and_evidence_layers_are_exact(self) -> None:
        self.assertEqual(
            self.contract["schema"],
            "faz35-first-customer-journey/v1",
        )
        self.assertEqual(self.contract["product"], "etik-speak")
        self.assertTrue(self.contract["blocksFeatureWorkUntilAccepted"])
        self.assertEqual(
            self.contract["evidenceLayers"],
            [
                "up",
                "functional",
                "authorized",
                "privacy-safe",
                "browser",
                "recoverable",
            ],
        )
        self.assertIn("hangi gerçek işi uçtan uca", self.contract["priorityQuestion"])

    def test_source_deployed_and_accepted_states_cannot_collapse(self) -> None:
        semantics = self.contract["stateSemantics"]
        self.assertEqual(set(semantics), {"source-ready", "deployed", "accepted"})
        self.assertIn("no runtime claim", semantics["source-ready"])
        self.assertIn("no customer-journey claim", semantics["deployed"])
        self.assertIn("full journey", semantics["accepted"])

    def test_public_aliases_and_manager_surfaces_are_explicit(self) -> None:
        self.assertEqual(
            self.surfaces["public-canonical"]["url"],
            "https://etik.acik.com",
        )
        self.assertEqual(
            self.surfaces["public-alias"]["url"],
            "https://speakup.acik.com",
        )
        self.assertEqual(
            self.surfaces["manager-test"]["url"],
            "https://testai.acik.com/ethic",
        )
        self.assertEqual(
            self.surfaces["manager-production"]["url"],
            "https://ai.acik.com/ethic",
        )
        self.assertEqual(
            self.surfaces["manager-production"]["acceptanceState"],
            "human-gated",
        )
        self.assertEqual(
            self.surfaces["public-canonical"]["artifactRole"],
            self.surfaces["public-alias"]["artifactRole"],
        )

    def test_journey_is_ordered_and_every_result_has_a_consumer(self) -> None:
        orders = [step["order"] for step in self.journey]
        self.assertEqual(orders, list(range(1, len(self.journey) + 1)))
        self.assertEqual(len({step["id"] for step in self.journey}), len(self.journey))

        allowed_layers = set(self.contract["evidenceLayers"])
        for step in self.journey:
            with self.subTest(step=step["id"]):
                self.assertTrue(step["action"])
                self.assertTrue(step["persistedResult"])
                self.assertTrue(step["nextConsumer"])
                self.assertTrue(step["requiredEvidenceLayers"])
                self.assertLessEqual(
                    set(step["requiredEvidenceLayers"]),
                    allowed_layers,
                )
                self.assertTrue(set(step["surfaces"]).issubset(self.surfaces))

        self.assertEqual(
            self.journey[-1]["persistedResult"],
            "The next authorized actor can use the reporter reply for continued case handling.",
        )

    def test_required_denials_cover_identity_authz_and_concurrency(self) -> None:
        controls = set(self.contract["requiredNegativeControls"])
        self.assertTrue(
            {
                "cross-host-receipt-deny",
                "wrong-organization-empty-list",
                "openfga-denied-existence-hiding",
                "idempotency-replay-and-conflict",
                "stale-writer-deny",
                "internal-note-hidden-from-reporter",
                "logout-revokes-mailbox-session",
                "suite-cookie-rejected-on-public-api",
                "raw-secret-absent-from-url-console-log-trace",
            }.issubset(controls)
        )

    def test_synthetic_boundary_and_production_human_gates_are_fail_closed(self) -> None:
        boundary = self.contract["testAcceptanceBoundary"]
        self.assertEqual(boundary["dataClass"], "synthetic-only")
        self.assertEqual(
            set(boundary["requiredSurfaces"]),
            {"public-canonical", "public-alias", "manager-test"},
        )
        self.assertIn("production readiness", boundary["doesNotProve"])
        self.assertIn(
            "recoverability until ES-009 evidence is accepted",
            boundary["doesNotProve"],
        )
        self.assertGreaterEqual(len(self.contract["productionHumanGates"]), 5)

    def test_recoverability_is_required_but_not_overclaimed(self) -> None:
        recoverability = self.contract["recoverabilityContract"]
        self.assertTrue(recoverability["required"])
        self.assertEqual(recoverability["currentEvidenceOwner"], "ES-009")
        self.assertGreaterEqual(len(recoverability["acceptance"]), 3)

    def test_charter_links_the_canonical_journey_contract(self) -> None:
        charter = CHARTER.read_text()
        self.assertIn(
            "./contracts/faz35-first-customer-journey.v1.json",
            charter,
        )
        for layer in (
            "`Up`",
            "`Functional`",
            "`Authorized`",
            "`Privacy-safe`",
            "`Browser`",
            "`Recoverable`",
        ):
            self.assertIn(layer, charter)


if __name__ == "__main__":
    unittest.main(verbosity=2)
