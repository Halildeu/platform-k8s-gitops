# iter-50 Step 3.4a — Self-hosted GitHub Actions runner image for staging-sw.
#
# Codex 019dded6 S1 sertleştirmesi:
#   - Tek amaçlı image (runner + deploy tools); job-container çalıştırmaz.
#   - kubectl + rsync + curl + jq + skopeo + gh + Playwright/Chromium preinstalled.
#   - docker.sock NO mount (deploy işi container build/job çalıştırmamalı).
#   - Mount'lar: kubeconfig RO + /home/halil/platform/web-stage/releases RW (compose'ta).
#   - Labels: self-hosted, staging-sw, testai-deploy (entrypoint kayıt sırasında set eder).
#
# Base: ubuntu:22.04 — actions/runner desteklenen platform; Playwright resmi
# Chromium binary'leri Ubuntu için hazır.

FROM ubuntu:22.04

ARG RUNNER_VERSION=2.319.1
ARG TARGETARCH=x64
# Playwright Chromium binary versiyonu actions/runner cache disk space optimization.
ARG PLAYWRIGHT_BROWSERS_VERSION=v1.49.0

ENV DEBIAN_FRONTEND=noninteractive \
    RUNNER_ALLOW_RUNASROOT=0 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# 1. Base packages (deploy tools + runtime libs)
# shellcheck disable=SC2086
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates curl wget gnupg \
      git jq rsync openssh-client \
      python3 python3-pip \
      sudo unzip xz-utils \
      lsb-release software-properties-common \
      libnss3 libatk1.0-0 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
      libpango-1.0-0 libcairo2 libasound2 fonts-liberation libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# 2. kubectl (k3d-test context için)
RUN curl -sLO "https://dl.k8s.io/release/v1.31.0/bin/linux/${TARGETARCH:-amd64}/kubectl" && \
    install -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl

# 3. skopeo (image manifest digest karşılaştırma)
RUN apt-get update && apt-get install -y --no-install-recommends skopeo && \
    rm -rf /var/lib/apt/lists/*

# 4. gh CLI (GitHub API operations — workflow_dispatch + run inspect)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | \
      dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && \
    apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# 5. Node.js 22 (Playwright runtime)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# 6. Runner kullanıcısı
RUN useradd -m -s /bin/bash runner && \
    usermod -aG sudo runner && \
    echo "runner ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/runner

# 7. actions/runner indir + extract
WORKDIR /home/runner
RUN curl -sL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${TARGETARCH}-${RUNNER_VERSION}.tar.gz" | \
      tar xz && \
    chown -R runner:runner /home/runner

# 8. Runner dependency installer
RUN /home/runner/bin/installdependencies.sh

# 9. Playwright Chromium preinstall (build-time; runtime'da indirme yok)
USER runner
WORKDIR /home/runner

# Codex S4: Gate 2 behavior smoke için Chromium gerek.
# `npx playwright install chromium --with-deps` runtime'da deps indirmek
# istiyor (apt-get); build-time'da yapıp `--with-deps` flag'siz yeniden
# install edersek deps zaten kurulu (yukarıda apt-get'le ekledik).
RUN mkdir -p /opt/playwright && \
    npm install -g playwright@${PLAYWRIGHT_BROWSERS_VERSION#v} && \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright playwright install chromium

# 10. Entrypoint
USER root
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER runner
WORKDIR /home/runner

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
