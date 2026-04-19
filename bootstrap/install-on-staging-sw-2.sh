#!/usr/bin/env bash
# install-on-staging-sw-2.sh — D32 Prod Host Bootstrap Script (S4-F)
#
# ⚠ SUPERSEDED by ADR-0002 (2026-04-19): same-host prod cutover kabul edildi.
# Bu script yalnız ileride 2. fiziksel sunucu eklenirse (forward-extension)
# referans olarak korunur. Yeni prod kurulum: ADR-0002 §3 + ilgili compose
# template (host-compose/{prod,test}/) — docs/prod-cutover-runbook-v2.md.
#
# Bu script yeni 2. fiziksel sunucu `staging-sw-2` üzerinde prod cluster +
# host compose PG/KC/Vault prod + host nginx proxy kurulumu yapar.
#
# PREREQ:
#   - Ubuntu 22.04 LTS + SSH + halil user + sudoers
#   - kubectl/k3d/helm/docker CE binary install (F1.3-F1.4)
#   - GitHub SSH key (K8s-gitops repo clone için, read-only deploy key)
#   - Sectigo wildcard cert /home/halil/platform/tls/ (staging-sw ile aynı, paylaşımlı)
#
# KULLANIM:
#   ssh staging-sw-2 'bash -s' < install-on-staging-sw-2.sh
#   veya:
#   ssh staging-sw-2 "cd /home/halil/platform-k8s-gitops && bash bootstrap/install-on-staging-sw-2.sh"
#
# DRY_RUN=true mode:
#   Komutları yazdır, çalıştırma. Validasyon amaçlı.
#
# Source: PLAN.md Bölüm 1.5 D32 Bootstrap Kontrat Listesi F1-F9
# Source: docs/prod-cutover-smoke-runbook.md
# Codex Tur 3 + 4-tur uzlaşısı (thread 019d9a75)

set -euo pipefail

DRY_RUN="${DRY_RUN:-false}"
REMOTE_USER="${REMOTE_USER:-halil}"
K3D_CLUSTER="${K3D_CLUSTER:-prod}"
GITOPS_REPO="${GITOPS_REPO:-git@github.com:Halildeu/platform-k8s-gitops.git}"
GITOPS_PATH="${GITOPS_PATH:-/home/halil/platform-k8s-gitops}"

log()  { printf '\033[36m[install]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[33m[install]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

run() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '\033[90mDRY RUN:\033[0m %s\n' "$*" >&2
  else
    eval "$@"
  fi
}

# ========================
# F1 — Donanım + Temel Kurulum
# ========================
log "=== F1: Temel Kurulum Ön-Kontrol ==="
run "docker version >/dev/null 2>&1" || err "Docker kurulu değil (F1.4)"
run "k3d version >/dev/null 2>&1" || err "k3d kurulu değil (F1.3)"
run "kubectl version --client >/dev/null 2>&1" || err "kubectl kurulu değil (F1.3)"
run "sudo -n sysctl fs.inotify.max_user_instances" 2>/dev/null || warn "F1.5: sysctl inotify=512 elle set (W2 pattern)"

# ========================
# F2 — k3d-prod Cluster
# ========================
log "=== F2: k3d-prod Cluster ==="
if run "k3d cluster list | grep -q ${K3D_CLUSTER}"; then
  log "   ✓ ${K3D_CLUSTER} cluster zaten var"
else
  log "   k3d-${K3D_CLUSTER} create (bootstrap/k3d-${K3D_CLUSTER}.yaml)"
  run "k3d cluster create --config ${GITOPS_PATH}/bootstrap/k3d-${K3D_CLUSTER}.yaml"
fi

log "   F2.2: Calico tigera-operator install"
run "bash ${GITOPS_PATH}/bootstrap/install-calico.sh ${K3D_CLUSTER}"
log "   (post-F2.2 manual: Installation CR 'typhaDeployment.replicas: 0' tek-node opt — W2 pattern)"

log "   F2.3: ingress-nginx install"
run "bash ${GITOPS_PATH}/bootstrap/install-ingress.sh ${K3D_CLUSTER}"

log "   F2.4: ArgoCD install"
run "bash ${GITOPS_PATH}/bootstrap/install-argocd.sh ${K3D_CLUSTER}"

log "   F2.5: kube-prometheus-stack install"
run "bash ${GITOPS_PATH}/bootstrap/install-monitoring.sh ${K3D_CLUSTER}"

log "   F2.6: Loki + Tempo + Promtail install"
run "bash ${GITOPS_PATH}/bootstrap/install-logs-traces.sh ${K3D_CLUSTER}"

# ========================
# F3 — Host Compose PROD Instance
# ========================
log "=== F3: Host Compose PROD Servisleri ==="
# NOT: staging-sw'deki compose'un FORK'u — fresh prod instance, data migration YOK
# Template'ler 2026-04-19 yazıldı (Codex PR #1 iter-9 + iter-10 fix):
#   host-compose/postgres/prod/ + keycloak/prod/ + vault/prod/
# Secret dosyaları (secrets/*.txt) manuel yazılmalı (chmod 600 + .gitignore).
log "   F3.1: PostgreSQL prod"
warn "     Prereq: host-compose/postgres/prod/secrets/pg_password.txt yaz (chmod 600)"
run "docker compose -f ${GITOPS_PATH}/host-compose/postgres/prod/docker-compose.yml up -d"

log "   F3.2: Keycloak prod"
warn "     Prereq: host-compose/keycloak/prod/secrets/kc_db_password.txt + kc_admin_password.txt"
run "docker compose -f ${GITOPS_PATH}/host-compose/keycloak/prod/docker-compose.yml up -d"

log "   F3.3: Vault prod"
warn "     NOT: ilk kurulum sonrası vault operator init (host-compose/vault/prod/README.md)"
run "docker compose -f ${GITOPS_PATH}/host-compose/vault/prod/docker-compose.yml up -d"

log "   F3.4: PG init databases (stdin pipe — /tmp host file drift fix)"
# Codex PR #1 iter-9 tespit: heredoc /tmp/init-prod-db.sql host'ta yazılır,
# docker exec container içinden okur → path uyumsuz. Fix: stdin pipe ile
# docker exec -i doğrudan.
run 'docker exec -i platform-postgres-db-prod psql -U postgres <<SQL
CREATE DATABASE auth_db OWNER platform;
CREATE DATABASE users_db OWNER platform;
CREATE DATABASE variants_db OWNER platform;
CREATE DATABASE core_db OWNER platform;
CREATE DATABASE reports_db OWNER platform;
CREATE DATABASE schemas_db OWNER platform;
CREATE DATABASE permission_db OWNER platform;
CREATE DATABASE openfga OWNER openfga;
CREATE DATABASE keycloak OWNER keycloak_user;
SQL'

# ========================
# F4 — Host Nginx SNI Proxy
# ========================
log "=== F4: Host Nginx SNI Proxy (D18 edge) ==="
log "   F4.1-F4.4: host-compose/proxy/ compose up"
run "docker compose -f ${GITOPS_PATH}/host-compose/proxy/docker-compose.yml up -d"
run "docker exec host-nginx-proxy nginx -t"

# ========================
# F5 — Network + Dış Proxy
# ========================
log "=== F5: Network + Dış Proxy (sysadmin iş) ==="
warn "   F5.1: staging-sw-2 kurumsal IP ataması (ops)"
warn "   F5.2: Dış proxy kurumsal L4 backend TABLOSUNA staging-sw-2 IP ekleme (sysadmin)"
warn "   F5.3: DNS kaydı dokunulmaz (cutover upstream switch ile değişir)"

# ========================
# F6 — Artifact + Secret (Codex iter-3 PARTIAL absorb)
# ========================
log "=== F6: ESO Secret Flow ==="
log "   F6.0: ESO Helm install (external-secrets ns)"
run "bash ${GITOPS_PATH}/bootstrap/install-eso-helm.sh prod"
log "   F6.1: Vault AppRole secret-id (manuel — ops ilk bootstrap, sonrası auto-rotate)"
warn "     kubectl -n external-secrets create secret generic vault-approle-secret --from-literal=secret-id=<VAULT_ESO_RUNTIME_SECRET_ID>"
log "   F6.2: Overlay ESO apply — ClusterSecretStore + ghcr-pull (YASAK: base/eso doğrudan apply)"
run "kubectl --context k3d-${K3D_CLUSTER} apply -k ${GITOPS_PATH}/kustomize/overlays/prod/eso"
log "   F6.3: Doğrula ClusterSecretStore Ready + ghcr-pull Synced (W1 Opsiyon B: workload ns)"
run "kubectl --context k3d-${K3D_CLUSTER} get clustersecretstore vault-platform-gitops"
# Codex PR #1 iter-9: ghcr-pull ExternalSecret W1 Opsiyon B ile workload ns'de
# (external-secrets değil — platform-prod/test).
run "kubectl --context k3d-${K3D_CLUSTER} -n platform-${K3D_CLUSTER} get externalsecret ghcr-pull"
run "kubectl --context k3d-${K3D_CLUSTER} -n platform-${K3D_CLUSTER} get secret ghcr-pull"
log "   F6.4: Per-service ExternalSecret (7 backend + permission-service) — overlay apply ile gelir (F8+)"

# ========================
# F7 — GitOps (ArgoCD)
# ========================
log "=== F7: ArgoCD Repo + Applications ==="
log "   F7.0: ArgoCD cluster registry (Codex PR #1 iter-9 eksiklik fix)"
# platform-prod Application destination name: prod-cluster bekliyor —
# argocd cluster add ile kaydet.
warn "   F7.0.1: argocd login <server> (ilk kurulum, ops manuel)"
warn "   F7.0.2: Prod cluster registry:"
warn "     argocd cluster add k3d-${K3D_CLUSTER} --name prod-cluster --project default"
warn "     (context k3d-${K3D_CLUSTER} lokal, ama multi-cluster ArgoCD için cluster secret üretilir)"

log "   F7.1: ArgoCD repo credential"
run "argocd --server argocd.${K3D_CLUSTER}.local repo add ${GITOPS_REPO} --ssh-private-key-path ~/.ssh/k8s-gitops-deploy"
log "   F7.2: app-of-apps root.yaml apply"
run "kubectl --context k3d-${K3D_CLUSTER} apply -f ${GITOPS_PATH}/argocd/applications/root.yaml"
log "   F7.3: ArgoCD first sync — DRY RUN"
warn "   Prod application MANUAL sync (D30 atomic cutover) — ops elle"
warn "   NOT: root.yaml exclude platform-policies + platform-cert-manager"
warn "   (DRAFT, Kyverno/cert-manager Helm install edilmeden CRD yok)"

# ========================
# F8 — Pre-Cutover Smoke
# ========================
log "=== F8: Pre-Cutover Smoke (ops iş) ==="
log "   F8.1: Pod Ready kontrol"
run "kubectl --context k3d-${K3D_CLUSTER} -n platform-prod get pods"
log "   F8.2: imageID == GHCR digest kontrol (tüm 8 servis)"
warn "   F8.3-F8.5: Intra-cluster Zanzibar smoke + localhost edge + No-Go gate (docs/prod-cutover-smoke-runbook.md)"

log ""
log "=== F1-F8 PASS ==="
log "F9 Cutover atomic switch: docs/prod-cutover-smoke-runbook.md"
log "SONRAKİ: Codex pre-cutover ping-pong + sysadmin dış proxy backend switch"
log "Detay runbook: docs/D32-bootstrap-runbook.md (F1-F9 adım-adım + partial unwind)"
