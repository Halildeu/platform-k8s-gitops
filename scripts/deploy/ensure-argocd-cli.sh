#!/usr/bin/env bash
set -euo pipefail

# Deterministic ArgoCD CLI bootstrap. Stdout contains only the verified binary
# path so callers can safely use command substitution; diagnostics use stderr.

ARGOCD_VERSION="${ARGOCD_VERSION:-v2.13.1}"
EXPECTED_VERSION="v2.13.1"
CACHE_ROOT="${ARGOCD_TOOL_CACHE:-${RUNNER_TOOL_CACHE:-${HOME}/.cache/platform-tools}}"

if [[ "$ARGOCD_VERSION" != "$EXPECTED_VERSION" ]]; then
  echo "FAIL: unsupported ARGOCD_VERSION=$ARGOCD_VERSION; checksum contract pins $EXPECTED_VERSION" >&2
  exit 1
fi

for command in curl uname; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "FAIL: required command not found: $command" >&2
    exit 1
  }
done

os=$(uname -s | tr '[:upper:]' '[:lower:]')
arch=$(uname -m)
case "$arch" in
  x86_64|amd64) arch="amd64" ;;
  aarch64|arm64) arch="arm64" ;;
  *)
    echo "FAIL: unsupported ArgoCD CLI architecture: $arch" >&2
    exit 1
    ;;
esac

case "${os}-${arch}" in
  linux-amd64) expected_sha256="8e436f0429d2a88b3181d2cfc460c034070e0ee1c665467271e5d75eb4d55f7f" ;;
  linux-arm64) expected_sha256="76cbc9044c6c8f989302e0354516a95b485e1c9c5eba431fef6a669b2fbd3be4" ;;
  darwin-amd64) expected_sha256="6bfefaa9c66ea7b33e2777e3d57779e39ed91ec05a984dc94a09b94249a3f808" ;;
  darwin-arm64) expected_sha256="9419f78550fbe2ecb02577fd3831c57e6d05a7c47a90e1e0f8262197fd10dcc9" ;;
  *)
    echo "FAIL: unsupported ArgoCD CLI platform: ${os}-${arch}" >&2
    exit 1
    ;;
esac

sha256_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  else
    echo "FAIL: sha256sum or shasum is required" >&2
    return 1
  fi
}

tool_dir="${CACHE_ROOT}/argocd/${ARGOCD_VERSION}/${os}-${arch}"
binary="${tool_dir}/argocd"
mkdir -p "$tool_dir"

if [[ -f "$binary" ]]; then
  actual_sha256=$(sha256_file "$binary")
  if [[ "$actual_sha256" == "$expected_sha256" ]]; then
    chmod 0755 "$binary"
    printf '%s\n' "$binary"
    exit 0
  fi
  echo "NOTICE: cached ArgoCD CLI checksum mismatch; replacing verified cache entry" >&2
  rm -f "$binary"
fi

tmp_binary="${binary}.tmp.$$"
trap 'rm -f "$tmp_binary"' EXIT
url="https://github.com/argoproj/argo-cd/releases/download/${ARGOCD_VERSION}/argocd-${os}-${arch}"
echo "Downloading pinned ArgoCD CLI ${ARGOCD_VERSION} for ${os}-${arch}" >&2
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
  --retry 3 --retry-all-errors \
  "$url" -o "$tmp_binary"

actual_sha256=$(sha256_file "$tmp_binary")
if [[ "$actual_sha256" != "$expected_sha256" ]]; then
  echo "FAIL: ArgoCD CLI SHA256 mismatch (actual=$actual_sha256 expected=$expected_sha256)" >&2
  exit 1
fi

chmod 0755 "$tmp_binary"
mv "$tmp_binary" "$binary"
trap - EXIT
printf '%s\n' "$binary"
