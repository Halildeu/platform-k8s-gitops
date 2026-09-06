import importlib.util
import json
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "scripts/faz24/meeting_source_runtime_metadata.py"
SPEC = importlib.util.spec_from_file_location("metadata", PATH)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def test_metadata_does_not_publish_config_or_unrelated_pods():
    calls = []

    def read(kind, name):
        calls.append((kind, name))
        if kind == "deployment":
            return {"metadata": {"generation": 1}, "spec": {"template": {"spec": {
                "containers": [{"image": "image@sha256:test", "env": [{"value": "private"}]}]}}}}
        if kind == "pods":
            return {"items": [{"metadata": {"labels": {"app.kubernetes.io/name": "other-private"}}}]}
        return {"data": {"MEETING_TRANSCRIPT_READ_ENABLED": "true", "private": "sensitive"}}

    report = helper.snapshot(read)
    assert report["transcriptReadConfigMapSetting"] == "true"
    assert report["pods"] == []
    assert "private" not in json.dumps(report)
    assert "sensitive" not in json.dumps(report)
    assert report["secretRead"] is False
    assert report["runtimeMutation"] is False
    assert {kind for kind, _ in calls} == {"deployment", "pods", "configmap"}
