from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from scripts.ai.cross_ai_authority import AuthorityUnavailable, load_active_authority
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from tests.ai.signed_evidence_fixture import make_signed_evidence


ROOT = Path(__file__).resolve().parents[2]


class PublicReviewAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config/github-apps").mkdir(parents=True)
        (self.root / "schema").mkdir()
        shutil.copyfile(
            ROOT / "schema/cross-ai-provider-review-authority-v1.schema.json",
            self.root / "schema/cross-ai-provider-review-authority-v1.schema.json",
        )
        self.fixture = make_signed_evidence()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_json(self, relative: str, value: object) -> None:
        (self.root / relative).write_text(
            json.dumps(value, sort_keys=True), encoding="utf-8",
        )

    def manifest(self, *, status: str = "active") -> dict[str, object]:
        active = status == "active"
        return {
            "schemaVersion": "acik.cross-ai-provider-review-authority.v1",
            "status": status,
            "authoritySource": "test-vault-transit-public-export",
            "trustRootPath": (
                "config/github-apps/cross-ai-provider-review-trust-root.v2.json"
                if active else None
            ),
            "revocationsPath": (
                "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json"
                if active else None
            ),
            "expectedTrustRootSha256": (
                self.fixture.authority.expected_trust_root_sha256 if active else None
            ),
            "rotationPolicy": {
                "maxTrustRootLifetimeHours": 720,
                "maxProviderKeyRotationHours": 168,
                "minimumKeyOverlapHours": 24,
                "maxRevocationStalenessMinutes": 60,
                "maxReviewLeafLifetimeMinutes": 120,
            },
        }

    def install_active_files(self) -> None:
        self.write_json(
            "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
            self.fixture.authority.trust_root,
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json",
            self.fixture.authority.revocations_envelope,
        )

    def test_committed_locator_is_truthfully_tracked_pending(self) -> None:
        shutil.copyfile(
            ROOT / "config/github-apps/cross-ai-provider-review-authority.v1.json",
            self.root / "config/github-apps/cross-ai-provider-review-authority.v1.json",
        )
        with self.assertRaisesRegex(AuthorityUnavailable, "tracked_pending"):
            load_active_authority(self.root, now=self.fixture.factory.now)

    def test_active_locator_requires_signed_fresh_revocations_and_independent_pin(self) -> None:
        self.install_active_files()
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            self.manifest(),
        )
        authority = load_active_authority(self.root, now=self.fixture.factory.now)
        self.assertEqual(
            authority.expected_trust_root_sha256,
            sha256_digest(authority.trust_root),
        )

        wrong_pin = self.manifest()
        wrong_pin["expectedTrustRootSha256"] = "sha256:" + ("0" * 64)
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            wrong_pin,
        )
        with self.assertRaisesRegex(AuthorityUnavailable, "pin mismatch"):
            load_active_authority(self.root, now=self.fixture.factory.now)

    def test_absent_or_stale_revocations_never_fall_back_to_empty(self) -> None:
        self.install_active_files()
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            self.manifest(),
        )
        (self.root / "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json").unlink()
        with self.assertRaisesRegex(AuthorityUnavailable, "resource is unavailable"):
            load_active_authority(self.root, now=self.fixture.factory.now)

        self.install_active_files()
        with self.assertRaisesRegex(AuthorityUnavailable, "not active"):
            load_active_authority(
                self.root,
                now=self.fixture.factory.now + timedelta(hours=2),
            )


if __name__ == "__main__":
    unittest.main()
