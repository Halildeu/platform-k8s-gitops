#!/usr/bin/env bash
# scripts/drift-detection/alarm_receiver.sh
#
# Codex P0 follow-up — drift detection JSON output → GitHub issue audit trail.
# Reads /tmp/drift-report-<env>-<ts>.json (produced by check_env_drift.sh)
# and opens a GitHub issue per P1/P2 finding (with deduplication via title
# match — repeated drift reuses existing issue's comment thread).
#
# Designed for staging-sw systemd integration:
#
#   ExecStart=/bin/bash check_env_drift.sh prod
#   ExecStartPost=/bin/bash alarm_receiver.sh /tmp/drift-report-prod-<ts>.json
#
# Or invoked manually for ad-hoc reports.
#
# Auth: requires gh CLI logged in (or GITHUB_TOKEN env). Read+write issues
# scope on platform-k8s-gitops repo. The runner identity (gha-runner SA or
# operator) must have issue write access.
#
# Codex P1 alarm class mapping (from openfga-model-contract.md):
#   P1: prod git/live digest mismatch >10min, GHCR manifest unknown,
#       ESO SecretSyncedError, OpenFGA admin tuple missing
#   P2: test git/live drift >30min, prod promotion lag >7d,
#       quota headroom < surge pod
#   P3: stale current-state docs, smoke creds missing
#
# This MVP supports P1+P2 (P3 deferred — needs current-state mtime check).
#
# Codex Sprint A P0 Item 6 hardening:
#   - Pre-flight: gh auth status + repo access verified BEFORE processing
#   - Persistent undelivered log: failed alarms → /var/log/.../undelivered.jsonl
#     (so retry-able later and audit trail not lost)
#   - Optional webhook fallback via DRIFT_ALARM_WEBHOOK env var
#   - Retry with exponential backoff on 429/5xx
#   - Capture gh stderr for actionable error messages
#
# Faz 23.2.D T1.4 PR-2 — D43 Outage Fallback Bypass (Codex 019e0dea iter-2):
#   - Alertmanager direct fallback chain extension (cluster-internal `/api/v2/alerts`)
#   - Trigger: ALARM_FALLBACK_ALERTMANAGER=1 + class=P1 + GH+webhook delivery fail
#   - Stable labels (alertname/cluster/severity/outage_fallback/dedupe_key)
#   - 4xx no-retry (auth/validation), 5xx/timeout retry exponential backoff
#   - No-token-log guard (payload contains NO secret/token/credential)
#   - Public Alertmanager exposure açılmaz; cluster-internal URL only
#
# Delivery chain (cascade order):
#   1) GitHub Issues (default — orchestrator-route audit trail)
#   2) DRIFT_ALARM_WEBHOOK generic webhook (GH 4xx/5xx/timeout sonrası)
#   3) Alertmanager direct (P1 only + ALARM_FALLBACK_ALERTMANAGER=1; GH+webhook fail)
#   4) Persistent undelivered log (all delivery paths failed)

set -uo pipefail

REPORT="${1:-/tmp/drift-report-prod-latest.json}"
[[ ! -f "$REPORT" ]] && { echo "ERR: report not found: $REPORT"; exit 1; }

REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"
UNDELIVERED_LOG="${ALARM_UNDELIVERED_LOG:-/var/log/platform-drift-alarm-undelivered.jsonl}"
WEBHOOK_URL="${DRIFT_ALARM_WEBHOOK:-}"
MAX_RETRIES=3

# Faz 23.2.D T1.4 PR-2 — D43 Outage Fallback Bypass: Alertmanager direct fallback.
#
# Codex thread 019e0dea iter-2 absorb: notification-orchestrator down olduğunda
# kritik drift alarm'larının Alertmanager üstünden direkt Slack/SMTP'ye gitmesi
# için yeni fallback path. Mevcut webhook fallback (DRIFT_ALARM_WEBHOOK) generic;
# Alertmanager native `/api/v2/alerts` payload format'ı için ayrı delivery path.
#
# Trigger sırası (Codex iter-2 absorb #2 fallback client trigger conditions):
#   1) GitHub Issues delivery (mevcut, default — orchestrator-route audit trail)
#   2) DRIFT_ALARM_WEBHOOK generic webhook (mevcut, GH 4xx/5xx/timeout sonrası)
#   3) Alertmanager direct (YENİ, P1 critical class + ALARM_FALLBACK_ALERTMANAGER=1)
#
# URL: ALERTMANAGER_FALLBACK_URL default cluster-internal
#   http://alertmanager.monitoring.svc.cluster.local:9093/api/v2/alerts
#
# Public Alertmanager exposure açılmaz (Codex iter-2 #7 absorb security).
# Token/secret/credential payload'a YAZILMAZ (no-token-log guard).
#
# Stable labels (Alertmanager fingerprint stability — Codex iter-2 #7 + iter-3):
#   alertname=DriftDetectionFallback
#   cluster=<env>
#   severity=critical            (P1 → critical; P2 → warning — Alertmanager routing convention)
#   drift_class=<P1|P2>          (orijinal sınıf ayrı label — Codex iter-3 #1)
#   kind=<finding kind>
#   outage_fallback=true
#   bypass_orchestrator=true
#   dedupe_key=<sha256(env+kind+title+full_msg)>   (Codex iter-3 #4 expanded input)
#
# 4xx auth fail → no retry (immediate undelivered log + escalate).
# 5xx/timeout/connection refused → retry MAX_RETRIES exponential backoff.
#
# Idempotency: dedupe_key stable across same finding; Alertmanager group_wait
# kendi side'da dedupe yapar; agent burda explicit retry'da aynı key gönderir.
#
# Mode (Codex iter-3 #2):
#   ALARM_FALLBACK_ALERTMANAGER_MODE=parallel  (default — D43 amacı: GH/webhook başarılı
#                                                olsa bile P1 + toggle aktifse Alertmanager
#                                                paralel gönderim; orchestrator-bypass
#                                                receipt kanıtı korunur)
#   ALARM_FALLBACK_ALERTMANAGER_MODE=last_resort (eski cascade davranışı; sadece
#                                                  GH+webhook fail sonrası gönderim)
ALERTMANAGER_FALLBACK_URL="${ALERTMANAGER_FALLBACK_URL:-http://alertmanager.monitoring.svc.cluster.local:9093/api/v2/alerts}"
ALARM_FALLBACK_ALERTMANAGER="${ALARM_FALLBACK_ALERTMANAGER:-0}"
ALARM_FALLBACK_ALERTMANAGER_MODE="${ALARM_FALLBACK_ALERTMANAGER_MODE:-parallel}"

# ------------------------------------------------------------
# Pre-flight: gh auth + repo access
# ------------------------------------------------------------
preflight() {
  if ! command -v gh > /dev/null 2>&1; then
    echo "ERR: gh CLI not installed — cannot deliver alarms via GitHub Issues"
    return 1
  fi

  # Check gh auth status (silent if logged in, errors if not)
  if ! gh auth status > /dev/null 2>&1; then
    echo "ERR: gh CLI not authenticated — run 'gh auth login' or set GITHUB_TOKEN"
    return 1
  fi

  # Check repo access (read OK = sufficient signal; write happens on actual API call)
  if ! gh repo view "$REPO" > /dev/null 2>&1; then
    echo "ERR: cannot access repo $REPO — check token scope (needs 'repo' or 'public_repo' + 'issues:write')"
    return 1
  fi

  echo "[alarm_receiver] pre-flight: gh auth OK, repo access OK"
  return 0
}

# ------------------------------------------------------------
# Undelivered log helper — persist failed alarms for retry/audit
# ------------------------------------------------------------
log_undelivered() {
  local cls="$1"
  local knd="$2"
  local title="$3"
  local body="$4"
  local reason="$5"

  # Best-effort dir creation (may need sudo on first run)
  local log_dir
  log_dir=$(dirname "$UNDELIVERED_LOG")
  mkdir -p "$log_dir" 2>/dev/null || true

  if [[ ! -w "$log_dir" ]]; then
    # Fallback to /tmp if /var/log not writable (no sudo)
    UNDELIVERED_LOG="/tmp/platform-drift-alarm-undelivered.jsonl"
  fi

  # Append JSONL entry
  local entry
  entry=$(jq -nc \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg env "$ENV" \
    --arg cls "$cls" \
    --arg knd "$knd" \
    --arg title "$title" \
    --arg body "$body" \
    --arg reason "$reason" \
    --arg report "$REPORT" \
    '{ts:$ts, environment:$env, class:$cls, kind:$knd, title:$title, body:$body, reason:$reason, report:$report}')

  echo "$entry" >> "$UNDELIVERED_LOG" 2>/dev/null || \
    echo "[WARN] could not write to $UNDELIVERED_LOG — alarm dropped" >&2
}

# ------------------------------------------------------------
# Webhook fallback (optional) — POST alarm payload to external URL
# ------------------------------------------------------------
deliver_webhook() {
  local cls="$1"
  local knd="$2"
  local title="$3"
  local msg="$4"

  [[ -z "$WEBHOOK_URL" ]] && return 1

  local payload
  payload=$(jq -nc \
    --arg env "$ENV" \
    --arg cls "$cls" \
    --arg knd "$knd" \
    --arg title "$title" \
    --arg msg "$msg" \
    --arg ts "$TS" \
    --arg report "$REPORT" \
    '{environment:$env, class:$cls, kind:$knd, title:$title, message:$msg, timestamp:$ts, report:$report}')

  local code
  code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 10 \
    -X POST -H "Content-Type: application/json" \
    -d "$payload" "$WEBHOOK_URL" 2>/dev/null || echo "000")

  case "$code" in
    2*) echo "  [webhook] delivered to $WEBHOOK_URL ($code)"; return 0 ;;
    *)  echo "  [webhook] FAILED ($code)"; return 1 ;;
  esac
}

# ------------------------------------------------------------
# Faz 23.2.D T1.4 PR-2 — D43 Alertmanager direct fallback delivery.
# Codex 019e0dea iter-2 absorb: cluster-internal Alertmanager `/api/v2/alerts`
# POST; stable labels (alertname/cluster/severity/outage_fallback/dedupe_key);
# 4xx no-retry (auth/validation), 5xx/timeout retry exponential backoff.
# ------------------------------------------------------------
deliver_alertmanager() {
  local cls="$1"
  local knd="$2"
  local title="$3"
  local msg="$4"

  # Trigger gate: Codex iter-2 absorb — yalnız critical class + explicit toggle
  if [[ "$ALARM_FALLBACK_ALERTMANAGER" != "1" ]]; then
    return 1
  fi

  # Codex iter-3 #1: severity Alertmanager routing convention `critical`/`warning`;
  # orijinal drift sınıfı (P1/P2) ayrı `drift_class` label'ında taşınır.
  # Repo Alertmanager routing `severity = "critical"` üzerinden çalışıyor.
  local sev_label
  case "$cls" in
    P1) sev_label="critical" ;;
    P2) sev_label="warning" ;;
    *)  sev_label="info" ;;
  esac

  # Codex iter-3 #4: Dedupe input expanded — env+kind+title+full_msg.
  # First 60 char dar; iki farklı P1 finding aynı prefix paylaşırsa collision.
  # Hash output sabit uzunlukta olduğu için label maliyeti artmaz.
  local sig_input
  sig_input=$(printf '%s|%s|%s|%s' "$ENV" "$knd" "$title" "$msg")

  # Codex iter-3 #3: sha256 portability — sha256sum primary (Linux), shasum fallback (macOS).
  local sig
  if command -v sha256sum > /dev/null 2>&1; then
    sig=$(printf '%s' "$sig_input" | sha256sum | awk '{print $1}')
  elif command -v shasum > /dev/null 2>&1; then
    sig=$(printf '%s' "$sig_input" | shasum -a 256 | awk '{print $1}')
  else
    echo "  [alertmanager-fallback] ERROR: no sha256 implementation (sha256sum/shasum) — cannot compute dedupe_key" >&2
    return 1
  fi

  # Compose Alertmanager v2 alerts payload
  # [{labels:{...}, annotations:{...}, startsAt:..., generatorURL:...}]
  local payload
  payload=$(jq -nc \
    --arg alertname "DriftDetectionFallback" \
    --arg cluster "$ENV" \
    --arg severity "$sev_label" \
    --arg drift_class "$cls" \
    --arg knd "$knd" \
    --arg title "$title" \
    --arg msg "$msg" \
    --arg sig "$sig" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" \
    --arg report "$REPORT" \
    '[{
      labels: {
        alertname: $alertname,
        cluster: $cluster,
        severity: $severity,
        drift_class: $drift_class,
        kind: $knd,
        outage_fallback: "true",
        bypass_orchestrator: "true",
        dedupe_key: $sig
      },
      annotations: {
        summary: $title,
        description: $msg,
        report: $report
      },
      startsAt: $ts,
      generatorURL: "https://github.com/Halildeu/platform-k8s-gitops"
    }]')

  # No-token-log guard — payload contains NO secret/token/credential
  echo "  [alertmanager-fallback] POST $ALERTMANAGER_FALLBACK_URL (dedupe_key=${sig:0:12}...)"

  # Retry with exponential backoff
  local attempt=1
  while [[ $attempt -le $MAX_RETRIES ]]; do
    local code
    code=$(curl -sf -o /dev/null -w '%{http_code}' --max-time 10 \
      -X POST -H "Content-Type: application/json" \
      -d "$payload" "$ALERTMANAGER_FALLBACK_URL" 2>/dev/null || echo "000")

    case "$code" in
      2*)
        echo "  [alertmanager-fallback] delivered ($code)"
        return 0
        ;;
      4*)
        # No retry on auth/validation errors
        echo "  [alertmanager-fallback] FAILED ($code) — non-transient (auth/validation), no retry"
        return 1
        ;;
      *)
        # 5xx/timeout/connection refused → retry
        local backoff=$((2 ** attempt))
        echo "  [alertmanager-fallback] attempt $attempt/$MAX_RETRIES failed ($code): sleeping ${backoff}s"
        sleep "$backoff"
        attempt=$((attempt + 1))
        ;;
    esac
  done

  echo "  [alertmanager-fallback] exhausted $MAX_RETRIES retries"
  return 1
}

# ------------------------------------------------------------
# Retry helper for gh API calls (rate limit + transient 5xx)
# ------------------------------------------------------------
gh_with_retry() {
  local attempt=1
  local stderr_capture
  stderr_capture=$(mktemp)
  while [[ $attempt -le $MAX_RETRIES ]]; do
    if "$@" 2>"$stderr_capture"; then
      rm -f "$stderr_capture"
      return 0
    fi

    local err
    err=$(cat "$stderr_capture")

    # Detect rate limit or transient errors
    if echo "$err" | grep -qE 'rate limit|429|503|502|504|timeout|connection refused'; then
      local backoff=$((2 ** attempt))
      echo "  [retry] attempt $attempt/$MAX_RETRIES failed (transient): sleeping ${backoff}s"
      sleep "$backoff"
      attempt=$((attempt + 1))
    else
      # Non-transient error — fail fast
      echo "  [retry] non-transient error, no retry: $(echo "$err" | head -3)"
      rm -f "$stderr_capture"
      return 1
    fi
  done

  echo "  [retry] exhausted $MAX_RETRIES retries"
  rm -f "$stderr_capture"
  return 1
}

# ------------------------------------------------------------
# Main processing
# ------------------------------------------------------------
ENV=$(jq -r '.environment' "$REPORT")
TS=$(jq -r '.timestamp' "$REPORT")
EXIT_CODE=$(jq -r '.exit_code' "$REPORT")

# Extract findings filtered to P1/P2 (skip OK + P3).
# Codex 019e44c8 should_fix #2 — P3 is documented as ::notice::-only
# (ADR-0023 PR-4 check_env_drift.sh). The alarm receiver MUST NOT open or
# update GitHub issues on a P3-only report; P3 is operator-visible via the
# GitHub Actions notice line and the JSON artifact.
findings_count=$(jq '[.findings[] | select(.class == "P1" or .class == "P2")] | length' "$REPORT")
[[ "$findings_count" -eq 0 ]] && {
  echo "[alarm_receiver] no P1/P2 findings — exit clean (P3 ignored by design)"
  exit 0
}

echo "[alarm_receiver] $findings_count P1/P2 findings to process from $REPORT"

# Pre-flight
preflight_ok=1
if ! preflight; then
  preflight_ok=0
  echo "[alarm_receiver] pre-flight failed — all alarms will go to webhook OR undelivered log"
fi

processed=0
delivered_gh=0
delivered_webhook=0
undelivered=0

# For each P1/P2 finding, generate a stable signature and open/update issue
# (P3 explicitly excluded; see Codex 019e44c8 should_fix #2 note above).
jq -c '.findings[] | select(.class == "P1" or .class == "P2")' "$REPORT" | while IFS= read -r finding; do
  cls=$(echo "$finding" | jq -r '.class')
  knd=$(echo "$finding" | jq -r '.kind')
  msg=$(echo "$finding" | jq -r '.message')
  details=$(echo "$finding" | jq -r '.details // empty')

  # Stable signature: env + class + kind + first 60 chars of message
  sig_msg=$(echo "$msg" | head -c 60)
  title="[drift-${cls}] ${ENV}/${knd}: ${sig_msg}"

  body="**Class**: \`$cls\`
**Environment**: \`$ENV\`
**Kind**: \`$knd\`
**First detected at**: \`$TS\`

## Message

$msg

## Details

\`\`\`
$details
\`\`\`

## Report artifact

\`\`\`
$REPORT
\`\`\`

## Operator playbook

| Class | Action |
|---|---|
| P1 | Operator action required within 10min — investigate cluster live state vs gitops yaml; reconciliation PR if break-glass was used |
| P2 | Warning — review within 1 day; may indicate stale promotion or quota tightening |
| P3 | Info — backlog grooming |

## Auto-deduplication

This issue auto-deduplicates on title match. Repeated drift detections add comments to this thread. Close the issue once cluster ↔ gitops parity restored.

---

🤖 Auto-opened by drift-detection alarm_receiver (Codex P0 follow-up + Sprint A Item 6 hardening).
"

  delivery_status="undelivered"

  if [[ "$preflight_ok" -eq 1 ]]; then
    # Try GitHub Issues first
    existing_issue=$(gh issue list --repo "$REPO" --state open --search "\"$title\" in:title" \
      --json number,title --jq '.[] | select(.title == "'"$title"'") | .number' 2>/dev/null | head -1)

    if [[ -n "$existing_issue" ]]; then
      echo "[alarm_receiver] [$cls] $knd — adding comment to existing issue #$existing_issue"
      if gh_with_retry gh issue comment "$existing_issue" --repo "$REPO" --body "Drift recurrence at $TS

Report: \`$REPORT\`
Details: $details"; then
        delivery_status="github"
      fi
    else
      echo "[alarm_receiver] [$cls] $knd — opening new issue: $title"
      if gh_with_retry gh issue create --repo "$REPO" \
        --title "$title" \
        --label "drift-detection,$cls" \
        --body "$body"; then
        delivery_status="github"
      fi
    fi
  fi

  # Webhook fallback if GH delivery failed (or skipped due to preflight)
  if [[ "$delivery_status" != "github" ]]; then
    if deliver_webhook "$cls" "$knd" "$title" "$msg"; then
      delivery_status="webhook"
    fi
  fi

  # Faz 23.2.D T1.4 PR-2 — D43 Alertmanager direct fallback (Codex 019e0dea iter-2 + iter-3).
  #
  # Iter-3 #2 absorb: parallel mode default — D43 amacı "orchestrator down iken
  # kritik alarm Alertmanager bypass kanalına da düşsün". Cascade-only davranış
  # GH/webhook başarılı olduğunda Alertmanager hiç tetiklenmez → bypass kanıt
  # üretilemez. Toggle açıkken P1 her durumda Alertmanager'a paralel gönderim.
  #
  # Mode (ALARM_FALLBACK_ALERTMANAGER_MODE):
  #   parallel (default)  — P1 + toggle → her zaman gönder (D43 bypass amacı)
  #   last_resort         — P1 + toggle + delivery_status=undelivered (eski cascade)
  if [[ "$cls" == "P1" ]] && [[ "$ALARM_FALLBACK_ALERTMANAGER" == "1" ]]; then
    should_send=0
    case "$ALARM_FALLBACK_ALERTMANAGER_MODE" in
      parallel) should_send=1 ;;
      last_resort)
        [[ "$delivery_status" == "undelivered" ]] && should_send=1
        ;;
      *)
        echo "  [alertmanager-fallback] WARN: unknown mode '$ALARM_FALLBACK_ALERTMANAGER_MODE'; defaulting to parallel" >&2
        should_send=1
        ;;
    esac

    if [[ "$should_send" -eq 1 ]]; then
      if deliver_alertmanager "$cls" "$knd" "$title" "$msg"; then
        # Codex iter-3 #2: parallel mode'da delivery_status'u override etme
        # (GH başarısı korunsun); only override when no prior success.
        [[ "$delivery_status" == "undelivered" ]] && delivery_status="alertmanager"
      fi
    fi
  fi

  # Persistent undelivered log if all delivery paths failed
  if [[ "$delivery_status" == "undelivered" ]]; then
    log_undelivered "$cls" "$knd" "$title" "$body" "all_delivery_paths_failed"
    echo "  [UNDELIVERED] persisted to $UNDELIVERED_LOG"
  fi
done

echo "[alarm_receiver] processed $findings_count findings; check undelivered log: $UNDELIVERED_LOG"
