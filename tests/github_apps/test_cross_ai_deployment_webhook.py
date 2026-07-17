from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import tempfile
import unittest
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.webhook import (
    load_secret_files,
    parse_deployment_protection_webhook,
    validate_callback_url,
    verify_webhook_signature,
)


TEST_HMAC_KEY = secrets.token_hex(32).encode()


def payload() -> dict[str, object]:
    return {
        "action": "requested",
        "environment": "faz22-view-only-pilot",
        "event": "workflow_dispatch",
        "sha": "0123456789abcdef0123456789abcdef01234567",
        "ref": "refs/tags/cross-ai-intent/30000000-0000-4000-8000-000000000001",
        "deployment_callback_url": (
            "https://api.github.com/repos/Halildeu/platform-k8s-gitops/"
            "actions/runs/987654321/deployment_protection_rule"
        ),
        "deployment": {"id": 1},
        "pull_requests": [],
        "repository": {
            "id": 123456789,
            "full_name": "Halildeu/platform-k8s-gitops",
        },
        "installation": {"id": 2222},
        "sender": {"id": 424242, "login": "platform-automation[bot]"},
    }


def signed_request(
    data: bytes, hmac_key: bytes = TEST_HMAC_KEY
) -> tuple[dict[str, str], bytes]:
    signature = hmac.new(hmac_key, data, hashlib.sha256).hexdigest()
    return (
        {
            "Content-Type": "application/json",
            "X-GitHub-Event": "deployment_protection_rule",
            "X-GitHub-Delivery": "11111111-2222-4333-8444-555555555555",
            "X-Hub-Signature-256": f"sha256={signature}",
        },
        data,
    )


class WebhookTest(unittest.TestCase):
    def test_parses_authenticated_requested_event(self) -> None:
        raw = json.dumps(payload(), separators=(",", ":")).encode()
        headers, body = signed_request(raw)
        request = parse_deployment_protection_webhook(
            raw_body=body,
            headers=headers,
            secrets=(TEST_HMAC_KEY,),
        )
        self.assertEqual(request.run_id, 987654321)
        self.assertEqual(request.request_id, "30000000-0000-4000-8000-000000000001")
        self.assertEqual(request.repository_id, 123456789)

    def test_accepts_rotation_secret_without_identifying_version(self) -> None:
        rotation_key = secrets.token_hex(32).encode()
        raw = json.dumps(payload(), separators=(",", ":")).encode()
        headers, body = signed_request(raw, rotation_key)
        request = parse_deployment_protection_webhook(
            raw_body=body,
            headers=headers,
            secrets=(TEST_HMAC_KEY, rotation_key),
        )
        self.assertEqual(request.environment, "faz22-view-only-pilot")

    def test_rejects_bad_hmac(self) -> None:
        raw = json.dumps(payload(), separators=(",", ":")).encode()
        headers, body = signed_request(raw)
        headers["X-Hub-Signature-256"] = "sha256=" + ("0" * 64)
        with self.assertRaisesRegex(PolicyError, "WEBHOOK_SIGNATURE_INVALID"):
            parse_deployment_protection_webhook(
                raw_body=body,
                headers=headers,
                secrets=(TEST_HMAC_KEY,),
            )

    def test_rejects_duplicate_json_keys(self) -> None:
        raw = (
            b'{"action":"requested","action":"requested",'
            b'"environment":"faz22-view-only-pilot"}'
        )
        headers, body = signed_request(raw)
        with self.assertRaisesRegex(PolicyError, "WEBHOOK_JSON_DUPLICATE_KEY"):
            parse_deployment_protection_webhook(
                raw_body=body,
                headers=headers,
                secrets=(TEST_HMAC_KEY,),
            )

    def test_rejects_wrong_event_or_action(self) -> None:
        raw = json.dumps(payload(), separators=(",", ":")).encode()
        headers, body = signed_request(raw)
        headers["X-GitHub-Event"] = "deployment"
        with self.assertRaisesRegex(PolicyError, "WEBHOOK_EVENT_INVALID"):
            parse_deployment_protection_webhook(
                raw_body=body,
                headers=headers,
                secrets=(TEST_HMAC_KEY,),
            )

    def test_rejects_non_intent_ref(self) -> None:
        value = payload()
        value["ref"] = "refs/heads/main"
        raw = json.dumps(value, separators=(",", ":")).encode()
        headers, body = signed_request(raw)
        with self.assertRaisesRegex(PolicyError, "INTENT_REF_INVALID"):
            parse_deployment_protection_webhook(
                raw_body=body,
                headers=headers,
                secrets=(TEST_HMAC_KEY,),
            )

    def test_rejects_callback_ssrf_and_confusion_shapes(self) -> None:
        invalid = [
            "http://api.github.com/repos/Halildeu/platform-k8s-gitops/actions/runs/1/deployment_protection_rule",
            "https://api.github.com.evil.test/repos/Halildeu/platform-k8s-gitops/actions/runs/1/deployment_protection_rule",
            "https://api.github.com/repos/Other/repo/actions/runs/1/deployment_protection_rule",
            "https://api.github.com/repos/Halildeu/platform-k8s-gitops/actions/runs/1/deployment_protection_rule?token=x",
            "https://api.github.com/repos/Halildeu/platform-k8s-gitops/actions/runs/../1/deployment_protection_rule",
            "https://user@api.github.com/repos/Halildeu/platform-k8s-gitops/actions/runs/1/deployment_protection_rule",
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaisesRegex(PolicyError, "CALLBACK_URL_INVALID"):
                    validate_callback_url(
                        value,
                        repository="Halildeu/platform-k8s-gitops",
                    )

    def test_rejects_oversized_body_before_hmac(self) -> None:
        with self.assertRaisesRegex(PolicyError, "WEBHOOK_BODY_TOO_LARGE"):
            verify_webhook_signature(
                b"x" * (1024 * 1024 + 1),
                "sha256=" + ("0" * 64),
                (TEST_HMAC_KEY,),
            )

    def test_secret_files_require_distinct_strong_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            duplicate_key = secrets.token_hex(32).encode()
            first.write_bytes(duplicate_key)
            second.write_bytes(duplicate_key)
            with self.assertRaisesRegex(PolicyError, "WEBHOOK_SECRET_DUPLICATE"):
                load_secret_files((first, second))


if __name__ == "__main__":
    unittest.main()
