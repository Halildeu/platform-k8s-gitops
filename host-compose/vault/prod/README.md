# Vault Prod Compose (staging-sw-2 D32)

## Kurulum

```bash
# 1. Compose up (Raft storage fresh init)
docker compose -f docker-compose.yml up -d

# 2. Vault init (ilk kurulum — ONCE)
docker exec -it platform-vault-prod vault operator init \
  -key-shares=5 -key-threshold=3
# Çıktı: 5 unseal key + 1 root token — GUVENLI YERDE SAKLA

# 3. Unseal (3/5 key)
docker exec -it platform-vault-prod vault operator unseal <key-1>
docker exec -it platform-vault-prod vault operator unseal <key-2>
docker exec -it platform-vault-prod vault operator unseal <key-3>

# 4. Login (root token)
export VAULT_ADDR=http://10.9.10.53:8200
vault login <root-token>

# 5. KV v2 mount + audit backend
vault secrets enable -version=2 -path=kv kv
vault audit enable -path=file_audit file file_path=/vault/logs/audit.log

# 6. Policy + AppRole (bootstrap/vault-policies/eso-runtime.hcl)
vault policy write eso-runtime ../../../bootstrap/vault-policies/eso-runtime.hcl
vault auth enable approle
vault write auth/approle/role/eso-runtime \
  token_policies="eso-runtime" \
  token_ttl=1h token_max_ttl=24h

# 7. Seed platform secret'ler (docs/S2-B1-vault-property-matrix.md §2)
vault kv put kv/gitops/ghcr-token username=halildeu password=<PAT>
vault kv put kv/platform/permission-service \
  db_username=platform db_password=<...> \
  internal_api_key=<...> keycloak_client_secret=<...>
# ... diğer servisler docs/S2-B1 §1
```

## Backup

```bash
# Raft snapshot (docs/S5-DR §2.3)
vault operator raft snapshot save /tmp/vault-snapshot-$(date +%Y%m%d).snap
docker cp platform-vault-prod:/tmp/vault-snapshot-*.snap /home/halil/platform/backup/vault/
```

## Referanslar

- PLAN.md D20 host bridge
- bootstrap/vault-policies/eso-runtime.hcl (ESO policy)
- bootstrap/vault-policies/README.md (AppRole + test komutları)
- docs/S2-B1-vault-property-matrix.md (path + property matrisi)
- docs/S5-vault-audit-retention.md (audit backend + logrotate)
- docs/S5-disaster-recovery-runbook.md §2.3 (Raft snapshot backup)
