# PostgreSQL Test Instance — ADR-0002 Same-Host Isolation

> **Container:** `platform-pg-test` · **Port:** 5433 · **Network:** `platform-test-net`
> **Disk:** `/srv/platform/stateful/test/postgres`
> **Default state:** kapalı (ADR §5.1 test scale-to-zero) — up edilirse kullanıcı iradesi

## Kurulum

```bash
# 0. Host bind-mount + network
sudo mkdir -p /srv/platform/stateful/test/postgres
sudo chown -R 999:999 /srv/platform/stateful/test/postgres
docker network create platform-test-net 2>/dev/null || true  # k3d-test zaten kullanıyor

# 1. Secret
mkdir -p secrets
echo "<STRONG_RANDOM_TEST_PASSWORD>" > secrets/pg_password.txt
chmod 600 secrets/pg_password.txt

# 2. Compose up
docker compose -f docker-compose.yml up -d

# 3. Init doğrulama
docker exec platform-pg-test psql -U postgres -c '\l' | \
  grep -E 'auth_db|permission_db'
```

## Test Down (default)

```bash
docker compose down   # scale-to-zero default
```

## İzolasyon

- Prod PG (`platform-pg-prod`, port 5432) ile hiçbir ortak kaynak yok
- Ayrı network, ayrı disk, ayrı credential (Vault kv/platform/<svc> iki ayrı Vault'ta aynı path)
- Test data prod'a sızmaz; prod data test'e gitmez

## Referanslar

- [ADR-0002 §3.2](../../../docs/adr/0002-single-host-dual-cluster.md)
- [host-compose/README.md](../../README.md)
