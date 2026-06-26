#!/usr/bin/env python3
"""Tests for Faz 24 desktop mic + loopback capture evidence verifier."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify_desktop_capture_evidence.py"

MIC_SHA = "1" * 64
LOOPBACK_SHA = "2" * 64
DEVICE_HASH = "sha256:" + "a" * 64
CONSENT_HASH = "sha256:" + "b" * 64
SESSION_ID = "SES-31a15790-57eb-4cbe-b923-954c8f6578ac"


def valid_evidence() -> dict:
    return {
        "schemaVersion": "faz24.desktopCaptureEvidence.v1",
        "status": "pass",
        "generatedAt": "2026-06-27T00:00:00Z",
        "tokenIncluded": False,
        "client": {
            "kind": "platform-desktop",
            "os": "windows",
            "appVersion": "0.24.0-smoke",
            "buildCommit": "unknown",
            "captureMode": "real-device",
            "activeIndicatorVisible": True,
        },
        "session": {
            "meetingId": "ce3982b6-0a85-4b56-aecf-de3234af8224",
            "captureId": "b003d1a4-1428-41ad-a47d-fe374ad1b013",
            "sessionId": SESSION_ID,
            "correlationId": "faz24-desktop-capture-20260627T000000Z",
        },
        "consent": {
            "recordingConsentCaptured": True,
            "consentTextHash": CONSENT_HASH,
            "consentTextIncluded": False,
        },
        "sources": {
            "microphone": {
                "proven": True,
                "sourceKind": "microphone",
                "synthetic": False,
                "deviceLabelHash": DEVICE_HASH,
                "durationMs": 1500,
                "sampleRateHz": 16000,
                "channels": 1,
                "byteLength": 48000,
                "sha256": MIC_SHA,
                "rawAudioIncluded": False,
            },
            "loopback": {
                "proven": True,
                "sourceKind": "loopback",
                "synthetic": False,
                "deviceLabelHash": DEVICE_HASH,
                "durationMs": 1500,
                "sampleRateHz": 48000,
                "channels": 2,
                "byteLength": 192000,
                "sha256": LOOPBACK_SHA,
                "rawAudioIncluded": False,
            },
        },
        "steps": [
            {"name": "desktop_app_started", "ok": True},
            {"name": "permission_check", "ok": True},
            {"name": "mic_capture", "ok": True},
            {"name": "loopback_capture", "ok": True},
            {
                "name": "record_consent",
                "ok": True,
                "method": "POST",
                "path": "/api/v1/audio-gateway/consents",
                "statusCode": 201,
            },
            {
                "name": "start_session",
                "ok": True,
                "method": "POST",
                "path": "/api/v1/audio-gateway/sessions",
                "statusCode": 201,
            },
            {
                "name": "upload_mic_chunk",
                "ok": True,
                "method": "POST",
                "path": f"/api/v1/audio-gateway/sessions/{SESSION_ID}/chunks",
                "statusCode": 200,
                "source": "microphone",
                "sha256": MIC_SHA,
            },
            {
                "name": "upload_loopback_chunk",
                "ok": True,
                "method": "POST",
                "path": f"/api/v1/audio-gateway/sessions/{SESSION_ID}/chunks",
                "statusCode": 200,
                "source": "loopback",
                "sha256": LOOPBACK_SHA,
            },
            {
                "name": "finish_session",
                "ok": True,
                "method": "POST",
                "path": f"/api/v1/audio-gateway/sessions/{SESSION_ID}/finish",
                "statusCode": 200,
            },
            {
                "name": "session_status",
                "ok": True,
                "method": "GET",
                "path": f"/api/v1/audio-gateway/sessions/{SESSION_ID}/status",
                "statusCode": 200,
            },
        ],
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
        "failures": [],
    }


def run_validator(data: dict) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
        json.dump(data, tmp)
        tmp.flush()
        return subprocess.run(
            [sys.executable, str(SCRIPT), tmp.name],
            text=True,
            capture_output=True,
            check=False,
        )


def test_valid_evidence_passes():
    result = run_validator(valid_evidence())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Faz 24 desktop capture evidence: PASS" in result.stdout


def test_summary_json_exposes_only_redacted_aggregate_fields(tmp_path):
    evidence_file = tmp_path / "desktop-evidence.json"
    summary_file = tmp_path / "desktop-summary.json"
    evidence_file.write_text(json.dumps(valid_evidence()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(evidence_file),
            "--summary-json",
            str(summary_file),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    summary = json.loads(summary_file.read_text(encoding="utf-8"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert summary["schemaVersion"] == "faz24.desktopCaptureEvidenceVerifier.v1"
    assert summary["evidenceSchemaVersion"] == "faz24.desktopCaptureEvidence.v1"
    assert summary["status"] == "pass"
    assert summary["tokenIncluded"] is False
    assert summary["ids"] == {
        "meetingId": "ce3982b6-0a85-4b56-aecf-de3234af8224",
        "captureId": "b003d1a4-1428-41ad-a47d-fe374ad1b013",
        "sessionId": SESSION_ID,
    }
    assert summary["boundaries"]["desktopMicLoopbackProven"] is True
    rendered = json.dumps(summary)
    assert DEVICE_HASH not in rendered
    assert MIC_SHA not in rendered
    assert LOOPBACK_SHA not in rendered


def test_raw_audio_key_is_rejected():
    data = valid_evidence()
    data["sources"]["microphone"]["raw_audio"] = "AAAA"

    result = run_validator(data)

    assert result.returncode != 0
    assert "no_sensitive_content" in result.stdout


def test_camel_case_sensitive_keys_are_rejected():
    data = valid_evidence()
    data["destinationUrl"] = "https://internal-stt.example.test/transcribe"
    data["transcriptText"] = "Toplanti transcript metni olmamali"
    data["sttEndpoint"] = "https://whisper.internal.example.test/v1/transcriptions"
    data["callbackUrl"] = "https://callback.internal.example.test/hook"

    result = run_validator(data)

    assert result.returncode != 0
    assert "no_sensitive_content" in result.stdout
    assert "destinationUrl" in result.stdout
    assert "transcriptText" in result.stdout
    assert "sttEndpoint" in result.stdout
    assert "callbackUrl" in result.stdout


def test_loopback_must_be_real_device_and_proven():
    data = valid_evidence()
    data["sources"]["loopback"]["proven"] = False
    data["sources"]["loopback"]["synthetic"] = True

    result = run_validator(data)

    assert result.returncode != 0
    assert "loopback_proven" in result.stdout
    assert "loopback_real_device" in result.stdout


def test_direct_stt_and_production_overclaim_fails():
    data = valid_evidence()
    data["boundaries"]["directClientToStt"] = True
    data["boundaries"]["directSttTranscriptProven"] = True
    data["boundaries"]["productionReady"] = True

    result = run_validator(data)

    assert result.returncode != 0
    assert "boundary_directClientToStt" in result.stdout
    assert "boundary_directSttTranscriptProven" in result.stdout
    assert "boundary_productionReady" in result.stdout


def test_session_id_must_be_safe_path_segment():
    data = valid_evidence()
    data["session"]["sessionId"] = "SES-../../bad session"
    data["steps"][6]["path"] = "/api/v1/audio-gateway/sessions/SES-../../bad session/chunks"
    data["steps"][7]["path"] = "/api/v1/audio-gateway/sessions/SES-../../bad session/chunks"
    data["steps"][8]["path"] = "/api/v1/audio-gateway/sessions/SES-../../bad session/finish"
    data["steps"][9]["path"] = "/api/v1/audio-gateway/sessions/SES-../../bad session/status"

    result = run_validator(data)

    assert result.returncode != 0
    assert "session_id_shape" in result.stdout


def test_step_order_must_be_exact():
    data = valid_evidence()
    data["steps"] = copy.deepcopy(data["steps"])
    data["steps"][2], data["steps"][3] = data["steps"][3], data["steps"][2]

    result = run_validator(data)

    assert result.returncode != 0
    assert "steps_exact_order" in result.stdout


def test_upload_sha_must_match_source_digest():
    data = valid_evidence()
    data["steps"][6]["sha256"] = "3" * 64

    result = run_validator(data)

    assert result.returncode != 0
    assert "upload_mic_chunk_sha256_match" in result.stdout
