"""DSSE PAE and Ed25519 verification for bounded JSON evidence."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .canonical import canonical_bytes, sha256_digest
from .errors import reject


@dataclass(frozen=True)
class VerifiedEnvelope:
    payload_type: str
    payload: dict[str, Any]
    payload_bytes: bytes
    envelope_digest: str
    signing_key_ids: tuple[str, ...]


def _strict_b64(value: object, field: str) -> bytes:
    if not isinstance(value, str):
        reject("DSSE_BASE64_INVALID", f"{field} must be Base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        reject("DSSE_BASE64_INVALID", f"{field} is not canonical Base64")


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE Pre-Authentication Encoding (PAE)."""

    if not payload_type or any(ord(character) > 0x7F for character in payload_type):
        reject("DSSE_PAYLOAD_TYPE_INVALID", "payloadType must be non-empty ASCII")
    return (
        b"DSSEv1 "
        + str(len(payload_type.encode("utf-8"))).encode("ascii")
        + b" "
        + payload_type.encode("utf-8")
        + b" "
        + str(len(payload)).encode("ascii")
        + b" "
        + payload
    )


def decode_public_key(value: object, key_id: str) -> bytes:
    raw = _strict_b64(value, f"trustRoot.keys[{key_id}].publicKeyBase64")
    if len(raw) != 32:
        reject("TRUST_KEY_INVALID", f"{key_id} must be a raw 32-byte Ed25519 key")
    return raw


def verify_json_envelope(
    envelope: object,
    *,
    expected_payload_type: str,
    allowed_keys: dict[str, bytes],
    required_key_ids: Iterable[str] | None = None,
    exactly_one_signature: bool = True,
) -> VerifiedEnvelope:
    if not isinstance(envelope, dict):
        reject("DSSE_SCHEMA_INVALID", "DSSE envelope must be an object")
    if set(envelope) != {"payloadType", "payload", "signatures"}:
        reject("DSSE_SCHEMA_INVALID", "DSSE envelope has missing or unknown fields")
    payload_type = envelope.get("payloadType")
    if payload_type != expected_payload_type:
        reject("DSSE_PAYLOAD_TYPE_MISMATCH", "unexpected DSSE payloadType")
    payload_bytes = _strict_b64(envelope.get("payload"), "payload")
    try:
        payload = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        reject("DSSE_PAYLOAD_INVALID", "DSSE payload must be a UTF-8 JSON object")
    if not isinstance(payload, dict):
        reject("DSSE_PAYLOAD_INVALID", "DSSE payload must be a JSON object")
    if payload_bytes != canonical_bytes(payload):
        reject("DSSE_PAYLOAD_NON_CANONICAL", "DSSE payload bytes are not canonical JCS")

    signatures = envelope.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        reject("DSSE_SIGNATURE_MISSING", "at least one DSSE signature is required")
    if exactly_one_signature and len(signatures) != 1:
        reject("DSSE_SIGNATURE_COUNT", "exactly one DSSE signature is required")

    required = set(required_key_ids or ())
    seen: set[str] = set()
    message = pae(expected_payload_type, payload_bytes)
    for index, signature_entry in enumerate(signatures):
        if not isinstance(signature_entry, dict) or set(signature_entry) != {"keyid", "sig"}:
            reject("DSSE_SIGNATURE_INVALID", f"signatures[{index}] has invalid fields")
        key_id = signature_entry.get("keyid")
        if not isinstance(key_id, str) or key_id in seen:
            reject("DSSE_SIGNATURE_INVALID", f"signatures[{index}].keyid is invalid")
        public_key = allowed_keys.get(key_id)
        if public_key is None:
            reject("DSSE_KEY_NOT_ALLOWED", f"signature key {key_id} is not allowlisted")
        signature = _strict_b64(signature_entry.get("sig"), f"signatures[{index}].sig")
        if len(signature) != 64:
            reject("DSSE_SIGNATURE_INVALID", f"signature for {key_id} has invalid length")
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        except (InvalidSignature, ValueError):
            reject("DSSE_SIGNATURE_INVALID", f"signature verification failed for {key_id}")
        seen.add(key_id)

    if required and not required.issubset(seen):
        reject("DSSE_REQUIRED_SIGNER_MISSING", "required DSSE signer is missing")

    return VerifiedEnvelope(
        payload_type=expected_payload_type,
        payload=payload,
        payload_bytes=payload_bytes,
        envelope_digest=sha256_digest(envelope),
        signing_key_ids=tuple(sorted(seen)),
    )
