from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/faz24-cert-rotation-drill-evidence-ingest.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_dispatches_cert_rotation_drill_ingest():
    text = workflow_text()

    assert "workflow_dispatch:" in text
    assert "evidence_json_base64" in text
    assert "Faz 24 Meeting-AI Cert Rotation Drill Evidence Ingest" in text
    assert "faz24-cert-rotation-drill-${{ github.run_id }}" in text


def test_workflow_bounds_dispatch_payload_size():
    text = workflow_text()

    assert 'if [ "${#EVIDENCE_JSON_BASE64}" -gt 200000 ]; then' in text
    assert "evidence_json_base64 is too large" in text
    assert "evidence_json_base64 must be plain base64" in text


def test_workflow_routes_to_cert_rotation_drill_verifier():
    text = workflow_text()

    assert "scripts/faz24/verify_meeting_ai_cert_rotation_drill_evidence.py" in text
    assert '"${EVIDENCE_JSON}" \\' in text
    assert '--summary-json "${SUMMARY_JSON}"' in text


def test_workflow_preserves_no_mutation_and_secret_scan_boundaries():
    text = workflow_text()

    assert "contents: read" in text
    assert "does not run the live drill, seed Vault" in text
    assert "-e 'Bearer '" in text
    assert "-e 'Authorization:'" in text
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,'" in text
    assert "PRIVATE KEY" in text
    assert "vault_token" in text
    assert "issuing_ca" in text
    assert "raw_audio" in text
    assert "transcript" in text
    assert "full_name" in text
    assert "id: secret_scan" in text
    assert "steps.secret_scan.outcome == 'success'" in text


def test_grep_patterns_keep_option_separator_after_patterns():
    text = workflow_text()

    secret_scan = text.split("- name: Verify artifact excludes private material", 1)[1]
    secret_scan = secret_scan.split("- name: Write workflow summary", 1)[0]

    assert "grep -R -I -q -E --" not in secret_scan
    assert "grep -E --" not in secret_scan
    assert "-e '-----BEGIN CERTIFICATE-----'" in secret_scan
    assert '-- "${EVIDENCE_DIR}"' in secret_scan


def test_workflow_uploads_artifact_before_failure_guard():
    text = workflow_text()

    upload_index = text.index("Upload evidence ingest artifact")
    cleanup_index = text.index("Cleanup local evidence directory")
    failure_index = text.index("Fail workflow when evidence is rejected")

    assert "actions/upload-artifact@v7" in text
    assert upload_index < cleanup_index < failure_index
    assert "retention-days: 14" in text
