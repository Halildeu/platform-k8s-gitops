from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/run_audio_gateway_session_expiry_transient_smoke.sh"


def test_transient_smoke_script_is_shell_syntax_valid():
    proc = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_transient_smoke_is_isolated_bounded_and_cleans_up():
    text = SCRIPT.read_text(encoding="utf-8")

    assert "EXPECTED_IMAGE must be an immutable image@sha256 reference" in text
    assert 'SOURCE_IMAGE}" != "${EXPECTED_IMAGE}' in text
    assert 'EXPECTED_DIGEST="${EXPECTED_IMAGE##*@}"' in text
    assert 'POD_IMAGE_DIGEST="${POD_IMAGE_ID##*@}"' in text
    assert 'POD_IMAGE_DIGEST}" != "${EXPECTED_DIGEST}' in text
    assert '"app.kubernetes.io/name": $name' in text
    assert '"evidence.platform/transient-smoke": "audio-gateway-session-expiry"' in text
    assert "activeDeadlineSeconds" in text
    assert "ttlSecondsAfterFinished: 60" in text
    assert "TRANSIENT_TTL_SECONDS must be between 120 and 1800" in text
    assert 'trap - EXIT INT TERM' in text
    assert "cleanup_resources" in text
    assert 'delete networkpolicy "${NETPOL_NAME}"' in text
    assert 'delete job "${JOB_NAME}"' in text
    assert "--cascade=foreground" in text
    assert "transient smoke cleanup could not be verified" in text
    assert 'get job "${JOB_NAME}" --ignore-not-found -o name' in text
    assert 'get networkpolicy "${NETPOL_NAME}" --ignore-not-found -o name' in text
    assert 'for attempt in 1 2 3' in text
    assert 'if [[ "${cleanup_rc}" == "0" ]]' in text
    assert 'AUDIO_GATEWAY_MAX_SESSION_MINUTES", value: "1"' in text
    assert 'AUDIO_GATEWAY_SESSION_EXPIRY_SWEEP_MS", value: "1000"' in text
    assert 'AUDIO_GATEWAY_BOUNDS_MAX_ACTIVE_SESSIONS", value: "1"' in text
    assert 'AUDIO_GATEWAY_DISPATCHER_MODE", value: "noop"' in text
    assert 'AUDIO_GATEWAY_AUDIT_REDIS_ENABLED", value: "false"' in text
    assert 'AUDIO_GATEWAY_HEALTH_REDIS_ENABLED", value: "false"' in text
    assert 'AUDIO_GATEWAY_DIRECT_STT_TRANSCRIPT_RESULT_STREAM_ENABLED", value: "false"' in text
    assert '.secretRef.name != "audio-gateway-secrets"' in text
    assert "RUN_SESSION_EXPIRY_SMOKE=1" in text
    assert 'KC_ADMIN_TRANSPORT="rest"' in text
    assert 'BASE_URL="https://testai.acik.com"' in text
    assert 'EXPECTED_ISSUER="https://testai.acik.com/realms/platform-test"' in text
    assert "SESSION_EXPIRY_EXPECTED_IMAGE" in text
    assert "SESSION_EXPIRY_POD_UID" in text
    assert '"pod/${POD_NAME}" ":8210" ":8081"' in text
    assert "kubectl port-forward did not allocate both loopback ports" in text
    assert "kubectl port-forward exited during smoke" in text
    assert "transient pod runtime binding changed during smoke" in text
    assert "POST_POD_UID" in text
    assert "POST_POD_IMAGE_ID" in text
    assert ".cleanup.directGrantsRestored == true" in text
    assert ".cleanup.tempUserDeleted == true" in text
    assert ".cleanup.tokenFileRemoved == true" in text
    assert ".clientBefore.protocolMappers | sort_by" in text
    assert ".clientAfter.protocolMappers | sort_by" in text
    assert "run-platform-desktop-token-evidence-chain.sh" in text
    assert "kubectl set image" not in text
    assert "kubectl patch" not in text
    assert "kubectl edit" not in text
    assert "set -x" not in text
