"""Load the fixed public provider-review authority from the trusted repo tree."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.dsse import decode_public_key
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import load_json_file
from scripts.github_apps.cross_ai_deployment_policy.timeutil import parse_utc, utc_now


MANIFEST_PATH = Path("config/github-apps/cross-ai-provider-review-authority.v1.json")
MANIFEST_SCHEMA = Path("schema/cross-ai-provider-review-authority-v1.schema.json")
GENESIS_PATH = Path("config/github-apps/cross-ai-provider-review-genesis.v1.json")
GENESIS_SCHEMA = Path("schema/cross-ai-provider-review-genesis-v1.schema.json")


class AuthorityUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class PublicReviewAuthority:
    trust_root: dict[str, Any]
    revocations_envelope: dict[str, Any]
    expected_trust_root_sha256: str
    codex_executable_policy: dict[str, Any]
    issuer_runtime_policy: dict[str, Any]
    observed_at: datetime


def require_active_codex_provider_key(
    verifier: EvidenceVerifier,
    trust_root: dict[str, Any],
    *,
    issued_at: datetime,
) -> None:
    """Require at least one usable direct-Codex provider key at the boundary."""

    candidates = [
        key
        for key in trust_root.get("keys", [])
        if key.get("role") == "provider-review"
        and key.get("providerFamily") == "openai"
    ]
    for key in candidates:
        try:
            verifier.require_active_signing_key(
                key_id=key["keyId"],
                role="provider-review",
                provider_family="openai",
                issued_at=issued_at,
            )
            return
        except (KeyError, PolicyError):
            continue
    raise AuthorityUnavailable(
        "provider-review public authority has no active OpenAI provider key"
    )


def _validate_document(value: Any, schema: dict[str, Any], label: str) -> dict[str, Any]:
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors or not isinstance(value, dict):
        raise AuthorityUnavailable(f"provider-review {label} is invalid")
    return value


def _fixed_config_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    config_root = (root / "config/github-apps").resolve()
    if config_root not in path.parents:
        raise AuthorityUnavailable("provider-review authority path escapes the fixed config root")
    return path


def _load_public_authority(
    root: Path,
    locator: dict[str, Any],
    *,
    now: datetime,
    review_reference_time: datetime | None = None,
) -> PublicReviewAuthority:
    trust_path = _fixed_config_path(root, locator["trustRootPath"])
    revocations_path = _fixed_config_path(root, locator["revocationsPath"])
    try:
        trust_root = load_json_file(trust_path)
        revocations = load_json_file(revocations_path)
    except Exception as exc:
        raise AuthorityUnavailable(
            "provider-review public authority resource is unavailable"
        ) from exc
    expected = locator["expectedTrustRootSha256"]
    if sha256_digest(trust_root) != expected:
        raise AuthorityUnavailable("provider-review trust-root pin mismatch")
    if (
        locator.get("expectedRevocationsSha256") is not None
        and sha256_digest(revocations) != locator["expectedRevocationsSha256"]
    ):
        raise AuthorityUnavailable("provider-review revocation snapshot pin mismatch")
    try:
        verifier = EvidenceVerifier(
            trust_root=trust_root,
            revocations_envelope=revocations,
            now=now,
            expected_trust_root_sha256=expected,
            review_reference_time=review_reference_time,
        )
        verifier.require_active_signing_key(
            key_id=locator["issuerRuntimePolicy"]["attestorKeyId"],
            role="runner-management",
            issued_at=review_reference_time or now,
        )
        require_active_codex_provider_key(
            verifier,
            trust_root,
            issued_at=review_reference_time or now,
        )
    except PolicyError as exc:
        raise AuthorityUnavailable(
            f"provider-review public authority is not active: {exc.code}"
        ) from exc
    return PublicReviewAuthority(
        trust_root=trust_root,
        revocations_envelope=revocations,
        expected_trust_root_sha256=expected,
        codex_executable_policy=locator["codexExecutablePolicy"],
        issuer_runtime_policy=locator["issuerRuntimePolicy"],
        observed_at=now,
    )


def _git(root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AuthorityUnavailable("provider-review genesis git binding is invalid") from exc


def _git_blob(root: Path, revision: str, path: Path) -> bytes:
    return _git(root, "show", f"{revision}:{path.as_posix()}")


def _git_json(root: Path, revision: str, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_git_blob(root, revision, path))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityUnavailable("provider-review genesis head document is invalid") from exc
    if not isinstance(value, dict):
        raise AuthorityUnavailable("provider-review genesis head document is invalid")
    return value


def load_active_authority(
    repo_root: Path, *, now: datetime | None = None
) -> PublicReviewAuthority:
    root = repo_root.expanduser().resolve()
    manifest_path = root / MANIFEST_PATH
    schema_path = root / MANIFEST_SCHEMA
    try:
        manifest = load_json_file(manifest_path)
        schema = load_json_file(schema_path)
    except Exception as exc:
        raise AuthorityUnavailable("provider-review authority manifest is unavailable") from exc
    manifest = _validate_document(manifest, schema, "authority manifest")
    if manifest["status"] != "active":
        raise AuthorityUnavailable("provider-review public authority is tracked_pending")
    return _load_public_authority(root, manifest, now=now or utc_now())


def load_authority_for_evidence(
    repo_root: Path,
    *,
    expected_trust_root_sha256: str,
    observed_at: datetime,
    evidence_reference_time: datetime,
) -> PublicReviewAuthority:
    """Resolve current or immutable retired authority for durable evidence."""

    root = repo_root.expanduser().resolve()
    try:
        manifest = _validate_document(
            load_json_file(root / MANIFEST_PATH),
            load_json_file(root / MANIFEST_SCHEMA),
            "authority manifest",
        )
    except Exception as exc:
        if isinstance(exc, AuthorityUnavailable):
            raise
        raise AuthorityUnavailable(
            "provider-review authority history is unavailable"
        ) from exc
    if (
        manifest["status"] == "active"
        and manifest["expectedTrustRootSha256"]
        == expected_trust_root_sha256
    ):
        return _load_public_authority(root, manifest, now=observed_at)
    matches = [
        entry for entry in manifest["historicalAuthorities"]
        if entry["expectedTrustRootSha256"] == expected_trust_root_sha256
    ]
    if len(matches) != 1:
        raise AuthorityUnavailable(
            "provider-review evidence trust root is not uniquely archived"
        )
    historical = matches[0]
    digest = expected_trust_root_sha256.removeprefix("sha256:")
    expected_directory = f"config/github-apps/cross-ai-provider-review-history/{digest}/"
    if not (
        historical["trustRootPath"].startswith(expected_directory)
        and historical["revocationsPath"].startswith(expected_directory)
    ):
        raise AuthorityUnavailable(
            "provider-review authority history path is not content-addressed"
        )
    retired_at = parse_utc(historical["retiredAt"], "historicalAuthority.retiredAt")
    if retired_at > observed_at:
        raise AuthorityUnavailable(
            "provider-review authority retirement is future-dated"
        )
    if evidence_reference_time >= retired_at:
        raise AuthorityUnavailable(
            "provider-review evidence was issued after its authority retired"
        )
    return _load_public_authority(
        root,
        historical,
        # The archived envelope is the final signed revocation view for this
        # authority generation.  Rotation validation already proved that the
        # replacement authority and its revocations were fresh at observation;
        # replay must therefore validate the predecessor snapshot at its
        # immutable retirement boundary, not against the current wall clock.
        now=retired_at,
        review_reference_time=evidence_reference_time,
    )


def validate_authority_history_transition(
    repo_root: Path,
    *,
    expected_bindings: dict[str, str],
    now: datetime | None = None,
) -> None:
    """Keep retired authority material append-only across a root rotation.

    The checkout is the trusted target-branch tip.  Head documents are parsed
    as data only.  A root digest may change only when the old active root and
    its final signed revocation snapshot are copied byte-for-byte into a
    content-addressed history directory and one exact manifest entry is
    appended.  Existing history can never be edited or removed.
    """

    required_bindings = {"base_tip_sha", "base_sha", "head_sha", "scope_sha256"}
    if set(expected_bindings) != required_bindings:
        raise AuthorityUnavailable("provider-review history binding set is invalid")
    root = repo_root.expanduser().resolve()
    base_tip = expected_bindings["base_tip_sha"]
    base = expected_bindings["base_sha"]
    head = expected_bindings["head_sha"]
    current = _git(root, "rev-parse", "HEAD").decode().strip().lower()
    merge_base = _git(root, "merge-base", base_tip, head).decode().strip().lower()
    if current != base_tip or base != base_tip or merge_base != base:
        raise AuthorityUnavailable(
            "provider-review history validation requires the exact trusted base tip"
        )

    changed = {
        line
        for line in _git(
            root, "diff", "--name-only", "--no-renames", f"{base}...{head}"
        ).decode("utf-8", errors="strict").splitlines()
        if line
    }
    manifest_name = MANIFEST_PATH.as_posix()
    history_prefix = "config/github-apps/cross-ai-provider-review-history/"
    history_changes = {path for path in changed if path.startswith(history_prefix)}
    try:
        schema = load_json_file(root / MANIFEST_SCHEMA)
        base_manifest = _validate_document(
            load_json_file(root / MANIFEST_PATH), schema, "authority manifest"
        )
        head_manifest = (
            _validate_document(
                _git_json(root, head, MANIFEST_PATH), schema, "head authority manifest"
            )
            if manifest_name in changed
            else base_manifest
        )
    except Exception as exc:
        if isinstance(exc, AuthorityUnavailable):
            raise
        raise AuthorityUnavailable(
            "provider-review authority history contract is unavailable"
        ) from exc

    base_revocations_path = base_manifest.get("revocationsPath")
    head_revocations_path = head_manifest.get("revocationsPath")
    revocations_changed = any(
        isinstance(path, str) and path in changed
        for path in (base_revocations_path, head_revocations_path)
    )
    if (
        revocations_changed
        and base_manifest["status"] == "active"
        and head_manifest["status"] == "active"
        and base_manifest["expectedTrustRootSha256"]
        == head_manifest["expectedTrustRootSha256"]
    ):
        if base_revocations_path != head_revocations_path:
            raise AuthorityUnavailable(
                "provider-review same-root revocation path is immutable"
            )
        try:
            trust_root = _git_json(
                root, head, Path(head_manifest["trustRootPath"])
            )
            predecessor = _git_json(root, base, Path(base_revocations_path))
            replacement = _git_json(root, head, Path(head_revocations_path))
            if sha256_digest(trust_root) != head_manifest["expectedTrustRootSha256"]:
                raise AuthorityUnavailable(
                    "provider-review same-root revocation pin mismatch"
                )
            verifier = EvidenceVerifier(
                trust_root=trust_root,
                revocations_envelope=replacement,
                now=now or utc_now(),
                expected_trust_root_sha256=head_manifest[
                    "expectedTrustRootSha256"
                ],
            )
            verifier.require_monotonic_revocation_predecessor(
                predecessor, require_stale=False
            )
        except PolicyError as exc:
            raise AuthorityUnavailable(
                f"provider-review same-root revocation transition is invalid: {exc.code}"
            ) from exc

    if manifest_name not in changed:
        if history_changes:
            raise AuthorityUnavailable(
                "provider-review archived authority changed without a manifest rotation"
            )
        return

    base_history = base_manifest["historicalAuthorities"]
    head_history = head_manifest["historicalAuthorities"]
    base_digest = base_manifest["expectedTrustRootSha256"]
    head_digest = head_manifest["expectedTrustRootSha256"]

    if base_manifest["status"] != "active":
        if head_history != base_history or history_changes:
            raise AuthorityUnavailable(
                "provider-review genesis cannot mutate retired authority history"
            )
        return
    if head_manifest["status"] != "active":
        raise AuthorityUnavailable(
            "provider-review active authority cannot be retired without a replacement"
        )
    if head_digest == base_digest:
        if head_history != base_history or history_changes:
            raise AuthorityUnavailable(
                "provider-review retired authority history is immutable"
            )
        if (
            head_manifest["codexExecutablePolicy"]
            != base_manifest["codexExecutablePolicy"]
            or head_manifest["issuerRuntimePolicy"]
            != base_manifest["issuerRuntimePolicy"]
        ):
            raise AuthorityUnavailable(
                "provider-review executable or runtime policy requires a root rotation"
            )
        return

    if not isinstance(base_digest, str) or not isinstance(head_digest, str):
        raise AuthorityUnavailable("provider-review root rotation digest is unavailable")
    old_digest_hex = base_digest.removeprefix("sha256:")
    archive_root_path = (
        f"{history_prefix}{old_digest_hex}/trust-root.v2.json"
    )
    archive_revocations_path = (
        f"{history_prefix}{old_digest_hex}/revocations.v1.dsse.json"
    )
    if history_changes != {archive_root_path, archive_revocations_path}:
        raise AuthorityUnavailable(
            "provider-review root rotation must add only the exact archived authority files"
        )

    try:
        old_root_path = Path(base_manifest["trustRootPath"])
        old_revocations_path = Path(base_manifest["revocationsPath"])
        old_root_raw = _git_blob(root, base, old_root_path)
        old_revocations_raw = _git_blob(root, base, old_revocations_path)
        archived_root_raw = _git_blob(root, head, Path(archive_root_path))
        archived_revocations_raw = _git_blob(
            root, head, Path(archive_revocations_path)
        )
        old_root = json.loads(old_root_raw)
        old_revocations = json.loads(old_revocations_raw)
        archived_root = json.loads(archived_root_raw)
        archived_revocations = json.loads(archived_revocations_raw)
        new_root = _git_json(root, head, Path(head_manifest["trustRootPath"]))
        new_revocations = _git_json(
            root, head, Path(head_manifest["revocationsPath"])
        )
    except Exception as exc:
        if isinstance(exc, AuthorityUnavailable):
            raise
        raise AuthorityUnavailable(
            "provider-review root rotation resource is unavailable"
        ) from exc
    if sha256_digest(old_root) != base_digest:
        raise AuthorityUnavailable("provider-review predecessor trust-root pin mismatch")
    if (
        archived_root_raw != old_root_raw
        or archived_revocations_raw != old_revocations_raw
        or archived_root != old_root
        or archived_revocations != old_revocations
    ):
        raise AuthorityUnavailable(
            "provider-review root rotation archive does not match the trusted predecessor"
        )
    if sha256_digest(new_root) != head_digest:
        raise AuthorityUnavailable("provider-review replacement trust-root pin mismatch")

    try:
        historical_roots = [
            _git_json(root, base, Path(entry["trustRootPath"]))
            for entry in base_history
        ]

        def identity(key: dict[str, Any]) -> tuple[Any, ...]:
            return (
                key["keyId"],
                key["role"],
                key["providerFamily"],
                tuple(key["allowedChannels"]),
                tuple(key["allowedModelIds"]),
                tuple(key["allowedModelIdentityClasses"]),
                key["directProviderCli"],
                key["notBefore"],
                key["notAfter"],
            )

        immediate_keys = {
            decode_public_key(key["publicKeyBase64"], key["keyId"]): identity(key)
            for key in old_root["keys"]
        }
        historical_keys = {
            decode_public_key(key["publicKeyBase64"], key["keyId"])
            for trust_root in historical_roots
            for key in trust_root["keys"]
        }
        replacement_keys = [
            (
                decode_public_key(key["publicKeyBase64"], key["keyId"]),
                identity(key),
            )
            for key in new_root["keys"]
        ]
    except (KeyError, TypeError, PolicyError) as exc:
        raise AuthorityUnavailable(
            "provider-review rotation public-key history is invalid"
        ) from exc
    for public_key, replacement_identity in replacement_keys:
        if public_key in immediate_keys:
            if replacement_identity != immediate_keys[public_key]:
                raise AuthorityUnavailable(
                    "provider-review replacement reassigns a predecessor public key"
                )
        elif public_key in historical_keys:
            raise AuthorityUnavailable(
                "provider-review replacement resurrects a retired public key"
            )

    retired_at_text = new_root.get("issuedAt")
    if not isinstance(retired_at_text, str):
        raise AuthorityUnavailable("provider-review replacement issuance time is invalid")
    retired_at = parse_utc(retired_at_text, "replacementTrustRoot.issuedAt")
    old_issued_at = parse_utc(old_root.get("issuedAt"), "predecessorTrustRoot.issuedAt")
    old_expires_at = parse_utc(old_root.get("expiresAt"), "predecessorTrustRoot.expiresAt")
    observed = now or utc_now()
    max_skew = old_root.get("maxClockSkewSeconds")
    maximum_past_seconds = (
        base_manifest["rotationPolicy"]["maxReviewLeafLifetimeMinutes"] * 60
    )
    if (
        not isinstance(max_skew, int)
        or retired_at <= old_issued_at
        or retired_at >= old_expires_at
        or (retired_at - observed).total_seconds() > max_skew
        or (observed - retired_at).total_seconds() > maximum_past_seconds
    ):
        raise AuthorityUnavailable(
            "provider-review replacement issuance is outside the predecessor boundary"
        )

    minimum_overlap = timedelta(
        hours=base_manifest["rotationPolicy"]["minimumKeyOverlapHours"]
    )
    overlap_deadline = retired_at + minimum_overlap
    shared_provider_overlap = False
    for key in new_root["keys"]:
        if key.get("role") != "provider-review" or key.get("providerFamily") != "openai":
            continue
        public_key = decode_public_key(key["publicKeyBase64"], key["keyId"])
        if public_key not in immediate_keys or identity(key) != immediate_keys[public_key]:
            continue
        not_before = parse_utc(key["notBefore"], "providerKey.notBefore")
        not_after = parse_utc(key["notAfter"], "providerKey.notAfter")
        if not_before <= retired_at and not_after >= overlap_deadline:
            shared_provider_overlap = True
            break
    if not shared_provider_overlap:
        raise AuthorityUnavailable(
            "provider-review root rotation lacks the required provider key overlap"
        )

    expected_history_entry = {
        "trustRootPath": archive_root_path,
        "revocationsPath": archive_revocations_path,
        "expectedTrustRootSha256": base_digest,
        "expectedRevocationsSha256": sha256_digest(old_revocations),
        "codexExecutablePolicy": base_manifest["codexExecutablePolicy"],
        "issuerRuntimePolicy": base_manifest["issuerRuntimePolicy"],
        "retiredAt": retired_at_text,
    }
    if head_history != [*base_history, expected_history_entry]:
        raise AuthorityUnavailable(
            "provider-review root rotation must append the exact predecessor authority"
        )

    try:
        predecessor_verifier = EvidenceVerifier(
            trust_root=old_root,
            revocations_envelope=old_revocations,
            now=retired_at,
            expected_trust_root_sha256=base_digest,
        )
        verifier = EvidenceVerifier(
            trust_root=new_root,
            revocations_envelope=new_revocations,
            now=observed,
            expected_trust_root_sha256=head_digest,
            review_reference_time=retired_at,
        )
        verifier.require_active_signing_key(
            key_id=head_manifest["issuerRuntimePolicy"]["attestorKeyId"],
            role="runner-management",
            issued_at=retired_at,
        )
        require_active_codex_provider_key(
            verifier,
            new_root,
            issued_at=retired_at,
        )
        predecessor_entries = {
            sha256_digest(entry)
            for entry in predecessor_verifier.revocations["entries"]
        }
        replacement_entries = {
            sha256_digest(entry) for entry in verifier.revocations["entries"]
        }
        if not predecessor_entries.issubset(replacement_entries):
            raise AuthorityUnavailable(
                "provider-review replacement omits a predecessor revocation"
            )
    except AuthorityUnavailable:
        raise
    except PolicyError as exc:
        raise AuthorityUnavailable(
            f"provider-review replacement authority is invalid: {exc.code}"
        ) from exc


def load_staged_activation_authority(
    repo_root: Path,
    *,
    expected_bindings: dict[str, str],
    scope_bytes: bytes,
    now: datetime | None = None,
) -> PublicReviewAuthority:
    """Authorize only the exact staged -> active one-time transition.

    The trusted base owns the staged public root and this verifier.  The PR head
    may change only the locator and retire the one-time genesis record; no head
    code, schema, trust root or revocation bytes are executed or trusted.
    """

    root = repo_root.expanduser().resolve()
    required_bindings = {"base_tip_sha", "base_sha", "head_sha", "scope_sha256"}
    if set(expected_bindings) != required_bindings:
        raise AuthorityUnavailable("provider-review genesis binding set is invalid")
    scope_sha256 = hashlib.sha256(scope_bytes).hexdigest()
    if scope_sha256 != expected_bindings["scope_sha256"]:
        raise AuthorityUnavailable("provider-review genesis scope digest mismatch")
    base_tip = expected_bindings["base_tip_sha"]
    base = expected_bindings["base_sha"]
    head = expected_bindings["head_sha"]
    current = _git(root, "rev-parse", "HEAD").decode().strip().lower()
    merge_base = _git(root, "merge-base", base_tip, head).decode().strip().lower()
    if current != base_tip or base != base_tip or merge_base != base:
        raise AuthorityUnavailable("provider-review genesis requires the exact trusted base tip")

    try:
        genesis = load_json_file(root / GENESIS_PATH)
        genesis_schema = load_json_file(root / GENESIS_SCHEMA)
        manifest = load_json_file(root / MANIFEST_PATH)
        manifest_schema = load_json_file(root / MANIFEST_SCHEMA)
    except Exception as exc:
        raise AuthorityUnavailable("provider-review genesis contract is unavailable") from exc
    genesis = _validate_document(genesis, genesis_schema, "genesis contract")
    manifest = _validate_document(manifest, manifest_schema, "authority manifest")
    if genesis["status"] != "staged" or manifest["status"] != "tracked_pending":
        raise AuthorityUnavailable("provider-review genesis is not staged")

    expected_paths = genesis["transitionContract"]["activateAuthority"][
        "exactChangedPaths"
    ]
    changed = sorted(
        line for line in _git(
            root, "diff", "--name-only", "--no-renames", f"{base}...{head}"
        ).decode("utf-8", errors="strict").splitlines() if line
    )
    if changed != expected_paths:
        raise AuthorityUnavailable("provider-review activation changes paths outside genesis")

    head_genesis = _validate_document(
        _git_json(root, head, GENESIS_PATH), genesis_schema, "head genesis contract"
    )
    expected_head_genesis = dict(genesis)
    expected_head_genesis["status"] = "retired"
    if head_genesis != expected_head_genesis:
        raise AuthorityUnavailable("provider-review genesis retirement is not exact")

    head_manifest = _validate_document(
        _git_json(root, head, MANIFEST_PATH), manifest_schema, "head authority manifest"
    )
    expected_head_manifest = dict(manifest)
    expected_head_manifest.update(
        {
            "status": "active",
            "trustRootPath": genesis["trustRootPath"],
            "revocationsPath": genesis["revocationsPath"],
            "expectedTrustRootSha256": genesis["expectedTrustRootSha256"],
            "issuerRuntimePolicy": genesis["issuerRuntimePolicy"],
        }
    )
    if head_manifest != expected_head_manifest:
        raise AuthorityUnavailable("provider-review authority activation is not exact")

    staged_locator = dict(expected_head_manifest)
    return _load_public_authority(root, staged_locator, now=now or utc_now())


def load_revocation_refresh_authority(
    repo_root: Path,
    *,
    expected_bindings: dict[str, str],
    scope_bytes: bytes,
    now: datetime | None = None,
    require_stale_predecessor: bool = True,
) -> PublicReviewAuthority:
    """Load only a signed, monotonic, revocations-file-only stale recovery.

    The verifier and trust root come from the exact trusted base. The PR head
    contributes only a fresh DSSE revocation envelope signed by the already
    pinned revocation authority. Normal high-impact Codex review is still
    required; this function merely prevents a missed 60-minute refresh window
    from making that review cryptographically impossible.
    """

    root = repo_root.expanduser().resolve()
    required_bindings = {"base_tip_sha", "base_sha", "head_sha", "scope_sha256"}
    if set(expected_bindings) != required_bindings:
        raise AuthorityUnavailable("provider-review revocation recovery binding set is invalid")
    if hashlib.sha256(scope_bytes).hexdigest() != expected_bindings["scope_sha256"]:
        raise AuthorityUnavailable("provider-review revocation recovery scope digest mismatch")
    base_tip = expected_bindings["base_tip_sha"]
    base = expected_bindings["base_sha"]
    head = expected_bindings["head_sha"]
    current = _git(root, "rev-parse", "HEAD").decode().strip().lower()
    merge_base = _git(root, "merge-base", base_tip, head).decode().strip().lower()
    if current != base_tip or base != base_tip or merge_base != base:
        raise AuthorityUnavailable(
            "provider-review revocation recovery requires the exact trusted base tip"
        )
    try:
        manifest = _validate_document(
            load_json_file(root / MANIFEST_PATH),
            load_json_file(root / MANIFEST_SCHEMA),
            "authority manifest",
        )
    except Exception as exc:
        if isinstance(exc, AuthorityUnavailable):
            raise
        raise AuthorityUnavailable(
            "provider-review revocation recovery contract is unavailable"
        ) from exc
    locator = manifest
    if manifest["status"] == "tracked_pending":
        try:
            genesis = _validate_document(
                load_json_file(root / GENESIS_PATH),
                load_json_file(root / GENESIS_SCHEMA),
                "genesis contract",
            )
        except Exception as exc:
            if isinstance(exc, AuthorityUnavailable):
                raise
            raise AuthorityUnavailable(
                "provider-review staged revocation recovery contract is unavailable"
            ) from exc
        if genesis["status"] != "staged":
            raise AuthorityUnavailable(
                "provider-review revocation recovery requires active or staged authority"
            )
        locator = {
            **manifest,
            "trustRootPath": genesis["trustRootPath"],
            "revocationsPath": genesis["revocationsPath"],
            "expectedTrustRootSha256": genesis["expectedTrustRootSha256"],
            "issuerRuntimePolicy": genesis["issuerRuntimePolicy"],
        }
    elif manifest["status"] != "active":
        raise AuthorityUnavailable(
            "provider-review revocation recovery requires active or staged authority"
        )
    revocations_path = Path(locator["revocationsPath"])
    expected_path = "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json"
    if revocations_path.as_posix() != expected_path:
        raise AuthorityUnavailable("provider-review revocation recovery path is not canonical")
    changed = sorted(
        line for line in _git(
            root, "diff", "--name-only", "--no-renames", f"{base}...{head}"
        ).decode("utf-8", errors="strict").splitlines() if line
    )
    if changed != [expected_path]:
        raise AuthorityUnavailable(
            "provider-review revocation recovery changes paths outside the signed release"
        )
    trust_root = load_json_file(_fixed_config_path(root, locator["trustRootPath"]))
    predecessor = load_json_file(_fixed_config_path(root, locator["revocationsPath"]))
    replacement = _git_json(root, head, revocations_path)
    expected = locator["expectedTrustRootSha256"]
    if sha256_digest(trust_root) != expected:
        raise AuthorityUnavailable("provider-review trust-root pin mismatch")
    observed = now or utc_now()
    try:
        verifier = EvidenceVerifier(
            trust_root=trust_root,
            revocations_envelope=replacement,
            now=observed,
            expected_trust_root_sha256=expected,
        )
        verifier.require_active_signing_key(
            key_id=locator["issuerRuntimePolicy"]["attestorKeyId"],
            role="runner-management",
            issued_at=observed,
        )
        verifier.require_monotonic_revocation_predecessor(
            predecessor,
            require_stale=require_stale_predecessor,
        )
    except PolicyError as exc:
        raise AuthorityUnavailable(
            f"provider-review revocation recovery is invalid: {exc.code}"
        ) from exc
    return PublicReviewAuthority(
        trust_root=trust_root,
        revocations_envelope=replacement,
        expected_trust_root_sha256=expected,
        codex_executable_policy=manifest["codexExecutablePolicy"],
        issuer_runtime_policy=locator["issuerRuntimePolicy"],
        observed_at=observed,
    )


def is_exact_revocation_transition(
    repo_root: Path, *, expected_bindings: dict[str, str]
) -> bool:
    """Classify the sole revocation-file transition from the trusted base."""

    required_bindings = {"base_tip_sha", "base_sha", "head_sha", "scope_sha256"}
    if set(expected_bindings) != required_bindings:
        raise AuthorityUnavailable("provider-review revocation binding set is invalid")
    root = repo_root.expanduser().resolve()
    base_tip = expected_bindings["base_tip_sha"]
    base = expected_bindings["base_sha"]
    head = expected_bindings["head_sha"]
    current = _git(root, "rev-parse", "HEAD").decode().strip().lower()
    merge_base = _git(root, "merge-base", base_tip, head).decode().strip().lower()
    if current != base_tip or base != base_tip or merge_base != base:
        raise AuthorityUnavailable(
            "provider-review revocation classification requires the exact trusted base tip"
        )
    changed = sorted(
        line for line in _git(
            root, "diff", "--name-only", "--no-renames", f"{base}...{head}"
        ).decode("utf-8", errors="strict").splitlines() if line
    )
    return changed == [
        "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json"
    ]


__all__ = [
    "AuthorityUnavailable",
    "PublicReviewAuthority",
    "is_exact_revocation_transition",
    "load_active_authority",
    "load_authority_for_evidence",
    "load_revocation_refresh_authority",
    "load_staged_activation_authority",
    "require_active_codex_provider_key",
    "validate_authority_history_transition",
]
