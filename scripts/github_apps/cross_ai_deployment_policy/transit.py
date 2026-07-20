"""Vault Transit-backed DSSE signer; private keys never enter this process."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .canonical import canonical_bytes
from .dsse import pae
from .errors import reject
from .github import Transport, UrllibTransport
from .jsonutil import loads_json_bytes


VAULT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
VAULT_SIGNATURE = re.compile(r"^vault:v([1-9][0-9]*):([A-Za-z0-9+/]+={0,2})$")


class VaultTransitSigner:
    def __init__(
        self,
        *,
        vault_origin: str,
        token_file: Path,
        mount: str,
        key_name: str,
        key_version: int,
        transport: Transport | None = None,
    ) -> None:
        parsed = urlsplit(vault_origin)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            reject("VAULT_ORIGIN_INVALID", "Vault origin must be canonical HTTPS")
        if (
            VAULT_NAME.fullmatch(mount) is None
            or VAULT_NAME.fullmatch(key_name) is None
            or key_version < 1
        ):
            reject("VAULT_TRANSIT_KEY_INVALID", "Vault Transit key binding is invalid")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(token_file, flags)
        except OSError:
            reject("VAULT_TOKEN_UNAVAILABLE", "Vault token file cannot be opened safely")
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or metadata.st_mode & 0o077
                or not 20 <= metadata.st_size <= 4097
            ):
                reject(
                    "VAULT_TOKEN_FILE_INVALID",
                    "Vault token file must be a bounded owner-only regular file",
                )
            raw = os.read(descriptor, metadata.st_size + 1)
        except OSError:
            reject("VAULT_TOKEN_UNAVAILABLE", "Vault token file cannot be read safely")
        finally:
            os.close(descriptor)
        if len(raw) != metadata.st_size:
            reject("VAULT_TOKEN_FILE_INVALID", "Vault token file changed while reading")
        token = raw.strip()
        if not 20 <= len(token) <= 4096 or b"\x00" in token:
            reject("VAULT_TOKEN_INVALID", "Vault token file is invalid")
        try:
            self._token = token.decode("ascii")
        except UnicodeDecodeError:
            reject("VAULT_TOKEN_INVALID", "Vault token must be ASCII")
        self.vault_origin = vault_origin
        self.mount = mount
        self.key_name = key_name
        self.key_version = key_version
        self.token_file_identity = (metadata.st_dev, metadata.st_ino)
        self.token_sha256 = hashlib.sha256(token).digest()
        self.transport = transport or UrllibTransport()

    @property
    def key_id(self) -> str:
        return f"vault-transit://{self.mount}/{self.key_name}#v{self.key_version}"

    def sign(self, message: bytes) -> bytes:
        if not message or len(message) > 4 * 1024 * 1024:
            reject("VAULT_SIGN_INPUT_INVALID", "signing input size is invalid")
        body = canonical_bytes(
            {
                "input": base64.b64encode(message).decode("ascii"),
                "key_version": self.key_version,
            }
        )
        response = self.transport.request(
            "POST",
            f"{self.vault_origin}/v1/{self.mount}/sign/{self.key_name}",
            headers={
                "Content-Type": "application/json",
                "X-Vault-Token": self._token,
                "User-Agent": "acik-cross-ai-evidence-issuer/1",
            },
            body=body,
        )
        if response.status != 200:
            reject("VAULT_SIGN_FAILED", "Vault Transit signing request failed")
        payload = loads_json_bytes(response.body, label="Vault Transit response")
        data = payload.get("data")
        if not isinstance(data, dict):
            reject("VAULT_SIGN_RESPONSE_INVALID", "Vault response data is missing")
        signature_value = data.get("signature")
        if not isinstance(signature_value, str):
            reject("VAULT_SIGN_RESPONSE_INVALID", "Vault signature is missing")
        match = VAULT_SIGNATURE.fullmatch(signature_value)
        if match is None or int(match.group(1)) != self.key_version:
            reject("VAULT_SIGN_VERSION_MISMATCH", "Vault used an unexpected key version")
        try:
            signature = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError):
            reject("VAULT_SIGN_RESPONSE_INVALID", "Vault signature is not Base64")
        if len(signature) != 64:
            reject("VAULT_SIGN_RESPONSE_INVALID", "Vault Ed25519 signature length is invalid")
        return signature

    def sign_json_envelope(
        self,
        *,
        payload_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload_bytes = canonical_bytes(payload)
        signature = self.sign(pae(payload_type, payload_bytes))
        return {
            "payloadType": payload_type,
            "payload": base64.b64encode(payload_bytes).decode("ascii"),
            "signatures": [
                {
                    "keyid": self.key_id,
                    "sig": base64.b64encode(signature).decode("ascii"),
                }
            ],
        }


class VaultKubernetesTransitSigner:
    """Mint one workload-bound Vault token per signature and revoke it."""

    def __init__(
        self,
        *,
        vault_origin: str,
        kubernetes_jwt_file: Path,
        auth_mount: str,
        role: str,
        expected_policy: str,
        mount: str,
        key_name: str,
        key_version: int,
        transport: Transport | None = None,
    ) -> None:
        parsed = urlsplit(vault_origin)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or VAULT_NAME.fullmatch(auth_mount) is None
            or VAULT_NAME.fullmatch(role) is None
            or VAULT_NAME.fullmatch(expected_policy) is None
            or VAULT_NAME.fullmatch(mount) is None
            or VAULT_NAME.fullmatch(key_name) is None
            or key_version < 1
        ):
            reject(
                "VAULT_KUBERNETES_BINDING_INVALID",
                "Vault Kubernetes Transit binding is invalid",
            )
        self.vault_origin = vault_origin
        self.kubernetes_jwt_file = kubernetes_jwt_file
        self.auth_mount = auth_mount
        self.role = role
        self.expected_policy = expected_policy
        self.mount = mount
        self.key_name = key_name
        self.key_version = key_version
        self.transport = transport or UrllibTransport()

    @property
    def key_id(self) -> str:
        return f"vault-transit://{self.mount}/{self.key_name}#v{self.key_version}"

    def _projected_jwt(self) -> str:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.kubernetes_jwt_file, flags)
        except OSError:
            reject(
                "VAULT_KUBERNETES_JWT_UNAVAILABLE",
                "projected workload JWT cannot be opened",
            )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_mode & 0o027
                or not 100 <= metadata.st_size <= 16384
            ):
                reject(
                    "VAULT_KUBERNETES_JWT_INVALID",
                    "projected workload JWT permissions or size are invalid",
                )
            raw = os.read(descriptor, metadata.st_size + 1)
        except OSError:
            reject(
                "VAULT_KUBERNETES_JWT_UNAVAILABLE",
                "projected workload JWT cannot be read",
            )
        finally:
            os.close(descriptor)
        token = raw.strip()
        if len(raw) != metadata.st_size or not 100 <= len(token) <= 16384:
            reject(
                "VAULT_KUBERNETES_JWT_INVALID",
                "projected workload JWT changed or is invalid",
            )
        try:
            return token.decode("ascii")
        except UnicodeDecodeError:
            reject(
                "VAULT_KUBERNETES_JWT_INVALID",
                "projected workload JWT must be ASCII",
            )

    def sign(self, message: bytes) -> bytes:
        if not message or len(message) > 4 * 1024 * 1024:
            reject("VAULT_SIGN_INPUT_INVALID", "signing input size is invalid")
        login = self.transport.request(
            "POST",
            f"{self.vault_origin}/v1/auth/{self.auth_mount}/login",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "acik-cross-ai-runtime-attestor/1",
            },
            body=canonical_bytes({"role": self.role, "jwt": self._projected_jwt()}),
        )
        if login.status != 200:
            reject(
                "VAULT_KUBERNETES_LOGIN_FAILED",
                "Vault workload authentication failed",
            )
        login_payload = loads_json_bytes(login.body, label="Vault Kubernetes login")
        auth = login_payload.get("auth")
        if not isinstance(auth, dict):
            reject(
                "VAULT_KUBERNETES_LOGIN_INVALID",
                "Vault workload authentication response is invalid",
            )
        token = auth.get("client_token")
        policies = auth.get("token_policies")
        lease_duration = auth.get("lease_duration")
        if (
            not isinstance(token, str)
            or not 20 <= len(token) <= 4096
            or auth.get("renewable") is not False
            or policies != [self.expected_policy]
            or auth.get("num_uses") != 2
            or not isinstance(lease_duration, int)
            or not 1 <= lease_duration <= 600
        ):
            reject(
                "VAULT_KUBERNETES_LOGIN_INVALID",
                "Vault workload token differs from the bounded signing contract",
            )
        sign_response = None
        sign_failed = False
        try:
            sign_response = self.transport.request(
                "POST",
                f"{self.vault_origin}/v1/{self.mount}/sign/{self.key_name}",
                headers={
                    "Content-Type": "application/json",
                    "X-Vault-Token": token,
                    "User-Agent": "acik-cross-ai-runtime-attestor/1",
                },
                body=canonical_bytes(
                    {
                        "input": base64.b64encode(message).decode("ascii"),
                        "key_version": self.key_version,
                    }
                ),
            )
        except Exception:
            sign_failed = True
        try:
            revoke = self.transport.request(
                "POST",
                f"{self.vault_origin}/v1/auth/token/revoke-self",
                headers={
                    "Content-Type": "application/json",
                    "X-Vault-Token": token,
                    "User-Agent": "acik-cross-ai-runtime-attestor/1",
                },
                body=b"{}",
            )
        except Exception:
            reject(
                "VAULT_SIGN_FAILED",
                "Vault signing token could not be revoked",
            )
        if (
            sign_failed
            or sign_response is None
            or sign_response.status != 200
            or revoke.status not in {200, 204}
        ):
            reject(
                "VAULT_SIGN_FAILED",
                "Vault signing or one-use token revocation failed",
            )
        payload = loads_json_bytes(sign_response.body, label="Vault Transit response")
        data = payload.get("data")
        signature_value = data.get("signature") if isinstance(data, dict) else None
        match = (
            VAULT_SIGNATURE.fullmatch(signature_value)
            if isinstance(signature_value, str)
            else None
        )
        if match is None or int(match.group(1)) != self.key_version:
            reject("VAULT_SIGN_VERSION_MISMATCH", "Vault used an unexpected key version")
        try:
            signature = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError):
            reject("VAULT_SIGN_RESPONSE_INVALID", "Vault signature is not Base64")
        if len(signature) != 64:
            reject("VAULT_SIGN_RESPONSE_INVALID", "Vault signature length is invalid")
        return signature

    def sign_json_envelope(
        self,
        *,
        payload_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload_bytes = canonical_bytes(payload)
        signature = self.sign(pae(payload_type, payload_bytes))
        return {
            "payloadType": payload_type,
            "payload": base64.b64encode(payload_bytes).decode("ascii"),
            "signatures": [
                {
                    "keyid": self.key_id,
                    "sig": base64.b64encode(signature).decode("ascii"),
                }
            ],
        }


__all__ = ["VaultKubernetesTransitSigner", "VaultTransitSigner"]
