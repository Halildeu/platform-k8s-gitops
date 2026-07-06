#!/usr/bin/env bash
# Read-only Faz 22.6 #548 A1 preflight.
#
# Checks the live test cluster and Denetim PC prerequisites for the strong
# device-key broker path. It prints status/presence only; it never prints secret
# values and never mutates Kubernetes, Vault, GitHub, or the Windows endpoint.

set -euo pipefail

SSH_TARGET="${SSH_TARGET:-staging-sw}"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
DENETIM_SSH_TARGET="${DENETIM_SSH_TARGET:-denetimpc@10.99.0.2}"
DENETIM_SSH_IDENTITY="${DENETIM_SSH_IDENTITY:-$HOME/.ssh/id_ed25519}"
DENETIM_CHECK="${DENETIM_CHECK:-true}"
DEVICE_KEY_OVERLAY="${DEVICE_KEY_OVERLAY:-kustomize/overlays/test/activation/endpoint-admin-remote-bridge-device-key}"
ENDPOINT_ADMIN_ESO_OVERLAY="${ENDPOINT_ADMIN_ESO_OVERLAY:-kustomize/overlays/test/eso/endpoint-admin}"
VAULT_TLS_DIR="${VAULT_TLS_DIR:-/home/halil/platform-stateful/test/vault/tls}"

if [ -z "${SSH_AUTH_SOCK:-}" ] && command -v launchctl >/dev/null 2>&1; then
  launchd_ssh_auth_sock="$(launchctl getenv SSH_AUTH_SOCK 2>/dev/null || true)"
  if [ -n "$launchd_ssh_auth_sock" ]; then
    export SSH_AUTH_SOCK="$launchd_ssh_auth_sock"
  fi
fi

ok() { printf 'PASS %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*"; }
FAILED=0
fail() {
  FAILED=1
  printf 'FAIL %s\n' "$*"
}

is_local_target() {
  case "$SSH_TARGET" in
    local|localhost|127.0.0.1)
      return 0
      ;;
  esac
  return 1
}

shell_quote() {
  local value="$1"
  printf "'%s'" "$(printf '%s' "$value" | sed "s/'/'\\\\''/g")"
}

remote_kubectl() {
  if is_local_target; then
    if [ "$#" -eq 1 ]; then
      bash -lc "kubectl --context $(shell_quote "$KUBE_CONTEXT") -n $(shell_quote "$KUBE_NAMESPACE") $1"
    else
      kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" "$@"
    fi
  else
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_TARGET" \
      "kubectl --context '$KUBE_CONTEXT' -n '$KUBE_NAMESPACE' $*"
  fi
}

remote_shell() {
  if is_local_target; then
    bash -lc "$*"
  else
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_TARGET" "$@"
  fi
}

denetim_ssh() {
  local identity_args=()
  local jump_args=()
  if [ -n "$DENETIM_SSH_IDENTITY" ]; then
    identity_args=(-i "$DENETIM_SSH_IDENTITY")
  fi
  if ! is_local_target; then
    jump_args=(-J "$SSH_TARGET")
  fi
  ssh -o BatchMode=yes -o ConnectTimeout=10 "${identity_args[@]}" "${jump_args[@]}" "$DENETIM_SSH_TARGET" "$@"
}

printf 'A1_PREFLIGHT_BEGIN context=%s namespace=%s ssh=%s denetim=%s\n' \
  "$KUBE_CONTEXT" "$KUBE_NAMESPACE" "$SSH_TARGET" "$DENETIM_SSH_TARGET"

if kubectl kustomize "$DEVICE_KEY_OVERLAY" >/tmp/faz22-6-a1-device-key-render.yaml; then
  ok "device-key overlay renders"
  if grep -q 'REMOTE_BRIDGE_DEVICE_TRUST_VERIFIER: DEVICE_KEY_ATTESTATION_REAL' /tmp/faz22-6-a1-device-key-render.yaml; then
    ok "rendered verifier=DEVICE_KEY_ATTESTATION_REAL"
  else
    fail "rendered verifier missing DEVICE_KEY_ATTESTATION_REAL"
  fi
  if grep -q 'nodePort: 31945' /tmp/faz22-6-a1-device-key-render.yaml; then
    ok "rendered dedicated nodePort=31945"
  else
    warn "rendered dedicated nodePort 31945 not found"
  fi
else
  fail "device-key overlay does not render"
fi

if remote_kubectl "get deploy endpoint-admin-service endpoint-admin-remote-bridge -o name" >/dev/null 2>&1; then
  ok "live primary service and shared broker are visible"
else
  fail "live primary service/shared broker lookup failed"
fi

if kubectl kustomize "$ENDPOINT_ADMIN_ESO_OVERLAY" >/tmp/faz22-6-a1-endpoint-admin-eso-render.yaml; then
  for key in ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID ENDPOINT_ADMIN_TPM_ATTEST_VAULT_SECRET_ID; do
    if grep -q "secretKey: $key" /tmp/faz22-6-a1-endpoint-admin-eso-render.yaml; then
      ok "rendered endpoint-admin ESO maps $key"
    else
      warn "rendered endpoint-admin ESO does not map $key"
    fi
  done
else
  warn "endpoint-admin ESO overlay does not render"
fi

service_tpm="$(remote_kubectl "get configmap endpoint-admin-service-config -o jsonpath='{.data.ENDPOINT_ADMIN_TPM_ATTEST_ENABLED}'" 2>/dev/null || true)"
service_root="$(remote_kubectl "get configmap endpoint-admin-service-config -o jsonpath='{.data.ENDPOINT_ADMIN_TPM_ATTEST_MANUFACTURER_ROOT_SHA256}'" 2>/dev/null || true)"
service_vault="$(remote_kubectl "get configmap endpoint-admin-service-config -o jsonpath='{.data.ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ENABLED}'" 2>/dev/null || true)"
shared_verifier="$(remote_kubectl "get configmap endpoint-admin-remote-bridge-config -o jsonpath='{.data.REMOTE_BRIDGE_DEVICE_TRUST_VERIFIER}'" 2>/dev/null || true)"
vault_https_port="$(remote_kubectl "get service vault -o jsonpath='{.spec.ports[?(@.port==8202)].port}'" 2>/dev/null || true)"

if [ "$service_tpm" = "true" ]; then
  ok "endpoint-admin-service tpm-attest enabled"
else
  fail "endpoint-admin-service tpm-attest not enabled"
fi
if [ -n "$service_root" ]; then
  ok "endpoint-admin-service manufacturer root pin present"
else
  fail "endpoint-admin-service manufacturer root pin missing"
fi
if [ "$service_vault" = "true" ]; then
  ok "endpoint-admin-service Vault PKI enabled"
else
  warn "endpoint-admin-service Vault PKI not enabled yet"
fi
if [ "$vault_https_port" = "8202" ]; then
  ok "Vault HTTPS service port 8202 visible"
else
  warn "Vault HTTPS service port 8202 not visible yet"
fi
if [ "$shared_verifier" = "MACHINE_CERT_ENROLLMENT" ]; then
  ok "shared broker remains MACHINE_CERT_ENROLLMENT"
else
  warn "shared broker verifier is $shared_verifier"
fi

vault_tls_files="$(remote_shell "if sudo -n test -r '$VAULT_TLS_DIR/ca.crt' && sudo -n test -r '$VAULT_TLS_DIR/tls.crt' && sudo -n test -r '$VAULT_TLS_DIR/tls.key'; then echo present; else echo missing; fi" 2>/dev/null || true)"
if [ "$vault_tls_files" = "present" ]; then
  ok "Vault TLS material present on $SSH_TARGET (values not printed)"
  printf -v vault_tls_dir_env '%q' "$VAULT_TLS_DIR"
  vault_status_cmd="VAULT_TLS_DIR=$vault_tls_dir_env
$(cat <<'EOS'
vault_status_pass=0
if command -v curl >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  if curl -fsS --connect-timeout 3 --max-time 10 --cacert "$VAULT_TLS_DIR/ca.crt" \
    "https://127.0.0.1:8302/v1/sys/seal-status" | jq -e '.sealed == false' >/dev/null; then
    vault_status_pass=1
  fi
fi
docker_cmd() {
  local docker_bin
  for docker_bin in docker /usr/bin/docker /usr/local/bin/docker /snap/bin/docker; do
    if command -v "$docker_bin" >/dev/null 2>&1 && "$docker_bin" version >/dev/null 2>&1; then
      "$docker_bin" "$@"
      return 0
    fi
    if command -v sudo >/dev/null 2>&1 && sudo -n "$docker_bin" version >/dev/null 2>&1; then
      sudo -n "$docker_bin" "$@"
      return 0
    fi
  done
  return 1
}
if [ "$vault_status_pass" = "1" ] || docker_cmd exec platform-vault-test sh -c 'VAULT_ADDR=https://127.0.0.1:8202 VAULT_CACERT=/vault/tls/ca.crt vault status -format=json >/dev/null'; then
  echo pass
else
  echo fail
fi
EOS
)"
  vault_https_health="$(remote_shell "$vault_status_cmd" 2>/dev/null || true)"
  if [ "$vault_https_health" = "pass" ]; then
    ok "Vault HTTPS 8202 CA-pinned status works"
  else
    warn "Vault HTTPS 8202 CA-pinned status not working yet"
  fi
else
  warn "Vault TLS material missing on $SSH_TARGET:$VAULT_TLS_DIR"
fi

for key in ENDPOINT_ADMIN_TPM_ATTEST_VAULT_ROLE_ID ENDPOINT_ADMIN_TPM_ATTEST_VAULT_SECRET_ID; do
  value_present="$(remote_kubectl "get secret endpoint-admin-service-secrets -o jsonpath='{.data.$key}'" 2>/dev/null || true)"
  if [ -n "$value_present" ]; then
    ok "live endpoint-admin-service-secrets has $key"
  else
    warn "live endpoint-admin-service-secrets missing $key"
  fi
done

for es in \
  endpoint-admin-remote-bridge-secrets-device-key \
  endpoint-admin-remote-bridge-tls-device-key \
  endpoint-admin-remote-bridge-signer-device-key; do
  ready="$(remote_kubectl "get externalsecret '$es' -o jsonpath='{.status.conditions[?(@.type==\"Ready\")].status}'" 2>/dev/null || true)"
  if [ "$ready" = "True" ]; then
    ok "ExternalSecret $es Ready=True"
  else
    warn "ExternalSecret $es not Ready=True (not applied or Vault path not seeded)"
  fi
done

if [ "$DENETIM_CHECK" != "true" ]; then
  warn "Denetim PC check skipped by DENETIM_CHECK=$DENETIM_CHECK"
elif denetim_ssh 'cmd /c hostname' >/tmp/faz22-6-a1-denetim-host.txt 2>/dev/null; then
  ok "Denetim PC reachable host=$(tr -d '\r\n' </tmp/faz22-6-a1-denetim-host.txt)"
  tpm_info="$(denetim_ssh \
    'powershell -NoProfile -Command "tpmtool getdeviceinformation"' 2>/dev/null || true)"
  printf '%s\n' "$tpm_info" | sed 's/^/INFO denetim-tpm /'
  ek_count="$(denetim_ssh \
    'powershell -NoProfile -Command "(Get-TpmEndorsementKeyInfo -Hash Sha256).ManufacturerCertificates.Count"' 2>/dev/null | tr -d '\r' || true)"
  if [ "${ek_count:-0}" -ge 1 ]; then
    ok "Denetim PC EK manufacturer cert count=$ek_count"
  else
    fail "Denetim PC EK manufacturer cert missing"
  fi
  agent_version="$(denetim_ssh \
    'powershell -NoProfile -Command "(Get-Item C:\Progra~1\EndpointAgent\endpoint-agent.exe).VersionInfo.ProductVersion"' 2>/dev/null | tr -d '\r' || true)"
  if [ -n "$agent_version" ]; then
    ok "Denetim PC EndpointAgent version=$agent_version"
  else
    warn "Denetim PC EndpointAgent version unavailable"
  fi
else
  fail "Denetim PC not reachable via $SSH_TARGET -> $DENETIM_SSH_TARGET"
fi

printf 'A1_PREFLIGHT_END\n'
exit "$FAILED"
