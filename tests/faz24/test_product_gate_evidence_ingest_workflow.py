from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/faz24-product-gate-evidence-ingest.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_dispatches_three_product_gates():
    text = workflow_text()

    assert "workflow_dispatch:" in text
    assert "gate:" in text
    assert "- gcap" in text
    assert "- gops" in text
    assert "- gcomp" in text
    assert "gcap|gops|gcomp" in text


def test_workflow_routes_each_gate_to_expected_verifier():
    text = workflow_text()

    assert "scripts/faz24/verify_gcap_capture_gate_evidence.py" in text
    assert "scripts/faz24/verify_gops_operability_gate_evidence.py" in text
    assert "scripts/faz24/verify_gcomp_compliance_gate_evidence.py" in text
    assert '--evidence-file "${EVIDENCE_JSON}"' in text
    assert '--output-file "${SUMMARY_JSON}"' in text


def test_workflow_preserves_no_mutation_and_secret_scan_boundaries():
    text = workflow_text()

    assert "contents: read" in text
    assert "It does not run a" in text
    assert "No pilot, runtime/Kubernetes/Vault/firewall/legal mutation" in text
    assert "-e 'Bearer '" in text
    assert "-e 'Authorization:'" in text
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,'" in text
    assert "PRIVATE KEY" in text
    assert "forbidden key names" in text
    assert "raw_audio" in text
    assert "raw_transcript" in text
    assert "raw_prompt" in text
    assert "raw_response_text" in text
    assert 'id: secret_scan' in text
    assert 'steps.secret_scan.outcome == \'success\'' in text


def test_grep_patterns_keep_option_separator_after_patterns():
    text = workflow_text()

    secret_scan = text.split("- name: Verify artifact excludes private material", 1)[1]
    secret_scan = secret_scan.split("- name: Write workflow summary", 1)[0]

    assert "grep -R -E --" not in secret_scan
    assert "grep -E --" not in secret_scan
    assert "-e '-----BEGIN CERTIFICATE-----'" in secret_scan
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,' \\\n            -- \\" in secret_scan
    assert "-e '\"(phone|telephone|email)\"[[:space:]]*:' \\\n            -- \\" in secret_scan


def test_workflow_uploads_artifact_before_failure_guard():
    text = workflow_text()

    upload_index = text.index("Upload evidence ingest artifact")
    cleanup_index = text.index("Cleanup local evidence directory")
    failure_index = text.index("Fail workflow when evidence is rejected")

    assert "actions/upload-artifact@v7" in text
    assert upload_index < cleanup_index < failure_index
    assert "retention-days: 14" in text
