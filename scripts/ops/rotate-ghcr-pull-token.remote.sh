#!/usr/bin/env bash
# rotate-ghcr-pull-token.remote.sh — UZAK TARAF gövdesi.
# Bu dosya doğrudan çalıştırılmaz; rotate-ghcr-pull-token.sh onu base64 ile
# uzak hosta taşır. PAT stdin ile gelir (argv/env/log'a asla girmez).
# Ayrı dosya olmasının sebebi teknik: gövdeyi $(cat <<EOF) içine gömmek,
# içindeki ")" karakterleri yüzünden bash komut-ikamesi ayrıştırıcısını bozar.
set -uo pipefail
IFS= read -r PAT || true
[ -z "${PAT:-}" ] && { echo "HATA: PAT uzak tarafa ulaşmadı." >&2; exit 2; }

mask() { printf '%s' "$1" | sed 's/./*/g' | cut -c1-8; }

# --- 1) DOĞRULAMA (Vault'a yazmadan önce) -------------------------------
# GHCR token exchange: PAT -> registry token, sonra gerçek manifest HEAD.
echo "== 1) PAT doğrulanıyor (Vault'a HENÜZ dokunulmadı) =="
BASIC=$(printf '%s:%s' "$GHCR_USER" "$PAT" | base64 -w0 2>/dev/null || printf '%s:%s' "$GHCR_USER" "$PAT" | base64)
TOKEN=$(curl -s --max-time 20 -H "Authorization: Basic $BASIC" \
  "https://ghcr.io/token?service=ghcr.io&scope=repository:${PROBE_PACKAGE}:pull" \
  | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')

if [ -z "${TOKEN:-}" ]; then
    echo "   SONUÇ: BAŞARISIZ — GHCR token alınamadı (PAT geçersiz mi?)." >&2
    echo "   Vault'a DOKUNULMADI; mevcut kimlik korundu." >&2
    exit 1
fi

CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json" \
  "https://ghcr.io/v2/${PROBE_PACKAGE}/manifests/latest")
echo "   manifest probe -> HTTP $CODE"

case "$CODE" in
    200|404)
        # 200 = çekilebiliyor. 404 = yetki VAR ama 'latest' tag'i yok (paket
        # digest-pinned) — bu da yetkinin çalıştığını gösterir; 401/403 değil.
        echo "   SONUÇ: GEÇERLİ (read:packages çalışıyor)"
        ;;
    401|403)
        echo "   SONUÇ: BAŞARISIZ — HTTP $CODE. PAT'te 'read:packages' scope'u yok" >&2
        echo "   ya da paket bu hesaba kapalı. Vault'a DOKUNULMADI." >&2
        exit 1
        ;;
    *)
        echo "   SONUÇ: BELİRSİZ (HTTP $CODE) — güvenli tarafta kalıp durduruldu." >&2
        echo "   Vault'a DOKUNULMADI." >&2
        exit 1
        ;;
esac

# --- 2) Vault'a yaz -----------------------------------------------------
echo "== 2) Vault'a yazılıyor ($VAULT_PATH) =="
VT=$(sudo -n jq -r '.root_token // empty' /srv/platform/secrets/backup-auth/vault-init-prod.json 2>/dev/null)
[ -z "${VT:-}" ] && VT=$(jq -r '.root_token // empty' /srv/platform/secrets/vault/test-active/vault-init-test.json 2>/dev/null)
[ -z "${VT:-}" ] && { echo "HATA: Vault token okunamadı." >&2; exit 2; }

# PAT stdin ile vault'a girer; argv'de görünmez (D43 deseni).
if ! printf '%s' "$PAT" | docker exec -i -e VT="$VT" "$VAULT_CONTAINER" \
     sh -c "VAULT_TOKEN=\$VT vault kv patch $VAULT_PATH username='$GHCR_USER' password=-" >/dev/null 2>&1; then
    echo "HATA: Vault yazımı başarısız." >&2
    exit 2
fi
echo "   yazıldı (değer basılmadı)"

# --- 3) ESO'yu hemen yenile --------------------------------------------
echo "== 3) ESO yenileniyor (30m interval beklenmeden) =="
kubectl --context "$CTX" -n "$NS" annotate externalsecret ghcr-pull \
  force-sync="$(date +%s)" --overwrite >/dev/null 2>&1 || true
sleep 12
READY=$(kubectl --context "$CTX" -n "$NS" get externalsecret ghcr-pull \
  -o jsonpath='{.status.conditions[0].status}' 2>/dev/null)
echo "   ExternalSecret Ready=$READY"

# --- 4) Node'da GERÇEK pull denemesi ------------------------------------
# En önemli adım: "secret render oldu" yetmez; kubelet gerçekten çekebiliyor mu.
echo "== 4) Node'da gerçek pull doğrulaması =="
kubectl --context "$CTX" -n "$NS" delete pod ghcr-pull-probe --ignore-not-found >/dev/null 2>&1
PROBE_IMG=$(kubectl --context "$CTX" -n "$NS" get deploy auth-service \
  -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
kubectl --context "$CTX" -n "$NS" run ghcr-pull-probe --restart=Never \
  --image="$PROBE_IMG" --overrides='{"spec":{"imagePullSecrets":[{"name":"ghcr-pull"}],"containers":[{"name":"ghcr-pull-probe","image":"'"$PROBE_IMG"'","command":["true"],"imagePullPolicy":"Always"}]}}' \
  >/dev/null 2>&1
RC=1
for _ in $(seq 1 12); do
    sleep 5
    PH=$(kubectl --context "$CTX" -n "$NS" get pod ghcr-pull-probe -o jsonpath='{.status.phase}' 2>/dev/null)
    WHY=$(kubectl --context "$CTX" -n "$NS" get pod ghcr-pull-probe \
          -o jsonpath='{.status.containerStatuses[0].state.waiting.reason}' 2>/dev/null)
    case "${WHY:-}" in
        ErrImagePull|ImagePullBackOff)
            echo "   SONUÇ: pull HÂLÂ BAŞARISIZ ($WHY)" >&2; RC=1; break ;;
    esac
    case "${PH:-}" in
        Succeeded|Running) echo "   SONUÇ: pull BAŞARILI (phase=$PH)"; RC=0; break ;;
    esac
done
kubectl --context "$CTX" -n "$NS" delete pod ghcr-pull-probe --ignore-not-found >/dev/null 2>&1

if [ "$RC" = "0" ]; then
    echo ""
    echo "PASS: GHCR pull kimliği döndürüldü ve gerçek pull ile doğrulandı."
    echo "      Artık backend imajları promote edilebilir (#2876 kapanabilir)."
else
    echo ""
    echo "FAIL: PAT geçerliydi ama node hâlâ çekemiyor — paket görünürlüğü veya" >&2
    echo "      ghcr-pull Secret render'ı incelenmeli." >&2
fi
exit $RC
