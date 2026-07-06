import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
STEP_RE = re.compile(r"(?ms)^      - name: .+?(?=^      - name: |\Z)")


def _faz24_workflows_with_artifact_secret_scan():
    workflows = []
    for workflow in WORKFLOW_DIR.glob("faz24-*.yml"):
        text = workflow.read_text(encoding="utf-8")
        if (
            "Verify artifact excludes private material" in text
            and "actions/upload-artifact@v7" in text
        ):
            workflows.append(workflow)
    return sorted(workflows)


def _steps(text):
    return STEP_RE.findall(text)


def test_faz24_artifact_uploads_require_successful_secret_scan():
    workflows = _faz24_workflows_with_artifact_secret_scan()

    assert workflows, "expected Faz 24 artifact secret-scan workflow coverage"
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        assert "steps.verify_artifact.outcome != 'failure'" not in text, workflow

        steps = _steps(text)
        scan_steps = [
            step
            for step in steps
            if "- name: Verify artifact excludes private material" in step
        ]
        assert scan_steps, workflow
        scan_step = scan_steps[0]
        scan_id_match = re.search(
            r"(?m)^        id: (secret_scan|verify_artifact)$",
            scan_step,
        )
        assert scan_id_match, workflow
        scan_id = scan_id_match.group(1)

        upload_steps = [
            step for step in steps if "uses: actions/upload-artifact@v7" in step
        ]
        assert upload_steps, workflow
        for upload_step in upload_steps:
            if "if: always()" in upload_step:
                assert (
                    f"steps.{scan_id}.outcome == 'success'" in upload_step
                ), workflow
