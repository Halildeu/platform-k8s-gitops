from pathlib import Path
import json
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
    assert "KC_ADMIN_MODE" in text
    assert "ADMIN_TOKEN_FILE" in text
    assert "kc_admin_rest" in text
    assert "RESOURCE_CLIENT_ID" in text
    assert "CAPABILITY_ROLE" in text
    assert "audio_record" in text
    assert "role-mappings/clients/${RESOURCE_CLIENT_UUID}" in text
    assert "required-client-role-missing" in text
    assert "CLIENT_ROLE_ASSIGNED" in text
    assert "preflight_existing_user_reconcile" in text
    assert "existing-user-reconcile-requires-explicit-confirmation" in text
    assert "existing-user-company-alias-out-of-scope" in text
    assert "existing-user-tenant-alias-out-of-scope" in text
    assert "controlled-mapper-prune-requires-explicit-confirmation" in text
    assert "verify_no_assigned_scope_controlled_claims" in text
    assert "assigned-scope-controlled-claim-collision" in text
    assert "for scope_kind in default optional" in text
    assert "${scope_kind}-client-scopes" in text
    assert "keycloak-controlled-claim-mapper-contract-failed" in text
    assert "del(.credentials)" in text
    assert "chmod 0600 \"${RECONCILE_BACKUP_JSON}\"" in text
    assert "credentialsMutated: false" in text
    assert "mapper-${name}-update.json" in text
    assert "kcadm-mapper-${name}-update.json" in text
    assert "jq --arg id" in text
    assert ".id = $id" in text
    assert "keycloak-admin-login-failed" in text
    assert "sudoReadable" in text
    assert "--arg candidateLabel" in text
    assert '{"label": $candidateLabel, "exists": $exists' in text
    assert "{label: $label" not in text
    assert "--arg label" not in text
    assert 'write_kc_source_diagnostic "host-file"' in text
    assert 'write_kc_source_diagnostic "host-file-sudo"' in text
    assert 'write_kc_source_diagnostic "actions-secret" "KC_TEST_ADMIN_PASSWORD"' in text
    assert "sudo -n cat" in text
    assert 'rm -f "${ADMIN_PASS_FILE}" "${ADMIN_TOKEN_FILE}" "${USER_PASS_FILE}" "${TOKEN_FILE}"' in text
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


def test_controlled_claim_mapper_jq_contract_compiles_and_rejects_duplicates():
    text = SCRIPT.read_text(encoding="utf-8")
    function = text.split("verify_controlled_claim_mapper_contract() {", 1)[1]
    function = function.split("write_audience_mapper() {", 1)[0]
    program = function.split("jq -e '\n", 1)[1].split(
        "\n  ' \"${mapper_file}\"", 1
    )[0]

    claims = ["org_id", "tenant_id", "tenantId", "companyId", "userId"]
    mappers = [
        {
            "name": claim,
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "config": {
                "claim.name": claim,
                "user.attribute": claim,
                "access.token.claim": "true",
            },
        }
        for claim in claims
    ]

    valid = subprocess.run(
        ["jq", "-e", program],
        input=json.dumps(mappers),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr

    duplicate = subprocess.run(
        ["jq", "-e", program],
        input=json.dumps([*mappers, mappers[0]]),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert duplicate.returncode == 1, duplicate.stderr


def test_workflow_runs_on_staging_sw_and_scans_artifacts():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: [self-hosted, staging-sw, testai-deploy]" in workflow
    assert "run-platform-desktop-token-evidence-chain.sh" in workflow
    assert "KC_ADMIN_PASSWORD: ${{ secrets.KC_TEST_ADMIN_PASSWORD }}" in workflow
    assert 'CONFIRM_CONTROLLED_MAPPER_PRUNE: "YES"' in workflow
    assert "faz24-platform-desktop-token-evidence-${{ github.run_id }}" in workflow
    assert "Verify artifact excludes private material" in workflow
    assert "directGrantsRestored" in workflow
    assert "tempUserDeleted" in workflow
    assert "tokenFileRemoved" in workflow
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,'" in workflow
    assert "SECRET_SCAN_OUTCOME" in workflow
    assert "No production, direct-STT, desktop mic/loopback" in workflow
    assert 'sed -n \'1,80p\' "${EVIDENCE_DIR}/runner.stdout"' not in workflow
    assert 'sed -n \'1,80p\' "${EVIDENCE_DIR}/runner.stderr"' not in workflow
    assert "cancel-in-progress: false" in workflow


def test_workflow_secret_scan_blocks_raw_audio_data_urls_before_upload():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    secret_scan = workflow.split("- name: Verify artifact excludes private material", 1)[1]
    secret_scan = secret_scan.split("- name: Write workflow summary", 1)[0]

    assert "grep -R -a -E --" not in secret_scan
    assert "grep -E --" not in secret_scan
    assert "-e '-----BEGIN CERTIFICATE-----'" in secret_scan
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,' \\\n            -- \\" in secret_scan
    assert "steps.secret_scan.outcome == 'success'" in workflow
