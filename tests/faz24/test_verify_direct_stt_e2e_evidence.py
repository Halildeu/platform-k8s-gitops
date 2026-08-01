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
        "tokenIncluded": False,
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
            "podReady": True,
        },
        "runtime": {
            "directSttEnabled": True,
            "selectedProvider": "internal",
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
            "applicable": True,
            "provider": "internal",
            "fromRealPod": True,
            "host": "live-stt.denetim",
            "port": 8243,
            "clientCertificateUsed": True,
            "healthHttpStatus": 200,
            "totalMs": 423,
        },
        "flow": {
            "sttProvider": "internal",
            "sessionId": "SES-31a15790-57eb-4cbe-b923-954c8f6578ac",
            "chunkSeq": 0,
            "correlationId": "faz24-direct-stt-182-test",
            "sampleSha256": "076a27c79e5ace2a3d47f9dd2e83e4ff6ea8872b3c2218f66c92b89b55f36560",
            "rawAudioIncluded": False,
            "meetingCreateHttpStatus": 201,
            "chunkUploadHttpStatus": 200,
            "finishHttpStatus": 200,
            "transcribeHttpStatus": 200,
            "resultStreamKey": "transcript:direct-stt-results",
            "resultStreamEntryFound": True,
            "resultStreamRecordId": "1782471276845-0",
            "resultModel": "faster-whisper-medium",
            "resultDevice": "cuda",
            "transcriptTextIncluded": False,
            "transcriptSha256": "7d793037a0760186574b0282f2f435e7e7e27e7a9b0e3025a67f08cd47a4ad58",
            "transcriptCharCount": 42,
        },
        "audit": {
            "streamKey": "audit:events",
            "evidenceSource": "durable-db",
            "eventType": "CHUNK_FORWARDED_TO_COMPUTE_PLANE",
            "eventFound": True,
            "durableEventFound": True,
            "recordId": "1782471276846-0",
            "sessionIdMatches": True,
            "chunkSeqMatches": True,
            "correlationIdMatches": True,
            "eventTimestampPresent": True,
            "entryHashPresent": True,
            "prevHashPresent": True,
            "entryHashAlgorithm": "SHA-256",
            "entryHashVersion": "1",
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
            "directClientToStt": False,
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

    def test_pod_ready_required(self):
        data = valid_e2e()
        data["environment"]["podReady"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("environment_pod_ready", result.stdout)

    def test_shared_mtls_secret_name_fails(self):
        data = valid_e2e()
        data["runtime"]["mtlsSecretName"] = "audio-gateway-secrets"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("runtime_mtls_secret_name", result.stdout)

    def test_mtls_probe_host_port_are_bound_to_live_stt(self):
        data = valid_e2e()
        data["mtlsProbe"]["host"] = "localhost"
        data["mtlsProbe"]["port"] = 8200

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("mtls_probe_host", result.stdout)
        self.assertIn("mtls_probe_port", result.stdout)

    def test_speechmatics_provider_evidence_passes_without_internal_mtls_probe(self):
        data = valid_e2e()
        data["runtime"]["selectedProvider"] = "speechmatics"
        data["mtlsProbe"] = {
            "applicable": False,
            "provider": "speechmatics",
            "fromRealPod": False,
            "clientCertificateUsed": False,
            "healthHttpStatus": 0,
            "totalMs": 0,
        }
        data["flow"]["sttProvider"] = "speechmatics"
        data["flow"]["resultModel"] = "speechmatics-realtime-v2"
        data["flow"]["resultDevice"] = "speechmatics-saas"

        result = self.run_validator(data)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_speechmatics_result_metadata_mismatch_fails(self):
        data = valid_e2e()
        data["runtime"]["selectedProvider"] = "speechmatics"
        data["mtlsProbe"] = {
            "applicable": False,
            "provider": "speechmatics",
            "fromRealPod": False,
            "clientCertificateUsed": False,
            "healthHttpStatus": 0,
            "totalMs": 0,
        }
        data["flow"]["sttProvider"] = "speechmatics"
        data["flow"]["resultModel"] = "faster-whisper-medium"
        data["flow"]["resultDevice"] = "cuda"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("flow_speechmatics_model", result.stdout)
        self.assertIn("flow_speechmatics_device", result.stdout)

    def test_direct_client_to_stt_overclaim_fails(self):
        data = valid_e2e()
        data["boundaries"]["directClientToStt"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("boundary_directClientToStt", result.stdout)

    def test_correlation_id_rejects_path_like_shape(self):
        data = valid_e2e()
        data["flow"]["correlationId"] = "faz24/direct-stt-182"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("flow_correlation_id", result.stdout)

    def test_camelcase_sensitive_key_is_rejected(self):
        data = valid_e2e()
        data["flow"]["transcriptText"] = "raw transcript must never be attached"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_url_like_value_is_rejected_even_under_safe_key(self):
        data = valid_e2e()
        data["mtlsProbe"]["healthTarget"] = "https://live-stt.denetim:8243/health"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_data_audio_value_is_rejected(self):
        data = valid_e2e()
        data["flow"]["samplePreview"] = "data:audio/wav;base64,QUJDRA=="

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_token_included_flag_must_be_false(self):
        data = valid_e2e()
        data["tokenIncluded"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("token_not_included", result.stdout)

    def test_transient_stream_only_audit_evidence_fails(self):
        data = valid_e2e()
        data["audit"]["evidenceSource"] = "redis-stream"
        data["audit"]["durableEventFound"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("audit_evidence_source", result.stdout)
        self.assertIn("audit_durable_event_found", result.stdout)

    def test_durable_audit_hash_chain_metadata_is_required(self):
        data = valid_e2e()
        data["audit"]["eventTimestampPresent"] = False
        data["audit"]["entryHashPresent"] = False
        data["audit"]["prevHashPresent"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("audit_timestamp_present", result.stdout)
        self.assertIn("audit_entry_hash_present", result.stdout)
        self.assertIn("audit_prev_hash_present", result.stdout)


if __name__ == "__main__":
    unittest.main()
