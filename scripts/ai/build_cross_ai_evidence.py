#!/usr/bin/env python3
"""Run the fixed direct-Codex route and emit one signed evidence carrier.

No provider response, model identity, git coordinate or signed payload is read
from stdin/argv. The entrypoint derives the exact head/merge-base/sanitized
scope, constructs the canonical prompt, launches DirectCodexRunner, issues the
leaf with the active provider-review Vault Transit key, verifies it against the
independently pinned trust root and writes one create-once v3 carrier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ai.prepare_cross_ai_scope import MAX_SCOPE_BYTES, derive_scope, run_git
from scripts.ai.cross_ai_authority import (
    AuthorityUnavailable,
    PublicReviewAuthority,
    load_active_authority,
)
from scripts.ai.trusted_cross_ai_evidence import (
    EVIDENCE_SCHEMA,
    build_prompt,
    build_subject,
    canonical_bytes,
    validate_evidence,
)
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError, reject
from scripts.github_apps.cross_ai_deployment_policy.provider import (
    CODEX_HIGH_IMPACT_MODEL,
    CODEX_ROUTINE_MODEL,
    DirectCodexRunner,
    EnvelopeSigner,
    ProviderReviewIssuer,
    ReviewCoordinates,
)
from scripts.github_apps.cross_ai_deployment_policy.timeutil import parse_utc, utc_now
from scripts.github_apps.cross_ai_deployment_policy.transit import VaultTransitSigner


MAX_COMMENT_EVIDENCE_BYTES = 256_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--consultation-class",
        choices=("routine", "high-impact"),
        default="high-impact",
    )
    parser.add_argument("--vault-origin", required=True)
    parser.add_argument("--vault-token-file", type=Path, required=True)
    parser.add_argument("--vault-key-version", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _scope(workspace: Path) -> tuple[dict[str, str], bytes]:
    head_sha = run_git(workspace, "rev-parse", "HEAD").lower()
    base_tip_sha = run_git(workspace, "rev-parse", "origin/main").lower()
    base_sha = run_git(workspace, "merge-base", base_tip_sha, head_sha).lower()
    scope_bytes, _, _ = derive_scope(
        workspace,
        base_tip_sha=base_tip_sha,
        base_sha=base_sha,
        head_sha=head_sha,
        max_scope_bytes=MAX_SCOPE_BYTES,
        scan_secrets=True,
    )
    bindings = {
        "base_tip_sha": base_tip_sha,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "scope_sha256": hashlib.sha256(scope_bytes).hexdigest(),
    }
    return bindings, scope_bytes


def _write_exclusive(path: Path, content: bytes) -> None:
    target = path.expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
    except OSError:
        reject("EVIDENCE_OUTPUT_INVALID", "evidence output must be a new writable file")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        reject("EVIDENCE_OUTPUT_INVALID", "evidence output write failed")


def build_signed_evidence(
    args: argparse.Namespace,
    *,
    runner: DirectCodexRunner | None = None,
    signer: EnvelopeSigner | None = None,
    authority: PublicReviewAuthority | None = None,
) -> dict[str, object]:
    if not 30 <= args.timeout_seconds <= 1200:
        reject("PROVIDER_TIMEOUT_INVALID", "provider timeout must be 30-1200 seconds")
    if os.path.lexists(args.output.expanduser().absolute()):
        reject("EVIDENCE_OUTPUT_INVALID", "evidence output must be a new writable file")
    workspace = args.workspace.expanduser().resolve()
    consultation_class = getattr(args, "consultation_class", "high-impact")
    model = (
        CODEX_ROUTINE_MODEL
        if consultation_class == "routine"
        else CODEX_HIGH_IMPACT_MODEL
    )
    if not workspace.is_dir() or not (workspace / ".git").exists():
        reject("PROVIDER_WORKSPACE_INVALID", "workspace is not a git worktree")
    bindings, scope_bytes = _scope(workspace)
    scope_sha256 = f"sha256:{bindings['scope_sha256']}"
    prompt = build_prompt(
        base_tip_sha=bindings["base_tip_sha"],
        base_sha=bindings["base_sha"],
        head_sha=bindings["head_sha"],
        scope_sha256=scope_sha256,
        scope_bytes=scope_bytes,
    )
    subject = build_subject(
        base_tip_sha=bindings["base_tip_sha"],
        base_sha=bindings["base_sha"],
        head_sha=bindings["head_sha"],
        scope_sha256=scope_sha256,
        prompt=prompt,
    )
    now = utc_now().replace(microsecond=0)
    expires = now + timedelta(minutes=90)
    issued_at = now.isoformat().replace("+00:00", "Z")
    expires_at = expires.isoformat().replace("+00:00", "Z")
    subject_sha256 = sha256_digest(subject)
    coordinates = ReviewCoordinates(
        review_id=str(uuid4()),
        review_chain_id=str(uuid4()),
        subject_sha256=subject_sha256,
        round=1,
        previous_round_sha256=None,
        closure_root_sha256=sha256_digest(
            {
                "domain": "acik.cross-ai-single-review-closure.v1",
                "subjectSha256": subject_sha256,
            }
        ),
        issued_at=issued_at,
        expires_at=expires_at,
    )
    active_authority = authority or load_active_authority(workspace, now=now)
    trust_root = active_authority.trust_root
    revocations = active_authority.revocations_envelope
    active_signer = signer or VaultTransitSigner(
        vault_origin=args.vault_origin,
        token_file=args.vault_token_file,
        mount="cross-ai",
        key_name="openai",
        key_version=args.vault_key_version,
    )
    verifier = EvidenceVerifier(
        trust_root=trust_root,
        revocations_envelope=revocations,
        now=now,
        expected_trust_root_sha256=active_authority.expected_trust_root_sha256,
    )
    key = verifier.require_active_signing_key(
        key_id=active_signer.key_id,
        role="provider-review",
        provider_family="openai",
        issued_at=parse_utc(issued_at, "review.issuedAt"),
    )
    if (
        key.allowed_channels != ("openai-codex",)
        or set(key.allowed_model_ids)
        != {CODEX_ROUTINE_MODEL, CODEX_HIGH_IMPACT_MODEL}
        or key.allowed_model_identity_classes != ("trusted-launch-attested",)
        or key.direct_provider_cli is not True
    ):
        reject("TRUST_SIGNER_BINDING_MISMATCH", "provider signer route is not fixed Codex")
    execution = (runner or DirectCodexRunner()).run(
        prompt=prompt,
        model=model,
        workspace=workspace,
        timeout_seconds=args.timeout_seconds,
    )
    envelope = ProviderReviewIssuer(
        signer=active_signer,
        provider_family="openai",
        channel="openai-codex",
        direct_provider_cli=True,
        model_identity_class="trusted-launch-attested",
        allowed_models=frozenset({CODEX_ROUTINE_MODEL, CODEX_HIGH_IMPACT_MODEL}),
        issuer="cross-ai-issuer-openai",
    ).issue(execution=execution, coordinates=coordinates)
    if execution.capability_snapshot is None:
        reject("PROVIDER_LAUNCH_ATTESTATION_MISSING", "Codex launch attestation is missing")
    evidence: dict[str, object] = {
        "schema": EVIDENCE_SCHEMA,
        "subject": subject,
        "capability_snapshot": execution.capability_snapshot,
        "response": execution.result_text,
        "review_envelope": envelope,
        "review_envelope_sha256": sha256_digest(envelope),
        "trust_root_sha256": active_authority.expected_trust_root_sha256,
    }
    validate_evidence(
        evidence,
        trust_root=trust_root,
        revocations_envelope=revocations,
        expected_trust_root_sha256=active_authority.expected_trust_root_sha256,
        expected_bindings=bindings,
        scope_bytes=scope_bytes,
        now=now,
        require_agree=False,
        expected_model=model,
    )
    rendered = canonical_bytes(evidence)
    if len(rendered) > MAX_COMMENT_EVIDENCE_BYTES:
        reject("EVIDENCE_OUTPUT_INVALID", "signed evidence exceeds the GitHub carrier limit")
    _write_exclusive(args.output, rendered)
    return {
        "ok": True,
        "schema": EVIDENCE_SCHEMA,
        "head_sha": bindings["head_sha"],
        "scope_sha256": bindings["scope_sha256"],
        "model_id": model,
        "model_identity_class": "trusted-launch-attested",
        "review_envelope_sha256": sha256_digest(envelope),
        "verdict": json.loads(execution.result_text)["verdict"],
    }


def main() -> int:
    try:
        sys.stdout.buffer.write(canonical_bytes(build_signed_evidence(parse_args())) + b"\n")
        return 0
    except (AuthorityUnavailable, PolicyError, ValueError) as exc:
        code = exc.code if isinstance(exc, PolicyError) else "TRUSTED_EVIDENCE_INVALID"
        message = exc.message if isinstance(exc, PolicyError) else str(exc)
        sys.stdout.buffer.write(
            canonical_bytes({"ok": False, "error": code, "message": message}) + b"\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
