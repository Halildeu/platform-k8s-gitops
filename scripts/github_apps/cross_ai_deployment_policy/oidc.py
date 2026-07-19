"""Strict GitHub Actions OIDC verification for runner bootstrap."""

from __future__ import annotations

import base64
import binascii
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .errors import reject
from .jsonutil import loads_json_bytes


ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = f"{ISSUER}/.well-known/jwks"
AUDIENCE = "acik-cross-ai-runner-bootstrap"
MAX_JWT_BYTES = 32 * 1024
MAX_JWKS_BYTES = 256 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _b64url(value: str, label: str) -> bytes:
    if not value or "=" in value:
        reject("BOOTSTRAP_OIDC_INVALID", f"OIDC {label} is not canonical Base64url")
    try:
        decoded = base64.b64decode(
            value + ("=" * (-len(value) % 4)), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError):
        reject("BOOTSTRAP_OIDC_INVALID", f"OIDC {label} is invalid Base64url")
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        reject("BOOTSTRAP_OIDC_INVALID", f"OIDC {label} is not canonical Base64url")
    return decoded


def _jwt_json(value: str, label: str) -> dict[str, Any]:
    raw = _b64url(value, label)
    return loads_json_bytes(raw, max_bytes=16 * 1024, label=f"OIDC {label}")


class GitHubOIDCJWKSLoader:
    def __init__(self, *, cache_seconds: int = 300) -> None:
        if not 30 <= cache_seconds <= 3600:
            reject(
                "BOOTSTRAP_OIDC_CONFIG_INVALID", "OIDC JWKS cache duration is invalid"
            )
        self.cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._last_forced_at = 0.0
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
        )

    def __call__(self, *, force_refresh: bool = False) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            if (
                force_refresh
                and self._cached is not None
                and now - self._last_forced_at < 30
            ):
                return self._cached
            if (
                not force_refresh
                and self._cached is not None
                and now - self._cached_at <= self.cache_seconds
            ):
                return self._cached
            if force_refresh:
                self._last_forced_at = now
            request = urllib.request.Request(
                JWKS_URL,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "acik-cross-ai-oidc-verifier/1",
                },
            )
            try:
                with self._opener.open(request, timeout=10) as response:
                    if (
                        response.status != 200
                        or response.headers.get_content_type() != "application/json"
                    ):
                        reject(
                            "BOOTSTRAP_OIDC_JWKS_UNAVAILABLE",
                            "GitHub OIDC JWKS is invalid",
                        )
                    raw = response.read(MAX_JWKS_BYTES + 1)
            except urllib.error.HTTPError:
                reject(
                    "BOOTSTRAP_OIDC_JWKS_UNAVAILABLE", "GitHub OIDC JWKS was rejected"
                )
            except (urllib.error.URLError, TimeoutError, OSError):
                reject(
                    "BOOTSTRAP_OIDC_JWKS_UNAVAILABLE", "GitHub OIDC JWKS is unavailable"
                )
            if len(raw) > MAX_JWKS_BYTES:
                reject(
                    "BOOTSTRAP_OIDC_JWKS_UNAVAILABLE", "GitHub OIDC JWKS is oversized"
                )
            value = loads_json_bytes(
                raw, max_bytes=MAX_JWKS_BYTES, label="GitHub OIDC JWKS"
            )
            keys = value.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 20:
                reject(
                    "BOOTSTRAP_OIDC_JWKS_INVALID", "GitHub OIDC JWKS keys are invalid"
                )
            self._cached = value
            self._cached_at = now
            return value


class GitHubOIDCVerifier:
    def __init__(
        self,
        *,
        jwks_loader: Callable[[], dict[str, Any]] | None = None,
        jwks_refresher: Callable[[], dict[str, Any]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if jwks_loader is None:
            loader = GitHubOIDCJWKSLoader()
            self.jwks_loader = loader
            self.jwks_refresher = lambda: loader(force_refresh=True)
        else:
            self.jwks_loader = jwks_loader
            self.jwks_refresher = jwks_refresher
        self._now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _positive_claim(claims: dict[str, Any], name: str) -> int:
        value = claims.get(name)
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdigit()
            or value.startswith("0")
        ):
            reject("BOOTSTRAP_OIDC_CLAIM_MISMATCH", f"OIDC {name} claim is invalid")
        return int(value)

    def verify(
        self,
        token: str,
        *,
        repository_id: int,
        repository: str,
        environment: str,
        intent_ref: str,
        head_sha: str,
        workflow_path: str,
        run_id: int,
        run_attempt: int,
        actor_id: int,
    ) -> dict[str, Any]:
        return self.verify_claim_profile(
            token,
            audience=AUDIENCE,
            exact_claims={
                "repository_id": str(repository_id),
                "repository": repository,
                "environment": environment,
                "ref": intent_ref,
                "sha": head_sha,
                "event_name": "workflow_dispatch",
                "runner_environment": "self-hosted",
                "workflow_ref": f"{repository}/{workflow_path}@{intent_ref}",
                "sub": f"repo:{repository}:environment:{environment}",
            },
            positive_claims={
                "run_id": run_id,
                "run_attempt": run_attempt,
                "actor_id": actor_id,
            },
            max_token_age_seconds=600,
        )

    def verify_claim_profile(
        self,
        token: str,
        *,
        audience: str,
        exact_claims: dict[str, str],
        positive_claims: dict[str, int],
        forbidden_claims: tuple[str, ...] = (),
        required_unique_claims: tuple[str, ...] = ("jti",),
        max_token_age_seconds: int = 300,
    ) -> dict[str, Any]:
        """Verify one explicit GitHub OIDC capability profile.

        The forward VIEW_ONLY transaction has distinct binding, preflight,
        authorization and executor audiences.  Callers must materialize every
        registry/binding-derived equality before invoking this method; no
        claim expression language is evaluated in the verifier.
        """

        if (
            not isinstance(audience, str)
            or not audience.isascii()
            or not 1 <= len(audience) <= 200
            or not 30 <= max_token_age_seconds <= 600
            or not exact_claims
            or any(
                not isinstance(name, str)
                or not name
                or not isinstance(value, str)
                for name, value in exact_claims.items()
            )
            or any(
                not isinstance(name, str)
                or not name
                or not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
                for name, value in positive_claims.items()
            )
            or any(not isinstance(name, str) or not name for name in forbidden_claims)
            or any(
                not isinstance(name, str) or not name
                for name in required_unique_claims
            )
        ):
            reject(
                "BOOTSTRAP_OIDC_CONFIG_INVALID",
                "OIDC claim profile is invalid",
            )
        claim_sets = (
            set(exact_claims),
            set(positive_claims),
            set(forbidden_claims),
            set(required_unique_claims),
        )
        if (
            len(set(forbidden_claims)) != len(forbidden_claims)
            or len(set(required_unique_claims)) != len(required_unique_claims)
            or any(
                claim_sets[index].intersection(claim_sets[other])
                for index in range(len(claim_sets))
                for other in range(index + 1, len(claim_sets))
            )
        ):
            reject(
                "BOOTSTRAP_OIDC_CONFIG_INVALID",
                "OIDC claim profile contains overlapping authority fields",
            )

        if not isinstance(token, str) or not 100 <= len(token) <= MAX_JWT_BYTES:
            reject("BOOTSTRAP_OIDC_INVALID", "OIDC token size is invalid")
        parts = token.split(".")
        if len(parts) != 3:
            reject("BOOTSTRAP_OIDC_INVALID", "OIDC token is not a compact JWT")
        header = _jwt_json(parts[0], "header")
        claims = _jwt_json(parts[1], "claims")
        signature = _b64url(parts[2], "signature")
        header_fields = set(header)
        if (
            not {"alg", "kid", "typ"}.issubset(header_fields)
            or header_fields - {"alg", "kid", "typ", "x5t"}
            or header.get("alg") != "RS256"
            or header.get("typ") != "JWT"
            or ("x5t" in header and not isinstance(header["x5t"], str))
        ):
            reject(
                "BOOTSTRAP_OIDC_INVALID", "OIDC header is not the pinned RS256 profile"
            )
        kid = header.get("kid")
        if not isinstance(kid, str) or not 1 <= len(kid) <= 200:
            reject("BOOTSTRAP_OIDC_INVALID", "OIDC key ID is invalid")
        keys = self.jwks_loader().get("keys")
        if not isinstance(keys, list):
            reject("BOOTSTRAP_OIDC_JWKS_INVALID", "OIDC JWKS is invalid")
        matches = [
            entry
            for entry in keys
            if isinstance(entry, dict) and entry.get("kid") == kid
        ]
        if not matches and self.jwks_refresher is not None:
            refreshed_keys = self.jwks_refresher().get("keys")
            if not isinstance(refreshed_keys, list):
                reject("BOOTSTRAP_OIDC_JWKS_INVALID", "OIDC JWKS is invalid")
            matches = [
                entry
                for entry in refreshed_keys
                if isinstance(entry, dict) and entry.get("kid") == kid
            ]
        if len(matches) != 1:
            reject("BOOTSTRAP_OIDC_JWKS_INVALID", "OIDC signing key is ambiguous")
        jwk = matches[0]
        if (
            jwk.get("kty") != "RSA"
            or jwk.get("use") != "sig"
            or jwk.get("alg") != "RS256"
            or not isinstance(jwk.get("n"), str)
            or not isinstance(jwk.get("e"), str)
        ):
            reject("BOOTSTRAP_OIDC_JWKS_INVALID", "OIDC signing key profile is invalid")
        modulus = int.from_bytes(_b64url(jwk["n"], "modulus"), "big")
        exponent = int.from_bytes(_b64url(jwk["e"], "exponent"), "big")
        if modulus.bit_length() < 2048 or exponent != 65537:
            reject("BOOTSTRAP_OIDC_JWKS_INVALID", "OIDC RSA key strength is invalid")
        try:
            rsa.RSAPublicNumbers(exponent, modulus).public_key().verify(
                signature,
                f"{parts[0]}.{parts[1]}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError):
            reject("BOOTSTRAP_OIDC_SIGNATURE_INVALID", "OIDC signature is invalid")

        current = int(self._now().timestamp())
        iat = claims.get("iat")
        nbf = claims.get("nbf")
        exp = claims.get("exp")
        if (
            not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in (iat, nbf, exp)
            )
            or iat > current + 60
            or nbf > current + 60
            or exp < current - 30
            or exp - iat > max_token_age_seconds
            or exp <= nbf
        ):
            reject("BOOTSTRAP_OIDC_TIME_INVALID", "OIDC lifetime is invalid")
        exact = {"iss": ISSUER, "aud": audience, **exact_claims}
        if any(claims.get(name) != value for name, value in exact.items()):
            reject(
                "BOOTSTRAP_OIDC_CLAIM_MISMATCH",
                "OIDC authority claims differ from intent",
            )
        if any(
            self._positive_claim(claims, name) != value
            for name, value in positive_claims.items()
        ):
            reject(
                "BOOTSTRAP_OIDC_CLAIM_MISMATCH", "OIDC run identity differs from intent"
            )
        if any(name in claims for name in forbidden_claims):
            reject(
                "BOOTSTRAP_OIDC_CLAIM_MISMATCH",
                "OIDC contains a claim forbidden by this capability profile",
            )
        for name in required_unique_claims:
            value = claims.get(name)
            if (
                not isinstance(value, str)
                or not value.isascii()
                or not 16 <= len(value) <= 200
                or any(character in value for character in "\r\n\x00")
            ):
                reject(
                    "BOOTSTRAP_OIDC_CLAIM_MISMATCH",
                    "OIDC unique identity claim is invalid",
                )
        return claims


__all__ = [
    "AUDIENCE",
    "GitHubOIDCJWKSLoader",
    "GitHubOIDCVerifier",
    "ISSUER",
]
