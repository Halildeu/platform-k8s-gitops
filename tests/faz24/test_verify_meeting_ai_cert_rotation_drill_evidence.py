#!/usr/bin/env python3
"""Tests for the Faz 24 Meeting-AI gateway cert rotation fire-drill verifier."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify_meeting_ai_cert_rotation_drill_evidence.py"


def valid_evidence() -> dict:
    return {
        "schemaVersion": "faz24.meetingAiCertRotationDrillEvidence.v1",
        "status": "pass",
        "issue": "platform-k8s-gitops#2321",
        "tokenIncluded": False,
        "generatedAt": "2026-07-13T14:05:00Z",
        "failures": [],
        "environment": {
            "host": "staging-sw",
            "scope": "test",
            "vaultTransport": "container",
            "gatewayService": "meeting-ai-private-gateway.service",
            "rotationTimer": "meeting-ai-server-cert-rotation.timer",
            "rotationScheduleHours": 8,
        },
        "pki": {
            "serverMount": "pki_meeting_ai_server",
            "issueRole": "staging-gateway",
            "commonName": "meeting-ai-gateway.internal",
            "leafTtlHours": 24,
            "fullchainServed": True,
            "sanDnsIncludesGatewayInternal": True,
            "newLeafFingerprintSha256": "a" * 64,
            "previousLeafFingerprintSha256": "b" * 64,
            "scopedToken": {
                "rootTokenUsed": False,
                "policy": "meeting-ai-gateway-server",
                "renewIncrementHours": 24,
                "tokenValueIncluded": False,
            },
        },
        "successRotation": {
            "attempted": True,
            "succeeded": True,
            "atomicPointerSwapped": True,
            "currentTarget": "issued-20260713T140455Z-0a1b2c3d",
            "previousTarget": "issued-20260713T060455Z-9f8e7d6c",
            "gatewayReloaded": True,
            "notAfterAdvanced": True,
            "leafCheckendHours": 12,
            "versionsRetained": 3,
            "uninterruptedHealthzProbe": {
                "clientCertificateUsed": True,
                "httpStatus": 200,
                "observedAt": "2026-07-13T14:05:10Z",
            },
        },
        "telemetry": {
            "textfilePresent": True,
            "metricsPresent": [
                "meeting_ai_gateway_rotation_last_attempt_timestamp_seconds",
                "meeting_ai_gateway_rotation_last_success_timestamp_seconds",
                "meeting_ai_gateway_rotation_last_run_success",
                "meeting_ai_gateway_certificate_not_after_timestamp_seconds",
            ],
            "lastRunSuccessValue": 1,
            "lastAttemptAdvanced": True,
            "lastSuccessAdvanced": True,
        },
        "failureDrill": {
            "induced": True,
            "inducedFailureClass": "reload_failure",
            "pointerRolledBack": True,
            "rolledBackToPreviousTarget": True,
            "serviceStayedServingPreviousCert": True,
            "lastRunSuccessValueDuringFailure": 0,
            "newVersionRemovedOnFailure": True,
            "postDrillRecovered": True,
        },
        "alertDrill": {
            "prometheusRuleName": "meeting-ai-gateway",
            "alertsFiredDuringFailure": ["MeetingAIGatewayCertificateRotationFailed"],
            "alertsClearedAfterRecovery": True,
        },
        "boundaries": {
            "certRotationDrillProven": True,
            "privateListenerActivationProven": False,
            "mtlsNegativeMatrixProven": False,
            "jwtClaimMatrixProven": False,
            "outboxDrainProven": False,
            "electronProductPathProven": False,
            "productionReady": False,
            "rawKeyMaterialIncluded": False,
            "rawTokenIncluded": False,
        },
    }


class MeetingAiCertRotationDrillVerifierTest(unittest.TestCase):
    def run_validator(self, data: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            return subprocess.run(
                [sys.executable, str(SCRIPT), tmp.name],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_valid_evidence_passes(self):
        result = self.run_validator(valid_evidence())

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Meeting-AI cert rotation drill evidence: PASS", result.stdout)

    def test_schema_version_required(self):
        data = valid_evidence()
        data["schemaVersion"] = "faz24.somethingElse.v1"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("schema_version", result.stdout)

    def test_issue_binding_required(self):
        data = valid_evidence()
        data["issue"] = "platform-ai#182"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("issue", result.stdout)

    def test_scope_must_be_test(self):
        data = valid_evidence()
        data["environment"]["scope"] = "prod"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("environment_scope", result.stdout)

    def test_rotation_schedule_hours_pinned(self):
        data = valid_evidence()
        data["environment"]["rotationScheduleHours"] = 24

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("environment_rotation_schedule_hours", result.stdout)

    def test_root_token_use_rejected(self):
        data = valid_evidence()
        data["pki"]["scopedToken"]["rootTokenUsed"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("pki_scoped_token_root_absent", result.stdout)

    def test_leaf_fingerprint_must_rotate(self):
        data = valid_evidence()
        data["pki"]["previousLeafFingerprintSha256"] = data["pki"]["newLeafFingerprintSha256"]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("pki_leaf_fingerprint_rotated", result.stdout)

    def test_current_target_shape_enforced(self):
        data = valid_evidence()
        data["successRotation"]["currentTarget"] = "current"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("success_current_target", result.stdout)

    def test_success_must_serve_new_leaf_healthz(self):
        data = valid_evidence()
        data["successRotation"]["uninterruptedHealthzProbe"]["httpStatus"] = 503

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("success_healthz_status", result.stdout)

    def test_missing_rotation_metric_fails(self):
        data = valid_evidence()
        data["telemetry"]["metricsPresent"] = [
            "meeting_ai_gateway_rotation_last_attempt_timestamp_seconds",
            "meeting_ai_gateway_rotation_last_run_success",
        ]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("telemetry_required_metrics", result.stdout)

    def test_last_run_success_value_after_success(self):
        data = valid_evidence()
        data["telemetry"]["lastRunSuccessValue"] = 0

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("telemetry_last_run_success_value", result.stdout)

    def test_failure_drill_rollback_required(self):
        data = valid_evidence()
        data["failureDrill"]["pointerRolledBack"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("failure_pointer_rolled_back", result.stdout)

    def test_failure_drill_no_outage_required(self):
        data = valid_evidence()
        data["failureDrill"]["serviceStayedServingPreviousCert"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("failure_service_kept_serving", result.stdout)

    def test_failure_last_run_success_must_be_zero(self):
        data = valid_evidence()
        data["failureDrill"]["lastRunSuccessValueDuringFailure"] = 1

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("failure_last_run_success_zero", result.stdout)

    def test_required_failure_alert_must_fire(self):
        data = valid_evidence()
        data["alertDrill"]["alertsFiredDuringFailure"] = ["MeetingAIGatewayCertificateExpiring"]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("alert_fired_required", result.stdout)

    def test_unknown_alert_rejected(self):
        data = valid_evidence()
        data["alertDrill"]["alertsFiredDuringFailure"] = [
            "MeetingAIGatewayCertificateRotationFailed",
            "MeetingAIGatewaySomethingUnshipped",
        ]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("alert_fired_known", result.stdout)

    def test_production_ready_overclaim_rejected(self):
        data = valid_evidence()
        data["boundaries"]["productionReady"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("boundary_productionReady", result.stdout)

    def test_mtls_negative_matrix_overclaim_rejected(self):
        data = valid_evidence()
        data["boundaries"]["mtlsNegativeMatrixProven"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("boundary_mtlsNegativeMatrixProven", result.stdout)

    def test_forbidden_key_private_key_rejected(self):
        data = valid_evidence()
        data["pki"]["privateKey"] = "irrelevant"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_vault_token_value_rejected(self):
        data = valid_evidence()
        data["pki"]["scopedToken"]["vaultToken"] = "hvs.AAAAAAAAAAAAAAAAAAAAAAAA"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_pem_value_rejected_even_under_safe_key(self):
        data = valid_evidence()
        data["pki"]["note"] = "-----BEGIN CERTIFICATE-----\nMIID\n-----END CERTIFICATE-----"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_url_value_rejected(self):
        data = valid_evidence()
        data["environment"]["vaultEndpoint"] = "https://127.0.0.1:8202"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_token_included_flag_must_be_false(self):
        data = valid_evidence()
        data["tokenIncluded"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("token_not_included", result.stdout)

    def test_summary_json_written(self):
        data = valid_evidence()
        with tempfile.TemporaryDirectory() as tmp:
            evidence_path = Path(tmp) / "evidence.json"
            summary_path = Path(tmp) / "summary.json"
            evidence_path.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(evidence_path), "--summary-json", str(summary_path)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual("faz24.meetingAiCertRotationDrillVerifier.v1", summary["schemaVersion"])
            self.assertEqual("pass", summary["status"])
            self.assertEqual(summary["passed"], summary["total"])


if __name__ == "__main__":
    unittest.main()
