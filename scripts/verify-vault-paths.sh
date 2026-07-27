#!/usr/bin/env bash
# scripts/verify-vault-paths.sh
#
# ExternalSecret Vault path/property verify gate (Codex `019e6fb5` AGREE Yol
# C-prime — 3-layer verify gate). Inspired by check_env_drift.sh exit-code
# precedence + report-path override pattern.
#
# Two modes:
#
#   static — CI-friendly, no cluster/Vault access:
#     - Walks kustomize overlays + finds ExternalSecret manifests
#     - Extracts remoteRef.key + property + secretKey inventory via PyYAML
#     - Validates required remoteRef fields present + non-empty
#     - Output: JSON report + exit 0/1/2
#
#   live — aiserver cluster + Vault access via SSH:
#     - For each tracked ExternalSecret in --namespace:
#       1. kubectl get externalsecret <name> → status.conditions.Ready
#       2. kubectl get secret <target.name> → ownerRef + data.<key> length
#       3. SSH aiserver → vault kv get -field=<property> <path> | wc -c
#          (length-only check; value never round-trips through bash/stdout)
#     - Output: JSON report + exit 0/1/2
#
# Layer split (companion artifacts):
#   Layer 1 — this script `static` mode + .github/workflows/verify-vault-paths.yml
#   Layer 2 — this script `live` mode (manual/scheduled on aiserver)
#   Layer 3 — kustomize/base/monitoring/prometheusrule-alertmanager-bridge-gh-auth.yaml
#
# Exit codes (precedence high → low):
#   3   ERR — exec failure (kubectl/vault/ssh unreachable, python3/PyYAML missing)
#   1   FAIL — required field missing OR ESO Ready=False OR Secret absent OR token length < min
#   2   WARN — disabled/dormant manifest, informational
#   0   OK
#
# Security guardrails (HARD RULE — no token logging):
#   - Token VALUE never logged (vault `-field=` consumed via `wc -c` only)
#   - K8s Secret data decoded length via `base64 -d | wc -c`, never stdout
#   - SSH commands quote-escape Vault root token; unset after use
#
# Usage:
#   verify-vault-paths.sh static [--overlay test|prod|both] [--report PATH]
#   verify-vault-paths.sh live --context <ctx> --namespace <ns> \
#     [--externalsecret <name>] [--min-token-len <N>] \
#     [--vault-init-json PATH] [--vault-container <name>] [--report PATH]

set -uo pipefail

MODE="${1:-}"
[[ -n "$MODE" ]] && shift

OVERLAY="both"
NAMESPACE=""
CONTEXT=""
ESO_NAME=""
MIN_TOKEN_LEN="40"
VAULT_INIT_JSON="/srv/platform/secrets/backup-auth/vault-init-prod.json"
VAULT_CONTAINER="platform-vault-prod"
REPORT_PATH=""
SSH_HOST="${VAULT_PATHS_SSH_HOST:-aiadmin@aiserver}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  sed -n '1,/^set -uo pipefail$/{ /^#/p }' "${BASH_SOURCE[0]}"
  exit 2
}

# ---- Argument parsing -------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --overlay)
      [[ $# -ge 2 ]] || { echo "ERR: --overlay requires value" >&2; exit 3; }
      OVERLAY="$2"; shift 2 ;;
    --namespace)
      [[ $# -ge 2 ]] || { echo "ERR: --namespace requires value" >&2; exit 3; }
      NAMESPACE="$2"; shift 2 ;;
    --context)
      [[ $# -ge 2 ]] || { echo "ERR: --context requires value" >&2; exit 3; }
      CONTEXT="$2"; shift 2 ;;
    --externalsecret)
      [[ $# -ge 2 ]] || { echo "ERR: --externalsecret requires value" >&2; exit 3; }
      ESO_NAME="$2"; shift 2 ;;
    --min-token-len)
      [[ $# -ge 2 ]] || { echo "ERR: --min-token-len requires value" >&2; exit 3; }
      MIN_TOKEN_LEN="$2"; shift 2 ;;
    --vault-init-json)
      [[ $# -ge 2 ]] || { echo "ERR: --vault-init-json requires value" >&2; exit 3; }
      VAULT_INIT_JSON="$2"; shift 2 ;;
    --vault-container)
      [[ $# -ge 2 ]] || { echo "ERR: --vault-container requires value" >&2; exit 3; }
      VAULT_CONTAINER="$2"; shift 2 ;;
    --report)
      [[ $# -ge 2 ]] || { echo "ERR: --report requires value" >&2; exit 3; }
      REPORT_PATH="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "ERR: unknown arg: $1" >&2; usage ;;
  esac
done

# ---- Helpers ----------------------------------------------------------------
need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERR: missing required command: $1" >&2
    exit 3
  fi
}

python_yaml_check() {
  python3 -c 'import yaml' 2>/dev/null || {
    echo "ERR: python3 PyYAML missing (pip install pyyaml)" >&2
    exit 3
  }
}

write_report() {
  local body="$1"
  if [[ -n "$REPORT_PATH" ]]; then
    mkdir -p "$(dirname "$REPORT_PATH")"
    printf '%s\n' "$body" > "$REPORT_PATH"
    echo "::notice::report written → $REPORT_PATH"
  else
    printf '%s\n' "$body"
  fi
}

# ---- Static mode ------------------------------------------------------------
extract_eso_refs() {
  local manifest="$1"
  python3 - "$manifest" <<'PYEOF'
import json
import sys
import yaml

path = sys.argv[1]
out = []
try:
    with open(path) as f:
        for doc in yaml.safe_load_all(f):
            if not doc:
                continue
            # Codex `019e6fb5` iter-2 must_fix #4 absorb: kapsam genişledi
            # → JSON patch list (clustersecretstore-patch.yaml) gibi dict
            # olmayan docs skip.
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") != "ExternalSecret":
                continue
            name = doc.get("metadata", {}).get("name", "?")
            ns = doc.get("metadata", {}).get("namespace", "?")
            target_name = doc.get("spec", {}).get("target", {}).get("name", name)
            for d in doc.get("spec", {}).get("data", []):
                ref = d.get("remoteRef", {}) or {}
                key = ref.get("key") or ""
                prop = ref.get("property") or ""
                sk = d.get("secretKey") or ""
                missing = [f for f, v in (("key", key), ("property", prop), ("secretKey", sk)) if not v]
                out.append({
                    "manifest": path,
                    "namespace": ns,
                    "externalsecret": name,
                    "target_secret": target_name,
                    "vault_key": key,
                    "vault_property": prop,
                    "k8s_secret_key": sk,
                    "missing_fields": missing,
                    "status": "FAIL" if missing else "OK",
                })
except Exception as e:
    print(json.dumps({"manifest": path, "status": "ERR", "error": str(e)}), file=sys.stderr)
    sys.exit(3)

print(json.dumps(out))
PYEOF
}

mode_static() {
  python_yaml_check
  local overlays=()
  case "$OVERLAY" in
    test) overlays=("$REPO_ROOT/kustomize/overlays/test/eso") ;;
    prod) overlays=("$REPO_ROOT/kustomize/overlays/prod/eso") ;;
    both) overlays=("$REPO_ROOT/kustomize/overlays/test/eso" "$REPO_ROOT/kustomize/overlays/prod/eso") ;;
    *) echo "ERR: --overlay must be test|prod|both, got: $OVERLAY" >&2; exit 3 ;;
  esac

  local all_entries='[]'
  local fail_count=0
  local warn_count=0
  local ok_count=0
  local exit_code=0

  for dir in "${overlays[@]}"; do
    if [[ ! -d "$dir" ]]; then
      echo "::warning::overlay dir missing: $dir (treating as WARN)"
      warn_count=$((warn_count + 1))
      continue
    fi
    # Codex `019e6fb5` iter-2 must_fix #4 — kapsam: legacy bare-name files
    # (e.g. `endpoint-admin/externalsecret.yaml`) `externalsecret-*` glob'unun
    # dışında kalıyordu; `*.yaml` taraması + dormant exclude + kind-based
    # filter (Python extractor zaten kind!=ExternalSecret skip ediyor).
    while IFS= read -r -d '' manifest; do
      local entries
      if ! entries="$(extract_eso_refs "$manifest" 2>&1)"; then
        echo "::error::extract failed: $manifest" >&2
        echo "$entries" >&2
        exit_code=3
        continue
      fi
      # Skip files with no ExternalSecret docs (Python returned `[]`)
      if [[ "$(jq 'length' <<<"$entries" 2>/dev/null || echo 0)" == "0" ]]; then
        continue
      fi
      # Merge into aggregate
      all_entries="$(printf '%s\n%s' "$all_entries" "$entries" | jq -s 'add // []')"
    done < <(find "$dir" \
      -type f -name '*.yaml' \
      -not -name '*.disabled.*' \
      -not -name '*.template.*' \
      -not -name '*.example.*' \
      -print0)
  done

  ok_count=$(jq '[.[] | select(.status == "OK")] | length' <<<"$all_entries")
  fail_count=$(jq '[.[] | select(.status == "FAIL")] | length' <<<"$all_entries")
  if (( fail_count > 0 )); then exit_code=1; fi

  local report
  report="$(jq -n \
    --argjson entries "$all_entries" \
    --arg overlay "$OVERLAY" \
    --arg mode "static" \
    --argjson ok "$ok_count" \
    --argjson fail "$fail_count" \
    --argjson warn "$warn_count" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{
      mode: $mode,
      overlay: $overlay,
      timestamp: $ts,
      summary: { ok: $ok, fail: $fail, warn: $warn },
      entries: $entries
    }')"
  write_report "$report"

  if (( fail_count > 0 )); then
    echo "::error::$fail_count ExternalSecret remoteRef missing required fields"
    jq -r '.entries[] | select(.status == "FAIL") | "  - \(.manifest) :: \(.namespace)/\(.externalsecret) missing=\(.missing_fields | join(","))"' <<<"$report" >&2
  fi
  exit $exit_code
}

# ---- Live mode --------------------------------------------------------------
mode_live() {
  need_cmd kubectl
  need_cmd jq
  need_cmd ssh

  [[ -n "$CONTEXT" ]] || { echo "ERR: --context required for live mode" >&2; exit 3; }
  [[ -n "$NAMESPACE" ]] || { echo "ERR: --namespace required for live mode" >&2; exit 3; }

  # Resolve target list
  local -a targets=()
  if [[ -n "$ESO_NAME" ]]; then
    targets=("$ESO_NAME")
  else
    mapfile -t targets < <(
      kubectl --context "$CONTEXT" -n "$NAMESPACE" \
        get externalsecret -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null
    )
    if [[ ${#targets[@]} -eq 0 ]]; then
      echo "::warning::no ExternalSecret found in $CONTEXT/$NAMESPACE"
    fi
  fi

  local fail_count=0
  local ok_count=0
  local warn_count=0
  local checks_json='[]'

  for es in "${targets[@]}"; do
    local es_json
    if ! es_json="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get externalsecret "$es" -o json 2>/dev/null)"; then
      checks_json="$(jq --arg name "$es" '. + [{externalsecret: $name, status: "FAIL", reason: "kubectl_get_failed"}]' <<<"$checks_json")"
      fail_count=$((fail_count + 1))
      continue
    fi

    local ready vault_key vault_prop target_secret secret_key
    ready="$(jq -r '.status.conditions[] | select(.type=="Ready") | .status' <<<"$es_json" 2>/dev/null || echo "Unknown")"
    vault_key="$(jq -r '.spec.data[0].remoteRef.key // ""' <<<"$es_json")"
    vault_prop="$(jq -r '.spec.data[0].remoteRef.property // ""' <<<"$es_json")"
    target_secret="$(jq -r '.spec.target.name // .metadata.name' <<<"$es_json")"
    secret_key="$(jq -r '.spec.data[0].secretKey // ""' <<<"$es_json")"

    local k8s_secret_status="absent"
    local owner_ref="none"
    local token_len="0"
    local secret_json
    if secret_json="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret "$target_secret" -o json 2>/dev/null)"; then
      k8s_secret_status="present"
      owner_ref="$(jq -r '.metadata.ownerReferences[0] | "\(.kind)/\(.name)"' <<<"$secret_json" 2>/dev/null || echo "none")"
      if [[ -n "$secret_key" ]]; then
        # Decode length-only; no stdout leak of value
        token_len="$(jq -r --arg k "$secret_key" '.data[$k] // ""' <<<"$secret_json" | base64 -d 2>/dev/null | wc -c | tr -d ' ')"
      fi
    fi

    # Vault path/property check via SSH (length-only, never value)
    local vault_present="unknown"
    local vault_prop_len="0"
    if [[ -n "$vault_key" && -n "$vault_prop" ]]; then
      # Heredoc remote script avoids nested-quote escape gymnastics.
      # Backslash on $VAULT_ROOT_TOKEN/$VAULT_TOKEN defers expansion to remote;
      # $VAULT_INIT_JSON/$VAULT_CONTAINER/$vault_prop/$vault_key expand locally.
      local remote_script
      remote_script="$(cat <<EOSSH
VAULT_ROOT_TOKEN=\$(sudo -n jq -r .root_token '${VAULT_INIT_JSON}' 2>/dev/null)
if [ -z "\$VAULT_ROOT_TOKEN" ]; then echo 'TOKEN_LOAD_FAIL'; exit 3; fi
docker exec -e VAULT_TOKEN="\$VAULT_ROOT_TOKEN" '${VAULT_CONTAINER}' vault kv get -field='${vault_prop}' '${vault_key}' 2>/dev/null | wc -c | tr -d ' '
unset VAULT_ROOT_TOKEN
EOSSH
)"
      local vault_out
      # Codex `019e6fb5` iter-2 must_fix #2 — fail-closed: stderr suppressed so
      # `vault_out` only carries either the wc -c byte count, the literal
      # remote-emitted sentinel (TOKEN_LOAD_FAIL), or the local-emitted
      # sentinel (SSH_FAIL). Mixed stderr-noise output landing in default
      # branch and silently becoming `unknown` is what made probe-fail
      # acceptance-clean before this fix.
      vault_out="$(ssh -o BatchMode=yes "$SSH_HOST" "$remote_script" 2>/dev/null || echo "SSH_FAIL")"
      case "$vault_out" in
        SSH_FAIL|TOKEN_LOAD_FAIL)
          vault_present="error" ;;
        ""|0)
          vault_present="missing" ;;
        *)
          # numeric byte count
          if [[ "$vault_out" =~ ^[0-9]+$ ]]; then
            vault_present="present"
            vault_prop_len="$vault_out"
          else
            vault_present="unknown"
          fi ;;
      esac
    fi

    # Verdict per Codex `019e6fb5` acceptance + iter-2 absorb:
    #   - ownerRef enforcement (must_fix #1): stale/manual secret with valid
    #     length still FAILs unless ESO-owned (creationPolicy=Owner contract).
    #   - probe fail-closed (must_fix #2): unknown→FAIL; error→WARN with exit 2.
    local verdict="OK"
    local reason=""
    if [[ "$ready" != "True" ]]; then verdict="FAIL"; reason="eso_not_ready"; fi
    if [[ "$vault_present" == "missing" ]]; then verdict="FAIL"; reason="vault_property_missing"; fi
    if [[ "$vault_present" == "error" ]]; then verdict="WARN"; reason="vault_probe_unreachable"; fi
    if [[ "$vault_present" == "unknown" ]]; then verdict="FAIL"; reason="vault_probe_unknown"; fi
    if [[ "$k8s_secret_status" == "absent" ]]; then verdict="FAIL"; reason="${reason:-k8s_secret_absent}"; fi
    if [[ "$k8s_secret_status" == "present" && "$owner_ref" != "ExternalSecret/$es" ]]; then
      verdict="FAIL"; reason="${reason:-secret_not_eso_owned}"
    fi
    if [[ "$verdict" == "OK" && "$token_len" -lt "$MIN_TOKEN_LEN" ]]; then verdict="FAIL"; reason="token_length_below_min"; fi

    case "$verdict" in
      OK) ok_count=$((ok_count + 1)) ;;
      FAIL) fail_count=$((fail_count + 1)) ;;
      WARN) warn_count=$((warn_count + 1)) ;;
    esac

    checks_json="$(jq \
      --arg name "$es" \
      --arg ns "$NAMESPACE" \
      --arg ctx "$CONTEXT" \
      --arg ready "$ready" \
      --arg vk "$vault_key" \
      --arg vp "$vault_prop" \
      --arg sk "$secret_key" \
      --arg ts "$target_secret" \
      --arg ks "$k8s_secret_status" \
      --arg owner "$owner_ref" \
      --argjson tlen "$token_len" \
      --argjson vplen "$vault_prop_len" \
      --argjson mtok "$MIN_TOKEN_LEN" \
      --arg verdict "$verdict" \
      --arg reason "$reason" \
      '. + [{
        externalsecret: $name,
        namespace: $ns,
        context: $ctx,
        ready: $ready,
        vault_key: $vk,
        vault_property: $vp,
        vault_property_length: $vplen,
        k8s_secret_key: $sk,
        k8s_secret_target: $ts,
        k8s_secret_status: $ks,
        k8s_secret_owner: $owner,
        k8s_secret_token_length: $tlen,
        min_token_length: $mtok,
        verdict: $verdict,
        reason: $reason
      }]' <<<"$checks_json")"
  done

  # Codex `019e6fb5` iter-2 must_fix #2 — exit code precedence:
  #   FAIL → 1 (machine-enforced fail-closed)
  #   WARN → 2 (operational; not bridge acceptance pass)
  local exit_code=0
  if (( fail_count > 0 )); then
    exit_code=1
  elif (( warn_count > 0 )); then
    exit_code=2
  fi

  local report
  report="$(jq -n \
    --argjson checks "$checks_json" \
    --arg ctx "$CONTEXT" \
    --arg ns "$NAMESPACE" \
    --arg mode "live" \
    --argjson ok "$ok_count" \
    --argjson fail "$fail_count" \
    --argjson warn "$warn_count" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{
      mode: $mode,
      context: $ctx,
      namespace: $ns,
      timestamp: $ts,
      summary: { ok: $ok, fail: $fail, warn: $warn },
      checks: $checks
    }')"
  write_report "$report"

  if (( fail_count > 0 )); then
    echo "::error::$fail_count ExternalSecret(s) failed live preflight"
    jq -r '.checks[] | select(.verdict == "FAIL") | "  - \(.context):\(.namespace)/\(.externalsecret) reason=\(.reason) ready=\(.ready) k8s=\(.k8s_secret_status) token_len=\(.k8s_secret_token_length)"' <<<"$report" >&2
  fi
  exit $exit_code
}

# ---- Dispatch ---------------------------------------------------------------
case "$MODE" in
  static) mode_static ;;
  live)   mode_live ;;
  ""|-h|--help) usage ;;
  *) echo "ERR: unknown mode: $MODE (use static|live)" >&2; usage ;;
esac
