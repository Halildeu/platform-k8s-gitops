"""Fixed TEST mTLS synthetic live-update probe; stdout is metadata only."""
import json
import subprocess
import time
import uuid

PREFIX = ["kubectl", "--context", "k3d-test", "-n", "platform-test"]
STAGES = [
    ("Ayşe sunum dosyasını cuma günü hazırlayacak.", [], [0]),
    ("Sunumu çevrim içi yapmaya karar verdik. Mehmet bütçe tablosunu kontrol edecek.", [1], [0, 2]),
    ("Ayşe için sunum dosyası hazırlama görevini iptal ettik.", [1], [2]),
    ("Mehmet'in bütçe kontrolü görevi iptal edildi. Zeynep bütçe tablosunu kontrol edecek.", [1], [5]),
    ("Katılımcılar gündemin diğer konularını görüştü.", [1], [5]),
]
SOURCE = [
    "Ayşe sunum dosyasını cuma günü hazırlayacak.",
    "Sunumu çevrim içi yapmaya karar verdik.",
    "Mehmet bütçe tablosunu kontrol edecek.",
    "Ayşe için sunum dosyası hazırlama görevini iptal ettik.",
    "Mehmet'in bütçe kontrolü görevi iptal edildi.",
    "Zeynep bütçe tablosunu kontrol edecek.",
    "Katılımcılar gündemin diğer konularını görüştü.",
]


def metadata(body, version, decisions, actions, elapsed):
    required_decisions = {SOURCE[i] for i in decisions}
    # Cancellation itself can legitimately also be a decision. It must remove
    # the task; do not fail a correct model for additionally listing the change.
    optional = ([3] if version >= 3 else []) + ([4] if version >= 4 else [])
    actual_decisions = set(body.get("decisions", []))
    owners = {0: ("Ayşe", "cuma günü"), 2: ("Mehmet", None), 5: ("Zeynep", None)}
    expected_actions = {(SOURCE[i], *owners[i]) for i in actions}
    correct = (
        body.get("is_partial") is True and body.get("version") == version
        and required_decisions <= actual_decisions <= required_decisions | {SOURCE[i] for i in optional}
        and {(item["text"], item.get("owner"), item.get("due_date"))
             for item in body.get("action_items", [])} == expected_actions
        and body.get("ungrounded_count") == 0
        and body.get("grounding_policy") == "verified_only"
    )
    return {"version": version, "qualityPass": correct,
            "elapsedSeconds": round(elapsed, 3), "withinFiveSeconds": elapsed <= 5,
            "decisionCount": len(body.get("decisions", [])),
            "actionCount": len(body.get("action_items", [])),
            "cursorReturned": isinstance(body.get("live_cursor"), dict)}


def probe():
    pods = subprocess.run(PREFIX + ["get", "pods", "-l", "app.kubernetes.io/name=audio-gateway",
                                  "-o", "json"], capture_output=True, text=True,
                          timeout=20, check=True)
    candidates = [p for p in json.loads(pods.stdout)["items"]
                  if not p["metadata"].get("deletionTimestamp")
                  and p.get("status", {}).get("phase") == "Running"]
    if len(candidates) != 1:
        raise RuntimeError("requires-one-running-test-gateway")
    pod = candidates[0]["metadata"]["name"]
    command = PREFIX + ["exec", "-i", pod, "-c", "audio-gateway", "--", "curl", "--disable",
                        "--silent", "--fail", "--connect-timeout", "5", "--max-time", "120",
                        "--proto", "=https", "--cacert", "/etc/direct-stt-mtls/direct-stt-ca.crt",
                        "--cert", "/etc/direct-stt-mtls/direct-stt-client.crt",
                        "--key", "/etc/direct-stt-mtls/direct-stt-client.key",
                        "-H", "Content-Type: application/json", "--data-binary", "@-",
                        "https://live-stt.denetim:8244/analyze/live"]
    meeting = str(uuid.uuid4())
    transcript, cursor, rows = "", None, []
    for version, (addition, decisions, actions) in enumerate(STAGES, 1):
        transcript = (transcript + " " + addition).strip()
        payload = {"transcript": transcript, "meeting_id": meeting, "segment_seq": version}
        if cursor is not None:
            payload["previous_live_cursor"] = cursor
        started = time.monotonic()
        result = subprocess.run(command, input=json.dumps(payload), capture_output=True,
                                text=True, timeout=135, check=False)
        elapsed = time.monotonic() - started
        if result.returncode:
            rows.append({"version": version, "transportExitCode": result.returncode})
            break
        body = json.loads(result.stdout)
        rows.append(metadata(body, version, decisions, actions, elapsed))
        cursor = body.get("live_cursor")
    passed = len(rows) == len(STAGES) and all(
        row.get("qualityPass") and row.get("withinFiveSeconds")
        and row.get("cursorReturned") for row in rows)
    return {"schema": "test-live-incremental-latency-v1", "synthetic": True,
            "status": "pass" if passed else "fail", "phoneAcceptance": False,
            "scope": "gateway-pod-to-live-AI HTTP; excludes STT and phone rendering",
            "credentialMaterialExported": False, "rows": rows}


if __name__ == "__main__":
    try:
        report = probe()
    except Exception as error:
        # No raw response, command output, exception text or meeting text in evidence.
        report = {"status": "error", "errorClass": type(error).__name__, "phoneAcceptance": False}
    print(json.dumps(report, ensure_ascii=True, indent=2))
    raise SystemExit(0 if report["status"] == "pass" else 1)
