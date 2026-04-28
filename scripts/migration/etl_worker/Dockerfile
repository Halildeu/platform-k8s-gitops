# Faz 16.3 — ETL Worker Dockerfile (Codex iter-5 AGREE)
# Base: python:3.12-slim + msodbcsql18 (MSSQL ODBC driver)

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# msodbcsql18 + dependencies (Microsoft official)
# 2026-04-28 fix (DR-6 readiness check): the previous `prod.list`-fetched
# format omitted [signed-by=...] for the in-repo .list file. Modern apt
# (Debian 12 Bookworm/Trixie sqv-based signature verification) rejects
# unsigned-source format → "Failed to parse keyring
# '/usr/share/keyrings/microsoft-prod.gpg': No such file or directory" at
# apt-get update.
# Fix: write the source line explicitly with [signed-by=...] pointing at
# the dearmored key we install. (Codex `019dd2c9` does NOT cover
# Dockerfile keyring details; this is a build-toolchain fix scoped to
# the existing pipeline.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY etl_worker/ ./etl_worker/
COPY config/ ./config/

RUN pip install --upgrade pip setuptools wheel \
    && pip install -e .

# Non-root user
RUN useradd -m -u 1000 etl
USER etl

ENTRYPOINT ["python", "-m", "etl_worker"]
CMD ["--help"]
