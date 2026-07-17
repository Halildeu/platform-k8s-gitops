ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

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
      org.opencontainers.image.title="Acik signed Cross-AI deployment protection rule"
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 cross-ai \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
      --shell /usr/sbin/nologin cross-ai
COPY --from=dependencies /opt/venv /opt/venv
WORKDIR /app
COPY --chown=10001:10001 scripts/github_apps /app/scripts/github_apps
COPY --chown=10001:10001 schema/cross-ai-deployment-*.schema.json /app/schema/
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "scripts.github_apps.run_cross_ai_deployment_policy"]
CMD ["--help"]
