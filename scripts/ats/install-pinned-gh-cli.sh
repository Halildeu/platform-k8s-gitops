#!/usr/bin/env bash
# Install an immutable GitHub CLI release into the current Actions job without
# assuming a machine-global package. The archive checksum is pinned from the
# immutable cli/cli v2.96.0 release asset metadata.
set -euo pipefail

VERSION="2.96.0"
RUNNER_TEMP="${RUNNER_TEMP:-/tmp}"
GITHUB_PATH="${GITHUB_PATH:-}"

[[ -n "$GITHUB_PATH" ]] || {
  echo "[fullats-gh] GITHUB_PATH is required" >&2
  exit 2
}
[[ "$(uname -s)" == "Linux" ]] || {
  echo "[fullats-gh] unsupported runner operating system" >&2
  exit 2
}

case "$(uname -m)" in
  x86_64|amd64)
    archive_arch="amd64"
    expected_sha="83d5c2ccad5498f58bf6368acb1ab32588cf43ab3a4b1c301bf36328b1c8bd60"
    ;;
  aarch64|arm64)
    archive_arch="arm64"
    expected_sha="06f86ec7103d41993b76cd78072f43595c34aaa56506d971d9860e67140bf909"
    ;;
  *)
    echo "[fullats-gh] unsupported runner architecture" >&2
    exit 2
    ;;
esac

for command in curl tar; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "[fullats-gh] missing command: $command" >&2
    exit 2
  }
done

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "[fullats-gh] missing SHA-256 implementation" >&2
    return 2
  fi
}

install_root="$(mktemp -d "$RUNNER_TEMP/fullats-gh.XXXXXX")"
archive="$install_root/gh.tar.gz"
trap 'rm -rf "$install_root"' EXIT
url="https://github.com/cli/cli/releases/download/v${VERSION}/gh_${VERSION}_linux_${archive_arch}.tar.gz"

curl --fail --silent --show-error --location \
  --connect-timeout 10 --max-time 120 \
  --retry 4 --retry-all-errors --retry-delay 2 \
  "$url" >"$archive"
actual_sha="$(sha256_file "$archive")"
[[ "$actual_sha" == "$expected_sha" ]] || {
  echo "[fullats-gh] archive SHA-256 mismatch" >&2
  exit 1
}

tar -xzf "$archive" -C "$install_root"
bin_dir="$install_root/gh_${VERSION}_linux_${archive_arch}/bin"
[[ -x "$bin_dir/gh" ]] || {
  echo "[fullats-gh] extracted GitHub CLI is not executable" >&2
  exit 1
}
"$bin_dir/gh" version >/dev/null

# GITHUB_PATH is consumed by the runner for subsequent steps. The directory
# intentionally remains until the job-scoped runner temp is cleaned.
trap - EXIT
rm -f "$archive"
printf '%s\n' "$bin_dir" >>"$GITHUB_PATH"
echo "[fullats-gh] installed pinned GitHub CLI v$VERSION"
