from pathlib import Path
import json
import shlex
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/run-platform-desktop-token-evidence-chain.sh"
REST_LIB = REPO_ROOT / "scripts/faz24/lib/keycloak_admin_rest.sh"
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
    rest_text = REST_LIB.read_text(encoding="utf-8")

    assert "KC_REALM must be platform-test" in text
    assert "GITHUB_RUN_ATTEMPT" in text
    assert "directAccessGrantsEnabled=${DIRECT_GRANTS_ORIGINAL}" in text
    assert "client-direct-grants-restore-verify.json" in text
    assert "'.directAccessGrantsEnabled == $expected'" in text
    assert '"users/${TEMP_USER_ID}"' in text
    assert "TOKEN_FILE_REMOVED" in text
    assert "grant-attempts-array.json" in text
    assert "keycloak_admin_password_candidates" in text
    assert "hostFileCandidates" in text
    assert "KC_ADMIN_MODE" in text
    assert 'KC_ADMIN_TRANSPORT="${KC_ADMIN_TRANSPORT:-rest}"' in text
    assert "ADMIN_TOKEN_FILE" in text
    assert "ADMIN_CURL_CONFIG" in text
    assert "kc_admin_rest" in text
    assert "recover_stale_session_expiry_state" in text
    assert "TEMP_USERNAME_PREFIX" in text
    assert "faz24_temp_user_ids" in rest_text
    assert "max=100" in text
    assert "faz24_stale_user_count_allowed" in rest_text
    assert "faz24_stale_cleanup_proven" in rest_text
    assert "stale-test-state-run-scoped-user-limit-exceeded" in text
    assert "stale-test-state-user-count-invalid" in text
    assert "stale-test-state-user-verify-count-invalid" in text
    assert "stale-test-state-users-remain-after-cleanup" in text
    assert "stale-test-state-direct-grants-invalid" in text
    assert "'.directAccessGrantsEnabled == false'" in text
    assert "faz24_cleanup_state_proven" in rest_text
    assert 'FAILURE_REASON="live-state-cleanup-not-proven"' in text
    assert "RESOURCE_CLIENT_ID" in text
    assert "CAPABILITY_ROLE" in text
    assert "audio_record" in text
    assert "role-mappings/clients/${RESOURCE_CLIENT_UUID}" in text
    assert 'add-roles -r "${KC_REALM}" --uid "${TEMP_USER_ID}"' in text
    assert '--uusername "${TEMP_USERNAME}"' not in text
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
    assert 'write_user_attribute_mapper "tenant_id" "org_id"' in text
    assert 'canonicalUserAttribute: "org_id"' in text
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
    assert 'rm -f "${ADMIN_PASS_FILE}" "${ADMIN_TOKEN_FILE}" "${ADMIN_CURL_CONFIG}"' in text
    assert '--config "${ADMIN_CURL_CONFIG}"' in rest_text
    assert "session-expiry smoke target allowlist mismatch" in text
    assert 'if [[ "${RUN_SESSION_EXPIRY_SMOKE}" == "1" ]]; then' in text
    assert "verify_controlled_claim_mapper_contract\n  verify_no_assigned_scope_controlled_claims\nelse\n  converge_platform_desktop_mappers" in text
    assert "keycloak-kcadm-password-argv-disabled" in text
    assert 'unset KC_ADMIN_PASSWORD' in text
    assert '--password "$(' not in text
    assert '--new-password "$(' not in text
    assert "rawTokenLogged: false" in text
    assert "rawPasswordLogged: false" in text
    assert "rawAdminCredentialLogged: false" in text
    assert "run_external_recorder_smoke.py" in text
    assert "verify_external_recorder_smoke_evidence.py" in text
    assert "RUN_MEETING_AI_RESULT_ACCEPTANCE" in text
    assert "run_meeting_ai_user_result_acceptance.py" in text
    assert "MEETING_AI_RESULT_ACCEPTANCE_JSON" in text
    assert "meetingAiUserResultAcceptance" in text
    assert '--token-file "${TOKEN_FILE}"' in text
    assert "RUN_SESSION_EXPIRY_SMOKE" in text
    assert "SESSION_EXPIRY_AUDIO_BASE_URL" in text
    assert "SESSION_EXPIRY_METRICS_BASE_URL" in text
    assert "SESSION_EXPIRY_EXPECTED_IMAGE" in text
    assert "SESSION_EXPIRY_POD_UID" in text
    assert "session-expiry-smoke-loopback-url-invalid" in text
    assert "run_audio_gateway_session_expiry_smoke.py" in text
    assert "audioGatewaySessionExpirySmoke" in text
    assert "access_token" not in {
        line.strip()
        for line in text.splitlines()
        if line.lstrip().startswith("echo ")
    }
    assert "path:" not in text
    assert "set -x" not in text


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_admin_rest_401_refreshes_once_and_retries_cleanup_once(tmp_path, method):
    calls = tmp_path / "calls"
    refreshes = tmp_path / "refreshes"
    calls.write_text("0", encoding="utf-8")
    refreshes.write_text("0", encoding="utf-8")
    script = f"""
set -euo pipefail
source {REST_LIB!s}
CALLS={calls!s}
REFRESHES={refreshes!s}
KC_ADMIN_MODE=rest
kc_admin_rest_once() {{
  value=$(cat "$CALLS")
  value=$((value + 1))
  printf '%s' "$value" > "$CALLS"
  if [ "$value" -eq 1 ]; then printf '401'; else printf '204'; fi
}}
refresh_keycloak_admin_rest_session() {{
  value=$(cat "$REFRESHES")
  printf '%s' "$((value + 1))" > "$REFRESHES"
  return 0
}}
code=$(kc_admin_rest {method} /cleanup/test /tmp/out /tmp/body)
[ "$code" = 204 ]
[ "$(cat "$CALLS")" = 2 ]
[ "$(cat "$REFRESHES")" = 1 ]
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_admin_rest_failed_retry_keeps_cleanup_evidence_fail_closed(tmp_path, method):
    calls = tmp_path / "calls"
    refreshes = tmp_path / "refreshes"
    calls.write_text("0", encoding="utf-8")
    refreshes.write_text("0", encoding="utf-8")
    script = f"""
set -euo pipefail
source {REST_LIB!s}
CALLS={calls!s}
REFRESHES={refreshes!s}
KC_ADMIN_MODE=rest
kc_admin_rest_once() {{
  value=$(cat "$CALLS")
  printf '%s' "$((value + 1))" > "$CALLS"
  printf '401'
}}
refresh_keycloak_admin_rest_session() {{
  value=$(cat "$REFRESHES")
  printf '%s' "$((value + 1))" > "$REFRESHES"
  return 0
}}
code=$(kc_admin_rest {method} /cleanup/test /tmp/out /tmp/body)
[ "$code" = 401 ]
cleanup_proven=false
[ "$code" = 204 ] && cleanup_proven=true
[ "$cleanup_proven" = false ]
[ "$(cat "$CALLS")" = 2 ]
[ "$(cat "$REFRESHES")" = 1 ]
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    ("direct_toggled", "direct_restored", "user_created", "user_deleted", "expected"),
    [
        ("false", "false", "false", "false", True),
        ("true", "true", "false", "false", True),
        ("false", "false", "true", "true", True),
        ("true", "false", "false", "false", False),
        ("false", "false", "true", "false", False),
        ("true", "true", "true", "false", False),
    ],
)
def test_cleanup_state_is_proven_only_when_each_mutation_is_reverted(
    direct_toggled, direct_restored, user_created, user_deleted, expected
):
    script = f"""
set -euo pipefail
source {REST_LIB!s}
if faz24_cleanup_state_proven {direct_toggled} {direct_restored} {user_created} {user_deleted}; then
  result=true
else
  result=false
fi
[ "$result" = {str(expected).lower()} ]
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({"directAccessGrantsEnabled": False}, True),
        ({"directAccessGrantsEnabled": True}, False),
        ({}, False),
        ({"directAccessGrantsEnabled": None}, False),
    ],
)
def test_stale_direct_grants_requires_observed_exact_false(document, expected):
    proc = subprocess.run(
        ["jq", "-e", ".directAccessGrantsEnabled == false"],
        input=json.dumps(document),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert (proc.returncode == 0) is expected


def test_temp_user_filter_selects_only_exact_recovery_run(tmp_path):
    users = tmp_path / "users.json"
    users.write_text(
        json.dumps(
            [
                {"id": "gha", "username": "faz24-recorder-smoke-codex-29534428064-1"},
                {"id": "local", "username": "faz24-recorder-smoke-codex-20260717T010203Z-2"},
                {"id": "manual", "username": "faz24-recorder-smoke-codex-manual"},
                {"id": "other", "username": "another-user"},
            ]
        ),
        encoding="utf-8",
    )
    pattern = "^faz24-recorder-smoke-codex-29534428064-[0-9]+$"
    script = f"""
set -euo pipefail
source {REST_LIB!s}
ids=$(faz24_temp_user_ids {users!s} '{pattern}')
[ "$ids" = gha ]
[ "$(faz24_temp_user_count {users!s} '{pattern}')" = 1 ]
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_temp_user_filter_returns_zero_for_already_absent_recovery_run(tmp_path):
    users = tmp_path / "users.json"
    users.write_text("[]", encoding="utf-8")
    pattern = "^faz24-recorder-smoke-codex-29534428064-[0-9]+$"
    script = f"""
set -euo pipefail
source {REST_LIB!s}
[ -z "$(faz24_temp_user_ids {users!s} '{pattern}')" ]
[ "$(faz24_temp_user_count {users!s} '{pattern}')" = 0 ]
faz24_stale_user_count_allowed 0
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        ("0", True),
        ("1", True),
        ("20", True),
        ("21", False),
        ("-1", False),
        ("", False),
        ("05", False),
        (" 5", False),
        ("5 ", False),
        ("not-a-count", False),
    ],
)
def test_stale_user_count_allows_only_bounded_numeric_values(count, expected):
    quoted_count = shlex.quote(count)
    script = f"""
set -euo pipefail
source {REST_LIB!s}
if faz24_stale_user_count_allowed {quoted_count}; then
  result=true
else
  result=false
fi
[ "$result" = {str(expected).lower()} ]
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    ("matched", "deleted", "remaining", "expected"),
    [
        ("0", "0", "0", True),
        ("1", "1", "0", True),
        ("1", "0", "0", False),
        ("1", "1", "1", False),
        ("20", "19", "0", False),
    ],
)
def test_stale_cleanup_requires_deleted_match_and_zero_remaining(
    matched, deleted, remaining, expected
):
    script = f"""
set -euo pipefail
source {REST_LIB!s}
if faz24_stale_cleanup_proven {matched} {deleted} {remaining}; then
  result=true
else
  result=false
fi
[ "$result" = {str(expected).lower()} ]
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


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
                "user.attribute": "org_id" if claim == "tenant_id" else claim,
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
    assert "run_session_expiry_smoke:" in workflow
    assert "run_meeting_ai_result_acceptance:" in workflow
    assert "recover_stale_run_id:" in workflow
    assert "expected_audio_gateway_image:" in workflow
    assert "run_audio_gateway_session_expiry_transient_smoke.sh" in workflow
    assert "EXPECTED_AUDIO_GATEWAY_IMAGE" in workflow
    assert "SESSION_EXPIRY_SMOKE_JSON" in workflow
    assert "MEETING_AI_RESULT_ACCEPTANCE_JSON" in workflow
    assert "session-expiry excludes external-recorder and Meeting-AI result acceptance" in workflow
    assert "Meeting-AI result acceptance requires external-recorder smoke" in workflow
    assert "platform-backend-audio-gateway-service@sha256:[0-9a-f]{64}" in workflow
    assert "CONFIRM_CONTROLLED_MAPPER_PRUNE: ${{ inputs.run_session_expiry_smoke == 'true' && 'NO' || 'YES' }}" in workflow
    assert "promote_single_artifact" in workflow
    assert 'session["boundaries"]["sessionRegistryCapacityReused"] is True' in workflow
    assert 'session["boundaries"]["aggregationReservationReleased"] is True' in workflow
    assert 'session["boundaries"]["negativeInvariantStable"] is True' in workflow
    assert 'result["userRead"]["accepted"] is True' in workflow
    assert 'result["metadataOnlyAudit"]["accepted"] is True' in workflow
    assert "faz24-platform-desktop-token-evidence-${{ github.run_id }}-${{ github.run_attempt }}" in workflow
    assert "group: faz24-platform-desktop-keycloak-test-mutation" in workflow
    assert "required ${name} artifact was not produced" in workflow
    assert 'KC_ADMIN_PASSWORD: ${{ secrets.KC_TEST_ADMIN_PASSWORD }}' in workflow
    assert 'secret in candidate.read_bytes()' in workflow
    assert "Verify artifact excludes private material" in workflow
    assert "directGrantsRestored" in workflow
    assert "staleDirectGrantsVerified" in workflow
    assert "staleTempUsersMatched" in workflow
    assert 'type(data["cleanup"]["staleTempUsersMatched"]) is int' in workflow
    assert '0 <= data["cleanup"]["staleTempUsersMatched"] <= 20' in workflow
    assert "staleTempUsersRemaining" in workflow
    assert "adminSessionRefreshAttempted" in workflow
    assert "adminSessionRefreshed" in workflow
    assert "tempUserDeleted" in workflow
    assert "tokenFileRemoved" in workflow
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,'" in workflow
    assert "SECRET_SCAN_OUTCOME" in workflow
    assert "ACCEPTANCE_OUTCOME" in workflow
    assert "- name: Validate evidence acceptance" in workflow
    assert "RUNNER_STDOUT: /tmp/faz24-platform-desktop-token-runner-" in workflow
    assert "RUNNER_STDERR: /tmp/faz24-platform-desktop-token-runner-" in workflow
    assert '"${EVIDENCE_DIR}/runner.stdout"' not in workflow
    assert '"${EVIDENCE_DIR}/runner.stderr"' not in workflow
    assert 'trap \'rm -f -- "${RUNNER_STDOUT}" "${RUNNER_STDERR}"\' EXIT' in workflow
    assert 'failureReason: "evidence-chain-exited-before-diagnostic"' in workflow
    assert "Free-form runner logs are ephemeral and never uploaded" in workflow
    assert "no production or desktop mic/loopback closure claim" in workflow
    assert 'sed -n' not in workflow
    assert "cancel-in-progress: false" in workflow


def test_workflow_secret_scan_blocks_raw_audio_data_urls_before_upload():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    secret_scan = workflow.split("- name: Verify artifact excludes private material", 1)[1]
    secret_scan = secret_scan.split("- name: Validate evidence acceptance", 1)[0]

    assert "grep -R -a -E --" not in secret_scan
    assert "grep -E --" not in secret_scan
    assert secret_scan.count("grep -R -a -q -E") == 2
    assert 'data["tokenIncluded"] is False' in secret_scan
    assert 'data["boundaries"]["rawTokenLogged"] is False' in secret_scan
    assert 'data["boundaries"]["rawPasswordLogged"] is False' in secret_scan
    assert 'data["boundaries"]["rawAdminCredentialLogged"] is False' in secret_scan
    assert 'test -s "${DIAG_JSON}"' in secret_scan
    assert "if diagnostic.is_file()" not in secret_scan
    assert 'sensitive_scan_rc="$?"' in secret_scan
    assert 'key_scan_rc="$?"' in secret_scan
    assert '"${sensitive_scan_rc}" -ne 1' in secret_scan
    assert '"${key_scan_rc}" -ne 1' in secret_scan
    assert "-e '-----BEGIN CERTIFICATE-----'" in secret_scan
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,' \\\n            -- \\" in secret_scan
    assert 'session["status"] == "pass"' not in secret_scan
    assert "steps.secret_scan.outcome == 'success'" in workflow


def test_workflow_uploads_secret_safe_failure_diagnostics_before_final_failure():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    acceptance = workflow.split("- name: Validate evidence acceptance", 1)[1]
    acceptance = acceptance.split("- name: Write workflow summary", 1)[0]
    upload = workflow.split("- name: Upload platform-desktop token evidence artifact", 1)[1]
    upload = upload.split("- name: Cleanup local evidence directory", 1)[0]

    assert "id: acceptance" in acceptance
    assert 'test -s "${DIAG_JSON}"' in acceptance
    assert 'session["status"] == "pass"' in acceptance
    assert "if: always() && steps.secret_scan.outcome == 'success'" in upload
    assert "steps.acceptance.outcome" not in upload
