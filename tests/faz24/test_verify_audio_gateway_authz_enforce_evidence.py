import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/verify_audio_gateway_authz_enforce_evidence.py"


def valid_evidence() -> dict:
    return {
        "schemaVersion": "faz24.audioGatewayAuthzEnforceEvidence.v1",
        "status": "pass",
        "tokenIncluded": False,
        "environment": {
            "baseUrl": "https://testai.acik.com",
            "namespace": "platform-test",
            "resourceClientId": "audio-gateway-service",
            "enforceAudience": True,
            "requireAudioRecordRole": True,
            "jwksInternal": True,
        },
        "recorderToken": {
            "tokenIncluded": False,
            "audiencePresent": True,
            "audioRecordRolePresent": True,
            "newLoginVerified": True,
            "refreshGrantVerified": True,
        },
        "boundaries": {
            "testClusterOnly": True,
            "directSttProven": False,
            "rawAudioSent": False,
            "computePlaneAuditProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
        },
        "failures": [],
        "checks": [
            {
                "name": "no_token",
                "method": "GET",
                "path": "/api/v1/audio-gateway/sessions/SES-negative/status",
                "statusCode": 401,
                "ok": True,
                "tokenIncluded": False,
            },
            {
                "name": "wrong_audience",
                "method": "GET",
                "path": "/api/v1/audio-gateway/sessions/SES-negative/status",
                "statusCode": 401,
                "ok": True,
                "tokenIncluded": False,
            },
            {
                "name": "missing_audio_record_role",
                "method": "GET",
                "path": "/api/v1/audio-gateway/sessions/SES-negative/status",
                "statusCode": 403,
                "ok": True,
                "tokenIncluded": False,
            },
            {
                "name": "valid_recorder",
                "method": "GET",
                "path": "/api/v1/audio-gateway/sessions/SES-nonexistent/status",
                "statusCode": 404,
                "ok": True,
                "tokenIncluded": False,
                "securityPassed": True,
                "businessStatus": "session-not-found",
            },
        ],
    }


def run_verifier(tmp_path: Path, data: dict) -> subprocess.CompletedProcess[str]:
    evidence_file = tmp_path / "audio-gateway-authz.json"
    evidence_file.write_text(json.dumps(data), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--evidence-file", str(evidence_file)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_valid_evidence_passes(tmp_path):
    proc = run_verifier(tmp_path, valid_evidence())
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["tokenIncluded"] is False
    assert report["resourceClientId"] == "audio-gateway-service"
    assert report["capabilityRole"] == "audio_record"
    assert report["failures"] == []


def test_default_off_environment_fails(tmp_path):
    data = valid_evidence()
    data["environment"]["enforceAudience"] = False

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("enforceAudience" in failure for failure in report["failures"])


def test_missing_role_denial_must_be_403(tmp_path):
    data = valid_evidence()
    data["checks"][2]["statusCode"] = 401

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("missing_audio_record_role.statusCode" in failure for failure in report["failures"])


def test_valid_recorder_404_requires_business_boundary(tmp_path):
    data = valid_evidence()
    data["checks"][3]["businessStatus"] = "authz-denied"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("session-not-found" in failure for failure in report["failures"])


def test_missing_required_check_fails(tmp_path):
    data = valid_evidence()
    data["checks"] = [check for check in data["checks"] if check["name"] != "wrong_audience"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("exact expected order" in failure for failure in report["failures"])


def test_token_leak_fails(tmp_path):
    data = valid_evidence()
    data["checks"][1]["diagnostic"] = (
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzbW9rZSJ9.signature"
    )

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("secret-like value" in failure for failure in report["failures"])


def test_raw_audio_field_fails(tmp_path):
    data = valid_evidence()
    data["checks"][3]["raw_audio"] = "redacted"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("forbidden key" in failure for failure in report["failures"])


def test_overclaim_boundary_fails(tmp_path):
    data = valid_evidence()
    data["boundaries"]["productionReady"] = True
    data["boundaries"]["directSttProven"] = True

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("productionReady" in failure for failure in report["failures"])
    assert any("directSttProven" in failure for failure in report["failures"])


def test_malformed_json_returns_error(tmp_path):
    evidence_file = tmp_path / "broken.json"
    evidence_file.write_text("{not-json", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--evidence-file", str(evidence_file)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    report = json.loads(proc.stdout)

    assert proc.returncode == 2
    assert report["status"] == "error"
