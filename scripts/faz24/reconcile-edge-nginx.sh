#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="${EDGE_NGINX_SOURCE:-${ROOT}/host-compose/web-nginx/default.conf}"
SSH_TARGET="${SSH_TARGET:-aiadmin@aiserver}"
REMOTE_FILE="${EDGE_NGINX_REMOTE_FILE:-/srv/platform/web/nginx/default.conf}"
CONTAINER="${EDGE_NGINX_CONTAINER:-platform-web-nginx}"
VERIFY="${ROOT}/scripts/faz24/verify-edge-nginx-ws-contract.sh"

mode=check
expected_live_sha=""
remote_candidate=""
live_copy="$(mktemp)"
container_copy="$(mktemp)"
trap 'rm -f -- "$live_copy" "$container_copy"; if [[ -n "$remote_candidate" ]]; then ssh -o BatchMode=yes "$SSH_TARGET" "rm -f -- '\''$remote_candidate'\''" >/dev/null 2>&1 || true; fi' EXIT

usage() {
  cat <<'EOF'
Usage:
  reconcile-edge-nginx.sh --check
  reconcile-edge-nginx.sh --apply --expected-live-sha SHA256

--check is read-only and compares canonical source, host path and container
bind-mount bytes.
--apply requires an exact live SHA (CAS), validates the candidate in the running
container, creates timestamped host/runtime backups, restarts nginx so a
read-only bind mount follows the new inode, and rolls back on failure.

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
ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_TARGET" \
  "docker exec '$CONTAINER' cat /etc/nginx/conf.d/default.conf" >"$container_copy"
"$VERIFY" "$container_copy"

source_sha="$(shasum -a 256 "$SOURCE" | awk '{print $1}')"
live_sha="$(shasum -a 256 "$live_copy" | awk '{print $1}')"
container_sha="$(shasum -a 256 "$container_copy" | awk '{print $1}')"
printf 'source_sha=%s\nlive_sha=%s\ncontainer_sha=%s\n' \
  "$source_sha" "$live_sha" "$container_sha"

if [[ "$mode" == check ]]; then
  if [[ "$source_sha" == "$live_sha" && "$source_sha" == "$container_sha" ]]; then
    printf 'PASS: host path and container bind mount exactly match canonical source\n'
    exit 0
  fi
  printf 'DRIFT: semantic contract passes, but source/host/container bytes differ\n' >&2
  exit 3
fi

[[ "$expected_live_sha" =~ ^[0-9a-f]{64}$ ]] || \
  fail '--apply requires --expected-live-sha with a lowercase SHA-256 digest'
[[ "$live_sha" == "$expected_live_sha" ]] || \
  fail "CAS mismatch: expected ${expected_live_sha}, observed ${live_sha}"

remote_candidate="$(
  ssh -o BatchMode=yes "$SSH_TARGET" \
    'umask 077; candidate=$(mktemp /srv/platform/web/nginx/default.conf.candidate.XXXXXX); cat >"$candidate"; printf "%s" "$candidate"' \
    <"$SOURCE"
)"
[[ "$remote_candidate" == /srv/platform/web/nginx/default.conf.candidate.* ]] || \
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
trap 'docker exec "$container" rm -f /tmp/edge-default.candidate /tmp/nginx-candidate.conf >/dev/null 2>&1 || true' EXIT
docker exec "$container" sh -eu -c '
  sed "s@include /etc/nginx/conf.d/\\*.conf;@include /tmp/edge-default.candidate;@" \
    /etc/nginx/nginx.conf >/tmp/nginx-candidate.conf
  nginx -t -c /tmp/nginx-candidate.conf
'
REMOTE_VALIDATE

ssh -o BatchMode=yes "$SSH_TARGET" bash -s -- \
  "$remote_candidate" "$REMOTE_FILE" "$CONTAINER" "$expected_live_sha" \
  "$container_sha" "$source_sha" <<'REMOTE_APPLY'
set -euo pipefail
candidate="$1"
live_file="$2"
container="$3"
expected_sha="$4"
expected_container_sha="$5"
source_sha="$6"
container_file="/etc/nginx/conf.d/default.conf"

current_sha="$(sha256sum "$live_file" | awk '{print $1}')"
[[ "$current_sha" == "$expected_sha" ]] || {
  printf 'CAS mismatch immediately before apply: expected %s, observed %s\n' "$expected_sha" "$current_sha" >&2
  exit 1
}
current_container_sha="$(
  docker exec "$container" sha256sum "$container_file" | awk '{print $1}'
)"
[[ "$current_container_sha" == "$expected_container_sha" ]] || {
  printf 'container CAS mismatch immediately before apply: expected %s, observed %s\n' \
    "$expected_container_sha" "$current_container_sha" >&2
  exit 1
}
mount_source="$(
  docker inspect "$container" \
    --format '{{range .Mounts}}{{if eq .Destination "/etc/nginx/conf.d/default.conf"}}{{.Source}}{{end}}{{end}}'
)"
[[ "$mount_source" == "$live_file" ]] || {
  printf 'container bind source mismatch: expected %s, observed %s\n' \
    "$live_file" "${mount_source:-missing}" >&2
  exit 1
}

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="${live_file}.bak-canonical-${timestamp}"
runtime_backup="${live_file}.bak-runtime-${timestamp}"
cp -p -- "$live_file" "$backup"
docker exec "$container" cat "$container_file" >"$runtime_backup"
chmod --reference="$live_file" "$runtime_backup"
chown --reference="$live_file" "$runtime_backup"
cp --preserve=mode,ownership -- "$candidate" "${live_file}.new"
mv -f -- "${live_file}.new" "$live_file"

rollback() {
  set +e
  cp -p -- "$runtime_backup" "${live_file}.rollback"
  mv -f -- "${live_file}.rollback" "$live_file"
  docker restart "$container" >/dev/null
  docker exec "$container" nginx -t
  set -e
  printf 'ROLLBACK: restored effective runtime from %s\n' "$runtime_backup" >&2
}

if ! docker restart "$container" >/dev/null; then
  rollback
  exit 1
fi
if ! docker exec "$container" nginx -t; then
  rollback
  exit 1
fi

applied_sha="$(sha256sum "$live_file" | awk '{print $1}')"
applied_container_sha="$(
  docker exec "$container" sha256sum "$container_file" | awk '{print $1}'
)"
[[ "$applied_sha" == "$source_sha" && "$applied_container_sha" == "$source_sha" ]] || {
  rollback
  printf 'post-apply digest mismatch: expected %s, host %s, container %s\n' \
    "$source_sha" "$applied_sha" "$applied_container_sha" >&2
  exit 1
}
printf 'APPLIED: host_sha=%s container_sha=%s backup=%s runtime_backup=%s\n' \
  "$applied_sha" "$applied_container_sha" "$backup" "$runtime_backup"
REMOTE_APPLY

ssh -o BatchMode=yes "$SSH_TARGET" "rm -f -- '$remote_candidate'"
remote_candidate=""
ssh -o BatchMode=yes "$SSH_TARGET" \
  "docker exec '$CONTAINER' nginx -t; curl -ksSf https://testai.acik.com/testai-healthz >/dev/null; curl -ksSf https://ai.acik.com/nginx-healthz >/dev/null"
printf 'PASS: canonical edge config applied with dual SHA, rollback backups, and health probes\n'
