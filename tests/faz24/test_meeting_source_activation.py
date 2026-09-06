import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def render(overlay):
    output = subprocess.check_output(["kustomize", "build", str(ROOT / "kustomize/overlays" / overlay)], text=True)
    return list(yaml.safe_load_all(output))


def test_source_read_uses_existing_test_identity_and_rolls_pod():
    docs = render("test")
    config = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "meeting-service-config")
    assert config["data"]["MEETING_TRANSCRIPT_READ_ENABLED"] == "true"
    deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "meeting-service")
    assert deployment["metadata"]["namespace"] == "platform-test"
    container = next(c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == "meeting-service")
    binding = next(e for e in container["env"] if e["name"] == "MEETING_TRANSCRIPT_READ_CLIENT_SECRET")
    assert binding == {"name": "MEETING_TRANSCRIPT_READ_CLIENT_SECRET", "valueFrom": {"secretKeyRef": {
        "name": "meeting-service-secrets", "key": "MEETING_ASSIGNEE_DIRECTORY_CLIENT_SECRET"}}}
    assert deployment["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 1


def test_no_production_source_activation():
    docs = render("prod")
    assert "MEETING_TRANSCRIPT_READ_ENABLED" not in yaml.safe_dump(docs)
    assert "MEETING_TRANSCRIPT_READ_CLIENT_SECRET" not in yaml.safe_dump(docs)
