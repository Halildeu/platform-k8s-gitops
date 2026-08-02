from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/contracts/faz35-evidence-custody.v1.json"
ADR = ROOT / "docs/adr/0048-faz35-evidence-dual-artifact-custody.md"
CHARTER = ROOT / "docs/faz-35-etik-speak-product-charter.md"
COMPARTMENT_ADR = ROOT / "docs/adr/0047-faz35-case-identity-link-compartments.md"


class Faz35EvidenceCustodyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.adr = ADR.read_text(encoding="utf-8")
        cls.charter = CHARTER.read_text(encoding="utf-8")
        cls.compartment_adr = COMPARTMENT_ADR.read_text(encoding="utf-8")

    def test_identity_and_truthful_default_are_exact(self) -> None:
        self.assertEqual(self.contract["schema"], "faz35-evidence-custody/v1")
        self.assertEqual(self.contract["product"], "etik-speak")
        self.assertEqual(
            self.contract["defaultMode"],
            "text-only-fail-closed-until-runtime-accepted",
        )
        self.assertIn("source/design decision only", self.adr)
        self.assertIn("do not prove\nscanner effectiveness", self.adr.lower())

    def test_dual_artifact_roles_and_storage_zones_are_separate(self) -> None:
        roles = set(self.contract["artifactRoles"])
        self.assertEqual(
            roles,
            {
                "quarantine-upload",
                "sealed-original",
                "sanitized-derivative",
                "controlled-export",
            },
        )
        zones = {zone["id"]: zone for zone in self.contract["storageZones"]}
        self.assertEqual(
            set(zones),
            {
                "quarantine",
                "sealed-original",
                "sanitized-derivative",
                "controlled-export",
            },
        )
        self.assertTrue(zones["sealed-original"]["objectLock"])
        self.assertFalse(zones["sealed-original"]["ordinaryStaffRead"])
        self.assertTrue(zones["sanitized-derivative"]["ordinaryStaffRead"])
        self.assertTrue(all(not zone["publicRead"] for zone in zones.values()))

    def test_forward_lifecycle_cannot_skip_integrity_seal_scan_or_sanitize(self) -> None:
        expected = [
            ["DECLARED", "UPLOADING"],
            ["UPLOADING", "QUARANTINED"],
            ["QUARANTINED", "INTEGRITY_VERIFIED"],
            ["INTEGRITY_VERIFIED", "ORIGINAL_SEALED"],
            ["ORIGINAL_SEALED", "SCANNING"],
            ["SCANNING", "SANITIZING"],
            ["SANITIZING", "DERIVATIVE_READY"],
            ["DERIVATIVE_READY", "AVAILABLE"],
        ]
        self.assertEqual(self.contract["forwardTransitions"], expected)
        states = self.contract["states"]
        self.assertEqual(len(states), len(set(states)))
        for terminal in self.contract["terminalOrBoundedStates"]:
            self.assertIn(terminal, states)
        self.assertTrue(
            {
                "sealed-original-immutable",
                "malware-verdict-clean",
                "sanitization-verdict-clean",
                "derivation-manifest-control-plane-signed",
                "correct-org-product-authz",
            }.issubset(self.contract["availabilityPreconditions"])
        )

    def test_admission_is_magic_authoritative_bounded_and_archive_deny(self) -> None:
        admission = self.contract["admission"]
        self.assertEqual(
            admission["mediaAuthority"],
            "magic-and-bounded-structural-parse",
        )
        self.assertFalse(admission["extensionAuthority"])
        self.assertLessEqual(admission["maxBytes"], 25 * 1024 * 1024)
        self.assertLessEqual(admission["uploadCapabilityTtlSeconds"], 600)
        self.assertTrue(admission["exactContentLengthRequired"])
        self.assertTrue(admission["sha256Required"])
        self.assertEqual(admission["archivePolicy"]["baseline"], "deny")
        self.assertTrue(
            admission["archivePolicy"]["futureEnablementRequiresNewContractVersion"]
        )
        self.assertTrue(
            {
                "archive-or-container",
                "unknown-or-polyglot",
                "executable",
                "macro-enabled-office",
            }.issubset(admission["deniedClasses"])
        )

    def test_standing_principals_cannot_read_sealed_original(self) -> None:
        principals = {
            principal["id"]: principal
            for principal in self.contract["principals"]
        }
        reveal = principals["sealed-reveal-session"]
        self.assertFalse(reveal["standing"])
        self.assertLessEqual(reveal["maxTtlSeconds"], 600)
        self.assertIn("read-once:one-sealed-original", reveal["capabilities"])
        self.assertTrue(
            {
                "two-different-human-approvers",
                "conflict-and-recusal-deny",
                "wrong-org-deny",
                "worm-audit",
            }.issubset(reveal["requires"])
        )

        for principal in principals.values():
            if principal["standing"]:
                self.assertNotIn(
                    "read:sealed-original",
                    principal["capabilities"],
                    principal["id"],
                )
                self.assertNotIn(
                    "read-once:one-sealed-original",
                    principal["capabilities"],
                    principal["id"],
                )

    def test_scanner_sandbox_and_derivative_lineage_fail_closed(self) -> None:
        sandbox = self.contract["scannerSandbox"]
        for required_true in (
            "immutableImageDigestRequired",
            "sbomAndProvenanceRequired",
            "nonRoot",
            "readOnlyRootFilesystem",
            "boundedCpuMemoryTimeAndOutput",
            "secondScanOfDerivativeRequired",
        ):
            self.assertTrue(sandbox[required_true], required_true)
        self.assertEqual(sandbox["network"], "none")
        self.assertEqual(sandbox["unknownVerdict"], "fail-closed-unavailable")

        sanitization = self.contract["sanitization"]
        self.assertFalse(sanitization["overwriteExistingDerivative"])
        self.assertTrue(sanitization["newVersionCreatesAppendOnlyLineage"])
        self.assertTrue(
            {
                "exif",
                "author",
                "scripts-and-actions",
                "external-references",
                "embedded-files",
                "active-content",
            }.issubset(sanitization["strip"])
        )

    def test_manifest_is_control_plane_signed_and_privacy_safe(self) -> None:
        manifest = self.contract["manifest"]
        self.assertEqual(manifest["signer"], "control-plane")
        self.assertEqual(manifest["hashAlgorithm"], "sha256")
        self.assertTrue(manifest["appendOnly"])
        self.assertTrue(manifest["hashChained"])
        self.assertTrue(
            {
                "sealed-original-sha256-and-size",
                "sanitized-derivative-sha256-and-size",
                "scanner-sanitizer-parser-image-digests",
                "signature-and-rule-versions",
                "previous-manifest-hash",
            }.issubset(manifest["requiredFields"])
        )
        self.assertTrue(
            {
                "attachment-content",
                "extracted-text",
                "original-filename",
                "reporter-identity",
                "narrative",
                "receipt-or-access-secret",
                "storage-credential-or-presigned-url",
            }.issubset(manifest["forbiddenFields"])
        )

    def test_outages_do_not_break_text_report_or_silently_downgrade(self) -> None:
        failures = {
            failure["failure"]: failure
            for failure in self.contract["failureModes"]
        }
        for failure in failures.values():
            self.assertFalse(failure["silentDowngrade"])
            self.assertIn("remain-functional", failure["reportAndMailbox"])
        self.assertIn("scanner-or-sanitizer-unavailable", failures)
        self.assertIn("audit-sink-unavailable", failures)
        self.assertIn("storage-unavailable", failures)

    def test_negative_matrix_covers_file_authz_reveal_privacy_and_rollback(self) -> None:
        negative = set(self.contract["requiredNegativeTests"])
        self.assertTrue(
            {
                "extension-magic-mismatch-denied",
                "oversized-upload-denied",
                "unknown-and-polyglot-denied",
                "archive-nesting-and-decompression-bomb-denied",
                "synthetic-malware-and-active-content-denied",
                "parser-timeout-fails-closed",
                "scan-and-sanitize-outage-keeps-text-journey-functional",
                "normal-case-role-cannot-read-quarantine-or-sealed-original",
                "wrong-org-technical-admin-reporter-credential-denied",
                "sealed-reveal-self-same-person-proxy-recused-expired-replay-denied",
                "attachment-content-filename-identity-secret-and-storage-url-absent-from-telemetry",
                "idempotent-retry-does-not-duplicate-original-derivative-or-custody-event",
                "rollback-preserves-text-intake-and-mailbox",
            }.issubset(negative)
        )

    def test_standards_human_gates_and_cross_references_cannot_disappear(self) -> None:
        standards = " ".join(self.contract["standards"])
        for required in (
            "ISO 37002",
            "ISO/IEC 27001",
            "ISO/IEC 27037",
            "GDPR",
            "KVKK",
            "NIST SP 800-53",
            "OWASP ASVS",
            "OWASP File Upload Cheat Sheet",
        ):
            self.assertIn(required, standards)
        self.assertGreaterEqual(len(self.contract["productionHumanGates"]), 5)
        self.assertGreaterEqual(len(self.contract["doesNotProve"]), 100)
        self.assertIn(
            "./contracts/faz35-evidence-custody.v1.json",
            self.charter,
        )
        self.assertIn(
            "./0048-faz35-evidence-dual-artifact-custody.md",
            self.compartment_adr,
        )

    def test_worker_object_store_identity_is_not_decided_by_list_order(self) -> None:
        """ES-104G (#2860) — the worker must keep its OWN object-store credentials.

        The API and the worker each get a secret, and both secrets use the same key
        names (`ETHICS_EVIDENCE_S3_ACCESS_KEY` / `_SECRET_KEY`). The worker mounts both
        via `envFrom`, where a duplicate key is resolved by POSITION: the last entry
        wins. Measured live on 2026-08-02 the worker does use its own identity — but
        only because its secret happens to be listed last.

        That is a separation held up by list order and nothing else. Reorder the list —
        by hand, by a merge, by a formatter — and the worker silently runs as the API
        identity: no error, no log line, no failed probe, and the "separate API and
        worker credentials" acceptance quietly becomes false. This test is the thing
        that would notice.
        """
        rendered = subprocess.run(
            ["kustomize", "build", str(ROOT / "kustomize/overlays/test/activation/etik-speak")],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

        worker = None
        for document in yaml.safe_load_all(rendered):
            if (
                document
                and document.get("kind") == "Deployment"
                and document["metadata"]["name"] == "ethics-evidence-worker"
            ):
                worker = document
                break
        self.assertIsNotNone(worker, "ethics-evidence-worker is missing from the rendered overlay")

        containers = worker["spec"]["template"]["spec"]["containers"]
        self.assertEqual(len(containers), 1, "unexpected container count on the evidence worker")
        sources = [
            entry["secretRef"]["name"]
            for entry in containers[0].get("envFrom", [])
            if "secretRef" in entry
        ]
        self.assertIn(
            "ethics-evidence-worker-secrets",
            sources,
            "the worker must be given its own object-store credentials",
        )
        if "ethics-service-secrets" in sources:
            self.assertGreater(
                sources.index("ethics-evidence-worker-secrets"),
                sources.index("ethics-service-secrets"),
                "the worker's own secret must come AFTER the API secret in envFrom, because "
                "the two share key names and the later entry wins; listed the other way round "
                "the worker would run as the API identity with no visible symptom",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
