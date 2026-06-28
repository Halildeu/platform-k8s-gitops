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
    assert "PRIVATE KEY" in text
    assert "raw_audio" in text
    assert "transcript" in text
    assert "full_name" in text
    assert 'id: secret_scan' in text
    assert "steps.secret_scan.outcome == 'success'" in text


def test_workflow_uploads_artifact_before_failure_guard():
    text = workflow_text()

    upload_index = text.index("Upload evidence ingest artifact")
    cleanup_index = text.index("Cleanup local evidence directory")
    failure_index = text.index("Fail workflow when evidence is rejected")

    assert "actions/upload-artifact@v7" in text
    assert upload_index < cleanup_index < failure_index
    assert "retention-days: 14" in text
