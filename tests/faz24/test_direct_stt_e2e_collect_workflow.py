from pathlib import Path
import argparse
import importlib.util
import json
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/faz24-direct-stt-e2e-collect.yml"
COLLECTOR = REPO_ROOT / "scripts/faz24/collect_direct_stt_e2e_evidence.py"
RUNNER = REPO_ROOT / "scripts/faz24/run-platform-desktop-token-evidence-chain.sh"


def _load_collector():
    spec = importlib.util.spec_from_file_location("collect_direct_stt_e2e_evidence", COLLECTOR)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_collector_python_syntax_valid():
    proc = subprocess.run(
        ["python3", "-m", "py_compile", str(COLLECTOR)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr


def test_runner_accepts_privacy_safe_chunk_file_without_logging_token_material():
    text = RUNNER.read_text(encoding="utf-8")

    assert "SMOKE_CHUNK_FILE" in text
    assert "SMOKE_AUDIO_FORMAT" in text
    assert "SMOKE_SAMPLE_RATE_HZ" in text
    assert "smoke_args+=(--chunk-file" in text
    assert "set -x" not in text
    assert "TOKEN_FILE_REMOVED" in text


def _resp_bulk(value):
    return f"${len(value)}\r\n{value}\r\n"


def _resp_array(values):
    return f"*{len(values)}\r\n" + "".join(values)


def _resp_stream_record(record_id, fields):
    field_values = []
    for key, value in fields:
        field_values.append(_resp_bulk(key))
        field_values.append(_resp_bulk(value))
    return _resp_array([_resp_bulk(record_id), _resp_array(field_values)])


def _resp_xrevrange(records):
    return "+OK\r\n" + _resp_array(records) + "+OK\r\n"


def test_redis_records_falls_back_to_kube_exec_without_docker():
    collector = _load_collector()
    calls = []

    def fake_runner(argv, _timeout):
        calls.append(argv)
        if argv[:2] == ["docker", "exec"]:
            return collector.CommandResult(127, "", "docker: command not found")
        if argv[:6] == ["kubectl", "--context", "k3d-test", "-n", "platform-test", "exec"]:
            return collector.CommandResult(
                0,
                _resp_xrevrange(
                    [
                        _resp_stream_record(
                            "1782471276845-0",
                            [
                                ("eventType", "DIRECT_STT_TRANSCRIPT_RESULT"),
                                ("sessionId", "SES-test"),
                                ("chunkSeq", "0"),
                            ],
                        )
                    ]
                ),
                "",
            )
        raise AssertionError(f"unexpected command: {argv}")

    records, error = collector.redis_records(
        fake_runner,
        container="platform-redis-streams-test",
        context="k3d-test",
        namespace="platform-test",
        service="redis-streams",
        secret="audio-gateway-secrets",
        secret_key="SPRING_DATA_REDIS_PASSWORD",
        image="redis:7.4-alpine",
        exec_pod="audio-gateway-abc",
        exec_container="audio-gateway",
        stream="transcript:direct-stt-results",
        count=1000,
    )

    assert error is None
    assert records == [
        (
            "1782471276845-0",
            {
                "eventType": "DIRECT_STT_TRANSCRIPT_RESULT",
                "sessionId": "SES-test",
                "chunkSeq": "0",
            },
        )
    ]
    exec_calls = [argv for argv in calls if argv[:6] == ["kubectl", "--context", "k3d-test", "-n", "platform-test", "exec"]]
    assert len(exec_calls) == 1
    assert exec_calls[0][6:9] == ["audio-gateway-abc", "-c", "audio-gateway"]
    assert "SPRING_DATA_REDIS_PASSWORD" in exec_calls[0][-4]
    assert "docker: command not found" not in json.dumps(records)


def test_redis_records_accepts_text_mode_lf_normalized_resp():
    collector = _load_collector()
    payload = _resp_xrevrange(
        [
            _resp_stream_record(
                "1782471276845-0",
                [
                    ("eventType", "DIRECT_STT_TRANSCRIPT_RESULT"),
                    ("sessionId", "SES-test"),
                    ("chunkSeq", "0"),
                ],
            )
        ]
    ).replace("\r\n", "\n")

    records, error = collector.redis_records_from_resp_result(
        collector.CommandResult(0, payload, ""),
        stream="transcript:direct-stt-results",
    )

    assert error is None
    assert records == [
        (
            "1782471276845-0",
            {
                "eventType": "DIRECT_STT_TRANSCRIPT_RESULT",
                "sessionId": "SES-test",
                "chunkSeq": "0",
            },
        )
    ]


def test_redis_stream_records_uses_kube_exec_fallback_without_pod_creation():
    collector = _load_collector()
    calls = []

    def fake_runner(argv, _timeout):
        calls.append(argv)
        if argv[:2] == ["docker", "exec"]:
            return collector.CommandResult(127, "", "docker: command not found")
        if argv[:6] == ["kubectl", "--context", "k3d-test", "-n", "platform-test", "exec"]:
            stream = argv[-2]
            record = (
                _resp_stream_record("1-0", [("sessionId", "SES-test"), ("chunkSeq", "0")])
                if stream == "transcript:direct-stt-results"
                else _resp_stream_record("2-0", [("eventType", "CHUNK_FORWARDED_TO_COMPUTE_PLANE")])
            )
            return collector.CommandResult(
                0,
                _resp_xrevrange([record]),
                "",
            )
        raise AssertionError(f"unexpected command: {argv}")

    records, errors = collector.redis_stream_records(
        fake_runner,
        container="platform-redis-streams-test",
        streams=["transcript:direct-stt-results", "audit:events"],
        count=1000,
        context="k3d-test",
        namespace="platform-test",
        service="redis-streams",
        secret="audio-gateway-secrets",
        secret_key="SPRING_DATA_REDIS_PASSWORD",
        image="redis:7.4-alpine",
        exec_pod="audio-gateway-abc",
        exec_container="audio-gateway",
    )

    assert errors == []
    assert sorted(records) == ["audit:events", "transcript:direct-stt-results"]
    assert not [argv for argv in calls if "apply" in argv or "delete" in argv]
    assert len([argv for argv in calls if argv[:6] == ["kubectl", "--context", "k3d-test", "-n", "platform-test", "exec"]]) == 2


def test_redis_stream_records_keeps_kube_exec_partial_successes():
    collector = _load_collector()

    def fake_runner(argv, _timeout):
        if argv[:2] == ["docker", "exec"]:
            return collector.CommandResult(127, "", "docker: command not found")
        if argv[:6] == ["kubectl", "--context", "k3d-test", "-n", "platform-test", "exec"]:
            stream = argv[-2]
            if stream == "audit:events":
                return collector.CommandResult(124, "", "timeout")
            return collector.CommandResult(
                0,
                _resp_xrevrange([_resp_stream_record("1-0", [("sessionId", "SES-test")])]),
                "",
            )
        raise AssertionError(f"unexpected command: {argv}")

    records, errors = collector.redis_stream_records(
        fake_runner,
        container="platform-redis-streams-test",
        streams=["transcript:direct-stt-results", "audit:events"],
        count=1000,
        context="k3d-test",
        namespace="platform-test",
        exec_pod="audio-gateway-abc",
        exec_container="audio-gateway",
    )

    assert sorted(records) == ["transcript:direct-stt-results"]
    assert records["transcript:direct-stt-results"][0][0] == "1-0"
    assert errors
    assert "audit:events:command-exit-124" in errors[0]


def test_wait_for_direct_stt_result_polls_until_matching_result():
    collector = _load_collector()
    now = [0.0]
    fetch_count = [0]

    def fetch_records():
        fetch_count[0] += 1
        if fetch_count[0] == 1:
            return {
                collector.EXPECTED_RESULT_STREAM: [],
                collector.EXPECTED_AUDIT_STREAM: [],
            }, []
        fields = {
            "sessionId": "SES-test",
            "chunkSeq": "0",
            "correlationId": "faz24-test",
        }
        return {
            collector.EXPECTED_RESULT_STREAM: [
                ("1-0", {**fields, "eventType": collector.EXPECTED_RESULT_EVENT})
            ]
        }, []

    records, errors = collector.wait_for_direct_stt_result(
        fetch_records,
        session_id="SES-test",
        chunk_seq=0,
        correlation_id="faz24-test",
        timeout_seconds=60,
        poll_interval_seconds=2,
        monotonic=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )

    assert errors == []
    assert fetch_count[0] == 2
    assert now[0] == 2
    assert records[collector.EXPECTED_RESULT_STREAM][0][0] == "1-0"


def test_durable_audit_record_via_postgres_returns_metadata_only_projection():
    collector = _load_collector()
    calls = []

    def fake_runner(argv, _timeout):
        calls.append(argv)
        return collector.CommandResult(
            0,
            "\t".join(
                [
                    "1782471276846-0",
                    collector.EXPECTED_AUDIT_EVENT,
                    "SES-test",
                    "0",
                    "faz24-test",
                    "true",
                    "true",
                    "true",
                    "SHA-256",
                    "1",
                ]
            )
            + "\n",
            "",
        )

    record, error = collector.durable_audit_record_via_postgres(
        fake_runner,
        container="platform-pg-test",
        user="platform",
        database="audit_event",
        session_id="SES-test",
        chunk_seq=0,
        correlation_id="faz24-test",
    )

    assert error is None
    assert record == {
        "recordId": "1782471276846-0",
        "eventType": collector.EXPECTED_AUDIT_EVENT,
        "sessionId": "SES-test",
        "chunkSeq": "0",
        "correlationId": "faz24-test",
        "eventTimestampPresent": "t",
        "entryHashPresent": "t",
        "prevHashPresent": "t",
        "entryHashAlgorithm": "SHA-256",
        "entryHashVersion": "1",
    }
    assert calls[0][:4] == ["docker", "exec", "platform-pg-test", "psql"]
    assert "entry_hash" in calls[0][-1]
    assert "prev_hash" in calls[0][-1]


def test_wait_for_durable_audit_record_polls_until_hash_chain_is_ready():
    collector = _load_collector()
    now = [0.0]
    fetch_count = [0]

    def fetch_record():
        fetch_count[0] += 1
        if fetch_count[0] == 1:
            return None, None
        if fetch_count[0] == 2:
            return {
                "recordId": "2-0",
                "eventTimestampPresent": "f",
                "entryHashPresent": "f",
                "prevHashPresent": "f",
                "entryHashAlgorithm": "SHA-256",
                "entryHashVersion": "1",
            }, None
        return {
            "recordId": "2-0",
            "eventTimestampPresent": "t",
            "entryHashPresent": "t",
            "prevHashPresent": "t",
            "entryHashAlgorithm": "SHA-256",
            "entryHashVersion": "1",
        }, None

    record, error = collector.wait_for_durable_audit_record(
        fetch_record,
        timeout_seconds=60,
        poll_interval_seconds=2,
        monotonic=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )

    assert error is None
    assert record["recordId"] == "2-0"
    assert record["entryHashPresent"] == "t"
    assert fetch_count[0] == 3
    assert now[0] == 4


def test_direct_stt_e2e_collect_workflow_boundary_and_secret_scan():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: [self-hosted, aiserver, testai-deploy]" in workflow
    assert "run-platform-desktop-token-evidence-chain.sh" in workflow
    assert "collect_direct_stt_e2e_evidence.py" in workflow
    assert "verify_direct_stt_e2e_evidence.py" in workflow
    assert "--audit-db-container platform-pg-test" in workflow
    assert "--audit-db-name audit_event" in workflow
    assert "successfully consumed Redis audit entries are ACK+DEL" in workflow
    assert "KC_ADMIN_PASSWORD: ${{ secrets.KC_TEST_ADMIN_PASSWORD }}" in workflow
    assert 'CONFIRM_CONTROLLED_MAPPER_PRUNE: "YES"' in workflow
    assert "RUN_EXTERNAL_SMOKE: \"1\"" in workflow
    assert "Prepare privacy-safe smoke chunk fixture" in workflow
    assert "CHUNK_FILE_INPUT: ${{ inputs.chunk_file }}" in workflow
    assert 'chunk_file="${RUNNER_TEMP}/faz24-synthetic-smoke-${GITHUB_RUN_ID}.pcm"' in workflow
    assert 'test "${AUDIO_FORMAT_INPUT}" = "PCM16"' in workflow
    assert 'default: "16000"' in workflow
    assert "contains no human speech" in workflow
    assert "chunk_fixture_source=${fixture_source}" in workflow
    assert "CHUNK_FIXTURE_SOURCE: ${{ steps.prepare_chunk.outputs.chunk_fixture_source }}" in workflow
    assert "SMOKE_CHUNK_FILE: ${{ steps.prepare_chunk.outputs.chunk_file }}" in workflow
    assert "SMOKE_STT_PROVIDER: ${{ inputs.stt_provider }}" in workflow
    assert 'STT_PROVIDER_INPUT: ${{ inputs.stt_provider }}' in workflow
    assert 'internal|speechmatics) ;;' in workflow
    assert (
        "speechmatics smoke requires a readable privacy-safe speech fixture" in workflow
    )
    assert "faz24-direct-stt-e2e-collect-${{ github.run_id }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "group: faz24-platform-desktop-keycloak-test-mutation" in workflow
    assert "-e 'data:audio/[A-Za-z0-9.+-]+;base64,'" in workflow
    assert '"(raw_audio|audio_bytes|audio_base64|transcript_text|textDraft)"' in workflow
    assert "metadata-only Gate 2 evidence collection" in workflow
    assert "does not claim production readiness" in workflow
    assert "runner.stderr.sha256=" in workflow
    assert "collector.stderr.sha256=" in workflow
    assert "sed -n '1,120p' \"${EVIDENCE_DIR}/runner.stderr\"" not in workflow
    assert "sed -n '1,120p' \"${EVIDENCE_DIR}/collector.stderr\"" not in workflow


def test_workflow_does_not_accept_secret_shaped_inputs():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    validate = workflow.split("- name: Validate dispatch inputs", 1)[1]
    validate = validate.split("- name: Checkout", 1)[0]

    assert "Bearer " in validate
    assert "Authorization:" in validate
    assert "-----BEGIN .*PRIVATE KEY-----" in validate
    assert "must not contain token/private/secret-like material" in validate


@pytest.mark.parametrize(
    ("provider", "result_model", "result_device", "probe_applicable"),
    [
        ("internal", "faster-whisper-medium", "cuda", True),
        ("speechmatics", "speechmatics-realtime-v2", "speechmatics-saas", False),
    ],
)
def test_collector_builds_verifier_compatible_metadata_without_raw_transcript(
    tmp_path, provider, result_model, result_device, probe_applicable
):
    collector = _load_collector()
    smoke_file = tmp_path / "smoke.json"
    sample_sha = "a" * 64
    smoke_file.write_text(
        json.dumps(
            {
                "schemaVersion": "faz24.externalRecorderSmoke.v1",
                "status": "pass",
                "tokenIncluded": False,
                "ids": {
                    "meetingId": "22222222-2222-4222-8222-222222222222",
                    "captureId": "33333333-3333-4333-8333-333333333333",
                    "sessionId": "SES-31a15790-57eb-4cbe-b923-954c8f6578ac",
                },
                "sample": {
                    "chunkSeq": 0,
                    "sampleSha256": sample_sha,
                    "byteLength": 4096,
                    "audioFormat": "WAV",
                    "sampleRateHz": 48000,
                    "channels": 1,
                    "rawAudioIncluded": False,
                },
                "steps": [
                    {"name": "token_contract", "ok": True, "report": {"status": "pass", "tokenIncluded": False}},
                    {
                        "name": "create_meeting",
                        "method": "POST",
                        "path": "/api/v1/admin/meetings",
                        "statusCode": 201,
                        "ok": True,
                        "tokenIncluded": False,
                        "response": {"id": "22222222-2222-4222-8222-222222222222"},
                    },
                    {"name": "record_consent", "statusCode": 201, "ok": True, "tokenIncluded": False},
                    {
                        "name": "start_session",
                        "statusCode": 201,
                        "ok": True,
                        "tokenIncluded": False,
                        "response": {"sttProvider": provider},
                    },
                    {
                        "name": "upload_chunk",
                        "statusCode": 200,
                        "ok": True,
                        "tokenIncluded": False,
                        "response": {"chunkSeq": 0, "correlationId": "faz24-direct-stt-test"},
                    },
                    {"name": "finish_session", "statusCode": 200, "ok": True, "tokenIncluded": False},
                    {"name": "session_status", "statusCode": 200, "ok": True, "tokenIncluded": False},
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_runner(argv, _timeout):
        if argv[:4] == ["kubectl", "config", "get-contexts", "k3d-test"]:
            return collector.CommandResult(0, "k3d-test\n", "")
        if argv[:4] == ["kubectl", "--context", "k3d-test", "get"] and argv[4:6] == ["namespace", "platform-test"]:
            return collector.CommandResult(0, '{"metadata":{"name":"platform-test"}}', "")
        if argv[:6] == ["kubectl", "--context", "k3d-test", "-n", "platform-test", "get"]:
            kind = argv[6]
            name = argv[7] if len(argv) > 8 and argv[7] != "-o" else None
            if kind == "configmap":
                return collector.CommandResult(0, json.dumps({"data": {"AUDIO_GATEWAY_DIRECT_STT_ENABLED": "true"}}), "")
            if kind == "deployment":
                return collector.CommandResult(
                    0,
                    json.dumps(
                        {
                            "spec": {
                                "template": {
                                    "spec": {
                                        "hostAliases": [{"ip": "10.99.0.2", "hostnames": ["live-stt.denetim"]}],
                                        "containers": [
                                            {
                                                "name": "audio-gateway",
                                                "volumeMounts": [
                                                    {"name": "direct-stt-mtls", "mountPath": "/etc/direct-stt-mtls"}
                                                ],
                                            }
                                        ],
                                    }
                                }
                            }
                        }
                    ),
                    "",
                )
            if kind == "pods":
                return collector.CommandResult(
                    0,
                    json.dumps(
                        {
                            "items": [
                                {
                                    "metadata": {
                                        "name": "audio-gateway-abc",
                                        "creationTimestamp": "2026-06-29T10:00:00Z",
                                        "labels": {"app.kubernetes.io/name": "audio-gateway"},
                                    },
                                    "status": {
                                        "phase": "Running",
                                        "containerStatuses": [
                                            {
                                                "name": "audio-gateway",
                                                "ready": True,
                                                "imageID": "repo@sha256:" + ("b" * 64),
                                            }
                                        ],
                                    },
                                }
                            ]
                        }
                    ),
                    "",
                )
            if kind == "secret" and name == "audio-gateway-direct-stt-mtls":
                return collector.CommandResult(
                    0,
                    "direct-stt-ca.crt\ndirect-stt-client.crt\ndirect-stt-client.key\n",
                    "",
                )
        if argv[:3] == ["kubectl", "--context", "k3d-test"] and "exec" in argv:
            return collector.CommandResult(0, "200 67\n", "")
        if argv[:3] == ["kubectl", "--context", "k3d-test"] and "logs" in argv:
            return collector.CommandResult(0, "Direct-STT transcript received textLen=12\n", "")
        if argv[:4] == ["docker", "exec", "platform-pg-test", "psql"]:
            return collector.CommandResult(
                0,
                "\t".join(
                    [
                        "1782471276846-0",
                        "CHUNK_FORWARDED_TO_COMPUTE_PLANE",
                        "SES-31a15790-57eb-4cbe-b923-954c8f6578ac",
                        "0",
                        "faz24-direct-stt-test",
                        "t",
                        "t",
                        "t",
                        "SHA-256",
                        "1",
                    ]
                )
                + "\n",
                "",
            )
        if argv[:2] == ["docker", "exec"]:
            stream = argv[-2]
            if stream == "transcript:direct-stt-results":
                return collector.CommandResult(
                    0,
                    json.dumps(
                        [
                            [
                                "1782471276845-0",
                                [
                                    "eventType",
                                    "DIRECT_STT_TRANSCRIPT_RESULT",
                                    "sessionId",
                                    "SES-31a15790-57eb-4cbe-b923-954c8f6578ac",
                                    "chunkSeq",
                                    "0",
                                    "correlationId",
                                    "faz24-direct-stt-test",
                                    "textDraft",
                                    "Merhaba dunya",
                                    "model",
                                    result_model,
                                    "device",
                                    result_device,
                                ],
                            ]
                        ]
                    ),
                    "",
                )
            if stream == "audio:chunks:p00":
                return collector.CommandResult(
                    0,
                    json.dumps(
                        [
                            [
                                "1782471276844-0",
                                [
                                    "sessionId",
                                    "SES-31a15790-57eb-4cbe-b923-954c8f6578ac",
                                    "chunkSeq",
                                    "0",
                                    "correlationId",
                                    "faz24-direct-stt-test",
                                    "sha256",
                                    sample_sha,
                                    "audioFormat",
                                    "WAV",
                                ],
                            ]
                        ]
                    ),
                    "",
                )
            return collector.CommandResult(0, "[]", "")
        raise AssertionError(f"unexpected command: {argv}")

    args = argparse.Namespace(
        external_smoke_file=smoke_file,
        output=tmp_path / "e2e.json",
        context="k3d-test",
        namespace="platform-test",
        deployment="audio-gateway",
        redis_container="platform-redis-streams-test",
        redis_service="redis-streams",
        redis_secret="audio-gateway-secrets",
        redis_secret_key="SPRING_DATA_REDIS_PASSWORD",
        redis_cli_image="redis:7.4-alpine",
        gitops_commit="5fb581052354c8874c575573d755a0bf47ba923f",
        probe_timeout=40,
        redis_count=1000,
    )
    evidence = collector.collect(args, fake_runner)
    rendered = json.dumps(evidence)

    assert evidence["status"] == "pass"
    assert evidence["flow"]["sessionId"].startswith("SES-")
    assert evidence["flow"]["transcriptCharCount"] == len("Merhaba dunya")
    assert evidence["runtime"]["selectedProvider"] == provider
    assert evidence["flow"]["sttProvider"] == provider
    assert evidence["flow"]["resultModel"] == result_model
    assert evidence["flow"]["resultDevice"] == result_device
    assert evidence["mtlsProbe"]["applicable"] is probe_applicable
    assert evidence["audit"]["chunkSeqMatches"] is True
    assert evidence["audit"]["evidenceSource"] == "durable-db"
    assert evidence["audit"]["entryHashPresent"] is True
    assert evidence["audit"]["prevHashPresent"] is True
    assert "Merhaba dunya" not in rendered
    assert "textDraft" not in rendered
