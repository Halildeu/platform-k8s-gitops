#!/usr/bin/env bash
# Faz 24 (#3437 madde 4) — meeting-ai ready-consumer stale watchdog.
#
# The GPU-host meeting-ai refuses to start when its transcript-ready permit no
# longer matches the deployed platform-ai commit, and that refusal is a single
# log line: the port simply never opens. On 2026-08-04 nobody noticed for hours
# and three meetings went unanalysed. This watchdog turns that silence into an
# alert.
#
# Checks (all read-only, over the existing WireGuard mTLS hop):
#   1. meeting-ai answers /ready at all;
#   2. ready_consumer.enabled is true and its worker is running;
#   3. the Redis consumer group is not falling behind (lag under a bound).
#
# Emits one Teams Adaptive Card per state change (never on every run) via the
# workspace Power Automate webhook already used for platform alerts.
set -euo pipefail
umask 077

STATE_FILE="${MAI_WATCHDOG_STATE:-/var/lib/platform/mai-watchdog.state}"
WEBHOOK_FILE="${MAI_WATCHDOG_WEBHOOK_FILE:-/srv/platform/secrets/alerting/teams-webhook.url}"
CONTEXT="${MAI_WATCHDOG_CONTEXT:-k3d-test}"
NAMESPACE="${MAI_WATCHDOG_NAMESPACE:-platform-test}"
MTLS_SECRET="${MAI_WATCHDOG_SECRET:-audio-gateway-direct-stt-mtls}"
HOST="${MAI_WATCHDOG_HOST:-live-stt.denetim}"
PORT="${MAI_WATCHDOG_PORT:-8244}"
HOST_IP="${MAI_WATCHDOG_HOST_IP:-10.99.0.2}"
MAX_LAG="${MAI_WATCHDOG_MAX_LAG:-25}"

WORK="$(mktemp -d /tmp/mai-watchdog.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

fail_reason=""
ready_json=""

if ! kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret "$MTLS_SECRET" -o json > "$WORK/secret.json" 2>/dev/null; then
  fail_reason="mTLS secret $MTLS_SECRET okunamadi"
else
  WORK="$WORK" python3 - <<'PY'
import base64, json, os
data = json.load(open(os.path.join(os.environ["WORK"], "secret.json")))["data"]
for key, name in (("direct-stt-ca.crt", "ca.crt"),
                  ("direct-stt-client.crt", "client.crt"),
                  ("direct-stt-client.key", "client.key")):
    open(os.path.join(os.environ["WORK"], name), "wb").write(base64.b64decode(data[key]))
PY
  if ! ready_json="$(curl -sS --cert "$WORK/client.crt" --key "$WORK/client.key" --cacert "$WORK/ca.crt" \
      --resolve "${HOST}:${PORT}:${HOST_IP}" --max-time 10 "https://${HOST}:${PORT}/ready" 2>/dev/null)"; then
    fail_reason="meeting-ai /ready yanit vermiyor (port kapali olabilir — permit reddi bu sekilde gorunur)"
  fi
fi

if [ -z "$fail_reason" ] && [ -n "$ready_json" ]; then
  fail_reason="$(READY_JSON="$ready_json" MAX_LAG="$MAX_LAG" python3 - <<'PY'
import json, os
try:
    ready = json.loads(os.environ["READY_JSON"])
except ValueError:
    print("meeting-ai /ready gecerli JSON dondurmedi")
    raise SystemExit(0)
consumer = ready.get("ready_consumer") or {}
problems = []
if not consumer.get("enabled"):
    problems.append("ready_consumer kapali (permit reddi veya elle devre disi)")
elif not consumer.get("worker_running"):
    problems.append("ready_consumer worker calismiyor")
elif not consumer.get("redis_group_ready"):
    problems.append("redis tuketici grubu hazir degil")
unfinished = consumer.get("oldest_unfinished_age_sec")
if isinstance(unfinished, (int, float)) and unfinished > 900:
    problems.append(f"en eski islenmemis olay {int(unfinished)}s bekliyor")
error_code = consumer.get("error_code")
if error_code:
    problems.append(f"consumer error_code={error_code}")
print("; ".join(problems))
PY
)"
fi

state="ok"
[ -n "$fail_reason" ] && state="alert"
previous="$( [ -f "$STATE_FILE" ] && cat "$STATE_FILE" || echo "unknown" )"
mkdir -p "$(dirname "$STATE_FILE")"
printf '%s' "$state" > "$STATE_FILE"

if [ "$state" = "$previous" ]; then
  exit 0   # no state change — stay quiet
fi

if [ ! -r "$WEBHOOK_FILE" ]; then
  printf 'mai-watchdog: state %s -> %s (%s); webhook dosyasi okunamadi\n' "$previous" "$state" "${fail_reason:-saglikli}" >&2
  exit 0
fi

if [ "$state" = "alert" ]; then
  title="Faz 24 — meeting-ai analiz tuketicisi durdu"
  text="Denetim PC uzerindeki meeting-ai ready-consumer saglikli degil: ${fail_reason}. Toplanti analizleri (ozet/karar/aksiyon) uretilmiyor. Runbook: docs/runbooks/RB-faz24-transcript-ready-legacy-pre-enable.md — permit yenileme: scripts/faz24/issue-transcript-ready-permit.sh"
else
  title="Faz 24 — meeting-ai analiz tuketicisi normale dondu"
  text="ready-consumer yeniden calisiyor; analiz uretimi devam ediyor."
fi

payload="$(TITLE="$title" TEXT="$text" python3 - <<'PY'
import json, os
print(json.dumps({
    "type": "message",
    "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": os.environ["TITLE"]},
                {"type": "TextBlock", "wrap": True, "text": os.environ["TEXT"]},
            ],
        },
    }],
}))
PY
)"

curl -sS -X POST -H "Content-Type: application/json" --data-binary "$payload" \
  --max-time 15 "$(cat "$WEBHOOK_FILE")" >/dev/null || {
    printf 'mai-watchdog: Teams bildirimi gonderilemedi (state %s)\n' "$state" >&2
  }
