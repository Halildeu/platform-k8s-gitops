"""Fail-closed verification of signed Cross-AI deployment evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import sha256_digest
from .dsse import VerifiedEnvelope, decode_public_key, verify_json_envelope
from .errors import reject
from .timeutil import parse_utc, utc_now


ROOT = Path(__file__).resolve().parents[3]
BUNDLE_SCHEMA = ROOT / "schema/cross-ai-deployment-bundle-v1.schema.json"
REVIEW_SCHEMA = ROOT / "schema/cross-ai-deployment-review-v1.schema.json"
TRUST_ROOT_SCHEMA = ROOT / "schema/cross-ai-deployment-trust-root-v1.schema.json"
REVOCATIONS_SCHEMA = ROOT / "schema/cross-ai-deployment-revocations-v1.schema.json"
RUNNER_ADMISSION_LEASE_SCHEMA = (
    ROOT / "schema/cross-ai-runner-admission-lease-v1.schema.json"
)

BUNDLE_PAYLOAD_TYPE = "application/vnd.acik.cross-ai-deployment-bundle.v1+json"
REVIEW_PAYLOAD_TYPE = "application/vnd.acik.cross-ai-deployment-review.v1+json"
REVOCATIONS_PAYLOAD_TYPE = (
    "application/vnd.acik.cross-ai-deployment-revocations.v1+json"
)
RUNNER_ADMISSION_LEASE_PAYLOAD_TYPE = (
    "application/vnd.acik.cross-ai-runner-admission-lease.v1+json"
)
SESSION_DOMAIN = "acik.cross-ai-deployment-session.v1"
CLOSURE_DOMAIN = "acik.cross-ai-deployment-closure.v1"
MAX_GRANT_TTL = timedelta(minutes=120)


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
    ) -> None:
        self.now = now or utc_now()
        self.expected_policy_sha256 = expected_policy_sha256
        self.trust_root = trust_root
        if (
            expected_trust_root_sha256 is not None
            and sha256_digest(trust_root) != expected_trust_root_sha256
        ):
            reject(
                "TRUST_ROOT_DIGEST_MISMATCH",
                "trust root differs from the deployment-configured digest",
            )
        _validate_schema(trust_root, TRUST_ROOT_SCHEMA, "TRUST_ROOT_SCHEMA_INVALID")
        self.max_skew = timedelta(seconds=trust_root["maxClockSkewSeconds"])
        self.required_provider_families = frozenset(
            trust_root["requiredProviderFamilies"]
        )
        self.minimum_provider_families = trust_root["minimumProviderFamilies"]
        self.minimum_direct_routes = trust_root["minimumDirectProviderRoutes"]
        self.keys = self._parse_trust_keys(trust_root)
        self._validate_trust_root_lifetime()
        self.revocations_envelope = self._verify_revocations(revocations_envelope)
        self.revocations = self.revocations_envelope.payload

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

    def _active_keys(self, role: str) -> dict[str, bytes]:
        active: dict[str, bytes] = {}
        for key in self.keys.values():
            if key.role != role:
                continue
            if (
                key.not_before <= self.now + self.max_skew
                and key.not_after >= self.now - self.max_skew
            ):
                active[key.key_id] = key.public_key
        if not active:
            reject("TRUST_ACTIVE_KEY_MISSING", f"no active {role} key is available")
        return active

    def _verify_revocations(self, envelope: dict[str, Any]) -> VerifiedEnvelope:
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
        if next_update < self.now - self.max_skew:
            reject("REVOCATIONS_STALE", "revocation set nextUpdate is stale")
        if next_update <= issued_at:
            reject("REVOCATIONS_LIFETIME_INVALID", "revocation set lifetime is invalid")
        signer = self.keys[verified.signing_key_ids[0]]
        self._validate_key_time(signer, issued_at, "revocation", check_revocation=False)
        return verified

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
        for entry in self.revocations["entries"]:
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
            expected_payload_type=BUNDLE_PAYLOAD_TYPE,
            allowed_keys=coordinator_keys,
            exactly_one_signature=True,
        )
        _validate_schema(outer.payload, BUNDLE_SCHEMA, "BUNDLE_SCHEMA_INVALID")
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
                "domain": SESSION_DOMAIN,
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
        provider_keys = self._active_keys("provider-review")
        verified: dict[str, VerifiedReview] = {}
        review_ids: set[str] = set()
        for envelope in bundle["reviewEnvelopes"]:
            leaf_envelope = verify_json_envelope(
                envelope,
                expected_payload_type=REVIEW_PAYLOAD_TYPE,
                allowed_keys=provider_keys,
                exactly_one_signature=True,
            )
            _validate_schema(
                leaf_envelope.payload, REVIEW_SCHEMA, "REVIEW_SCHEMA_INVALID"
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
            if issued_at > self.now + self.max_skew:
                reject("REVIEW_NOT_YET_VALID", "review issue time is in the future")
            if expires_at < self.now - self.max_skew:
                reject("REVIEW_EXPIRED", "review is expired")
            if expires_at <= issued_at:
                reject("REVIEW_LIFETIME_INVALID", "review lifetime is invalid")
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

    def _verify_review_chains(self, reviews: dict[str, VerifiedReview]) -> None:
        chains: dict[str, list[VerifiedReview]] = defaultdict(list)
        for review in reviews.values():
            chains[review.payload["reviewChainId"]].append(review)
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
                "domain": CLOSURE_DOMAIN,
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
            if review.key.direct_provider_cli
            and review.key.provider_family is not None
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
