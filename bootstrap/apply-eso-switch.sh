#!/usr/bin/env bash
# Per-service ExternalSecret switch automation
# Her servis base/apps/<svc>/kustomization.yaml dosyasında secret-stub.yaml
# referansını externalsecret.yaml ile değiştirir (idempotent).
#
# Prereq:
#   - base/apps/<svc>/externalsecret.yaml mevcut (her servis için yazılı)
#   - ESO + ClusterSecretStore Ready (bootstrap/install-eso-helm.sh + overlay)
#   - Vault kv/platform/<svc> path'leri seed edilmiş (S2-B1 preflight)
#
# Usage: bash bootstrap/apply-eso-switch.sh <test|prod>
# Codex iter-6 yedek iş (b) — repo-side automation, canlı apply değil.

set -euo pipefail

CLUSTER="${1:-}"

if [[ "${CLUSTER}" != "test" && "${CLUSTER}" != "prod" ]]; then
  echo "ERROR: Usage: $0 <test|prod>"
  echo "  Verildi: '${CLUSTER}'"
  exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SERVICES=(
  auth-service
  user-service
  variant-service
  core-data-service
  report-service
  schema-service
  permission-service
)

echo "=== ES Switch Automation → ${CLUSTER} cluster ==="
echo "Repo: ${REPO_DIR}"
echo

SWAPPED=0
SKIPPED=0
MISSING=0

for svc in "${SERVICES[@]}"; do
  KUST="${REPO_DIR}/kustomize/base/apps/${svc}/kustomization.yaml"
  ES_FILE="${REPO_DIR}/kustomize/base/apps/${svc}/externalsecret.yaml"

  if [[ ! -f "${KUST}" ]]; then
    echo "⚠ ${svc}: kustomization.yaml yok, skip"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # Idempotent: zaten swapped mi kontrol et
  if grep -q "externalsecret.yaml" "${KUST}" && ! grep -q "secret-stub.yaml" "${KUST}"; then
    echo "✅ ${svc}: already swapped (externalsecret.yaml, no secret-stub)"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  # ExternalSecret dosyası var mı?
  if [[ ! -f "${ES_FILE}" ]]; then
    echo "❌ ${svc}: externalsecret.yaml YOK (${ES_FILE})"
    echo "   Manuel yaz gerek — swap atlanıyor"
    MISSING=$((MISSING + 1))
    continue
  fi

  # Swap uygula
  sed -i.bak 's|secret-stub.yaml|externalsecret.yaml|g' "${KUST}"
  rm "${KUST}.bak"
  echo "✓ ${svc}: secret-stub.yaml → externalsecret.yaml"
  SWAPPED=$((SWAPPED + 1))
done

echo
echo "=== Özet ==="
echo "Swapped: ${SWAPPED}"
echo "Skipped: ${SKIPPED}"
echo "Missing: ${MISSING}"

if [[ ${MISSING} -gt 0 ]]; then
  echo
  echo "⚠ ${MISSING} servis externalsecret.yaml eksik. Yaz + tekrar çalıştır."
  exit 1
fi

cat <<EOF

=== NEXT STEPS ===

1. Git diff kontrol:
   git diff kustomize/base/apps/*/kustomization.yaml

2. Commit (eğer değişiklik varsa):
   git add -A
   git commit -m "feat(eso): switch per-service secret-stub → externalsecret (${CLUSTER})"

3. Overlay apply (canlı — ESO Synced olacak):
   kubectl --context k3d-${CLUSTER} apply -k kustomize/overlays/${CLUSTER}

4. Doğrula (7 ExternalSecret Synced + Secret'ların Vault'tan geldiği):
   kubectl --context k3d-${CLUSTER} -n platform-${CLUSTER} get externalsecret
   # Beklenen: 7 satır, STATUS=SecretSynced, READY=True

   kubectl --context k3d-${CLUSTER} -n platform-${CLUSTER} get secret \\
     -l app.kubernetes.io/component=backend

5. Rolling restart (ConfigMap env pickup için):
   kubectl --context k3d-${CLUSTER} -n platform-${CLUSTER} rollout restart deploy

6. Smoke (docs/S1-S2-acceptance-smoke-runbook.md 3 katman D29):
   # Katman 1 Up: pod Running
   # Katman 2 Functional: /actuator/health + Hub /authz/version 401
   # Katman 3 Zanzibar-ready: external edge deny + allow synthetic

ROLLBACK (swap geri al):
   git checkout -- kustomize/base/apps/*/kustomization.yaml
   # veya: git revert <this-commit>
EOF
