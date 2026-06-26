#!/usr/bin/env python3
"""Tests for direct-STT e2e evidence verifier."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify_direct_stt_e2e_evidence.py"


def valid_e2e() -> dict:
    return {
        "schemaVersion": "faz24.directSttE2eEvidence.v1",
        "status": "pass",
        "issue": "platform-ai#182",
        "generatedAt": "2026-06-26T20:30:00Z",
        "failures": [],
        "source": {
            "gitopsCommit": "96767b37a0bd6dd85b58e3510311633a97d3c082",
            "backendImageDigest": "abe1e28cc088008d026534ac6cb0ffdc2d0f9e01d62a50029b256170aac0e6b0",
        },
        "environment": {
            "cluster": "k3d-test",
            "kubectlContext": "k3d-test",
            "namespace": "platform-test",
            "deployment": "audio-gateway",
            "podName": "audio-gateway-769cc7745c-46st4",
        },
        "runtime": {
            "directSttEnabled": True,
            "transcribeHost": "live-stt.denetim",
            "transcribePort": 8243,
            "hostAliasIp": "10.99.0.2",
            "mtlsMountPath": "/etc/direct-stt-mtls",
            "mtlsMountPresent": True,
            "mtlsSecretName": "audio-gateway-direct-stt-mtls",
            "secretValueIncluded": False,
            "mtlsSecretKeyNames": [
                "direct-stt-ca.crt",
                "direct-stt-client.crt",
                "direct-stt-client.key",
            ],
        },
        "mtlsProbe": {
            "fromRealPod": True,
            "clientCertificateUsed": True,
            "healthHttpStatus": 200,
            "totalMs": 423,
        },
        "flow": {
            "sessionId": "31a15790-57eb-4cbe-b923-954c8f6578ac",
            "chunkId": "ce3982b6-0a85-4b56-aecf-de3234af8224",
            "correlationId": "b003d1a4-1428-41ad-a47d-fe374ad1b013",
            "sampleSha256": "076a27c79e5ace2a3d47f9dd2e83e4ff6ea8872b3c2218f66c92b89b55f36560",
            "rawAudioIncluded": False,
            "meetingCreateHttpStatus": 201,
            "chunkUploadHttpStatus": 200,
            "finishHttpStatus": 200,
            "transcribeHttpStatus": 200,
            "resultStreamKey": "transcript:direct-stt-results",
            "resultStreamEntryFound": True,
            "resultStreamRecordId": "1782471276845-0",
            "transcriptTextIncluded": False,
            "transcriptSha256": "7d793037a0760186574b0282f2f435e7e7e27e7a9b0e3025a67f08cd47a4ad58",
            "transcriptCharCount": 42,
        },
        "audit": {
            "streamKey": "audit:events",
            "eventType": "CHUNK_FORWARDED_TO_COMPUTE_PLANE",
            "eventFound": True,
            "recordId": "1782471276846-0",
            "sessionIdMatches": True,
            "chunkIdMatches": True,
            "correlationIdMatches": True,
        },
        "persistence": {
            "redisAudioChunkMetadataOnly": True,
            "rawAudioInRedis": False,
            "rawAudioInResultStream": False,
            "rawAudioInLogs": False,
            "rawTranscriptInEvidence": False,
            "rawTranscriptInLogs": False,
        },
        "boundaries": {
            "directAudioE2eProven": True,
            "directSttTranscriptProven": True,
            "computePlaneAuditProven": True,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "i7ProdGateProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
        },
    }


class DirectSttE2eEvidenceVerifierTest(unittest.TestCase):
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

    def test_valid_e2e_passes(self):
        result = self.run_validator(valid_e2e())

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz 24 direct-STT e2e evidence: PASS", result.stdout)

    def test_wrong_kubectl_context_fails(self):
        data = valid_e2e()
        data["environment"]["kubectlContext"] = "k3d-prod"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("environment_kubectl_context", result.stdout)

    def test_shared_mtls_secret_name_fails(self):
        data = valid_e2e()
        data["runtime"]["mtlsSecretName"] = "audio-gateway-secrets"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("runtime_mtls_secret_name", result.stdout)


if __name__ == "__main__":
    unittest.main()
