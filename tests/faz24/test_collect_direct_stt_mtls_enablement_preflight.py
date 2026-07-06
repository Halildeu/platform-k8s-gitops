#!/usr/bin/env python3
"""Tests for the direct-STT mTLS preflight metadata collector."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTOR_PATH = (
    REPO_ROOT
    / "scripts"
    / "faz24"
    / "collect_direct_stt_mtls_enablement_preflight.py"
)
VERIFIER_PATH = (
    REPO_ROOT / "scripts" / "faz24" / "verify_direct_stt_mtls_enablement_preflight.py"
)

spec = importlib.util.spec_from_file_location("collect_direct_stt_mtls", COLLECTOR_PATH)
collector = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)


IMAGE_ID = (
    "docker-pullable://ghcr.io/halildeu/platform-backend-audio-gateway-service@"
    "sha256:abe1e28cc088008d026534ac6cb0ffdc2d0f9e01d62a50029b256170aac0e6b0"
)


class FakeRunner:
    def __init__(
        self,
        *,
        missing_context: bool = False,
        namespace_reachable: bool = True,
        missing_secret_key: bool = False,
        external_secret_ready: bool = True,
        external_secret_reason: str = "SecretSynced",
        external_secret_message: str = "",
        mtls_status: int = 200,
        vault_path: str = "kv/platform/audio-gateway-service",
        git_sha: str | None = "91a743542cdaf6996dea6d055cf08252e9122e59",
    ):
        self.missing_context = missing_context
        self.namespace_reachable = namespace_reachable
        self.missing_secret_key = missing_secret_key
        self.external_secret_ready = external_secret_ready
        self.external_secret_reason = external_secret_reason
        self.external_secret_message = external_secret_message
        self.mtls_status = mtls_status
        self.vault_path = vault_path
        self.git_sha = git_sha
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: int = 30):
        self.commands.append(argv)
        if argv == ["git", "rev-parse", "HEAD"]:
            if self.git_sha is None:
                return collector.CommandResult(128, "", "not-a-git-repo")
            return collector.CommandResult(0, self.git_sha + "\n", "")
        if len(argv) == 6 and argv[:3] == ["kubectl", "config", "get-contexts"]:
            context = argv[3]
            if self.missing_context:
                return collector.CommandResult(1, "", f"context {context} not found")
            return collector.CommandResult(0, context + "\n", "")
        if (
            len(argv) >= 8
            and argv[:4] == ["kubectl", "--context", argv[2], "get"]
            and argv[4] == "namespace"
        ):
            if not self.namespace_reachable:
                return collector.CommandResult(1, "", "namespace not found")
            return self._json({"metadata": {"name": argv[5]}})
        if argv[:7] == [
            "kubectl",
            "--context",
            "k3d-test",
            "-n",
            "platform-test",
            "get",
            "secret",
        ]:
            secret_name = argv[7] if len(argv) > 7 else ""
            if secret_name == "audio-gateway-direct-stt-mtls":
                keys = [
                    "direct-stt-ca.crt",
                    "direct-stt-client.crt",
                    "direct-stt-client.key",
                ]
                if self.missing_secret_key:
                    keys.remove("direct-stt-client.key")
                return collector.CommandResult(0, "\n".join(keys) + "\n", "")
            if secret_name == "audio-gateway-secrets":
                return collector.CommandResult(0, "SPRING_DATA_REDIS_PASSWORD\n", "")
        if argv[:6] == ["kubectl", "--context", "k3d-test", "-n", "platform-test", "get"]:
            return self._kubectl_get(argv)
        if argv[:6] == ["kubectl", "--context", "k3d-test", "-n", "platform-test", "exec"]:
            return collector.CommandResult(0, f"{self.mtls_status:03d} 0.412", "")
        return collector.CommandResult(127, "", "unexpected-command")

    def _kubectl_get(self, argv: list[str]):
        kind = argv[6]
        name = argv[7] if len(argv) > 9 and argv[7] != "-o" else ""
        if kind == "deployment" and name == "audio-gateway":
            return self._json(deployment())
        if kind == "configmap" and name == "audio-gateway-config":
            return self._json(configmap())
        if kind == "externalsecret" and name == "audio-gateway-direct-stt-mtls":
            return self._json(
                external_secret(
                    self.vault_path,
                    ready=self.external_secret_ready,
                    reason=self.external_secret_reason,
                    message=self.external_secret_message,
                )
            )
        if kind == "externalsecret" and name == "audio-gateway-secrets":
            return self._json(aggregate_external_secret())
        if kind == "networkpolicy" and name == "allow-audio-gateway-egress-live-stt-mtls":
            return self._json(network_policy())
        if kind == "pods":
            return self._json(pods())
        return collector.CommandResult(127, "", f"unexpected-get-{kind}-{name}")

    def _json(self, data: dict):
        return collector.CommandResult(0, json.dumps(data), "")


def deployment() -> dict:
    return {
        "spec": {
            "template": {
                "spec": {
                    "hostAliases": [
                        {"ip": "10.99.0.2", "hostnames": ["live-stt.denetim"]}
                    ],
                    "containers": [
                        {
                            "name": "audio-gateway",
                            "envFrom": [
                                {"configMapRef": {"name": "audio-gateway-config"}},
                                {"secretRef": {"name": "audio-gateway-secrets"}},
                            ],
                            "volumeMounts": [
                                {
                                    "name": "direct-stt-mtls",
                                    "mountPath": "/etc/direct-stt-mtls",
                                    "readOnly": True,
                                }
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "direct-stt-mtls",
                            "secret": {
                                "secretName": "audio-gateway-direct-stt-mtls",
                                "optional": True,
                            },
                        }
                    ],
                }
            }
        }
    }


def configmap() -> dict:
    return {"data": {"AUDIO_GATEWAY_DIRECT_STT_ENABLED": "false"}}


def external_secret(
    vault_path: str,
    *,
    ready: bool = True,
    reason: str = "SecretSynced",
    message: str = "",
) -> dict:
    return {
        "spec": {
            "secretStoreRef": {"name": "vault-platform-gitops"},
            "data": [
                {
                    "secretKey": "direct-stt-ca.crt",
                    "remoteRef": {
                        "key": vault_path,
                        "property": "direct_stt_ca_crt",
                    },
                },
                {
                    "secretKey": "direct-stt-client.crt",
                    "remoteRef": {
                        "key": vault_path,
                        "property": "direct_stt_client_crt",
                    },
                },
                {
                    "secretKey": "direct-stt-client.key",
                    "remoteRef": {
                        "key": vault_path,
                        "property": "direct_stt_client_key",
                    },
                },
            ],
        },
        "status": {
            "conditions": [
                {
                    "type": "Ready",
                    "status": "True" if ready else "False",
                    "reason": reason,
                    "message": message,
                    "lastTransitionTime": "2026-06-29T01:00:00Z",
                }
            ]
        },
    }


def aggregate_external_secret() -> dict:
    return {
        "spec": {
            "secretStoreRef": {"name": "vault-platform-gitops"},
            "data": [
                {
                    "secretKey": "SPRING_DATA_REDIS_PASSWORD",
                    "remoteRef": {
                        "key": "kv/platform/audio-gateway-service",
                        "property": "redis_password",
                    },
                },
            ],
        },
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }


def network_policy() -> dict:
    return {
        "spec": {
            "egress": [
                {
                    "to": [{"ipBlock": {"cidr": "10.99.0.2/32"}}],
                    "ports": [{"protocol": "TCP", "port": 8243}],
                }
            ]
        }
    }


def pods() -> dict:
    return {
        "items": [
            {
                "metadata": {
                    "name": "audio-gateway-69d4f9d494-lzsgf",
                    "creationTimestamp": "2026-06-26T21:00:00Z",
                    "labels": {"app.kubernetes.io/name": "audio-gateway"},
                },
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": "audio-gateway",
                            "ready": True,
                            "imageID": IMAGE_ID,
                        }
                    ],
                },
            }
        ]
    }


class DirectSttMtlsPreflightCollectorTest(unittest.TestCase):
    def run_verifier(self, data: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            return subprocess.run(
                [sys.executable, str(VERIFIER_PATH), tmp.name],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_successful_collection_passes_existing_verifier(self):
        runner = FakeRunner()

        evidence = collector.build_evidence(runner=runner)

        self.assertEqual("pass", evidence["status"])
        self.assertEqual([], evidence["failures"])
        self.assertFalse(evidence["runtimeSecret"]["secretValueIncluded"])
        self.assertEqual(
            [
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
            evidence["externalSecret"]["conditions"],
        )
        self.assertEqual(
            {
                "direct-stt-ca.crt",
                "direct-stt-client.crt",
                "direct-stt-client.key",
            },
            set(evidence["runtimeSecret"]["keyNames"]),
        )
        self.assertEqual(
            "audio-gateway-direct-stt-mtls",
            evidence["desiredState"]["mtlsSecretName"],
        )
        self.assertTrue(evidence["desiredState"]["mtlsSecretOptional"])
        self.assertTrue(evidence["runtimeSecret"]["dedicatedSecretNotEnvFrom"])
        self.assertEqual("audio-gateway-secrets", evidence["aggregateSecret"]["name"])
        self.assertEqual(
            ["SPRING_DATA_REDIS_PASSWORD"],
            evidence["aggregateSecret"]["targetSecretKeys"],
        )
        self.assertEqual(
            ["SPRING_DATA_REDIS_PASSWORD"],
            evidence["aggregateSecret"]["runtimeKeyNames"],
        )
        self.assertFalse(evidence["aggregateSecret"]["directSttKeysPresent"])
        runtime_kubectl_commands = [
            command
            for command in runner.commands
            if command and command[0] == "kubectl" and command[1] != "config"
        ]
        self.assertTrue(all("--context" in command for command in runtime_kubectl_commands))
        exec_commands = [command for command in runner.commands if "exec" in command]
        self.assertEqual(1, len(exec_commands))
        self.assertIn("curl -sS", exec_commands[0][-1])
        self.assertNotIn("curl -skS", exec_commands[0][-1])
        self.assertTrue(evidence["environment"]["contextAvailable"])
        self.assertTrue(evidence["environment"]["namespaceReachable"])
        self.assertEqual("", evidence["environment"]["contextFailure"])

        result = self.run_verifier(evidence)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Faz 24 direct-STT mTLS enablement preflight: PASS", result.stdout)

    def test_missing_runtime_secret_key_fails_without_leaking_values(self):
        evidence = collector.build_evidence(runner=FakeRunner(missing_secret_key=True))
        serialized = json.dumps(evidence)

        self.assertEqual("fail", evidence["status"])
        self.assertIn("runtime-secret-key-missing", evidence["failures"])
        self.assertNotIn("BEGIN CERTIFICATE", serialized)
        self.assertNotIn("Bearer ", serialized)
        self.assertNotIn("PRIVATE KEY", serialized)

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("status_pass", result.stdout)

    def test_external_secret_synced_error_records_redacted_condition_metadata(self):
        message = (
            "could not get secret data from provider: missing property "
            "direct_stt_client_key at kv/platform/audio-gateway-service"
        )
        evidence = collector.build_evidence(
            runner=FakeRunner(
                external_secret_ready=False,
                external_secret_reason="SecretSyncedError",
                external_secret_message=message,
                missing_secret_key=True,
                mtls_status=000,
            )
        )
        serialized = json.dumps(evidence)

        self.assertEqual("fail", evidence["status"])
        self.assertIn("external-secret-not-ready", evidence["failures"])
        self.assertEqual("SecretSyncedError", evidence["externalSecret"]["conditions"][0]["reason"])
        self.assertTrue(evidence["externalSecret"]["conditions"][0]["messagePresent"])
        self.assertEqual(len(message), evidence["externalSecret"]["conditions"][0]["messageLength"])
        self.assertFalse(evidence["externalSecret"]["conditions"][0]["messageIncluded"])
        self.assertNotIn(message, serialized)
        self.assertNotIn("direct_stt_client_key at", serialized)

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("external_secret_ready", result.stdout)
        self.assertIn("external_secret_conditions_redacted", result.stdout)

    def test_non_200_mtls_probe_fails(self):
        evidence = collector.build_evidence(runner=FakeRunner(mtls_status=000))

        self.assertEqual("fail", evidence["status"])
        self.assertIn("mtls-health-not-200", evidence["failures"])
        self.assertEqual(0, evidence["mtlsProbe"]["healthHttpStatus"])

    def test_wrong_external_secret_vault_path_fails(self):
        evidence = collector.build_evidence(
            runner=FakeRunner(vault_path="kv/platform/wrong-service")
        )

        self.assertEqual("fail", evidence["status"])
        self.assertIn("external-secret-vault-path-mismatch", evidence["failures"])
        self.assertEqual("kv/platform/wrong-service", evidence["externalSecret"]["vaultPath"])

    def test_missing_git_sha_fails_without_pass_claim(self):
        evidence = collector.build_evidence(runner=FakeRunner(git_sha=None))

        self.assertEqual("fail", evidence["status"])
        self.assertIn("source-gitops-commit-invalid", evidence["failures"])
        self.assertEqual("", evidence["source"]["gitopsCommit"])

    def test_context_override_is_reflected_in_environment_metadata(self):
        evidence = collector.build_evidence(runner=FakeRunner(), context="k3d-prod")

        self.assertEqual("k3d-prod", evidence["environment"]["cluster"])
        self.assertEqual("k3d-prod", evidence["environment"]["kubectlContext"])
        self.assertEqual("fail", evidence["status"])

    def test_missing_kube_context_short_circuits_runtime_reads(self):
        runner = FakeRunner(missing_context=True)

        evidence = collector.build_evidence(runner=runner)

        self.assertEqual("fail", evidence["status"])
        self.assertFalse(evidence["environment"]["contextAvailable"])
        self.assertFalse(evidence["environment"]["namespaceReachable"])
        self.assertEqual(
            "kubectl-context-k3d-test-missing",
            evidence["environment"]["contextFailure"],
        )
        self.assertEqual(["kubectl-context-k3d-test-missing"], evidence["failures"])
        runtime_kubectl_commands = [
            command
            for command in runner.commands
            if command and command[0] == "kubectl" and command[1] != "config"
        ]
        self.assertEqual([], runtime_kubectl_commands)

    def test_unreachable_namespace_short_circuits_runtime_reads(self):
        runner = FakeRunner(namespace_reachable=False)

        evidence = collector.build_evidence(runner=runner)

        self.assertEqual("fail", evidence["status"])
        self.assertTrue(evidence["environment"]["contextAvailable"])
        self.assertFalse(evidence["environment"]["namespaceReachable"])
        self.assertEqual(
            "kubectl-namespace-platform-test:command-exit-1",
            evidence["environment"]["contextFailure"],
        )
        self.assertEqual(["kubectl-namespace-platform-test:command-exit-1"], evidence["failures"])
        runtime_kubectl_commands = [
            command
            for command in runner.commands
            if command and command[0] == "kubectl" and command[1] != "config"
        ]
        self.assertEqual(
            [["kubectl", "--context", "k3d-test", "get", "namespace", "platform-test", "-o", "json"]],
            runtime_kubectl_commands,
        )


if __name__ == "__main__":
    unittest.main()
