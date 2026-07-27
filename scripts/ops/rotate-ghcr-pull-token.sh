#!/usr/bin/env bash
# rotate-ghcr-pull-token.sh — GHCR pull PAT'ini güvenli ve doğrulanmış şekilde
# döndür (gitops#2876).
#
# NEDEN VAR
#   2026-07-24/25'te k3d-test'in `ghcr-pull` kimliği yeni imaj sürümlerini
#   çekemez oldu (403 Forbidden). Sonuç: HİÇBİR backend imajı promote
#   edilemiyor ve her deneme o servisi düşürüyor. O gün üç kesinti bundan:
#   #2863 (auth-service 106dk), #2874/#2875 (user-service), #2883 (auth-service).
#
# TASARIM KARARI — ÖNCE DOĞRULA, SONRA YAZ
#   Vault'a doğrulanmamış bir PAT yazmak, ÇALIŞAN kimliği sessizce bozar ve
#   arıza ancak bir sonraki image pull'da (saatler sonra, bir servis düşerken)
#   ortaya çıkar. Bu script yeni PAT'i Vault'a yazmadan ÖNCE gerçek bir GHCR
#   manifest çağrısıyla sınar; geçmezse hiçbir şeye dokunmaz.
#
# GÜVENLİK
#   - PAT yalnız STDIN'den alınır. argv'ye YAZILMAZ (ps/shell-history sızıntısı),
#     env'e export EDİLMEZ, ekrana BASILMAZ, log'a düşmez.
#   - Doğrulama ve Vault yazımı uzak hostta tek oturumda, in-band yapılır.
#   - Script hiçbir yerde PAT'i dosyaya kalıcı yazmaz.
#
# KULLANIM
#   1) PAT üret (owner):  https://github.com/settings/tokens/new?scopes=read:packages&description=k3d-ghcr-pull
#      Gerekli TEK scope: read:packages   (repo/workflow GEREKMEZ — least privilege)
#   2) Döndür:
#        printf '%s' '<YENI_PAT>' | bash scripts/ops/rotate-ghcr-pull-token.sh
#      veya interaktif (terminal ekoyu kapatır):
#        bash scripts/ops/rotate-ghcr-pull-token.sh --prompt
#
# ÇIKIŞ KODU
#   0 = döndürüldü ve pull doğrulandı
#   1 = PAT geçersiz/yetkisiz — Vault'a DOKUNULMADI
#   2 = ön koşul eksik (SSH/Vault/araç)
set -uo pipefail

SSH_HOST="${SSH_HOST:-aiserver}"
VAULT_CONTAINER="${VAULT_CONTAINER:-platform-vault-test}"
VAULT_PATH="${VAULT_PATH:-kv/gitops/ghcr-token}"
GHCR_USER="${GHCR_USER:-Halildeu}"
# Doğrulama hedefi: gerçekten çekilmesi gereken bir paket.
PROBE_PACKAGE="${PROBE_PACKAGE:-halildeu/platform-backend-auth-service}"
CTX="${KUBE_CONTEXT:-k3d-test}"
NS="${NAMESPACE:-platform-test}"

PROMPT=0
[ "${1:-}" = "--prompt" ] && PROMPT=1

# --- PAT'i STDIN'den al (argv'ye asla girmez) ---------------------------
if [ "$PROMPT" = "1" ]; then
    printf 'GHCR PAT (read:packages) — giriş gizli: ' >&2
    stty -echo 2>/dev/null; IFS= read -r NEW_PAT; stty echo 2>/dev/null
    printf '\n' >&2
else
    IFS= read -r NEW_PAT || true
fi

if [ -z "${NEW_PAT:-}" ]; then
    echo "HATA: PAT stdin'den okunamadı. Kullanım: printf '%s' '<PAT>' | $0" >&2
    exit 2
fi
case "$NEW_PAT" in
    *[![:print:]]*) echo "HATA: PAT yazdırılamayan karakter içeriyor." >&2; exit 2 ;;
esac

if ! ssh -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST" true 2>/dev/null; then
    echo "HATA: SSH_HOST='$SSH_HOST' erişilemiyor." >&2
    exit 2
fi

# Uzak gövde AYRI DOSYADA (rotate-ghcr-pull-token.remote.sh). Sebep teknik:
# gövdeyi $(cat <<EOF) içine gömmek, içindeki ")" karakterleri yüzünden bash
# komut-ikamesi ayrıştırıcısını bozuyor. Ayrıca `bash -s` + heredoc, PAT'i
# taşıyan pipe'ı ezerdi (SC2259). Bu yüzden gövde base64 ile ARGÜMAN olarak
# gider; stdin yalnızca PAT'e ayrılır.
REMOTE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/rotate-ghcr-pull-token.remote.sh"
if [ ! -f "$REMOTE_FILE" ]; then
    echo "HATA: uzak gövde bulunamadı: $REMOTE_FILE" >&2
    exit 2
fi
REMOTE_B64=$(base64 < "$REMOTE_FILE" | tr -d '\n')

printf '%s' "$NEW_PAT" | ssh -o BatchMode=yes "$SSH_HOST" \
  "VAULT_CONTAINER='$VAULT_CONTAINER' VAULT_PATH='$VAULT_PATH' GHCR_USER='$GHCR_USER' \
   PROBE_PACKAGE='$PROBE_PACKAGE' CTX='$CTX' NS='$NS' \
   bash -c \"\$(printf '%s' '$REMOTE_B64' | base64 -d)\""
