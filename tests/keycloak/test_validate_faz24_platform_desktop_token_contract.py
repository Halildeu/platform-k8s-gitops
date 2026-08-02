import base64
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/keycloak/validate_faz24_platform_desktop_token_contract.py"
CANONICAL_COMPANY_1 = "68c73eb9-c410-37dc-aff7-5ade8fbbcbb7"
CANONICAL_COMPANY_42 = "310d6171-0b74-39b5-901a-b9dd75864177"


def _segment(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _token(payload: dict) -> str:
    payload = {
        "sub": "11111111-2222-3333-8444-555555555555",
        "org_id": CANONICAL_COMPANY_1,
        "tenant_id": CANONICAL_COMPANY_1,
        **payload,
    }
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
    assert report["tenantAliases"]["consistent"] is True
    assert report["tenantAliases"]["valuesIncluded"] is False
    assert report["clientRole"]["present"] is True


def test_additional_realtime_realm_role_is_fail_closed():
    token = _token(
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
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--additional-required-roles",
            "TRANSCRIPT_ADMIN",
        ],
        input=token,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["additionalRealmRoles"] == {
        "required": ["TRANSCRIPT_ADMIN"],
        "missing": ["TRANSCRIPT_ADMIN"],
        "present": False,
    }
    assert token not in proc.stdout


def test_additional_realtime_realm_role_passes_when_token_contains_it():
    token = _token(
        {
            "iss": "https://testai.acik.com/realms/platform-test",
            "azp": "platform-desktop",
            "aud": ["audio-gateway-service", "meeting-service", "frontend"],
            "tenantId": "1",
            "companyId": "1",
            "userId": "990001",
            "realm_access": {"roles": ["MEETING_ADMIN", "TRANSCRIPT_ADMIN"]},
            "resource_access": {
                "audio-gateway-service": {"roles": ["audio_record"]}
            },
        }
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--additional-required-roles",
            "TRANSCRIPT_ADMIN",
        ],
        input=token,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["additionalRealmRoles"] == {
        "required": ["TRANSCRIPT_ADMIN"],
        "missing": [],
        "present": True,
    }


def test_conflicting_tenant_aliases_fail_without_emitting_values():
    proc, report = _run(
        _token(
            {
                "azp": "platform-desktop",
                "aud": ["audio-gateway-service", "meeting-service", "frontend"],
                "tenant_id": "00000000-0000-0000-0000-000000000001",
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
    assert report["tenantAliases"]["consistent"] is False
    assert report["tenantAliases"]["valuesIncluded"] is False
    assert any("conflicting tenant claim aliases" in item for item in report["failures"])
    assert CANONICAL_COMPANY_1 not in proc.stdout
    assert "00000000-0000-0000-0000-000000000001" not in proc.stdout


def test_java_name_uuid_compatibility_for_non_default_company():
    proc, report = _run(
        _token(
            {
                "org_id": CANONICAL_COMPANY_42,
                "tenant_id": CANONICAL_COMPANY_42,
                "azp": "platform-desktop",
                "aud": ["audio-gateway-service", "meeting-service", "frontend"],
                "tenantId": "42",
                "companyId": "42",
                "userId": "990042",
                "realm_access": {"roles": ["MEETING_ADMIN"]},
                "resource_access": {
                    "audio-gateway-service": {"roles": ["audio_record"]}
                },
            }
        )
    )

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["tenantAliases"]["consistent"] is True
    assert CANONICAL_COMPANY_42 not in proc.stdout


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
    assert report["tenantAliases"]["missing"] == ["companyId"]
    assert report["tenantAliases"]["consistent"] is False
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
