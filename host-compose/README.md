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

Mevcut `platform-postgres-db-1` / `platform-keycloak-1` / `platform-vault-1` container'ları (platform-ssot repo backend compose) **shared** durumda (prod live trafik + test dev shared).

### UYARI: Port Çakışması (Codex PR #12 iter-1 blocker fix)

Legacy container'lar zaten host port 5432/8080/8200 publish ediyor. Yeni prod compose'lar aynı portları kullanmak istiyor. Naif "önce yeni up, sonra eski stop" akışı **port çakışması ile fail olur**.

### Güvenli Migration Sırası (port-çakışmasız)

**Faz D.1 — Prod Hazırlık (zero-downtime)**
1. Bind-mount dizinleri + network pre-create (bkz §1 Host prerequisite)
2. Vault prod init + seed (host-compose/vault/prod — **port 8200 legacy Vault ile çakışmaz** çünkü legacy Vault `platform_microservice-network` üzerinde, port publish'i yok — doğrula!)
3. Prod PG + KC **PORT MAP KAPALI veya farklı** compose override ile up (geçici)

**Faz D.2 — Data Migration (zero-downtime)**
4. Legacy PG dump → yeni prod PG restore (pg_dumpall | psql)
5. Legacy Vault KV dump → yeni prod Vault seed (vault kv get + vault kv put)
6. Legacy KC realm export → yeni prod KC import
7. Doğrulama: yeni prod stack intra-docker reachable, data intact

**Faz D.3 — Atomic Port Swap (cutover window)**
8. Host nginx edge config freeze
9. `docker stop platform-postgres-db-1 platform-keycloak-1 platform-vault-1` (eski stack)
10. Yeni prod compose port map'leri aktif et (override kaldır → 5432/8081/8200 aç)
11. `docker compose restart platform-pg-prod platform-kc-prod platform-vault-prod`
12. K8s Endpoints yeni prod container IP'lerine patch (bootstrap/reconnect-compose-to-net.sh benzeri prod variant)
13. Edge smoke (ai.acik.com healthy)

**Faz D.4 — Rollback Window (72h)**
14. Legacy stack container'lar **silinmez, sadece stop** (rollback trigger varsa re-start)
15. T+72h stabil → legacy stack decommission + volume archive

### Geçici Compose Override Pattern (Faz D.1)

```bash
# docker-compose.override.yml (geçici, git dışı)
cat > host-compose/postgres/prod/docker-compose.override.yml <<'EOF'
services:
  postgres:
    ports: !override
      - "15432:5432"   # Geçici farklı port, legacy 5432 ile çakışmaz
EOF
docker compose up -d
# Data migration tamamlandıktan sonra override'ı sil + restart
```

### Alternatif: Kısa Downtime (basit ama kesinti var)

Eğer planned downtime kabul edilebiliyorsa:
```bash
docker stop platform-postgres-db-1 platform-keycloak-1 platform-vault-1
# Port serbest; yeni prod compose'lar normal up
docker compose -f host-compose/postgres/prod/docker-compose.yml up -d
# ... KC + Vault
# Data yok — fresh bootstrap (Step 0-5 BOOTSTRAP.md)
```

Bu senaryoda legacy data KAYBOLMAZ (container stopped, volume remains). Rollback için legacy container'ları tekrar `docker start`.

**Detaylı runbook:** [`docs/prod-cutover-runbook-v2.md`](../docs/prod-cutover-runbook-v2.md) (Faz G atomic edge cutover)
**Credential bootstrap:** [`host-compose/BOOTSTRAP.md`](./BOOTSTRAP.md) (fresh install credential zinciri)

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
