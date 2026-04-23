# Keycloak Test Instance — ADR-0002 Same-Host Isolation

> **Container:** `platform-kc-test` · **Port:** 8082 · **Network:** `platform-test-net`
> **Disk:** `/srv/platform/stateful/test/keycloak`
> **DB:** test PG (`platform-pg-test`)
> **Default state:** kapalı (test scale-to-zero)

## Kurulum

**NOT:** `profiles: [manual]` default-off enforce. Compose up manuel profile gerektirir.

```bash
sudo mkdir -p /srv/platform/stateful/test/keycloak
sudo chown -R 1000:0 /srv/platform/stateful/test/keycloak
sudo install -d -o 1000 -g 0 -m 0775 /srv/platform/stateful/test/keycloak/tmp

mkdir -p secrets
echo "<KC_DB_TEST_PASSWORD>" > secrets/kc_db_password.txt
echo "<KC_ADMIN_TEST_PASSWORD>" > secrets/kc_admin_password.txt
chmod 600 secrets/*.txt

# Prereq: platform-pg-test + platform-test-net hazır
docker compose --profile manual up -d
```

**Kritik not:** Keycloak container `uid=1000 gid=0` ile çalışır. Bind-mount dizini buna writable değilse `data/tmp` oluşturulamaz ve `/resources/*` login asset zinciri `500 application/json` döner.

## Smoke

```bash
curl http://localhost:8082/health/ready
curl http://localhost:8082/realms/serban/.well-known/openid-configuration
```

## Referanslar

- [host-compose/README.md](../../README.md)
- [ADR-0002 §3.2](../../../docs/adr/0002-single-host-dual-cluster.md)
