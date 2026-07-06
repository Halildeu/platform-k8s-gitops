import base64
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/keycloak/validate_faz24_platform_desktop_token_contract.py"


def _segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _token(payload: dict) -> str:
    return ".".join(
        [
            _segment({"alg": "none", "typ": "JWT"}),
            _segment(payload),
            "signature",
        ]
    )


def _run(token: str):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=token,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return proc, json.loads(proc.stdout)


def test_valid_platform_desktop_token_contract_passes():
    proc, report = _run(
        _token(
            {
                "iss": "https://testai.acik.com/realms/platform-test",
                "azp": "platform-desktop",
                "aud": ["audio-gateway-service", "meeting-service", "frontend"],
                "tenantId": "1",
                "companyId": "1",
                "userId": "990001",
                "realm_access": {"roles": ["MEETING_ADMIN"]},
                "resource_access": {
                    "audio-gateway-service": {"roles": ["audio_record"]}
                },
            }
        )
    )

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["tokenIncluded"] is False
    assert report["audience"]["gatewayMatches"] == ["frontend"]
    assert all(report["claims"].values())
    assert report["clientRole"]["present"] is True


def test_missing_gateway_compatible_audience_fails():
    proc, report = _run(
        _token(
            {
                "azp": "platform-desktop",
                "aud": ["audio-gateway-service", "meeting-service"],
                "tenantId": "1",
                "companyId": "1",
                "userId": "990001",
                "realm_access": {"roles": ["MEETING_ADMIN"]},
                "resource_access": {
                    "audio-gateway-service": {"roles": ["audio_record"]}
                },
            }
        )
    )

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["audience"]["gatewayCompatible"] is False
    assert any("api-gateway-compatible" in failure for failure in report["failures"])


def test_missing_required_claim_and_role_fail_without_leaking_token():
    token = _token(
        {
            "azp": "platform-desktop",
            "aud": ["audio-gateway-service", "meeting-service", "account"],
            "tenantId": "1",
            "userId": "990001",
            "realm_access": {"roles": ["USER"]},
        }
    )
    proc, report = _run(
        token
    )

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["claims"]["companyId"] is False
    assert report["realmRole"]["present"] is False
    assert token not in proc.stdout
    assert token not in proc.stderr
    assert "access_token" not in proc.stdout
    assert "access_token" not in proc.stderr
    assert "signature" not in proc.stdout
    assert "signature" not in proc.stderr


def test_missing_audio_record_client_role_fails():
    proc, report = _run(
        _token(
            {
                "azp": "platform-desktop",
                "aud": ["audio-gateway-service", "meeting-service", "frontend"],
                "tenantId": "1",
                "companyId": "1",
                "userId": "990001",
                "realm_access": {"roles": ["MEETING_ADMIN"]},
            }
        )
    )

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["clientRole"]["resourceClientId"] == "audio-gateway-service"
    assert report["clientRole"]["present"] is False
    assert report["clientRole"]["missing"] == ["audio_record"]
    assert any("missing client role" in failure for failure in report["failures"])


def test_token_file_input_path_passes(tmp_path):
    token_file = tmp_path / "token.jwt"
    token_file.write_text(
        _token(
            {
                "azp": "platform-desktop",
                "aud": ["audio-gateway-service", "meeting-service", "auth-service"],
                "tenantId": "1",
                "companyId": "1",
                "userId": "990001",
                "realm_access": {"roles": ["MEETING_ADMIN"]},
                "resource_access": {
                    "audio-gateway-service": {"roles": ["audio_record"]}
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--token-file", str(token_file)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["audience"]["gatewayMatches"] == ["auth-service"]


def test_required_azp_mismatch_fails():
    proc, report = _run(
        _token(
            {
                "azp": "wrong-client",
                "aud": ["audio-gateway-service", "meeting-service", "frontend"],
                "tenantId": "1",
                "companyId": "1",
                "userId": "990001",
                "realm_access": {"roles": ["MEETING_ADMIN"]},
                "resource_access": {
                    "audio-gateway-service": {"roles": ["audio_record"]}
                },
            }
        )
    )

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("azp mismatch" in failure for failure in report["failures"])


def test_expected_issuer_can_be_enforced():
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--expected-issuer",
            "https://testai.acik.com/realms/platform-test",
        ],
        input=_token(
            {
                "iss": "https://wrong.example/realms/platform-test",
                "azp": "platform-desktop",
                "aud": ["audio-gateway-service", "meeting-service", "frontend"],
                "tenantId": "1",
                "companyId": "1",
                "userId": "990001",
                "realm_access": {"roles": ["MEETING_ADMIN"]},
            }
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("issuer mismatch" in failure for failure in report["failures"])


def test_malformed_input_returns_error():
    proc, report = _run("not-a-jwt")

    assert proc.returncode == 2
    assert report["status"] == "error"
    assert report["tokenIncluded"] is False
