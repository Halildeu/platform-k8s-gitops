import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_OVERLAY = REPO_ROOT / "kustomize/overlays/test"
TEST_ESO_OVERLAY = REPO_ROOT / "kustomize/overlays/test/eso"


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


def _render_test_eso_overlay() -> list[dict]:
    proc = subprocess.run(
        ["kubectl", "kustomize", str(TEST_ESO_OVERLAY)],
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


def test_audio_gateway_direct_stt_mtls_uses_dedicated_secret_domain():
    rendered = _render_test_overlay()
    deployment = _find(rendered, "Deployment", "audio-gateway")
    pod_spec = deployment["spec"]["template"]["spec"]
    container = next(
        item for item in pod_spec["containers"] if item["name"] == "audio-gateway"
    )

    env_secret_names = {
        item.get("secretRef", {}).get("name")
        for item in container.get("envFrom", [])
        if "secretRef" in item
    }
    assert env_secret_names == {"audio-gateway-secrets"}

    direct_volume = next(
        item for item in pod_spec["volumes"] if item["name"] == "direct-stt-mtls"
    )
    assert direct_volume["secret"]["secretName"] == "audio-gateway-direct-stt-mtls"
    assert direct_volume["secret"]["optional"] is True
    assert direct_volume["secret"]["defaultMode"] == 0o440

    rendered_eso = _render_test_eso_overlay()
    aggregate = _find(rendered_eso, "ExternalSecret", "audio-gateway-secrets")
    aggregate_keys = {item["secretKey"] for item in aggregate["spec"]["data"]}
    assert aggregate_keys == {"SPRING_DATA_REDIS_PASSWORD"}

    mtls = _find(rendered_eso, "ExternalSecret", "audio-gateway-direct-stt-mtls")
    mtls_keys = {item["secretKey"] for item in mtls["spec"]["data"]}
    mtls_properties = {item["remoteRef"]["property"] for item in mtls["spec"]["data"]}
    assert mtls["spec"]["target"]["name"] == "audio-gateway-direct-stt-mtls"
    assert mtls_keys == {
        "direct-stt-ca.crt",
        "direct-stt-client.crt",
        "direct-stt-client.key",
    }
    assert mtls_properties == {
        "direct_stt_ca_crt",
        "direct_stt_client_crt",
        "direct_stt_client_key",
    }
