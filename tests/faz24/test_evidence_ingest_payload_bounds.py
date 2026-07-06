from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


def _faz24_ingest_workflows_with_evidence_input():
    return sorted(
        workflow
        for workflow in WORKFLOW_DIR.glob("faz24-*.yml")
        if "evidence_json_base64:" in workflow.read_text(encoding="utf-8")
    )


def test_all_faz24_evidence_ingest_workflows_bound_dispatch_payload_size():
    workflows = _faz24_ingest_workflows_with_evidence_input()

    assert workflows, "expected Faz 24 evidence-ingest workflow coverage"
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        assert 'if [ "${#EVIDENCE_JSON_BASE64}" -gt 200000 ]; then' in text, workflow
        assert "evidence_json_base64 is too large" in text, workflow
