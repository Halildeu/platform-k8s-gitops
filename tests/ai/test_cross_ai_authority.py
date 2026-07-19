from __future__ import annotations

import copy
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
    is_exact_revocation_transition,
    load_active_authority,
    load_authority_for_evidence,
    load_revocation_refresh_authority,
    load_staged_activation_authority,
    validate_authority_history_transition,
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
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
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
            "historicalAuthorities": [],
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

    def test_retired_root_is_content_addressed_and_bounded_to_pre_retirement_evidence(self) -> None:
        digest = self.fixture.authority.expected_trust_root_sha256
        digest_hex = digest.removeprefix("sha256:")
        history_root = (
            f"config/github-apps/cross-ai-provider-review-history/"
            f"{digest_hex}/trust-root.v2.json"
        )
        history_revocations = (
            f"config/github-apps/cross-ai-provider-review-history/"
            f"{digest_hex}/revocations.v1.dsse.json"
        )
        manifest = self.manifest(status="tracked_pending")
        manifest["historicalAuthorities"] = [
            {
                "trustRootPath": history_root,
                "revocationsPath": history_revocations,
                "expectedTrustRootSha256": digest,
                "expectedRevocationsSha256": sha256_digest(
                    self.fixture.authority.revocations_envelope
                ),
                "codexExecutablePolicy": (
                    self.fixture.authority.codex_executable_policy
                ),
                "issuerRuntimePolicy": (
                    self.fixture.authority.issuer_runtime_policy
                ),
                "retiredAt": "2026-07-18T20:45:00Z",
            }
        ]
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            manifest,
        )
        self.write_json(history_root, self.fixture.authority.trust_root)
        self.write_json(
            history_revocations,
            self.fixture.authority.revocations_envelope,
        )
        authority = load_authority_for_evidence(
            self.root,
            expected_trust_root_sha256=digest,
            observed_at=self.fixture.factory.now + timedelta(minutes=35),
            evidence_reference_time=self.fixture.factory.now,
        )
        self.assertEqual(digest, authority.expected_trust_root_sha256)
        with self.assertRaisesRegex(AuthorityUnavailable, "after its authority retired"):
            load_authority_for_evidence(
                self.root,
                expected_trust_root_sha256=digest,
                observed_at=self.fixture.factory.now + timedelta(hours=2),
                evidence_reference_time=self.fixture.factory.now
                + timedelta(minutes=30),
            )

    def test_retired_root_replay_checks_revocations_against_current_observation(self) -> None:
        digest = self.fixture.authority.expected_trust_root_sha256
        digest_hex = digest.removeprefix("sha256:")
        history_root = (
            f"config/github-apps/cross-ai-provider-review-history/"
            f"{digest_hex}/trust-root.v2.json"
        )
        history_revocations = (
            f"config/github-apps/cross-ai-provider-review-history/"
            f"{digest_hex}/revocations.v1.dsse.json"
        )
        stale_snapshot = self.fixture.factory.sign(
            REVOCATIONS_PAYLOAD_TYPE,
            {
                "schemaVersion": "acik.cross-ai-deployment-revocations.v1",
                "revocationSetId": "20000000-0000-4000-8000-000000000099",
                "issuedAt": "2026-07-18T20:10:00Z",
                "nextUpdate": "2026-07-18T21:10:00Z",
                "entries": [],
            },
            self.fixture.factory.REVOCATION_KEY_ID,
        )
        manifest = self.manifest(status="tracked_pending")
        manifest["historicalAuthorities"] = [
            {
                "trustRootPath": history_root,
                "revocationsPath": history_revocations,
                "expectedTrustRootSha256": digest,
                "expectedRevocationsSha256": sha256_digest(stale_snapshot),
                "codexExecutablePolicy": self.fixture.authority.codex_executable_policy,
                "issuerRuntimePolicy": self.fixture.authority.issuer_runtime_policy,
                "retiredAt": "2026-07-18T21:00:00Z",
            }
        ]
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            manifest,
        )
        self.write_json(history_root, self.fixture.authority.trust_root)
        self.write_json(history_revocations, stale_snapshot)
        with self.assertRaisesRegex(
            AuthorityUnavailable,
            "public authority is not active: REVOCATIONS_STALE",
        ):
            load_authority_for_evidence(
                self.root,
                expected_trust_root_sha256=digest,
                observed_at=self.fixture.factory.now + timedelta(hours=1),
                evidence_reference_time=self.fixture.factory.now + timedelta(minutes=25),
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
            "historicalAuthorities": [],
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

    def rotated_trust_root(self) -> dict[str, object]:
        replacement = copy.deepcopy(self.fixture.authority.trust_root)
        replacement.update(
            {
                "trustRootId": "10000000-0000-4000-8000-000000000002",
                "issuedAt": "2026-07-18T20:30:00Z",
                "expiresAt": "2026-08-17T20:30:00Z",
                "sourcePublicKeysetSha256": "sha256:" + ("7" * 64),
            }
        )
        for key in replacement["keys"]:
            key["notBefore"] = "2026-07-18T20:30:00Z"
            key["notAfter"] = (
                "2026-07-25T20:30:00Z"
                if key["role"] == "provider-review"
                else "2026-08-17T20:30:00Z"
            )
        return replacement

    def install_rotation(self) -> tuple[str, str]:
        predecessor_manifest = self.authority_manifest(active=True)
        predecessor_root = self.fixture.authority.trust_root
        predecessor_revocations = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000097",
            issued_at="2026-07-18T20:00:00Z",
            next_update="2026-07-18T21:00:00Z",
            entries=[],
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            predecessor_manifest,
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
            predecessor_root,
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json",
            predecessor_revocations,
        )
        base = self.commit("active predecessor authority")

        replacement_root = self.rotated_trust_root()
        replacement_revocations = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000098",
            issued_at="2026-07-18T20:30:00Z",
            next_update="2026-07-18T21:30:00Z",
            entries=[],
        )
        old_digest = self.fixture.authority.expected_trust_root_sha256
        old_digest_hex = old_digest.removeprefix("sha256:")
        history_root = (
            "config/github-apps/cross-ai-provider-review-history/"
            f"{old_digest_hex}/trust-root.v2.json"
        )
        history_revocations = (
            "config/github-apps/cross-ai-provider-review-history/"
            f"{old_digest_hex}/revocations.v1.dsse.json"
        )
        self.write_json(history_root, predecessor_root)
        self.write_json(history_revocations, predecessor_revocations)
        self.write_json(
            "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
            replacement_root,
        )
        self.write_json(
            "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json",
            replacement_revocations,
        )
        replacement_manifest = self.authority_manifest(active=True)
        replacement_manifest["expectedTrustRootSha256"] = sha256_digest(
            replacement_root
        )
        replacement_manifest["historicalAuthorities"] = [
            {
                "trustRootPath": history_root,
                "revocationsPath": history_revocations,
                "expectedTrustRootSha256": old_digest,
                "expectedRevocationsSha256": sha256_digest(
                    predecessor_revocations
                ),
                "codexExecutablePolicy": (
                    predecessor_manifest["codexExecutablePolicy"]
                ),
                "issuerRuntimePolicy": predecessor_manifest["issuerRuntimePolicy"],
                "retiredAt": "2026-07-18T20:30:00Z",
            }
        ]
        self.write_json(
            "config/github-apps/cross-ai-provider-review-authority.v1.json",
            replacement_manifest,
        )
        head = self.commit("rotate and archive predecessor authority")
        self.git("reset", "-q", "--hard", base)
        return base, head

    def history_bindings(self, base: str, head: str) -> dict[str, str]:
        return {
            "base_tip_sha": base,
            "base_sha": base,
            "head_sha": head,
            "scope_sha256": "1" * 64,
        }

    def test_root_rotation_appends_exact_content_addressed_predecessor(self) -> None:
        base, head = self.install_rotation()
        validate_authority_history_transition(
            self.root,
            expected_bindings=self.history_bindings(base, head),
            now=self.fixture.factory.now,
        )

    def test_root_rotation_rejects_backdated_retirement(self) -> None:
        base, valid_head = self.install_rotation()
        self.git("checkout", "-q", valid_head)
        root_path = (
            "config/github-apps/cross-ai-provider-review-trust-root.v2.json"
        )
        manifest_path = (
            "config/github-apps/cross-ai-provider-review-authority.v1.json"
        )
        replacement_root = json.loads((self.root / root_path).read_text())
        replacement_root["issuedAt"] = "2026-07-18T18:29:00Z"
        manifest = json.loads((self.root / manifest_path).read_text())
        manifest["expectedTrustRootSha256"] = sha256_digest(replacement_root)
        manifest["historicalAuthorities"][-1]["retiredAt"] = (
            replacement_root["issuedAt"]
        )
        self.write_json(root_path, replacement_root)
        self.write_json(manifest_path, manifest)
        bad_head = self.commit("backdate authority retirement")
        self.git("reset", "-q", "--hard", base)
        with self.assertRaisesRegex(AuthorityUnavailable, "predecessor boundary"):
            validate_authority_history_transition(
                self.root,
                expected_bindings=self.history_bindings(base, bad_head),
                now=self.fixture.factory.now,
            )

    def test_root_rotation_rejects_replacement_revocations_stale_at_review(self) -> None:
        base, valid_head = self.install_rotation()
        self.git("checkout", "-q", valid_head)
        root_path = (
            "config/github-apps/cross-ai-provider-review-trust-root.v2.json"
        )
        revocations_path = (
            "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json"
        )
        manifest_path = (
            "config/github-apps/cross-ai-provider-review-authority.v1.json"
        )
        replacement_root = json.loads((self.root / root_path).read_text())
        replacement_root["issuedAt"] = "2026-07-18T20:00:00Z"
        replacement_root["expiresAt"] = "2026-08-17T20:00:00Z"
        for key in replacement_root["keys"]:
            key["notBefore"] = "2026-07-18T20:00:00Z"
            key["notAfter"] = (
                "2026-07-25T20:00:00Z"
                if key["role"] == "provider-review"
                else "2026-08-17T20:00:00Z"
            )
        stale_revocations = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000099",
            issued_at="2026-07-18T20:00:00Z",
            next_update="2026-07-18T20:20:00Z",
            entries=[],
        )
        manifest = json.loads((self.root / manifest_path).read_text())
        manifest["expectedTrustRootSha256"] = sha256_digest(replacement_root)
        manifest["historicalAuthorities"][-1]["retiredAt"] = (
            replacement_root["issuedAt"]
        )
        self.write_json(root_path, replacement_root)
        self.write_json(revocations_path, stale_revocations)
        self.write_json(manifest_path, manifest)
        bad_head = self.commit("use stale replacement revocations")
        self.git("reset", "-q", "--hard", base)
        with self.assertRaisesRegex(AuthorityUnavailable, "REVOCATIONS_STALE"):
            validate_authority_history_transition(
                self.root,
                expected_bindings=self.history_bindings(base, bad_head),
                now=self.fixture.factory.now,
            )

    def test_root_rotation_without_archive_is_rejected(self) -> None:
        base, valid_head = self.install_rotation()
        self.git("checkout", "-q", valid_head)
        manifest_path = (
            "config/github-apps/cross-ai-provider-review-authority.v1.json"
        )
        manifest = json.loads((self.root / manifest_path).read_text())
        manifest["historicalAuthorities"] = []
        self.write_json(manifest_path, manifest)
        self.git("rm", "-q", "-r", "config/github-apps/cross-ai-provider-review-history")
        bad_head = self.commit("drop required rotation archive")
        self.git("reset", "-q", "--hard", base)
        with self.assertRaisesRegex(AuthorityUnavailable, "exact archived authority"):
            validate_authority_history_transition(
                self.root,
                expected_bindings=self.history_bindings(base, bad_head),
                now=self.fixture.factory.now,
            )

    def test_existing_history_cannot_be_deleted_or_mutated(self) -> None:
        _, rotation_head = self.install_rotation()
        self.git("checkout", "-q", rotation_head)
        manifest_path = (
            "config/github-apps/cross-ai-provider-review-authority.v1.json"
        )
        manifest = json.loads((self.root / manifest_path).read_text())
        archived_root_path = manifest["historicalAuthorities"][0]["trustRootPath"]
        manifest["historicalAuthorities"] = []
        self.write_json(manifest_path, manifest)
        deletion_head = self.commit("attempt history deletion")
        self.git("reset", "-q", "--hard", rotation_head)
        with self.assertRaisesRegex(AuthorityUnavailable, "history is immutable"):
            validate_authority_history_transition(
                self.root,
                expected_bindings=self.history_bindings(
                    rotation_head, deletion_head
                ),
                now=self.fixture.factory.now,
            )

        self.git("checkout", "-q", rotation_head)
        archived_root = json.loads((self.root / archived_root_path).read_text())
        archived_root["trustRootId"] = "10000000-0000-4000-8000-000000000099"
        self.write_json(archived_root_path, archived_root)
        mutation_head = self.commit("attempt archived byte mutation")
        self.git("reset", "-q", "--hard", rotation_head)
        with self.assertRaisesRegex(AuthorityUnavailable, "without a manifest rotation"):
            validate_authority_history_transition(
                self.root,
                expected_bindings=self.history_bindings(
                    rotation_head, mutation_head
                ),
                now=self.fixture.factory.now,
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

    def test_proactive_revocation_only_pr_cannot_bypass_replacement_validation(self) -> None:
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
        predecessor = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000090",
            issued_at="2026-07-18T20:00:00Z",
            next_update="2026-07-18T21:00:00Z",
            entries=[],
        )
        self.write_json(revocation_path, predecessor)
        base = self.commit("fresh active authority")
        proactive = self.signed_revocations(
            set_id="20000000-0000-4000-8000-000000000096",
            issued_at="2026-07-18T20:20:00Z",
            next_update="2026-07-18T21:20:00Z",
            entries=[],
        )
        self.write_json(revocation_path, proactive)
        head = self.commit("proactive signed refresh")
        self.git("reset", "-q", "--hard", base)
        scope = self.scope(base, head)
        bindings = {
            "base_tip_sha": base,
            "base_sha": base,
            "head_sha": head,
            "scope_sha256": hashlib.sha256(scope).hexdigest(),
        }
        self.assertTrue(
            is_exact_revocation_transition(
                self.root, expected_bindings=bindings
            )
        )
        with self.assertRaisesRegex(AuthorityUnavailable, "NOT_REQUIRED"):
            load_revocation_refresh_authority(
                self.root,
                expected_bindings=bindings,
                scope_bytes=scope,
                now=self.fixture.factory.now,
            )
        recovered = load_revocation_refresh_authority(
            self.root,
            expected_bindings=bindings,
            scope_bytes=scope,
            now=self.fixture.factory.now,
            require_stale_predecessor=False,
        )
        self.assertEqual(proactive, recovered.revocations_envelope)

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
