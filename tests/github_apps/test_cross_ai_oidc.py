from __future__ import annotations

import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.oidc import (
    AUDIENCE,
    ISSUER,
    GitHubOIDCVerifier,
)


REPOSITORY_ID = 123456
REPOSITORY = "Halildeu/platform-k8s-gitops"
ENVIRONMENT = "faz22-view-only-pilot"
REQUEST_ID = "10000000-0000-4000-8000-000000000001"
INTENT_REF = f"refs/tags/cross-ai-intent/{REQUEST_ID}"
HEAD_SHA = "a" * 40
WORKFLOW_PATH = ".github/workflows/cross-ai-protected-apply.yml"
RUN_ID = 999001
RUN_ATTEMPT = 1
ACTOR_ID = 987654
KID = "github-actions-test-key"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class GitHubOIDCVerifierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = cls.private_key.public_key().public_numbers()
        cls.jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": KID,
                    "use": "sig",
                    "alg": "RS256",
                    "n": b64url(
                        numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
                    ),
                    "e": b64url(
                        numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
                    ),
                }
            ]
        }

    def setUp(self) -> None:
        self.now = datetime(2026, 7, 17, 8, 0, 0, tzinfo=timezone.utc)
        current = int(self.now.timestamp())
        self.claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "repository_id": str(REPOSITORY_ID),
            "repository": REPOSITORY,
            "environment": ENVIRONMENT,
            "ref": INTENT_REF,
            "sha": HEAD_SHA,
            "event_name": "workflow_dispatch",
            "runner_environment": "self-hosted",
            "workflow_ref": f"{REPOSITORY}/{WORKFLOW_PATH}@{INTENT_REF}",
            "sub": f"repo:{REPOSITORY}:environment:{ENVIRONMENT}",
            "run_id": str(RUN_ID),
            "run_attempt": str(RUN_ATTEMPT),
            "actor_id": str(ACTOR_ID),
            "jti": "20000000-0000-4000-8000-000000000001",
            "iat": current - 10,
            "nbf": current - 10,
            "exp": current + 290,
        }
        self.verifier = GitHubOIDCVerifier(
            jwks_loader=lambda: self.jwks,
            now=lambda: self.now,
        )

    def token(
        self,
        *,
        claims: dict[str, Any] | None = None,
        header: dict[str, Any] | None = None,
        payload_bytes: bytes | None = None,
        private_key: rsa.RSAPrivateKey | None = None,
    ) -> str:
        actual_header = header or {"alg": "RS256", "kid": KID, "typ": "JWT"}
        encoded_header = b64url(
            json.dumps(actual_header, sort_keys=True, separators=(",", ":")).encode()
        )
        encoded_claims = b64url(
            payload_bytes
            or json.dumps(
                claims or self.claims, sort_keys=True, separators=(",", ":")
            ).encode()
        )
        signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
        signature = (private_key or self.private_key).sign(
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return f"{signing_input.decode('ascii')}.{b64url(signature)}"

    def verify(self, token: str) -> dict[str, Any]:
        return self.verifier.verify(
            token,
            repository_id=REPOSITORY_ID,
            repository=REPOSITORY,
            environment=ENVIRONMENT,
            intent_ref=INTENT_REF,
            head_sha=HEAD_SHA,
            workflow_path=WORKFLOW_PATH,
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            actor_id=ACTOR_ID,
        )

    def test_accepts_exact_rs256_github_claims_and_optional_x5t(self) -> None:
        token = self.token(
            header={"alg": "RS256", "kid": KID, "typ": "JWT", "x5t": "thumbprint"}
        )
        self.assertEqual(self.verify(token)["jti"], self.claims["jti"])

    def test_rejects_authority_and_run_claim_drift(self) -> None:
        cases = {
            "aud": "another-audience",
            "ref": "refs/heads/main",
            "sha": "b" * 40,
            "workflow_ref": f"{REPOSITORY}/.github/workflows/other.yml@{INTENT_REF}",
            "run_id": str(RUN_ID + 1),
            "run_attempt": "2",
            "actor_id": str(ACTOR_ID + 1),
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                claims = dict(self.claims)
                claims[name] = value
                with self.assertRaisesRegex(
                    PolicyError, "BOOTSTRAP_OIDC_CLAIM_MISMATCH"
                ):
                    self.verify(self.token(claims=claims))

    def test_rejects_wrong_key_unknown_kid_and_expired_token(self) -> None:
        another_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_OIDC_SIGNATURE_INVALID"):
            self.verify(self.token(private_key=another_key))
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_OIDC_JWKS_INVALID"):
            self.verify(
                self.token(header={"alg": "RS256", "kid": "unknown", "typ": "JWT"})
            )
        expired = dict(self.claims)
        expired["iat"] = int((self.now - timedelta(minutes=6)).timestamp())
        expired["nbf"] = expired["iat"]
        expired["exp"] = int((self.now - timedelta(minutes=1)).timestamp())
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_OIDC_TIME_INVALID"):
            self.verify(self.token(claims=expired))

    def test_refreshes_jwks_once_on_unknown_kid(self) -> None:
        refreshes: list[bool] = []
        verifier = GitHubOIDCVerifier(
            jwks_loader=lambda: {"keys": []},
            jwks_refresher=lambda: refreshes.append(True) or self.jwks,
            now=lambda: self.now,
        )
        claims = verifier.verify(
            self.token(),
            repository_id=REPOSITORY_ID,
            repository=REPOSITORY,
            environment=ENVIRONMENT,
            intent_ref=INTENT_REF,
            head_sha=HEAD_SHA,
            workflow_path=WORKFLOW_PATH,
            run_id=RUN_ID,
            run_attempt=RUN_ATTEMPT,
            actor_id=ACTOR_ID,
        )
        self.assertEqual(claims["jti"], self.claims["jti"])
        self.assertEqual(refreshes, [True])

    def test_rejects_low_public_exponent_profile(self) -> None:
        weak = {"keys": [dict(self.jwks["keys"][0], e=b64url(b"\x03"))]}
        verifier = GitHubOIDCVerifier(
            jwks_loader=lambda: weak,
            now=lambda: self.now,
        )
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_OIDC_JWKS_INVALID"):
            verifier.verify(
                self.token(),
                repository_id=REPOSITORY_ID,
                repository=REPOSITORY,
                environment=ENVIRONMENT,
                intent_ref=INTENT_REF,
                head_sha=HEAD_SHA,
                workflow_path=WORKFLOW_PATH,
                run_id=RUN_ID,
                run_attempt=RUN_ATTEMPT,
                actor_id=ACTOR_ID,
            )

    def test_rejects_duplicate_claim_and_unpinned_header_field(self) -> None:
        canonical = json.dumps(self.claims, sort_keys=True, separators=(",", ":"))
        duplicate = (canonical[:-1] + ',"aud":"duplicate"}').encode()
        with self.assertRaisesRegex(PolicyError, "JSON_DUPLICATE_KEY"):
            self.verify(self.token(payload_bytes=duplicate))
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_OIDC_INVALID"):
            self.verify(
                self.token(
                    header={
                        "alg": "RS256",
                        "kid": KID,
                        "typ": "JWT",
                        "jku": "https://attacker.invalid/jwks",
                    }
                )
            )

    def test_explicit_profile_rejects_forbidden_claim_even_when_empty(self) -> None:
        claims = dict(self.claims)
        claims.pop("environment")
        claims["aud"] = "faz22-view-only-binding"
        claims["runner_environment"] = "github-hosted"
        claims["sub"] = f"repo:{REPOSITORY}:ref:{INTENT_REF}"
        exact = {
            "repository_id": str(REPOSITORY_ID),
            "repository": REPOSITORY,
            "ref": INTENT_REF,
            "sha": HEAD_SHA,
            "event_name": "workflow_dispatch",
            "runner_environment": "github-hosted",
            "workflow_ref": f"{REPOSITORY}/{WORKFLOW_PATH}@{INTENT_REF}",
            "sub": f"repo:{REPOSITORY}:ref:{INTENT_REF}",
        }
        verified = self.verifier.verify_claim_profile(
            self.token(claims=claims),
            audience="faz22-view-only-binding",
            exact_claims=exact,
            positive_claims={
                "run_id": RUN_ID,
                "run_attempt": RUN_ATTEMPT,
                "actor_id": ACTOR_ID,
            },
            forbidden_claims=("environment", "job_workflow_ref"),
        )
        self.assertEqual(verified["ref"], INTENT_REF)

        claims["environment"] = ""
        with self.assertRaisesRegex(
            PolicyError, "BOOTSTRAP_OIDC_CLAIM_MISMATCH"
        ):
            self.verifier.verify_claim_profile(
                self.token(claims=claims),
                audience="faz22-view-only-binding",
                exact_claims=exact,
                positive_claims={
                    "run_id": RUN_ID,
                    "run_attempt": RUN_ATTEMPT,
                    "actor_id": ACTOR_ID,
                },
                forbidden_claims=("environment", "job_workflow_ref"),
            )

    def test_explicit_profile_enforces_actor_and_300_second_lifetime(self) -> None:
        claims = dict(self.claims)
        claims["aud"] = "faz22-view-only-preflight"
        claims["actor_id"] = str(ACTOR_ID + 1)
        exact = {
            "repository": REPOSITORY,
            "ref": INTENT_REF,
            "sha": HEAD_SHA,
        }
        with self.assertRaisesRegex(
            PolicyError, "BOOTSTRAP_OIDC_CLAIM_MISMATCH"
        ):
            self.verifier.verify_claim_profile(
                self.token(claims=claims),
                audience="faz22-view-only-preflight",
                exact_claims=exact,
                positive_claims={"actor_id": ACTOR_ID},
            )

        claims["actor_id"] = str(ACTOR_ID)
        claims["iat"] = int(self.now.timestamp()) - 20
        claims["nbf"] = claims["iat"]
        claims["exp"] = claims["iat"] + 301
        with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_OIDC_TIME_INVALID"):
            self.verifier.verify_claim_profile(
                self.token(claims=claims),
                audience="faz22-view-only-preflight",
                exact_claims=exact,
                positive_claims={"actor_id": ACTOR_ID},
            )


if __name__ == "__main__":
    unittest.main()
