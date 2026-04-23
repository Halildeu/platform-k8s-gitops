# Keycloak Prod Instance — ADR-0002 Same-Host Isolation

> **Container:** `platform-kc-prod` · **Port:** 8081 · **Network:** `platform-prod-net`
> **Disk:** `/srv/platform/stateful/prod/keycloak`
> **DB:** prod PG (`platform-pg-prod`, cross-env read YASAK)

## Kurulum

```bash
# 0. Host bind-mount + prereq
sudo mkdir -p /srv/platform/stateful/prod/keycloak
sudo chown -R 1000:0 /srv/platform/stateful/prod/keycloak
sudo install -d -o 1000 -g 0 -m 0775 /srv/platform/stateful/prod/keycloak/tmp

# 1. Secret dosyaları
mkdir -p secrets
echo "<KC_DB_PASSWORD>" > secrets/kc_db_password.txt
echo "<KC_ADMIN_PASSWORD>" > secrets/kc_admin_password.txt
chmod 600 secrets/*.txt

# 2. Prereq: platform-pg-prod ve platform-prod-net hazır (bkz ../../postgres/prod/)

# 3. Compose up
docker compose -f docker-compose.yml up -d

# 4. Realm import (first-time; backup/restore için day-2-governance §1.4)
docker cp /path/to/serban-YYYYMMDD.json platform-kc-prod:/tmp/
docker exec platform-kc-prod /opt/keycloak/bin/kc.sh import \
  --file /tmp/serban-YYYYMMDD.json
```

**Kritik not:** Keycloak container `uid=1000 gid=0` ile çalışır. Bind-mount dizini buna writable değilse `data/tmp` oluşturulamaz ve `/resources/*` asset'leri `500` döner.

## Smoke

```bash
curl http://localhost:8081/health/ready          # 200 + {"status":"UP"}
curl http://localhost:8081/realms/serban/.well-known/openid-configuration    # OIDC discovery
```

## İzolasyon

- Realm adı test ile aynı olabilir (`serban`); issuer URL ve client_secret farklı
- Test KC (`platform-kc-test`, port 8082) ile cross-read **YASAK** (ayrı DB, ayrı Vault path)
- Admin credentials Vault path: `kv/platform/keycloak/admin`

## Rotation

- Admin token TTL: `8h` (day-2-governance §2.1)
- Confidential client secrets: çeyreklik rotation

## Referanslar

- [ADR-0002 §3.2](../../../docs/adr/0002-single-host-dual-cluster.md)
- [host-compose/README.md](../../README.md)
- [docs/day-2-governance.md §1.4](../../../docs/day-2-governance.md) (KC realm export)
- [docs/S5-cert-renewal-runbook.md](../../../docs/S5-cert-renewal-runbook.md) (Sectigo)
