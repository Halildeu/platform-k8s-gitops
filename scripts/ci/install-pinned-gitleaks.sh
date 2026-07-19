#!/usr/bin/env bash
set -euo pipefail

readonly VERSION="8.30.1"
readonly ARCHIVE="gitleaks_${VERSION}_linux_x64.tar.gz"
readonly ARCHIVE_SHA256="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
readonly RELEASE_URL="https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/${ARCHIVE}"

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "pinned gitleaks installer supports only the GitHub-hosted Linux x86_64 runner" >&2
  exit 1
fi

install_root="${1:-${RUNNER_TEMP:?RUNNER_TEMP is required}/pinned-gitleaks-${VERSION}}"
download_root="$(mktemp -d "${RUNNER_TEMP:-/tmp}/gitleaks-download.XXXXXX")"
trap 'rm -rf "$download_root"' EXIT
umask 077

curl \
  --fail \
  --location \
  --proto '=https' \
  --retry 3 \
  --show-error \
  --silent \
  --tlsv1.2 \
  --output "$download_root/$ARCHIVE" \
  "$RELEASE_URL"

printf '%s  %s\n' "$ARCHIVE_SHA256" "$download_root/$ARCHIVE" | sha256sum --check --strict -

rm -rf "$install_root"
mkdir -p "$install_root"
tar --extract --gzip --file "$download_root/$ARCHIVE" --directory "$install_root" gitleaks
test -f "$install_root/gitleaks"
test ! -L "$install_root/gitleaks"
chmod 0555 "$install_root/gitleaks"
test "$("$install_root/gitleaks" version)" = "$VERSION"

if [ -n "${GITHUB_PATH:-}" ]; then
  printf '%s\n' "$install_root" >> "$GITHUB_PATH"
fi
printf '%s\n' "$install_root/gitleaks"
