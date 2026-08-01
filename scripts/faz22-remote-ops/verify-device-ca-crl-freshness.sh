#!/usr/bin/env bash
# Fail closed before attended approval when the device-CA CRL consumed by the
# device-key broker is stale, differs from the public Vault PKI CRL, or has not
# been followed by a broker restart.

set -euo pipefail

KUBE_CONTEXT="${KUBE_CONTEXT:-k3d-test}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-platform-test}"
EXTERNAL_SECRET="${EXTERNAL_SECRET:-endpoint-admin-remote-bridge-secrets-device-key}"
KUBERNETES_SECRET="${KUBERNETES_SECRET:-endpoint-admin-remote-bridge-secrets-device-key}"
BROKER_DEPLOYMENT="${BROKER_DEPLOYMENT:-endpoint-admin-remote-bridge-device-key}"
PUBLIC_PKI_BASE_URL="${PUBLIC_PKI_BASE_URL:-http://127.0.0.1:8201/v1/pki_int}"
CRL_MIN_VALIDITY_SECONDS="${CRL_MIN_VALIDITY_SECONDS:-3600}"

fail() {
  echo "device-ca-crl-preflight: $1" >&2
  exit 1
}

for binding in \
  "$KUBE_CONTEXT=k3d-test" \
  "$KUBE_NAMESPACE=platform-test" \
  "$EXTERNAL_SECRET=endpoint-admin-remote-bridge-secrets-device-key" \
  "$KUBERNETES_SECRET=endpoint-admin-remote-bridge-secrets-device-key" \
  "$BROKER_DEPLOYMENT=endpoint-admin-remote-bridge-device-key" \
  "$PUBLIC_PKI_BASE_URL=http://127.0.0.1:8201/v1/pki_int"; do
  [[ "${binding%%=*}" == "${binding#*=}" ]] \
    || fail "test-only target override refused: ${binding%%=*}"
done

[[ "$CRL_MIN_VALIDITY_SECONDS" =~ ^[0-9]+$ ]] \
  || fail "CRL_MIN_VALIDITY_SECONDS must be an integer"
(( CRL_MIN_VALIDITY_SECONDS >= 600 && CRL_MIN_VALIDITY_SECONDS <= 86400 )) \
  || fail "CRL_MIN_VALIDITY_SECONDS must be between 600 and 86400"

for command_name in awk base64 curl date jq kubectl mktemp openssl sed sha256sum stat; do
  command -v "$command_name" >/dev/null 2>&1 \
    || fail "required command missing: $command_name"
done

work_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/faz22-device-ca-crl-preflight.XXXXXX")"
chmod 700 "$work_dir"
cleanup() {
  rm -rf -- "$work_dir"
}
trap cleanup EXIT

k8s_ca="$work_dir/k8s-ca.pem"
k8s_crl="$work_dir/k8s.crl.pem"
source_ca="$work_dir/source-ca.pem"
source_crl="$work_dir/source.crl.pem"
external_secret_json="$work_dir/external-secret.json"
deployment_json="$work_dir/deployment.json"
pods_json="$work_dir/pods.json"

kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
  get secret "$KUBERNETES_SECRET" \
  -o jsonpath='{.data.ENDPOINT_ADMIN_REMOTE_ACCESS_CERT_TRUST_TRUST_ANCHOR_PEM}' \
  | base64 --decode >"$k8s_ca" \
  || fail "Kubernetes trust anchor read failed"
kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
  get secret "$KUBERNETES_SECRET" \
  -o jsonpath='{.data.ENDPOINT_ADMIN_REMOTE_ACCESS_CERT_TRUST_CRL_PEM}' \
  | base64 --decode >"$k8s_crl" \
  || fail "Kubernetes CRL read failed"

[[ -s "$k8s_ca" && -s "$k8s_crl" ]] \
  || fail "Kubernetes trust anchor or CRL is empty"
(( $(stat -c '%s' "$k8s_ca") <= 65536 )) \
  || fail "Kubernetes trust anchor exceeds 64 KiB"
(( $(stat -c '%s' "$k8s_crl") <= 8388608 )) \
  || fail "Kubernetes CRL exceeds 8 MiB"

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

openssl x509 -in "$k8s_ca" -noout >/dev/null 2>&1 \
  || fail "Kubernetes trust anchor is not a valid certificate"
openssl crl -in "$k8s_crl" -noout >/dev/null 2>&1 \
  || fail "Kubernetes CRL is not valid"
openssl x509 -in "$source_ca" -noout >/dev/null 2>&1 \
  || fail "public Vault PKI CA is not a valid certificate"
openssl crl -in "$source_crl" -noout >/dev/null 2>&1 \
  || fail "public Vault PKI CRL is not valid"

openssl crl -in "$k8s_crl" -noout -verify -CAfile "$k8s_ca" >/dev/null 2>&1 \
  || fail "Kubernetes CRL signature verification failed"
openssl crl -in "$source_crl" -noout -verify -CAfile "$source_ca" >/dev/null 2>&1 \
  || fail "public Vault PKI CRL signature verification failed"

k8s_ca_subject="$(openssl x509 -in "$k8s_ca" -noout -subject -nameopt RFC2253 | sed 's/^subject=//')"
k8s_crl_issuer="$(openssl crl -in "$k8s_crl" -noout -issuer -nameopt RFC2253 | sed 's/^issuer=//')"
[[ -n "$k8s_ca_subject" && "$k8s_ca_subject" == "$k8s_crl_issuer" ]] \
  || fail "Kubernetes CRL issuer does not match the trust anchor subject"

k8s_ca_fingerprint="$(openssl x509 -in "$k8s_ca" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')"
source_ca_fingerprint="$(openssl x509 -in "$source_ca" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')"
k8s_crl_fingerprint="$(openssl crl -in "$k8s_crl" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')"
source_crl_fingerprint="$(openssl crl -in "$source_crl" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')"
[[ "$k8s_ca_fingerprint" == "$source_ca_fingerprint" ]] \
  || fail "Kubernetes trust anchor differs from the public Vault PKI CA"
[[ "$k8s_crl_fingerprint" == "$source_crl_fingerprint" ]] \
  || fail "Kubernetes CRL differs from the public Vault PKI CRL"

next_update="$(openssl crl -in "$k8s_crl" -noout -nextupdate | sed 's/^nextUpdate=//')"
next_update_epoch="$(date -u -d "$next_update" +%s 2>/dev/null)" \
  || fail "CRL nextUpdate cannot be parsed"
now_epoch="$(date -u +%s)"
remaining_seconds="$(( next_update_epoch - now_epoch ))"
(( remaining_seconds >= CRL_MIN_VALIDITY_SECONDS )) \
  || fail "CRL has ${remaining_seconds}s remaining; ${CRL_MIN_VALIDITY_SECONDS}s is required"

kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
  get externalsecret "$EXTERNAL_SECRET" -o json >"$external_secret_json" \
  || fail "ExternalSecret read failed"
jq -e '
  any(.status.conditions[]?;
    .type == "Ready" and .status == "True" and .reason == "SecretSynced")
' "$external_secret_json" >/dev/null \
  || fail "ExternalSecret is not Ready/SecretSynced"
force_sync_epoch="$(jq -er '.metadata.annotations["force-sync"] | select(test("^[1-9][0-9]{9,12}$"))' "$external_secret_json")" \
  || fail "ExternalSecret force-sync marker is missing or invalid"

kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
  get deployment "$BROKER_DEPLOYMENT" -o json >"$deployment_json" \
  || fail "broker deployment read failed"
restart_time="$(jq -er '.spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"]' "$deployment_json")" \
  || fail "broker restart marker is missing"
restart_epoch="$(date -u -d "$restart_time" +%s 2>/dev/null)" \
  || fail "broker restart marker cannot be parsed"
(( restart_epoch >= force_sync_epoch )) \
  || fail "broker restart predates the latest CRL force-sync"
jq -e '
  (.spec.replicas == 1)
  and (.status.readyReplicas == 1)
  and (.status.availableReplicas == 1)
  and (.status.updatedReplicas == 1)
' "$deployment_json" >/dev/null \
  || fail "broker deployment is not 1/1 Ready and updated"

kubectl --context "$KUBE_CONTEXT" -n "$KUBE_NAMESPACE" \
  get pods -l "app.kubernetes.io/name=$BROKER_DEPLOYMENT" -o json >"$pods_json" \
  || fail "broker pod read failed"
jq -e '
  (.items | length) == 1
  and (.items[0].status.phase == "Running")
  and any(.items[0].status.conditions[]?; .type == "Ready" and .status == "True")
  and (.items[0].status.containerStatuses | length) >= 1
  and all(.items[0].status.containerStatuses[];
    .ready == true and (.imageID | test("@sha256:[a-f0-9]{64}$")))
' "$pods_json" >/dev/null \
  || fail "broker pod is not Ready with immutable imageID"

printf 'device-ca-crl-preflight: PASS caSha256=%s crlSha256=%s nextUpdate=%s remainingSeconds=%s restart=%s\n' \
  "$(sha256sum "$k8s_ca" | awk '{print $1}')" \
  "$(sha256sum "$k8s_crl" | awk '{print $1}')" \
  "$(date -u -d "@$next_update_epoch" +%FT%TZ)" \
  "$remaining_seconds" \
  "$restart_time"
