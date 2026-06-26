import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/verify_gcap_capture_gate_evidence.py"

SUCCESS_CHECK_NAMES = [
    "no_sensitive_content",
    "schema_version",
    "status_pass",
    "token_not_included",
    "failures_empty",
    "meeting_id_uuid",
    "capture_id_uuid",
    "session_id_shape",
    "boundary_externalMeetingAdminPathExercised",
    "boundary_recorderLifecycleExercised",
    "boundary_directSttProven",
    "boundary_directClientToStt",
    "boundary_directSttTranscriptProven",
    "boundary_computePlaneAuditProven",
    "boundary_desktopMicLoopbackProven",
    "boundary_productionReady",
    "steps_exact_order",
    "token_contract_step",
    "create_meeting_http_contract",
    "record_consent_http_contract",
    "start_session_http_contract",
    "upload_chunk_http_contract",
    "finish_session_http_contract",
    "session_status_http_contract",
    "create_meeting_response_id",
    "record_consent_response_ids",
    "start_session_response_id",
    "finish_session_final_state",
    "session_status_finished",
]

DESKTOP_SUCCESS_CHECK_NAMES = [
    "no_sensitive_content",
    "schema_version",
    "status_pass",
    "generated_at",
    "token_not_included",
    "failures_empty",
    "client_kind",
    "client_os",
    "client_build_commit",
    "client_capture_mode",
    "client_active_indicator",
    "meeting_id_uuid",
    "capture_id_uuid",
    "session_id_shape",
    "correlation_id_safe",
    "consent_captured",
    "consent_hash",
    "consent_text_absent",
    "microphone_proven",
    "microphone_kind",
    "microphone_real_device",
    "microphone_device_hash",
    "microphone_duration",
    "microphone_sample_rate",
    "microphone_channels",
    "microphone_byte_length",
    "microphone_sha256",
    "microphone_raw_absent",
    "loopback_proven",
    "loopback_kind",
    "loopback_real_device",
    "loopback_device_hash",
    "loopback_duration",
    "loopback_sample_rate",
    "loopback_channels",
    "loopback_byte_length",
    "loopback_sha256",
    "loopback_raw_absent",
    "steps_exact_order",
    "desktop_app_started_ok",
    "permission_check_ok",
    "mic_capture_ok",
    "loopback_capture_ok",
    "record_consent_ok",
    "record_consent_method",
    "record_consent_status",
    "record_consent_path",
    "start_session_ok",
    "start_session_method",
    "start_session_status",
    "start_session_path",
    "upload_mic_chunk_ok",
    "upload_mic_chunk_method",
    "upload_mic_chunk_status",
    "upload_mic_chunk_path",
    "upload_mic_chunk_source",
    "upload_mic_chunk_sha256_match",
    "upload_loopback_chunk_ok",
    "upload_loopback_chunk_method",
    "upload_loopback_chunk_status",
    "upload_loopback_chunk_path",
    "upload_loopback_chunk_source",
    "upload_loopback_chunk_sha256_match",
    "finish_session_ok",
    "finish_session_method",
    "finish_session_status",
    "finish_session_path",
    "session_status_ok",
    "session_status_method",
    "session_status_status",
    "session_status_path",
    "boundary_desktopMicLoopbackProven",
    "boundary_gatewayOnly",
    "boundary_rawAudioIncluded",
    "boundary_rawTranscriptIncluded",
    "boundary_directClientToStt",
    "boundary_directSttTranscriptProven",
    "boundary_computePlaneAuditProven",
    "boundary_productionReady",
]


def verifier_report(index: int, *, status: str = "pass", retry: bool = False) -> dict:
    meeting_id = f"22222222-2222-4222-8222-{index:012d}"
    capture_id = f"33333333-3333-4333-8333-{index:012d}"
    session_id = f"SES-test-{index}"
    checks = [{"name": name, "passed": True, "message": "ok"} for name in SUCCESS_CHECK_NAMES]
    failures: list[str] = []

    if status != "pass":
        checks = [
            {**check, "passed": False, "message": "upload_chunk must pass"}
            if check["name"] == "upload_chunk_http_contract"
            else check
            for check in checks
        ]
        failures = ["upload_chunk must pass"]

    report = {
        "schemaVersion": "faz24.externalRecorderSmokeVerifier.v1",
        "status": status,
        "tokenIncluded": False,
        "checkedAt": "2026-06-25T08:00:00Z",
        "evidenceSchemaVersion": "faz24.externalRecorderSmoke.v1",
        "ids": {
            "meetingId": meeting_id,
            "captureId": capture_id,
            "sessionId": session_id,
        },
        "boundaries": {
            "externalMeetingAdminPathExercised": True,
            "recorderLifecycleExercised": True,
            "directSttProven": False,
            "directClientToStt": False,
            "directSttTranscriptProven": False,
            "computePlaneAuditProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
        },
        "checks": checks,
        "failures": failures,
    }
    if retry:
        report["attemptKind"] = "retry"
    return report


def desktop_verifier_report(index: int, *, status: str = "pass", retry: bool = False) -> dict:
    meeting_id = f"44444444-4444-4444-8444-{index:012d}"
    capture_id = f"55555555-5555-4555-8555-{index:012d}"
    session_id = f"SES-desktop-{index}"
    checks = [{"name": name, "passed": True, "message": "ok"} for name in DESKTOP_SUCCESS_CHECK_NAMES]
    failures: list[str] = []

    if status != "pass":
        checks = [
            {**check, "passed": False, "message": "loopback_capture must pass"}
            if check["name"] == "loopback_capture_ok"
            else check
            for check in checks
        ]
        failures = ["loopback_capture must pass"]

    report = {
        "schemaVersion": "faz24.desktopCaptureEvidenceVerifier.v1",
        "evidenceSchemaVersion": "faz24.desktopCaptureEvidence.v1",
        "status": status,
        "tokenIncluded": False,
        "checkedAt": "2026-06-27T08:00:00Z",
        "ids": {
            "meetingId": meeting_id,
            "captureId": capture_id,
            "sessionId": session_id,
        },
        "boundaries": {
            "desktopMicLoopbackProven": True,
            "gatewayOnly": True,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "directClientToStt": False,
            "directSttTranscriptProven": False,
            "computePlaneAuditProven": False,
            "productionReady": False,
        },
        "checks": checks,
        "failures": failures,
    }
    if retry:
        report["attemptKind"] = "retry"
    return report


def run_gate(tmp_path: Path, payload, *extra_args: str) -> subprocess.CompletedProcess[str]:
    evidence_file = tmp_path / "gcap-input.json"
    if isinstance(payload, str):
        evidence_file.write_text(payload, encoding="utf-8")
    else:
        evidence_file.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--evidence-file", str(evidence_file), *extra_args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_five_clean_reports_pass_default_thresholds(tmp_path):
    reports = [verifier_report(index) for index in range(1, 6)]

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["tokenIncluded"] is False
    assert report["metrics"]["attempts"] == 5
    assert report["metrics"]["passed"] == 5
    assert report["metrics"]["successRate"] == 1.0
    assert report["boundaries"]["directSttProven"] is False
    assert report["metrics"]["attemptClasses"] == {"externalRecorder": 5, "desktopCapture": 0}


def test_wrapper_reports_object_passes(tmp_path):
    payload = {"reports": [verifier_report(index) for index in range(1, 6)]}

    proc = run_gate(tmp_path, payload)
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["metrics"]["sourceCount"] == 1


def test_jsonl_reports_pass(tmp_path):
    payload = "\n".join(json.dumps(verifier_report(index)) for index in range(1, 6))

    proc = run_gate(tmp_path, payload)
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["metrics"]["reportCount"] == 5


def test_desktop_capture_verifier_reports_pass_default_thresholds(tmp_path):
    reports = [desktop_verifier_report(index) for index in range(1, 6)]

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["metrics"]["attemptClasses"] == {"externalRecorder": 0, "desktopCapture": 5}
    assert report["metrics"]["passedAttemptClasses"]["desktopCapture"] == 5
    assert report["boundaries"]["desktopCaptureVerifierInputsAccepted"] is True
    assert report["boundaries"]["desktopMicLoopbackProven"] is True


def test_mixed_external_and_desktop_reports_pass_thresholds(tmp_path):
    reports = [verifier_report(index) for index in range(1, 4)]
    reports.extend(desktop_verifier_report(index) for index in range(4, 6))

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 0
    assert report["status"] == "pass"
    assert report["metrics"]["attemptClasses"] == {"externalRecorder": 3, "desktopCapture": 2}
    assert report["metrics"]["passed"] == 5
    assert report["metrics"]["distinctMeetings"] == 5
    assert report["metrics"]["distinctSessions"] == 5


def test_empty_report_list_blocks(tmp_path):
    proc = run_gate(tmp_path, [])
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert "at least one verifier report is required" in report["failures"]


def test_below_min_attempts_blocks(tmp_path):
    reports = [verifier_report(index) for index in range(1, 4)]

    proc = run_gate(
        tmp_path,
        reports,
        "--min-distinct-meetings",
        "4",
        "--min-distinct-sessions",
        "4",
    )
    report = json.loads(proc.stdout)

    assert proc.returncode == 3
    assert report["status"] == "blocked"
    assert any("attempts must be >=" in failure for failure in report["failures"])


def test_success_rate_below_threshold_fails_when_enough_attempts(tmp_path):
    reports = [verifier_report(index) for index in range(1, 5)]
    reports.append(verifier_report(5, status="fail"))

    proc = run_gate(
        tmp_path,
        reports,
        "--min-distinct-meetings",
        "4",
        "--min-distinct-sessions",
        "4",
    )
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["metrics"]["successRate"] == 0.8
    assert any("success rate must be" in failure for failure in report["failures"])


def test_retry_rate_above_threshold_fails(tmp_path):
    reports = [verifier_report(index, retry=(index == 5)) for index in range(1, 6)]

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert report["metrics"]["retryRate"] == 0.2
    assert any("retry rate must be" in failure for failure in report["failures"])


def test_nested_token_leak_fails(tmp_path):
    reports = [verifier_report(index) for index in range(1, 6)]
    reports[0]["diagnostic"] = {
        "message": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzbW9rZSJ9.signature"
    }

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("secret-like value" in failure for failure in report["failures"])


def test_sensitive_key_leak_fails(tmp_path):
    reports = [verifier_report(index) for index in range(1, 6)]
    reports[0]["diagnostic"] = {"api_key": "redacted-looking-but-forbidden"}

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("forbidden key" in failure for failure in report["failures"])


def test_underlying_unsafe_verifier_check_fails(tmp_path):
    reports = [verifier_report(index) for index in range(1, 6)]
    for check in reports[0]["checks"]:
        if check["name"] == "no_sensitive_content":
            check["passed"] = False
            check["message"] = "secret-like value"

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("unsafe verifier checks" in failure for failure in report["failures"])


def test_boundary_overclaim_fails(tmp_path):
    reports = [verifier_report(index) for index in range(1, 6)]
    reports[0]["boundaries"]["directSttProven"] = True

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("direct-STT" in failure for failure in report["failures"])


def test_external_summary_missing_post_hardening_boundary_checks_fails(tmp_path):
    reports = [verifier_report(index) for index in range(1, 6)]
    reports[0]["boundaries"].pop("directClientToStt")
    reports[0]["boundaries"].pop("directSttTranscriptProven")
    reports[0]["checks"] = [
        check
        for check in reports[0]["checks"]
        if check["name"]
        not in {"boundary_directClientToStt", "boundary_directSttTranscriptProven"}
    ]

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("boundary_directClientToStt" in failure for failure in report["failures"])
    assert any("post-hardening G-CAP expectations" in failure for failure in report["failures"])


def test_external_summary_direct_client_or_transcript_overclaim_fails(tmp_path):
    reports = [verifier_report(index) for index in range(1, 6)]
    reports[0]["boundaries"]["directClientToStt"] = True
    reports[1]["boundaries"]["directSttTranscriptProven"] = True

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("direct-STT" in failure for failure in report["failures"])


def test_desktop_summary_direct_client_to_stt_overclaim_fails(tmp_path):
    reports = [desktop_verifier_report(index) for index in range(1, 6)]
    reports[0]["boundaries"]["directClientToStt"] = True

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("direct-STT" in failure for failure in report["failures"])


def test_raw_smoke_schema_is_not_accepted(tmp_path):
    payload = {
        "schemaVersion": "faz24.externalRecorderSmoke.v1",
        "status": "pass",
        "tokenIncluded": False,
    }

    proc = run_gate(tmp_path, payload)
    report = json.loads(proc.stdout)

    assert proc.returncode == 2
    assert report["status"] == "error"
    assert any("expected one of" in failure for failure in report["failures"])


def test_raw_desktop_capture_schema_is_not_accepted(tmp_path):
    payload = {
        "schemaVersion": "faz24.desktopCaptureEvidence.v1",
        "status": "pass",
        "tokenIncluded": False,
    }

    proc = run_gate(tmp_path, payload)
    report = json.loads(proc.stdout)

    assert proc.returncode == 2
    assert report["status"] == "error"
    assert any("expected one of" in failure for failure in report["failures"])


def test_desktop_summary_sensitive_key_leak_fails(tmp_path):
    reports = [desktop_verifier_report(index) for index in range(1, 6)]
    reports[0]["diagnostic"] = {"transcriptText": "Toplanti metni aggregate kanita girmemeli"}

    proc = run_gate(tmp_path, reports)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert report["status"] == "fail"
    assert any("forbidden key" in failure for failure in report["failures"])


def test_invalid_json_returns_error(tmp_path):
    proc = run_gate(tmp_path, "{not-json")
    report = json.loads(proc.stdout)

    assert proc.returncode == 2
    assert report["status"] == "error"
    assert "invalid JSON" in report["failures"][0]
