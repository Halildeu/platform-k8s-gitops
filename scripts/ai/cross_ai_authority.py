"""Load the fixed public provider-review authority from the trusted repo tree."""

from __future__ import annotations

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


class AuthorityUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class PublicReviewAuthority:
    trust_root: dict[str, Any]
    revocations_envelope: dict[str, Any]
    expected_trust_root_sha256: str
    codex_executable_policy: dict[str, Any]


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
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(manifest),
        key=lambda item: list(item.path),
    )
    if errors:
        raise AuthorityUnavailable("provider-review authority manifest is invalid")
    if manifest["status"] != "active":
        raise AuthorityUnavailable("provider-review public authority is tracked_pending")
    trust_path = (root / manifest["trustRootPath"]).resolve()
    revocations_path = (root / manifest["revocationsPath"]).resolve()
    config_root = (root / "config/github-apps").resolve()
    if config_root not in trust_path.parents or config_root not in revocations_path.parents:
        raise AuthorityUnavailable("provider-review authority path escapes the fixed config root")
    try:
        trust_root = load_json_file(trust_path)
        revocations = load_json_file(revocations_path)
    except Exception as exc:
        raise AuthorityUnavailable("provider-review public authority resource is unavailable") from exc
    expected = manifest["expectedTrustRootSha256"]
    if sha256_digest(trust_root) != expected:
        raise AuthorityUnavailable("provider-review trust-root pin mismatch")
    try:
        EvidenceVerifier(
            trust_root=trust_root,
            revocations_envelope=revocations,
            now=now or utc_now(),
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
        codex_executable_policy=manifest["codexExecutablePolicy"],
    )


__all__ = ["AuthorityUnavailable", "PublicReviewAuthority", "load_active_authority"]
