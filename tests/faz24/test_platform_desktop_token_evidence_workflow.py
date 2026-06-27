from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/run-platform-desktop-token-evidence-chain.sh"
WORKFLOW = REPO_ROOT / ".github/workflows/faz24-platform-desktop-token-evidence.yml"


def test_runner_script_is_shell_syntax_valid():
    proc = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr


def test_runner_contract_restores_and_redacts():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "KC_REALM must be platform-test" in text
    assert "GITHUB_RUN_ATTEMPT" in text
    assert "directAccessGrantsEnabled=${DIRECT_GRANTS_ORIGINAL}" in text
    assert '"users/${TEMP_USER_ID}"' in text
    assert "TOKEN_FILE_REMOVED" in text
    assert "grant-attempts-array.json" in text
    assert "keycloak_admin_password_candidates" in text
    assert "hostFileCandidates" in text
    assert "sudoReadable" in text
    assert 'write_kc_source_diagnostic "host-file"' in text
    assert 'write_kc_source_diagnostic "host-file-sudo"' in text
    assert "sudo -n cat" in text
    assert "rawTokenLogged: false" in text
    assert "rawPasswordLogged: false" in text
    assert "rawAdminCredentialLogged: false" in text
    assert "run_external_recorder_smoke.py" in text
    assert "verify_external_recorder_smoke_evidence.py" in text
    assert "access_token" not in {
        line.strip()
        for line in text.splitlines()
        if line.lstrip().startswith("echo ")
    }
    assert "path:" not in text
    assert "set -x" not in text


def test_workflow_runs_on_staging_sw_and_scans_artifacts():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: [self-hosted, staging-sw, testai-deploy]" in workflow
    assert "run-platform-desktop-token-evidence-chain.sh" in workflow
    assert "faz24-platform-desktop-token-evidence-${{ github.run_id }}" in workflow
    assert "Verify artifact excludes private material" in workflow
    assert "directGrantsRestored" in workflow
    assert "tempUserDeleted" in workflow
    assert "tokenFileRemoved" in workflow
    assert "SECRET_SCAN_OUTCOME" in workflow
    assert "No production, direct-STT, desktop mic/loopback" in workflow
    assert 'sed -n \'1,80p\' "${EVIDENCE_DIR}/runner.stdout"' not in workflow
    assert 'sed -n \'1,80p\' "${EVIDENCE_DIR}/runner.stderr"' not in workflow
    assert "cancel-in-progress: false" in workflow
