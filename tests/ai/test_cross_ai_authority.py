from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from scripts.ai.cross_ai_authority import (
    AuthorityUnavailable,
    load_active_authority,
    load_revocation_refresh_authority,
    load_staged_activation_authority,
)
from scripts.ai.prepare_cross_ai_scope import MAX_SCOPE_BYTES, derive_scope
from scripts.ai.verify_cross_ai_authority_transition import (
    TransitionError,
    stage_public_authority,
)
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    REVOCATIONS_PAYLOAD_TYPE,
)
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
            "codexExecutablePolicy": self.fixture.authority.codex_executable_policy,
            "issuerRuntimePolicy": (
                self.fixture.authority.issuer_runtime_policy if active else None
            ),
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

        wrong_attestor = self.manifest()
        wrong_attestor["issuerRuntimePolicy"] = dict(
            wrong_attestor["issuerRuntimePolicy"]
        )
        wrong_attestor["issuerRuntimePolicy"]["attestorKeyId"] = (
            "vault-transit://cross-ai/runner-management#v9"
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            wrong_attestor,
        )
        with self.assertRaisesRegex(AuthorityUnavailable, "TRUST_SIGNER_BINDING"):
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


class GenesisTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "config/github-apps").mkdir(parents=True)
        (self.root / "schema").mkdir()
        for name in (
            "cross-ai-provider-review-authority-v1.schema.json",
            "cross-ai-provider-review-genesis-v1.schema.json",
        ):
            shutil.copyfile(ROOT / "schema" / name, self.root / "schema" / name)
        self.fixture = make_signed_evidence()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Cross AI Test")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def write_json(self, relative: str, value: object) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def authority_manifest(self, *, active: bool) -> dict[str, object]:
        return {
            "schemaVersion": "acik.cross-ai-provider-review-authority.v1",
            "status": "active" if active else "tracked_pending",
            "authoritySource": "test-vault-transit-public-export",
            "codexExecutablePolicy": self.fixture.authority.codex_executable_policy,
            "issuerRuntimePolicy": (
                self.fixture.authority.issuer_runtime_policy if active else None
            ),
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

    def genesis(self, *, status: str) -> dict[str, object]:
        value = json.loads(
            (ROOT / "config/github-apps/cross-ai-provider-review-genesis.v1.json").read_text()
        )
        value["status"] = status
        if status != "installed":
            value.update(
                {
                    "trustRootPath": "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
                    "revocationsPath": "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json",
                    "expectedTrustRootSha256": self.fixture.authority.expected_trust_root_sha256,
                    "issuerRuntimePolicy": self.fixture.authority.issuer_runtime_policy,
                }
            )
        return value

    def commit(self, message: str) -> str:
        self.git("add", ".")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def install_base(self, *, genesis_status: str) -> str:
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            self.authority_manifest(active=False),
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-genesis.v1.json",
            self.genesis(status=genesis_status),
        )
        if genesis_status == "staged":
            self.write_json(
                "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
                self.fixture.authority.trust_root,
            )
            self.write_json(
                "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json",
                self.fixture.authority.revocations_envelope,
            )
        return self.commit("base")

    def scope(self, base: str, head: str) -> bytes:
        scope, _, _ = derive_scope(
            self.root,
            base_tip_sha=base,
            base_sha=base,
            head_sha=head,
            max_scope_bytes=MAX_SCOPE_BYTES,
            scan_secrets=False,
        )
        return scope

    def test_stage_requires_exact_paths_valid_signed_revocations_and_pending_locator(self) -> None:
        base = self.install_base(genesis_status="installed")
        self.write_json(
            "config/github-apps/cross-ai-provider-review-genesis.v1.json",
            self.genesis(status="staged"),
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
            self.fixture.authority.trust_root,
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json",
            self.fixture.authority.revocations_envelope,
        )
        head = self.commit("stage")
        self.git("reset", "-q", "--hard", base)
        result = stage_public_authority(
            self.root, base=base, head=head, now=self.fixture.factory.now
        )
        self.assertEqual(result["statusAfter"], "staged")

        self.git("checkout", "-q", head)
        (self.root / "extra.txt").write_text("not allowed", encoding="utf-8")
        bad_head = self.commit("extra")
        self.git("checkout", "-q", base)
        with self.assertRaisesRegex(TransitionError, "outside genesis"):
            stage_public_authority(
                self.root, base=base, head=bad_head, now=self.fixture.factory.now
            )

    def test_activation_uses_only_staged_base_authority_and_exact_retirement(self) -> None:
        base = self.install_base(genesis_status="staged")
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            self.authority_manifest(active=True),
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-genesis.v1.json",
            self.genesis(status="retired"),
        )
        head = self.commit("activate")
        self.git("reset", "-q", "--hard", base)
        scope = self.scope(base, head)
        authority = load_staged_activation_authority(
            self.root,
            expected_bindings={
                "base_tip_sha": base,
                "base_sha": base,
                "head_sha": head,
                "scope_sha256": hashlib.sha256(scope).hexdigest(),
            },
            scope_bytes=scope,
            now=self.fixture.factory.now,
        )
        self.assertEqual(
            authority.expected_trust_root_sha256,
            self.fixture.authority.expected_trust_root_sha256,
        )

        self.git("checkout", "-q", head)
        genesis = self.genesis(status="retired")
        genesis["expectedTrustRootSha256"] = "sha256:" + ("0" * 64)
        self.write_json(
            "config/github-apps/cross-ai-provider-review-genesis.v1.json", genesis
        )
        bad_head = self.commit("mutate genesis")
        self.git("checkout", "-q", base)
        bad_scope = self.scope(base, bad_head)
        with self.assertRaisesRegex(AuthorityUnavailable, "retirement is not exact"):
            load_staged_activation_authority(
                self.root,
                expected_bindings={
                    "base_tip_sha": base,
                    "base_sha": base,
                    "head_sha": bad_head,
                    "scope_sha256": hashlib.sha256(bad_scope).hexdigest(),
                },
                scope_bytes=bad_scope,
                now=self.fixture.factory.now,
            )

    def test_stage_rejects_runtime_attestor_outside_the_pinned_root(self) -> None:
        base = self.install_base(genesis_status="installed")
        staged = self.genesis(status="staged")
        staged["issuerRuntimePolicy"] = dict(staged["issuerRuntimePolicy"])
        staged["issuerRuntimePolicy"]["attestorKeyId"] = (
            "vault-transit://cross-ai/runner-management#v9"
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-genesis.v1.json",
            staged,
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
            self.fixture.authority.trust_root,
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json",
            self.fixture.authority.revocations_envelope,
        )
        head = self.commit("stage with untrusted attestor")
        self.git("reset", "-q", "--hard", base)
        with self.assertRaisesRegex(TransitionError, "TRUST_SIGNER_BINDING"):
            stage_public_authority(
                self.root, base=base, head=head, now=self.fixture.factory.now
            )

    def signed_revocations(
        self, *, set_id: str, issued_at: str, next_update: str,
        entries: list[dict[str, str]],
    ) -> dict[str, object]:
        return self.fixture.factory.sign(
            REVOCATIONS_PAYLOAD_TYPE,
            {
                "schemaVersion": "acik.cross-ai-deployment-revocations.v1",
                "revocationSetId": set_id,
                "issuedAt": issued_at,
                "nextUpdate": next_update,
                "entries": entries,
            },
            self.fixture.factory.REVOCATION_KEY_ID,
        )

    def test_stale_revocations_have_one_signed_monotonic_exact_path_recovery(self) -> None:
        prior_entry = {
            "type": "review",
            "id": "sha256:" + ("1" * 64),
            "effectiveAt": "2026-07-18T18:00:00Z",
            "reasonCode": "REVIEW_COMPROMISED",
        }
        stale = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000091",
            issued_at="2026-07-18T18:00:00Z",
            next_update="2026-07-18T19:00:00Z",
            entries=[prior_entry],
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            self.authority_manifest(active=True),
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
            self.fixture.authority.trust_root,
        )
        revocation_path = (
            "config/github-apps/"
            "cross-ai-provider-review-revocations.v1.dsse.json"
        )
        self.write_json(revocation_path, stale)
        base = self.commit("stale base")
        with self.assertRaisesRegex(AuthorityUnavailable, "REVOCATIONS_STALE"):
            load_active_authority(self.root, now=self.fixture.factory.now)

        fresh = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000092",
            issued_at="2026-07-18T20:20:00Z",
            next_update="2026-07-18T21:00:00Z",
            entries=[prior_entry],
        )
        self.write_json(revocation_path, fresh)
        head = self.commit("signed refresh")
        self.git("reset", "-q", "--hard", base)
        scope = self.scope(base, head)
        bindings = {
            "base_tip_sha": base,
            "base_sha": base,
            "head_sha": head,
            "scope_sha256": hashlib.sha256(scope).hexdigest(),
        }
        recovered = load_revocation_refresh_authority(
            self.root,
            expected_bindings=bindings,
            scope_bytes=scope,
            now=self.fixture.factory.now,
        )
        self.assertEqual(recovered.revocations_envelope, fresh)

        self.git("checkout", "-q", head)
        removed = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000093",
            issued_at="2026-07-18T20:21:00Z",
            next_update="2026-07-18T21:00:00Z",
            entries=[],
        )
        self.write_json(revocation_path, removed)
        bad_head = self.commit("attempt unrevocation")
        self.git("checkout", "-q", base)
        bad_scope = self.scope(base, bad_head)
        with self.assertRaisesRegex(AuthorityUnavailable, "UNREVOCATION_FORBIDDEN"):
            load_revocation_refresh_authority(
                self.root,
                expected_bindings={
                    **bindings,
                    "head_sha": bad_head,
                    "scope_sha256": hashlib.sha256(bad_scope).hexdigest(),
                },
                scope_bytes=bad_scope,
                now=self.fixture.factory.now,
            )

    def test_staged_authority_can_refresh_after_its_initial_revocations_expire(self) -> None:
        stale = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000094",
            issued_at="2026-07-18T18:00:00Z",
            next_update="2026-07-18T19:00:00Z",
            entries=[],
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            self.authority_manifest(active=False),
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-genesis.v1.json",
            self.genesis(status="staged"),
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
            self.fixture.authority.trust_root,
        )
        revocation_path = (
            "config/github-apps/"
            "cross-ai-provider-review-revocations.v1.dsse.json"
        )
        self.write_json(revocation_path, stale)
        base = self.commit("staged stale base")

        fresh = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000095",
            issued_at="2026-07-18T20:20:00Z",
            next_update="2026-07-18T21:00:00Z",
            entries=[],
        )
        self.write_json(revocation_path, fresh)
        head = self.commit("refresh staged revocations")
        self.git("reset", "-q", "--hard", base)
        scope = self.scope(base, head)
        authority = load_revocation_refresh_authority(
            self.root,
            expected_bindings={
                "base_tip_sha": base,
                "base_sha": base,
                "head_sha": head,
                "scope_sha256": hashlib.sha256(scope).hexdigest(),
            },
            scope_bytes=scope,
            now=self.fixture.factory.now,
        )
        self.assertEqual(authority.revocations_envelope, fresh)

        self.git("checkout", "-q", head)
        (self.root / "unrelated.txt").write_text("not allowed", encoding="utf-8")
        unrelated_head = self.commit("unrelated mutation")
        self.git("checkout", "-q", base)
        unrelated_scope = self.scope(base, unrelated_head)
        with self.assertRaisesRegex(AuthorityUnavailable, "outside the signed release"):
            load_revocation_refresh_authority(
                self.root,
                expected_bindings={
                    "base_tip_sha": base,
                    "base_sha": base,
                    "head_sha": unrelated_head,
                    "scope_sha256": hashlib.sha256(unrelated_scope).hexdigest(),
                },
                scope_bytes=unrelated_scope,
                now=self.fixture.factory.now,
            )

    def test_genesis_workflow_is_trusted_main_human_protected_and_hash_locked(self) -> None:
        workflow = (
            ROOT / ".github/workflows/cross-ai-provider-review-genesis.yml"
        ).read_text(encoding="utf-8")
        for required in (
            "environment: cross-ai-provider-review-genesis",
            'test "$GITHUB_REF" = "refs/heads/main"',
            "repos/$GH_REPO/environments/$EXPECTED_ENVIRONMENT",
            '.type == "required_reviewers"',
            ".prevent_self_review == true",
            "--require-hashes",
            "--only-binary=:all:",
            "scripts/ai/verify_cross_ai_authority_transition.py",
            "test \"$(jq -r .base.sha \"$RUNNER_TEMP/pr.json\")\" = \"$GITHUB_SHA\"",
            "test \"$(git merge-base \"$GITHUB_SHA\" \"$EXPECTED_HEAD_SHA\")\" = \"$GITHUB_SHA\"",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("contents: write", workflow)


if __name__ == "__main__":
    unittest.main()
