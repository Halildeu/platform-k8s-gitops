#!/usr/bin/env python3
"""Verify the one-time public-authority stage/activation transition.

This program is intended to run only from the immutable default-branch
workflow behind the protected ``cross-ai-provider-review-genesis`` Environment.
It reads PR-head JSON as data, never imports or executes PR-head code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ai.cross_ai_authority import (
    GENESIS_PATH,
    GENESIS_SCHEMA,
    MANIFEST_PATH,
    MANIFEST_SCHEMA,
    AuthorityUnavailable,
    load_staged_activation_authority,
    require_active_codex_provider_key,
)
from scripts.ai.prepare_cross_ai_scope import MAX_SCOPE_BYTES, derive_scope
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import load_json_file


GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class TransitionError(ValueError):
    pass


def git(root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TransitionError("genesis git binding is invalid") from exc


def git_json(root: Path, revision: str, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(git(root, "show", f"{revision}:{path.as_posix()}"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TransitionError(f"{path} is not strict JSON at the requested revision") from exc
    if not isinstance(value, dict):
        raise TransitionError(f"{path} is not a JSON object")
    return value


def validate(value: Any, schema: dict[str, Any], label: str) -> dict[str, Any]:
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors or not isinstance(value, dict):
        raise TransitionError(f"{label} is invalid")
    return value


def exact_git_binding(root: Path, base_tip: str, base: str, head: str) -> None:
    if not all(GIT_SHA.fullmatch(value) for value in (base_tip, base, head)):
        raise TransitionError("genesis coordinate format is invalid")
    current = git(root, "rev-parse", "HEAD").decode().strip().lower()
    merge_base = git(root, "merge-base", base_tip, head).decode().strip().lower()
    if current != base_tip or base != base_tip or merge_base != base:
        raise TransitionError("genesis requires exact default-branch base tip")


def stage_public_authority(
    root: Path, *, base: str, head: str, now: datetime
) -> dict[str, Any]:
    genesis_schema = load_json_file(root / GENESIS_SCHEMA)
    manifest_schema = load_json_file(root / MANIFEST_SCHEMA)
    base_genesis = validate(
        load_json_file(root / GENESIS_PATH), genesis_schema, "base genesis contract"
    )
    base_manifest = validate(
        load_json_file(root / MANIFEST_PATH), manifest_schema, "base authority manifest"
    )
    if base_genesis["status"] != "installed" or base_manifest["status"] != "tracked_pending":
        raise TransitionError("genesis installation is not pending a public authority")
    expected_paths = base_genesis["transitionContract"]["stagePublicAuthority"][
        "exactChangedPaths"
    ]
    changed = sorted(
        line for line in git(
            root, "diff", "--name-only", "--no-renames", f"{base}...{head}"
        ).decode("utf-8", errors="strict").splitlines() if line
    )
    if changed != expected_paths:
        raise TransitionError("public-authority stage changes paths outside genesis")

    head_genesis = validate(
        git_json(root, head, GENESIS_PATH), genesis_schema, "head genesis contract"
    )
    expected_head = dict(base_genesis)
    expected_head.update(
        {
            "status": "staged",
            "trustRootPath": "config/github-apps/cross-ai-provider-review-trust-root.v2.json",
            "revocationsPath": "config/github-apps/cross-ai-provider-review-revocations.v1.dsse.json",
            "expectedTrustRootSha256": head_genesis.get("expectedTrustRootSha256"),
            "issuerRuntimePolicy": head_genesis.get("issuerRuntimePolicy"),
        }
    )
    if head_genesis != expected_head:
        raise TransitionError("public-authority stage mutates the genesis contract")
    trust_root = git_json(root, head, Path(head_genesis["trustRootPath"]))
    revocations = git_json(root, head, Path(head_genesis["revocationsPath"]))
    expected_pin = head_genesis["expectedTrustRootSha256"]
    if sha256_digest(trust_root) != expected_pin:
        raise TransitionError("staged trust-root digest does not match genesis pin")
    try:
        verifier = EvidenceVerifier(
            trust_root=trust_root,
            revocations_envelope=revocations,
            now=now,
            expected_trust_root_sha256=expected_pin,
        )
        verifier.require_active_signing_key(
            key_id=head_genesis["issuerRuntimePolicy"]["attestorKeyId"],
            role="runner-management",
            issued_at=now,
        )
        require_active_codex_provider_key(
            verifier,
            trust_root,
            issued_at=now,
        )
    except PolicyError as exc:
        raise TransitionError(f"staged public authority is invalid: {exc.code}") from exc
    if git_json(root, head, MANIFEST_PATH) != base_manifest:
        raise TransitionError("stage PR must not activate the public authority locator")
    return {
        "statusBefore": "installed",
        "statusAfter": "staged",
        "trustRootSha256": expected_pin,
    }


def write_exclusive(path: Path, content: bytes) -> None:
    target = path.expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise TransitionError("genesis attestation output is not create-once") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("stage", "activate"), required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--base-tip-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        root = args.repo_root.expanduser().resolve()
        exact_git_binding(root, args.base_tip_sha, args.base_sha, args.head_sha)
        scope_bytes, _, _ = derive_scope(
            root,
            base_tip_sha=args.base_tip_sha,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            max_scope_bytes=MAX_SCOPE_BYTES,
            scan_secrets=False,
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if args.phase == "stage":
            transition = stage_public_authority(
                root, base=args.base_sha, head=args.head_sha, now=now
            )
        else:
            load_staged_activation_authority(
                root,
                expected_bindings={
                    "base_tip_sha": args.base_tip_sha,
                    "base_sha": args.base_sha,
                    "head_sha": args.head_sha,
                    "scope_sha256": hashlib.sha256(scope_bytes).hexdigest(),
                },
                scope_bytes=scope_bytes,
                now=now,
            )
            transition = {
                "statusBefore": "staged",
                "statusAfter": "retired",
                "trustRootSha256": load_json_file(root / GENESIS_PATH)[
                    "expectedTrustRootSha256"
                ],
            }
        attestation = {
            "schemaVersion": "acik.cross-ai-provider-review-genesis-attestation.v1",
            "phase": args.phase,
            "baseTipSha": args.base_tip_sha,
            "baseSha": args.base_sha,
            "headSha": args.head_sha,
            "scopeSha256": "sha256:" + hashlib.sha256(scope_bytes).hexdigest(),
            "environment": "cross-ai-provider-review-genesis",
            "workflowPath": ".github/workflows/cross-ai-provider-review-genesis.yml",
            "verifiedAt": now.isoformat().replace("+00:00", "Z"),
            **transition,
        }
        rendered = json.dumps(
            attestation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        write_exclusive(args.output, rendered)
        print(rendered.decode("utf-8"))
        return 0
    except (AuthorityUnavailable, TransitionError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
