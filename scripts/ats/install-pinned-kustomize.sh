#!/usr/bin/env bash
# Install an immutable kustomize release into the current Actions job without
# assuming a machine-global package. Release asset digests are pinned from the
# immutable kubernetes-sigs/kustomize v5.8.1 GitHub release metadata.
set -euo pipefail

VERSION="5.8.1"
RUNNER_TEMP="${RUNNER_TEMP:-/tmp}"
GITHUB_PATH="${GITHUB_PATH:-}"

[[ -n "$GITHUB_PATH" ]] || {
  echo "[fullats-kustomize] GITHUB_PATH is required" >&2
  exit 2
}
[[ "$(uname -s)" == "Linux" ]] || {
  echo "[fullats-kustomize] unsupported runner operating system" >&2
  exit 2
}

case "$(uname -m)" in
  x86_64|amd64)
    archive_arch="amd64"
    expected_sha="029a7f0f4e1932c52a0476cf02a0fd855c0bb85694b82c338fc648dcb53a819d"
    ;;
  aarch64|arm64)
    archive_arch="arm64"
    expected_sha="0953ea3e476f66d6ddfcd911d750f5167b9365aa9491b2326398e289fef2c142"
    ;;
  *)
    echo "[fullats-kustomize] unsupported runner architecture" >&2
    exit 2
    ;;
esac

for command in curl tar; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "[fullats-kustomize] missing command: $command" >&2
    exit 2
  }
done

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "[fullats-kustomize] missing SHA-256 implementation" >&2
    return 2
  fi
}

install_root="$(mktemp -d "$RUNNER_TEMP/fullats-kustomize.XXXXXX")"
archive="$install_root/kustomize.tar.gz"
trap 'rm -rf "$install_root"' EXIT
url="https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize/v${VERSION}/kustomize_v${VERSION}_linux_${archive_arch}.tar.gz"

curl --fail --silent --show-error --location \
  --connect-timeout 10 --max-time 120 \
  --retry 4 --retry-all-errors --retry-delay 2 \
  "$url" >"$archive"
actual_sha="$(sha256_file "$archive")"
[[ "$actual_sha" == "$expected_sha" ]] || {
  echo "[fullats-kustomize] archive SHA-256 mismatch" >&2
  exit 1
}

bin_dir="$install_root/bin"
mkdir -p "$bin_dir"
tar -xzf "$archive" -C "$bin_dir"
[[ -x "$bin_dir/kustomize" ]] || {
  echo "[fullats-kustomize] extracted kustomize is not executable" >&2
  exit 1
}
[[ "$("$bin_dir/kustomize" version)" == "v${VERSION}" ]] || {
  echo "[fullats-kustomize] extracted version mismatch" >&2
  exit 1
}

# GITHUB_PATH is consumed by the runner for subsequent steps. The directory
# intentionally remains until the job-scoped runner temp is cleaned.
trap - EXIT
rm -f "$archive"
printf '%s\n' "$bin_dir" >>"$GITHUB_PATH"
echo "[fullats-kustomize] installed pinned kustomize v$VERSION"
