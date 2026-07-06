import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/verify_compute_plane_audit_evidence.py"


def valid_evidence() -> dict:
    session_id = "SES-60b83553-4643-47e4-960d-c646251a4422"
    meeting_id = "22222222-2222-4222-8222-222222222222"
    correlation_id = "faz24-direct-stt-20260625T090000Z"
    sha256 = "a" * 64
    return {
        "schemaVersion": "faz24.computePlaneAuditEvidence.v1",
        "status": "pass",
        "tokenIncluded": False,
        "source": {
            "streamKey": "audit:events",
            "redisStreamRecordId": "1782370000000-0",
        },
        "expected": {
            "sessionId": session_id,
            "meetingId": meeting_id,
            "chunkSeq": 0,
            "correlationId": correlation_id,
            "sha256": sha256,
            "byteLength": 512,
            "computePlane": "live-stt",
        },
        "event": {
            "eventType": "CHUNK_FORWARDED_TO_COMPUTE_PLANE",
            "sessionId": session_id,
            "tenantId": "42",
            "userId": "7",
            "meetingId": meeting_id,
            "deviceId": "desktop-smoke-1",
            "language": "tr",
            "chunkSeq": "0",
            "audioFormat": "WAV",
            "sampleRateHz": "16000",
            "channels": "1",
            "sha256": sha256,
            "byteLength": "512",
            "correlationId": correlation_id,
            "forwardedAtMs": "1782370000000",
            "computePlane": "live-stt",
        },
        "boundaries": {
            "chunkForwardedToComputePlaneProven": True,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "destinationUrlIncluded": False,
            "directSttTranscriptProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
        },
        "failures": [],
    }


def run_verifier(tmp_path: Path, data: dict) -> subprocess.CompletedProcess[str]:
    evidence_file = tmp_path / "compute-plane-evidence.json"
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
    assert report["event"]["eventType"] == "CHUNK_FORWARDED_TO_COMPUTE_PLANE"
    assert report["failures"] == []


def test_expected_session_mismatch_fails(tmp_path):
    data = valid_evidence()
    data["event"]["sessionId"] = "SES-other"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("event.sessionId must match expected.sessionId" in failure for failure in report["failures"])


def test_invalid_sha256_fails(tmp_path):
    data = valid_evidence()
    data["event"]["sha256"] = "deadbeef"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("event.sha256" in failure for failure in report["failures"])


def test_missing_expected_hash_context_fails(tmp_path):
    data = valid_evidence()
    del data["expected"]["sha256"]

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("expected must include" in failure for failure in report["failures"])


def test_raw_audio_key_fails(tmp_path):
    data = valid_evidence()
    data["event"]["rawAudio"] = "base64-audio"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("forbidden key" in failure for failure in report["failures"])


def test_transcript_text_key_fails(tmp_path):
    data = valid_evidence()
    data["event"]["transcriptText"] = "merhaba dunya"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("forbidden key" in failure for failure in report["failures"])


def test_destination_url_key_fails(tmp_path):
    data = valid_evidence()
    data["event"]["destinationUrl"] = "https://live-stt.example/transcribe"

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("forbidden key" in failure for failure in report["failures"])


def test_jwt_shaped_value_fails(tmp_path):
    data = valid_evidence()
    jwt_shaped = "eyJaaaaaaaa.bbbbbbbb.cccccccc"
    data["expected"]["correlationId"] = jwt_shaped
    data["event"]["correlationId"] = jwt_shaped

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("secret-like value" in failure for failure in report["failures"])


def test_overclaim_transcript_or_production_fails(tmp_path):
    data = valid_evidence()
    data["boundaries"]["directSttTranscriptProven"] = True
    data["boundaries"]["productionReady"] = True

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("directSttTranscriptProven" in failure for failure in report["failures"])
    assert any("productionReady" in failure for failure in report["failures"])


def test_missing_positive_boundary_fails(tmp_path):
    data = valid_evidence()
    data["boundaries"]["chunkForwardedToComputePlaneProven"] = False

    proc = run_verifier(tmp_path, data)
    report = json.loads(proc.stdout)

    assert proc.returncode == 1
    assert any("chunkForwardedToComputePlaneProven" in failure for failure in report["failures"])


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
