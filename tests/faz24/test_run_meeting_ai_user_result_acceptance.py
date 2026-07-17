import importlib.util
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "faz24"
    / "run_meeting_ai_user_result_acceptance.py"
)
SPEC = importlib.util.spec_from_file_location("meeting_ai_user_result_acceptance", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acceptance
SPEC.loader.exec_module(acceptance)


def _service_evidence(meeting_id, analysis_run_id):
    return {
        "accepted": True,
        "syntheticWrite": {
            "meetingId": str(meeting_id),
            "analysisRunId": str(analysis_run_id),
            "containsUserTranscript": False,
            "containsPii": False,
        },
        "checks": [{"id": "ingest-first-write", "pass": True}],
    }


def _result_body(meeting_id, analysis_run_id):
    return {
        "meetingId": str(meeting_id),
        "analysisRunId": str(analysis_run_id),
        "schema_version": "5-adr0043",
        "model": "runtime-smoke",
        "backend": "synthetic",
        "summary": acceptance.EXPECTED_SUMMARY,
        "persisted": True,
        "storageMode": "canonical",
        "redacted": True,
        "decisions": [],
        "action_items": [],
    }


def _audit_value():
    return {
        "rowCount": 1,
        "orgMatchesTenant": True,
        "subjectPresent": True,
        "accessTypeExact": True,
        "resultCountExact": True,
        "traceValuesAllowlisted": True,
        "metadataColumnsExact": True,
    }


def test_user_result_acceptance_proves_write_read_and_metadata_only_audit():
    meeting_id = uuid.uuid4()
    analysis_run_id = uuid.uuid4()
    secret_token = "eyJ.test-user-token.signature"

    def fake_service_writer(**kwargs):
        assert kwargs["meeting_id"] == meeting_id
        return _service_evidence(meeting_id, analysis_run_id)

    def fake_user_request(public_base_url, requested_meeting_id, token, timeout):
        assert public_base_url == "https://testai.acik.com"
        assert requested_meeting_id == meeting_id
        assert token == secret_token
        assert timeout == 10
        return acceptance.UserHttpResult(
            200,
            {"cache-control": "no-store"},
            json.dumps(_result_body(meeting_id, analysis_run_id)).encode(),
        )

    def fake_audit_reader(**kwargs):
        assert kwargs["meeting_id"] == meeting_id
        assert kwargs["analysis_run_id"] == analysis_run_id
        return _audit_value()

    evidence, accepted = acceptance.run_acceptance(
        context="k3d-test",
        namespace="platform-test",
        public_base_url="https://testai.acik.com",
        private_base_url="http://127.0.0.1:31080",
        private_host="meeting-ai-private.testai.internal",
        pg_container="platform-pg-test",
        pg_database="meeting",
        meeting_id=meeting_id,
        token=secret_token,
        timeout_seconds=10,
        service_writer=fake_service_writer,
        user_request=fake_user_request,
        audit_reader=fake_audit_reader,
    )

    assert accepted is True
    assert evidence["accepted"] is True
    assert evidence["userRead"]["accepted"] is True
    assert evidence["metadataOnlyAudit"]["accepted"] is True
    assert evidence["boundaries"]["canonicalResponseBodyIncluded"] is False
    serialized = json.dumps(evidence)
    assert secret_token not in serialized
    assert acceptance.EXPECTED_SUMMARY not in serialized
    assert "accessorSubject" not in serialized


def test_user_result_acceptance_fails_when_public_read_is_not_cache_safe():
    meeting_id = uuid.uuid4()
    analysis_run_id = uuid.uuid4()

    evidence, accepted = acceptance.run_acceptance(
        context="k3d-test",
        namespace="platform-test",
        public_base_url="https://testai.acik.com",
        private_base_url="http://127.0.0.1:31080",
        private_host="meeting-ai-private.testai.internal",
        pg_container="platform-pg-test",
        pg_database="meeting",
        meeting_id=meeting_id,
        token="eyJ.test.signature",
        timeout_seconds=10,
        service_writer=lambda **_kwargs: _service_evidence(meeting_id, analysis_run_id),
        user_request=lambda *_args: acceptance.UserHttpResult(
            200,
            {"cache-control": "private"},
            json.dumps(_result_body(meeting_id, analysis_run_id)).encode(),
        ),
        audit_reader=lambda **_kwargs: _audit_value(),
    )

    assert accepted is False
    assert evidence["userRead"]["accepted"] is False
    assert any(
        item["id"] == "cache-control-no-store" and item["pass"] is False
        for item in evidence["userRead"]["checks"]
    )


def test_exact_test_allowlist_is_checked_before_token_read(tmp_path):
    token_file = tmp_path / "token.jwt"
    token_file.write_text("must-not-be-read", encoding="utf-8")
    os.chmod(token_file, 0o600)
    output = tmp_path / "evidence.json"

    exit_code = acceptance.main(
        [
            "--context",
            "k3d-prod",
            "--meeting-id",
            str(uuid.uuid4()),
            "--token-file",
            str(token_file),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    assert not output.exists()


def test_token_file_must_be_mode_0600_regular_file(tmp_path):
    token_file = tmp_path / "token.jwt"
    token_file.write_text("eyJ.test.signature", encoding="utf-8")
    os.chmod(token_file, 0o640)

    try:
        acceptance.read_user_token(token_file)
    except acceptance.AcceptanceError as exc:
        assert "mode-0600" in str(exc)
    else:
        raise AssertionError("group-readable token file must be rejected")


def test_audit_contract_rejects_duplicate_rows():
    value = _audit_value()
    value["rowCount"] = 2

    checks, accepted = acceptance._audit_checks(value)

    assert accepted is False
    assert checks[0] == {"id": "audit-rowCount", "pass": False}


def test_audit_reader_uses_jsonb_contract_and_select_only_sql(monkeypatch):
    meeting_id = uuid.uuid4()
    analysis_run_id = uuid.uuid4()

    def fake_run(command, *, input, text, capture_output, check, timeout):
        assert command[:4] == ["docker", "exec", "-i", "platform-pg-test"]
        assert "::jsonb" in input
        assert "SELECT json_build_object" in input
        assert not any(word in input.upper() for word in ("INSERT ", "UPDATE ", "DELETE ", "ALTER "))
        return subprocess.CompletedProcess(command, 0, json.dumps(_audit_value()), "")

    monkeypatch.setattr(acceptance.subprocess, "run", fake_run)
    value = acceptance.read_access_audit(
        pg_container="platform-pg-test",
        pg_database="meeting",
        meeting_id=meeting_id,
        analysis_run_id=analysis_run_id,
        started_at=datetime.now(timezone.utc),
        timeout_seconds=10,
    )

    assert value == _audit_value()


def test_evidence_writer_is_mode_0600_and_rejects_symlink(tmp_path):
    output = tmp_path / "evidence.json"
    acceptance.write_evidence(output, {"accepted": True})
    assert output.stat().st_mode & 0o777 == 0o600

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    linked = tmp_path / "linked.json"
    linked.symlink_to(target)
    try:
        acceptance.write_evidence(linked, {"accepted": False})
    except acceptance.AcceptanceError as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("symlink output must be rejected")
