"""Fail-closed verification of signed Cross-AI deployment evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import sha256_digest
from .dsse import VerifiedEnvelope, decode_public_key, verify_json_envelope
from .errors import reject
from .timeutil import parse_utc, utc_now


ROOT = Path(__file__).resolve().parents[3]
BUNDLE_SCHEMA = ROOT / "schema/cross-ai-deployment-bundle-v1.schema.json"
REVIEW_SCHEMA = ROOT / "schema/cross-ai-deployment-review-v1.schema.json"
TRUST_ROOT_SCHEMA = ROOT / "schema/cross-ai-deployment-trust-root-v1.schema.json"
BUNDLE_SCHEMA_V2 = ROOT / "schema/cross-ai-deployment-bundle-v2.schema.json"
REVIEW_SCHEMA_V2 = ROOT / "schema/cross-ai-deployment-review-v2.schema.json"
TRUST_ROOT_SCHEMA_V2 = ROOT / "schema/cross-ai-deployment-trust-root-v2.schema.json"
REVOCATIONS_SCHEMA = ROOT / "schema/cross-ai-deployment-revocations-v1.schema.json"
RUNNER_ADMISSION_LEASE_SCHEMA = (
    ROOT / "schema/cross-ai-runner-admission-lease-v1.schema.json"
)
PROVIDER_RUNTIME_ATTESTATION_SCHEMA = (
    ROOT / "schema/cross-ai-provider-review-runtime-attestation-v1.schema.json"
)

BUNDLE_PAYLOAD_TYPE = "application/vnd.acik.cross-ai-deployment-bundle.v1+json"
REVIEW_PAYLOAD_TYPE = "application/vnd.acik.cross-ai-deployment-review.v1+json"
BUNDLE_PAYLOAD_TYPE_V2 = "application/vnd.acik.cross-ai-deployment-bundle.v2+json"
REVIEW_PAYLOAD_TYPE_V2 = "application/vnd.acik.cross-ai-deployment-review.v2+json"
REVOCATIONS_PAYLOAD_TYPE = (
    "application/vnd.acik.cross-ai-deployment-revocations.v1+json"
)
RUNNER_ADMISSION_LEASE_PAYLOAD_TYPE = (
    "application/vnd.acik.cross-ai-runner-admission-lease.v1+json"
)
PROVIDER_RUNTIME_ATTESTATION_PAYLOAD_TYPE = (
    "application/vnd.acik.cross-ai-provider-review-runtime-attestation.v1+json"
)
SESSION_DOMAIN = "acik.cross-ai-deployment-session.v1"
CLOSURE_DOMAIN = "acik.cross-ai-deployment-closure.v1"
SESSION_DOMAIN_V2 = "acik.cross-ai-deployment-session.v2"
CLOSURE_DOMAIN_V2 = "acik.cross-ai-deployment-closure.v2"
MAX_GRANT_TTL = timedelta(minutes=120)
MAX_REVIEW_TTL = timedelta(minutes=120)
MAX_REVOCATION_TTL = timedelta(minutes=60)
MAX_PROVIDER_RUNTIME_ATTESTATION_TTL = timedelta(minutes=10)
MIN_V2_TRUST_ROOT_TTL = timedelta(hours=168)
MAX_V2_TRUST_ROOT_TTL = timedelta(hours=720)
MAX_V2_PROVIDER_KEY_TTL = timedelta(hours=168)
MIN_V2_PROVIDER_KEY_OVERLAP = timedelta(hours=24)
OPENAI_TRANSIT_KEY_ID = re.compile(
    r"^vault-transit://cross-ai/openai#v([1-9][0-9]*)$"
)
MINIMAX_NEW_REVIEW_CUTOFF = datetime(2026, 7, 18, tzinfo=timezone.utc)
REQUIRED_PROVIDER_ROUTES = {
    "anthropic": (
        "direct-anthropic-cli",
        "claude-opus-4-8",
        "provider-reported",
        True,
    ),
    "minimax": (
        "direct-minimax-cli",
        "minimax/MiniMax-M3",
        "provider-reported",
        True,
    ),
    "openai": (
        "openai-codex",
        "gpt-5.6-sol",
        "provider-reported",
        True,
    ),
}
REQUIRED_PROVIDER_ROUTES_V2 = {
    "openai": (
        "openai-codex",
        ("gpt-5.3-codex-spark", "gpt-5.6-sol"),
        "trusted-launch-attested",
        True,
    ),
}


@dataclass(frozen=True)
class TrustKey:
    key_id: str
    role: str
    public_key: bytes
    provider_family: str | None
    allowed_channels: tuple[str, ...]
    allowed_model_ids: tuple[str, ...]
    allowed_model_identity_classes: tuple[str, ...]
    direct_provider_cli: bool | None
    not_before: datetime
    not_after: datetime


@dataclass(frozen=True)
class VerifiedReview:
    digest: str
    envelope: VerifiedEnvelope
    key: TrustKey
    issued_at: datetime
    expires_at: datetime

    @property
    def payload(self) -> dict[str, Any]:
        return self.envelope.payload


@dataclass(frozen=True)
class VerifiedRunnerAdmissionLease:
    digest: str
    envelope: VerifiedEnvelope
    key: TrustKey
    issued_at: datetime
    expires_at: datetime

    @property
    def payload(self) -> dict[str, Any]:
        return self.envelope.payload


@dataclass(frozen=True)
class VerifiedBundle:
    bundle_id: str
    bundle_digest: str
    subject_digest: str
    request_id: str
    session_digest: str
    expires_at: datetime
    provider_families: tuple[str, ...]
    provider_identity_classes: tuple[tuple[str, str], ...]
    final_review_digests: tuple[str, ...]
    coordinator_key_id: str
    runner_admission_lease: VerifiedRunnerAdmissionLease
    payload: dict[str, Any]


def _load_schema(path: Path) -> dict[str, Any]:
    import json

    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        reject("SCHEMA_UNAVAILABLE", f"cannot load schema {path.name}: {exc}")
    if not isinstance(schema, dict):
        reject("SCHEMA_UNAVAILABLE", f"schema {path.name} is not an object")
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_schema(instance: object, path: Path, code: str) -> None:
    validator = Draft202012Validator(_load_schema(path), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "$"
        reject(code, f"{path.name} validation failed at {location}: {first.message}")


class EvidenceVerifier:
    """Verify trust-root, revocation and provider-distinct bundle invariants."""

    def __init__(
        self,
        *,
        trust_root: dict[str, Any],
        revocations_envelope: dict[str, Any],
        now: datetime | None = None,
        expected_policy_sha256: str | None = None,
        expected_trust_root_sha256: str | None = None,
        verification_mode: Literal["active", "forensic"] = "active",
        forensic_reference_time: datetime | None = None,
        review_reference_time: datetime | None = None,
        supplemental_revocation_entries: tuple[dict[str, Any], ...] = (),
    ) -> None:
        self.observed_at = now or utc_now()
        if verification_mode not in {"active", "forensic"}:
            reject("VERIFICATION_MODE_INVALID", "verification mode is unsupported")
        if verification_mode == "active" and forensic_reference_time is not None:
            reject(
                "FORENSIC_REFERENCE_INVALID",
                "active verification cannot use a forensic reference time",
            )
        if verification_mode == "forensic" and review_reference_time is not None:
            reject(
                "REVIEW_REFERENCE_INVALID",
                "forensic verification derives review time from its forensic reference",
            )
        if verification_mode == "forensic" and forensic_reference_time is None:
            reject(
                "FORENSIC_REFERENCE_REQUIRED",
                "forensic verification requires an explicit historical time",
            )
        if (
            forensic_reference_time is not None
            and forensic_reference_time > self.observed_at
        ):
            reject(
                "FORENSIC_REFERENCE_INVALID",
                "forensic reference time cannot be in the future",
            )
        self.verification_mode = verification_mode
        self.now = forensic_reference_time or self.observed_at
        if (
            review_reference_time is not None
            and review_reference_time > self.observed_at
        ):
            reject(
                "REVIEW_REFERENCE_INVALID",
                "review reference time cannot be after authority observation",
            )
        self.review_reference_time = (
            self.now if verification_mode == "forensic"
            else review_reference_time or self.observed_at
        )
        self.expected_policy_sha256 = expected_policy_sha256
        self.trust_root = trust_root
        schema_version = trust_root.get("schemaVersion")
        if schema_version == "acik.cross-ai-deployment-trust-root.v1":
            self.contract_version = "v1"
            self.trust_root_schema = TRUST_ROOT_SCHEMA
            self.bundle_schema = BUNDLE_SCHEMA
            self.review_schema = REVIEW_SCHEMA
            self.bundle_payload_type = BUNDLE_PAYLOAD_TYPE
            self.review_payload_type = REVIEW_PAYLOAD_TYPE
            self.session_domain = SESSION_DOMAIN
            self.closure_domain = CLOSURE_DOMAIN
            self.required_provider_routes = REQUIRED_PROVIDER_ROUTES
        elif schema_version == "acik.cross-ai-deployment-trust-root.v2":
            self.contract_version = "v2"
            self.trust_root_schema = TRUST_ROOT_SCHEMA_V2
            self.bundle_schema = BUNDLE_SCHEMA_V2
            self.review_schema = REVIEW_SCHEMA_V2
            self.bundle_payload_type = BUNDLE_PAYLOAD_TYPE_V2
            self.review_payload_type = REVIEW_PAYLOAD_TYPE_V2
            self.session_domain = SESSION_DOMAIN_V2
            self.closure_domain = CLOSURE_DOMAIN_V2
            self.required_provider_routes = REQUIRED_PROVIDER_ROUTES_V2
        else:
            reject(
                "TRUST_ROOT_SCHEMA_INVALID",
                "trust root contract version is unsupported",
            )
        if self.verification_mode == "forensic":
            if self.contract_version != "v1":
                reject(
                    "FORENSIC_CONTRACT_INVALID",
                    "forensic replay is reserved for the retired v1 contract",
                )
            if self.now >= MINIMAX_NEW_REVIEW_CUTOFF:
                reject(
                    "FORENSIC_REFERENCE_INVALID",
                    "v1 forensic reference time must predate the retirement cutoff",
                )
        if (
            expected_trust_root_sha256 is not None
            and sha256_digest(trust_root) != expected_trust_root_sha256
        ):
            reject(
                "TRUST_ROOT_DIGEST_MISMATCH",
                "trust root differs from the deployment-configured digest",
            )
        _validate_schema(
            trust_root, self.trust_root_schema, "TRUST_ROOT_SCHEMA_INVALID"
        )
        self.max_skew = timedelta(seconds=trust_root["maxClockSkewSeconds"])
        self.required_provider_families = frozenset(
            trust_root["requiredProviderFamilies"]
        )
        if (
            self.contract_version == "v1"
            and "minimax" in self.required_provider_families
            and self.verification_mode == "active"
            and self.observed_at >= MINIMAX_NEW_REVIEW_CUTOFF
        ):
            reject(
                "MINIMAX_PROVIDER_DEPRECATED",
                "active verification cannot use a MiniMax-bearing v1 trust root after the cutoff",
            )
        trust_root_expires_at = parse_utc(trust_root["expiresAt"], "trustRoot.expiresAt")
        if (
            self.contract_version == "v1"
            and "minimax" in self.required_provider_families
            and trust_root_expires_at > MINIMAX_NEW_REVIEW_CUTOFF
        ):
            reject(
                "MINIMAX_TRUST_ROOT_DEPRECATED",
                "MiniMax trust roots may not remain valid after the forward-policy cutoff",
            )
        self.minimum_provider_families = trust_root["minimumProviderFamilies"]
        self.minimum_direct_routes = trust_root["minimumDirectProviderRoutes"]
        self.keys = self._parse_trust_keys(trust_root)
        self._validate_trust_root_lifetime()
        self.revocations_envelope = self._verify_revocations(revocations_envelope)
        self.revocations = self.revocations_envelope.payload
        supplemental_payload = dict(self.revocations)
        supplemental_payload["entries"] = list(supplemental_revocation_entries)
        _validate_schema(
            supplemental_payload,
            REVOCATIONS_SCHEMA,
            "SUPPLEMENTAL_REVOCATIONS_SCHEMA_INVALID",
        )
        self.supplemental_revocation_entries = tuple(supplemental_revocation_entries)

    def _parse_trust_keys(self, trust_root: dict[str, Any]) -> dict[str, TrustKey]:
        parsed: dict[str, TrustKey] = {}
        public_keys: set[bytes] = set()
        for entry in trust_root["keys"]:
            key_id = entry["keyId"]
            if key_id in parsed:
                reject("TRUST_KEY_DUPLICATE", f"duplicate key ID {key_id}")
            public_key = decode_public_key(entry["publicKeyBase64"], key_id)
            if public_key in public_keys:
                reject(
                    "TRUST_KEY_REUSED",
                    "one Ed25519 key must not serve two trust entries",
                )
            public_keys.add(public_key)
            role = entry["role"]
            family = entry["providerFamily"]
            channels = tuple(entry["allowedChannels"])
            model_ids = tuple(entry["allowedModelIds"])
            model_identity_classes = tuple(entry["allowedModelIdentityClasses"])
            direct = entry["directProviderCli"]
            if role == "provider-review":
                if (
                    not family
                    or not channels
                    or not model_ids
                    or not model_identity_classes
                    or not isinstance(direct, bool)
                ):
                    reject(
                        "TRUST_KEY_ATTRIBUTION_INVALID",
                        f"provider key {key_id} lacks fixed family/channel/direct attribution",
                    )
                expected_route = self.required_provider_routes.get(family)
                actual_route = (
                    channels[0],
                    model_ids if self.contract_version == "v2" else model_ids[0],
                    model_identity_classes[0],
                    direct,
                )
                if expected_route is None or actual_route != expected_route:
                    reject(
                        "TRUST_PROVIDER_ROUTE_INVALID",
                        f"provider key {key_id} differs from the canonical direct route",
                    )
            elif (
                family is not None
                or channels
                or model_ids
                or model_identity_classes
                or direct is not None
            ):
                reject(
                    "TRUST_KEY_ATTRIBUTION_INVALID",
                    f"non-provider key {key_id} must not carry provider attribution",
                )
            not_before = parse_utc(entry["notBefore"], f"keys[{key_id}].notBefore")
            not_after = parse_utc(entry["notAfter"], f"keys[{key_id}].notAfter")
            if not_after <= not_before:
                reject(
                    "TRUST_KEY_LIFETIME_INVALID", f"key {key_id} lifetime is invalid"
                )
            parsed[key_id] = TrustKey(
                key_id=key_id,
                role=role,
                public_key=public_key,
                provider_family=family,
                allowed_channels=channels,
                allowed_model_ids=model_ids,
                allowed_model_identity_classes=model_identity_classes,
                direct_provider_cli=direct,
                not_before=not_before,
                not_after=not_after,
            )
        roles = {key.role for key in parsed.values()}
        if not {
            "provider-review",
            "coordinator",
            "revocation",
            "runner-management",
        }.issubset(roles):
            reject(
                "TRUST_ROLE_MISSING",
                "provider, coordinator, revocation and runner-management keys are required",
            )
        families = {
            key.provider_family
            for key in parsed.values()
            if key.role == "provider-review"
        }
        if families != self.required_provider_families:
            reject(
                "TRUST_PROVIDER_SET_INVALID",
                "trust root provider families differ from the required signed set",
            )
        if self.contract_version == "v2":
            role_counts = defaultdict(int)
            for key in parsed.values():
                role_counts[key.role] += 1
            if any(
                role_counts[role] != 1
                for role in ("coordinator", "revocation", "runner-management")
            ):
                reject(
                    "TRUST_ROLE_CARDINALITY_INVALID",
                    "v2 requires exactly one coordinator, revocation and runner-management key",
                )
            provider_keys = sorted(
                (key for key in parsed.values() if key.role == "provider-review"),
                key=lambda key: key.not_before,
            )
            if len(provider_keys) not in {1, 2}:
                reject(
                    "TRUST_PROVIDER_KEY_CARDINALITY_INVALID",
                    "v2 permits one active OpenAI key or one bounded rotation pair",
                )
            versions: list[int] = []
            for key in provider_keys:
                match = OPENAI_TRANSIT_KEY_ID.fullmatch(key.key_id)
                if match is None:
                    reject(
                        "TRUST_PROVIDER_KEY_ID_INVALID",
                        "v2 provider key must use the fixed OpenAI Transit route",
                    )
                versions.append(int(match.group(1)))
                if key.not_after - key.not_before > MAX_V2_PROVIDER_KEY_TTL:
                    reject(
                        "TRUST_PROVIDER_KEY_LIFETIME_INVALID",
                        "v2 provider-review key lifetime exceeds 168 hours",
                    )
            if len(provider_keys) == 2:
                versioned_keys = sorted(
                    zip(versions, provider_keys), key=lambda item: item[0]
                )
                if versioned_keys[1][0] != versioned_keys[0][0] + 1:
                    reject(
                        "TRUST_PROVIDER_ROTATION_INVALID",
                        "v2 provider rotation keys must be consecutive versions",
                    )
                if (
                    versioned_keys[1][1].not_before
                    < versioned_keys[0][1].not_before
                    or versioned_keys[1][1].not_after
                    <= versioned_keys[0][1].not_after
                ):
                    reject(
                        "TRUST_PROVIDER_ROTATION_INVALID",
                        "v2 provider rotation chronology does not advance with the key version",
                    )
                overlap_start = max(key.not_before for key in provider_keys)
                overlap_end = min(key.not_after for key in provider_keys)
                if overlap_end - overlap_start < MIN_V2_PROVIDER_KEY_OVERLAP:
                    reject(
                        "TRUST_PROVIDER_ROTATION_OVERLAP_INVALID",
                        "v2 provider rotation overlap is shorter than 24 hours",
                    )
        return parsed

    def _validate_trust_root_lifetime(self) -> None:
        issued_at = parse_utc(self.trust_root["issuedAt"], "trustRoot.issuedAt")
        expires_at = parse_utc(self.trust_root["expiresAt"], "trustRoot.expiresAt")
        if issued_at > self.now + self.max_skew:
            reject("TRUST_ROOT_NOT_YET_VALID", "trust root issue time is in the future")
        if expires_at < self.now - self.max_skew:
            reject("TRUST_ROOT_EXPIRED", "trust root is expired")
        if expires_at <= issued_at:
            reject("TRUST_ROOT_LIFETIME_INVALID", "trust root lifetime is invalid")
        if self.contract_version == "v2":
            lifetime = expires_at - issued_at
            if not MIN_V2_TRUST_ROOT_TTL <= lifetime <= MAX_V2_TRUST_ROOT_TTL:
                reject(
                    "TRUST_ROOT_LIFETIME_INVALID",
                    "v2 trust root lifetime must be between 168 and 720 hours",
                )

    def _active_keys(self, role: str) -> dict[str, bytes]:
        return self._keys_valid_at(role, self.now)

    def _keys_valid_at(self, role: str, reference_time: datetime) -> dict[str, bytes]:
        active: dict[str, bytes] = {}
        for key in self.keys.values():
            if key.role != role:
                continue
            if (
                key.not_before <= reference_time + self.max_skew
                and key.not_after >= reference_time - self.max_skew
            ):
                active[key.key_id] = key.public_key
        if not active:
            reject(
                "TRUST_ACTIVE_KEY_MISSING",
                f"no {role} key is valid at the acceptance reference time",
            )
        return active

    def _role_keys(self, role: str) -> dict[str, bytes]:
        keys = {
            key.key_id: key.public_key
            for key in self.keys.values()
            if key.role == role
        }
        if not keys:
            reject("TRUST_ROLE_MISSING", f"no {role} key is present")
        return keys

    def _validate_root_time(self, issued_at: datetime, label: str) -> None:
        root_start = parse_utc(self.trust_root["issuedAt"], "trustRoot.issuedAt")
        root_end = parse_utc(self.trust_root["expiresAt"], "trustRoot.expiresAt")
        if issued_at < root_start - self.max_skew:
            reject("TRUST_ROOT_NOT_YET_VALID", f"{label} predates trust-root validity")
        if issued_at > root_end + self.max_skew:
            reject("TRUST_ROOT_EXPIRED", f"{label} was issued after trust-root expiry")

    def require_active_signing_key(
        self,
        *,
        key_id: str,
        role: str,
        provider_family: str | None = None,
        issued_at: datetime | None = None,
    ) -> TrustKey:
        """Fail before issuance when a workload is bound to the wrong key."""

        key = self.keys.get(key_id)
        if key is None or key.role != role:
            reject(
                "TRUST_SIGNER_BINDING_MISMATCH",
                "signer key is absent or has a different trust-root role",
            )
        if provider_family is not None and key.provider_family != provider_family:
            reject(
                "TRUST_SIGNER_BINDING_MISMATCH",
                "signer key has a different provider attribution",
            )
        if provider_family is None and key.provider_family is not None:
            reject(
                "TRUST_SIGNER_BINDING_MISMATCH",
                "non-provider signer unexpectedly has provider attribution",
            )
        if key_id not in self._active_keys(role):
            reject("TRUST_SIGNER_NOT_ACTIVE", "signer key is not active")
        self._validate_key_time(key, issued_at or self.now, "signer")
        return key

    def _verify_revocations(
        self, envelope: dict[str, Any], *, require_fresh: bool = True
    ) -> VerifiedEnvelope:
        verified = verify_json_envelope(
            envelope,
            expected_payload_type=REVOCATIONS_PAYLOAD_TYPE,
            allowed_keys=self._active_keys("revocation"),
            exactly_one_signature=True,
        )
        _validate_schema(
            verified.payload,
            REVOCATIONS_SCHEMA,
            "REVOCATIONS_SCHEMA_INVALID",
        )
        issued_at = parse_utc(verified.payload["issuedAt"], "revocations.issuedAt")
        next_update = parse_utc(
            verified.payload["nextUpdate"], "revocations.nextUpdate"
        )
        if issued_at > self.now + self.max_skew:
            reject(
                "REVOCATIONS_NOT_YET_VALID",
                "revocation set issue time is in the future",
            )
        if require_fresh and next_update < self.now - self.max_skew:
            reject("REVOCATIONS_STALE", "revocation set nextUpdate is stale")
        if next_update <= issued_at:
            reject("REVOCATIONS_LIFETIME_INVALID", "revocation set lifetime is invalid")
        if next_update - issued_at > MAX_REVOCATION_TTL:
            reject(
                "REVOCATIONS_LIFETIME_INVALID",
                "revocation set lifetime exceeds 60 minutes",
            )
        signer = self.keys[verified.signing_key_ids[0]]
        self._validate_root_time(issued_at, "revocation")
        root_end = parse_utc(self.trust_root["expiresAt"], "trustRoot.expiresAt")
        if next_update > root_end + self.max_skew:
            reject(
                "REVOCATIONS_LIFETIME_INVALID",
                "revocation refresh extends beyond trust-root validity",
            )
        self._validate_key_time(signer, issued_at, "revocation", check_revocation=False)
        if next_update > signer.not_after + self.max_skew:
            reject(
                "REVOCATIONS_LIFETIME_INVALID",
                "revocation refresh extends beyond signer validity",
            )
        return verified

    def require_stale_revocation_predecessor(
        self, predecessor_envelope: dict[str, Any]
    ) -> VerifiedEnvelope:
        """Validate the sole narrow recovery from a missed refresh window.

        ``self`` has already authenticated the fresh replacement against the
        active pinned root. The trusted-base predecessor must also be
        authentic, actually stale, strictly older, and every prior revocation
        must remain present byte-for-byte. This permits an exact
        revocations-file-only PR to recover freshness without creating an
        unrevocation or arbitrary governance bypass.
        """

        return self.require_monotonic_revocation_predecessor(
            predecessor_envelope, require_stale=True
        )

    def require_monotonic_revocation_predecessor(
        self,
        predecessor_envelope: dict[str, Any],
        *,
        require_stale: bool,
    ) -> VerifiedEnvelope:
        """Authenticate a proactive or stale monotonic revocation release."""

        predecessor = self._verify_revocations(predecessor_envelope, require_fresh=False)
        old_issued = parse_utc(
            predecessor.payload["issuedAt"], "predecessorRevocations.issuedAt"
        )
        old_next = parse_utc(
            predecessor.payload["nextUpdate"], "predecessorRevocations.nextUpdate"
        )
        new_issued = parse_utc(
            self.revocations["issuedAt"], "replacementRevocations.issuedAt"
        )
        if require_stale and old_next >= self.now - self.max_skew:
            reject(
                "REVOCATION_RECOVERY_NOT_REQUIRED",
                "revocation predecessor is not stale",
            )
        if (
            new_issued <= old_issued
            or self.revocations["revocationSetId"]
            == predecessor.payload["revocationSetId"]
        ):
            reject(
                "REVOCATION_RECOVERY_ORDER_INVALID",
                "replacement revocation set is not a new release",
            )
        old_entries = {
            sha256_digest(entry) for entry in predecessor.payload["entries"]
        }
        new_entries = {sha256_digest(entry) for entry in self.revocations["entries"]}
        if not old_entries.issubset(new_entries):
            reject(
                "REVOCATION_RECOVERY_UNREVOCATION_FORBIDDEN",
                "replacement omits a predecessor revocation",
            )
        return predecessor

    def _validate_key_time(
        self,
        key: TrustKey,
        issued_at: datetime,
        label: str,
        *,
        check_revocation: bool = True,
    ) -> None:
        if issued_at < key.not_before - self.max_skew:
            reject("SIGNING_KEY_NOT_YET_VALID", f"{label} predates key validity")
        if issued_at > key.not_after + self.max_skew:
            reject("SIGNING_KEY_EXPIRED", f"{label} was issued after key expiry")
        if check_revocation and self._is_revoked("key", key.key_id, issued_at):
            reject("SIGNING_KEY_REVOKED", f"key {key.key_id} is revoked")

    def _is_revoked(
        self, kind: str, identifier: str, issued_at: datetime | None = None
    ) -> bool:
        for entry in (
            *self.revocations["entries"],
            *self.supplemental_revocation_entries,
        ):
            if entry["type"] != kind or entry["id"] != identifier:
                continue
            parse_utc(entry["effectiveAt"], "revocation.effectiveAt")
            # This verifier decides only current, unconsumed authorizations.
            # Any matching current revocation is therefore immediate even when
            # the leaf predates effectiveAt. Historical audit validation is a
            # separate mode and is intentionally not implemented here.
            _ = issued_at
            return True
        return False

    def verify_bundle(self, envelope: dict[str, Any]) -> VerifiedBundle:
        coordinator_keys = self._active_keys("coordinator")
        outer = verify_json_envelope(
            envelope,
            expected_payload_type=self.bundle_payload_type,
            allowed_keys=coordinator_keys,
            exactly_one_signature=True,
        )
        _validate_schema(
            outer.payload, self.bundle_schema, "BUNDLE_SCHEMA_INVALID"
        )
        bundle = outer.payload
        coordinator = self.keys[outer.signing_key_ids[0]]
        grant_not_before = parse_utc(bundle["grant"]["notBefore"], "grant.notBefore")
        self._validate_key_time(coordinator, grant_not_before, "bundle")

        subject_digest = sha256_digest(
            {
                "subject": bundle["subject"],
                "workflowStages": bundle["workflowStages"],
                "grant": bundle["grant"],
            }
        )
        self._verify_subject_and_grant(bundle, subject_digest)
        runner_admission_lease = self._verify_runner_admission_lease(bundle)

        reviews = self._verify_reviews(bundle, subject_digest)
        if self.contract_version == "v2":
            self._verify_review_runtime_attestations(bundle, reviews)
        closure_root = self._verify_closure(bundle, reviews, subject_digest)
        final_reviews, families = self._verify_consensus(
            bundle,
            reviews,
            subject_digest,
            closure_root,
        )

        bundle_id = bundle["bundleId"]
        request_id = bundle["grant"]["requestId"]
        for kind, identifier in (
            ("bundle", bundle_id),
            ("subject", subject_digest),
            ("grant", request_id),
        ):
            if self._is_revoked(kind, identifier):
                reject("EVIDENCE_REVOKED", f"{kind} authorization is revoked")

        return VerifiedBundle(
            bundle_id=bundle_id,
            bundle_digest=outer.envelope_digest,
            subject_digest=subject_digest,
            request_id=request_id,
            session_digest=bundle["subject"]["sessionSha256"],
            expires_at=parse_utc(bundle["grant"]["expiresAt"], "grant.expiresAt"),
            provider_families=tuple(sorted(families)),
            provider_identity_classes=tuple(
                sorted(
                    (
                        review.key.provider_family or "",
                        review.payload["modelIdentityClass"],
                    )
                    for review in final_reviews
                )
            ),
            final_review_digests=tuple(
                sorted(review.digest for review in final_reviews)
            ),
            coordinator_key_id=coordinator.key_id,
            runner_admission_lease=runner_admission_lease,
            payload=bundle,
        )

    def _verify_runner_admission_lease(
        self, bundle: dict[str, Any]
    ) -> VerifiedRunnerAdmissionLease:
        envelope = bundle["runnerAdmissionLeaseEnvelope"]
        verified = verify_json_envelope(
            envelope,
            expected_payload_type=RUNNER_ADMISSION_LEASE_PAYLOAD_TYPE,
            allowed_keys=self._active_keys("runner-management"),
            exactly_one_signature=True,
        )
        _validate_schema(
            verified.payload,
            RUNNER_ADMISSION_LEASE_SCHEMA,
            "RUNNER_ADMISSION_LEASE_SCHEMA_INVALID",
        )
        subject = bundle["subject"]
        grant = bundle["grant"]
        payload = verified.payload
        if verified.envelope_digest != subject["runnerAdmissionLeaseSha256"]:
            reject(
                "RUNNER_ADMISSION_LEASE_DIGEST_MISMATCH",
                "runner admission lease differs from the signed subject",
            )
        bindings = {
            "requestId": grant["requestId"],
            "repositoryId": subject["repositoryId"],
            "repository": subject["repository"],
            "environment": subject["environment"],
            "headSha": subject["headSha"],
            "intentRef": subject["intentRef"],
            "runnerPolicySha256": subject["runnerPolicySha256"],
        }
        if any(payload.get(key) != value for key, value in bindings.items()):
            reject(
                "RUNNER_ADMISSION_LEASE_BINDING_MISMATCH",
                "runner admission lease differs from deployment subject",
            )
        issued_at = parse_utc(payload["issuedAt"], "runnerLease.issuedAt")
        expires_at = parse_utc(payload["expiresAt"], "runnerLease.expiresAt")
        grant_start = parse_utc(grant["notBefore"], "grant.notBefore")
        grant_end = parse_utc(grant["expiresAt"], "grant.expiresAt")
        if (
            issued_at > self.now + self.max_skew
            or expires_at < self.now - self.max_skew
            or expires_at <= issued_at
            or issued_at < grant_start - self.max_skew
            or expires_at < grant_end
        ):
            reject(
                "RUNNER_ADMISSION_LEASE_LIFETIME_INVALID",
                "runner admission lease does not cover the signed grant",
            )
        runners = payload["eligibleRunners"]
        runner_ids = [entry["runnerId"] for entry in runners]
        runner_names = [entry["runnerNameSha256"] for entry in runners]
        if len(set(runner_ids)) != len(runner_ids) or len(set(runner_names)) != len(
            runner_names
        ):
            reject(
                "RUNNER_ADMISSION_LEASE_AMBIGUOUS",
                "runner admission lease contains duplicate identities",
            )
        key = self.keys[verified.signing_key_ids[0]]
        self._validate_key_time(key, issued_at, "runner admission lease")
        if self._is_revoked("runner-lease", payload["leaseId"]):
            reject("EVIDENCE_REVOKED", "runner admission lease is revoked")
        return VerifiedRunnerAdmissionLease(
            digest=verified.envelope_digest,
            envelope=verified,
            key=key,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def _verify_subject_and_grant(
        self, bundle: dict[str, Any], subject_digest: str
    ) -> None:
        subject = bundle["subject"]
        grant = bundle["grant"]
        not_before = parse_utc(grant["notBefore"], "grant.notBefore")
        expires_at = parse_utc(grant["expiresAt"], "grant.expiresAt")
        if expires_at <= not_before:
            reject("GRANT_LIFETIME_INVALID", "grant expiresAt must follow notBefore")
        if expires_at - not_before > MAX_GRANT_TTL:
            reject("GRANT_TTL_EXCEEDED", "grant exceeds the 120 minute v1 maximum")
        if not_before > self.now + self.max_skew:
            reject("GRANT_NOT_YET_VALID", "grant is not yet valid")
        if expires_at < self.now - self.max_skew:
            reject("GRANT_EXPIRED", "grant is expired")
        if (
            self.expected_policy_sha256
            and subject["policySha256"] != self.expected_policy_sha256
        ):
            reject(
                "POLICY_DIGEST_MISMATCH",
                "subject policy digest does not match pinned policy",
            )
        request_id = grant["requestId"]
        if subject["intentRef"] != f"refs/tags/cross-ai-intent/{request_id}":
            reject("INTENT_REF_MISMATCH", "intent ref is not bound to requestId")

        expected_session = sha256_digest(
            {
                "domain": self.session_domain,
                "requestId": request_id,
                "deploymentSessionId": grant["deploymentSessionId"],
                "repositoryId": subject["repositoryId"],
                "environment": subject["environment"],
                "headSha": subject["headSha"],
                "intentRef": subject["intentRef"],
                "bootstrapCredentialSha256": subject["bootstrapCredentialSha256"],
                "endpointIdSha256": subject["endpointIdSha256"],
                "operatorIdSha256": subject["operatorIdSha256"],
            }
        )
        if subject["sessionSha256"] != expected_session:
            reject(
                "SESSION_BINDING_MISMATCH",
                "sessionSha256 does not match canonical session",
            )

        stages = bundle["workflowStages"]
        stage_names = [stage["stage"] for stage in stages]
        if stage_names != ["apply", "browser-evidence", "compensating-rollback"]:
            reject("STAGE_SEQUENCE_INVALID", "v1 stage order is not canonical")
        if [stage["order"] for stage in stages] != [1, 2, 3]:
            reject("STAGE_SEQUENCE_INVALID", "v1 stage order numbers are invalid")
        if stages[0].get("dependsOn", []) != []:
            reject("STAGE_SEQUENCE_INVALID", "apply must not depend on another stage")
        if stages[1].get("dependsOn") != ["apply"]:
            reject("STAGE_SEQUENCE_INVALID", "browser-evidence must depend on apply")
        if stages[2].get("dependsOnFailure") != ["apply"]:
            reject("STAGE_SEQUENCE_INVALID", "rollback must be failure-bound to apply")

        # subject_digest is intentionally computed here even when no review is
        # present; callers can safely use it only after full verification.
        if not subject_digest.startswith("sha256:"):
            reject("SUBJECT_DIGEST_INVALID", "subject digest calculation failed")

    def _verify_reviews(
        self, bundle: dict[str, Any], subject_digest: str
    ) -> dict[str, VerifiedReview]:
        # A current authorization uses observation time by default. A durable
        # downstream product verifier instead supplies its independently
        # fetched pilot/run time, so an authentic leaf remains verifiable after
        # normal provider-key rotation. The leaf is still checked separately at
        # its signed issuedAt, preventing a retired key from backdating a new
        # review into its old interval.
        provider_keys = (
            self._keys_valid_at("provider-review", self.review_reference_time)
            if self.verification_mode == "active"
            else self._role_keys("provider-review")
        )
        verified: dict[str, VerifiedReview] = {}
        review_ids: set[str] = set()
        for envelope in bundle["reviewEnvelopes"]:
            leaf_envelope = verify_json_envelope(
                envelope,
                expected_payload_type=self.review_payload_type,
                allowed_keys=provider_keys,
                exactly_one_signature=True,
            )
            _validate_schema(
                leaf_envelope.payload,
                self.review_schema,
                "REVIEW_SCHEMA_INVALID",
            )
            leaf = leaf_envelope.payload
            key_id = leaf_envelope.signing_key_ids[0]
            if leaf["keyId"] != key_id:
                reject(
                    "PROVIDER_ATTRIBUTION_MISMATCH",
                    "leaf keyId differs from DSSE signer",
                )
            key = self.keys[key_id]
            if (
                leaf["providerFamily"] != key.provider_family
                or leaf["channel"] not in key.allowed_channels
                or leaf["modelId"] not in key.allowed_model_ids
                or leaf["directProviderCli"] is not key.direct_provider_cli
                or leaf["modelIdentityClass"] not in key.allowed_model_identity_classes
                or leaf["issuer"] != f"cross-ai-issuer-{key.provider_family}"
            ):
                reject(
                    "PROVIDER_ATTRIBUTION_MISMATCH",
                    "leaf provider/channel/direct attribution differs from trust root",
                )
            if leaf["subjectSha256"] != subject_digest:
                reject(
                    "REVIEW_SUBJECT_MISMATCH", "review does not bind the bundle subject"
                )
            issued_at = parse_utc(leaf["issuedAt"], "review.issuedAt")
            expires_at = parse_utc(leaf["expiresAt"], "review.expiresAt")
            if self.contract_version == "v1" and leaf["providerFamily"] == "minimax":
                if (
                    self.verification_mode == "active"
                    and self.observed_at >= MINIMAX_NEW_REVIEW_CUTOFF
                ):
                    reject(
                        "MINIMAX_PROVIDER_DEPRECATED",
                        "active verification cannot accept MiniMax review leaves after the cutoff",
                    )
                if issued_at >= MINIMAX_NEW_REVIEW_CUTOFF:
                    reject(
                        "MINIMAX_REVIEW_DEPRECATED",
                        "MiniMax reviews issued on or after the forward-policy cutoff are forbidden",
                    )
            if issued_at > self.review_reference_time + self.max_skew:
                reject("REVIEW_NOT_YET_VALID", "review issue time is in the future")
            if expires_at < self.review_reference_time - self.max_skew:
                reject("REVIEW_EXPIRED", "review is expired")
            if expires_at <= issued_at:
                reject("REVIEW_LIFETIME_INVALID", "review lifetime is invalid")
            if expires_at - issued_at > MAX_REVIEW_TTL:
                reject(
                    "REVIEW_LIFETIME_INVALID",
                    "review lifetime exceeds 120 minutes",
                )
            self._validate_root_time(issued_at, "review")
            self._validate_key_time(key, issued_at, "review")
            if leaf["reviewId"] in review_ids:
                reject("REVIEW_ID_DUPLICATE", "reviewId must be unique")
            review_ids.add(leaf["reviewId"])
            digest = leaf_envelope.envelope_digest
            if digest in verified:
                reject("REVIEW_DUPLICATE", "review envelope digest must be unique")
            if self._is_revoked("review", digest, issued_at):
                reject("REVIEW_REVOKED", "review envelope is revoked")
            verified[digest] = VerifiedReview(
                digest=digest,
                envelope=leaf_envelope,
                key=key,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        self._verify_review_chains(verified)
        return verified

    def verify_provider_review(
        self, envelope: dict[str, Any], expected_subject_sha256: str
    ) -> VerifiedReview:
        """Verify one signed provider leaf against the pinned active authority.

        This deliberately reuses the same signature, role, attribution,
        lifetime and revocation checks as bundle verification. It is the
        bootstrap-safe acceptance boundary for a standalone consultation
        comment; the owner-authored comment is only a transport envelope.
        """

        if not isinstance(expected_subject_sha256, str) or not expected_subject_sha256.startswith(
            "sha256:"
        ):
            reject("REVIEW_SUBJECT_MISMATCH", "expected review subject digest is invalid")
        reviews = self._verify_reviews(
            {"reviewEnvelopes": [envelope]}, expected_subject_sha256
        )
        if len(reviews) != 1:
            reject("REVIEW_CARDINALITY_INVALID", "exactly one provider review is required")
        return next(iter(reviews.values()))

    def _verify_review_runtime_attestations(
        self,
        bundle: dict[str, Any],
        reviews: dict[str, VerifiedReview],
    ) -> None:
        attestations = bundle["reviewRuntimeAttestationEnvelopes"]
        if len(attestations) != len(reviews):
            reject(
                "PROVIDER_RUNTIME_CARDINALITY_MISMATCH",
                "every provider review requires exactly one runtime attestation",
            )
        attested_reviews: set[str] = set()
        runtime_policy = self.trust_root["providerReviewRuntimePolicy"]
        for envelope in attestations:
            verified = verify_json_envelope(
                envelope,
                expected_payload_type=PROVIDER_RUNTIME_ATTESTATION_PAYLOAD_TYPE,
                allowed_keys=self._role_keys("runner-management"),
                exactly_one_signature=True,
            )
            _validate_schema(
                verified.payload,
                PROVIDER_RUNTIME_ATTESTATION_SCHEMA,
                "PROVIDER_RUNTIME_ATTESTATION_SCHEMA_INVALID",
            )
            review_digest = verified.payload["providerReviewEnvelopeSha256"]
            if review_digest in attested_reviews:
                reject(
                    "PROVIDER_RUNTIME_DUPLICATE",
                    "a provider review has more than one runtime attestation",
                )
            review = reviews.get(review_digest)
            if review is None:
                reject(
                    "PROVIDER_RUNTIME_REVIEW_UNKNOWN",
                    "runtime attestation references a review outside the bundle",
                )
            self.verify_provider_runtime_attestation(
                envelope,
                runtime_policy=runtime_policy,
                provider_review_envelope_sha256=review.digest,
                prompt_sha256=review.payload["inputSha256"],
                response_sha256=review.payload["outputSha256"],
                capability_snapshot_sha256=review.payload[
                    "capabilitySnapshotSha256"
                ],
                provider_session_id=review.payload["providerSessionId"],
                provider_review_issued_at=review.issued_at,
            )
            attested_reviews.add(review_digest)
        if attested_reviews != set(reviews):
            reject(
                "PROVIDER_RUNTIME_REVIEW_MISSING",
                "one or more provider reviews lack a runtime attestation",
            )

    def verify_provider_runtime_attestation(
        self,
        envelope: dict[str, Any],
        *,
        runtime_policy: dict[str, Any],
        provider_review_envelope_sha256: str,
        prompt_sha256: str,
        response_sha256: str,
        capability_snapshot_sha256: str,
        provider_session_id: str,
        provider_review_issued_at: datetime,
    ) -> VerifiedEnvelope:
        """Require a second authority for the immutable issuer runtime.

        Possession of the provider-review signing key is insufficient. The
        runner-management signer independently binds the fixed workload image
        and launcher source to the exact prompt, response, Codex session,
        capability snapshot and signed provider leaf.
        """

        required_policy = {
            "schemaVersion",
            "workloadIdentity",
            "issuerImageDigest",
            "launcherSourceSha256",
            "attestorKeyId",
            "maxAttestationLifetimeSeconds",
            "apiOrigin",
            "sessionPath",
            "authAudience",
            "kubernetesNamespace",
            "kubernetesServiceAccount",
            "kubernetesContainerName",
            "vaultKubernetesAuthMount",
            "vaultKubernetesRole",
            "vaultTokenPolicy",
            "maxReplicas",
        }
        if (
            not isinstance(runtime_policy, dict)
            or set(runtime_policy) != required_policy
            or runtime_policy.get("schemaVersion")
            != "acik.cross-ai-provider-review-runtime-policy.v1"
            or runtime_policy.get("maxAttestationLifetimeSeconds") != 600
            or runtime_policy.get("sessionPath")
            != "/api/v1/cross-ai/provider-review-runtime/sessions"
            or runtime_policy.get("authAudience")
            != "acik-cross-ai-provider-review-runtime"
            or runtime_policy.get("maxReplicas") != 1
        ):
            reject(
                "PROVIDER_RUNTIME_POLICY_INVALID",
                "provider issuer runtime policy is invalid",
            )
        verified = verify_json_envelope(
            envelope,
            expected_payload_type=PROVIDER_RUNTIME_ATTESTATION_PAYLOAD_TYPE,
            allowed_keys=self._keys_valid_at(
                "runner-management", provider_review_issued_at
            ),
            exactly_one_signature=True,
        )
        _validate_schema(
            verified.payload,
            PROVIDER_RUNTIME_ATTESTATION_SCHEMA,
            "PROVIDER_RUNTIME_ATTESTATION_SCHEMA_INVALID",
        )
        payload = verified.payload
        key_id = verified.signing_key_ids[0]
        if payload["keyId"] != key_id or key_id != runtime_policy["attestorKeyId"]:
            reject(
                "PROVIDER_RUNTIME_ATTESTOR_MISMATCH",
                "provider runtime signer differs from the pinned runner authority",
            )
        expected = {
            "workloadIdentity": runtime_policy["workloadIdentity"],
            "issuerImageDigest": runtime_policy["issuerImageDigest"],
            "launcherSourceSha256": runtime_policy["launcherSourceSha256"],
            "providerReviewEnvelopeSha256": provider_review_envelope_sha256,
            "promptSha256": prompt_sha256,
            "responseSha256": response_sha256,
            "capabilitySnapshotSha256": capability_snapshot_sha256,
            "providerSessionId": provider_session_id,
        }
        if any(payload[field] != value for field, value in expected.items()):
            reject(
                "PROVIDER_RUNTIME_BINDING_MISMATCH",
                "provider runtime attestation differs from the exact review execution",
            )
        issued_at = parse_utc(payload["issuedAt"], "providerRuntime.issuedAt")
        expires_at = parse_utc(payload["expiresAt"], "providerRuntime.expiresAt")
        if issued_at != provider_review_issued_at:
            reject(
                "PROVIDER_RUNTIME_REVIEW_TIME_MISMATCH",
                "provider runtime attestation is not co-issued with the review leaf",
            )
        if (
            expires_at <= issued_at
            or expires_at - issued_at > MAX_PROVIDER_RUNTIME_ATTESTATION_TTL
        ):
            reject(
                "PROVIDER_RUNTIME_LIFETIME_INVALID",
                "provider runtime attestation lifetime is invalid",
            )
        key = self.keys[key_id]
        self._validate_root_time(issued_at, "provider runtime attestation")
        self._validate_key_time(key, issued_at, "provider runtime attestation")
        if self._is_revoked("issuer-runtime", verified.envelope_digest, issued_at):
            reject(
                "PROVIDER_RUNTIME_REVOKED",
                "provider runtime attestation is revoked",
            )
        return verified

    def _verify_review_chains(self, reviews: dict[str, VerifiedReview]) -> None:
        chains: dict[str, list[VerifiedReview]] = defaultdict(list)
        raised_occurrences: dict[str, list[VerifiedReview]] = defaultdict(list)
        resolved_occurrences: dict[str, list[VerifiedReview]] = defaultdict(list)
        acknowledged_occurrences: dict[str, list[VerifiedReview]] = defaultdict(list)
        for review in reviews.values():
            chains[review.payload["reviewChainId"]].append(review)
            finding_ids = set(review.payload["findingIds"])
            resolved_ids = set(review.payload["resolvedFindingIds"])
            acknowledged_ids = set(review.payload["acknowledgedFindingIds"])
            if review.payload["verdict"] == "AGREE" and (
                finding_ids or resolved_ids or acknowledged_ids
            ):
                reject(
                    "REVIEW_AGREE_FINDINGS_INVALID",
                    "AGREE review must not carry finding state transitions",
                )
            if review.payload["verdict"] in {"REVISE", "RED"} and not finding_ids:
                reject(
                    "REVIEW_DISSENT_FINDINGS_REQUIRED",
                    "REVISE and RED reviews must raise at least one finding",
                )
            if review.payload["verdict"] == "PARTIAL" and not (
                finding_ids or resolved_ids or acknowledged_ids
            ):
                reject(
                    "REVIEW_PARTIAL_TRANSITION_REQUIRED",
                    "PARTIAL review must carry a finding state transition",
                )
            if finding_ids & (resolved_ids | acknowledged_ids):
                reject(
                    "REVIEW_FINDING_STATE_INVALID",
                    "a review cannot raise and close the same finding",
                )
            if not acknowledged_ids.issubset(resolved_ids):
                reject(
                    "REVIEW_FINDING_STATE_INVALID",
                    "acknowledged findings must be resolved in the same review",
                )
            for finding_id in finding_ids:
                raised_occurrences[finding_id].append(review)
            for finding_id in resolved_ids:
                resolved_occurrences[finding_id].append(review)
            for finding_id in acknowledged_ids:
                acknowledged_occurrences[finding_id].append(review)
        if any(len(occurrences) != 1 for occurrences in raised_occurrences.values()):
            reject(
                "REVIEW_FINDING_REUSED",
                "finding IDs must identify exactly one raise event in the bundle",
            )
        referenced_ids = set(resolved_occurrences) | set(acknowledged_occurrences)
        if not referenced_ids.issubset(raised_occurrences):
            reject(
                "REVIEW_FINDING_REFERENCE_INVALID",
                "resolved or acknowledged finding has no raise event",
            )
        if any(len(occurrences) != 1 for occurrences in resolved_occurrences.values()):
            reject(
                "REVIEW_FINDING_STATE_INVALID",
                "finding IDs must identify exactly one resolve event",
            )
        if any(
            len(occurrences) != 1 for occurrences in acknowledged_occurrences.values()
        ):
            reject(
                "REVIEW_FINDING_STATE_INVALID",
                "finding IDs must identify exactly one acknowledgement event",
            )
        for finding_id, acknowledgements in acknowledged_occurrences.items():
            raised = raised_occurrences[finding_id][0]
            acknowledged = acknowledgements[0]
            if (
                raised.key.provider_family != acknowledged.key.provider_family
                or acknowledged.issued_at <= raised.issued_at
            ):
                reject(
                    "REVIEW_FINDING_REFERENCE_INVALID",
                    "finding acknowledgement must follow its same-provider raise event",
                )
        for chain_id, chain in chains.items():
            ordered = sorted(chain, key=lambda item: item.payload["round"])
            families = {item.key.provider_family for item in ordered}
            if len(families) != 1:
                reject(
                    "REVIEW_CHAIN_PROVIDER_MISMATCH",
                    f"chain {chain_id} crosses providers",
                )
            rounds = [item.payload["round"] for item in ordered]
            if rounds != list(range(1, len(ordered) + 1)):
                reject(
                    "REVIEW_CHAIN_GAP", f"chain {chain_id} rounds are not contiguous"
                )
            if ordered[0].payload["previousRoundSha256"] is not None:
                reject(
                    "REVIEW_CHAIN_INVALID",
                    f"chain {chain_id} first round has a predecessor",
                )
            for previous, current in zip(ordered, ordered[1:]):
                if current.payload["previousRoundSha256"] != previous.digest:
                    reject(
                        "REVIEW_CHAIN_INVALID", f"chain {chain_id} predecessor mismatch"
                    )

    def _verify_closure(
        self,
        bundle: dict[str, Any],
        reviews: dict[str, VerifiedReview],
        subject_digest: str,
    ) -> str:
        entries = bundle["closure"]["entries"]
        finding_ids: set[str] = set()
        closure_projection: list[dict[str, str]] = []
        for entry in entries:
            finding_id = entry["findingId"]
            if finding_id in finding_ids:
                reject(
                    "CLOSURE_DUPLICATE_FINDING", "closure finding IDs must be unique"
                )
            finding_ids.add(finding_id)
            raised = reviews.get(entry["raisedByReviewSha256"])
            acknowledged = reviews.get(entry["acknowledgedByReviewSha256"])
            if raised is None or acknowledged is None:
                reject("CLOSURE_REVIEW_MISSING", "closure references an unknown review")
            if (
                raised.payload["verdict"] == "AGREE"
                or finding_id not in raised.payload["findingIds"]
            ):
                reject(
                    "CLOSURE_RAISE_INVALID",
                    "finding is not raised by a non-AGREE review",
                )
            if raised.key.provider_family != acknowledged.key.provider_family:
                reject(
                    "CLOSURE_ACK_PROVIDER_MISMATCH",
                    "raiser provider must acknowledge fix",
                )
            if (
                finding_id not in acknowledged.payload["resolvedFindingIds"]
                or finding_id not in acknowledged.payload["acknowledgedFindingIds"]
            ):
                reject("CLOSURE_ACK_MISSING", "fix lacks provider acknowledgement")
            if acknowledged.issued_at <= raised.issued_at:
                reject(
                    "CLOSURE_ACK_ORDER_INVALID", "acknowledgement must follow finding"
                )
            closure_projection.append(
                {
                    "findingId": finding_id,
                    "raisedByReviewSha256": entry["raisedByReviewSha256"],
                    "fixSha256": entry["fixSha256"],
                    "acknowledgedByReviewSha256": entry["acknowledgedByReviewSha256"],
                }
            )
        raised_ids = {
            finding_id
            for review in reviews.values()
            if review.payload["verdict"] != "AGREE"
            for finding_id in review.payload["findingIds"]
        }
        if finding_ids != raised_ids:
            reject(
                "CLOSURE_INCOMPLETE", "closure does not cover every must-fix finding"
            )
        closure_root = sha256_digest(
            {
                "domain": self.closure_domain,
                "subjectSha256": subject_digest,
                "entries": sorted(
                    closure_projection, key=lambda item: item["findingId"]
                ),
            }
        )
        if bundle["closure"]["closureRootSha256"] != closure_root:
            reject("CLOSURE_ROOT_MISMATCH", "closure root digest is invalid")
        if bundle["consensus"]["closureRootSha256"] != closure_root:
            reject("CLOSURE_ROOT_MISMATCH", "consensus closure root differs")
        return closure_root

    def _verify_consensus(
        self,
        bundle: dict[str, Any],
        reviews: dict[str, VerifiedReview],
        subject_digest: str,
        closure_root: str,
    ) -> tuple[list[VerifiedReview], set[str]]:
        final_digests = bundle["consensus"]["finalAgreeReviewSha256"]
        chain_tips: dict[str, str] = {}
        for digest, review in reviews.items():
            chain_id = review.payload["reviewChainId"]
            current = chain_tips.get(chain_id)
            if (
                current is None
                or reviews[current].payload["round"] < review.payload["round"]
            ):
                chain_tips[chain_id] = digest
        final_reviews: list[VerifiedReview] = []
        for digest in final_digests:
            if digest not in reviews:
                reject(
                    "CONSENSUS_REVIEW_MISSING", "consensus references unknown review"
                )
            review = reviews[digest]
            if chain_tips[review.payload["reviewChainId"]] != digest:
                reject("CONSENSUS_NOT_CHAIN_TIP", "counted review is not its chain tip")
            if review.payload["verdict"] != "AGREE":
                reject(
                    "CONSENSUS_VERDICT_INVALID", "counted final verdict must be AGREE"
                )
            if review.payload["subjectSha256"] != subject_digest:
                reject("CONSENSUS_SUBJECT_MISMATCH", "counted review subject differs")
            if review.payload["closureRootSha256"] != closure_root:
                reject(
                    "CONSENSUS_CLOSURE_MISMATCH", "counted AGREE has old closure root"
                )
            final_reviews.append(review)
        if set(chain_tips.values()) != set(final_digests):
            reject(
                "CONSENSUS_UNCOUNTED_CHAIN",
                "every provider review chain tip must be selected by consensus",
            )
        families = {
            review.key.provider_family
            for review in final_reviews
            if review.key.provider_family is not None
        }
        direct_families = {
            review.key.provider_family
            for review in final_reviews
            if review.key.direct_provider_cli and review.key.provider_family is not None
        }
        if families != self.required_provider_families:
            reject(
                "PROVIDER_FAMILY_SET_MISMATCH",
                "final provider families differ from the signed required set",
            )
        if direct_families != self.required_provider_families:
            reject(
                "DIRECT_PROVIDER_SET_MISMATCH",
                "every required provider family must use its signed direct route",
            )
        if set(bundle["consensus"]["providerFamilies"]) != families:
            reject(
                "CONSENSUS_PROVIDER_MISMATCH",
                "consensus provider family list is invalid",
            )
        return final_reviews, families


__all__ = ["EvidenceVerifier", "VerifiedBundle"]
