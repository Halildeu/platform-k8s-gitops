#!/usr/bin/env python3
"""Run the fixed direct-Codex route and emit one signed evidence carrier.

No provider response, model identity, git coordinate or signed payload is read
from stdin/argv. The entrypoint derives the exact head/merge-base/sanitized
scope, constructs the canonical prompt, launches DirectCodexRunner, issues the
leaf with the active provider-review Vault Transit key, verifies it against the
independently pinned trust root, requires a second runtime attestation from the
isolated runner-management service and writes one create-once v3 carrier. The
raw CLI owns neither signing capability and therefore fails closed; production
issuance is available only through the pinned service adapters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ai.prepare_cross_ai_scope import MAX_SCOPE_BYTES, derive_scope, run_git
from scripts.ai.cross_ai_authority import (
    AuthorityUnavailable,
    PublicReviewAuthority,
    load_review_submission_authority,
)
from scripts.ai.trusted_cross_ai_evidence import (
    EVIDENCE_SCHEMA,
    TrustedEvidenceError,
    build_prompt,
    build_subject,
    canonical_bytes,
    validate_github_comment_transport,
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
    parse_canonical_review_response,
)
from scripts.github_apps.cross_ai_deployment_policy.timeutil import parse_utc, utc_now


CANONICAL_MAIN_REF_API = (
    "https://api.github.com/repos/Halildeu/platform-k8s-gitops/"
    "git/ref/heads/main"
)
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class IssuerRuntimeAttestor(Protocol):
    """Remote runner-management service; never a local private-key adapter."""

    def attest(
        self,
        *,
        provider_review_envelope: dict[str, Any],
        execution: object,
        prompt_sha256: str,
        issued_at: str,
        expires_at: str,
    ) -> dict[str, Any]: ...


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--consultation-class",
        choices=("routine", "high-impact"),
        default="high-impact",
    )
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _canonical_main_tip(workspace: Path) -> str:
    """Resolve main from GitHub TLS, never from caller-controlled git refs."""

    request = urllib.request.Request(
        CANONICAL_MAIN_REF_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "acik-cross-ai-provider-review-issuer/1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    try:
        with opener.open(request, timeout=30) as response:
            if response.status != 200:
                reject(
                    "PROVIDER_BASE_AUTHORITY_UNAVAILABLE",
                    "canonical GitHub main ref is unavailable",
                )
            raw = response.read(65_537)
        if len(raw) > 65_536:
            raise ValueError("canonical GitHub ref response is oversized")
        document = json.loads(raw)
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ):
        reject(
            "PROVIDER_BASE_AUTHORITY_UNAVAILABLE",
            "canonical GitHub main ref cannot be verified",
        )
    if not isinstance(document, dict):
        reject(
            "PROVIDER_BASE_AUTHORITY_INVALID",
            "canonical GitHub main ref response is invalid",
        )
    target = document.get("object")
    if not isinstance(target, dict):
        reject(
            "PROVIDER_BASE_AUTHORITY_INVALID",
            "canonical GitHub main ref response is invalid",
        )
    tip = target.get("sha")
    if (
        document.get("ref") != "refs/heads/main"
        or target.get("type") != "commit"
        or not isinstance(tip, str)
        or not GIT_SHA_RE.fullmatch(tip)
    ):
        reject(
            "PROVIDER_BASE_AUTHORITY_INVALID",
            "canonical GitHub main ref response is invalid",
        )
    try:
        local = subprocess.run(
            ["git", "rev-parse", "--verify", f"{tip}^{{commit}}"],
            cwd=workspace,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env={
                "HOME": os.environ.get("HOME", ""),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "LANG": "C",
                "LC_ALL": "C",
                "TZ": "UTC",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
            },
        )
    except OSError:
        reject(
            "PROVIDER_BASE_OBJECT_UNAVAILABLE",
            "canonical main commit is unavailable in the issuer workspace",
        )
    if local.returncode != 0 or local.stdout.strip().lower() != tip:
        reject(
            "PROVIDER_BASE_OBJECT_UNAVAILABLE",
            "canonical main commit is unavailable in the issuer workspace",
        )
    return tip


def _scope(workspace: Path) -> tuple[dict[str, str], bytes]:
    head_sha = run_git(workspace, "rev-parse", "HEAD").lower()
    base_tip_sha = _canonical_main_tip(workspace)
    base_sha = (
        run_git(workspace, "rev-parse", f"{head_sha}^1").lower()
        if head_sha == base_tip_sha
        else run_git(workspace, "merge-base", base_tip_sha, head_sha).lower()
    )
    if head_sha == base_sha or not run_git(
        workspace, "diff", "--name-only", "--no-renames", f"{base_sha}...{head_sha}"
    ).splitlines():
        reject(
            "PROVIDER_SCOPE_EMPTY",
            "direct Codex review requires a non-empty PR head distinct from its trusted base",
        )
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
    runtime_attestor: IssuerRuntimeAttestor | None = None,
) -> dict[str, object]:
    if not 30 <= args.timeout_seconds <= 1200:
        reject("PROVIDER_TIMEOUT_INVALID", "provider timeout must be 30-1200 seconds")
    if os.path.lexists(args.output.expanduser().absolute()):
        reject("EVIDENCE_OUTPUT_INVALID", "evidence output must be a new writable file")
    if signer is None or runtime_attestor is None:
        reject(
            "TRUSTED_ISSUER_SERVICE_REQUIRED",
            "provider and runner-management authority are available only inside the pinned issuer service",
        )
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
    subject_sha256 = sha256_digest(subject)
    preflight_now = utc_now().replace(microsecond=0)
    preflight_authority = authority or load_review_submission_authority(
        workspace,
        expected_bindings=bindings,
        scope_bytes=scope_bytes,
        now=preflight_now,
    )
    active_signer = signer
    preflight_verifier = EvidenceVerifier(
        trust_root=preflight_authority.trust_root,
        revocations_envelope=preflight_authority.revocations_envelope,
        now=preflight_now,
        expected_trust_root_sha256=(
            preflight_authority.expected_trust_root_sha256
        ),
    )
    key = preflight_verifier.require_active_signing_key(
        key_id=active_signer.key_id,
        role="provider-review",
        provider_family="openai",
        issued_at=preflight_now,
    )
    if (
        key.allowed_channels != ("openai-codex",)
        or set(key.allowed_model_ids)
        != {CODEX_ROUTINE_MODEL, CODEX_HIGH_IMPACT_MODEL}
        or key.allowed_model_identity_classes != ("trusted-launch-attested",)
        or key.direct_provider_cli is not True
    ):
        reject("TRUST_SIGNER_BINDING_MISMATCH", "provider signer route is not fixed Codex")
    execution = (
        runner
        or DirectCodexRunner(
            executable_policy=preflight_authority.codex_executable_policy
        )
    ).run(
        prompt=prompt,
        model=model,
        workspace=workspace,
        timeout_seconds=args.timeout_seconds,
    )
    # The provider call can run for up to 20 minutes. Reload and revalidate the
    # complete public authority only after it returns so leaf time, signer
    # status, root/key validity and the revocation snapshot cannot be frozen at
    # launch time.
    now = utc_now().replace(microsecond=0)
    expires = now + timedelta(minutes=90)
    issued_at = now.isoformat().replace("+00:00", "Z")
    expires_at = expires.isoformat().replace("+00:00", "Z")
    active_authority = authority or load_review_submission_authority(
        workspace,
        expected_bindings=bindings,
        scope_bytes=scope_bytes,
        now=now,
    )
    trust_root = active_authority.trust_root
    revocations = active_authority.revocations_envelope
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
        issued_at=now,
    )
    if (
        key.allowed_channels != ("openai-codex",)
        or set(key.allowed_model_ids)
        != {CODEX_ROUTINE_MODEL, CODEX_HIGH_IMPACT_MODEL}
        or key.allowed_model_identity_classes != ("trusted-launch-attested",)
        or key.direct_provider_cli is not True
    ):
        reject("TRUST_SIGNER_BINDING_MISMATCH", "provider signer route is not fixed Codex")
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
    runtime_envelope = runtime_attestor.attest(
        provider_review_envelope=envelope,
        execution=execution,
        prompt_sha256=subject["promptSha256"],
        issued_at=issued_at,
        expires_at=(now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
    )
    evidence: dict[str, object] = {
        "schema": EVIDENCE_SCHEMA,
        "subject": subject,
        "capability_snapshot": execution.capability_snapshot,
        "response": execution.result_text,
        "review_envelope": envelope,
        "review_envelope_sha256": sha256_digest(envelope),
        "issuer_runtime_envelope": runtime_envelope,
        "issuer_runtime_envelope_sha256": sha256_digest(runtime_envelope),
        "trust_root_sha256": active_authority.expected_trust_root_sha256,
    }
    validate_evidence(
        evidence,
        trust_root=trust_root,
        revocations_envelope=revocations,
        expected_trust_root_sha256=active_authority.expected_trust_root_sha256,
        codex_executable_policy=active_authority.codex_executable_policy,
        issuer_runtime_policy=active_authority.issuer_runtime_policy,
        expected_bindings=bindings,
        scope_bytes=scope_bytes,
        now=now,
        require_agree=False,
        expected_model=model,
    )
    rendered = canonical_bytes(evidence)
    try:
        validate_github_comment_transport(rendered.decode("utf-8"))
    except TrustedEvidenceError as exc:
        reject("EVIDENCE_OUTPUT_INVALID", str(exc))
    _write_exclusive(args.output, rendered)
    return {
        "ok": True,
        "schema": EVIDENCE_SCHEMA,
        "head_sha": bindings["head_sha"],
        "scope_sha256": bindings["scope_sha256"],
        "model_id": model,
        "model_identity_class": "trusted-launch-attested",
        "review_envelope_sha256": sha256_digest(envelope),
        "verdict": parse_canonical_review_response(execution.result_text)["verdict"],
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
