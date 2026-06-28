from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "direct_stt_mtls_seed_operator.py"

PEM_DASHES = "-" * 5
CERT_BEGIN = f"{PEM_DASHES}BEGIN CERTIFICATE{PEM_DASHES}"
CERT_END = f"{PEM_DASHES}END CERTIFICATE{PEM_DASHES}"
KEY_BEGIN = f"{PEM_DASHES}BEGIN PRIVATE KEY{PEM_DASHES}"
KEY_END = f"{PEM_DASHES}END PRIVATE KEY{PEM_DASHES}"
CA_PEM = f"{CERT_BEGIN}\nQUJD\n{CERT_END}\n"
CLIENT_CERT_PEM = f"{CERT_BEGIN}\nREVG\n{CERT_END}\n"
CLIENT_KEY_PEM = f"{KEY_BEGIN}\nR0hJ\n{KEY_END}\n"
VAULT_TOKEN = "test-vault-token-123"


def write_private(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)


class VaultPatchHandler(BaseHTTPRequestHandler):
    captured: dict[str, object] = {}

    def do_PATCH(self) -> None:  # noqa: N802 - stdlib callback name
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        VaultPatchHandler.captured = {
            "path": self.path,
            "token": self.headers.get("X-Vault-Token"),
            "contentType": self.headers.get("Content-Type"),
            "body": json.loads(body.decode("utf-8")),
        }
        response = json.dumps({"request_id": "req-test"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *_args: object) -> None:
        return


class DirectSttMtlsSeedOperatorTest(unittest.TestCase):
    def build_args(self, tmpdir: Path, evidence: Path, *, vault_addr: str = "https://vault.test") -> list[str]:
        ca = tmpdir / "ca.crt"
        client_crt = tmpdir / "client.crt"
        client_key = tmpdir / "client.key"
        token = tmpdir / "vault.token"
        write_private(ca, CA_PEM)
        write_private(client_crt, CLIENT_CERT_PEM)
        write_private(client_key, CLIENT_KEY_PEM)
        write_private(token, VAULT_TOKEN)
        return [
            sys.executable,
            str(SCRIPT),
            "--vault-addr",
            vault_addr,
            "--vault-path",
            "kv/platform/audio-gateway-service",
            "--vault-token-file",
            str(token),
            "--ca-crt-file",
            str(ca),
            "--client-crt-file",
            str(client_crt),
            "--client-key-file",
            str(client_key),
            "--evidence-out",
            str(evidence),
        ]

    def test_dry_run_writes_redacted_evidence_without_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            evidence_path = tmpdir / "evidence.json"
            result = subprocess.run(
                self.build_args(tmpdir, evidence_path),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("status=dry-run", result.stdout)
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            rendered = json.dumps(evidence, sort_keys=True)

            self.assertEqual("faz24.directSttMtlsSeedOperatorEvidence.v1", evidence["schemaVersion"])
            self.assertEqual("dry-run", evidence["status"])
            self.assertFalse(evidence["applyRequested"])
            self.assertEqual(
                ["direct_stt_ca_crt", "direct_stt_client_crt", "direct_stt_client_key"],
                evidence["vault"]["properties"],
            )
            self.assertFalse(evidence["boundaries"]["secretValuesIncluded"])
            self.assertFalse(evidence["boundaries"]["vaultTokenIncluded"])
            self.assertFalse(evidence["boundaries"]["localFilePathsIncluded"])
            self.assertNotIn("BEGIN CERTIFICATE", rendered)
            self.assertNotIn("BEGIN PRIVATE KEY", rendered)
            self.assertNotIn(VAULT_TOKEN, rendered)
            self.assertNotIn(str(tmpdir), rendered)

    def test_apply_patches_vault_kv2_without_recording_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            evidence_path = tmpdir / "evidence.json"
            server = HTTPServer(("127.0.0.1", 0), VaultPatchHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                vault_addr = f"http://127.0.0.1:{server.server_port}"
                result = subprocess.run(
                    [*self.build_args(tmpdir, evidence_path, vault_addr=vault_addr), "--apply"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
            finally:
                server.shutdown()
                thread.join(timeout=5)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("status=pass", result.stdout)
            captured = VaultPatchHandler.captured
            self.assertEqual("/v1/kv/data/platform/audio-gateway-service", captured["path"])
            self.assertEqual(VAULT_TOKEN, captured["token"])
            self.assertEqual("application/merge-patch+json", captured["contentType"])
            self.assertEqual(
                {
                    "direct_stt_ca_crt": CA_PEM,
                    "direct_stt_client_crt": CLIENT_CERT_PEM,
                    "direct_stt_client_key": CLIENT_KEY_PEM,
                },
                captured["body"]["data"],
            )

            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            rendered = json.dumps(evidence, sort_keys=True)
            self.assertEqual("pass", evidence["status"])
            self.assertTrue(evidence["applyRequested"])
            self.assertEqual(200, evidence["result"]["httpStatus"])
            self.assertTrue(evidence["result"]["vaultRequestIdPresent"])
            self.assertNotIn("BEGIN CERTIFICATE", rendered)
            self.assertNotIn("BEGIN PRIVATE KEY", rendered)
            self.assertNotIn(VAULT_TOKEN, rendered)
            self.assertNotIn(str(tmpdir), rendered)

    def test_rejects_group_readable_private_key_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            evidence_path = tmpdir / "evidence.json"
            args = self.build_args(tmpdir, evidence_path)
            client_key = tmpdir / "client.key"
            os.chmod(client_key, 0o644)

            result = subprocess.run(
                args,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("client-key-file must not be group/world accessible", result.stderr)


if __name__ == "__main__":
    unittest.main()
