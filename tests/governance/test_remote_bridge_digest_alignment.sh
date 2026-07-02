#!/usr/bin/env bash
# Issue #2067 (Codex 019f0733 verdict C): remote-bridge expected digest is a
# SINGLE source of truth = the rendered overlay. This tests the shared lib, the
# PR-time alignment guard, and the audit's derive (incl. the env-override escape
# hatch being fail-closed).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIB="$ROOT/scripts/governance/lib-remote-bridge-digest.sh"
GUARD="$ROOT/scripts/governance/check-remote-bridge-digest-alignment.sh"
AUDIT="$ROOT/scripts/faz22-remote-ops/faz22-6-completion-audit.sh"

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/rb-digest-align.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

A="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
B="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

# --- Fake kustomize: emits a controlled endpoint-admin image per overlay path. ---
fake_bin="$tmp_dir/bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/kustomize" <<'SH'
#!/usr/bin/env bash
# fake `kustomize build <overlay>`
set -euo pipefail
overlay="${2:-}"
case "$overlay" in
  *activation/endpoint-admin-remote-bridge-device-key*) d="$FAKE_DEVICE_KEY_DIGEST" ;;
  *activation/endpoint-admin-remote-bridge*) d="$FAKE_BRIDGE_DIGEST" ;;
  *) d="$FAKE_PRIMARY_DIGEST" ;;
esac
cat <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: x
spec:
  template:
    spec:
      containers:
        - name: endpoint-admin-service
          image: ghcr.io/halildeu/platform-backend-endpoint-admin-service@${d}
YAML
SH
chmod +x "$fake_bin/kustomize"

run_guard_fake() { # run_guard_fake <primary> <bridge> <device-key>
  PATH="$fake_bin:$PATH" FAKE_PRIMARY_DIGEST="$1" FAKE_BRIDGE_DIGEST="$2" FAKE_DEVICE_KEY_DIGEST="$3" bash "$GUARD"
}

# 1) Guard PASS against the REAL overlays (they are aligned on main).
out="$(bash "$GUARD")"
printf '%s\n' "$out" | grep -q '^REMOTE_BRIDGE_DIGEST_ALIGNMENT=pass digest=ghcr.io/halildeu/platform-backend-endpoint-admin-service@sha256:' \
  || { echo "FAIL: real overlays should be aligned: $out"; exit 1; }

# 2) Guard PASS with fake equal digests.
out="$(run_guard_fake "$A" "$A" "$A")"
printf '%s\n' "$out" | grep -q "^REMOTE_BRIDGE_DIGEST_ALIGNMENT=pass digest=.*@${A}\$" \
  || { echo "FAIL: equal fake digests should pass: $out"; exit 1; }

# 3) Guard FAIL on drift (primary != bridge).
set +e
out="$(run_guard_fake "$A" "$B" "$A")"; rc=$?
set -e
[ "$rc" != 0 ] || { echo "FAIL: drift should exit non-zero"; exit 1; }
printf '%s\n' "$out" | grep -q '^REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=digest-drift' \
  || { echo "FAIL: drift reason: $out"; exit 1; }
printf '%s\n' "$out" | grep -q 'device-key' \
  || { echo "FAIL: drift output should include the device-key overlay: $out"; exit 1; }

# 3b) Guard also FAILS when only the #548 device-key broker is stale.
set +e
out="$(run_guard_fake "$A" "$A" "$B")"; rc=$?
set -e
[ "$rc" != 0 ] || { echo "FAIL: device-key drift should exit non-zero"; exit 1; }
printf '%s\n' "$out" | grep -q '^REMOTE_BRIDGE_DIGEST_ALIGNMENT=fail reason=digest-drift' \
  || { echo "FAIL: device-key drift reason: $out"; exit 1; }

# 4) Lib unit: no render tool -> rbd_overlay_digest returns 3; drift -> rbd_expected_digest returns 4.
cat >"$tmp_dir/lib-unit.sh" <<UNIT
#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=/dev/null
source "$LIB"
rbd_render_cmd() { return 1; }                 # simulate no kustomize/kubectl
rbd_overlay_digest "x" >/dev/null 2>&1; echo "no_tool_rc=\$?"
rbd_render_cmd() { printf 'kustomize build'; } # restore tool
rbd_overlay_digest() { case "\$1" in *bridge*) echo "ghcr.io/x@${A}";; *) echo "ghcr.io/x@${B}";; esac; }
rbd_expected_digest >/dev/null 2>&1; echo "drift_rc=\$?"
UNIT
unit_out="$(bash "$tmp_dir/lib-unit.sh")"
printf '%s\n' "$unit_out" | grep -q '^no_tool_rc=3$' || { echo "FAIL: no-tool rc!=3: $unit_out"; exit 1; }
printf '%s\n' "$unit_out" | grep -q '^drift_rc=4$' || { echo "FAIL: drift rc!=4: $unit_out"; exit 1; }

# 5) Audit derive: an env-set EXPECTED_REMOTE_BRIDGE_DIGEST WITHOUT the explicit
#    override flag is fail-closed (must NOT silently override the rendered source).
cat >"$tmp_dir/audit-override.sh" <<AUD
#!/usr/bin/env bash
set -uo pipefail
export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$AUDIT"
EXPECTED_REMOTE_BRIDGE_DIGEST="${A}" REMOTE_BRIDGE_KUBECTL_MODE=local-kubectl SSH_TARGET=local \
  check_remote_bridge
echo "rc=\$?"
AUD
set +e
ovr_out="$(bash "$tmp_dir/audit-override.sh" 2>&1)"
set -e
printf '%s\n' "$ovr_out" | grep -q 'reason=expected-digest-env-set-without-ALLOW_EXPECTED_DIGEST_OVERRIDE' \
  || { echo "FAIL: env-set EXPECTED without ALLOW must be rejected: $ovr_out"; exit 1; }

# 6) evaluate_remote_bridge_live: exact per-object parse (no grep-count masking).
IMG="ghcr.io/halildeu/platform-backend-endpoint-admin-service"
mk_deploys() {
  local img="$1" bridge="${2:-$1}" device_key="${3:-$1}"
  jq -nc --arg img "$img" --arg bridge "$bridge" --arg device_key "$device_key" '{items:[
  {metadata:{name:"endpoint-admin-service"},spec:{template:{spec:{containers:[{image:$img}]}}}},
  {metadata:{name:"endpoint-admin-remote-bridge"},spec:{template:{spec:{containers:[{image:$bridge}]}}}},
  {metadata:{name:"endpoint-admin-remote-bridge-device-key"},spec:{template:{spec:{containers:[{image:$device_key}]}}}}]}'
}
mk_pod() { jq -nc --arg n "$1" --arg img "$2" '{metadata:{name:($n+"-x"),deletionTimestamp:null,labels:{"app.kubernetes.io/name":$n}},status:{phase:"Running",containerStatuses:[{ready:true,imageID:$img}]}}'; }
mk_es() { jq -nc '{items:[
  {metadata:{name:"endpoint-admin-remote-bridge-secrets"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}},
  {metadata:{name:"endpoint-admin-remote-bridge-signer"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}},
  {metadata:{name:"endpoint-admin-remote-bridge-tls"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}},
  {metadata:{name:"endpoint-admin-remote-bridge-secrets-device-key"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}},
  {metadata:{name:"endpoint-admin-remote-bridge-signer-device-key"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}},
  {metadata:{name:"endpoint-admin-remote-bridge-tls-device-key"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}}]}'; }
mk_ingress() { jq -nc --arg svc "$1" '{spec:{rules:[{host:"remote-bridge-mtls.testai.acik.com",http:{paths:[{backend:{service:{name:$svc}}}]}}]}}'; }

export F22_6_COMPLETION_AUDIT_SOURCE_ONLY=1
# shellcheck source=/dev/null
source "$AUDIT"

deploys_ok="$(mk_deploys "${IMG}@${A}")"
pods_ok="$(jq -nc --argjson a "$(mk_pod endpoint-admin-service "${IMG}@${A}")" --argjson b "$(mk_pod endpoint-admin-remote-bridge "${IMG}@${A}")" '{items:[$a,$b]}')"
es_ok="$(mk_es)"
ingress_base="$(mk_ingress endpoint-admin-remote-bridge)"
ingress_device_key="$(mk_ingress endpoint-admin-remote-bridge-device-key)"

evaluate_remote_bridge_live "$A" "$deploys_ok" "$pods_ok" "$es_ok" "$ingress_base" >/dev/null \
  || { echo "FAIL: aligned fixtures should evaluate ok"; exit 1; }

# When the public SNI Ingress points at the #548 device-key broker, the inactive
# enrollment-backed broker may still be on an older digest without blocking the
# active remote-bridge evidence.
deploys_device_key_active="$(mk_deploys "${IMG}@${A}" "${IMG}@${B}" "${IMG}@${A}")"
pods_device_key_active="$(jq -nc \
  --argjson a "$(mk_pod endpoint-admin-service "${IMG}@${A}")" \
  --argjson b "$(mk_pod endpoint-admin-remote-bridge "${IMG}@${B}")" \
  --argjson c "$(mk_pod endpoint-admin-remote-bridge-device-key "${IMG}@${A}")" '{items:[$a,$b,$c]}')"
evaluate_remote_bridge_live "$A" "$deploys_device_key_active" "$pods_device_key_active" "$es_ok" "$ingress_device_key" >/dev/null \
  || { echo "FAIL: active device-key SNI should ignore inactive stale enrollment-backed broker"; exit 1; }

# A 2nd endpoint-admin-service pod on a WRONG digest must block (grep-count would mask it).
pods_drift="$(jq -nc \
  --argjson a "$(mk_pod endpoint-admin-service "${IMG}@${A}")" \
  --argjson b "$(mk_pod endpoint-admin-remote-bridge "${IMG}@${A}")" \
  --argjson c "$(mk_pod endpoint-admin-service "${IMG}@${B}")" '{items:[$a,$b,$c]}')"
set +e
evaluate_remote_bridge_live "$A" "$deploys_ok" "$pods_drift" "$es_ok" "$ingress_base" >"$tmp_dir/eval-drift.out"; erc=$?
set -e
[ "$erc" != 0 ] || { echo "FAIL: wrong-digest pod should block (count-masking guard)"; exit 1; }
grep -q 'pods:endpoint-admin-service' "$tmp_dir/eval-drift.out" || { echo "FAIL: drift reason: $(cat "$tmp_dir/eval-drift.out")"; exit 1; }

# A missing ExternalSecret must block.
es_missing="$(jq -nc '{items:[{metadata:{name:"endpoint-admin-remote-bridge-secrets"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}}]}')"
set +e
evaluate_remote_bridge_live "$A" "$deploys_ok" "$pods_ok" "$es_missing" "$ingress_base" >"$tmp_dir/eval-es.out"; erc=$?
set -e
[ "$erc" != 0 ] || { echo "FAIL: missing ExternalSecret should block"; exit 1; }
grep -q 'externalsecrets' "$tmp_dir/eval-es.out" || { echo "FAIL: es reason: $(cat "$tmp_dir/eval-es.out")"; exit 1; }

# All 3 ES present but one has NO Ready condition must block (Codex 019f0733:
# the old all(select-stream) silently skipped a missing-condition item).
es_no_ready="$(jq -nc '{items:[
  {metadata:{name:"endpoint-admin-remote-bridge-secrets"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}},
  {metadata:{name:"endpoint-admin-remote-bridge-signer"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}},
  {metadata:{name:"endpoint-admin-remote-bridge-tls"},status:{conditions:[]}}]}')"
set +e
evaluate_remote_bridge_live "$A" "$deploys_ok" "$pods_ok" "$es_no_ready" "$ingress_base" >"$tmp_dir/eval-es2.out"; erc=$?
set -e
[ "$erc" != 0 ] || { echo "FAIL: ES present but missing Ready condition should block"; exit 1; }
grep -q 'externalsecrets' "$tmp_dir/eval-es2.out" || { echo "FAIL: es-no-ready reason: $(cat "$tmp_dir/eval-es2.out")"; exit 1; }

# 7) env-override WITH ALLOW: even a fully-matching live state is DIAGNOSTIC only,
#    never a canonical pass (Codex 019f0733 P1). Fake kubectl emits matching JSON.
fake2="$tmp_dir/bin2"
mkdir -p "$fake2"
cat >"$fake2/kubectl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
args="$*"
img="ghcr.io/halildeu/platform-backend-endpoint-admin-service@${FAKE_DIGEST}"
case "$args" in
  *"get deploy"*) jq -nc --arg img "$img" '{items:[{metadata:{name:"endpoint-admin-service"},spec:{template:{spec:{containers:[{image:$img}]}}}},{metadata:{name:"endpoint-admin-remote-bridge"},spec:{template:{spec:{containers:[{image:$img}]}}}}]}' ;;
  *"get pod"*) jq -nc --arg img "$img" '{items:[{metadata:{name:"p1",deletionTimestamp:null,labels:{"app.kubernetes.io/name":"endpoint-admin-service"}},status:{phase:"Running",containerStatuses:[{ready:true,imageID:$img}]}},{metadata:{name:"p2",deletionTimestamp:null,labels:{"app.kubernetes.io/name":"endpoint-admin-remote-bridge"}},status:{phase:"Running",containerStatuses:[{ready:true,imageID:$img}]}}]}' ;;
  *"get externalsecret"*) jq -nc '{items:[{metadata:{name:"endpoint-admin-remote-bridge-secrets"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}},{metadata:{name:"endpoint-admin-remote-bridge-signer"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}},{metadata:{name:"endpoint-admin-remote-bridge-tls"},status:{conditions:[{type:"Ready",status:"True",reason:"SecretSynced"}]}}]}' ;;
  *"get ingress"*) jq -nc '{spec:{rules:[{host:"remote-bridge-mtls.testai.acik.com",http:{paths:[{backend:{service:{name:"endpoint-admin-remote-bridge"}}}]}}]}}' ;;
  *) echo '{}' ;;
esac
SH
chmod +x "$fake2/kubectl"
set +e
ovr2_out="$(PATH="$fake2:$PATH" FAKE_DIGEST="$A" ALLOW_EXPECTED_DIGEST_OVERRIDE=1 EXPECTED_REMOTE_BRIDGE_DIGEST="$A" \
  REMOTE_BRIDGE_KUBECTL_MODE=local-kubectl SSH_TARGET=local check_remote_bridge)"
ovr2_rc=$?
set -e
[ "$ovr2_rc" != 0 ] || { echo "FAIL: env_override must never be a canonical pass (rc must be non-zero): $ovr2_out"; exit 1; }
printf '%s\n' "$ovr2_out" | grep -q '^REMOTE_BRIDGE_LIVE=diagnostic_pass .*expected_source=env_override' \
  || { echo "FAIL: env_override matching live should be diagnostic_pass: $ovr2_out"; exit 1; }
if printf '%s\n' "$ovr2_out" | grep -q '^REMOTE_BRIDGE_LIVE=pass '; then
  echo "FAIL: env_override must NOT emit a canonical REMOTE_BRIDGE_LIVE=pass: $ovr2_out"; exit 1
fi

# 8) apply-workflow must NOT pin a stale literal digest default (#2067 de-pin).
APPLY_WF="$ROOT/.github/workflows/apply-remote-bridge-activation.yml"
if grep -qE "default: *'sha256:" "$APPLY_WF"; then
  echo "FAIL: apply workflow must not pin a sha256 expected_digest default (de-pinned #2067)"; exit 1
fi

echo "remote-bridge-digest-alignment-ok"
