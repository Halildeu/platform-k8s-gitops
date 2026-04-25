#!/usr/bin/env bash
# Faz 17.3 — Mac k3d-dev ghcr-pull secret + ServiceAccount setup
#
# Kullanım: ./scripts/dev-ghcr-pull-setup.sh
#
# Bağımlılık:
# - Docker Desktop (Mac) veya Docker (Linux) ile `docker login ghcr.io` authenticated
# - Mac'te Docker Desktop credsStore=desktop → keychain'den çekilir
# - Linux'ta config.json'dan direkt çekilir (eski Docker)
#
# Faz 17.3 D34 dev realm self-contained: imagePullPolicy=IfNotPresent + GHCR pull
# (Tiltfile yerine — platform-ssot deprecated 2026-04-25 Faz 19.10)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '\033[0;36m[ghcr-pull]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[ghcr-pull]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[ghcr-pull]\033[0m %s\n' "$*" >&2; exit 1; }

# k3d-dev cluster up mı?
kubectl --context k3d-dev cluster-info >/dev/null 2>&1 \
    || err "k3d-dev context yok — önce './bootstrap/setup-clusters.sh dev'"

# Namespace var mı?
kubectl --context k3d-dev get ns platform-dev >/dev/null 2>&1 \
    || kubectl --context k3d-dev create ns platform-dev

# GHCR credential çekme yöntemi (Mac Docker Desktop credsStore=desktop vs Linux config.json)
USERNAME=""
PASSWORD=""

if [[ -f "$HOME/.docker/config.json" ]]; then
    CREDS_STORE=$(python3 -c "import json; d=json.load(open('$HOME/.docker/config.json')); print(d.get('credsStore', ''))" 2>/dev/null || echo "")

    if [[ "$CREDS_STORE" == "desktop" ]] && command -v docker-credential-desktop >/dev/null 2>&1; then
        # Mac Docker Desktop — keychain'den çek
        log "Docker Desktop credsStore tespit edildi (Mac/keychain)"
        CREDS=$(echo "ghcr.io" | docker-credential-desktop get 2>/dev/null) \
            || err "docker-credential-desktop get fail — 'docker login ghcr.io' çalıştır"
        USERNAME=$(echo "$CREDS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('Username',''))")
        PASSWORD=$(echo "$CREDS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('Secret',''))")
    else
        # Linux Docker veya credsStore yok — config.json auth field'dan çek
        log "Docker config.json direct (Linux)"
        AUTH_B64=$(python3 -c "import json; d=json.load(open('$HOME/.docker/config.json')); print(d.get('auths',{}).get('ghcr.io',{}).get('auth',''))")
        if [[ -n "$AUTH_B64" ]]; then
            DECODED=$(echo "$AUTH_B64" | base64 -D 2>/dev/null || echo "$AUTH_B64" | base64 -d)
            USERNAME=$(echo "$DECODED" | cut -d: -f1)
            PASSWORD=$(echo "$DECODED" | cut -d: -f2-)
        fi
    fi
fi

[[ -n "$USERNAME" && -n "$PASSWORD" ]] \
    || err "GHCR credential bulunamadı — 'docker login ghcr.io' çalıştır"

log "GHCR credential alındı (username=$USERNAME)"

# K8s secret yenile (idempotent)
log "ghcr-pull secret oluşturuluyor (platform-dev ns)"
kubectl --context k3d-dev -n platform-dev delete secret ghcr-pull --ignore-not-found >/dev/null 2>&1
kubectl --context k3d-dev -n platform-dev create secret docker-registry ghcr-pull \
    --docker-server=ghcr.io \
    --docker-username="$USERNAME" \
    --docker-password="$PASSWORD" >/dev/null

# ServiceAccount'lara default imagePullSecret ekle
SAS=("default" "api-gateway" "auth-service")
for sa in "${SAS[@]}"; do
    if kubectl --context k3d-dev -n platform-dev get sa "$sa" >/dev/null 2>&1; then
        log "ServiceAccount '$sa' patched (imagePullSecrets=ghcr-pull)"
        kubectl --context k3d-dev -n platform-dev patch sa "$sa" \
            -p '{"imagePullSecrets":[{"name":"ghcr-pull"}]}' >/dev/null
    else
        warn "ServiceAccount '$sa' bulunamadı — kustomize apply sonrası tekrar çalıştır"
    fi
done

log "✓ ghcr-pull secret + ServiceAccount setup tamamlandı"
log "Sıradaki adım: ./scripts/dev-up.sh --profile authn-min"
