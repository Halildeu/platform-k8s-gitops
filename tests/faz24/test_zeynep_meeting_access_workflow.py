from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
REPAIR_SCRIPT = (
    REPO_ROOT / "scripts/faz24/repair-d35-permission-writer-credential.sh"
)
WORKFLOW = REPO_ROOT / ".github/workflows/faz24-zeynep-meeting-access.yml"
NEW_PASSWORD = "a" * 64
WRITER_USER_ID = "cbc9a869-1833-4d9c-beea-a9fa52fa851e"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run_ambiguous_reset_scenario(
    tmp_path: Path,
    scenario: str,
    *,
    initial_email: str = "d35-admin@example.com",
    email_scenario: str = "unchanged",
    writer_user_id: str = WRITER_USER_ID,
    vault_scenario: str = "ready",
    required_actions: tuple[str, ...] = (),
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_jq = shutil.which("jq")
    assert real_jq is not None

    _write_executable(
        bin_dir / "jq",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *'/home/halil/bootstrap-drill/vault-init-test.json'* ]]; then
  printf '%s' 'mock-root-token'
  exit 0
fi
exec {real_jq} "$@"
""",
    )
    _write_executable(
        bin_dir / "openssl",
        f"""#!/usr/bin/env bash
printf '%s\\n' '{NEW_PASSWORD}'
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "inspect" ]]; then
  if [[ "${MOCK_VAULT_SCENARIO}" == 'missing-container' ]]; then
    exit 1
  fi
  exit 0
fi
[[ "$1" == "exec" ]]
if [[ "$*" == *'vault kv get'* ]]; then
  IFS= read -r _token
  [[ "${MOCK_VAULT_SCENARIO}" != 'read-failure' ]] || exit 1
  data="$(cat "${MOCK_VAULT_STATE}")"
  version="$(cat "${MOCK_VAULT_VERSION}")"
  jq -n --argjson data "${data}" --argjson version "${version}" \
    '{data: {metadata: {version: $version}, data: $data}}'
  exit 0
fi
if [[ "$*" == *'vault kv put'* ]]; then
  IFS= read -r _token
  cat > "${MOCK_VAULT_STATE}"
  version="$(cat "${MOCK_VAULT_VERSION}")"
  printf '%s' "$((version + 1))" > "${MOCK_VAULT_VERSION}"
  printf '%s\\n' 'vault-put' >> "${MOCK_EVENT_LOG}"
  exit 0
fi
exit 1
""",
    )
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
method=GET
output=''
url=''
password_file=''
data_binary_file=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    -X) method="$2"; shift 2 ;;
    --data-urlencode)
      if [[ "$2" == password@* ]]; then
        password_file="${2#password@}"
      fi
      shift 2
      ;;
    --data-binary)
      data_binary_file="${2#@}"
      shift 2
      ;;
    http://*|https://*) url="$1"; shift ;;
    *) shift ;;
  esac
done
: > "${output}"
if [[ "${url}" == *'/realms/master/'* ]]; then
  printf '%s' '{"access_token":"admin-token"}' > "${output}"
  printf '%s' '200'
elif [[ "${url}" == *'/admin/realms/platform-test/users/'*'/reset-password' ]]; then
  if [[ "${MOCK_SCENARIO}" == 'new-success' ]]; then
    printf '%s' 'new' > "${MOCK_KEYCLOAK_STATE}"
  fi
  printf '%s\\n' 'keycloak-reset-ambiguous' >> "${MOCK_EVENT_LOG}"
  printf '%s' '503'
elif [[ "${url}" == *'/admin/realms/platform-test/users/'* && "${method}" == 'PUT' ]]; then
  expected_url="http://127.0.0.1:8082/admin/realms/platform-test/users/${MOCK_EXPECTED_WRITER_USER_ID}"
  [[ "${url}" == "${expected_url}" ]] || exit 91
  [[ -n "${data_binary_file}" && -f "${data_binary_file}" ]] || exit 92
  jq -e --arg id "${MOCK_EXPECTED_WRITER_USER_ID}" \
    --arg email "${MOCK_EXPECTED_WRITER_EMAIL}" \
    '. == {
      id: $id,
      enabled: true,
      username: "d35-admin-persona",
      email: $email,
      emailVerified: false,
      firstName: "D35",
      lastName: "Persona",
      attributes: {sentinel: ["keep"]},
      requiredActions: []
    }' \
    "${data_binary_file}" >/dev/null || exit 93
  printf '%s\\n' 'keycloak-required-actions-clear' >> "${MOCK_EVENT_LOG}"
  printf '%s' '[]' > "${MOCK_REQUIRED_ACTIONS_STATE}"
  printf '%s' '204'
elif [[ "${url}" == *'/admin/realms/platform-test/users' ]]; then
  if [[ "$(cat "${MOCK_EMAIL_RECONCILIATION_STATE}")" == 'true' ]]; then
    case "${MOCK_EMAIL_SCENARIO}" in
      readback-http-failure)
        printf '%s' '503'
        exit 0
        ;;
      readback-transport-failure)
        printf '%s' '000'
        exit 7
        ;;
      readback-empty)
        printf '%s' '[]' > "${output}"
        printf '%s' '200'
        exit 0
        ;;
      readback-duplicate)
        jq -n --arg id "${MOCK_EXPECTED_WRITER_USER_ID}" \
          '[
            {id: $id, enabled: true, username: "d35-admin-persona", email: "d35-admin@example.com"},
            {id: "duplicate-id", enabled: true, username: "d35-admin-persona", email: "d35-admin@example.com"}
          ]' > "${output}"
        printf '%s' '200'
        exit 0
        ;;
    esac
  fi
  email="$(cat "${MOCK_KEYCLOAK_EMAIL_STATE}")"
  user_id="$(cat "${MOCK_KEYCLOAK_USER_ID_STATE}")"
  required_actions="$(cat "${MOCK_REQUIRED_ACTIONS_STATE}")"
  jq -n --arg id "${user_id}" --arg email "${email}" \\
    --argjson requiredActions "${required_actions}" \\
    '[{
      id: $id,
      enabled: true,
      username: "d35-admin-persona",
      email: $email,
      emailVerified: false,
      firstName: "D35",
      lastName: "Persona",
      attributes: {sentinel: ["keep"]},
      requiredActions: $requiredActions
    }]' > "${output}"
  printf '%s' '200'
elif [[ "${url}" == *'/realms/platform-test/protocol/openid-connect/token' ]]; then
  password="$(cat "${password_file}")"
  keycloak_state="$(cat "${MOCK_KEYCLOAK_STATE}")"
  if [[ "$(cat "${MOCK_REQUIRED_ACTIONS_STATE}")" != '[]' ]]; then
    printf '%s' '{"error":"invalid_grant","error_description":"Account is not fully set up"}' > "${output}"
    printf '%s' '400'
  elif [[ "${keycloak_state}" == 'new' && "${password}" == "${MOCK_NEW_PASSWORD}" ]] || \
     [[ "${keycloak_state}" == 'old' && "${password}" == 'old-password' ]]; then
    printf '%s' '{"access_token":"writer-token"}' > "${output}"
    printf '%s' '200'
  else
    printf '%s' '{"error":"invalid_grant"}' > "${output}"
    printf '%s' '401'
  fi
elif [[ "${url}" == *'/api/v1/roles' ]]; then
  printf '%s' '{"items":[]}' > "${output}"
  printf '%s' '200'
else
  printf '%s' '500'
fi
""",
    )

    original_vault = {
        "admin_persona_username": "stale-persona",
        "admin_persona_password": "old-password",
        "preserved": "value",
    }
    vault_state = tmp_path / "vault-state.json"
    vault_state.write_text(json.dumps(original_vault), encoding="utf-8")
    vault_version = tmp_path / "vault-version"
    vault_version.write_text("1", encoding="utf-8")
    keycloak_state = tmp_path / "keycloak-state"
    keycloak_state.write_text(
        "none" if scenario == "neither" else "old", encoding="utf-8"
    )
    keycloak_email_state = tmp_path / "keycloak-email-state"
    keycloak_email_state.write_text(initial_email, encoding="utf-8")
    keycloak_user_id_state = tmp_path / "keycloak-user-id-state"
    keycloak_user_id_state.write_text(writer_user_id, encoding="utf-8")
    email_reconciliation_state = tmp_path / "email-reconciliation-state"
    email_reconciliation_state.write_text("false", encoding="utf-8")
    required_actions_state = tmp_path / "required-actions-state.json"
    required_actions_state.write_text(
        json.dumps(list(required_actions)), encoding="utf-8"
    )
    event_log = tmp_path / "events.log"
    event_log.write_text("", encoding="utf-8")
    result_path = tmp_path / "result.json"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "KC_ADMIN_PASSWORD": "mock-admin-password",
            "MOCK_SCENARIO": scenario,
            "MOCK_NEW_PASSWORD": NEW_PASSWORD,
            "MOCK_VAULT_STATE": str(vault_state),
            "MOCK_VAULT_VERSION": str(vault_version),
            "MOCK_KEYCLOAK_STATE": str(keycloak_state),
            "MOCK_KEYCLOAK_EMAIL_STATE": str(keycloak_email_state),
            "MOCK_KEYCLOAK_USER_ID_STATE": str(keycloak_user_id_state),
            "MOCK_EMAIL_RECONCILIATION_STATE": str(email_reconciliation_state),
            "MOCK_EMAIL_SCENARIO": email_scenario,
            "MOCK_EXPECTED_WRITER_EMAIL": initial_email,
            "MOCK_EXPECTED_WRITER_USER_ID": WRITER_USER_ID,
            "MOCK_REQUIRED_ACTIONS_STATE": str(required_actions_state),
            "MOCK_VAULT_SCENARIO": vault_scenario,
            "MOCK_EVENT_LOG": str(event_log),
        }
    )
    proc = subprocess.run(
        ["bash", str(REPAIR_SCRIPT), "--out", str(result_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    return (
        proc,
        json.loads(result_path.read_text(encoding="utf-8")),
        json.loads(vault_state.read_text(encoding="utf-8")),
        event_log.read_text(encoding="utf-8").splitlines(),
        original_vault,
    )


def test_repair_script_is_shell_syntax_valid():
    proc = subprocess.run(
        ["bash", "-n", str(REPAIR_SCRIPT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr


def test_repair_script_keeps_vault_and_keycloak_reconcilable():
    text = REPAIR_SCRIPT.read_text(encoding="utf-8")

    assert 'vault kv put -cas="$2" "$1" -' in text
    assert "docker cp" not in text
    assert "VAULT_CONTAINER_NEW_FILE" not in text
    assert "VAULT_CONTAINER_ROLLBACK_FILE" not in text
    assert "vault-persona-cas-write-failed" in text
    assert "vault-persona-readback-mismatch" in text
    assert "permission-writer-password-reset-not-applied" in text
    assert "permission-writer-password-reset-state-unverified" in text
    vault_write_call = (
        'vault_put_data "${ROOT_TOKEN}" "${VAULT_ORIGINAL_VERSION}" '
        '"${VAULT_NEW_DATA}"'
    )
    assert text.index(vault_write_call) < text.index("RESET_BODY=")
    ambiguous_new_probe = text.index("AMBIGUOUS_NEW_TOKEN_JSON=")
    ambiguous_old_probe = text.index("AMBIGUOUS_OLD_TOKEN_JSON=")
    assert ambiguous_new_probe < ambiguous_old_probe
    assert 'request_writer_token "${NEW_PASSWORD_FILE}"' in text[
        ambiguous_new_probe:ambiguous_old_probe
    ]
    assert 'request_writer_token "${EXISTING_PASSWORD_FILE}"' in text[
        ambiguous_old_probe:
    ]


def test_repair_script_exact_readback_and_noop_contract():
    text = REPAIR_SCRIPT.read_text(encoding="utf-8")

    assert ".data.data.admin_persona_password ==" in text
    assert 'STATUS="already-ready"' in text
    assert "rolesReadReady" in text
    assert "requiredActionsReady" in text
    assert "requiredActionsCleared" in text
    assert "permissionServiceWriterReady" not in text
    assert "permission-service roles read access" in text
    assert f'readonly WRITER_USER_ID="{WRITER_USER_ID}"' in text
    assert "permission-writer-id-mismatch" in text
    assert 'identityBinding: "username+immutable-user-id"' in text
    assert "permissionWriterEmailMutation: false" in text
    assert "WRITER_EMAIL" not in text
    assert "email-reconcile" not in text


def test_update_profile_required_action_is_cleared_for_exact_writer(tmp_path):
    proc, result, vault_state, events, _ = _run_ambiguous_reset_scenario(
        tmp_path,
        "new-success",
        initial_email="drifted@example.invalid",
        required_actions=("UPDATE_PROFILE",),
    )

    assert proc.returncode == 0, proc.stderr
    assert result["permissionWriter"]["requiredActionsReady"] is True
    assert result["permissionWriter"]["requiredActionsCleared"] is True
    assert result["boundaries"]["permissionWriterEmailMutation"] is False
    assert vault_state["admin_persona_password"] == NEW_PASSWORD
    assert events == [
        "keycloak-required-actions-clear",
        "vault-put",
        "keycloak-reset-ambiguous",
    ]


def test_unexpected_required_action_blocks_before_any_mutation(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            required_actions=("CONFIGURE_TOTP",),
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == (
        "permission-writer-required-actions-unsupported"
    )
    assert result["permissionWriter"]["requiredActionsReady"] is False
    assert result["permissionWriter"]["requiredActionsCleared"] is False
    assert vault_state == original_vault
    assert events == []


def test_vault_preflight_blocks_before_required_action_clear(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            vault_scenario="missing-container",
            required_actions=("UPDATE_PROFILE",),
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == "vault-container-missing"
    assert result["permissionWriter"]["requiredActionsCleared"] is False
    assert vault_state == original_vault
    assert events == []


def test_writer_email_is_preserved_while_credential_is_repaired(tmp_path):
    proc, result, vault_state, events, _ = _run_ambiguous_reset_scenario(
        tmp_path,
        "new-success",
        initial_email="drifted@example.invalid",
        email_scenario="rejected",
    )

    assert proc.returncode == 0, proc.stderr
    assert result["permissionWriter"]["exactIdentityMatch"] is True
    assert result["permissionWriter"]["identityBinding"] == (
        "username+immutable-user-id"
    )
    assert result["boundaries"]["permissionWriterEmailMutation"] is False
    assert vault_state["admin_persona_password"] == NEW_PASSWORD
    assert events == ["vault-put", "keycloak-reset-ambiguous"]


def test_writer_uid_mismatch_blocks_before_any_mutation(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            writer_user_id="unexpected-writer-id",
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == "permission-writer-id-mismatch"
    assert result["permissionWriter"]["exactIdentityMatch"] is False
    assert vault_state == original_vault
    assert events == []


@pytest.mark.parametrize(
    ("vault_scenario", "expected_reason"),
    [
        ("missing-container", "vault-container-missing"),
        ("read-failure", "vault-persona-preflight-read-failed"),
    ],
)
def test_vault_preflight_failure_blocks_before_credential_mutation(
    tmp_path, vault_scenario, expected_reason
):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            initial_email="drifted@example.invalid",
            email_scenario="success",
            vault_scenario=vault_scenario,
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == expected_reason
    assert result["permissionWriter"]["exactIdentityMatch"] is True
    assert result["boundaries"]["permissionWriterEmailMutation"] is False
    assert vault_state == original_vault
    assert (tmp_path / "keycloak-email-state").read_text(encoding="utf-8") == (
        "drifted@example.invalid"
    )
    assert events == []


def test_ambiguous_reset_continues_when_new_password_is_live(tmp_path):
    proc, result, vault_state, events, _ = _run_ambiguous_reset_scenario(
        tmp_path, "new-success"
    )

    assert proc.returncode == 0, proc.stderr
    assert result["status"] == "repaired"
    assert result["permissionWriter"]["keycloakCredentialReset"] is True
    assert result["permissionWriter"]["vaultRollbackAttempted"] is False
    assert vault_state["admin_persona_password"] == NEW_PASSWORD
    assert events == ["vault-put", "keycloak-reset-ambiguous"]


def test_ambiguous_reset_rolls_vault_back_when_only_old_password_is_live(tmp_path):
    proc, result, vault_state, events, original_vault = _run_ambiguous_reset_scenario(
        tmp_path, "old-success"
    )

    assert proc.returncode == 1
    assert result["failureReason"] == (
        "permission-writer-password-reset-not-applied-vault-rolled-back"
    )
    assert result["permissionWriter"]["vaultRollbackAttempted"] is True
    assert result["permissionWriter"]["vaultRollbackSucceeded"] is True
    assert vault_state == original_vault
    assert events == ["vault-put", "keycloak-reset-ambiguous", "vault-put"]


def test_ambiguous_reset_preserves_new_vault_value_when_state_is_unverified(tmp_path):
    proc, result, vault_state, events, _ = _run_ambiguous_reset_scenario(
        tmp_path, "neither"
    )

    assert proc.returncode == 1
    assert result["failureReason"] == "permission-writer-password-reset-state-unverified"
    assert result["permissionWriter"]["vaultRollbackAttempted"] is False
    assert vault_state["admin_persona_password"] == NEW_PASSWORD
    assert events == ["vault-put", "keycloak-reset-ambiguous"]


def test_workflow_blocks_unredacted_summary_and_artifact():
    text = WORKFLOW.read_text(encoding="utf-8")

    redaction = text.split("- name: Verify redacted result contract", 1)[1]
    redaction = redaction.split("- name: Publish redacted summary", 1)[0]
    assert "id: redaction" in redaction
    assert "grep -aEq" in redaction
    assert "grep -aE \\" not in redaction
    assert text.count("steps.redaction.outcome == 'success'") == 2
    assert "vaultRollbackAttempted" in text
    assert "vaultRollbackSucceeded" in text
    assert "rolesReadReady" in text
    assert "requiredActionsReady" in text
    assert "requiredActionsCleared" in text
    assert 'faz24.permissionWriterCredentialRepair.v2' in redaction
    assert ".boundaries.permissionWriterEmailMutation == false" in redaction
    assert 'identityBinding == "username+immutable-user-id"' in redaction
