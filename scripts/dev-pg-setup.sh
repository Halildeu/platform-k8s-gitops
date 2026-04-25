#!/usr/bin/env bash
# Faz 17.3 — Mac dev PG fixture (Docker Desktop host'ta postgres:16-alpine)
#
# Kullanım: ./scripts/dev-pg-setup.sh
#
# k3d-dev cluster pod'ları host gateway 192.168.65.254:5432 üzerinden bu PG'ye bağlanır
# (overlays/local-authn-min postgres Endpoints patch'i ile).
#
# 7 DB pre-create: auth_db, user_db, variant_db, core_db, reports_db, schemas_db, permission_db
# (Spring Boot Flyway migration'ları her DB için ayrı schema build eder)

set -euo pipefail

# SCRIPT_DIR removed (unused — SC2034)

log()  { printf '\033[0;36m[dev-pg]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[dev-pg]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[dev-pg]\033[0m %s\n' "$*" >&2; exit 1; }

# Docker daemon erişim kontrolü
docker info >/dev/null 2>&1 || err "docker daemon erişim — Docker Desktop çalışıyor mu?"

# Mevcut dev-pg varsa kaldır (idempotent)
if docker ps -a --format '{{.Names}}' | grep -qx "dev-pg"; then
    log "Mevcut dev-pg container bulundu — siliniyor (idempotent)"
    docker rm -f dev-pg >/dev/null
fi

# Image pull (cached olabilir)
log "postgres:16-alpine image hazırlanıyor"
docker pull postgres:16-alpine >/dev/null

# Container start (Mac Docker Desktop host bridge :5432)
log "dev-pg container başlatılıyor (5432:5432, USER=postgres, default DB=auth_db)"
docker run -d --name dev-pg \
    -p 5432:5432 \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=auth_db \
    postgres:16-alpine >/dev/null

# Ready bekleme
log "PG ready bekleniyor (max 30s)"
for i in {1..30}; do
    if docker exec dev-pg pg_isready -U postgres >/dev/null 2>&1; then
        log "PG ready (${i}s)"
        break
    fi
    sleep 1
done

# 7 DB pre-create (Spring Boot Flyway her DB için)
DBS=(auth_db user_db variant_db core_db reports_db schemas_db permission_db)
for db in "${DBS[@]}"; do
    docker exec dev-pg psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='$db'" 2>/dev/null | grep -q 1 \
        || docker exec dev-pg psql -U postgres -c "CREATE DATABASE $db;" >/dev/null 2>&1
done
log "✓ 7 DB hazır: ${DBS[*]}"

# Connectivity test (host'tan)
if nc -zv -w 3 127.0.0.1 5432 >/dev/null 2>&1; then
    log "✓ host'tan localhost:5432 erişim OK"
else
    err "host'tan localhost:5432 erişim FAIL — port conflict olabilir"
fi

log "Sıradaki adım: ./scripts/dev-up.sh --profile authn-min"
log "Pod restart sonrası auth-service Spring Boot Flyway init'i bu PG'ye bağlanır"
