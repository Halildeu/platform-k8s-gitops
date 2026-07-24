#!/usr/bin/env bash
# Faz 35 ES-104G: idempotent TEST evidence buckets, service accounts and Vault
# binding. Run on aiserver. Raw credentials never reach stdout or argv.
set -euo pipefail
# A caller may invoke bash -x; stop tracing before any credential is read.
set +x

ACTION="${1:-check}"
MINIO_CONTAINER="${MINIO_CONTAINER:-minio-minio-test-1}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
VAULT_PATH="${VAULT_PATH:-kv/platform/etik-speak}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
QUARANTINE_BUCKET="${QUARANTINE_BUCKET:-ethics-evidence-quarantine}"
SEALED_BUCKET="${SEALED_BUCKET:-ethics-evidence-sealed}"
DERIVATIVE_BUCKET="${DERIVATIVE_BUCKET:-ethics-evidence-derivative}"

case "$ACTION" in
  check|apply) ;;
  *) echo "FATAL: action must be check or apply" >&2; exit 1 ;;
esac
for binding in \
  "$MINIO_CONTAINER=minio-minio-test-1" \
  "$VAULT_CONTAINER=platform-vault-test" \
  "$VAULT_INIT_FILE=/srv/platform/secrets/backup-auth/vault-init-test.json" \
  "$VAULT_PATH=kv/platform/etik-speak" \
  "$MINIO_ENDPOINT=http://localhost:9000" \
  "$QUARANTINE_BUCKET=ethics-evidence-quarantine" \
  "$SEALED_BUCKET=ethics-evidence-sealed" \
  "$DERIVATIVE_BUCKET=ethics-evidence-derivative"; do
  [ "${binding%%=*}" = "${binding#*=}" ] || {
    echo "FATAL: TEST evidence-storage target override refused: ${binding%%=*}" >&2
    exit 1
  }
done
for command_name in docker jq openssl stat; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "FATAL: required command missing: $command_name" >&2
    exit 1
  }
done
[ -r "$VAULT_INIT_FILE" ] && [ -f "$VAULT_INIT_FILE" ] && [ ! -L "$VAULT_INIT_FILE" ] || {
  echo "FATAL: Vault init file must be a readable regular non-symlink" >&2
  exit 1
}
[ "$(stat -c '%U' "$VAULT_INIT_FILE")" = root ] &&
  [ "$(stat -c '%G' "$VAULT_INIT_FILE")" = root ] &&
  [ "$(stat -c '%a' "$VAULT_INIT_FILE")" = 640 ] || {
  echo "FATAL: Vault init file must be canonical root:root mode 640" >&2
  exit 1
}
[ "$(docker inspect -f '{{.State.Running}}' "$MINIO_CONTAINER")" = true ] &&
  [ "$(docker inspect -f '{{.State.Running}}' "$VAULT_CONTAINER")" = true ] || {
  echo "FATAL: TEST MinIO or Vault container is not running" >&2
  exit 1
}

API_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:GetBucketObjectLockConfiguration"],
      "Resource": [
        "arn:aws:s3:::ethics-evidence-quarantine",
        "arn:aws:s3:::ethics-evidence-sealed",
        "arn:aws:s3:::ethics-evidence-derivative"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
      "Resource": ["arn:aws:s3:::ethics-evidence-quarantine/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectRetention", "s3:PutObjectRetention"],
      "Resource": ["arn:aws:s3:::ethics-evidence-sealed/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion"],
      "Resource": ["arn:aws:s3:::ethics-evidence-derivative/*"]
    }
  ]
}'
WORKER_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketVersioning", "s3:GetBucketObjectLockConfiguration"],
      "Resource": [
        "arn:aws:s3:::ethics-evidence-quarantine",
        "arn:aws:s3:::ethics-evidence-sealed",
        "arn:aws:s3:::ethics-evidence-derivative"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:DeleteObject", "s3:DeleteObjectVersion"],
      "Resource": ["arn:aws:s3:::ethics-evidence-quarantine/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectRetention", "s3:PutObjectRetention"],
      "Resource": ["arn:aws:s3:::ethics-evidence-sealed/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
      "Resource": ["arn:aws:s3:::ethics-evidence-derivative/*"]
    }
  ]
}'

vault_root_token=$(jq -er '.root_token | select(type == "string" and length >= 20)' \
  "$VAULT_INIT_FILE")
api_access=''
api_secret=''
worker_access=''
worker_secret=''
manifest_key=''
new_api_access=''
new_worker_access=''
cleanup_new_accounts=true
cleanup() {
  unset vault_root_token api_access api_secret worker_access worker_secret manifest_key
  if [ "$cleanup_new_accounts" = true ]; then
    for access in "$new_api_access" "$new_worker_access"; do
      [ -n "$access" ] || continue
      docker exec "$MINIO_CONTAINER" sh -c '
        set -eu
        mc alias set evidence-admin "$1" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
        mc admin user svcacct rm evidence-admin "$2" >/dev/null 2>&1 || true
      ' sh "$MINIO_ENDPOINT" "$access" || true
    done
  fi
  unset new_api_access new_worker_access
}
trap cleanup EXIT

minio_admin() {
  docker exec "$MINIO_CONTAINER" sh -c '
    set -eu
    mc alias set evidence-admin "$1" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
    shift
    exec "$@"
  ' sh "$MINIO_ENDPOINT" "$@"
}
minio_admin mc ready evidence-admin >/dev/null

ensure_bucket() {
  local bucket=$1 lock=$2 version_json retention_json
  if ! minio_admin mc stat "evidence-admin/$bucket" >/dev/null 2>&1; then
    [ "$ACTION" = apply ] || {
      echo "FATAL: required evidence bucket is missing: $bucket" >&2
      return 1
    }
    if [ "$lock" = true ]; then
      minio_admin mc mb --with-lock "evidence-admin/$bucket" >/dev/null
    else
      minio_admin mc mb "evidence-admin/$bucket" >/dev/null
    fi
  fi
  if [ "$ACTION" = apply ]; then
    minio_admin mc version enable "evidence-admin/$bucket" >/dev/null
    if [ "$lock" = true ]; then
      minio_admin mc retention set --default COMPLIANCE 30d \
        "evidence-admin/$bucket" >/dev/null
    fi
  fi
  version_json=$(minio_admin mc version info --json "evidence-admin/$bucket")
  printf '%s' "$version_json" | jq -e \
    '.status == "success" and .versioning.status == "Enabled"' >/dev/null || {
    echo "FATAL: evidence bucket versioning is not enabled: $bucket" >&2
    return 1
  }
  if [ "$lock" = true ]; then
    retention_json=$(minio_admin mc retention info --json --default \
      "evidence-admin/$bucket")
    printf '%s' "$retention_json" | jq -e '
      .status == "success" and .enabled == "Enabled" and
      .mode == "COMPLIANCE" and .validity == "30DAYS"
    ' >/dev/null || {
      echo "FATAL: sealed bucket is not COMPLIANCE-locked for 30 days" >&2
      return 1
    }
  fi
}
ensure_bucket "$QUARANTINE_BUCKET" false
ensure_bucket "$SEALED_BUCKET" true
ensure_bucket "$DERIVATIVE_BUCKET" false

vault_read_document() {
  printf '%s\n' "$vault_root_token" | docker exec -i \
    -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c '
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      exec vault kv get -format=json "$1"
    ' sh "$VAULT_PATH"
}
vault_document=$(vault_read_document)
printf '%s' "$vault_document" | jq -e '
  .data.data | type == "object" and
  (.ETHICS_DB_USERNAME | type == "string" and length > 0) and
  (.ETHICS_DB_PASSWORD | type == "string" and length > 0)
' >/dev/null || {
  echo "FATAL: canonical Etik Speak Vault document is absent or malformed" >&2
  exit 1
}
vault_version=$(printf '%s' "$vault_document" | jq -er \
  '.data.metadata.version | select(type == "number" and . > 0)')
api_access=$(printf '%s' "$vault_document" | jq -r \
  '.data.data.ETHICS_EVIDENCE_API_S3_ACCESS_KEY // empty')
api_secret=$(printf '%s' "$vault_document" | jq -r \
  '.data.data.ETHICS_EVIDENCE_API_S3_SECRET_KEY // empty')
worker_access=$(printf '%s' "$vault_document" | jq -r \
  '.data.data.ETHICS_EVIDENCE_WORKER_S3_ACCESS_KEY // empty')
worker_secret=$(printf '%s' "$vault_document" | jq -r \
  '.data.data.ETHICS_EVIDENCE_WORKER_S3_SECRET_KEY // empty')
manifest_key=$(printf '%s' "$vault_document" | jq -r \
  '.data.data.ETHICS_EVIDENCE_MANIFEST_SIGNING_KEY // empty')

service_account_policy_matches() {
  local access=$1 expected=$2 actual expected_normalized actual_normalized
  actual=$(minio_admin mc admin user svcacct info --json --policy \
    evidence-admin "$access") || return 1
  expected_normalized=$(printf '%s' "$expected" | jq -cS '
    .Statement |= (
      map(
        .Action |= (if type == "array" then sort else [.] end) |
        .Resource |= (if type == "array" then sort else [.] end)
      ) |
      sort_by(.Effect, (.Action | join(",")), (.Resource | join(",")))
    )
  ')
  actual_normalized=$(printf '%s' "$actual" | jq -cS '
    .Statement |= (
      map(
        .Action |= (if type == "array" then sort else [.] end) |
        .Resource |= (if type == "array" then sort else [.] end)
      ) |
      sort_by(.Effect, (.Action | join(",")), (.Resource | join(",")))
    )
  ') || return 1
  [ "$actual_normalized" = "$expected_normalized" ]
}
service_account_authenticates() {
  local access=$1 secret=$2
  { printf '%s\n' "$access"; printf '%s\n' "$secret"; } |
    docker exec -i "$MINIO_CONTAINER" sh -c '
      set -eu
      IFS= read -r ACCESS_KEY
      IFS= read -r SECRET_KEY
      mc alias set evidence-runtime "$1" "$ACCESS_KEY" "$SECRET_KEY" >/dev/null 2>&1
      exec mc ls evidence-runtime/ethics-evidence-quarantine
    ' sh "$MINIO_ENDPOINT" >/dev/null
}
edit_service_account_policy() {
  local access=$1 expected=$2
  printf '%s' "$expected" | docker exec -i "$MINIO_CONTAINER" sh -c '
    set -eu
    policy_file=$(mktemp)
    trap '\''rm -f "$policy_file"'\'' EXIT
    cat >"$policy_file"
    mc alias set evidence-admin "$1" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
    mc admin user svcacct edit --policy "$policy_file" \
      evidence-admin "$2" >/dev/null
  ' sh "$MINIO_ENDPOINT" "$access"
}
create_service_account() {
  local name=$1 description=$2 expected=$3 result
  result=$(printf '%s' "$expected" | docker exec -i "$MINIO_CONTAINER" sh -c '
    set -eu
    policy_file=$(mktemp)
    trap '\''rm -f "$policy_file"'\'' EXIT
    cat >"$policy_file"
    mc alias set evidence-admin "$1" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
    mc admin user svcacct add --json --policy "$policy_file" \
      --name "$2" --description "$3" evidence-admin "$MINIO_ROOT_USER"
  ' sh "$MINIO_ENDPOINT" "$name" "$description")
  printf '%s' "$result" | jq -e '
    .status == "success" and .accountStatus == "enabled" and
    (.accessKey | type == "string" and length >= 16) and
    (.secretKey | type == "string" and length >= 32)
  ' >/dev/null || {
    echo "FATAL: MinIO service-account creation returned an invalid receipt" >&2
    return 1
  }
  printf '%s' "$result"
}
reconcile_service_account() {
  local kind=$1 expected=$2 access_var=$3 secret_var=$4 current_access current_secret result
  current_access=${!access_var}
  current_secret=${!secret_var}
  if [ -n "$current_access" ] && [ -n "$current_secret" ]; then
    if [ "$ACTION" = apply ]; then
      if edit_service_account_policy "$current_access" "$expected" 2>/dev/null &&
          service_account_policy_matches "$current_access" "$expected" &&
          service_account_authenticates "$current_access" "$current_secret"; then
        return
      fi
      # Recover a response-loss/cleanup split: Vault may contain a pair whose
      # MinIO account was removed before the prior run committed its receipt.
      minio_admin mc admin user svcacct rm evidence-admin "$current_access" \
        >/dev/null 2>&1 || true
      current_access=''
      current_secret=''
    else
      if ! service_account_policy_matches "$current_access" "$expected"; then
        echo "FATAL: existing $kind evidence service account policy mismatch" >&2
        return 1
      fi
      if ! service_account_authenticates "$current_access" "$current_secret"; then
        echo "FATAL: existing $kind evidence service account authentication failed" >&2
        return 1
      fi
      return
    fi
  fi
  [ "$ACTION" = apply ] || {
    echo "FATAL: $kind evidence service-account credential is absent from Vault" >&2
    return 1
  }
  # A partial Vault pair is unusable. Remove its known access key before
  # replacing both fields, avoiding an accumulating orphan account.
  if [ -n "$current_access" ]; then
    minio_admin mc admin user svcacct rm evidence-admin "$current_access" \
      >/dev/null 2>&1 || true
  fi
  result=$(create_service_account "faz35-ethics-evidence-$kind" \
    "Faz 35 TEST evidence $kind least-privilege identity" "$expected")
  printf -v "$access_var" '%s' "$(printf '%s' "$result" | jq -r .accessKey)"
  printf -v "$secret_var" '%s' "$(printf '%s' "$result" | jq -r .secretKey)"
  if [ "$kind" = api ]; then
    new_api_access=${!access_var}
  else
    new_worker_access=${!access_var}
  fi
}

if [ -z "$manifest_key" ]; then
  [ "$ACTION" = apply ] || {
    echo "FATAL: evidence manifest signing key is absent from Vault" >&2
    exit 1
  }
  manifest_key=$(openssl rand -hex 32)
fi
[ "${#manifest_key}" -ge 32 ] || {
  echo "FATAL: evidence manifest signing key is too short" >&2
  exit 1
}
reconcile_service_account api "$API_POLICY" api_access api_secret
reconcile_service_account worker "$WORKER_POLICY" worker_access worker_secret

if [ "$ACTION" = apply ]; then
  current_data=$(printf '%s' "$vault_document" | jq -c '.data.data')
  updated_data=$(printf '%s' "$current_data" | jq -c \
    --arg api_access "$api_access" \
    --arg api_secret "$api_secret" \
    --arg worker_access "$worker_access" \
    --arg worker_secret "$worker_secret" \
    --arg manifest_key "$manifest_key" '
      . + {
        ETHICS_EVIDENCE_API_S3_ACCESS_KEY: $api_access,
        ETHICS_EVIDENCE_API_S3_SECRET_KEY: $api_secret,
        ETHICS_EVIDENCE_WORKER_S3_ACCESS_KEY: $worker_access,
        ETHICS_EVIDENCE_WORKER_S3_SECRET_KEY: $worker_secret,
        ETHICS_EVIDENCE_MANIFEST_SIGNING_KEY: $manifest_key
      }
    ')
  { printf '%s\n' "$vault_root_token"; printf '%s' "$updated_data"; } |
    docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 \
      "$VAULT_CONTAINER" sh -c '
        set -eu
        IFS= read -r VAULT_TOKEN
        export VAULT_TOKEN
        document=$(mktemp)
        trap '\''rm -f "$document"'\'' EXIT
        cat >"$document"
        vault kv put -cas="$2" "$1" @"$document" >/dev/null
      ' sh "$VAULT_PATH" "$vault_version"
  verified_document=$(vault_read_document)
  printf '%s' "$verified_document" | jq -e \
    --arg api_access "$api_access" \
    --arg api_secret "$api_secret" \
    --arg worker_access "$worker_access" \
    --arg worker_secret "$worker_secret" \
    --arg manifest_key "$manifest_key" '
      .data.data.ETHICS_EVIDENCE_API_S3_ACCESS_KEY == $api_access and
      .data.data.ETHICS_EVIDENCE_API_S3_SECRET_KEY == $api_secret and
      .data.data.ETHICS_EVIDENCE_WORKER_S3_ACCESS_KEY == $worker_access and
      .data.data.ETHICS_EVIDENCE_WORKER_S3_SECRET_KEY == $worker_secret and
      .data.data.ETHICS_EVIDENCE_MANIFEST_SIGNING_KEY == $manifest_key
    ' >/dev/null || {
    echo "FATAL: Vault evidence credential read-after-write mismatch" >&2
    exit 1
  }
  # Vault CAS + readback is the commit point. From here a failed policy/auth
  # postcondition must leave the bound account available for a repair rerun,
  # rather than deleting it and creating a Vault/account split.
  cleanup_new_accounts=false
fi

service_account_policy_matches "$api_access" "$API_POLICY"
service_account_authenticates "$api_access" "$api_secret"
service_account_policy_matches "$worker_access" "$WORKER_POLICY"
service_account_authenticates "$worker_access" "$worker_secret"
cleanup_new_accounts=false
echo "Evidence storage: $ACTION PASS (versioned quarantine/derivative; sealed COMPLIANCE 30DAYS; API/worker credentials redacted)"
