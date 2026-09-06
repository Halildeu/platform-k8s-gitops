import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def render(overlay):
    output = subprocess.check_output(["kustomize", "build", str(ROOT / "kustomize/overlays" / overlay)], text=True)
    return list(yaml.safe_load_all(output))


def test_source_activation_uses_fixed_artifact_and_existing_identity_in_test():
    docs = render("test")
    config = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "meeting-service-config")
    assert config["data"]["MEETING_TRANSCRIPT_READ_ENABLED"] == "true"
    deployment = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "meeting-service")
    assert deployment["metadata"]["namespace"] == "platform-test"
    container = next(c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == "meeting-service")
    binding = next(e for e in container["env"] if e["name"] == "MEETING_TRANSCRIPT_READ_CLIENT_SECRET")
    assert binding == {
        "name": "MEETING_TRANSCRIPT_READ_CLIENT_SECRET",
        "valueFrom": {"secretKeyRef": {
            "name": "meeting-service-secrets",
            "key": "MEETING_ASSIGNEE_DIRECTORY_CLIENT_SECRET",
            "optional": False,
        }},
    }
    assert container["image"] == (
        "ghcr.io/halildeu/platform-backend-meeting-service@"
        "sha256:e11c77ab4c0f9f9b660f54ad0a831a66bb2a65c9bd58e6937f2bbd77ce33691d"
    )
    assert deployment["spec"]["strategy"]["rollingUpdate"]["maxUnavailable"] == 1


def test_no_production_source_activation():
    docs = render("prod")
    assert "MEETING_TRANSCRIPT_READ_ENABLED" not in yaml.safe_dump(docs)
    assert "MEETING_TRANSCRIPT_READ_CLIENT_SECRET" not in yaml.safe_dump(docs)
