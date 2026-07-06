#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ I6 MASQ evidence validator."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify-wg-bplus-i6-masq-evidence.py"


def valid_evidence() -> dict:
    checks = []
    for check_id in [
        "host-namespace-nat-rule-present",
        "pod-cidr-to-wg-masq-rule",
        "pod-to-platform-ai-http",
        "reboot-persistence",
        "drift-detect",
        "rollback-defined",
        "daemonset-not-assumed",
        "no-broad-lan-nat",
    ]:
        checks.append(
            {
                "id": check_id,
                "status": "pass",
                "observedAt": "2026-06-25T03:20:00Z",
                "summary": f"{check_id} metadata satisfied",
                "evidenceRef": f"checks/{check_id}.json",
            }
        )

    return {
        "schemaVersion": "faz24.wg-bplus.i6.pod-cidr-wg-masq.v1",
        "collectedAt": "2026-06-25T03:20:00Z",
        "status": "pass",
        "protectedEvidencePath": "github-actions://Halildeu/platform-k8s-gitops/actions/runs/1",
        "redaction": {
            "secretMaterialIncluded": False,
            "rawCommandOutputIncluded": False,
            "rawPacketCaptureIncluded": False,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
        },
        "topology": {
            "clusterName": "k3d-test",
            "podCIDR": "10.44.0.0/16",
            "serviceCIDR": "10.45.0.0/16",
            "wgInterface": "wg0",
            "platformAiTarget": {
                "host": "10.99.0.2",
                "port": 8200,
            },
        },
        "mechanism": {
            "type": "host-systemd-iptables",
            "managedOutsideCluster": True,
            "daemonSetAssumed": False,
            "host": "staging-sw",
            "systemdUnit": "k3d-wg-masq.service",
            "iptablesTable": "nat",
            "iptablesChain": "POSTROUTING",
            "expectedRuleHash": "0123456789abcdef",
        },
        "driftDetection": {
            "enabled": True,
            "mode": "systemd-timer",
            "intervalMinutes": 5,
            "expectedRuleHash": "0123456789abcdef",
            "evidenceRef": "drift/k3d-wg-masq-timer.json",
        },
        "rollback": {
            "defined": True,
            "tested": True,
            "commandHash": "fedcba9876543210",
            "evidenceRef": "rollback/dry-run.json",
        },
        "checks": checks,
    }


class WgBplusI6MasqEvidenceValidatorTest(unittest.TestCase):
    def run_validator(self, data: dict, *extra_args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            return subprocess.run(
                [sys.executable, str(SCRIPT), tmp.name, *extra_args],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_valid_evidence_passes(self):
        result = self.run_validator(valid_evidence())

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz24 WG-B+ I6 MASQ evidence: PASS", result.stdout)
        self.assertIn("podCIDR=10.44.0.0/16", result.stdout)

    def test_daemonset_assumption_fails(self):
        data = valid_evidence()
        data["mechanism"]["daemonSetAssumed"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("mechanism.daemonSetAssumed", result.stderr)

    def test_missing_required_check_fails(self):
        data = valid_evidence()
        data["checks"] = [check for check in data["checks"] if check["id"] != "rollback-defined"]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing required check 'rollback-defined'", result.stderr)

    def test_duplicate_check_id_fails(self):
        data = valid_evidence()
        data["checks"].append(dict(data["checks"][0]))

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("duplicate check id", result.stderr)

    def test_secret_or_raw_output_key_fails(self):
        data = valid_evidence()
        data["rawOutput"] = "iptables -t nat -S output"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("forbidden_key", result.stderr)

    def test_secret_like_value_fails(self):
        data = valid_evidence()
        data["operatorNote"] = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJpNiJ9.fakefakefake"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("secret_like_value", result.stderr)

    def test_rollback_must_be_tested(self):
        data = valid_evidence()
        data["rollback"]["tested"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("rollback.tested", result.stderr)

    def test_drift_hash_must_match_mechanism_hash(self):
        data = valid_evidence()
        data["driftDetection"]["expectedRuleHash"] = "1111111111111111"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("drift_hash_mismatch", result.stderr)

    def test_broad_pod_cidr_fails(self):
        data = valid_evidence()
        data["topology"]["podCIDR"] = "10.0.0.0/8"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("prefix is too broad", result.stderr)

    def test_host_bits_in_cidr_fail(self):
        data = valid_evidence()
        data["topology"]["podCIDR"] = "10.44.0.5/16"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be a valid CIDR", result.stderr)

    def test_absolute_evidence_ref_fails(self):
        data = valid_evidence()
        data["checks"][0]["evidenceRef"] = "/etc/iptables/rules.v4"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must stay under protectedEvidencePath", result.stderr)

    def test_parent_traversal_evidence_ref_fails(self):
        data = valid_evidence()
        data["checks"][0]["evidenceRef"] = "checks/../raw.txt"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must stay under protectedEvidencePath", result.stderr)

    def test_summary_json_is_written(self):
        data = valid_evidence()
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as evidence_tmp:
            with tempfile.NamedTemporaryFile("r", suffix=".json", encoding="utf-8") as summary_tmp:
                json.dump(data, evidence_tmp)
                evidence_tmp.flush()

                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT),
                        evidence_tmp.name,
                        "--summary-json",
                        summary_tmp.name,
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                summary = json.load(summary_tmp)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pass", summary["status"])
        self.assertEqual("10.44.0.0/16", summary["podCIDR"])


if __name__ == "__main__":
    unittest.main()
