from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/contracts/faz35-privacy-no-collect.v1.json"
THREAT_MODEL = ROOT / "docs/security/faz35-privacy-anonymity-threat-model.md"
PRIVACY_NOTICE = ROOT / "docs/legal/faz35-privacy-notice-tr.md"


class Faz35PrivacyNoCollectContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text())
        cls.threat_model = THREAT_MODEL.read_text()
        cls.privacy_notice = PRIVACY_NOTICE.read_text()

    def test_contract_identity_and_honest_claim_boundary(self) -> None:
        self.assertEqual(self.contract["schema"], "faz35-privacy-no-collect/v1")
        self.assertEqual(self.contract["product"], "etik-speak")
        self.assertEqual(self.contract["mode"], "anonymous")
        boundary = self.contract["claimBoundary"]
        for external_observer in (
            "reporter device",
            "ISP",
            "public CA",
            "DNS resolver",
            "upstream network operator",
        ):
            self.assertIn(external_observer, boundary)

    def test_anonymous_identity_compartment_is_forbidden(self) -> None:
        compartments = {
            compartment["id"]: compartment
            for compartment in self.contract["compartments"]
        }
        self.assertEqual(
            compartments["reporter-identity"]["anonymousMode"],
            "forbidden",
        )
        self.assertEqual(
            compartments["transport-abuse-state"]["anonymousMode"],
            "volatile-only",
        )
        self.assertEqual(
            compartments["attachment"]["anonymousMode"],
            "fail-closed-until-quarantine",
        )

    def test_identity_and_transport_metadata_are_never_collected(self) -> None:
        never_collect = set(self.contract["neverCollectInAnonymousMode"])
        self.assertTrue(
            {
                "name",
                "email",
                "phone",
                "employee-id",
                "suite-user-id",
                "device-fingerprint",
                "client-ip-durable",
                "user-agent-durable",
                "referrer-durable",
                "tls-session-durable",
            }.issubset(never_collect)
        )

    def test_secret_receipt_payload_and_client_identity_are_never_logged(self) -> None:
        never_log = set(self.contract["neverLogOrTrace"])
        self.assertTrue(
            {
                "raw-access-secret",
                "mailbox-session-cookie",
                "receipt-id",
                "case-narrative",
                "attachment-content",
                "reporter-identity",
                "client-ip",
                "x-forwarded-for",
                "x-real-ip",
                "user-agent",
                "referrer",
                "tls-session-id",
                "suite-cookie",
                "authorization-header",
            }.issubset(never_log)
        )

    def test_transport_use_is_volatile_unhashed_and_uncorrelated(self) -> None:
        for transport in self.contract["volatileTransportUse"]:
            with self.subTest(field=transport["field"]):
                self.assertFalse(transport["durable"])
                self.assertFalse(transport["hashed"])
                self.assertFalse(transport["caseCorrelated"])
                self.assertTrue(transport["lifetime"])

    def test_all_insider_and_boundary_classes_are_explicit(self) -> None:
        actor_ids = {actor["id"] for actor in self.contract["actors"]}
        self.assertTrue(
            {
                "reporter",
                "case-worker",
                "subject-of-report",
                "platform-operator",
                "database-operator",
                "observability-operator",
                "backup-operator",
                "key-custodian",
                "public-edge-operator",
            }.issubset(actor_ids)
        )
        boundary_ids = {
            boundary["id"] for boundary in self.contract["trustBoundaries"]
        }
        self.assertGreaterEqual(len(boundary_ids), 7)
        self.assertEqual(len(boundary_ids), len(self.contract["trustBoundaries"]))

    def test_threats_have_controls_and_machine_verification(self) -> None:
        threat_ids = [threat["id"] for threat in self.contract["threats"]]
        self.assertEqual(len(threat_ids), len(set(threat_ids)))
        self.assertGreaterEqual(len(threat_ids), 8)
        for threat in self.contract["threats"]:
            with self.subTest(threat=threat["id"]):
                self.assertTrue(threat["actor"])
                self.assertGreaterEqual(len(threat["controls"]), 2)
                self.assertGreaterEqual(len(threat["verification"]), 1)

    def test_runtime_negative_contract_covers_edge_app_db_and_browser(self) -> None:
        negative = set(self.contract["requiredNegativeTests"])
        self.assertTrue(
            {
                "no-domain-dot-acik-cookie",
                "suite-cookie-rejected-on-public-api",
                "client-identity-forwarding-headers-empty",
                "public-ingress-access-log-disabled",
                "synthetic-ip-ua-referrer-sentinel-absent",
                "raw-secret-receipt-narrative-absent-from-telemetry",
                "anonymous-identity-columns-null-or-absent",
                "wrong-org-and-openfga-denied-existence-hiding",
                "internal-note-hidden-from-reporter",
                "secret-absent-from-url-console-and-storage",
            }.issubset(negative)
        )

    def test_residual_risks_and_production_human_gates_remain_open(self) -> None:
        residual = self.contract["residualRisks"]
        self.assertGreaterEqual(len(residual), 4)
        self.assertTrue(all(risk["productionGate"] for risk in residual))
        self.assertGreaterEqual(len(self.contract["productionHumanGates"]), 5)

    def test_threat_model_and_privacy_notice_match_fail_closed_contract(self) -> None:
        self.assertIn(
            "../contracts/faz35-privacy-no-collect.v1.json",
            self.threat_model,
        )
        self.assertIn("YAYINLANAMAZ TASLAK", self.privacy_notice)
        self.assertIn("Rate-limit IP/hash | Saklanmaz", self.privacy_notice)
        self.assertIn("Public auth cookie | Yok", self.privacy_notice)
        self.assertIn(
            "Gerçek anonim modda reporter identity toplanmaz",
            self.privacy_notice,
        )
        for stale_claim in (
            "Rate-limit IP hash | 24 saat",
            "Basic-auth gate cookie",
            "5 yıl (case closure sonrası)",
            "10 yıl (immutable)",
            "250+ çalışan işletmeler",
        ):
            self.assertNotIn(stale_claim, self.privacy_notice)


if __name__ == "__main__":
    unittest.main(verbosity=2)
