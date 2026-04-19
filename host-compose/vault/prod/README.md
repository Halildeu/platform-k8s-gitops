# Vault Prod Instance — ADR-0002 Same-Host Isolation

> **Container:** `platform-vault-prod` · **Port:** 8200 · **Network:** `platform-prod-net`
> **Disk:** `/srv/platform/stateful/prod/vault/{data,logs}`
> **Seal:** manual (HSM yok — ADR §3.6; forward-extension: transit seal)

## Kurulum

```bash
# 0. Host bind-mount + network
sudo mkdir -p /srv/platform/stateful/prod/vault/{data,logs}
sudo chown -R 1000:1000 /srv/platform/stateful/prod/vault

# 1. Compose up (Raft storage fresh init)
docker compose -f docker-compose.yml up -d

# 2. Vault init (ilk kurulum — ONCE)
docker exec -it platform-vault-prod vault operator init \
  -key-shares=5 -key-threshold=3
# Çıktı: 5 unseal key + 1 root token — GÜVENLİ YERDE SAKLA (day-2-governance §1.3)

# 3. Unseal (3/5 key)
docker exec -it platform-vault-prod vault operator unseal <key-1>
docker exec -it platform-vault-prod vault operator unseal <key-2>
docker exec -it platform-vault-prod vault operator unseal <key-3>

# 4. Login
export VAULT_ADDR=http://localhost:8200
vault login <root-token>

# 5. KV v2 mount + audit
vault secrets enable -version=2 -path=kv kv
vault audit enable -path=file_audit file file_path=/vault/logs/audit.log

# 6. Policy (canonical: eso-runtime)
vault policy write eso-runtime ../../../bootstrap/vault-policies/prod/eso-runtime.hcl
vault auth enable approle
vault write auth/approle/role/eso-runtime \
  token_policies="eso-runtime" \
  token_ttl=1h token_max_ttl=24h

# 7. Seed platform secrets (docs/S2-B1-vault-property-matrix.md §2)
vault kv put kv/gitops/ghcr-token username=halildeu password=<PROD_PAT>
# ... 7 servis + openfga + keycloak admin

# 8. AppRole secret-id generate + K8s Secret create
vault write -f auth/approle/role/eso-runtime/secret-id
kubectl --context k3d-prod -n external-secrets create secret generic \
  vault-approle-secret --from-literal=secret-id=<SECRET_ID>

# 9. role_id oku + overlays/prod/eso/clustersecretstore-patch.yaml UUID güncelle
vault read auth/approle/role/eso-runtime/role-id
# → UUID'yi commit et (prod OPS-PREREQ tamamlanır)
```

## Backup

```bash
# Raft snapshot (day-2-governance §1.3)
docker exec platform-vault-prod sh -c \
  'VAULT_TOKEN=$TOKEN vault operator raft snapshot save /vault/logs/snapshot-$(date +%Y%m%d).snap'

# Off-host ship
rsync -av /srv/platform/stateful/prod/vault/logs/snapshot-*.snap backup-host:/backup/vault/prod/
```

## İzolasyon

- 2 ayrı Vault daemon (prod + test, **namespace yetersiz**)
- Ayrı data volume: `/srv/platform/stateful/{prod,test}/vault/data`
- Secret path her Vault'ta env-neutral: `kv/platform/<svc>` (manifest sadeliği)
- Policy dizin: `bootstrap/vault-policies/prod/` (env-specific role binding)
- Rotation: secret-id 30 gün prod

## Referanslar

- [ADR-0002 §3.6](../../../docs/adr/0002-single-host-dual-cluster.md) (Vault design)
- [bootstrap/vault-policies/README.md](../../../bootstrap/vault-policies/README.md)
- [docs/S2-B1-vault-property-matrix.md](../../../docs/S2-B1-vault-property-matrix.md)
- [docs/day-2-governance.md §1.3](../../../docs/day-2-governance.md) (Vault snapshot)
- [docs/S5-vault-audit-retention.md](../../../docs/S5-vault-audit-retention.md) (audit backend)
