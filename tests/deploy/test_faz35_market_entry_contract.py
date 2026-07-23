from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs/contracts/faz35-market-entry-controls.v1.json"
CHARTER = ROOT / "docs/faz-35-etik-speak-product-charter.md"


class Faz35MarketEntryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.register = json.loads(REGISTER.read_text())
        cls.controls = cls.register["controls"]
        cls.charter = CHARTER.read_text()

    def test_register_identity_and_taxonomy_are_exact(self) -> None:
        self.assertEqual(self.register["schema"], "faz35-market-entry-controls/v1")
        self.assertEqual(self.register["product"], "etik-speak")
        self.assertEqual(self.register["environmentAuthority"], "test-first")
        self.assertEqual(
            set(self.register["classes"]),
            {"CORE-MUST", "CORE-CONFIG", "FEATURE", "INTEGRATION"},
        )
        self.assertEqual(
            set(self.register["applicabilityClasses"]),
            {
                "global-baseline",
                "jurisdiction-pack",
                "assurance",
                "post-baseline-feature",
            },
        )

    def test_control_ids_are_unique_and_required_fields_are_bounded(self) -> None:
        ids = [control["id"] for control in self.controls]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 12)

        for control in self.controls:
            with self.subTest(control=control["id"]):
                self.assertRegex(control["id"], r"^ME-[A-Z0-9-]+-\d{2}$")
                self.assertIn(control["class"], self.register["classes"])
                self.assertIn(
                    control["applicability"],
                    self.register["applicabilityClasses"],
                )
                self.assertRegex(control["source"]["url"], r"^https://")
                self.assertGreaterEqual(len(control["owners"]), 1)
                self.assertGreaterEqual(len(control["acceptance"]), 1)
                self.assertGreaterEqual(len(control["evidence"]), 1)
                self.assertGreaterEqual(len(control["doesNotProve"].strip()), 20)
                self.assertIsInstance(control["machineVerifiable"], bool)
                self.assertIsInstance(control["humanAcceptanceRequired"], bool)

    def test_market_entry_source_families_cannot_silently_disappear(self) -> None:
        source_names = " ".join(
            control["source"]["name"] for control in self.controls
        )
        for required in (
            "ISO 37002",
            "EU Directive 2019/1937",
            "ISO 37301",
            "GDPR",
            "ISO/IEC 27001",
            "Sarbanes-Oxley",
            "DOJ Evaluation",
            "OWASP ASVS",
            "WCAG 2.2",
            "NIST SP 800-63B",
            "OpenTelemetry",
            "SOC 2",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source_names)

    def test_jurisdiction_and_assurance_claims_keep_human_gate(self) -> None:
        for control in self.controls:
            if control["applicability"] in {"jurisdiction-pack", "assurance"}:
                with self.subTest(control=control["id"]):
                    self.assertTrue(control["humanAcceptanceRequired"])

        boundary = self.register["legalBoundary"].lower()
        for prohibited_claim in ("legal advice", "certification", "production authorization"):
            self.assertIn(prohibited_claim, boundary)

    def test_post_baseline_ai_is_not_an_es1_or_es2_dependency(self) -> None:
        ai_controls = [
            control
            for control in self.controls
            if control["applicability"] == "post-baseline-feature"
        ]
        self.assertEqual([control["id"] for control in ai_controls], ["ME-AI-RMF-01"])
        self.assertEqual(ai_controls[0]["class"], "FEATURE")
        self.assertEqual(ai_controls[0]["releaseGate"], "post-ES-2")

    def test_charter_points_to_register_and_has_current_truth_boundary(self) -> None:
        self.assertIn(
            "./contracts/faz35-market-entry-controls.v1.json",
            self.charter,
        )
        self.assertNotIn(
            "exact-scope review, merge ve runtime kabulü bekleniyor",
            self.charter,
        )
        self.assertRegex(
            self.charter,
            re.compile(
                r"sentetik TEST kapalı döngüsü doğrulandı.*"
                r"production insan kapıları.*bekliyor",
                re.DOTALL,
            ),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
