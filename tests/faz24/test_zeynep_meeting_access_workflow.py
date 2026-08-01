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
PROVISION_SCRIPT = (
    REPO_ROOT / "scripts/faz24/provision-meeting-intelligence-access.sh"
)
MAIL_ANCHOR_RESOLVER = REPO_ROOT / "scripts/faz24/resolve-mail-anchor.jq"
PRIMARY_SUBJECT = "FAZ 24"
CORROBORATING_SUBJECT = "Platform Ai- Meeting Intelligence"
NEW_PASSWORD = "a" * 64
WRITER_USER_ID = "cbc9a869-1833-4d9c-beea-a9fa52fa851e"
WRITER_PROFILE_EMAIL = "d35-admin-persona@acik.com"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _resolve_mail_anchor(tmp_path: Path, primary: dict, corroborating: dict):
    primary_path = tmp_path / "primary.json"
    corroborating_path = tmp_path / "corroborating.json"
    primary_path.write_text(json.dumps(primary), encoding="utf-8")
    corroborating_path.write_text(json.dumps(corroborating), encoding="utf-8")

    return subprocess.run(
        [
            "jq",
            "-nr",
            "--arg",
            "primary_subject",
            PRIMARY_SUBJECT,
            "--arg",
            "corroborating_subject",
            CORROBORATING_SUBJECT,
            "--slurpfile",
            "primary",
            str(primary_path),
            "--slurpfile",
            "corroborating",
            str(corroborating_path),
            "-f",
            str(MAIL_ANCHOR_RESOLVER),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _mail_response(subject: str, *senders: str, next_link: bool = False) -> dict:
    response = {
        "value": [
            {
                "subject": subject,
                "from": {"emailAddress": {"address": sender}},
            }
            for sender in senders
        ]
    }
    if next_link:
        response["@odata.nextLink"] = "https://graph.example.test/next"
    return response


def test_mail_anchor_requires_one_shared_internal_sender(tmp_path):
    proc = _resolve_mail_anchor(
        tmp_path,
        _mail_response(
            PRIMARY_SUBJECT,
            "PERSON@ACIK.COM",
            "other-primary@acik.com",
            "external@example.com",
        ),
        _mail_response(
            CORROBORATING_SUBJECT,
            "person@acik.com",
            "other-corroborating@acik.com",
            "partner@example.com",
        ),
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "person@acik.com"


def test_mail_anchor_ignores_graph_case_insensitive_subject_superset(tmp_path):
    primary = _mail_response(PRIMARY_SUBJECT, "PERSON@ACIK.COM")
    primary["value"].extend(
        [
            {
                "subject": "faz 24",
                "from": {"emailAddress": {"address": "other@acik.com"}},
            },
            {
                "subject": "Faz 24",
                "from": {"emailAddress": {}},
            },
        ]
    )

    proc = _resolve_mail_anchor(
        tmp_path,
        primary,
        _mail_response(CORROBORATING_SUBJECT, "person@acik.com"),
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "person@acik.com"


@pytest.mark.parametrize(
    ("primary", "corroborating"),
    [
        (
            _mail_response(PRIMARY_SUBJECT),
            _mail_response(CORROBORATING_SUBJECT, "person@acik.com"),
        ),
        (
            _mail_response(
                PRIMARY_SUBJECT, "person@acik.com", "other@acik.com"
            ),
            _mail_response(
                CORROBORATING_SUBJECT, "person@acik.com", "other@acik.com"
            ),
        ),
        (
            _mail_response(PRIMARY_SUBJECT, "person@acik.com"),
            _mail_response(CORROBORATING_SUBJECT, "other@acik.com"),
        ),
        (
            _mail_response(PRIMARY_SUBJECT, "person@example.com"),
            _mail_response(CORROBORATING_SUBJECT, "person@example.com"),
        ),
        (
            _mail_response(PRIMARY_SUBJECT, "person@acik.com", next_link=True),
            _mail_response(CORROBORATING_SUBJECT, "person@acik.com"),
        ),
        (
            _mail_response(PRIMARY_SUBJECT, "person@acik.com"),
            _mail_response(
                CORROBORATING_SUBJECT, "person@acik.com", next_link=True
            ),
        ),
        (
            {
                "value": [
                    {
                        "subject": PRIMARY_SUBJECT,
                        "from": {"emailAddress": {}},
                    },
                    {
                        "subject": PRIMARY_SUBJECT,
                        "from": {
                            "emailAddress": {"address": "person@acik.com"}
                        },
                    },
                ]
            },
            _mail_response(CORROBORATING_SUBJECT, "person@acik.com"),
        ),
        (
            _mail_response(PRIMARY_SUBJECT, "person@acik.com", "not-an-email"),
            _mail_response(CORROBORATING_SUBJECT, "person@acik.com"),
        ),
        (
            {
                "value": [
                    {
                        "subject": PRIMARY_SUBJECT,
                        "from": {"emailAddress": {"address": 24}},
                    }
                ]
            },
            _mail_response(CORROBORATING_SUBJECT, "person@acik.com"),
        ),
        (
            _mail_response("faz 24", "person@acik.com"),
            _mail_response(CORROBORATING_SUBJECT, "person@acik.com"),
        ),
    ],
)
def test_mail_anchor_fails_closed_for_ambiguous_or_incomplete_evidence(
    tmp_path, primary, corroborating
):
    proc = _resolve_mail_anchor(tmp_path, primary, corroborating)

    assert proc.returncode != 0
    assert proc.stdout == ""


def test_provisioner_queries_two_independent_subject_anchors():
    text = PROVISION_SCRIPT.read_text(encoding="utf-8")

    assert 'MAIL_PRIMARY_SUBJECT="FAZ 24"' in text
    assert (
        'MAIL_CORROBORATING_SUBJECT="Platform Ai- Meeting Intelligence"' in text
    )
    assert text.count('read_mail_anchor "${MAIL_') == 2
    assert (
        'https://graph.microsoft.com/v1.0/users/${MAILBOX}/mailFolders/inbox/messages'
        in text
    )
    assert 'https://graph.microsoft.com/v1.0/users/${MAILBOX}/messages' not in text
    assert '--data-urlencode "\\$filter=subject eq' in text
    assert '--arg primary_subject "${MAIL_PRIMARY_SUBJECT}"' in text
    assert '--arg corroborating_subject "${MAIL_CORROBORATING_SUBJECT}"' in text
    assert "exact-zeynep-mail-anchor-inconsistent" in text
    assert "from.emailAddress.name" not in text


def test_provisioner_can_fail_closed_on_single_active_desktop_identity():
    text = PROVISION_SCRIPT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '--target-active-desktop-session' in text
    assert 'TARGET_MODE="mail-anchor"' in text
    assert 'TARGET_MODE="active-desktop-session"' in text
    assert 'desktop-session-user-not-exactly-one' in text
    assert 'desktop-session-user-not-internal' in text
    assert 'desktop-session-identity-drift' in text
    assert 'desktop-session-user-id-drift' in text
    assert 'desktop-session-company-id-missing' in text
    assert 'selector: $targetMode' in text
    assert 'active-desktop-session' in workflow
    assert 'args+=(--target-active-desktop-session)' in workflow


def _run_ambiguous_reset_scenario(
    tmp_path: Path,
    scenario: str,
    *,
    initial_email: str = WRITER_PROFILE_EMAIL,
    initial_first_name: str = "D35",
    initial_last_name: str = "Persona",
    email_owner_scenario: str = "available",
    writer_user_id: str = WRITER_USER_ID,
    writer_local_user_id: str = "12",
    vault_scenario: str = "ready",
    required_actions: tuple[str, ...] = (),
    profile_put_scenario: str = "success",
    admin_password_via_stdin: bool = False,
    pre_identity_credential_only: bool = False,
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_jq = shutil.which("jq")
    assert real_jq is not None

    _write_executable(
        bin_dir / "jq",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${{VAULT_INIT_FILE:-}}" && "$*" == *"${{VAULT_INIT_FILE}}"* ]]; then
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
  if [[ "$*" == *'platform-kc-test'* ]]; then
    printf '%s' '[{"HostIp":"127.0.0.1","HostPort":"8082"}]'
    exit 0
  fi
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
email_query=false
email_query_file=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) output="$2"; shift 2 ;;
    -X) method="$2"; shift 2 ;;
    --data-urlencode)
      if [[ "$2" == password@* ]]; then
        password_file="${2#password@}"
      elif [[ "$2" == email@* ]]; then
        email_query=true
        email_query_file="${2#email@}"
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
if [[ "${url}" == *'/.well-known/openid-configuration' ]]; then
  printf '%s' '{"issuer":"https://testai.acik.com/realms/platform-test","token_endpoint":"https://testai.acik.com/realms/platform-test/protocol/openid-connect/token"}'
  exit 0
fi
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
  jq -e '
    has("attributes") == false and
    has("requiredActions") == false and
    (keys | length) > 0
  ' "${data_binary_file}" >/dev/null || exit 93
  apply_profile() {
    if jq -e 'has("email")' "${data_binary_file}" >/dev/null; then
      jq -r '.email' "${data_binary_file}" > "${MOCK_KEYCLOAK_EMAIL_STATE}"
    fi
    if jq -e 'has("firstName")' "${data_binary_file}" >/dev/null; then
      jq -r '.firstName' "${data_binary_file}" > "${MOCK_KEYCLOAK_FIRST_NAME_STATE}"
    fi
    if jq -e 'has("lastName")' "${data_binary_file}" >/dev/null; then
      jq -r '.lastName' "${data_binary_file}" > "${MOCK_KEYCLOAK_LAST_NAME_STATE}"
    fi
    if [[ "${MOCK_PROFILE_PUT_SCENARIO}" == 'concurrent-required-action' ]]; then
      printf '%s' '["CONFIGURE_TOTP"]' > "${MOCK_LIVE_REQUIRED_ACTIONS_STATE}"
    elif [[ "${MOCK_PROFILE_PUT_SCENARIO}" == 'success-drop-attributes' ]]; then
      printf '%s' '{}' > "${MOCK_ATTRIBUTES_STATE}"
    fi
    printf '%s\\n' 'keycloak-profile-repair' >> "${MOCK_EVENT_LOG}"
  }
  case "${MOCK_PROFILE_PUT_SCENARIO}" in
    success|success-drop-attributes|concurrent-required-action|success-readback-http-failure|success-readback-transport-failure)
      apply_profile
      printf '%s' '204'
      ;;
    http-4xx)
      printf '%s' '409'
      ;;
    http-5xx-applied)
      apply_profile
      printf '%s' '503'
      ;;
    http-5xx-not-applied)
      printf '%s' '503'
      ;;
    transport-applied)
      apply_profile
      printf '%s' '000'
      exit 7
      ;;
    transport-not-applied)
      printf '%s' '000'
      exit 7
      ;;
    *) exit 94 ;;
  esac
elif [[ "${url}" == *"/admin/realms/platform-test/users/${MOCK_EXPECTED_WRITER_USER_ID}" && "${method}" == 'GET' ]]; then
  if [[ -s "${MOCK_EVENT_LOG}" ]]; then
    case "${MOCK_PROFILE_PUT_SCENARIO}" in
      success-readback-http-failure)
        printf '%s' '503'
        exit 0
        ;;
      success-readback-transport-failure)
        printf '%s' '000'
        exit 7
        ;;
    esac
  fi
  email="$(cat "${MOCK_KEYCLOAK_EMAIL_STATE}")"
  first_name="$(cat "${MOCK_KEYCLOAK_FIRST_NAME_STATE}")"
  last_name="$(cat "${MOCK_KEYCLOAK_LAST_NAME_STATE}")"
  required_actions="$(cat "${MOCK_LIVE_REQUIRED_ACTIONS_STATE}")"
  attributes="$(cat "${MOCK_ATTRIBUTES_STATE}")"
  jq -n --arg id "${MOCK_EXPECTED_WRITER_USER_ID}" --arg email "${email}" \
    --arg firstName "${first_name}" --arg lastName "${last_name}" \
    --argjson attributes "${attributes}" --argjson requiredActions "${required_actions}" \
    '{
      id: $id,
      enabled: true,
      username: "d35-admin-persona",
      email: $email,
      emailVerified: false,
      firstName: $firstName,
      lastName: $lastName,
      attributes: $attributes,
      requiredActions: $requiredActions
    }' > "${output}"
  printf '%s' '200'
elif [[ "${url}" == *'/admin/realms/platform-test/users' ]]; then
  if [[ "${email_query}" == 'true' ]]; then
    case "${MOCK_EMAIL_OWNER_SCENARIO}" in
      available)
        if [[ "$(cat "${MOCK_KEYCLOAK_EMAIL_STATE}")" == "$(cat "${email_query_file}")" ]]; then
          jq -n --arg id "${MOCK_EXPECTED_WRITER_USER_ID}" '[{id:$id}]' > "${output}"
        else
          printf '%s' '[]' > "${output}"
        fi
        ;;
      collision-after-put)
        if [[ -s "${MOCK_EVENT_LOG}" ]]; then
          jq -n --arg id "${MOCK_EXPECTED_WRITER_USER_ID}" \
            '[{id:$id},{id:"different-user-id"}]' > "${output}"
        else
          printf '%s' '[]' > "${output}"
        fi
        ;;
      collision)
        printf '%s' '[{"id":"different-user-id"}]' > "${output}"
        ;;
      http-failure)
        printf '%s' '503'
        exit 0
        ;;
      transport-failure)
        printf '%s' '000'
        exit 7
        ;;
      *) exit 95 ;;
    esac
    printf '%s' '200'
    exit 0
  fi
  email="$(cat "${MOCK_KEYCLOAK_EMAIL_STATE}")"
  first_name="$(cat "${MOCK_KEYCLOAK_FIRST_NAME_STATE}")"
  last_name="$(cat "${MOCK_KEYCLOAK_LAST_NAME_STATE}")"
  user_id="$(cat "${MOCK_KEYCLOAK_USER_ID_STATE}")"
  required_actions="$(cat "${MOCK_REQUIRED_ACTIONS_STATE}")"
  attributes="$(cat "${MOCK_ATTRIBUTES_STATE}")"
  jq -n --arg id "${user_id}" --arg email "${email}" \\
    --arg firstName "${first_name}" --arg lastName "${last_name}" \\
    --argjson attributes "${attributes}" --argjson requiredActions "${required_actions}" \\
    '[{
      id: $id,
      enabled: true,
      username: "d35-admin-persona",
      email: $email,
      emailVerified: false,
      firstName: $firstName,
      lastName: $lastName,
      attributes: $attributes,
      requiredActions: $requiredActions
    }]' > "${output}"
  printf '%s' '200'
elif [[ "${url}" == *'/realms/platform-test/protocol/openid-connect/token' ]]; then
  password="$(cat "${password_file}")"
  keycloak_state="$(cat "${MOCK_KEYCLOAK_STATE}")"
  if [[ "$(cat "${MOCK_LIVE_REQUIRED_ACTIONS_STATE}")" != '[]' ||
        ! -s "${MOCK_KEYCLOAK_EMAIL_STATE}" ||
        ! -s "${MOCK_KEYCLOAK_FIRST_NAME_STATE}" ||
        ! -s "${MOCK_KEYCLOAK_LAST_NAME_STATE}" ]]; then
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
    keycloak_first_name_state = tmp_path / "keycloak-first-name-state"
    keycloak_first_name_state.write_text(initial_first_name, encoding="utf-8")
    keycloak_last_name_state = tmp_path / "keycloak-last-name-state"
    keycloak_last_name_state.write_text(initial_last_name, encoding="utf-8")
    keycloak_user_id_state = tmp_path / "keycloak-user-id-state"
    keycloak_user_id_state.write_text(writer_user_id, encoding="utf-8")
    attributes_state = tmp_path / "attributes-state.json"
    attributes_state.write_text(
        json.dumps(
            {
                "sentinel": ["keep"],
                "userId": [writer_local_user_id],
                "subscriberId": [writer_local_user_id],
            }
        ),
        encoding="utf-8",
    )
    required_actions_state = tmp_path / "required-actions-state.json"
    required_actions_state.write_text(
        json.dumps(list(required_actions)), encoding="utf-8"
    )
    live_required_actions_state = tmp_path / "live-required-actions-state.json"
    live_required_actions_state.write_text(
        json.dumps(list(required_actions)),
        encoding="utf-8",
    )
    event_log = tmp_path / "events.log"
    event_log.write_text("", encoding="utf-8")
    vault_init_file = tmp_path / "vault-init-test.json"
    vault_init_file.write_text(
        json.dumps({"root_token": "mock-root-token"}), encoding="utf-8"
    )
    result_path = tmp_path / "result.json"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "MOCK_SCENARIO": scenario,
            "MOCK_NEW_PASSWORD": NEW_PASSWORD,
            "MOCK_VAULT_STATE": str(vault_state),
            "MOCK_VAULT_VERSION": str(vault_version),
            "MOCK_KEYCLOAK_STATE": str(keycloak_state),
            "MOCK_KEYCLOAK_EMAIL_STATE": str(keycloak_email_state),
            "MOCK_KEYCLOAK_FIRST_NAME_STATE": str(keycloak_first_name_state),
            "MOCK_KEYCLOAK_LAST_NAME_STATE": str(keycloak_last_name_state),
            "MOCK_KEYCLOAK_USER_ID_STATE": str(keycloak_user_id_state),
            "MOCK_ATTRIBUTES_STATE": str(attributes_state),
            "MOCK_EMAIL_OWNER_SCENARIO": email_owner_scenario,
            "MOCK_PROFILE_EMAIL": WRITER_PROFILE_EMAIL,
            "MOCK_EXPECTED_WRITER_USER_ID": WRITER_USER_ID,
            "MOCK_REQUIRED_ACTIONS_STATE": str(required_actions_state),
            "MOCK_LIVE_REQUIRED_ACTIONS_STATE": str(live_required_actions_state),
            "MOCK_PROFILE_PUT_SCENARIO": profile_put_scenario,
            "MOCK_VAULT_SCENARIO": vault_scenario,
            "MOCK_EVENT_LOG": str(event_log),
            "VAULT_INIT_FILE": str(vault_init_file),
        }
    )
    command = ["bash", str(REPAIR_SCRIPT), "--out", str(result_path)]
    stdin_value = None
    if admin_password_via_stdin:
        env.pop("KC_ADMIN_PASSWORD", None)
        command.append("--keycloak-admin-password-stdin")
        stdin_value = "mock-admin-password\n"
    else:
        env["KC_ADMIN_PASSWORD"] = "mock-admin-password"
    if pre_identity_credential_only:
        command.append("--pre-identity-credential-only")
    proc = subprocess.run(
        command,
        input=stdin_value,
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


def test_keycloak_admin_password_stdin_contract_reaches_ready_state(tmp_path):
    proc, result, _, _, _ = _run_ambiguous_reset_scenario(
        tmp_path,
        "new-success",
        writer_local_user_id="1204",
        admin_password_via_stdin=True,
        pre_identity_credential_only=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert result["status"] in {"credential-ready", "credential-repaired"}
    assert result["permissionWriter"]["loginReady"] is True
    assert result["permissionWriter"]["rolesReadReady"] is False
    assert "mock-admin-password" not in proc.stdout
    assert "mock-admin-password" not in proc.stderr


def test_pre_identity_credential_mode_never_mutates_the_writer_profile(tmp_path):
    proc, result, _, events, _ = _run_ambiguous_reset_scenario(
        tmp_path,
        "new-success",
        writer_local_user_id="1204",
        initial_email="drifted@example.invalid",
        admin_password_via_stdin=True,
        pre_identity_credential_only=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert result["status"] in {"credential-ready", "credential-repaired"}
    assert result["permissionWriter"]["loginReady"] is True
    assert result["permissionWriter"]["profileRepaired"] is False
    assert "keycloak-profile-repair" not in events
    assert (tmp_path / "keycloak-email-state").read_text(
        encoding="utf-8"
    ).strip() == "drifted@example.invalid"


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
    assert "profileReady" in text
    assert "profileRepaired" in text
    assert "existingAttributesPreserved" in text
    assert "requiredActionsPreserved" in text
    assert "permissionServiceWriterReady" not in text
    assert "permission-service roles read access" in text
    assert f'readonly WRITER_USER_ID="{WRITER_USER_ID}"' in text
    assert "permission-writer-id-mismatch" in text
    assert 'identityBinding: "username+immutable-user-id"' in text
    assert f'readonly WRITER_PROFILE_EMAIL="{WRITER_PROFILE_EMAIL}"' in text
    assert 'has("attributes") == false' in text
    assert 'has("requiredActions") == false' in text
    assert "{requiredActions: []}" not in text


def test_missing_service_profile_is_repaired_without_replacing_owned_state(tmp_path):
    proc, result, vault_state, events, _ = _run_ambiguous_reset_scenario(
        tmp_path,
        "new-success",
        initial_email="",
        initial_first_name="",
        initial_last_name="",
    )

    assert proc.returncode == 0, proc.stderr
    assert result["permissionWriter"]["requiredActionsReady"] is True
    assert result["permissionWriter"]["profileReady"] is True
    assert result["permissionWriter"]["profileRepaired"] is True
    assert result["permissionWriter"]["profileEmailCollisionFree"] is True
    assert result["permissionWriter"]["existingAttributesPreserved"] is True
    assert result["permissionWriter"]["requiredActionsPreserved"] is True
    assert result["boundaries"]["permissionWriterEmailMutation"] is True
    assert result["boundaries"]["permissionWriterEmailMutationAttempted"] is True
    assert result["boundaries"]["permissionWriterEmailMutationConfirmed"] is True
    assert vault_state["admin_persona_password"] == NEW_PASSWORD
    assert events == [
        "keycloak-profile-repair",
        "vault-put",
        "keycloak-reset-ambiguous",
    ]
    assert (tmp_path / "keycloak-email-state").read_text(
        encoding="utf-8"
    ).strip() == WRITER_PROFILE_EMAIL


@pytest.mark.parametrize(
    "profile_put_scenario", ("http-5xx-applied", "transport-applied")
)
def test_ambiguous_profile_put_applied_is_accepted_only_after_readback(
    tmp_path, profile_put_scenario
):
    proc, result, vault_state, events, _ = _run_ambiguous_reset_scenario(
        tmp_path,
        "new-success",
        initial_email="",
        initial_first_name="",
        initial_last_name="",
        profile_put_scenario=profile_put_scenario,
    )

    assert proc.returncode == 0, proc.stderr
    assert result["permissionWriter"]["requiredActionsReady"] is True
    assert result["permissionWriter"]["profileReady"] is True
    assert result["permissionWriter"]["profileRepaired"] is True
    assert vault_state["admin_persona_password"] == NEW_PASSWORD
    assert events == [
        "keycloak-profile-repair",
        "vault-put",
        "keycloak-reset-ambiguous",
    ]


@pytest.mark.parametrize(
    "profile_put_scenario", ("http-5xx-not-applied", "transport-not-applied")
)
def test_ambiguous_profile_put_not_applied_blocks_before_vault_write(
    tmp_path, profile_put_scenario
):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            initial_email="",
            initial_first_name="",
            initial_last_name="",
            profile_put_scenario=profile_put_scenario,
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == "permission-writer-profile-readback-mismatch"
    assert result["permissionWriter"]["requiredActionsReady"] is True
    assert result["permissionWriter"]["profileReady"] is False
    assert vault_state == original_vault
    assert events == []


def test_profile_put_4xx_is_rejected_before_readback_or_vault_write(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            initial_email="",
            initial_first_name="",
            initial_last_name="",
            profile_put_scenario="http-4xx",
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == "permission-writer-profile-repair-rejected"
    assert result["boundaries"]["permissionWriterEmailMutation"] is True
    assert result["boundaries"]["permissionWriterEmailMutationAttempted"] is True
    assert result["boundaries"]["permissionWriterEmailMutationConfirmed"] is False
    assert vault_state == original_vault
    assert events == []


def test_profile_email_collision_blocks_before_profile_or_vault_mutation(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            initial_email="",
            initial_first_name="",
            initial_last_name="",
            email_owner_scenario="collision",
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == "permission-writer-profile-email-conflict"
    assert vault_state == original_vault
    assert events == []


@pytest.mark.parametrize(
    "profile_put_scenario",
    ("success-readback-http-failure", "success-readback-transport-failure"),
)
def test_applied_profile_put_with_failed_readback_reports_attempted_not_confirmed(
    tmp_path, profile_put_scenario
):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            initial_email="",
            initial_first_name="",
            initial_last_name="",
            profile_put_scenario=profile_put_scenario,
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == "permission-writer-profile-readback-failed"
    assert result["boundaries"]["permissionWriterEmailMutation"] is True
    assert result["boundaries"]["permissionWriterEmailMutationAttempted"] is True
    assert result["boundaries"]["permissionWriterEmailMutationConfirmed"] is False
    assert result["permissionWriter"]["profileReady"] is False
    assert vault_state == original_vault
    assert events == ["keycloak-profile-repair"]


def test_post_write_email_collision_blocks_before_vault_write(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            initial_email="",
            initial_first_name="",
            initial_last_name="",
            email_owner_scenario="collision-after-put",
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == (
        "permission-writer-profile-email-ownership-unverified"
    )
    assert result["boundaries"]["permissionWriterEmailMutationAttempted"] is True
    assert result["boundaries"]["permissionWriterEmailMutationConfirmed"] is True
    assert result["permissionWriter"]["profileEmailCollisionFree"] is False
    assert result["permissionWriter"]["profileReady"] is False
    assert vault_state == original_vault
    assert events == ["keycloak-profile-repair"]


def test_concurrent_required_action_is_preserved_and_detected(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            initial_email="",
            initial_first_name="",
            initial_last_name="",
            profile_put_scenario="concurrent-required-action",
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == (
        "permission-writer-profile-required-actions-changed"
    )
    assert vault_state == original_vault
    assert events == ["keycloak-profile-repair"]
    assert json.loads(
        (tmp_path / "live-required-actions-state.json").read_text(encoding="utf-8")
    ) == ["CONFIGURE_TOTP"]


def test_profile_attribute_loss_is_detected_before_vault_write(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            initial_email="",
            initial_first_name="",
            initial_last_name="",
            profile_put_scenario="success-drop-attributes",
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == "permission-writer-profile-attributes-changed"
    assert vault_state == original_vault
    assert events == ["keycloak-profile-repair"]


@pytest.mark.parametrize("required_action", ("CONFIGURE_TOTP", "UPDATE_PROFILE"))
def test_operator_owned_required_action_blocks_before_any_mutation(
    tmp_path, required_action
):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            required_actions=(required_action,),
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == (
        "permission-writer-required-actions-unsupported"
    )
    assert result["permissionWriter"]["requiredActionsReady"] is False
    assert result["permissionWriter"]["profileReady"] is False
    assert vault_state == original_vault
    assert events == []


def test_vault_preflight_blocks_before_profile_repair(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            vault_scenario="missing-container",
            initial_email="",
            initial_first_name="",
            initial_last_name="",
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == "vault-container-missing"
    assert result["permissionWriter"]["profileRepaired"] is False
    assert vault_state == original_vault
    assert events == []


def test_writer_email_is_reconciled_to_the_canonical_local_identity(tmp_path):
    proc, result, vault_state, events, _ = _run_ambiguous_reset_scenario(
        tmp_path,
        "new-success",
        initial_email="drifted@example.invalid",
    )

    assert proc.returncode == 0, proc.stderr
    assert result["permissionWriter"]["exactIdentityMatch"] is True
    assert result["permissionWriter"]["identityBinding"] == (
        "username+immutable-user-id"
    )
    assert result["boundaries"]["permissionWriterEmailMutation"] is True
    assert result["boundaries"]["permissionWriterEmailMutationAttempted"] is True
    assert result["boundaries"]["permissionWriterEmailMutationConfirmed"] is True
    assert result["permissionWriter"]["profileRepaired"] is True
    assert result["permissionWriter"]["profileEmailCollisionFree"] is True
    assert vault_state["admin_persona_password"] == NEW_PASSWORD
    assert events == [
        "keycloak-profile-repair",
        "vault-put",
        "keycloak-reset-ambiguous",
    ]
    assert (tmp_path / "keycloak-email-state").read_text(
        encoding="utf-8"
    ).strip() == WRITER_PROFILE_EMAIL


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


def test_writer_local_user_id_mismatch_blocks_before_any_mutation(tmp_path):
    proc, result, vault_state, events, original_vault = (
        _run_ambiguous_reset_scenario(
            tmp_path,
            "new-success",
            initial_email="drifted@example.invalid",
            writer_local_user_id="9999",
        )
    )

    assert proc.returncode == 1
    assert result["failureReason"] == (
        "permission-writer-profile-precondition-local-user-mismatch"
    )
    assert result["boundaries"]["permissionWriterEmailMutationAttempted"] is False
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
    assert "profileReady" in text
    assert "profileRepaired" in text
    assert "existingAttributesPreserved" in text
    assert "requiredActionsPreserved" in text
    assert 'faz24.permissionWriterCredentialRepair.v3' in redaction
    assert ".boundaries.permissionWriterEmailMutation | type" in redaction
    assert ".boundaries.permissionWriterEmailMutationAttempted | type" in redaction
    assert ".boundaries.permissionWriterEmailMutationConfirmed | type" in redaction
    assert 'identityBinding == "username+immutable-user-id"' in redaction
