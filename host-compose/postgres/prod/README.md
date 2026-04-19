# PostgreSQL Prod Compose (staging-sw-2 D32)

## Kurulum

```bash
# 1. Secret dosyası (chmod 600)
mkdir -p secrets
echo "<STRONG_RANDOM_PASSWORD>" > secrets/pg_password.txt
chmod 600 secrets/pg_password.txt

# 2. Compose up
docker compose -f docker-compose.yml up -d

# 3. DB yaratma (bootstrap/install-on-staging-sw-2.sh F3.4 yapıyor)
docker exec -i platform-postgres-db-prod psql -U postgres <<SQL
CREATE DATABASE auth_db OWNER platform;
CREATE DATABASE users_db OWNER platform;
CREATE DATABASE variants_db OWNER platform;
CREATE DATABASE core_db OWNER platform;
CREATE DATABASE reports_db OWNER platform;
CREATE DATABASE schemas_db OWNER platform;
CREATE DATABASE permission_db OWNER platform;
CREATE DATABASE openfga OWNER openfga;
CREATE DATABASE keycloak OWNER keycloak_user;
SQL

# 4. Backup cron
bash ../../../bootstrap/backup-freshness-exporter.sh    # manual test
```

## Path Drift Uyarısı (Codex PR #1 iter-9)

`secrets/pg_password.txt` **git'e commit EDILMEZ** — .gitignore ile hariç tutun.
Secret örnek `secrets/pg_password.txt.example` git'te olabilir.

## Network

- Host bind: `10.9.10.53:5432` (D20 host bridge, K8s cluster Endpoints patch bu IP'e)
- Cluster dışından erişim YASAK (firewall)

## Referanslar

- PLAN.md D20 host bridge
- docs/S5-disaster-recovery-runbook.md (PG backup + restore)
- bootstrap/install-on-staging-sw-2.sh F3 (compose up komutu)
