import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/verify_external_recorder_smoke_evidence.py"


def valid_evidence() -> dict:
    meeting_id = "22222222-2222-4222-8222-222222222222"
    capture_id = "33333333-3333-4333-8333-333333333333"
    session_id = "SES-test-1"
    return {
        "schemaVersion": "faz24.externalRecorderSmoke.v1",
        "status": "pass",
        "tokenIncluded": False,
        "startedAt": "2026-06-25T08:00:00Z",
        "completedAt": "2026-06-25T08:01:00Z",
        "ids": {
            "meetingId": meeting_id,
            "captureId": capture_id,
            "sessionId": session_id,
        },
        "boundaries": {
            "externalMeetingAdminPathExercised": True,
            "recorderLifecycleExercised": True,
            "directSttProven": False,
            "directSttTranscriptProven": False,
            "directClientToStt": False,
            "computePlaneAuditProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
        },
        "failures": [],
        "steps": [
            {
                "name": "token_contract",
                "ok": True,
                "report": {
                    "schemaVersion": "faz24.platformDesktopTokenContract.v1",
                    "status": "pass",
                    "tokenIncluded": False,
                    "azp": "platform-desktop",
                    "issuer": "https://testai.acik.com/realms/platform-test",
                    "audience": {
                        "values": ["audio-gateway-service", "meeting-service", "frontend"],
                        "gatewayCompatible": True,
                    },
                    "claims": {
                        "sub": True,
                        "org_id": True,
                        "tenant_id": True,
                        "tenantId": True,
                        "companyId": True,
                        "userId": True,
                    },
                    "tenantAliases": {
                        "consistent": True,
                        "valuesIncluded": False,
                    },
                    "realmRole": {"required": "MEETING_ADMIN", "present": True},
                    "failures": [],
                },
            },
            {
                "name": "create_meeting",
                "method": "POST",
                "path": "/api/v1/admin/meetings",
                "expectedStatus": [201],
                "statusCode": 201,
                "ok": True,
                "tokenIncluded": False,
                "response": {"id": meeting_id, "status": "SCHEDULED"},
            },
            {
                "name": "record_consent",
                "method": "POST",
                "path": "/api/v1/audio-gateway/consents",
                "expectedStatus": [201],
                "statusCode": 201,
                "ok": True,
                "tokenIncluded": False,
                "response": {"meetingId": meeting_id, "captureId": capture_id},
            },
            {
                "name": "start_session",
                "method": "POST",
                "path": "/api/v1/audio-gateway/sessions",
                "expectedStatus": [200, 201],
                "statusCode": 201,
                "ok": True,
                "tokenIncluded": False,
                "response": {"sessionId": session_id},
            },
            {
                "name": "upload_chunk",
                "method": "POST",
                "path": f"/api/v1/audio-gateway/sessions/{session_id}/chunks",
                "expectedStatus": [200],
                "statusCode": 200,
                "ok": True,
                "tokenIncluded": False,
                "response": {"sessionId": session_id, "chunkCount": 1},
            },
            {
                "name": "finish_session",
                "method": "POST",
                "path": f"/api/v1/audio-gateway/sessions/{session_id}/finish",
                "expectedStatus": [200],
                "statusCode": 200,
                "ok": True,
                "tokenIncluded": False,
                "response": {"sessionId": session_id, "finalState": "FINISHED"},
            },
            {
                "name": "session_status",
                "method": "GET",
                "path": f"/api/v1/audio-gateway/sessions/{session_id}/status",
                "expectedStatus": [200],
                "statusCode": 200,
                "ok": True,
                "tokenIncluded": False,
                "response": {"sessionId": session_id, "state": "FINISHED", "chunkCount": 1},
            },
        ],
    }


def run_verifier(tmp_path: Path, data: dict) -> subprocess.CompletedProcess[str]:
    evidence_file = tmp_path / "evidence.json"
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
    assert report["evidenceSchemaVersion"] == "faz24.externalRecorderSmoke.v1"
    assert report["failures"] == []


def test_missing_required_step_fails(tmp_path):
    data = valid_evidence()
    data["steps"] = [step for step in data["steps"] if step["name"] != "upload_chunk"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("exact expected order" in failure for failure in report["failures"])


def test_wrong_step_order_fails(tmp_path):
    data = valid_evidence()
    data["steps"][4], data["steps"][5] = data["steps"][5], data["steps"][4]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("exact expected order" in failure for failure in report["failures"])


def test_non_finished_status_fails(tmp_path):
    data = valid_evidence()
    data["steps"][-1]["response"]["state"] = "PROCESSING"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("response.state must be FINISHED" in failure for failure in report["failures"])


def test_finish_without_final_state_fails(tmp_path):
    data = valid_evidence()
    del data["steps"][-2]["response"]["finalState"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("response.finalState must be FINISHED" in failure for failure in report["failures"])


def test_nested_token_leak_fails(tmp_path):
    data = valid_evidence()
    data["steps"][1]["response"]["diagnostic"] = {
        "message": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzbW9rZSJ9.signature"
    }

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("secret-like" in failure for failure in report["failures"])


def test_sensitive_key_leak_fails(tmp_path):
    data = valid_evidence()
    data["steps"][1]["response"]["api_key"] = "redacted-looking-but-forbidden"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("forbidden key" in failure for failure in report["failures"])


def test_camelcase_sensitive_key_leak_fails(tmp_path):
    data = valid_evidence()
    data["steps"][1]["response"]["destinationUrl"] = "https://internal.example.invalid/callback"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("forbidden key" in failure for failure in report["failures"])


def test_url_like_value_under_safe_key_fails(tmp_path):
    data = valid_evidence()
    data["steps"][1]["response"]["diagnostic"] = "https://internal.example.invalid/callback"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("URL-like" in failure for failure in report["failures"])


def test_data_audio_value_fails(tmp_path):
    data = valid_evidence()
    data["steps"][4]["response"]["preview"] = "data:audio/wav;base64,QUJDRA=="

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("raw audio" in failure for failure in report["failures"])


def test_unsafe_session_id_fails(tmp_path):
    data = valid_evidence()
    unsafe = "SES-../../secret"
    data["ids"]["sessionId"] = unsafe
    for step in data["steps"]:
        if step["name"] == "start_session":
            step["response"]["sessionId"] = unsafe
        elif step["name"] in {"upload_chunk", "finish_session", "session_status"}:
            step["path"] = step["path"].replace("SES-test-1", unsafe)
            step["response"]["sessionId"] = unsafe

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("ids.sessionId" in failure for failure in report["failures"])


def test_top_level_token_included_fails(tmp_path):
    data = valid_evidence()
    data["tokenIncluded"] = True

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("top-level tokenIncluded" in failure for failure in report["failures"])


def test_overclaim_boundary_fails(tmp_path):
    data = valid_evidence()
    data["boundaries"]["directSttProven"] = True
    data["boundaries"]["directSttTranscriptProven"] = True
    data["boundaries"]["directClientToStt"] = True
    data["boundaries"]["productionReady"] = True

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("directSttProven" in failure for failure in report["failures"])
    assert any("directSttTranscriptProven" in failure for failure in report["failures"])
    assert any("directClientToStt" in failure for failure in report["failures"])
    assert any("productionReady" in failure for failure in report["failures"])


def test_required_positive_boundary_fails_when_false(tmp_path):
    data = valid_evidence()
    data["boundaries"]["externalMeetingAdminPathExercised"] = False

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("externalMeetingAdminPathExercised" in failure for failure in report["failures"])


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
    assert any("invalid JSON" in failure for failure in report["failures"])


def test_output_file_is_owner_only(tmp_path):
    evidence_file = tmp_path / "evidence.json"
    output_file = tmp_path / "verify.json"
    evidence_file.write_text(json.dumps(valid_evidence()), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--evidence-file",
            str(evidence_file),
            "--output-file",
            str(output_file),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 0
    assert json.loads(output_file.read_text(encoding="utf-8"))["status"] == "pass"
    assert output_file.stat().st_mode & 0o777 == 0o600
