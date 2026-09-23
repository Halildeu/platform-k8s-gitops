"""Read-only TEST metadata for the source-read customer step tracked by #3399."""
import json
import argparse
import re
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
    for name in ("meeting-service", "transcript-service", "audio-gateway"):
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


LIVE_METRICS = {
    "audio_gw_live_analyze_publish_total", "audio_gw_live_analyze_coalesced_total",
    "audio_gw_live_analyze_publish_success_total", "audio_gw_live_analyze_publish_error_total",
    "audio_gw_live_analyze_drop_total", "audio_gw_live_analyze_request_seconds_count",
    "audio_gw_live_analyze_request_seconds_sum", "audio_gw_live_analyze_request_seconds_max",
}


def parse_live_diagnostics(metrics_text, logs_text):
    counters = {}
    for line in metrics_text.splitlines():
        match = re.fullmatch(r'([a-z_]+)(?:\{[^\n]*\})? ([0-9.eE+\-]+)', line)
        if match and match[1] in LIVE_METRICS:
            counters[match[1]] = counters.get(match[1], 0.0) + float(match[2])
    errors = []
    pattern = re.compile(
        r'live-analyze trigger failed err_class=([A-Za-z0-9_]{1,80}) '
        r'http_status=([0-9]{1,3}) meeting_id=([0-9a-f-]{36}) '
        r'seq=([0-9]{1,12}) elapsed_ms=([0-9]{1,12})(?:\s|$)'
    )
    for match in pattern.finditer(logs_text):
        errors.append({"errorClass": match[1], "httpStatus": int(match[2]),
                       "meetingId": match[3], "sequence": int(match[4]),
                       "elapsedMs": int(match[5])})
    return {"counters": counters, "recentErrors": errors[-30:],
            "rawLogsIncluded": False, "payloadIncluded": False,
            "counterScope": "pod-lifetime; not per-meeting",
            "logScope": "last 20 minutes; last 1000 lines; at most 262144 bytes"}


def mtls_health_probe(pod, port, run_fn=subprocess.run):
    """Use installed credentials in place; export only curl status/timings."""
    if port not in (8243, 8244):
        raise ValueError("unsupported-mtls-probe-port")
    command = ["kubectl", "--context", "k3d-test", "-n", "platform-test",
               "exec", pod, "-c", "audio-gateway", "--", "curl", "--disable",
               "--silent", "--output", "/dev/null", "--connect-timeout", "5",
               "--max-time", "10", "--proto", "=https",
               "--cacert", "/etc/direct-stt-mtls/direct-stt-ca.crt",
               "--cert", "/etc/direct-stt-mtls/direct-stt-client.crt",
               "--key", "/etc/direct-stt-mtls/direct-stt-client.key",
               "--write-out", "%{http_code} %{time_connect} %{time_appconnect} %{time_total} %{ssl_verify_result}",
               f"https://live-stt.denetim:{port}/health"]
    result = run_fn(command, capture_output=True, text=True, timeout=25, check=False)
    match = re.fullmatch(r"([0-9]{3}) ([0-9.]+) ([0-9.]+) ([0-9.]+) ([0-9]+)", result.stdout.strip())
    report = {"port": port, "exitCode": result.returncode,
              "credentialMaterialExported": False, "verifiedTlsRequired": True,
              "probeScope": "gateway pod to fixed upstream health; not inference acceptance"}
    if match:
        report.update(httpStatus=int(match[1]), connectSeconds=float(match[2]),
                      tlsSeconds=float(match[3]), totalSeconds=float(match[4]),
                      sslVerifyResult=int(match[5]))
    else:
        report["status"] = "no-parseable-probe-metadata"
    return report


def live_diagnostics():
    pods = read("pods", "").get("items", [])
    candidates = [pod for pod in pods if
                  pod["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "audio-gateway"
                  and not pod["metadata"].get("deletionTimestamp")]
    if len(candidates) != 1:
        raise RuntimeError("live-diagnostics-requires-one-gateway-pod")
    pod = candidates[0]["metadata"]["name"]
    prefix = ["kubectl", "--context", "k3d-test", "-n", "platform-test"]
    def capture(command):
        result = subprocess.run(prefix + command, capture_output=True, text=True, timeout=30, check=False)
        if result.returncode:
            raise RuntimeError("live-diagnostics-read-failed")
        return result.stdout
    metrics = capture(["exec", pod, "--", "curl", "--silent", "--fail", "--max-time", "10",
                       "http://localhost:8081/actuator/prometheus"])
    logs = capture(["logs", pod, "--since=20m", "--tail=1000", "--limit-bytes=262144"])
    report = parse_live_diagnostics(metrics, logs)
    report["mtlsHealthProbes"] = [mtls_health_probe(pod, port) for port in (8243, 8244)]
    report["mountedCredentialUsedInPlace"] = True
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-analysis", action="store_true")
    args = parser.parse_args()
    try:
        report = snapshot()
        if args.live_analysis:
            report["liveAnalysis"] = live_diagnostics()
        print(json.dumps(report, sort_keys=True))
    except Exception as error:
        print(json.dumps({"status": "error", "errorClass": type(error).__name__}))
        raise SystemExit(1)
