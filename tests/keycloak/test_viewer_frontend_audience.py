import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/keycloak/reconcile-viewer-frontend-audience.sh"
FAKE_CURL = ROOT / "tests/keycloak/fake_viewer_audience_curl.py"


def exact_mapper(mapper_id: str = "managed-id") -> dict:
    return {
        "id": mapper_id,
        "name": "remote-bridge-operator-api-audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.client.audience": "remote-bridge-operator-api",
            "id.token.claim": "false",
            "access.token.claim": "true",
            "introspection.token.claim": "true",
            "userinfo.token.claim": "false",
        },
    }


def run(tmp_path: Path, action: str, mappers: list[dict], **extra_env: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if not (bin_dir / "curl").exists():
        curl = bin_dir / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            f"exec {shlex.quote(sys.executable)} {shlex.quote(str(FAKE_CURL))} \"$@\"\n"
        )
        curl.chmod(0o755)
    docker = bin_dir / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 1\n")
    docker.chmod(0o755)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"mappers": mappers}))
    log = tmp_path / "calls.jsonl"
    out = tmp_path / "out"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_KC_STATE": str(state),
        "FAKE_KC_LOG": str(log),
        "KC_ADMIN_PASSWORD": "test-only-admin-password",
        "OUT_DIR": str(out),
        **extra_env,
    }
    result = subprocess.run(["bash", str(SCRIPT), action], env=env, text=True, capture_output=True)
    summary = json.loads((out / "viewer-frontend-audience-summary.json").read_text()) if out.exists() else None
    return result, json.loads(state.read_text()), summary, log.read_text() if log.exists() else ""


def mapper_mutations(log: str) -> list[dict]:
    return [
        row
        for line in log.splitlines()
        if (row := json.loads(line))["method"] in {"POST", "PUT", "DELETE"}
        and "/protocol-mappers/models" in row["url"]
    ]


def test_apply_is_idempotent_and_rollback_is_exact(tmp_path: Path):
    applied, state, summary, _ = run(tmp_path, "--apply", [])
    assert applied.returncode == 0, applied.stderr
    assert len(state["mappers"]) == 1
    assert summary["result"] == "created-and-verified"
    assert summary["after"]["exact"] is True
    assert summary["secretHygiene"] == {
        "adminPasswordIncluded": False,
        "adminTokenIncluded": False,
        "userTokenIncluded": False,
    }

    second, state, summary, log = run(tmp_path / "second", "--apply", state["mappers"])
    assert second.returncode == 0
    assert len(state["mappers"]) == 1
    assert summary["result"] == "already-converged"
    assert mapper_mutations(log) == []

    rolled_back, state, summary, _ = run(tmp_path / "rollback", "--rollback", state["mappers"])
    assert rolled_back.returncode == 0
    assert state["mappers"] == []
    assert summary["result"] == "removed-and-verified"
    assert summary["after"]["controlledMapperCount"] == 0


def test_check_reports_exact_or_drift(tmp_path: Path):
    passed, _, summary, _ = run(tmp_path / "pass", "--check", [exact_mapper()])
    assert passed.returncode == 0
    assert summary["result"] == "converged"

    drifted, _, summary, _ = run(tmp_path / "drift", "--check", [])
    assert drifted.returncode == 2
    assert summary["result"] == "drift"

    introspection_drift = exact_mapper()
    introspection_drift["config"]["introspection.token.claim"] = "false"
    rejected, _, summary, _ = run(
        tmp_path / "introspection-drift",
        "--check",
        [introspection_drift],
    )
    assert rejected.returncode == 2
    assert summary["result"] == "drift"
    assert summary["after"]["exact"] is False
    assert summary["securityBoundary"]["accessTokenOnly"] is False

    custom_audience_drift = exact_mapper()
    custom_audience_drift["config"]["included.custom.audience"] = "unexpected-api"
    rejected, _, summary, _ = run(
        tmp_path / "custom-audience-drift",
        "--check",
        [custom_audience_drift],
    )
    assert rejected.returncode == 2
    assert summary["after"]["exact"] is False


def test_conflicting_controlled_name_fails_without_mutation(tmp_path: Path):
    conflicting = exact_mapper()
    conflicting["config"]["included.client.audience"] = "another-api"
    result, state, summary, log = run(tmp_path, "--apply", [conflicting])
    assert result.returncode == 1
    assert state["mappers"] == [conflicting]
    assert summary["result"] == "failed:controlled-mapper-name-conflict"
    assert mapper_mutations(log) == []

    rolled_back, state, summary, log = run(
        tmp_path / "rollback-conflict",
        "--rollback",
        [conflicting],
    )
    assert rolled_back.returncode == 1
    assert state["mappers"] == [conflicting]
    assert summary["result"] == "failed:controlled-mapper-name-conflict"
    assert mapper_mutations(log) == []


def test_failed_postcondition_attempts_compensating_rollback(tmp_path: Path):
    result, state, summary, log = run(
        tmp_path,
        "--apply",
        [],
        FAKE_MUTATE_MAPPER_POST="1",
    )
    assert result.returncode == 1
    assert state["mappers"] == []
    assert summary["result"].startswith("failed:postcondition-failed-compensating-rollback-http-")
    assert summary["after"]["controlledMapperCount"] == 0
    mutations = mapper_mutations(log)
    assert [row["method"] for row in mutations] == ["POST", "DELETE"]
    assert mutations[-1]["url"].endswith("/server-assigned-id")


def test_non_test_target_is_rejected_before_admin_access(tmp_path: Path):
    result, _, summary, log = run(tmp_path, "--apply", [], KC_REALM="serban")
    assert result.returncode == 2
    assert summary is None
    assert log == ""


def test_workflow_keeps_test_and_secret_boundaries():
    workflow = (ROOT / ".github/workflows/faz22-6-viewer-frontend-audience.yml").read_text()
    assert "runs-on: [self-hosted, staging-sw, testai-deploy]" in workflow
    assert "platform-test-keycloak-configuration" in workflow
    assert "APPLY_VIEWER_FRONTEND_AUDIENCE" in workflow
    assert "productionMutation == false" in workflow
    assert "KC_TEST_ADMIN_PASSWORD" not in workflow
    assert "environment:" not in workflow
    trigger_block = workflow.split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "\n  push:" not in trigger_block
    assert "\n  pull_request:" not in trigger_block
    assert "\n  schedule:" not in trigger_block
