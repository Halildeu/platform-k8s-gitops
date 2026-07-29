from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import yaml


ROOT = Path(__file__).resolve().parents[2]
VAULT_PATH = "kv/platform/meeting-analysis-capability"
VAULT_API_PATH = f"/v1/kv/data/platform/{VAULT_PATH.rsplit('/', 1)[-1]}"
VAULT_PROPERTY = "hmac_secret_base64"
ENV_KEY = "ANALYSIS_JOB_CAPABILITY_HMAC_SECRET"
WRAPPER = ROOT / "scripts/ops/platform-ops-vault-patch.sh"


def policy_capabilities(path: Path, vault_api_path: str) -> set[str]:
    source = path.read_text(encoding="utf-8")
    match = re.search(
        rf'path "{re.escape(vault_api_path)}"\s*\{{\s*'
        r'capabilities\s*=\s*\[([^\]]+)\]\s*\}',
        source,
    )
    if match is None:
        raise AssertionError(f"missing exact policy block for {vault_api_path}")
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def external_secret_binding(path: Path) -> dict[str, str]:
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    matches = [
        item
        for item in manifest["spec"]["data"]
        if item.get("secretKey") == ENV_KEY
    ]
    if len(matches) != 1:
        raise AssertionError(f"{path} must contain one {ENV_KEY} binding")
    binding = matches[0]
    if set(binding) != {"secretKey", "remoteRef"}:
        raise AssertionError(f"{path} capability binding may only use remoteRef")
    return binding["remoteRef"]


class VaultHandler(BaseHTTPRequestHandler):
    writes: ClassVar[list[dict[str, object]]] = []
    revoked: ClassVar[bool] = False
    existing_data: ClassVar[dict[str, object] | None] = None
    existing_version: ClassVar[int] = 0
    force_cas_conflict: ClassVar[bool] = False

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _json(self, status: int, value: dict[str, object]) -> None:
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == VAULT_API_PATH:
            if type(self).existing_data is None:
                self._json(404, {"errors": []})
            else:
                self._json(
                    200,
                    {
                        "data": {
                            "data": type(self).existing_data,
                            "metadata": {"version": type(self).existing_version},
                        }
                    },
                )
            return
        self._json(404, {"errors": ["not found"]})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/auth/approle/login":
            self._body()
            self._json(200, {"auth": {"client_token": "fixture-token"}})
            return
        if self.path == "/v1/sys/capabilities-self":
            self._body()
            self._json(200, {"capabilities": ["create", "read", "update"]})
            return
        if self.path == VAULT_API_PATH:
            if type(self).force_cas_conflict:
                self._json(400, {"errors": ["check-and-set parameter did not match"]})
                return
            body = self._body()
            type(self).writes.append(body)
            type(self).existing_data = body["data"]
            type(self).existing_version += 1
            self._json(200, {"data": {"version": type(self).existing_version}})
            return
        if self.path == "/v1/auth/token/revoke-self":
            type(self).revoked = True
            self.send_response(204)
            self.end_headers()
            return
        self._json(404, {"errors": ["not found"]})


class AnalysisCapabilitySecretContractTests(unittest.TestCase):
    def test_both_external_secrets_read_one_shared_remote_property(self) -> None:
        meeting_path = (
            ROOT
            / "kustomize/overlays/test/eso/meeting-service/"
            "analysis-capability-externalsecret.yaml"
        )
        transcript_path = (
            ROOT
            / "kustomize/overlays/test/eso/transcript-service/"
            "analysis-capability-externalsecret.yaml"
        )
        meeting = external_secret_binding(meeting_path)
        transcript = external_secret_binding(transcript_path)
        expected = {"key": VAULT_PATH, "property": VAULT_PROPERTY}
        self.assertEqual(meeting, expected)
        self.assertEqual(transcript, expected)
        self.assertEqual(
            yaml.safe_load(meeting_path.read_text(encoding="utf-8"))["spec"]["target"][
                "name"
            ],
            "meeting-service-analysis-capability",
        )
        self.assertEqual(
            yaml.safe_load(transcript_path.read_text(encoding="utf-8"))["spec"][
                "target"
            ]["name"],
            "transcript-service-analysis-capability",
        )
        for path in (
            ROOT
            / "kustomize/overlays/test/eso/meeting-service/externalsecret.yaml",
            ROOT
            / "kustomize/overlays/test/eso/transcript-service/externalsecret.yaml",
        ):
            self.assertNotIn(ENV_KEY, path.read_text(encoding="utf-8"))

    def test_vault_policies_keep_runtime_read_only_and_writer_delete_free(self) -> None:
        api_path = "kv/data/platform/meeting-analysis-capability"
        runtime = policy_capabilities(
            ROOT / "bootstrap/vault-policies/test/eso-runtime-extras.hcl",
            api_path,
        )
        writer = policy_capabilities(
            ROOT
            / "bootstrap/vault-policies/test/meeting-analysis-capability-writer.hcl",
            api_path,
        )
        self.assertEqual(runtime, {"read"})
        self.assertEqual(writer, {"create", "update", "read"})
        self.assertNotIn("delete", writer)

        common_runtime = (
            ROOT / "bootstrap/vault-policies/common/eso-runtime.hcl"
        ).read_text(encoding="utf-8")
        common_writer = (
            ROOT / "bootstrap/vault-policies/common/bootstrap-writer.hcl"
        ).read_text(encoding="utf-8")
        self.assertNotIn(api_path, common_runtime)
        self.assertNotIn(api_path, common_writer)

        reconciler = (
            ROOT / "scripts/ops/vault-policy-reconcile.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "test/meeting-analysis-capability-writer.hcl|"
            "meeting-analysis-capability-writer-test",
            reconciler,
        )
        self.assertIn(
            "platform-bootstrap-writer,"
            "meeting-analysis-capability-writer-test",
            reconciler,
        )
        reconciler_policy = (
            ROOT / "bootstrap/vault-policies/test/vault-config-reconciler.hcl"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'path "sys/policies/acl/'
            'meeting-analysis-capability-writer-test"',
            reconciler_policy,
        )

    def run_writer(
        self,
        *,
        synthetic_secret: str,
        existing_data: dict[str, object] | None,
        existing_version: int,
        create_only: bool = False,
        force_cas_conflict: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        VaultHandler.writes = []
        VaultHandler.revoked = False
        VaultHandler.existing_data = existing_data
        VaultHandler.existing_version = existing_version
        VaultHandler.force_cas_conflict = force_cas_conflict
        server = ThreadingHTTPServer(("127.0.0.1", 0), VaultHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            command = [
                "/bin/bash",
                str(WRAPPER),
                "--vault-addr",
                f"http://127.0.0.1:{server.server_port}",
                "--service",
                "meeting-analysis-capability",
                "--field-from-stdin",
                VAULT_PROPERTY,
            ]
            if create_only:
                command.append("--create-only")
            result = subprocess.run(
                command,
                input=synthetic_secret + "\n",
                text=True,
                capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "VAULT_BOOTSTRAP_ROLE_ID": "fixture-role-id",
                    "VAULT_BOOTSTRAP_SECRET_ID": "fixture-secret-id",
                },
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        return result

    def test_writer_accepts_only_exact_stdin_property_and_redacts_value(self) -> None:
        synthetic_secret = base64.b64encode(b"a" * 32).decode()
        result = self.run_writer(
            synthetic_secret=synthetic_secret,
            existing_data=None,
            existing_version=0,
            create_only=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(synthetic_secret, result.stdout + result.stderr)
        self.assertEqual(
            VaultHandler.writes,
            [
                {
                    "options": {"cas": 0},
                    "data": {VAULT_PROPERTY: synthetic_secret},
                }
            ],
        )
        self.assertTrue(VaultHandler.revoked)

    def test_create_only_refuses_existing_capability_without_writing(self) -> None:
        old_secret = "old-value"
        result = self.run_writer(
            synthetic_secret=base64.b64encode(b"n" * 32).decode(),
            existing_data={VAULT_PROPERTY: old_secret},
            existing_version=4,
            create_only=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--create-only refused existing KV path", result.stderr)
        self.assertNotIn(old_secret, result.stdout + result.stderr)
        self.assertEqual(VaultHandler.writes, [])
        self.assertTrue(VaultHandler.revoked)

    def test_create_only_concurrent_create_fails_closed(self) -> None:
        synthetic_secret = base64.b64encode(b"a" * 32).decode()
        result = self.run_writer(
            synthetic_secret=synthetic_secret,
            existing_data=None,
            existing_version=0,
            create_only=True,
            force_cas_conflict=True,
        )
        self.assertEqual(result.returncode, 5)
        self.assertIn("possible CAS conflict", result.stderr)
        self.assertNotIn(synthetic_secret, result.stdout + result.stderr)
        self.assertEqual(VaultHandler.writes, [])
        self.assertTrue(VaultHandler.revoked)

    def test_writer_rejects_invalid_or_weak_hmac_material(self) -> None:
        for value in ("not-base64", "c2hvcnQ="):
            with self.subTest(value=value):
                result = self.run_writer(
                    synthetic_secret=value,
                    existing_data=None,
                    existing_version=0,
                    create_only=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(
                    "hmac_secret_base64 must encode exactly 32 bytes",
                    result.stderr,
                )
                self.assertNotIn(value, result.stdout + result.stderr)
                self.assertEqual(VaultHandler.writes, [])
                self.assertFalse(VaultHandler.revoked)

    def test_writer_rejects_unexpected_property(self) -> None:
        rejected = subprocess.run(
            [
                "/bin/bash",
                str(WRAPPER),
                "--service",
                "meeting-analysis-capability",
            "--field-from-stdin",
            "unexpected_property",
            "--create-only",
            ],
            input="synthetic\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn(
            "accepts only create-only hmac_secret_base64 from stdin",
            rejected.stderr,
        )

    def test_writer_rejects_capability_write_without_create_only(self) -> None:
        rejected = subprocess.run(
            [
                "/bin/bash",
                str(WRAPPER),
                "--service",
                "meeting-analysis-capability",
                "--field-from-stdin",
                VAULT_PROPERTY,
            ],
            input="synthetic\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn(
            "accepts only create-only hmac_secret_base64 from stdin",
            rejected.stderr,
        )

    def test_writer_rejects_canonical_prod_vault_for_test_capability(self) -> None:
        rejected = subprocess.run(
            [
                "/bin/bash",
                str(WRAPPER),
                "--vault-addr",
                "http://127.0.0.1:8200",
                "--service",
                "meeting-analysis-capability",
                "--field-from-stdin",
                VAULT_PROPERTY,
                "--create-only",
            ],
            input=base64.b64encode(b"a" * 32).decode() + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn(
            "TEST-only and refuses the canonical PROD Vault address",
            rejected.stderr,
        )


if __name__ == "__main__":
    unittest.main()
