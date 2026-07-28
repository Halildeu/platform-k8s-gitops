#!/usr/bin/env bash
set -euo pipefail

# Frontend promosyon preflight'ı: hedeflenen imaj digest'i gerçekten ÇEKİLEBİLİR mi?
#
# Neden (gitops#2885, 2026-07-24): promosyon PR'ları CI'ı yeşil geçiyor, merge
# oluyor, ArgoCD deployment'ı yeni digest'e çeviriyor — ama imaj node'da yok ve
# cluster GHCR'dan çekemiyorsa yeni pod ImagePullBackOff'a düşer. Eski pod
# cache'ten ayakta kaldığı için KESİNTİ OLMAZ ve hata SESSİZ kalır: PR yeşil,
# merge başarılı, kullanıcı eski UI'ı görür. Bu betik o sınıfı fail-closed yapar.
#
# Sıra:
#   1) imaj node'da zaten var mı (cache) → rollout çalışır, OK
#   2) yoksa registry'den cluster'ın kimliğiyle manifest çekilebiliyor mu → OK
#   3) ikisi de değilse → FAIL (ArgoCD mutasyonundan ÖNCE)
#
# Salt-okunur: yalnız GET/HEAD. Credential asla stdout/stderr'a yazılmaz.

TEST_CONTEXT="${TEST_CONTEXT:-k3d-test}"
TEST_NAMESPACE="${TEST_NAMESPACE:-platform-test}"
PULL_SECRET_NAME="${PULL_SECRET_NAME:-ghcr-pull}"
NODE_CONTAINER="${NODE_CONTAINER:-k3d-test-server-0}"

DEPLOYMENT_JSON="${1:-}"
[[ -n "$DEPLOYMENT_JSON" && -f "$DEPLOYMENT_JSON" ]] || {
  echo "usage: $0 <rendered-deployment.json>" >&2
  exit 2
}

image="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["spec"]["template"]["spec"]["containers"][0]["image"])
' "$DEPLOYMENT_JSON")"

[[ -n "$image" ]] || { echo "::error::desired image not found in render" >&2; exit 1; }

# Digest zorunlu (D30 immutable artifact): tag-only pin kabul edilmez.
case "$image" in
  *@sha256:*) ;;
  *) echo "::error::desired image is not digest-pinned: ${image%%@*}" >&2; exit 1 ;;
esac

digest="${image##*@}"
ref_no_digest="${image%@*}"          # repo[:tag]
repo_with_host="${ref_no_digest%%:*}" # ghcr.io/owner/name  (tag'i at)
# Yalnız ghcr.io bu betiğin kapsamında; başka registry'ler sessizce geçmez.
case "$repo_with_host" in
  ghcr.io/*) ;;
  *) echo "::notice::non-GHCR image, availability preflight skipped: $repo_with_host"; exit 0 ;;
esac
repo_path="${repo_with_host#ghcr.io/}"

echo "preflight: desired ${repo_with_host}@${digest:0:19}…"

# --- 1) Node cache'i -----------------------------------------------------------
node_has_image=false
if docker exec "$NODE_CONTAINER" crictl images -o json >/tmp/pf-node-images.json 2>/dev/null; then
  if python3 -c '
import json, sys
digest, repo = sys.argv[1], sys.argv[2]
imgs = json.load(open("/tmp/pf-node-images.json")).get("images", [])
hit = any(
    rd.startswith(repo + "@") and rd.endswith(digest)
    for i in imgs for rd in i.get("repoDigests", [])
)
raise SystemExit(0 if hit else 1)
' "$digest" "$repo_with_host"; then
    node_has_image=true
  fi
else
  echo "::notice::node image inventory unavailable ($NODE_CONTAINER); registry probe is authoritative"
fi

if [[ "$node_has_image" == true ]]; then
  echo "OK: digest already present on node cache — rollout can proceed"
  exit 0
fi

echo "digest not in node cache; probing registry with the cluster's own identity"

# --- 2) Registry probe (cluster kimliği) --------------------------------------
# Credential yalnız değişkende tutulur; hiçbir çıktıya yazılmaz.
basic_auth=""
if secret_json="$(kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" \
      get secret "$PULL_SECRET_NAME" -o json 2>/dev/null)"; then
  basic_auth="$(printf '%s' "$secret_json" | python3 -c '
import base64, json, sys
try:
    s = json.load(sys.stdin)
    cfg = json.loads(base64.b64decode(s["data"][".dockerconfigjson"]))
    print(cfg.get("auths", {}).get("ghcr.io", {}).get("auth", ""))
except Exception:
    print("")
')"
fi

token_url="https://ghcr.io/token?scope=repository:${repo_path}:pull&service=ghcr.io"
if [[ -n "$basic_auth" ]]; then
  identity="imagePullSecret/${PULL_SECRET_NAME}"
  token="$(curl -fsS -H "Authorization: Basic ${basic_auth}" "$token_url" 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' 2>/dev/null || true)"
else
  identity="anonymous (no ${PULL_SECRET_NAME} secret in ${TEST_NAMESPACE})"
  token="$(curl -fsS "$token_url" 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' 2>/dev/null || true)"
fi
basic_auth=""

status=000
if [[ -n "$token" ]]; then
  status="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${token}" \
    -H 'Accept: application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json' \
    "https://ghcr.io/v2/${repo_path}/manifests/${digest}" 2>/dev/null || echo 000)"
fi
token=""

if [[ "$status" == "200" ]]; then
  echo "OK: registry serves the digest to ${identity}"
  exit 0
fi

cat >&2 <<EOF
::error::image is NOT retrievable — promotion would silently fail to roll out
  image     : ${repo_with_host}@${digest}
  node cache: MISS
  registry  : HTTP ${status} as ${identity}
  etki      : ArgoCD deployment'ı bu digest'e çevirir, yeni pod ImagePullBackOff
              olur; eski pod cache'ten ayakta kaldığı için kesinti görünmez ve
              değişiklik canlıya HİÇ inmez.
  çözüm     : paket erişimini düzeltin (public görünürlük veya read:packages
              yetkili imagePullSecret) — gitops#2885
EOF
exit 1
