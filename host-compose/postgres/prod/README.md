# PostgreSQL Prod Instance — ADR-0002 Same-Host Isolation

> **Container:** `platform-pg-prod` · **Port:** 5432 · **Network:** `platform-prod-net`
> **Disk:** `/srv/platform/stateful/prod/postgres`

## Kurulum

```bash
# 0. Host bind-mount + network (bir kez, bootstrap)
sudo mkdir -p /srv/platform/stateful/prod/postgres
sudo chown -R 999:999 /srv/platform/stateful/prod/postgres
docker network create platform-prod-net 2>/dev/null || true

# 1. Secret dosyası (chmod 600, .gitignore)
mkdir -p secrets
echo "<STRONG_RANDOM_PASSWORD>" > secrets/pg_password.txt
chmod 600 secrets/pg_password.txt

# 2. Compose up (init/01-create-databases.sql otomatik çalışır)
docker compose -f docker-compose.yml up -d

# 3. Init doğrulama
docker exec platform-pg-prod psql -U postgres -c '\l' | \
  grep -E 'auth_db|permission_db|keycloak|openfga'

# 4. Backup freshness exporter test
bash ../../../bootstrap/backup-freshness-exporter.sh
```

## Secret Güvenliği

- `secrets/pg_password.txt` **git'e commit EDİLMEZ** (.gitignore hariç tutar)
- Template: `secrets/pg_password.txt.example` (placeholder, güvenli)
- Rotation: `docs/day-2-governance.md` §2.1 (90 gün prod)

## Network

- **Host bind:** `0.0.0.0:5432` (aynı sunucu, platform-prod-net üyesi container'lar kendi IP'leri üzerinden)
- **Cross-env YASAK:** test PG (platform-pg-test, port 5433) ile cross-read asla olmaz
- **Forward-extension:** 2nd host eklenirse VXLAN/wireguard overlay (ADR §6.1)

## İnit SQL

`init/01-create-databases.sql` ilk compose up'ta çalışır:
- 3 role: `platform`, `keycloak_user`, `openfga`
- 9 database: auth_db, users_db, variants_db, core_db, reports_db, schemas_db, permission_db, openfga, keycloak
- Placeholder passwords (`CHANGE_ME_PROD`) — Vault rotation sonrası aktif

## Referanslar

- [ADR-0002 §3.2](../../../docs/adr/0002-single-host-dual-cluster.md)
- [host-compose/README.md](../../README.md) (dizin yapı)
- [docs/day-2-governance.md §1.2](../../../docs/day-2-governance.md) (PG backup/restore)
