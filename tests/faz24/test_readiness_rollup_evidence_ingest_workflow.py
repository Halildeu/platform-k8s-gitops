from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/faz24-readiness-rollup-evidence-ingest.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_dispatches_rollup_ingest():
    text = workflow_text()

    assert "workflow_dispatch:" in text
    assert "evidence_json_base64" in text
    assert "Faz 24 Readiness Rollup Evidence Ingest" in text
    assert "faz24-readiness-rollup-${{ github.run_id }}" in text


def test_workflow_bounds_dispatch_payload_size():
    text = workflow_text()

    assert 'if [ "${#EVIDENCE_JSON_BASE64}" -gt 200000 ]; then' in text
    assert "evidence_json_base64 is too large" in text


def test_workflow_routes_to_rollup_verifier():
    text = workflow_text()

    assert "scripts/faz24/verify_faz24_readiness_rollup.py" in text
    assert '--evidence-file "${EVIDENCE_JSON}"' in text
    assert '--output-file "${SUMMARY_JSON}"' in text


def test_workflow_preserves_no_mutation_and_secret_scan_boundaries():
    text = workflow_text()

    assert "contents: read" in text
    assert "does not collect evidence, mutate runtime" in text
    assert "no evidence collection, runtime/Kubernetes/Vault/firewall/legal mutation" in text
    assert "-e 'Bearer '" in text
    assert "-e 'Authorization:'" in text
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,'" in text
    assert "PRIVATE KEY" in text
    assert "raw_audio" in text
    assert "transcript" in text
    assert "full_name" in text
    assert 'id: secret_scan' in text
    assert "steps.secret_scan.outcome == 'success'" in text


def test_grep_patterns_keep_option_separator_after_patterns():
    text = workflow_text()

    secret_scan = text.split("- name: Verify artifact excludes private material", 1)[1]
    secret_scan = secret_scan.split("- name: Write workflow summary", 1)[0]

    assert "grep -R -I -q -E --" not in secret_scan
    assert "grep -E --" not in secret_scan
    assert "-e '-----BEGIN CERTIFICATE-----'" in secret_scan
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,' \\\n            -e '\"(access_token" in secret_scan
    assert "full_name)\"[[:space:]]*:' \\\n            -- \"${EVIDENCE_DIR}\"" in secret_scan


def test_workflow_uploads_artifact_before_failure_guard():
    text = workflow_text()

    upload_index = text.index("Upload evidence ingest artifact")
    cleanup_index = text.index("Cleanup local evidence directory")
    failure_index = text.index("Fail workflow when evidence is rejected")

    assert "actions/upload-artifact@v7" in text
    assert upload_index < cleanup_index < failure_index
    assert "retention-days: 14" in text
