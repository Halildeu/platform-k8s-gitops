#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="${EDGE_NGINX_SOURCE:-${ROOT}/host-compose/web-nginx/default.conf}"
SSH_TARGET="${SSH_TARGET:-halil@staging-sw}"
REMOTE_FILE="${EDGE_NGINX_REMOTE_FILE:-/home/halil/platform/web/nginx/default.conf}"
CONTAINER="${EDGE_NGINX_CONTAINER:-platform-web-nginx}"
VERIFY="${ROOT}/scripts/faz24/verify-edge-nginx-ws-contract.sh"

mode=check
expected_live_sha=""
remote_candidate=""
live_copy="$(mktemp)"
trap 'rm -f -- "$live_copy"; if [[ -n "$remote_candidate" ]]; then ssh -o BatchMode=yes "$SSH_TARGET" "rm -f -- '\''$remote_candidate'\''" >/dev/null 2>&1 || true; fi' EXIT

usage() {
  cat <<'EOF'
Usage:
  reconcile-edge-nginx.sh --check
  reconcile-edge-nginx.sh --apply --expected-live-sha SHA256

--check is read-only and compares the canonical source with the live bind mount.
--apply requires an exact live SHA (CAS), validates the candidate in the running
container, creates a timestamped backup, reloads nginx, and rolls back on failure.

Environment overrides: SSH_TARGET, EDGE_NGINX_SOURCE, EDGE_NGINX_REMOTE_FILE,
EDGE_NGINX_CONTAINER.
EOF
}

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) mode=check; shift ;;
    --apply) mode=apply; shift ;;
    --expected-live-sha)
      [[ $# -ge 2 ]] || fail '--expected-live-sha requires a value'
      expected_live_sha="$2"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown argument: $1" ;;
  esac
done

[[ -s "$SOURCE" ]] || fail "canonical source missing: ${SOURCE}"
[[ -x "$VERIFY" ]] || fail "contract verifier is not executable: ${VERIFY}"
command -v ssh >/dev/null 2>&1 || fail 'ssh is required'
command -v shasum >/dev/null 2>&1 || fail 'shasum is required'

"$VERIFY" "$SOURCE"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_TARGET" "cat -- '$REMOTE_FILE'" >"$live_copy"
"$VERIFY" "$live_copy"

source_sha="$(shasum -a 256 "$SOURCE" | awk '{print $1}')"
live_sha="$(shasum -a 256 "$live_copy" | awk '{print $1}')"
printf 'source_sha=%s\nlive_sha=%s\n' "$source_sha" "$live_sha"

if [[ "$mode" == check ]]; then
  if [[ "$source_sha" == "$live_sha" ]]; then
    printf 'PASS: live edge config exactly matches canonical source\n'
    exit 0
  fi
  printf 'DRIFT: semantic contract passes, but live bytes differ from canonical source\n' >&2
  exit 3
fi

[[ "$expected_live_sha" =~ ^[0-9a-f]{64}$ ]] || \
  fail '--apply requires --expected-live-sha with a lowercase SHA-256 digest'
[[ "$live_sha" == "$expected_live_sha" ]] || \
  fail "CAS mismatch: expected ${expected_live_sha}, observed ${live_sha}"

remote_candidate="$(
  ssh -o BatchMode=yes "$SSH_TARGET" \
    'umask 077; candidate=$(mktemp /home/halil/platform/web/nginx/default.conf.candidate.XXXXXX); cat >"$candidate"; printf "%s" "$candidate"' \
    <"$SOURCE"
)"
[[ "$remote_candidate" == /home/halil/platform/web/nginx/default.conf.candidate.* ]] || \
  fail 'remote candidate path failed validation'

candidate_sha="$(ssh -o BatchMode=yes "$SSH_TARGET" "sha256sum -- '$remote_candidate'" | awk '{print $1}')"
[[ "$candidate_sha" == "$source_sha" ]] || fail 'candidate transfer digest mismatch'

# Validate without replacing the bind mount. The temporary root config includes
# only the candidate conf.d fragment and reuses the container's mounted TLS files.
ssh -o BatchMode=yes "$SSH_TARGET" bash -s -- "$remote_candidate" "$CONTAINER" <<'REMOTE_VALIDATE'
set -euo pipefail
candidate="$1"
container="$2"
docker cp "$candidate" "${container}:/tmp/edge-default.candidate"
docker exec "$container" sh -eu -c '
  sed "s@include /etc/nginx/conf.d/\\*.conf;@include /tmp/edge-default.candidate;@" \
    /etc/nginx/nginx.conf >/tmp/nginx-candidate.conf
  nginx -t -c /tmp/nginx-candidate.conf
'
REMOTE_VALIDATE

ssh -o BatchMode=yes "$SSH_TARGET" bash -s -- \
  "$remote_candidate" "$REMOTE_FILE" "$CONTAINER" "$expected_live_sha" "$source_sha" <<'REMOTE_APPLY'
set -euo pipefail
candidate="$1"
live_file="$2"
container="$3"
expected_sha="$4"
source_sha="$5"

current_sha="$(sha256sum "$live_file" | awk '{print $1}')"
[[ "$current_sha" == "$expected_sha" ]] || {
  printf 'CAS mismatch immediately before apply: expected %s, observed %s\n' "$expected_sha" "$current_sha" >&2
  exit 1
}

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="${live_file}.bak-canonical-${timestamp}"
cp -p -- "$live_file" "$backup"
cp --preserve=mode,ownership -- "$candidate" "${live_file}.new"
mv -f -- "${live_file}.new" "$live_file"

rollback() {
  cp -p -- "$backup" "$live_file"
  docker exec "$container" nginx -t
  docker exec "$container" nginx -s reload
  printf 'ROLLBACK: restored %s\n' "$backup" >&2
}

if ! docker exec "$container" nginx -t; then
  rollback
  exit 1
fi
if ! docker exec "$container" nginx -s reload; then
  rollback
  exit 1
fi

applied_sha="$(sha256sum "$live_file" | awk '{print $1}')"
[[ "$applied_sha" == "$source_sha" ]] || {
  rollback
  printf 'post-apply digest mismatch: expected %s, observed %s\n' "$source_sha" "$applied_sha" >&2
  exit 1
}
printf 'APPLIED: sha=%s backup=%s\n' "$applied_sha" "$backup"
REMOTE_APPLY

remote_candidate=""
ssh -o BatchMode=yes "$SSH_TARGET" \
  "docker exec '$CONTAINER' nginx -t; curl -ksSf https://testai.acik.com/testai-healthz >/dev/null; curl -ksSf https://ai.acik.com/nginx-healthz >/dev/null"
printf 'PASS: canonical edge config applied with CAS, rollback backup, and health probes\n'
