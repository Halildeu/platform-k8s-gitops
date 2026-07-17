from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.ledger import ObserveLedger
from scripts.github_apps.cross_ai_deployment_policy.server import ObserveService, make_server
from scripts.ops.cross_ai_observer_probe import (
    ProbeConfig,
    ProbeError,
    run_probe,
)
from tests.github_apps.test_cross_ai_deployment_webhook import TEST_HMAC_KEY


class ObserverProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.secret_file = root / "webhook-secret"
        self.secret_file.write_bytes(TEST_HMAC_KEY)
        self.ledger = ObserveLedger(root / "ledger.sqlite3")
        self.service = ObserveService(secrets=(TEST_HMAC_KEY,), ledger=self.ledger)
        self.server = make_server("127.0.0.1", 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.config = ProbeConfig(
            url=f"http://{host}:{port}/webhooks/github",
            repository_id=1211415632,
            repository="Halildeu/platform-k8s-gitops",
            installation_id=147158710,
            sender_id=186576227,
            environment="faz22-view-only-pilot",
            head_sha="0123456789abcdef0123456789abcdef01234567",
            run_id=987654321,
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.service.stop()
        self.ledger.close()
        self.directory.cleanup()

    def test_signed_delivery_and_duplicate_are_observed_once(self) -> None:
        result = run_probe(
            config=self.config,
            secret_file=self.secret_file,
            request_id="30000000-0000-4000-8000-000000000001",
            delivery_id="11111111-2222-4333-8444-555555555555",
        )
        self.service.queue.join()
        self.assertTrue(result["accepted"])
        self.assertFalse(result["first"]["duplicate"])
        self.assertTrue(result["second"]["duplicate"])
        self.assertEqual(result["secretBytes"], len(TEST_HMAC_KEY))
        self.assertEqual(self.ledger.counts(), (1, 1))

    def test_non_loopback_plain_http_is_rejected_before_secret_use(self) -> None:
        unsafe = ProbeConfig(**{**self.config.__dict__, "url": "http://example.test/hook"})
        with self.assertRaisesRegex(ProbeError, "HTTPS"):
            run_probe(config=unsafe, secret_file=self.secret_file)


if __name__ == "__main__":
    unittest.main()
