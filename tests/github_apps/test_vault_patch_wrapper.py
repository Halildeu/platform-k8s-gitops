from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts/ops/platform-ops-vault-patch.sh"
TARGET = "/v1/kv/data/platform/cross-ai-deployment-protection-test"


class VaultHandler(BaseHTTPRequestHandler):
    writes: ClassVar[list[dict[str, object]]] = []
    revoked: ClassVar[bool] = False

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
        if self.path == TARGET:
            self._json(404, {"errors": []})
            return
        self._json(404, {"errors": ["not found"]})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/auth/approle/login":
            self._body()
            self._json(200, {"auth": {"client_token": "fixture-client-token"}})
            return
        if self.path == "/v1/sys/capabilities-self":
            self._body()
            self._json(200, {"capabilities": ["create", "read", "update"]})
            return
        if self.path == TARGET:
            self.writes.append(self._body())
            self._json(200, {"data": {"version": 1}})
            return
        if self.path == "/v1/auth/token/revoke-self":
            type(self).revoked = True
            self.send_response(204)
            self.end_headers()
            return
        self._json(404, {"errors": ["not found"]})


class VaultPatchWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        VaultHandler.writes = []
        VaultHandler.revoked = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), VaultHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_first_seed_is_stdin_only_cas_guarded_and_cleans_credentials(self) -> None:
        webhook_secret = "synthetic-webhook-secret-for-test-only-0001"
        with tempfile.TemporaryDirectory() as directory:
            secret_id_file = Path(directory) / "secret-id"
            secret_id_file.write_text("fixture-secret-id", encoding="utf-8")
            secret_id_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
            env = os.environ.copy()
            env.update(
                {
                    "VAULT_BOOTSTRAP_ROLE_ID": "fixture-role-id",
                    "VAULT_BOOTSTRAP_SECRET_ID_FILE": str(secret_id_file),
                }
            )
            result = subprocess.run(
                [
                    str(WRAPPER),
                    "--vault-addr",
                    f"http://127.0.0.1:{self.server.server_port}",
                    "--service",
                    "cross-ai-deployment-protection-test",
                    "--field-from-stdin",
                    "github_webhook_secret_current",
                    "--cleanup-secret-id-file",
                ],
                input=webhook_secret + "\n",
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "1")
            self.assertNotIn(webhook_secret, result.stdout + result.stderr)
            self.assertFalse(secret_id_file.exists())

        self.assertEqual(
            VaultHandler.writes,
            [
                {
                    "options": {"cas": 0},
                    "data": {"github_webhook_secret_current": webhook_secret},
                }
            ],
        )
        self.assertTrue(VaultHandler.revoked)

    def test_cross_ai_path_rejects_arbitrary_property(self) -> None:
        result = subprocess.run(
            [
                str(WRAPPER),
                "--service",
                "cross-ai-deployment-protection-test",
                "--field-from-stdin",
                "unexpected_key",
            ],
            input="synthetic-value\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "accepts only --field-from-stdin github_webhook_secret_current",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
