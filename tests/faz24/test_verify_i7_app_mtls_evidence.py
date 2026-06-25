#!/usr/bin/env python3
"""Tests for the Faz 24 I7 app-mTLS evidence validator."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify-i7-app-mtls-evidence.py"


def check(check_id: str) -> dict:
    return {
        "id": check_id,
        "status": "pass",
        "observedAt": "2026-06-25T11:00:00Z",
        "summary": f"{check_id} metadata satisfied",
        "evidenceRef": f"checks/{check_id}.json",
        "evidenceHash": "0123456789abcdef",
    }


def service(name: str) -> dict:
    port = {"live-stt": 8243, "meeting-ai": 8343}[name]
    path = "/health" if name == "live-stt" else "/"
    return {
        "name": name,
        "endpoint": {
            "host": "live-stt.denetim" if name == "live-stt" else "meeting-ai.denetim",
            "wgIp": "10.99.0.2",
            "port": port,
            "path": path,
        },
        "validClientProbe": {
            "status": "pass",
            "observedAt": "2026-06-25T11:00:00Z",
            "tlsVerified": True,
            "clientCertificatePresented": True,
            "accepted": True,
            "httpStatus": 200,
            "evidenceRef": f"services/{name}/valid-client.json",
        },
        "noClientCertProbe": {
            "status": "pass",
            "observedAt": "2026-06-25T11:00:00Z",
            "rejected": True,
            "failureClass": "tls_client_certificate_required",
            "evidenceRef": f"services/{name}/no-client-cert.json",
        },
        "wrongClientCertProbe": {
            "status": "pass",
            "observedAt": "2026-06-25T11:00:00Z",
            "rejected": True,
            "failureClass": "tls_unknown_ca",
            "evidenceRef": f"services/{name}/wrong-client-cert.json",
        },
    }


def valid_preflight() -> dict:
    required_checks = [
        "wg-route-to-denetim",
        "tcp-8243-reachable",
        "tls-server-identity-verified",
        "mtls-valid-client-accepted",
        "mtls-no-client-rejected",
        "mtls-wrong-client-rejected",
        "redaction-no-audio-transcript",
    ]
    return {
        "schemaVersion": "faz24.i7.app-mtls.evidence.v1",
        "evidenceProfile": "live-stt-preflight",
        "collectedAt": "2026-06-25T11:00:00Z",
        "status": "pass",
        "tokenIncluded": False,
        "protectedEvidencePath": "github-actions://Halildeu/platform-k8s-gitops/actions/runs/1",
        "redaction": {
            "secretMaterialIncluded": False,
            "privateKeyIncluded": False,
            "rawCommandOutputIncluded": False,
            "rawPacketCaptureIncluded": False,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
        },
        "topology": {
            "source": "staging-sw/audio-gateway",
            "wgInterface": "wg0",
            "sourceWgIp": "10.99.0.1",
            "denetimWgIp": "10.99.0.2",
            "dnsName": "live-stt.denetim",
        },
        "pki": {
            "authority": "vault-pki-denetim-ai",
            "caBundleSha256": "a" * 64,
            "serverCertFingerprintSha256": "b" * 64,
            "clientCertFingerprintSha256": "c" * 64,
            "serverCertSanDns": ["live-stt.denetim"],
            "serverCertSanIps": ["10.99.0.2"],
        },
        "services": [service("live-stt")],
        "checks": [check(check_id) for check_id in required_checks],
        "boundaries": {
            "liveSttAppMtlsPreflightProven": True,
            "meetingAiAppMtlsProven": False,
            "i7ProdGateProven": False,
            "directSttEnabled": False,
            "computePlaneAuditProven": False,
            "directAudioE2eProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
        },
    }


def valid_prod_gate() -> dict:
    data = valid_preflight()
    data["evidenceProfile"] = "prod-gate"
    data["services"].append(service("meeting-ai"))
    data["checks"] = [
        check(check_id)
        for check_id in [
            "wg-route-to-denetim",
            "tcp-8243-reachable",
            "tcp-8343-reachable",
            "tls-server-identity-verified",
            "mtls-valid-client-accepted",
            "mtls-no-client-rejected",
            "mtls-wrong-client-rejected",
            "meeting-ai-mtls-valid-client-accepted",
            "request-audit-emitted",
            "plaintext-bypass-closed",
            "cert-rotation-drill",
            "failure-drill-fail-fast",
            "redaction-no-audio-transcript",
        ]
    ]
    data["boundaries"]["meetingAiAppMtlsProven"] = True
    data["boundaries"]["i7ProdGateProven"] = True
    data["requestAudit"] = {
        "emitted": True,
        "correlationPropagated": True,
        "clientCertIdentityLogged": True,
        "rawAudioLogged": False,
        "rawTranscriptLogged": False,
        "evidenceRef": "audit/request-audit.json",
    }
    data["rotation"] = {
        "tested": True,
        "newClientCertAccepted": True,
        "oldClientCertRejected": True,
        "evidenceRef": "rotation/client-cert-rotation.json",
    }
    data["failureDrill"] = {
        "mtlsFailureFailFast": True,
        "wgDownFailFast": True,
        "evidenceRef": "failure-drill/fail-fast.json",
    }
    data["plaintextBypass"] = {
        "closed": True,
        "externalPlaintextReachable": False,
        "evidenceRef": "plaintext-bypass/closed.json",
    }
    return data


class I7AppMtlsEvidenceValidatorTest(unittest.TestCase):
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

    def test_valid_preflight_passes(self):
        result = self.run_validator(valid_preflight())

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz24 I7 app-mTLS evidence: PASS", result.stdout)
        self.assertIn("evidenceProfile=live-stt-preflight", result.stdout)

    def test_valid_prod_gate_passes(self):
        result = self.run_validator(valid_prod_gate())

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("services=live-stt,meeting-ai", result.stdout)

    def test_preflight_must_not_include_meeting_ai_scope(self):
        data = valid_preflight()
        data["services"].append(service("meeting-ai"))

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("live-stt-preflight evidence must not include meeting-ai", result.stderr)

    def test_missing_tcp_8243_check_fails(self):
        data = valid_preflight()
        data["checks"] = [item for item in data["checks"] if item["id"] != "tcp-8243-reachable"]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing required check 'tcp-8243-reachable'", result.stderr)

    def test_valid_probe_must_be_accepted(self):
        data = valid_preflight()
        data["services"][0]["validClientProbe"]["accepted"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("validClientProbe.accepted", result.stderr)

    def test_wrong_cert_must_be_rejected(self):
        data = valid_preflight()
        data["services"][0]["wrongClientCertProbe"]["rejected"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("wrongClientCertProbe.rejected", result.stderr)

    def test_direct_stt_overclaim_fails(self):
        data = valid_preflight()
        data["boundaries"]["directSttEnabled"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("boundaries.directSttEnabled", result.stderr)

    def test_prod_gate_requires_audit_rotation_failure_sections(self):
        data = valid_prod_gate()
        del data["rotation"]

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("rotation must be an object", result.stderr)

    def test_raw_certificate_value_fails(self):
        data = valid_preflight()
        data["pki"]["certificatePem"] = "-----BEGIN CERTIFICATE----- fake"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("forbidden_key", result.stderr)

    def test_raw_audio_key_fails(self):
        data = valid_preflight()
        data["rawAudio"] = "base64"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("forbidden_key", result.stderr)

    def test_jwt_shaped_value_fails(self):
        data = valid_preflight()
        data["checks"][0]["summary"] = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJpNyJ9.fakefakefake"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("secret_like_value", result.stderr)

    def test_absolute_evidence_ref_fails(self):
        data = valid_preflight()
        data["checks"][0]["evidenceRef"] = "/tmp/raw.txt"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must stay under protectedEvidencePath", result.stderr)

    def test_summary_json_is_written(self):
        data = valid_preflight()
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
        self.assertEqual("live-stt-preflight", summary["evidenceProfile"])
        self.assertFalse(summary["tokenIncluded"])


if __name__ == "__main__":
    unittest.main()
