#!/usr/bin/env bash
# Faz 24 — transcript-ready pre-enable permit ceremony, end to end.
#
# Every platform-ai pin move invalidates the permit (it binds
# hostStartupGuard.platformAiCommit exactly), so the GPU host's meeting-ai
# ready-consumer refuses to start until a fresh permit is issued. Running the
# three steps by hand cost a full evening on 2026-08-04 (gitops#3437) because
# each one has a trap that only shows up as a misleading error:
#
#   * the signer calls auth/token/revoke-self when it finishes — handing it a
#     root token REVOKES THE ROOT TOKEN (recovery needs shamir generate-root),
#     so this script always mints a short-lived scoped token instead;
#   * the test Vault's HTTPS listener uses a private CA, and without
#     SSL_CERT_FILE the TLS failure surfaces as "Vault signer token revocation
#     failed" because the finally-block error replaces it;
#   * the collector needs psql, redis-cli and a pinned-host-key `denetim-pc`
#     ssh alias on the runner.
#
# Read-only up to the signing call. The permit is written to --output; installing
# it on the GPU host stays a separate, host-side step (configure-meeting-ai.ps1).
#
# Usage (on the runner that can reach the test cluster and the GPU host):
#   scripts/faz24/issue-transcript-ready-permit.sh --output /tmp/permit.dsse.json
set -euo pipefail
umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
POLICY="${REPO_ROOT}/config/faz24-transcript-ready-pre-enable-policy.v1.json"
CONTEXT="k3d-test"
NAMESPACE="platform-test"
VAULT_CONTAINER="platform-vault-test"
VAULT_ORIGIN="https://127.0.0.1:8302"
VAULT_CA_SOURCE="/srv/platform/stateful/test/vault/tls/ca.crt"
VAULT_INIT_FILE="/srv/platform/secrets/backup-auth/vault-init-test.json"
SIGNER_POLICY_NAME="faz24-transcript-ready-permit-signer"
TRUST_ROOT=""
OUTPUT=""

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --output) OUTPUT="${2:?--output needs a path}"; shift 2 ;;
    --trust-root) TRUST_ROOT="${2:?--trust-root needs a path}"; shift 2 ;;
    --vault-init-file) VAULT_INIT_FILE="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ -n "$OUTPUT" ] || die "--output is required"
[ -f "$POLICY" ] || die "policy not found: $POLICY"

for tool in psql redis-cli python3 jq kubectl docker ssh; do
  command -v "$tool" >/dev/null 2>&1 || die "missing prerequisite: $tool"
done
ssh -F "$HOME/.ssh/config" -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o ConnectTimeout=10 denetim-pc "cmd /c echo ok" >/dev/null 2>&1 ||
  die "the pinned 'denetim-pc' ssh alias is not usable; the collector's host probe needs it"

WORK="$(mktemp -d /tmp/faz24-permit.XXXXXX)"
cleanup() {
  if [ -f "${WORK}/signer.token" ]; then shred -u "${WORK}/signer.token" 2>/dev/null || rm -f "${WORK}/signer.token"; fi
  rm -rf "$WORK"
}
trap cleanup EXIT

GITOPS_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
POLICY_SHA256="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$POLICY")"
PRODUCER_DIGEST="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["producerCapabilities"][0]["transcriptImageDigest"])' "$POLICY")"

if [ -z "$TRUST_ROOT" ]; then
  # The host keeps EVERY trust root it has ever pinned, so "pick the first
  # file" is wrong: on 2026-08-05 the directory held four and the alphabetically
  # first one (417e06fe...) was not the active one (f09351c4...). Signing against
  # a stale root produces a permit the host then refuses, with an error that
  # points at the permit rather than at this selection. Read the ACTIVE root's
  # fingerprint from the host's own runtime env pin and fetch exactly that file.
  TRUST_ROOT="${WORK}/trust-root.json"
  ACTIVE_TRUST_SHA="$(ssh -F "$HOME/.ssh/config" -o BatchMode=yes -o StrictHostKeyChecking=yes denetim-pc \
    "powershell -NoProfile -Command \"(Select-String -Path 'C:\\ProgramData\\Acik\\platform-ai\\meeting-ai.env' -Pattern '^MAI_READY_EXPECTED_PERMIT_TRUST_ROOT_SHA256=' | ForEach-Object { \$_.Line }) -replace '^[^=]+=',''\"" \
    2>/dev/null | tr -d '\r' | grep -E '^[0-9a-f]{64}$' | head -1)"
  [ -n "$ACTIVE_TRUST_SHA" ] || die "could not read the active trust-root pin from the GPU host env; pass --trust-root"
  ssh -F "$HOME/.ssh/config" -o BatchMode=yes -o StrictHostKeyChecking=yes denetim-pc \
    "powershell -NoProfile -Command \"[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\\ProgramData\\Acik\\platform-ai\\permits\\trust\\transcript-ready-trust-root-${ACTIVE_TRUST_SHA}.json'))\"" \
    2>/dev/null | tr -d '\r' | grep -E '^[A-Za-z0-9+/=]+$' | head -1 | base64 -d > "$TRUST_ROOT"
  [ -s "$TRUST_ROOT" ] || die "could not fetch the pinned trust root from the GPU host; pass --trust-root"
  FETCHED_TRUST_SHA="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$TRUST_ROOT")"
  [ "$FETCHED_TRUST_SHA" = "$ACTIVE_TRUST_SHA" ] \
    || die "fetched trust root does not match the host's active pin; refusing to sign"
fi
TRUST_ROOT_SHA256="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$TRUST_ROOT")"

# The signer verifies the server certificate; the test Vault uses a private CA.
VAULT_CA="${WORK}/vault-ca.crt"
sudo cp "$VAULT_CA_SOURCE" "$VAULT_CA"
sudo chown "$(id -u):$(id -g)" "$VAULT_CA"
chmod 600 "$VAULT_CA"

PGUSER="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret transcript-service-secrets -o jsonpath='{.data.SPRING_DATASOURCE_USERNAME}' | base64 -d)"
PGPASSWORD="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret transcript-service-secrets -o jsonpath='{.data.SPRING_DATASOURCE_PASSWORD}' | base64 -d)"
REDISCLI_AUTH="$(kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret transcript-service-secrets -o jsonpath='{.data.TRANSCRIPT_REDIS_PASSWORD}' | base64 -d)"
export PGUSER PGPASSWORD REDISCLI_AUTH
export REDIS_HOST=172.19.0.250 REDIS_PORT=6379

echo "[1/4] read-only evidence collection (gitops ${GITOPS_COMMIT:0:12})"
python3 "${REPO_ROOT}/scripts/faz24/collect_transcript_ready_pre_enable_evidence.py" \
  --policy "$POLICY" --gitops-commit "$GITOPS_COMMIT" \
  --output "${WORK}/candidate.json" >/dev/null 2>&1 || true
[ -s "${WORK}/candidate.json" ] || die "collection produced no candidate evidence"

echo "[2/4] fail-closed verification"
python3 "${REPO_ROOT}/scripts/faz24/verify_transcript_ready_pre_enable_evidence.py" \
  "${WORK}/candidate.json" --policy "$POLICY" \
  --expected-gitops-commit "$GITOPS_COMMIT" --output "${WORK}/verdict.json" || true
[ -s "${WORK}/verdict.json" ] || die "verification produced no verdict"
STATUS="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("status"))' "${WORK}/verdict.json")"
if [ "$STATUS" != "accepted-candidate" ]; then
  echo "verdict: $STATUS — failed checks:" >&2
  python3 - "${WORK}/verdict.json" >&2 <<'PY'
import json, sys
for check in json.load(open(sys.argv[1])).get("checks", []):
    if not check.get("passed"):
        print(" -", check["name"], "|", check["message"], "|", check.get("remediation"))
PY
  die "gate rejected; fix the named check before signing (the allowlist commit and the host ledger are the usual two)"
fi

echo "[3/4] minting a scoped, short-lived signer token"
ROOT_TOKEN="$(sudo jq -r .root_token "$VAULT_INIT_FILE")"
printf '%s' "$ROOT_TOKEN" | docker exec -i "$VAULT_CONTAINER" sh -c \
  'VAULT_TOKEN=$(cat); export VAULT_TOKEN; vault policy read '"$SIGNER_POLICY_NAME"' >/dev/null 2>&1' ||
  die "vault policy '$SIGNER_POLICY_NAME' is missing; apply bootstrap/vault-policies/test/${SIGNER_POLICY_NAME}.hcl first"
printf '%s' "$ROOT_TOKEN" | docker exec -i "$VAULT_CONTAINER" sh -c \
  'VAULT_TOKEN=$(cat); export VAULT_TOKEN; vault token create -policy='"$SIGNER_POLICY_NAME"' -ttl=10m -orphan -field=token' \
  > "${WORK}/signer.token"
unset ROOT_TOKEN
chmod 600 "${WORK}/signer.token"
[ -s "${WORK}/signer.token" ] || die "signer token was not minted"

echo "[4/4] signing the DSSE permit"
SSL_CERT_FILE="$VAULT_CA" python3 "${REPO_ROOT}/scripts/faz24/sign_transcript_ready_pre_enable_permit.py" \
  --verdict "${WORK}/verdict.json" --evidence "${WORK}/candidate.json" \
  --policy "$POLICY" --trust-root "$TRUST_ROOT" \
  --expected-trust-root-sha256 "$TRUST_ROOT_SHA256" \
  --app-env test --expected-gitops-commit "$GITOPS_COMMIT" \
  --expected-policy-sha256 "$POLICY_SHA256" \
  --expected-producer-image-digest "$PRODUCER_DIGEST" \
  --vault-origin "$VAULT_ORIGIN" --vault-token-file "${WORK}/signer.token" \
  --vault-key-version 1 --output "$OUTPUT"

echo
echo "permit:            $OUTPUT"
echo "permit sha256:     $(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$OUTPUT")"
echo "trust root:        $TRUST_ROOT (sha256 $TRUST_ROOT_SHA256)"
echo "gitops commit:     $GITOPS_COMMIT"
echo "policy sha256:     $POLICY_SHA256"
echo "producer digest:   $PRODUCER_DIGEST"
echo
echo "Install on the GPU host (see docs/runbooks/RB-faz24-transcript-ready-legacy-pre-enable.md §9):"
echo "  scp the permit + trust root into C:\\ProgramData\\Acik\\platform-ai\\permits\\incoming\\,"
echo "  protect their ACLs (SetAccessRuleProtection(\$true,\$true)), then run"
echo "  configure-meeting-ai.ps1 with the four Expected* values printed above and -ReadyConsumerEnabled true."
