import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_OVERLAY = REPO_ROOT / "kustomize/overlays/test"


def _render_test_overlay() -> list[dict]:
    proc = subprocess.run(
        ["kubectl", "kustomize", str(TEST_OVERLAY)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return [doc for doc in yaml.safe_load_all(proc.stdout) if isinstance(doc, dict)]


def _find(rendered: list[dict], kind: str, name: str) -> dict:
    for doc in rendered:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"rendered {kind}/{name} not found")


def test_audio_gateway_authz_enforce_flip_triggers_pod_rollout():
    rendered = _render_test_overlay()

    config = _find(rendered, "ConfigMap", "audio-gateway-config")
    assert config["data"]["AUDIO_GATEWAY_SECURITY_ENFORCE_AUDIENCE"] == "true"
    assert config["data"]["AUDIO_GATEWAY_SECURITY_REQUIRE_AUDIO_RECORD_ROLE"] == "true"

    deployment = _find(rendered, "Deployment", "audio-gateway")
    annotations = deployment["spec"]["template"]["metadata"].get("annotations", {})
    assert (
        annotations.get("audio-gateway.acik.com/authz-enforce-rev")
        == "2026-06-26-716-enforce-v2"
    )
