# Host Compose — ADR-0002 Full Stateful Isolation

> **Referans ADR:** [`docs/adr/0002-single-host-dual-cluster.md`](../docs/adr/0002-single-host-dual-cluster.md)
> **Strateji:** same-host iki ayrı compose stack (prod + test) — tam izolasyon

## Dizin Yapısı

```
host-compose/
├── postgres/
│   ├── prod/   # platform-pg-prod (port 5432, platform-prod-net)
│   └── test/   # platform-pg-test (port 5433, platform-test-net)
├── keycloak/
│   ├── prod/   # platform-kc-prod (port 8081)
│   └── test/   # platform-kc-test (port 8082)
├── vault/
│   ├── prod/   # platform-vault-prod (port 8200)
│   └── test/   # platform-vault-test (port 8201)
└── proxy/      # host nginx SSL edge (shared)
```

## İzolasyon Kontratı (ADR-0002 §3.2)

| Alan | Prod | Test |
|---|---|---|
| Container isim | `platform-{pg,kc,vault}-prod` | `platform-{pg,kc,vault}-test` |
| Network | `platform-prod-net` | `platform-test-net` |
| Host port PG | 5432 | 5433 |
| Host port KC | 8081 | 8082 |
| Host port Vault | 8200 | 8201 |
| Disk path | `/srv/platform/stateful/prod/<svc>` | `/srv/platform/stateful/test/<svc>` |
| Resource budget | ADR §7.2 prod-stateful slice | ADR §7.2 test-stateful slice |
| Default state | Always up | Scale-to-zero (up edilirse kullanıcı iradesi) |

**KESİN YASAKLAR:**
- Prod + test shared PG / KC / Vault instance
- Aynı volume path (cross-contamination riski)
- Aynı container isim farklı env
- `platform_microservice-network` üzerinde stateful servis (legacy transition sonrası kaldırılır)

## Bootstrap Sırası

### 1. Host prerequisite
```bash
# Bind-mount dizinleri + sahiplik (UID 999 postgres, UID 1000 keycloak/vault)
sudo mkdir -p /srv/platform/stateful/{prod,test}/{postgres,keycloak,vault/data,vault/logs}
sudo chown -R 999:999 /srv/platform/stateful/{prod,test}/postgres
sudo chown -R 1000:1000 /srv/platform/stateful/{prod,test}/{keycloak,vault}

# Docker network (pre-create, external)
docker network create platform-prod-net 2>/dev/null || echo "prod-net exists"
docker network create platform-test-net 2>/dev/null || echo "test-net exists"
```

### 2. Prod stateful up (cutover öncesi hazırlanır)
```bash
cd host-compose/postgres/prod
# secrets/pg_password.txt yaz (chmod 600)
docker compose -f docker-compose.yml up -d

cd ../../keycloak/prod
# secrets/kc_db_password.txt + kc_admin_password.txt
docker compose -f docker-compose.yml up -d

cd ../../vault/prod
docker compose -f docker-compose.yml up -d
# Post-start: manual vault operator init + unseal
```

### 3. Test stateful up (ihtiyaç anında)
```bash
# Benzer sıra, test klasörü
cd host-compose/postgres/test && docker compose up -d
cd ../../keycloak/test && docker compose up -d
cd ../../vault/test && docker compose up -d
```

### 4. Test scale-down (ADR §5.1 default)
```bash
# Test kapalı tutulur (kullanıcı direktif 2026-04-19):
cd host-compose/vault/test && docker compose down
cd ../../keycloak/test && docker compose down
cd ../../postgres/test && docker compose down
```

## Secret Yönetimi

**Git'te ASLA yok:** `secrets/*.txt` dosyaları `.gitignore` ile hariç.
**Örnek:** `secrets/*.txt.example` (template içeriği placeholder).

**Rotation takvim:** `docs/day-2-governance.md` §2 (Vault AppRole 30 gün prod / 14 gün test).

## Migration — Legacy Compose'dan ADR-0002'ye

Mevcut `platform-postgres-db-1` / `platform-keycloak-1` / `platform-vault-1` container'ları (platform-ssot repo backend compose) **shared** durumda (hem test hem compose-live-backend aynı instance kullanıyor).

**Geçiş planı (Faz D — ADR §9 follow-up 9):**
1. Prod stateful yeni instance up (yukarıdaki bootstrap)
2. Prod data migration (dump + restore legacy → yeni prod PG/Vault)
3. Cutover sonrası (Faz G) eski shared instance decommission
4. Test stateful yeni instance up (ESO Faz 3 test yeniden seed)
5. Eski `platform-postgres-db-1` + legacy KC + Vault stop (T+72h+)

**Runbook:** `docs/prod-cutover-runbook-v2.md` + gelecek migration runbook.

## Forward-Extension Paths (ADR §6)

- İkinci host: `platform-prod-net` VXLAN/wireguard overlay ile genişler
- HA PG: Patroni/Stolon replication, mevcut bind-mount `/srv` → shared storage tier
- Vault replication: primary-secondary, bugünkü path/policy zarar görmez
- Ayrı disk/partition: bind-mount path mount swap ile zero-downtime

## Referanslar
- [ADR-0002](../docs/adr/0002-single-host-dual-cluster.md) (ana karar)
- [PLAN.md §0](../PLAN.md) (Faz A-I roadmap)
- [docs/prod-cutover-runbook-v2.md](../docs/prod-cutover-runbook-v2.md) (atomic cutover)
- [docs/day-2-governance.md](../docs/day-2-governance.md) (backup/rotation)
