#!/usr/bin/env bash
# ArgoCD-yönetimli overlay'ler için post-merge deterministik rollout bekleyicisi.
#
# Neden (gitops#3316, 2026-08-01 canlı kanıt):
#   kustomize/overlays/test ağacı (activation/* dahil) ArgoCD `platform-test`
#   Application'ı tarafından automated + selfHeal + ServerSideApply=true ile
#   yönetilir. Bu ağaca manuel `kubectl apply -k` YARIŞI KAYBEDER:
#     17:59:56 manuel apply eski digest'i canlıya yazdı (PATCH body kanıtlı,
#     T+0'da deployment'ta görünür); 18:00:02'de ArgoCD selfHeal
#     (initiatedBy: automated) git state'ine geri çevirdi — 6 saniye içinde.
#   ArgoCD git'i timeout.reconciliation=180s aralıkla poll eder; merge'den
#   hemen sonra hedef revision bayattır → manuel apply edilen YENİ digest bile
#   ArgoCD'nin cache'indeki ESKİ git state'ine geri çevrilir. Operatör bunu
#   "ilk apply yazmadı, ikinci apply yazdı" (sessiz no-op) olarak görür.
#   `--server-side --force-conflicts` da ÇÖZÜM DEĞİLDİR: yazma yine ~saniyeler
#   içinde selfHeal tarafından ezilir; yalnız "missing last-applied" uyarılarını
#   susturur (uyarı semptomdur; SSA anotasyonu hiç yazmaz — kök sebep
#   dual-writer'dır).
#
# Doğru akış (tek-yazar GitOps):
#   merge → git pull → bu script (refresh annotate + revision/Synced/Healthy
#   bekle) → gerekirse scripts/deploy/verify-pod-digest.sh ile canlı pod
#   digest kanıtı.
#
# Kullanım:
#   argocd-app-sync-wait.sh \
#     [--app platform-test] \
#     [--argocd-context k3d-prod] \
#     [--revision <sha>] \
#     [--timeout 300]
#
#   --revision verilmezse script'in içinde bulunduğu repo checkout'unun HEAD'i
#   beklenir (operatör önce git pull yapmış olmalı). Checkout çözülemezse
#   fail-loud.
#
# Exit codes:
#   0 = app hedef revision'da Synced + Healthy
#   1 = timeout / argüman hatası / revision çözülemedi

set -euo pipefail

APP="platform-test"
ARGOCD_CONTEXT="k3d-prod"
REVISION=""
TIMEOUT="300"
POLL_INTERVAL="5"

usage() {
  cat >&2 <<'EOF'
Kullanım: argocd-app-sync-wait.sh \
  [--app platform-test] \
  [--argocd-context k3d-prod] \
  [--revision <sha>] \
  [--timeout 300] \
  [--poll-interval 5]

--revision verilmezse script'in bulunduğu repo checkout'unun HEAD'i beklenir
(önce git pull). Ayrıntılı gerekçe: script başlık yorumu + gitops#3316.
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app) APP="$2"; shift 2 ;;
    --argocd-context) ARGOCD_CONTEXT="$2"; shift 2 ;;
    --revision) REVISION="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --poll-interval) POLL_INTERVAL="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "FAIL: bilinmeyen argüman: $1" >&2; usage ;;
  esac
done

for cmd in kubectl git; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "FAIL: gerekli komut yok: $cmd" >&2; exit 1; }
done

if [[ -z "$REVISION" ]]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REVISION="$(git -C "$script_dir" rev-parse HEAD 2>/dev/null)" || {
    echo "FAIL: --revision verilmedi ve repo HEAD çözülemedi ($script_dir)" >&2
    exit 1
  }
  echo "revision: checkout HEAD kullanılıyor: $REVISION" >&2
fi

if ! [[ "$REVISION" =~ ^[0-9a-f]{7,40}$ ]]; then
  echo "FAIL: geçersiz revision biçimi: $REVISION" >&2
  exit 1
fi

# Refresh annotation: ArgoCD'yi 180s git poll penceresini beklemeden hemen
# yeni commit'i fetch etmeye zorlar. ArgoCD işleyince anotasyonu kendisi siler.
kubectl --context "$ARGOCD_CONTEXT" -n argocd annotate application "$APP" \
  argocd.argoproj.io/refresh=normal --overwrite >/dev/null
echo "refresh tetiklendi: app=$APP hedef=$REVISION timeout=${TIMEOUT}s" >&2

deadline=$(( $(date +%s) + TIMEOUT ))
while true; do
  read -r sync_status health_status live_rev op_phase < <(
    kubectl --context "$ARGOCD_CONTEXT" -n argocd get application "$APP" \
      -o jsonpath='{.status.sync.status} {.status.health.status} {.status.sync.revision} {.status.operationState.phase}' 2>/dev/null
  ) || true
  sync_status="${sync_status:-?}"; health_status="${health_status:-?}"
  live_rev="${live_rev:-?}"; op_phase="${op_phase:-?}"

  echo "$(date -u +%H:%M:%S) sync=$sync_status health=$health_status rev=${live_rev:0:9} op=$op_phase" >&2

  if [[ "$sync_status" == "Synced" && "$health_status" == "Healthy" && "$live_rev" == "$REVISION"* ]]; then
    echo "OK: $APP $REVISION revision'ında Synced + Healthy"
    exit 0
  fi
  if (( $(date +%s) >= deadline )); then
    echo "FAIL: timeout (${TIMEOUT}s) — son durum: sync=$sync_status health=$health_status rev=$live_rev op=$op_phase" >&2
    echo "İpucu: 'kubectl --context $ARGOCD_CONTEXT -n argocd get application $APP -o yaml' ile status.conditions incele." >&2
    exit 1
  fi
  sleep "$POLL_INTERVAL"
done
