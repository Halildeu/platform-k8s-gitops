"""Read-only TEST metadata for the source-read customer step tracked by #3399."""
import json
import subprocess


def read(kind, name):
    result = subprocess.run(
        ["kubectl", "--context", "k3d-test", "-n", "platform-test", "get", kind]
        + ([name] if name else []) + ["-o", "json", "--request-timeout=20s"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode:
        raise RuntimeError("test-metadata-read-failed")
    return json.loads(result.stdout)


def snapshot(read_fn=read):
    report = {"schemaVersion": "faz24.meetingSourceRuntimeMetadata.v1",
              "context": "k3d-test", "namespace": "platform-test",
              "runtimeMutation": False, "secretRead": False, "services": {}}
    for name in ("meeting-service", "transcript-service", "audio-gateway-service"):
        deployment = read_fn("deployment", name)
        report["services"][name] = {
            "generation": deployment["metadata"]["generation"],
            "observedGeneration": deployment.get("status", {}).get("observedGeneration"),
            "readyReplicas": deployment.get("status", {}).get("readyReplicas", 0),
            "images": [c["image"] for c in deployment["spec"]["template"]["spec"]["containers"]],
        }
    pods = read_fn("pods", "")
    report["pods"] = [
        {"service": pod["metadata"].get("labels", {}).get("app.kubernetes.io/name"),
         "deleting": bool(pod["metadata"].get("deletionTimestamp")),
         "containers": [{"name": c["name"], "ready": c.get("ready", False),
                         "imageID": c.get("imageID", "")} for c in pod.get("status", {}).get("containerStatuses", [])]}
        for pod in pods.get("items", [])
        if pod["metadata"].get("labels", {}).get("app.kubernetes.io/name") in report["services"]
    ]
    config = read_fn("configmap", "meeting-service-config").get("data", {})
    value = config.get("MEETING_TRANSCRIPT_READ_ENABLED")
    report["transcriptReadConfigMapSetting"] = value if value in ("true", "false") else "absent-or-nonboolean"
    report["effectiveProcessEnvironmentProven"] = False
    return report


if __name__ == "__main__":
    try:
        print(json.dumps(snapshot(), sort_keys=True))
    except Exception as error:
        print(json.dumps({"status": "error", "errorClass": type(error).__name__}))
        raise SystemExit(1)
