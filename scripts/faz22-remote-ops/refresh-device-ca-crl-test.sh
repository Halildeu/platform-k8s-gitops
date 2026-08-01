#!/usr/bin/env bash
# Copy the signed public Vault PKI CRL into the dedicated TEST broker secret,
# reconcile ESO, and restart the startup-time CRL consumer only when changed.

set -euo pipefail
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
EXTERNAL_SECRET="${EXTERNAL_SECRET:-endpoint-admin-remote-bridge-secrets-device-key}"
KUBERNETES_SECRET="${KUBERNETES_SECRET:-endpoint-admin-remote-bridge-secrets-device-key}"
BROKER_DEPLOYMENT="${BROKER_DEPLOYMENT:-endpoint-admin-remote-bridge-device-key}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_KV_PATH="${VAULT_KV_PATH:-kv/platform/endpoint-admin-remote-bridge-device-key}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
PUBLIC_PKI_BASE_URL="${PUBLIC_PKI_BASE_URL:-http://127.0.0.1:8201/v1/pki_int}"
RECEIPT_PATH="${RECEIPT_PATH:-}"

fail() {
  echo "device-ca-crl-refresh: $1" >&2
  exit 1
}

for binding in \
  "$KUBE_CONTEXT=k3d-test" \
  "$KUBE_NAMESPACE=platform-test" \
  "$EXTERNAL_SECRET=endpoint-admin-remote-bridge-secrets-device-key" \
  "$KUBERNETES_SECRET=endpoint-admin-remote-bridge-secrets-device-key" \
  "$BROKER_DEPLOYMENT=endpoint-admin-remote-bridge-device-key" \
  "$VAULT_CONTAINER=platform-vault-test" \
  "$VAULT_KV_PATH=kv/platform/endpoint-admin-remote-bridge-device-key" \
  "$VAULT_INIT_FILE=/srv/platform/secrets/backup-auth/vault-init-test.json" \
  "$PUBLIC_PKI_BASE_URL=http://127.0.0.1:8201/v1/pki_int"; do
  [[ "${binding%%=*}" == "${binding#*=}" ]] \
    || fail "test-only target override refused: ${binding%%=*}"
done

for command_name in awk base64 curl date docker jq kubectl mktemp openssl sed seq sha256sum sleep stat; do
  command -v "$command_name" >/dev/null 2>&1 \
    || fail "required command missing: $command_name"
done

[[ -r "$VAULT_INIT_FILE" && -f "$VAULT_INIT_FILE" && ! -L "$VAULT_INIT_FILE" ]] \
  || fail "Vault init file must be a readable regular non-symlink"
init_mode="$(stat -c '%a' "$VAULT_INIT_FILE")"
[[ "$init_mode" == "600" || "$init_mode" == "640" ]] \
  || fail "Vault init file mode must be 0600 or 0640"
docker inspect "$VAULT_CONTAINER" >/dev/null 2>&1 \
  || fail "TEST Vault container is unavailable"

work_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/faz22-device-ca-crl-refresh.XXXXXX")"
chmod 700 "$work_dir"
cleanup() {
  unset vault_token
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

source_ca="$work_dir/source-ca.pem"
source_crl="$work_dir/source.crl.pem"
current_crl="$work_dir/current.crl.pem"
current_ca="$work_dir/current-ca.pem"

curl --fail --silent --show-error --connect-timeout 3 --max-time 15 \
  "$PUBLIC_PKI_BASE_URL/ca/pem" >"$source_ca" \
  || fail "public Vault PKI CA read failed"
curl --fail --silent --show-error --connect-timeout 3 --max-time 15 \
  "$PUBLIC_PKI_BASE_URL/crl/pem" >"$source_crl" \
  || fail "public Vault PKI CRL read failed"
[[ -s "$source_ca" && -s "$source_crl" ]] \
  || fail "public Vault PKI CA or CRL is empty"
(( $(stat -c '%s' "$source_ca") <= 65536 )) \
  || fail "public Vault PKI CA exceeds 64 KiB"
(( $(stat -c '%s' "$source_crl") <= 8388608 )) \
  || fail "public Vault PKI CRL exceeds 8 MiB"
openssl crl -in "$source_crl" -noout -verify -CAfile "$source_ca" >/dev/null 2>&1 \
  || fail "public Vault PKI CRL signature verification failed"
next_update="$(openssl crl -in "$source_crl" -noout -nextupdate | sed 's/^nextUpdate=//')"
next_update_epoch="$(date -u -d "$next_update" +%s 2>/dev/null)" \
  || fail "public Vault PKI CRL nextUpdate cannot be parsed"
(( next_update_epoch - $(date -u +%s) >= 86400 )) \
  || fail "public Vault PKI CRL has less than 24 hours remaining"

kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
  get secret "$KUBERNETES_SECRET" \
  -o jsonpath='{.data.ENDPOINT_ADMIN_REMOTE_ACCESS_CERT_TRUST_TRUST_ANCHOR_PEM}' \
  | base64 --decode >"$current_ca" \
  || fail "current Kubernetes trust anchor read failed"
kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
  get secret "$KUBERNETES_SECRET" \
  -o jsonpath='{.data.ENDPOINT_ADMIN_REMOTE_ACCESS_CERT_TRUST_CRL_PEM}' \
  | base64 --decode >"$current_crl" \
  || fail "current Kubernetes CRL read failed"
[[ -s "$current_ca" && -s "$current_crl" ]] \
  || fail "current Kubernetes trust anchor or CRL is empty"
current_ca_fingerprint="$(openssl x509 -in "$current_ca" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')" \
  || fail "current Kubernetes trust anchor is invalid"
source_ca_fingerprint="$(openssl x509 -in "$source_ca" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')" \
  || fail "public Vault PKI CA is invalid"
[[ "$current_ca_fingerprint" == "$source_ca_fingerprint" ]] \
  || fail "public Vault PKI CA differs from the broker trust anchor"

source_crl_sha256="$(sha256sum "$source_crl" | awk '{print $1}')"
current_crl_sha256="$(sha256sum "$current_crl" | awk '{print $1}')"
changed=false

if [[ "$source_crl_sha256" != "$current_crl_sha256" ]]; then
  vault_token="$(jq -er '.root_token | select(type == "string" and length >= 20)' "$VAULT_INIT_FILE")" \
    || fail "TEST Vault root token cannot be read"

  {
    printf '%s\n' "$vault_token"
    cat "$source_crl"
  } | docker exec -i "$VAULT_CONTAINER" sh -c '
    set -eu
    IFS= read -r VAULT_TOKEN
    export VAULT_TOKEN
    umask 077
    crl_file=$(mktemp /tmp/device-ca-crl.XXXXXX)
    trap '\''rm -f -- "$crl_file"'\'' EXIT
    cat >"$crl_file"
    vault kv patch kv/platform/endpoint-admin-remote-bridge-device-key \
      device_crl_pem=@"$crl_file" >/dev/null
  ' || fail "Vault CRL patch failed"
  unset vault_token

  force_sync_epoch="$(date -u +%s)"
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
    annotate externalsecret "$EXTERNAL_SECRET" \
    "force-sync=$force_sync_epoch" --overwrite >/dev/null \
    || fail "ExternalSecret force-sync failed"

  for _ in $(seq 1 30); do
    synced_crl_sha256="$({
      kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
        get secret "$KUBERNETES_SECRET" \
        -o jsonpath='{.data.ENDPOINT_ADMIN_REMOTE_ACCESS_CERT_TRUST_CRL_PEM}' \
        | base64 --decode
    } | sha256sum | awk '{print $1}')" || true
    [[ "$synced_crl_sha256" == "$source_crl_sha256" ]] && break
    sleep 2
  done
  [[ "${synced_crl_sha256:-}" == "$source_crl_sha256" ]] \
    || fail "ESO did not publish the refreshed CRL"

  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
    rollout restart "deployment/$BROKER_DEPLOYMENT" >/dev/null \
    || fail "broker rollout restart failed"
  kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
    rollout status "deployment/$BROKER_DEPLOYMENT" --timeout=180s \
    || fail "broker rollout did not become Ready"
  changed=true
fi

CRL_MIN_VALIDITY_SECONDS=86400 \
  "$SCRIPT_DIR/verify-device-ca-crl-freshness.sh"

if [[ -n "$RECEIPT_PATH" ]]; then
  receipt_dir="$(dirname "$RECEIPT_PATH")"
  mkdir -p "$receipt_dir"
  chmod 700 "$receipt_dir"
  jq -nS \
    --arg schemaVersion "faz22.6.deviceCaCrlRefresh.v1" \
    --arg observedAt "$(date -u +%FT%TZ)" \
    --arg changed "$changed" \
    --arg caSha256 "sha256:$(sha256sum "$source_ca" | awk '{print $1}')" \
    --arg crlSha256 "sha256:$source_crl_sha256" \
    --arg nextUpdate "$(date -u -d "@$next_update_epoch" +%FT%TZ)" \
    --arg deployment "$BROKER_DEPLOYMENT" \
    '{
      schemaVersion:$schemaVersion,
      observedAt:$observedAt,
      changed:($changed == "true"),
      publicCaSha256:$caSha256,
      publicCrlSha256:$crlSha256,
      nextUpdate:$nextUpdate,
      deployment:$deployment,
      secretMaterialIncluded:false
    }' >"$RECEIPT_PATH"
  chmod 600 "$RECEIPT_PATH"
fi

printf 'device-ca-crl-refresh: PASS changed=%s crlSha256=%s nextUpdate=%s\n' \
  "$changed" "$source_crl_sha256" "$(date -u -d "@$next_update_epoch" +%FT%TZ)"
