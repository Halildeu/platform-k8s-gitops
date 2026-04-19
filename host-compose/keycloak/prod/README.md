# Keycloak Prod Compose (staging-sw-2 D32)

## Kurulum

```bash
# 1. Secret dosyaları
mkdir -p secrets
echo "<KC_DB_PASSWORD>" > secrets/kc_db_password.txt
echo "<KC_ADMIN_PASSWORD>" > secrets/kc_admin_password.txt
chmod 600 secrets/*.txt

# 2. PostgreSQL prod up olmalı (bkz ../../postgres/prod/)
# DB + owner yaratılmış olmalı: keycloak / keycloak_user

# 3. Compose up
docker compose -f docker-compose.yml up -d

# 4. Realm import (staging-sw'den backup)
docker cp /path/to/serban-YYYYMMDD.json platform-keycloak-prod:/tmp/
docker exec platform-keycloak-prod /opt/keycloak/bin/kc.sh import \
  --file /tmp/serban-YYYYMMDD.json
```

## Smoke

```bash
# Healthz
curl http://10.9.10.53:8081/health/ready
# Beklenen: 200 + {"status":"UP"}

# Realm serban
curl http://10.9.10.53:8081/realms/serban/.well-known/openid-configuration
# Beklenen: 200 + OIDC discovery JSON
```

## Referanslar

- docs/S5-cert-renewal-runbook.md (Sectigo cert mount)
- docs/S5-disaster-recovery-runbook.md §3.2 (Realm restore)
- PLAN.md D20 host bridge + D24 JVM heap
- bootstrap/install-on-staging-sw-2.sh F3 (compose up)
