#!/usr/bin/env bash
# install-on-staging-sw.sh — Paralel testai.acik.com kurulumu (staging-sw)
#
# Mevcut ai.acik.com (compose stack) HİÇ DOKUNULMAZ. Yeni izole stack:
#   - k3d-test cluster (Docker container, ayrı network)
#   - Sectigo wildcard cert TLS Secret (paylaşılır, zaten *.acik.com)
#   - platform-web-nginx default.conf'a EK server block (testai.acik.com)
#   - nginx hot reload (graceful, atomik backup ile)
#
# Idempotent: her adımı pre-check ile atlanabilir.
# Dry-run: DRY_RUN=true ./install-on-staging-sw.sh
#
# Gereksinim:
#   - ssh staging-sw alias çalışıyor olmalı
#   - Sectigo cert dosyaları lokalde mevcut
#   - DNS testai.acik.com → 10.9.10.53 zaten ayarlı (sysadmin ticket)

set -euo pipefail

# ============================================================
# Konfigürasyon (env ile override)
# ============================================================
REMOTE="${REMOTE:-staging-sw}"
DRY_RUN="${DRY_RUN:-false}"
CERT_LOCAL="${CERT_LOCAL:-/Users/halilkocoglu/Downloads/STAR_acik_com1/Nginx/STAR_acik_com.crt}"
KEY_LOCAL="${KEY_LOCAL:-/Users/halilkocoglu/Downloads/STAR_acik_com1/Nginx/STAR_acik_com.key}"
TEST_PORT="${TEST_PORT:-9080}"               # k3d-test ingress HTTP host port
REPO_DIR_REMOTE="${REPO_DIR_REMOTE:-/home/halil/platform-k8s-gitops}"
NGX_CONF_HOST="${NGX_CONF_HOST:-/home/halil/platform/web/nginx/default.conf}"
LOCAL_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ============================================================
# Yardımcılar
# ============================================================
log()  { printf '\033[36m[setup]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[33m[setup]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[31m[setup]\033[0m %s\n' "$*" >&2; exit 1; }

run() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '\033[90mDRY:\033[0m %s\n' "$*" >&2
  else
    eval "$@"
  fi
}

sshrun() {
  # ssh non-login shell — PATH'i explicit set et (~/.local/bin için)
  local cmd="$*"
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '\033[90mDRY ssh:\033[0m %s\n' "${cmd}" >&2
  else
    ssh -o BatchMode=no "${REMOTE}" "export PATH=\$HOME/.local/bin:\$PATH; ${cmd}"
  fi
}

# ============================================================
# 1/14 — Pre-flight
# ============================================================
log "1/14 pre-flight: ssh + docker + compose stack"
ssh -o ConnectTimeout=5 -o BatchMode=no "${REMOTE}" 'true' >/dev/null 2>&1 \
  || err "ssh ${REMOTE} bağlanamadı"
sshrun 'docker --version >/dev/null 2>&1' \
  || err "docker yok (staging-sw)"
sshrun 'docker ps --format "{{.Names}}" | grep -q ^platform-web-nginx' \
  || err "platform-web-nginx çalışmıyor — beklenmedik durum, manuel kontrol"
sshrun 'test -f /home/halil/platform/tls/ai.acik.com/fullchain.pem' \
  || err "Sectigo cert host'ta yok (/home/halil/platform/tls/ai.acik.com/)"
log "   ✓ ssh + docker + compose + host cert OK"

[[ -f "${CERT_LOCAL}" ]] || err "Local cert yok: ${CERT_LOCAL}"
[[ -f "${KEY_LOCAL}" ]]  || err "Local key yok: ${KEY_LOCAL}"

# ============================================================
# 2/14 — Disk & güvenli prune
# ============================================================
log "2/14 disk durumu + güvenli prune"
DISK_USE=$(sshrun "df -h / | tail -1 | awk '{print \$5}' | tr -d %")
log "   disk kullanımı: ${DISK_USE}%"
[[ "${DISK_USE}" -lt 90 ]] || err "Disk %${DISK_USE} dolu — artırma gerek (200 GB ETA 16 Nisan)"
log "   docker image prune -f (sadece dangling)"
run "sshrun 'docker image prune -f'" >/dev/null

# ============================================================
# 3-5/14 — Binaries (user-level: ~/.local/bin, sudo gerekmez)
# ============================================================
log "3/14 k3d binary (~/.local/bin)"
if sshrun 'command -v k3d >/dev/null 2>&1 || test -x ~/.local/bin/k3d'; then
  K3D_VER=$(sshrun 'export PATH=$HOME/.local/bin:$PATH; k3d version 2>/dev/null | head -1')
  log "   ✓ zaten kurulu: ${K3D_VER}"
else
  log "   yükleniyor..."
  run "sshrun 'mkdir -p ~/.local/bin && curl -fsSL https://github.com/k3d-io/k3d/releases/download/v5.7.5/k3d-linux-amd64 -o ~/.local/bin/k3d && chmod +x ~/.local/bin/k3d'"
fi

log "4/14 kubectl binary (~/.local/bin)"
if sshrun 'command -v kubectl >/dev/null 2>&1 || test -x ~/.local/bin/kubectl'; then
  log "   ✓ zaten kurulu"
else
  log "   yükleniyor..."
  run "sshrun 'mkdir -p ~/.local/bin && KCTL_VER=\$(curl -fsSL https://dl.k8s.io/release/stable.txt) && curl -fsSL -o ~/.local/bin/kubectl https://dl.k8s.io/release/\$KCTL_VER/bin/linux/amd64/kubectl && chmod +x ~/.local/bin/kubectl'"
fi

log "5/14 helm binary (~/.local/bin)"
if sshrun 'command -v helm >/dev/null 2>&1 || test -x ~/.local/bin/helm'; then
  log "   ✓ zaten kurulu"
else
  log "   yükleniyor..."
  run "sshrun 'mkdir -p ~/.local/bin /tmp/helm-install && cd /tmp/helm-install && curl -fsSL https://get.helm.sh/helm-v3.16.3-linux-amd64.tar.gz | tar -xz && mv linux-amd64/helm ~/.local/bin/helm && chmod +x ~/.local/bin/helm && rm -rf /tmp/helm-install'"
fi

# PATH (sonraki adımlar için ssh'da non-login shell — PATH explicit gerek)
SSH_PATH_PREFIX='export PATH=$HOME/.local/bin:$PATH;'
log "   PATH prefix sonraki ssh komutlarına eklenecek: ${SSH_PATH_PREFIX}"

# ============================================================
# 6/14 — Repo sync (git clone/pull; D12: remote aktif 2026-04-15)
# ============================================================
REPO_URL="${REPO_URL:-git@github.com:Halildeu/platform-k8s-gitops.git}"
log "6/14 repo sync (git: ${REPO_URL})"

# GitHub SSH port 22 kurum firewall'da kapalı — sunucuda da port 443 config gerek
sshrun 'grep -q "Host github.com" ~/.ssh/config 2>/dev/null' || {
  log "   sunucuya github.com SSH config (port 443) ekleniyor"
  run "sshrun 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && printf \"\\nHost github.com\\n  HostName ssh.github.com\\n  User git\\n  Port 443\\n  StrictHostKeyChecking accept-new\\n\" >> ~/.ssh/config'"
}

if sshrun "test -d ${REPO_DIR_REMOTE}/.git"; then
  log "   repo mevcut → git fetch + reset (yerel değişiklik ezilir)"
  run "sshrun 'cd ${REPO_DIR_REMOTE} && git fetch origin && git reset --hard origin/main && git clean -fd'"
else
  log "   ilk clone"
  run "sshrun 'mkdir -p \$(dirname ${REPO_DIR_REMOTE}) && git clone ${REPO_URL} ${REPO_DIR_REMOTE}'"
fi
# Commit doğrula
sshrun "cd ${REPO_DIR_REMOTE} && git log --oneline -1" || log "   uyarı: git log alınamadı"

# ============================================================
# 7/14 — k3d-test cluster (port ${TEST_PORT}, mevcut compose çakışmaz)
# ============================================================
log "7/14 k3d-test cluster (host port: ${TEST_PORT})"
if sshrun "k3d cluster list --no-headers 2>/dev/null | awk '{print \$1}' | grep -qx test"; then
  log "   ✓ zaten var"
else
  run "sshrun 'k3d cluster create test \\
    --servers 1 --agents 0 \\
    --image rancher/k3s:v1.31.2-k3s1 \\
    --network platform-test-net \\
    --api-port 127.0.0.1:7443 \\
    --port \"127.0.0.1:${TEST_PORT}:80@server:0\" \\
    --k3s-arg \"--disable=traefik@server:*\" \\
    --k3s-arg \"--disable=servicelb@server:*\" \\
    --k3s-arg \"--disable=metrics-server@server:*\" \\
    --k3s-arg \"--flannel-backend=none@server:*\" \\
    --k3s-arg \"--disable-network-policy@server:*\" \\
    --k3s-arg \"--cluster-cidr=10.44.0.0/16@server:*\" \\
    --k3s-arg \"--service-cidr=10.45.0.0/16@server:*\"'"
fi

# ============================================================
# 8/14 — Calico CNI
# ============================================================
log "8/14 Calico CNI (k3d-test)"
run "sshrun 'cd ${REPO_DIR_REMOTE} && bash bootstrap/install-calico.sh test'"

# ============================================================
# 9/14 — ingress-nginx
# ============================================================
log "9/14 ingress-nginx (k3d-test)"
run "sshrun 'cd ${REPO_DIR_REMOTE} && bash bootstrap/install-ingress.sh test'"

# ============================================================
# 10/14 — Prometheus Operator CRD (ServiceMonitor için)
# ============================================================
log "10/14 Prometheus Operator CRD (ServiceMonitor)"
run "sshrun 'kubectl --context k3d-test apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.78.2/example/prometheus-operator-crd-full/monitoring.coreos.com_servicemonitors.yaml'"

# ============================================================
# 11/14 — Sectigo wildcard cert (TLS Secret)
# ============================================================
log "11/14 wildcard-acik-com-tls Secret (ingress-nginx + platform-test ns)"
TMP_CRT="/tmp/wildcard-acik-com-${RANDOM}.crt"
TMP_KEY="/tmp/wildcard-acik-com-${RANDOM}.key"
if [[ "${DRY_RUN}" != "true" ]]; then
  scp -q "${CERT_LOCAL}" "${REMOTE}:${TMP_CRT}"
  scp -q "${KEY_LOCAL}"  "${REMOTE}:${TMP_KEY}"
fi
sshrun "kubectl --context k3d-test create namespace platform-test --dry-run=client -o yaml | kubectl --context k3d-test apply -f -" >/dev/null
for ns in ingress-nginx platform-test; do
  run "sshrun 'kubectl --context k3d-test -n ${ns} create secret tls wildcard-acik-com-tls \
    --cert=${TMP_CRT} --key=${TMP_KEY} --dry-run=client -o yaml | kubectl --context k3d-test -n ${ns} apply -f -'" >/dev/null
done
run "sshrun 'shred -u ${TMP_CRT} ${TMP_KEY} 2>/dev/null || rm -f ${TMP_CRT} ${TMP_KEY}'"

# ============================================================
# 12/14 — kustomize overlay apply
# ============================================================
log "12/14 kustomize overlay apply (platform-test ns)"
run "sshrun 'kubectl --context k3d-test apply -k ${REPO_DIR_REMOTE}/kustomize/overlays/test/'"

# ============================================================
# 13/14 — platform-web-nginx'e testai server block (atomik backup + reload)
# ============================================================
log "13/14 platform-web-nginx'e testai server block ekle"
if sshrun "grep -q 'server_name testai.acik.com' ${NGX_CONF_HOST}"; then
  log "   ✓ zaten eklenmiş, atlanıyor"
else
  TS=$(date +%s)
  log "   default.conf yedek alınıyor: .bak-${TS}"
  run "sshrun 'cp ${NGX_CONF_HOST} ${NGX_CONF_HOST}.bak-${TS}'"

  log "   testai server block APPEND ediliyor"
  if [[ "${DRY_RUN}" != "true" ]]; then
    ssh "${REMOTE}" "cat >> ${NGX_CONF_HOST}" <<'NGINX_EOF'

# ============================================================
# testai.acik.com — paralel test ortamı (k3d-test cluster)
# 2026-04-15: mevcut ai.acik.com block dokunulmadan EKLENDİ
# Geri alma: bu satırlardan sonrasını sil + nginx -s reload
# ============================================================
server {
  listen 80;
  server_name testai.acik.com;

  location = /testai-healthz {
    access_log off;
    add_header Content-Type text/plain;
    return 200 'ok';
  }

  location / {
    return 301 https://$host$request_uri;
  }
}

server {
  listen 443 ssl;
  server_name testai.acik.com;

  ssl_certificate /etc/nginx/tls/tls.crt;     # Sectigo wildcard (paylaşılır)
  ssl_certificate_key /etc/nginx/tls/tls.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_prefer_server_ciphers on;

  add_header Strict-Transport-Security "max-age=86400" always;
  add_header X-Frame-Options "SAMEORIGIN" always;
  add_header X-Content-Type-Options "nosniff" always;

  client_max_body_size 25m;

  location = /testai-healthz {
    access_log off;
    add_header Content-Type text/plain;
    return 200 'ok';
  }

  # k3d-test cluster down (scale-to-zero) → 503 + anlamlı sayfa
  error_page 502 503 504 /testai-down.html;
  location = /testai-down.html {
    return 503 "Test ortamı şu an kapalı (scale-to-zero). Açmak için: kubectl --context k3d-test -n platform-test scale deploy --all --replicas=1\n";
    add_header Content-Type "text/plain; charset=utf-8";
  }

  location / {
    proxy_pass http://127.0.0.1:9080;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 300s;
    proxy_connect_timeout 10s;
  }
}
NGINX_EOF
  fi
fi

# ============================================================
# 14/14 — nginx -t + reload (atomik, geri-alınabilir)
# ============================================================
log "14/14 nginx -t test + graceful reload"
if sshrun 'docker exec platform-web-nginx nginx -t'; then
  log "   ✓ nginx -t başarılı"
  run "sshrun 'docker exec platform-web-nginx nginx -s reload'"
  log "   ✓ reload başarılı (graceful, mevcut bağlantılar etkilenmedi)"
else
  err "nginx -t başarısız! Geri alma için: cp ${NGX_CONF_HOST}.bak-* ${NGX_CONF_HOST}"
fi

# ============================================================
# Smoke
# ============================================================
log ""
log "=== Smoke ==="
sshrun 'curl -sk --max-time 5 https://127.0.0.1/testai-healthz -H "Host: testai.acik.com"' \
  && echo "" && log "   testai-healthz: ok"

for path in / /auth/foo /api/foo; do
  code=$(sshrun "curl -sk --max-time 5 -o /dev/null -w '%{http_code}' https://127.0.0.1${path} -H 'Host: testai.acik.com'" 2>/dev/null || echo "???")
  printf "   testai.acik.com%-15s → HTTP %s\n" "${path}" "${code}"
done

log ""
log "=== Mevcut sistem kontrolü (ai.acik.com etkilenmiş mi?) ==="
sshrun 'curl -sk --max-time 5 -o /dev/null -w "ai.acik.com / → HTTP %{http_code}\n" https://127.0.0.1/ -H "Host: ai.acik.com"'

log ""
log "✓ DONE — testai.acik.com paralel kurulum tamamlandı"
log ""
log "Tarayıcı erişim:"
log "  https://testai.acik.com               (DNS hazırsa, scale-to-zero default → 503)"
log "  Açmak için (testai backend pod'larını): "
log "    ssh ${REMOTE} 'kubectl --context k3d-test -n platform-test scale deploy --all --replicas=1'"
log ""
log "Geri alma (testai server block + cluster):"
log "  ssh ${REMOTE} 'cp ${NGX_CONF_HOST}.bak-* ${NGX_CONF_HOST} && docker exec platform-web-nginx nginx -s reload'"
log "  ssh ${REMOTE} 'k3d cluster delete test'"
