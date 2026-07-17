from pathlib import Path
import importlib.util
import json
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/faz24/collect_audio_gateway_dispatch_diagnostic.py"


def _load():
    spec = importlib.util.spec_from_file_location("collect_audio_gateway_dispatch_diagnostic", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _smoke(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "name": "start_session",
                        "response": {"sessionId": "SES-test-1"},
                    },
                    {
                        "name": "upload_chunk",
                        "response": {"correlationId": "faz24-corr-1"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def test_script_compiles_and_contains_no_raw_log_persistence():
    result = subprocess.run(
        ["python3", "-m", "py_compile", str(SCRIPT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"rawLogsIncluded": False' in text
    assert '"secretValuesIncluded": False' in text
    assert "write_text(result.stdout" not in text


def test_collect_classifies_exact_request_without_copying_raw_logs(tmp_path):
    collector = _load()
    smoke = tmp_path / "smoke.json"
    output = tmp_path / "diagnostic.json"
    _smoke(smoke)

    raw_line = (
        "Redis dispatch failed; marking Unavailable err=RedisConnectionFailureException "
        "sessionId=SES-test-1 chunkSeq=0 correlationId=faz24-corr-1 streamKey=audio:chunks:p01"
    )

    def runner(argv, timeout):
        assert argv[:6] == ["kubectl", "--context", "k3d-test", "-n", "platform-test", "logs"]
        assert "deployment/audio-gateway" in argv
        assert timeout == 30
        return collector.CommandResult(0, f"unrelated secret-like line\n{raw_line}\n", "")

    evidence = collector.collect(
        smoke,
        output,
        context="k3d-test",
        namespace="platform-test",
        deployment="audio-gateway",
        since="10m",
        command_runner=runner,
    )

    assert evidence["status"] == "classified"
    assert evidence["diagnostic"] == {
        "classification": "redis-dispatch-unavailable",
        "exceptionClass": "RedisConnectionFailureException",
        "matchedCount": 1,
        "logQuery": "success",
    }
    persisted = output.read_text(encoding="utf-8")
    assert raw_line not in persisted
    assert "unrelated secret-like line" not in persisted
    assert evidence["boundaries"]["rawLogsIncluded"] is False


def test_collect_ignores_other_request_and_reports_inconclusive(tmp_path):
    collector = _load()
    smoke = tmp_path / "smoke.json"
    output = tmp_path / "diagnostic.json"
    _smoke(smoke)

    def runner(_argv, _timeout):
        return collector.CommandResult(
            0,
            "ALERT Redis AUTH/ACL failure on dispatch err=RedisSystemException "
            "sessionId=SES-other chunkSeq=0 correlationId=faz24-other streamKey=audio:chunks:p02\n",
            "",
        )

    evidence = collector.collect(
        smoke,
        output,
        context="k3d-test",
        namespace="platform-test",
        deployment="audio-gateway",
        since="10m",
        command_runner=runner,
    )

    assert evidence["status"] == "inconclusive"
    assert evidence["diagnostic"]["classification"] == "no-allowlisted-match"
    assert evidence["diagnostic"]["exceptionClass"] is None


def test_collector_rejects_non_test_scope(tmp_path):
    collector = _load()
    smoke = tmp_path / "smoke.json"
    _smoke(smoke)

    try:
        collector.collect(
            smoke,
            tmp_path / "out.json",
            context="prod",
            namespace="platform-prod",
            deployment="audio-gateway",
            since="10m",
        )
    except ValueError as exc:
        assert "restricted to platform-test" in str(exc)
    else:
        raise AssertionError("non-test scope must be rejected")
