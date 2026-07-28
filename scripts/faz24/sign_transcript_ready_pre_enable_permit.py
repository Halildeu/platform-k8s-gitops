#!/usr/bin/env python3
"""Issue a TEST-bound DSSE permit with a dedicated Vault Transit key."""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.github_apps.cross_ai_deployment_policy.dsse import pae  # noqa: E402
from scripts.github_apps.cross_ai_deployment_policy.errors import (  # noqa: E402
    PolicyError,
)
from scripts.github_apps.cross_ai_deployment_policy.github import (  # noqa: E402
    Transport,
    UrllibTransport,
)
from scripts.github_apps.cross_ai_deployment_policy.transit import (  # noqa: E402
    VaultTransitSigner,
)
from transcript_ready_pre_enable_contract import (  # noqa: E402
    APP_ENVIRONMENTS,
    GIT_SHA_RE,
    HOST_GUARD_BINDING_FIELDS,
    ISSUE,
    KEY_ID_RE,
    LIVE_POD_BINDING_FIELDS,
    PERMIT_PAYLOAD_TYPE,
    PERMIT_TRUST_ROOT_FIELDS,
    PERMIT_TRUST_ROOT_SCHEMA,
    PRODUCER_BINDING_FIELDS,
    VERDICT_BINDING_FIELDS,
    VERDICT_CHECK_FIELDS,
    VERDICT_FIELDS,
    VERDICT_SCHEMA,
    ContractError,
    canonical_json,
    load_strict_json,
    parse_utc,
    require_secure_regular_file,
    sensitive_findings,
    sha256_bytes,
)
import verify_transcript_ready_pre_enable_evidence as verdict_verifier  # noqa: E402

TRANSIT_MOUNT = "meeting-ai"
TRANSIT_KEY_NAME = "transcript-ready-permit"
IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _strict_b64(value: Any, label: str, expected_size: int) -> bytes:
    if not isinstance(value, str):
        raise ContractError(f"{label} must be canonical Base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ContractError(f"{label} must be canonical Base64") from exc
    if (
        len(decoded) != expected_size
        or base64.b64encode(decoded).decode("ascii") != value
    ):
        raise ContractError(f"{label} has an invalid Ed25519 size or encoding")
    return decoded


def _validate_trust_root(
    *,
    raw: bytes,
    root: dict[str, Any],
    expected_sha256: str,
    expected_key_id: str,
    app_env: str,
    now: dt.datetime,
) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ContractError("expected trust-root SHA-256 is invalid")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ContractError("trust-root SHA-256 does not match the out-of-band pin")
    if set(root) != PERMIT_TRUST_ROOT_FIELDS:
        raise ContractError("trust-root has missing or unknown fields")
    if root.get("schemaVersion") != PERMIT_TRUST_ROOT_SCHEMA:
        raise ContractError("trust-root schema is invalid")
    key_id = root.get("keyId")
    if (
        not isinstance(key_id, str)
        or KEY_ID_RE.fullmatch(key_id) is None
        or key_id != expected_key_id
    ):
        raise ContractError("trust-root does not bind the dedicated key version")
    if root.get("algorithm") != "ed25519":
        raise ContractError("trust-root algorithm must be ed25519")
    environments = root.get("allowedAppEnvironments")
    if (
        not isinstance(environments, list)
        or not environments
        or environments != sorted(set(environments))
        or any(value not in APP_ENVIRONMENTS for value in environments)
        or app_env not in environments
    ):
        raise ContractError("trust-root environment allowlist is invalid")
    not_before = parse_utc(root.get("notBefore"))
    not_after = parse_utc(root.get("notAfter"))
    if not not_before < not_after or not not_before <= now <= not_after:
        raise ContractError("trust-root is outside its validity window")
    return _strict_b64(root.get("publicKeyBase64"), "trust-root public key", 32)


def _validate_verdict(
    verdict: dict[str, Any],
    *,
    app_env: str,
    expected_gitops_commit: str,
    expected_policy_sha256: str,
    expected_producer_image_digest: str,
    now: dt.datetime,
    max_age_seconds: int,
) -> None:
    if set(verdict) != VERDICT_FIELDS:
        raise ContractError("verdict has missing or unknown fields")
    if (
        verdict.get("schemaVersion") != VERDICT_SCHEMA
        or verdict.get("issue") != ISSUE
        or verdict.get("status") != "accepted-candidate"
        or verdict.get("enableAuthorized") is not True
    ):
        raise ContractError("only an accepted v2 candidate can be signed")
    if sensitive_findings(verdict):
        raise ContractError("verdict contains forbidden secret or customer content")
    generated_at = parse_utc(verdict.get("generatedAt"))
    verdict_age = (now - generated_at).total_seconds()
    if verdict_age < -30 or verdict_age > max_age_seconds:
        raise ContractError("verdict freshness is outside the signing window")
    boundary = verdict.get("boundary")
    if not isinstance(boundary, str) or not boundary.strip() or len(boundary) > 2048:
        raise ContractError("verdict boundary is invalid")

    checks = verdict.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ContractError("verdict must contain passing checks")
    names: set[str] = set()
    for check in checks:
        if (
            not isinstance(check, dict)
            or set(check) != VERDICT_CHECK_FIELDS
            or not isinstance(check.get("name"), str)
            or not check["name"]
            or check["name"] in names
            or check.get("passed") is not True
            or not isinstance(check.get("message"), str)
            or not check["message"]
            or check.get("remediation") != ""
        ):
            raise ContractError("verdict checks are not an exact passing set")
        names.add(check["name"])
    if verdict.get("requiredRemediationEvidence") != []:
        raise ContractError("accepted verdict cannot carry remediation requirements")

    binding = verdict.get("binding")
    if not isinstance(binding, dict) or set(binding) != VERDICT_BINDING_FIELDS:
        raise ContractError("verdict binding has missing or unknown fields")
    if (
        binding.get("targetAppEnv") != app_env
        or binding.get("expectedGitopsCommit") != expected_gitops_commit
        or binding.get("policySha256") != expected_policy_sha256
    ):
        raise ContractError("verdict target binding does not match signing intent")
    producer = binding.get("producerCapability")
    if (
        not isinstance(producer, dict)
        or set(producer) != PRODUCER_BINDING_FIELDS
        or producer.get("transcriptImageDigest") != expected_producer_image_digest
        or not isinstance(producer.get("backendCommit"), str)
        or GIT_SHA_RE.fullmatch(producer["backendCommit"]) is None
    ):
        raise ContractError("producer capability binding is invalid")
    pod = binding.get("liveTranscriptPod")
    if not isinstance(pod, dict) or set(pod) != LIVE_POD_BINDING_FIELDS:
        raise ContractError("live transcript pod binding is invalid")
    observed_at = parse_utc(pod.get("observedAt"))
    live_observation_age = (now - observed_at).total_seconds()
    if (
        not isinstance(pod.get("podUid"), str)
        or UUID_RE.fullmatch(pod["podUid"]) is None
        or pod.get("imageDigest") != expected_producer_image_digest
        or not isinstance(pod.get("evidenceSha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", pod["evidenceSha256"]) is None
        or observed_at > generated_at
        or generated_at - observed_at > dt.timedelta(seconds=900)
        or live_observation_age < -30
        or live_observation_age > max_age_seconds
    ):
        raise ContractError("live transcript pod runtime evidence is invalid")
    guard = binding.get("hostStartupGuard")
    if (
        not isinstance(guard, dict)
        or set(guard) != HOST_GUARD_BINDING_FIELDS
        or guard.get("permitRequired") is not True
        or not isinstance(guard.get("platformAiCommit"), str)
        or GIT_SHA_RE.fullmatch(guard["platformAiCommit"]) is None
        or not isinstance(guard.get("startupScriptSha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", guard["startupScriptSha256"]) is None
    ):
        raise ContractError("host startup guard binding is invalid")
    evidence_age = binding.get("evidenceAgeSeconds")
    observed_age = int((generated_at - observed_at).total_seconds())
    if (
        isinstance(evidence_age, bool)
        or not isinstance(evidence_age, int)
        or evidence_age != observed_age
        or not 0 <= evidence_age <= 900
    ):
        raise ContractError("evidence age does not bind the live observation")


def _recompute_canonical_verdict(
    *,
    verdict: dict[str, Any],
    evidence_path: Path,
    policy_path: Path,
    expected_gitops_commit: str,
    expected_policy_sha256: str,
) -> None:
    policy = verdict_verifier.load_policy(policy_path)
    policy_digest = verdict_verifier.file_sha256(policy_path)
    if policy_digest != expected_policy_sha256:
        raise ContractError("policy bytes do not match the signing intent")
    evidence = verdict_verifier.load_json(evidence_path)
    evidence_digest = verdict_verifier.file_sha256(evidence_path)
    generated_at = parse_utc(verdict.get("generatedAt"))
    checks, context = verdict_verifier.validate(
        evidence,
        policy,
        expected_gitops_commit=expected_gitops_commit,
        policy_path=policy_path,
        now=generated_at,
    )
    recomputed = verdict_verifier.build_verdict(
        checks=checks,
        context=context,
        policy=policy,
        expected_gitops_commit=expected_gitops_commit,
        policy_digest=policy_digest,
        evidence_digest=evidence_digest,
        generated_at=generated_at,
    )
    if canonical_json(recomputed) != canonical_json(verdict):
        raise ContractError(
            "verdict differs from the canonical evidence and policy verification"
        )


def _revoke_and_remove_token(
    *,
    vault_origin: str,
    token: str,
    token_file: Path,
    transport: Transport,
) -> None:
    revoke_error: ContractError | None = None
    try:
        response = transport.request(
            "POST",
            f"{vault_origin}/v1/auth/token/revoke-self",
            headers={
                "Content-Type": "application/json",
                "X-Vault-Token": token,
                "User-Agent": "acik-faz24-permit-signer/1",
            },
            body=b"{}",
        )
        # A one-use token is already invalid after the Transit request.
        if response.status not in {204, 403}:
            revoke_error = ContractError("Vault signer token revocation failed")
    except PolicyError:
        revoke_error = ContractError("Vault signer token revocation failed")
    try:
        token_file.unlink(missing_ok=True)
    except OSError as exc:
        raise ContractError("Vault signer token file cleanup failed") from exc
    if revoke_error is not None:
        raise revoke_error


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() and path.is_symlink():
        raise ContractError("permit output cannot replace a symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def sign_permit(
    *,
    verdict_path: Path,
    evidence_path: Path,
    policy_path: Path,
    trust_root_path: Path,
    expected_trust_root_sha256: str,
    app_env: str,
    expected_gitops_commit: str,
    expected_policy_sha256: str,
    expected_producer_image_digest: str,
    vault_origin: str,
    vault_token_file: Path,
    vault_mount: str,
    vault_key_name: str,
    vault_key_version: int,
    now: dt.datetime,
    max_age_seconds: int = 900,
    transport: Transport | None = None,
) -> tuple[dict[str, Any], bytes, bytes]:
    if app_env not in APP_ENVIRONMENTS:
        raise ContractError("app environment is invalid")
    if GIT_SHA_RE.fullmatch(expected_gitops_commit) is None:
        raise ContractError("expected GitOps commit is invalid")
    if re.fullmatch(r"[0-9a-f]{64}", expected_policy_sha256) is None:
        raise ContractError("expected policy SHA-256 is invalid")
    if IMAGE_DIGEST_RE.fullmatch(expected_producer_image_digest) is None:
        raise ContractError("expected producer image digest is invalid")
    if not 60 <= max_age_seconds <= 900:
        raise ContractError("signing freshness must be between 60 and 900 seconds")
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise ContractError("signing time must be UTC")
    if vault_mount != TRANSIT_MOUNT or vault_key_name != TRANSIT_KEY_NAME:
        raise ContractError("permit signer must use the dedicated Transit key")
    if isinstance(vault_key_version, bool) or vault_key_version < 1:
        raise ContractError("Vault key version is invalid")
    require_secure_regular_file(vault_token_file, "Vault token file")
    try:
        token = vault_token_file.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ContractError("Vault token file is unavailable") from exc
    if not 20 <= len(token) <= 4096 or any(character.isspace() for character in token):
        raise ContractError("Vault token file content is invalid")
    selected_transport = transport or UrllibTransport()

    try:
        _verdict_raw, verdict = load_strict_json(verdict_path, "verdict")
        trust_raw, trust_root = load_strict_json(trust_root_path, "trust-root")
        expected_key_id = (
            f"vault-transit://{vault_mount}/{vault_key_name}#v{vault_key_version}"
        )
        public_key = _validate_trust_root(
            raw=trust_raw,
            root=trust_root,
            expected_sha256=expected_trust_root_sha256,
            expected_key_id=expected_key_id,
            app_env=app_env,
            now=now,
        )
        _validate_verdict(
            verdict,
            app_env=app_env,
            expected_gitops_commit=expected_gitops_commit,
            expected_policy_sha256=expected_policy_sha256,
            expected_producer_image_digest=expected_producer_image_digest,
            now=now,
            max_age_seconds=max_age_seconds,
        )
        _recompute_canonical_verdict(
            verdict=verdict,
            evidence_path=evidence_path,
            policy_path=policy_path,
            expected_gitops_commit=expected_gitops_commit,
            expected_policy_sha256=expected_policy_sha256,
        )

        payload_bytes = canonical_json(verdict)
        signer = VaultTransitSigner(
            vault_origin=vault_origin,
            token_file=vault_token_file,
            mount=vault_mount,
            key_name=vault_key_name,
            key_version=vault_key_version,
            transport=selected_transport,
        )
        if signer.key_id != expected_key_id:
            raise ContractError("Vault signer key ID differs from the pinned trust root")
        signature = signer.sign(pae(PERMIT_PAYLOAD_TYPE, payload_bytes))
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                signature, pae(PERMIT_PAYLOAD_TYPE, payload_bytes)
            )
        except (InvalidSignature, ValueError) as exc:
            raise ContractError(
                "Vault signature does not verify with the pinned root"
            ) from exc
        envelope = {
            "payloadType": PERMIT_PAYLOAD_TYPE,
            "payload": base64.b64encode(payload_bytes).decode("ascii"),
            "signatures": [
                {
                    "keyid": signer.key_id,
                    "sig": base64.b64encode(signature).decode("ascii"),
                }
            ],
        }
        return envelope, payload_bytes, canonical_json(envelope)
    finally:
        _revoke_and_remove_token(
            vault_origin=vault_origin,
            token=token,
            token_file=vault_token_file,
            transport=selected_transport,
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verdict", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--trust-root", required=True, type=Path)
    parser.add_argument("--expected-trust-root-sha256", required=True)
    parser.add_argument("--app-env", required=True, choices=sorted(APP_ENVIRONMENTS))
    parser.add_argument("--expected-gitops-commit", required=True)
    parser.add_argument("--expected-policy-sha256", required=True)
    parser.add_argument("--expected-producer-image-digest", required=True)
    parser.add_argument("--vault-origin", required=True)
    parser.add_argument("--vault-token-file", required=True, type=Path)
    parser.add_argument("--vault-mount", default=TRANSIT_MOUNT)
    parser.add_argument("--vault-key-name", default=TRANSIT_KEY_NAME)
    parser.add_argument("--vault-key-version", required=True, type=int)
    parser.add_argument("--max-age-seconds", type=int, default=900)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        envelope, payload_bytes, envelope_bytes = sign_permit(
            verdict_path=args.verdict,
            evidence_path=args.evidence,
            policy_path=args.policy,
            trust_root_path=args.trust_root,
            expected_trust_root_sha256=args.expected_trust_root_sha256,
            app_env=args.app_env,
            expected_gitops_commit=args.expected_gitops_commit,
            expected_policy_sha256=args.expected_policy_sha256,
            expected_producer_image_digest=args.expected_producer_image_digest,
            vault_origin=args.vault_origin,
            vault_token_file=args.vault_token_file,
            vault_mount=args.vault_mount,
            vault_key_name=args.vault_key_name,
            vault_key_version=args.vault_key_version,
            now=dt.datetime.now(dt.timezone.utc),
            max_age_seconds=args.max_age_seconds,
        )
        _atomic_write(args.output, envelope_bytes + b"\n")
    except (ContractError, PolicyError) as exc:
        print(f"permit signing rejected: {exc}", file=sys.stderr)
        return 2
    print(f"key_id={envelope['signatures'][0]['keyid']}")
    print(f"payload_sha256={sha256_bytes(payload_bytes)}")
    print(f"envelope_sha256={sha256_bytes(envelope_bytes)}")
    print(f"trust_root_sha256={args.expected_trust_root_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
