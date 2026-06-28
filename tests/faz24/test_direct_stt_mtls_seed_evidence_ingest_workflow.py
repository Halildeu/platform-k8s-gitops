from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/faz24-direct-stt-mtls-seed-evidence-ingest.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_dispatches_seed_evidence_ingest():
    text = workflow_text()

    assert "workflow_dispatch:" in text
    assert "evidence_json_base64:" in text
    assert "contents: read" in text
    assert "faz24-direct-stt-mtls-seed-${{ github.run_id }}" in text
    assert "cancel-in-progress: false" in text


def test_workflow_routes_to_seed_evidence_verifier():
    text = workflow_text()

    assert "scripts/faz24/verify_direct_stt_mtls_seed_operator_evidence.py" in text
    assert '"${EVIDENCE_JSON}"' in text
    assert '--summary-json "${SUMMARY_JSON}"' in text
    assert "verification-summary.json" in text


def test_workflow_preserves_no_mutation_and_acceptance_boundaries():
    text = workflow_text()

    assert "does not read PEM files" in text
    assert "read Vault tokens" in text
    assert "mutate Vault/Kubernetes/Denetim/firewall" in text
    assert "enable direct-STT" in text
    assert "call /transcribe" in text
    assert "send audio" in text
    assert "prove ESO reconciliation" in text
    assert "production-readiness claim" in text


def test_workflow_scans_artifact_before_upload():
    text = workflow_text()

    assert 'id: secret_scan' in text
    assert "-e '-----BEGIN CERTIFICATE-----'" in text
    assert "-e 'Bearer '" in text
    assert "-e 'Authorization:'" in text
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,'" in text
    assert "-e 'audio/wav'" in text
    assert "-e 'https://live-stt\\.denetim:8243'" in text
    assert "-e '/transcribe'" in text
    assert "forbidden key names" in text
    assert "raw_audio" in text
    assert "raw_command_output" in text
    assert "steps.secret_scan.outcome == 'success'" in text


def test_grep_patterns_keep_option_separator_after_patterns():
    text = workflow_text()
    secret_scan = text.split("- name: Verify artifact excludes private material", 1)[1]
    secret_scan = secret_scan.split("- name: Write workflow summary", 1)[0]

    assert "grep -R -E --" not in secret_scan
    assert "grep -E --" not in secret_scan
    assert "-e '-----BEGIN CERTIFICATE-----'" in secret_scan
    assert "-e '/transcribe' \\\n            -- \\" in secret_scan
    assert "-e '\"(raw_command_output|command_output)\"[[:space:]]*:' \\\n            -- \\" in secret_scan


def test_workflow_uploads_artifact_before_failure_guard():
    text = workflow_text()

    upload_index = text.index("Upload evidence ingest artifact")
    cleanup_index = text.index("Cleanup local evidence directory")
    failure_index = text.index("Fail workflow when evidence is rejected")

    assert "actions/upload-artifact@v7" in text
    assert upload_index < cleanup_index < failure_index
    assert "retention-days: 14" in text
