"""Load the fixed public provider-review authority from the trusted repo tree."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import load_json_file
from scripts.github_apps.cross_ai_deployment_policy.timeutil import utc_now


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
    root: Path, locator: dict[str, Any], *, now: datetime
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
    try:
        EvidenceVerifier(
            trust_root=trust_root,
            revocations_envelope=revocations,
            now=now,
            expected_trust_root_sha256=expected,
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


def _git_json(root: Path, revision: str, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_git(root, "show", f"{revision}:{path.as_posix()}"))
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
        }
    )
    if head_manifest != expected_head_manifest:
        raise AuthorityUnavailable("provider-review authority activation is not exact")

    staged_locator = dict(expected_head_manifest)
    return _load_public_authority(root, staged_locator, now=now or utc_now())


__all__ = [
    "AuthorityUnavailable",
    "PublicReviewAuthority",
    "load_active_authority",
    "load_staged_activation_authority",
]
