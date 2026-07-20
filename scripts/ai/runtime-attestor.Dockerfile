ARG NODE_IMAGE=node:22.17.0-bookworm-slim@sha256:b04ce4ae4e95b522112c2e5c52f781471a5cbc3b594527bcddedee9bc48c03a0
ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

FROM ${NODE_IMAGE} AS codex
ARG TARGETARCH
ARG CODEX_VERSION=0.144.1
ARG CODEX_TARBALL_SHA512=5e2af5cea3dfa5e9e1768028b21379deea27cdb0578f5f023b2cd190595566948dc849795ed92e62ef6875d10b78f14decaff4b1751c48edf801de487825cf6f
ARG CODEX_LINUX_X64_SHA256=a96f944d1a596dbfb7fdd84f482be5c50e34b04bb371126840d873e4ebf26902
COPY config/github-apps/cross-ai-provider-review-authority.v1.json /tmp/codex-authority.json
COPY scripts/ai/verify_codex_npm_provenance.mjs /tmp/verify-codex-npm-provenance.mjs
RUN set -eux; \
    test "${TARGETARCH}" = "amd64"; \
    cd /tmp; \
    npm pack "@openai/codex@${CODEX_VERSION}" --ignore-scripts; \
    archive="openai-codex-${CODEX_VERSION}.tgz"; \
    actual="$(sha512sum "${archive}" | awk '{print $1}')"; \
    test "${actual}" = "${CODEX_TARBALL_SHA512}"; \
    mkdir /tmp/codex-audit; \
    npm install --prefix /tmp/codex-audit --ignore-scripts "@openai/codex@${CODEX_VERSION}"; \
    cd /tmp/codex-audit; \
    npm audit signatures --json > /tmp/npm-signature-audit.json; \
    node -e 'const a=require("/tmp/npm-signature-audit.json"); if (a.invalid?.length || a.missing?.length) process.exit(1)'; \
    node /tmp/verify-codex-npm-provenance.mjs /tmp/codex-authority.json; \
    npm install --global --ignore-scripts "/tmp/${archive}"; \
    native="$(find /usr/local/lib/node_modules/@openai/codex -path '*/vendor/*/bin/codex' -type f -perm /111)"; \
    test -n "${native}"; \
    test "$(printf '%s\n' "${native}" | wc -l)" -eq 1; \
    test "$(sha256sum "${native}" | awk '{print $1}')" = "${CODEX_LINUX_X64_SHA256}"; \
    codex --version | grep -Fx "codex-cli ${CODEX_VERSION}"

FROM ${PYTHON_IMAGE} AS dependencies
ENV PATH=/opt/venv/bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
COPY scripts/github_apps/cross_ai_deployment_policy/requirements.lock /tmp/requirements.lock
RUN python -m pip install \
      --require-hashes \
      --only-binary=:all: \
      --no-compile \
      --requirement /tmp/requirements.lock

FROM ${PYTHON_IMAGE} AS runtime
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/Halildeu/platform-k8s-gitops" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.title="Acik fixed-function Cross-AI runtime attestor"
ENV PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin \
    HOME=/var/lib/cross-ai-runtime \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN mkdir -p /var/lib/cross-ai-runtime \
    && printf '%s\n' 'cross-ai-runtime:x:10002:' >> /etc/group \
    && printf '%s\n' 'cross-ai-runtime:x:10002:10002:Cross-AI runtime:/var/lib/cross-ai-runtime:/usr/sbin/nologin' >> /etc/passwd \
    && chown 10002:10002 /var/lib/cross-ai-runtime
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules/@openai/codex /usr/local/lib/node_modules/@openai/codex
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
WORKDIR /app
COPY scripts/ai /app/scripts/ai
COPY scripts/github_apps /app/scripts/github_apps
COPY schema/cross-ai-*.schema.json /app/schema/
RUN codex --version | grep -Fx 'codex-cli 0.144.1'
USER 10002:10002
EXPOSE 8081
ENTRYPOINT ["python", "-m", "scripts.ai.run_cross_ai_runtime_attestor"]
CMD ["--help"]
