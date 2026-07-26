#!/usr/bin/env bash
# Faz 35 Etik Speak ES-104G: TEST evidence custody dependencies.
#
# Provisions the object-store side of the attachment pipeline: three buckets,
# two least-privilege identities with SEPARATE credentials (upload admission vs
# worker processing), and the Vault material the cell consumes through ESO.
#
# Run on the platform host. Raw credentials never reach stdout, the process
# argument list of this host, Git, an issue or an evidence file. Only key
# PRESENCE is ever reported.
#
# Idempotent: an existing bucket, policy, identity or Vault key is re-asserted,
# not recreated. Fail-closed: any step that cannot be verified aborts before a
# later step can report success.
set -euo pipefail
# A caller may invoke bash -x; disable tracing before any credential is read.
set +x
# shellcheck disable=SC2016 # Single quotes are the mechanism, not an oversight:
# these strings are programs executed inside a container, and "$1"/$MINIO_ROOT_*
# must expand there. Expanding them here would put arguments — and in one case a
# root credential — into this host's process list.

MINIO_CONTAINER="${MINIO_CONTAINER:-minio-minio-test-1}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
VAULT_PATH="${VAULT_PATH:-kv/platform/etik-speak}"
MINIO_COMPOSE_DIR="${MINIO_COMPOSE_DIR:-/opt/platform/minio}"

QUARANTINE_BUCKET=ethics-evidence-quarantine
SEALED_BUCKET=ethics-evidence-sealed
DERIVATIVE_BUCKET=ethics-evidence-derivative
API_USER=ethics-evidence-api
WORKER_USER=ethics-evidence-worker
API_POLICY=ethics-evidence-api
WORKER_POLICY=ethics-evidence-worker
KMS_KEY_NAME=ethics-evidence-test

ROTATE=0
for arg in "$@"; do
  case "$arg" in
    --rotate) ROTATE=1 ;;
    *) echo "FATAL: unknown argument: $arg" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Test-only guards. This script must never be pointed at production material.
# ---------------------------------------------------------------------------
[ "$MINIO_CONTAINER" = "minio-minio-test-1" ] || {
  echo "FATAL: this script is test-only; MINIO_CONTAINER=$MINIO_CONTAINER refused" >&2
  exit 1
}
[ "$VAULT_CONTAINER" = "platform-vault-test" ] || {
  echo "FATAL: this script is test-only; VAULT_CONTAINER=$VAULT_CONTAINER refused" >&2
  exit 1
}
[ "$VAULT_PATH" = "kv/platform/etik-speak" ] || {
  echo "FATAL: VAULT_PATH override refused" >&2
  exit 1
}

for container in "$MINIO_CONTAINER" "$VAULT_CONTAINER"; do
  docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true || {
    echo "FATAL: container is not running: $container" >&2
    exit 1
  }
done

# ---------------------------------------------------------------------------
# Credential plumbing. Every secret crosses a pipe, never an argument vector.
# ---------------------------------------------------------------------------

# The trailing newline is load-bearing: the reader inside the container uses
# `read -r`, which reports failure on an unterminated final line and would abort
# the whole script under `set -e` with no diagnostic.
vault_root_token() {
  sudo python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' \
    "$VAULT_INIT_FILE"
}

# vault_exec <script> [args...] — the token arrives on stdin inside the container.
vault_exec() {
  local script=$1; shift
  vault_root_token | docker exec -i -e VAULT_ADDR=http://127.0.0.1:8200 \
    "$VAULT_CONTAINER" sh -c "
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      $script
    " _ "$@"
}

# vault_read_property <key> — echoes the value, or nothing when absent.
# Used to reuse an already-seeded credential instead of rotating it.
vault_read_property() {
  vault_exec 'vault kv get -field="$1" '"$VAULT_PATH"' 2>/dev/null || true' "$1"
}

# vault_write_property <key> — value on stdin, never in an argument.
vault_write_property() {
  local key=$1 value
  IFS= read -r value
  { vault_root_token; printf '%s\n' "$value"; } | docker exec -i \
    -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" sh -c "
      set -eu
      IFS= read -r VAULT_TOKEN
      export VAULT_TOKEN
      IFS= read -r VALUE
      export VALUE
      printf '%s' \"\$VALUE\" | vault kv patch $VAULT_PATH \"\$1\"=- >/dev/null
    " _ "$key"
}

# mc_exec <script> [args...] — the MinIO root credential is read from the
# container's own environment; it never crosses the host boundary.
mc_exec() {
  local script=$1; shift
  docker exec -i "$MINIO_CONTAINER" sh -c '
    set -eu
    mc alias set es104g http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    trap "mc alias remove es104g >/dev/null 2>&1 || true" EXIT
    '"$script" _ "$@"
}

# A 40-character alphanumeric secret: safe for Spring env interpolation and for
# an S3 credential, with no shell- or URL-escaping hazard.
# `tr </dev/urandom | head -c` is the obvious spelling and the wrong one: head
# closes the pipe, tr dies of SIGPIPE and `pipefail` turns a successful draw
# into a 141 exit. Draw a bounded block first, then filter it.
generate_secret() {
  local drawn=""
  while [ "${#drawn}" -lt 40 ]; do
    drawn="$drawn$(LC_ALL=C head -c 256 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9')"
  done
  printf '%s' "${drawn:0:40}"
}

# ---------------------------------------------------------------------------
# 1. Server-side encryption. The custody contract pins AES256 and the service
#    refuses to start on anything else, so a MinIO without a KMS would accept
#    every declaration and then fail the first real upload.
# ---------------------------------------------------------------------------
ensure_kms() {
  if mc_exec 'mc admin kms key status es104g >/dev/null 2>&1'; then
    echo "kms: already configured"
    return 0
  fi

  echo "kms: not configured — enabling the single-key MinIO KMS"
  local key
  key=$(vault_read_property MINIO_TEST_KMS_SECRET_KEY)
  if [ -z "$key" ]; then
    key="$KMS_KEY_NAME:$(LC_ALL=C head -c 32 /dev/urandom | base64 | tr -d '\n')"
    printf '%s\n' "$key" | vault_write_property MINIO_TEST_KMS_SECRET_KEY
    echo "kms: master key generated and sealed into Vault"
  else
    echo "kms: reusing the master key already held in Vault"
  fi

  # The key reaches the container through the compose env file, which is
  # root-owned and outside Git — the same channel the root credential uses.
  local env_file="$MINIO_COMPOSE_DIR/.env"
  sudo test -f "$env_file" || {
    echo "FATAL: expected compose env file is missing: $env_file" >&2
    exit 1
  }
  if sudo grep -q '^MINIO_TEST_KMS_SECRET_KEY=' "$env_file"; then
    printf '%s' "$key" | sudo python3 -c '
import sys, re, pathlib
path = pathlib.Path(sys.argv[1])
value = sys.stdin.read()
text = path.read_text()
path.write_text(re.sub(r"(?m)^MINIO_TEST_KMS_SECRET_KEY=.*$",
                       "MINIO_TEST_KMS_SECRET_KEY=" + value, text))
' "$env_file"
  else
    printf '%s' "$key" | sudo python3 -c '
import sys, pathlib
path = pathlib.Path(sys.argv[1])
value = sys.stdin.read()
text = path.read_text()
if text and not text.endswith("\n"):
    text += "\n"
path.write_text(text + "MINIO_TEST_KMS_SECRET_KEY=" + value + "\n")
' "$env_file"
  fi
  unset key

  # The compose service must consume it; a silent no-op here would leave the
  # pipeline broken in exactly the way this step exists to prevent.
  sudo grep -q 'MINIO_KMS_SECRET_KEY' "$MINIO_COMPOSE_DIR/docker-compose.yml" || {
    echo "FATAL: minio-test compose does not pass MINIO_KMS_SECRET_KEY" >&2
    echo "       add it to the minio-test service environment first" >&2
    exit 1
  }

  # Compose interpolates every service in the file, including the prod one whose
  # credentials deliberately live only in an operator shell. Placeholders satisfy
  # that parse without touching prod: the profile and the explicit service name
  # keep the action on minio-test alone.
  ( cd "$MINIO_COMPOSE_DIR" \
      && sudo MINIO_ROOT_USER=unused-by-test-profile \
              MINIO_ROOT_PASSWORD=unused-by-test-profile \
         docker compose --profile test up -d minio-test )
  local waited=0
  until mc_exec 'mc admin kms key status es104g >/dev/null 2>&1'; do
    waited=$((waited + 3))
    [ "$waited" -le 90 ] || {
      echo "FATAL: MinIO KMS did not come up within 90s" >&2
      exit 1
    }
    sleep 3
  done
  echo "kms: enabled and answering"
}

# ---------------------------------------------------------------------------
# 2. Buckets. The sealed original bucket carries Object Lock, which can only be
#    set at creation — an existing bucket without it is a hard stop, never a
#    silently-accepted downgrade.
# ---------------------------------------------------------------------------
# The MinIO image is minimal and has no grep, so every text match happens on
# this side of the container boundary.
sealed_is_locked() {
  mc_exec 'mc retention info --default es104g/"$1" 2>&1' "$SEALED_BUCKET" \
    | grep -q COMPLIANCE
}

api_policy_reaches_sealed() {
  mc_exec 'mc admin policy info es104g "$1" 2>/dev/null' "$API_POLICY" \
    | grep -q "$SEALED_BUCKET"
}

ensure_buckets() {
  for bucket in "$QUARANTINE_BUCKET" "$DERIVATIVE_BUCKET"; do
    if mc_exec 'mc stat --no-list es104g/"$1" >/dev/null 2>&1' "$bucket"; then
      echo "bucket: $bucket present"
    else
      mc_exec 'mc mb --with-versioning es104g/"$1" >/dev/null' "$bucket"
      echo "bucket: $bucket created"
    fi
  done

  if mc_exec 'mc stat --no-list es104g/"$1" >/dev/null 2>&1' "$SEALED_BUCKET"; then
    sealed_is_locked || {
      echo "FATAL: $SEALED_BUCKET exists without COMPLIANCE object lock." >&2
      echo "       Object Lock cannot be added after creation; the bucket must be" >&2
      echo "       recreated by an operator before sealed originals are trusted." >&2
      exit 1
    }
    echo "bucket: $SEALED_BUCKET present with COMPLIANCE lock"
  else
    mc_exec 'mc mb --with-lock es104g/"$1" >/dev/null' "$SEALED_BUCKET"
    mc_exec 'mc retention set --default COMPLIANCE 30d es104g/"$1" >/dev/null' "$SEALED_BUCKET"
    echo "bucket: $SEALED_BUCKET created with COMPLIANCE 30d lock"
  fi
}

# ---------------------------------------------------------------------------
# 3. Least-privilege policies. The two identities are deliberately disjoint:
#    the request-facing service can write a quarantine object and read a
#    finished derivative, and nothing else; the worker can read quarantine,
#    seal it and publish a derivative, but can never read one back.
# ---------------------------------------------------------------------------
api_policy_document() {
  cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
      "Resource": ["arn:aws:s3:::$QUARANTINE_BUCKET/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion"],
      "Resource": ["arn:aws:s3:::$DERIVATIVE_BUCKET/*"]
    }
  ]
}
EOF
}

worker_policy_document() {
  cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:DeleteObject"],
      "Resource": ["arn:aws:s3:::$QUARANTINE_BUCKET/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
      "Resource": ["arn:aws:s3:::$SEALED_BUCKET/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
      "Resource": ["arn:aws:s3:::$DERIVATIVE_BUCKET/*"]
    }
  ]
}
EOF
}

ensure_policy() {
  local name=$1 document=$2
  printf '%s' "$document" | docker exec -i "$MINIO_CONTAINER" sh -c '
    set -eu
    mc alias set es104g http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    trap "mc alias remove es104g >/dev/null 2>&1 || true; rm -f /tmp/$1.json" EXIT
    cat >"/tmp/$1.json"
    mc admin policy create es104g "$1" "/tmp/$1.json" >/dev/null
  ' _ "$name"
  echo "policy: $name applied"
}

# ---------------------------------------------------------------------------
# 4. Identities. An identity that already exists keeps its credential unless
#    --rotate is given, so re-running this script does not invalidate a live
#    cell. The secret is only ever read back from Vault, never from MinIO.
# ---------------------------------------------------------------------------
ensure_identity() {
  local user=$1 policy=$2 access_key_property=$3 secret_key_property=$4
  local secret

  secret=$(vault_read_property "$secret_key_property")
  if [ -n "$secret" ] && [ "$ROTATE" -eq 0 ]; then
    echo "identity: $user reusing the credential held in Vault"
  else
    secret=$(generate_secret)
    echo "identity: $user credential generated"
  fi

  # Newline-terminated for the same reason the Vault token is: `read -r` fails
  # on an unterminated line and `set -e` would abort with nothing on stderr.
  printf '%s\n' "$secret" | docker exec -i "$MINIO_CONTAINER" sh -c '
    set -eu
    mc alias set es104g http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    trap "mc alias remove es104g >/dev/null 2>&1 || true" EXIT
    IFS= read -r SECRET
    mc admin user add es104g "$1" "$SECRET" >/dev/null
    mc admin policy attach es104g "$2" --user "$1" >/dev/null 2>&1 || true
  ' _ "$user" "$policy"

  printf '%s\n' "$user" | vault_write_property "$access_key_property"
  printf '%s\n' "$secret" | vault_write_property "$secret_key_property"
  unset secret
  echo "identity: $user bound to policy $policy and sealed into Vault"
}

# ---------------------------------------------------------------------------
# 5. Manifest signing key. The service refuses to start with fewer than 32
#    characters, so a short or absent key is a boot failure, not a silent
#    downgrade of the custody chain.
# ---------------------------------------------------------------------------
ensure_signing_key() {
  local existing
  existing=$(vault_read_property ETHICS_EVIDENCE_MANIFEST_SIGNING_KEY)
  if [ -n "$existing" ] && [ "${#existing}" -ge 32 ] && [ "$ROTATE" -eq 0 ]; then
    echo "signing key: present (${#existing} characters)"
    return 0
  fi
  generate_secret | vault_write_property ETHICS_EVIDENCE_MANIFEST_SIGNING_KEY
  echo "signing key: generated and sealed into Vault"
}

# ---------------------------------------------------------------------------
# 6. Verification. Presence and separation are proven against the live server,
#    not against what this script believes it just did.
# ---------------------------------------------------------------------------
verify() {
  local failed=0

  for bucket in "$QUARANTINE_BUCKET" "$SEALED_BUCKET" "$DERIVATIVE_BUCKET"; do
    mc_exec 'mc stat --no-list es104g/"$1" >/dev/null 2>&1' "$bucket" || {
      echo "VERIFY FAIL: bucket missing: $bucket" >&2; failed=1; }
  done

  sealed_is_locked || {
    echo "VERIFY FAIL: sealed bucket lost its object lock" >&2; failed=1; }

  mc_exec 'mc admin kms key status es104g >/dev/null 2>&1' || {
    echo "VERIFY FAIL: KMS is not answering; AES256 uploads would fail" >&2; failed=1; }

  for user in "$API_USER" "$WORKER_USER"; do
    mc_exec 'mc admin user info es104g "$1" >/dev/null 2>&1' "$user" || {
      echo "VERIFY FAIL: identity missing: $user" >&2; failed=1; }
  done

  # The separation itself is the security property worth proving: the
  # request-facing identity must not be able to write a sealed original.
  if api_policy_reaches_sealed; then
    echo "VERIFY FAIL: the API policy can reach the sealed bucket" >&2
    failed=1
  else
    echo "separation: the API identity cannot reach sealed originals"
  fi

  for property in \
    ETHICS_EVIDENCE_S3_ACCESS_KEY ETHICS_EVIDENCE_S3_SECRET_KEY \
    ETHICS_EVIDENCE_WORKER_S3_ACCESS_KEY ETHICS_EVIDENCE_WORKER_S3_SECRET_KEY \
    ETHICS_EVIDENCE_MANIFEST_SIGNING_KEY; do
    local value
    value=$(vault_read_property "$property")
    if [ -z "$value" ]; then
      echo "VERIFY FAIL: Vault property missing: $property" >&2
      failed=1
    else
      echo "vault: $property present (${#value} characters)"
    fi
    unset value
  done

  [ "$failed" -eq 0 ] || {
    echo "FATAL: verification failed; the cell must not be treated as provisioned" >&2
    exit 1
  }
  echo "verify: evidence custody dependencies are in place"
}

main() {
  ensure_kms
  ensure_buckets
  ensure_policy "$API_POLICY" "$(api_policy_document)"
  ensure_policy "$WORKER_POLICY" "$(worker_policy_document)"
  ensure_identity "$API_USER" "$API_POLICY" \
    ETHICS_EVIDENCE_S3_ACCESS_KEY ETHICS_EVIDENCE_S3_SECRET_KEY
  ensure_identity "$WORKER_USER" "$WORKER_POLICY" \
    ETHICS_EVIDENCE_WORKER_S3_ACCESS_KEY ETHICS_EVIDENCE_WORKER_S3_SECRET_KEY
  ensure_signing_key
  verify
}

main
