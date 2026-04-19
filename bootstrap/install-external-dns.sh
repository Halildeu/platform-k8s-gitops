#!/usr/bin/env bash
# ExternalDNS — otomatik DNS kayıt Helm install
# DRAFT: Kurumsal DNS provider entegrasyonu netleşince aktif.
# Şu an manuel A record (Sectigo wildcard cert + DNS sysadmin).
# Usage: bash bootstrap/install-external-dns.sh <test|prod>
set -euo pipefail

CLUSTER="${1:-}"

if [[ "${CLUSTER}" != "test" && "${CLUSTER}" != "prod" ]]; then
  echo "Usage: $0 <test|prod>"
  exit 1
fi

CTX="k3d-${CLUSTER}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VALUES="${REPO_DIR}/helm-values/external-dns/values.yaml"

echo "=== ExternalDNS Install → ${CTX} ==="
echo "WARN: DRAFT — kurumsal DNS provider + TSIG secret ayarlanmış olmalı."
echo "Prereq:"
echo "  - Kurumsal DNS server IP + TSIG key (sysadmin ile koordine)"
echo "  - values.yaml'da rfc2136.host ve tsigSecret doldurulmuş"
echo "  - Vault kv/platform/external-dns/tsig seed edilmiş"
echo ""
read -rp "Devam et? (y/N): " CONFIRM
if [[ "${CONFIRM}" != "y" ]]; then
  echo "Abort."
  exit 0
fi

helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/ 2>/dev/null || true
helm repo update external-dns

kubectl --context "${CTX}" create namespace external-dns --dry-run=client -o yaml \
  | kubectl --context "${CTX}" apply -f -

helm --kube-context "${CTX}" upgrade --install external-dns external-dns/external-dns \
  --namespace external-dns \
  --values "${VALUES}" \
  --wait --timeout 3m

kubectl --context "${CTX}" -n external-dns wait --for=condition=Available \
  deployment/external-dns --timeout=120s

cat <<EOF

=== ExternalDNS Install PASS — ${CTX} ===

NEXT STEPS:

1. Test ingress DNS auto-record:
   kubectl --context ${CTX} get ingress -A
   # Ingress host FQDN ExternalDNS tarafından DNS server'a yazılır

2. Doğrulama (DNS lookup):
   dig @<DNS_SERVER_IP> testai.acik.com
   # Beklenen: Ingress LoadBalancer/hostPort IP cevabı

3. Log monitoring:
   kubectl --context ${CTX} -n external-dns logs -f deployment/external-dns

4. Log'da "UPSERT" (create/update) veya "DELETE" görülür:
   txtOwnerId: platform-k8s-gitops (TXT record ExternalDNS ownership)

UYARI:
- policy: sync default — ingress delete → DNS kayıt da silinir (prod riskli)
- Prod için policy: upsert-only önerilir (DNS silme manuel)
- TSIG secret döner (çeyreklik) — Vault seed + pod restart

EOF
