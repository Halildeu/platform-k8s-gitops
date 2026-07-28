from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/faz24/reconcile_redis_streams_test_runtime.sh"
DIRECT_WORKFLOW = ROOT / ".github/workflows/faz24-direct-stt-e2e-collect.yml"
TOKEN_WORKFLOW = ROOT / ".github/workflows/faz24-platform-desktop-token-evidence.yml"


def test_script_is_valid_bash_and_test_only():
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'CONTEXT:-k3d-test' in text
    assert 'NAMESPACE:-platform-test' in text
    assert 'COMPOSE_DIR:-/opt/platform/redis-streams' in text
    assert 'EXPECTED_IP:-172.19.0.250' in text
    assert "productionMutated: false" in text
    assert "secretValuesIncluded: false" in text
    assert "podAuthPing: true" in text
    assert "redis-runtime-env-missing-secret-owner-action-required" in text
    assert "cat ${env_file}" not in text
    assert "set -x" not in text
    assert "platform-prod" not in text


def test_runtime_reconcile_precedes_real_audio_smoke_in_both_workflows():
    direct = DIRECT_WORKFLOW.read_text(encoding="utf-8")
    token = TOKEN_WORKFLOW.read_text(encoding="utf-8")

    for workflow, chain_step in (
        (direct, "Run token and external recorder lifecycle"),
        (token, "Run platform-desktop token evidence chain"),
    ):
        assert "faz24-redis-streams-runtime.json" in workflow
        assert "reconcile_redis_streams_test_runtime.sh" in workflow
        assert workflow.index("Reconcile test Redis Streams runtime") < workflow.index(chain_step)
