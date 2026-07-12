#!/usr/bin/env bash
# Shared canonical parser for Faz 22.6 #1580 VIEW_ONLY broker frame-flow evidence.
#
# The broker (endpoint-admin remote-bridge) logs each received VIEW_ONLY frame as a
# real production line, e.g.:
#   view-only frame: session=<sid> stream=<op> seq=0 bytes=90654 type=image/png disposition=DROPPED_NO_VIEWER ts=<...>
#
# The prior finalizer/smoke greps looked for synthetic tokens (event=SCREEN_VIEW,
# kind=VIEW_ONLY, ...) that the broker never emits — a producer/consumer log-contract
# mismatch that failed even when real 90 KB PNG frames flowed. Codex 019f559d S2/S3:
# parse the real format, stage-aware, disposition-allowlisted; the SAME helper backs
# both the smoke's broker_signals_json and the finalizer (one contract, no drift).
#
# Two stages (Codex S1: #1580 requires broker-RECEIVED, not viewer-DELIVERED):
#   received  -> DELIVERED or DROPPED_NO_VIEWER  (broker got a real, non-inert frame)
#   delivered -> DELIVERED only                  (viewer actually observed; NOT #1580)
# Unknown/error/policy-drop dispositions FAIL both stages (fail-closed).

# _vof_matching_seq_count <broker_log> <session_id> <disposition_regex>
# Emits the count of DISTINCT seq values on lines that are real, non-inert VIEW_ONLY
# frames for this session with an allowed disposition. >=2 distinct seq == proven flow.
_vof_matching_seq_count() {
  local broker_log="$1" session_id="$2" disp_re="$3" n
  [ -f "$broker_log" ] || { printf '0'; return; }
  n="$(grep -F "$session_id" "$broker_log" 2>/dev/null \
    | grep -E 'view-only frame:' \
    | grep -E "session=${session_id}([[:space:]]|$)" \
    | grep -E 'bytes=[1-9][0-9]*([[:space:]]|$)' \
    | grep -E 'type=image/png([[:space:]]|$)' \
    | grep -E "disposition=(${disp_re})([[:space:]]|$)" \
    | grep -oE 'seq=[0-9]+' \
    | sort -u \
    | wc -l)"
  # wc -l may pad with spaces; arithmetic-normalize to a bare integer.
  printf '%s' "$(( ${n:-0} + 0 ))"
}

# broker_log_has_received_frame_flow <broker_log> <session_id>
# TRUE (0) iff the broker received >=2 real, non-inert PNG VIEW_ONLY frames for the
# session (disposition DELIVERED or DROPPED_NO_VIEWER). This is the #1580 gate.
broker_log_has_received_frame_flow() {
  local n
  n="$(_vof_matching_seq_count "$1" "$2" 'DELIVERED|DROPPED_NO_VIEWER')"
  [ "${n:-0}" -ge 2 ]
}

# broker_log_has_delivered_frame_flow <broker_log> <session_id>
# TRUE (0) iff >=2 frames were actually DELIVERED to a viewer. NOT required by #1580
# (viewer relay is gated #2183); exposed so a future viewer-delivered claim is precise.
broker_log_has_delivered_frame_flow() {
  local n
  n="$(_vof_matching_seq_count "$1" "$2" 'DELIVERED')"
  [ "${n:-0}" -ge 2 ]
}
