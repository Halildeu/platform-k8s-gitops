#!/usr/bin/env python3
"""Tests for direct-STT mTLS enablement preflight evidence verifier."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify_direct_stt_mtls_enablement_preflight.py"


def valid_preflight() -> dict:
    return {
        "schemaVersion": "faz24.directSttMtlsEnablementPreflight.v1",
        "status": "pass",
        "issue": "platform-ai#182",
        "generatedAt": "2026-06-26T20:00:00Z",
        "failures": [],
        "source": {
            "gitopsCommit": "8c86093250f8353a86991667a8066f08ce586178",
            "backendImageDigest": "abe1e28cc088008d026534ac6cb0ffdc2d0f9e01d62a50029b256170aac0e6b0",
        },
        "environment": {
            "cluster": "k3d-test",
            "kubectlContext": "k3d-test",
            "namespace": "platform-test",
            "deployment": "audio-gateway",
            "podName": "audio-gateway-769cc7745c-46st4",
            "podReady": True,
            "contextAvailable": True,
            "namespaceReachable": True,
            "contextFailure": "",
        },
        "desiredState": {
            "directSttEnabled": False,
            "transcribeHost": "live-stt.denetim",
            "transcribePort": 8243,
            "hostAliasIp": "10.99.0.2",
            "networkPolicyCidr": "10.99.0.2/32",
            "networkPolicyPort": 8243,
            "mtlsMountPath": "/etc/direct-stt-mtls",
            "mtlsMountPresent": True,
            "mtlsSecretName": "audio-gateway-direct-stt-mtls",
            "mtlsSecretOptional": True,
        },
        "externalSecret": {
            "name": "audio-gateway-direct-stt-mtls",
            "ready": True,
            "secretStore": "vault-platform-gitops",
            "vaultPath": "kv/platform/audio-gateway-service",
            "mappedVaultProperties": [
                "direct_stt_ca_crt",
                "direct_stt_client_crt",
                "direct_stt_client_key",
            ],
            "targetSecretKeys": [
                "direct-stt-ca.crt",
                "direct-stt-client.crt",
                "direct-stt-client.key",
            ],
            "conditions": [
                {
                    "type": "Ready",
                    "status": "True",
                    "reason": "SecretSynced",
                    "lastTransitionTime": "2026-06-29T01:00:00Z",
                    "messagePresent": False,
                    "messageLength": 0,
                    "messageIncluded": False,
                }
            ],
            "secretValueIncluded": False,
        },
        "runtimeSecret": {
            "name": "audio-gateway-direct-stt-mtls",
            "keyNames": [
                "direct-stt-ca.crt",
                "direct-stt-client.crt",
                "direct-stt-client.key",
            ],
            "secretValueIncluded": False,
            "fileLikeKeysNotExportedAsEnv": True,
            "dedicatedSecretNotEnvFrom": True,
        },
        "aggregateSecret": {
            "name": "audio-gateway-secrets",
            "ready": True,
            "targetSecretKeys": ["SPRING_DATA_REDIS_PASSWORD"],
            "runtimeKeyNames": ["SPRING_DATA_REDIS_PASSWORD"],
            "directSttKeysPresent": False,
            "secretValueIncluded": False,
        },
        "mtlsProbe": {
            "fromRealPod": True,
            "host": "live-stt.denetim",
            "port": 8243,
            "clientCertificateUsed": True,
            "healthHttpStatus": 200,
            "totalMs": 412,
            "secretValueIncluded": False,
        },
        "boundaries": {
            "vaultSeedAuthorityAccepted": True,
            "secretValuesIncluded": False,
            "directSttEnabled": False,
            "rawAudioSent": False,
            "transcribeCalled": False,
            "directAudioE2eProven": False,
            "i7ProdGateProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
        },
    }


class DirectSttMtlsEnablementPreflightVerifierTest(unittest.TestCase):
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

    def test_valid_preflight_passes(self):
        result = self.run_validator(valid_preflight())

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz 24 direct-STT mTLS enablement preflight: PASS", result.stdout)

    def test_direct_stt_must_remain_disabled_before_flip(self):
        data = valid_preflight()
        data["desiredState"]["directSttEnabled"] = True
        data["boundaries"]["directSttEnabled"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("desired_direct_stt_disabled", result.stdout)
        self.assertIn("boundary_directSttEnabled", result.stdout)

    def test_missing_runtime_key_fails(self):
        data = valid_preflight()
        data["runtimeSecret"]["keyNames"].remove("direct-stt-client.key")

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("runtime_secret_keys", result.stdout)

    def test_shared_audio_gateway_secret_fails(self):
        data = valid_preflight()
        data["desiredState"]["mtlsSecretName"] = "audio-gateway-secrets"
        data["externalSecret"]["name"] = "audio-gateway-secrets"
        data["runtimeSecret"]["name"] = "audio-gateway-secrets"
        data["runtimeSecret"]["dedicatedSecretNotEnvFrom"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("desired_mtls_secret_name", result.stdout)
        self.assertIn("external_secret_name", result.stdout)
        self.assertIn("runtime_secret_name", result.stdout)
        self.assertIn("runtime_secret_not_env_from", result.stdout)

    def test_direct_stt_key_in_aggregate_secret_fails(self):
        data = valid_preflight()
        data["aggregateSecret"]["targetSecretKeys"].append("direct-stt-client.key")
        data["aggregateSecret"]["runtimeKeyNames"].append("direct-stt-client.key")
        data["aggregateSecret"]["directSttKeysPresent"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("aggregate_secret_no_direct_stt_keys", result.stdout)

    def test_missing_redis_key_in_aggregate_secret_fails(self):
        data = valid_preflight()
        data["aggregateSecret"]["targetSecretKeys"] = []
        data["aggregateSecret"]["runtimeKeyNames"] = []

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("aggregate_secret_target_redis_key", result.stdout)
        self.assertIn("aggregate_secret_runtime_redis_key", result.stdout)

    def test_wrong_kubectl_context_fails(self):
        data = valid_preflight()
        data["environment"]["kubectlContext"] = "k3d-prod"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("environment_kubectl_context", result.stdout)

    def test_missing_kube_context_fails_before_runtime_claim(self):
        data = valid_preflight()
        data["status"] = "fail"
        data["failures"] = ["kubectl-context-k3d-test-missing"]
        data["environment"]["contextAvailable"] = False
        data["environment"]["namespaceReachable"] = False
        data["environment"]["contextFailure"] = "kubectl-context-k3d-test-missing"
        data["environment"]["podName"] = ""
        data["environment"]["podReady"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("environment_context_available", result.stdout)
        self.assertIn("environment_namespace_reachable", result.stdout)
        self.assertIn("environment_context_failure_empty", result.stdout)

    def test_missing_external_secret_property_fails(self):
        data = valid_preflight()
        data["externalSecret"]["mappedVaultProperties"].remove("direct_stt_client_key")

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("external_secret_properties", result.stdout)

    def test_external_secret_raw_condition_message_fails(self):
        data = valid_preflight()
        data["externalSecret"]["conditions"][0]["messageIncluded"] = True
        data["externalSecret"]["conditions"][0]["message"] = "could not read secret property"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("external_secret_conditions_redacted", result.stdout)

    def test_external_secret_unsafe_condition_reason_fails(self):
        data = valid_preflight()
        data["externalSecret"]["conditions"][0]["reason"] = "SecretSynced\nError"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("external_secret_conditions_redacted", result.stdout)

    def test_external_secret_empty_required_condition_metadata_fails(self):
        data = valid_preflight()
        data["externalSecret"]["conditions"][0]["reason"] = ""

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("external_secret_conditions_redacted", result.stdout)

    def test_mtls_probe_must_use_real_pod(self):
        data = valid_preflight()
        data["mtlsProbe"]["fromRealPod"] = False

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("mtls_probe_real_pod", result.stdout)

    def test_secret_material_is_rejected(self):
        data = valid_preflight()
        data["runtimeSecret"]["client_key_pem"] = "-----BEGIN PRIVATE KEY-----\nredacted\n-----END PRIVATE KEY-----"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_camelcase_sensitive_key_is_rejected(self):
        data = valid_preflight()
        data["mtlsProbe"]["destinationUrl"] = "https://live-stt.denetim:8243/health"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_destination_url_key_is_rejected(self):
        data = valid_preflight()
        data["mtlsProbe"]["destination_url"] = "https://live-stt.denetim:8243/health"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_url_like_value_is_rejected_even_under_safe_key(self):
        data = valid_preflight()
        data["mtlsProbe"]["healthTarget"] = "https://live-stt.denetim:8243/health"

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_data_audio_value_is_rejected(self):
        data = valid_preflight()
        data["mtlsProbe"]["samplePreview"] = "data:audio/wav;base64,QUJDRA=="

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_audio_transcribe_overclaim_fails(self):
        data = valid_preflight()
        data["boundaries"]["rawAudioSent"] = True
        data["boundaries"]["transcribeCalled"] = True
        data["boundaries"]["directAudioE2eProven"] = True

        result = self.run_validator(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("boundary_rawAudioSent", result.stdout)
        self.assertIn("boundary_transcribeCalled", result.stdout)
        self.assertIn("boundary_directAudioE2eProven", result.stdout)


if __name__ == "__main__":
    unittest.main()
