from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify_direct_stt_mtls_seed_operator_evidence.py"


def valid_evidence() -> dict[str, object]:
    return {
        "schemaVersion": "faz24.directSttMtlsSeedOperatorEvidence.v1",
        "generatedAt": "2026-06-28T10:00:00Z",
        "status": "pass",
        "failureReason": None,
        "operation": "vault-kv-v2-merge-patch",
        "applyRequested": True,
        "vault": {
            "addrIncluded": False,
            "path": "kv/platform/audio-gateway-service",
            "properties": [
                "direct_stt_ca_crt",
                "direct_stt_client_crt",
                "direct_stt_client_key",
            ],
            "tokenIncluded": False,
            "tokenSource": "file",
        },
        "inputFiles": {
            "caCrt": {
                "label": "ca-crt-file",
                "provided": True,
                "contentKind": "certificate",
                "formatAccepted": True,
                "permissionsRestricted": True,
                "pathIncluded": False,
                "valueIncluded": False,
            },
            "clientCrt": {
                "label": "client-crt-file",
                "provided": True,
                "contentKind": "certificate",
                "formatAccepted": True,
                "permissionsRestricted": True,
                "pathIncluded": False,
                "valueIncluded": False,
            },
            "clientKey": {
                "label": "client-key-file",
                "provided": True,
                "contentKind": "private-key",
                "formatAccepted": True,
                "permissionsRestricted": True,
                "pathIncluded": False,
                "valueIncluded": False,
            },
        },
        "result": {
            "httpStatus": 200,
            "vaultRequestIdPresent": True,
            "errorClass": "",
        },
        "boundaries": {
            "secretValuesIncluded": False,
            "vaultTokenIncluded": False,
            "localFilePathsIncluded": False,
            "rawCommandOutputIncluded": False,
            "kubernetesMutation": False,
            "directSttEnabled": False,
            "transcribeCalled": False,
            "rawAudioSent": False,
            "productionMutation": False,
        },
        "nextVerification": [
            "force ESO refresh or wait for refreshInterval",
            "verify ExternalSecret/audio-gateway-direct-stt-mtls Ready=True",
            "verify Secret/audio-gateway-direct-stt-mtls exposes expected key names only",
            "rerun faz24-direct-stt-mtls-preflight-collect.yml before any flag flip",
        ],
    }


class VerifyDirectSttMtlsSeedOperatorEvidenceTest(unittest.TestCase):
    def run_verifier(self, evidence: dict[str, object]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            evidence_path = tmpdir / "seed-evidence.json"
            summary_path = tmpdir / "summary.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(evidence_path),
                    "--summary-json",
                    str(summary_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            if summary_path.exists():
                result.summary = json.loads(summary_path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
            return result

    def mutate(self, path: tuple[str, ...], value: object) -> dict[str, object]:
        evidence = copy.deepcopy(valid_evidence())
        target: object = evidence
        for key in path[:-1]:
            assert isinstance(target, dict)
            target = target[key]
        assert isinstance(target, dict)
        target[path[-1]] = value
        return evidence

    def test_accepts_applied_redacted_seed_evidence(self):
        result = self.run_verifier(valid_evidence())

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz 24 direct-STT mTLS seed operator evidence: PASS", result.stdout)
        self.assertEqual("pass", result.summary["status"])  # type: ignore[attr-defined]

    def test_rejects_dry_run_evidence(self):
        evidence = self.mutate(("status",), "dry-run")
        evidence["applyRequested"] = False

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("status_pass", result.stdout)
        self.assertEqual("fail", result.summary["status"])  # type: ignore[attr-defined]

    def test_rejects_failed_seed_evidence(self):
        evidence = self.mutate(("status",), "fail")
        evidence["failureReason"] = "vault-http-error"

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("failure_reason_empty", result.stdout)

    def test_rejects_vault_token_presence_claim(self):
        evidence = self.mutate(("vault", "tokenIncluded"), True)

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("vault_token_absent", result.stdout)

    def test_rejects_raw_pem_like_values(self):
        evidence = self.mutate(
            ("inputFiles", "caCrt", "diagnostic"),
            f"{'-' * 5}BEGIN CERTIFICATE{'-' * 5}",
        )

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_rejects_local_path_leakage(self):
        evidence = self.mutate(("inputFiles", "clientKey", "debugPath"), "/secure/direct-stt-client.key")

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("no_sensitive_content", result.stdout)

    def test_rejects_missing_required_property(self):
        evidence = copy.deepcopy(valid_evidence())
        assert isinstance(evidence["vault"], dict)
        evidence["vault"]["properties"] = ["direct_stt_ca_crt", "direct_stt_client_crt"]

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("vault_properties", result.stdout)

    def test_rejects_unrestricted_client_key_file(self):
        evidence = self.mutate(("inputFiles", "clientKey", "permissionsRestricted"), False)

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("input_clientKey_permissions", result.stdout)

    def test_rejects_non_2xx_vault_result(self):
        evidence = self.mutate(("result", "httpStatus"), 403)
        assert isinstance(evidence["result"], dict)
        evidence["result"]["errorClass"] = "vault-http-error"

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("result_http_status", result.stdout)
        self.assertIn("result_error_empty", result.stdout)

    def test_rejects_runtime_mutation_claims(self):
        evidence = self.mutate(("boundaries", "kubernetesMutation"), True)
        assert isinstance(evidence["boundaries"], dict)
        evidence["boundaries"]["directSttEnabled"] = True

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("boundary_kubernetesMutation", result.stdout)
        self.assertIn("boundary_directSttEnabled", result.stdout)


if __name__ == "__main__":
    unittest.main()
