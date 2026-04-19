# Vault Test Instance — ADR-0002 Same-Host Isolation

> **Container:** `platform-vault-test` · **Port:** 8201 · **Network:** `platform-test-net`
> **Disk:** `/srv/platform/stateful/test/vault/{data,logs}`
> **Default state:** kapalı (scale-to-zero); ESO apply öncesi up edilir

## Kurulum

```bash
sudo mkdir -p /srv/platform/stateful/test/vault/{data,logs}
sudo chown -R 1000:1000 /srv/platform/stateful/test/vault

# ADR §5.1 enforce: profiles [manual] default-off
docker compose --profile manual up -d

# Init + unseal (prod ile aynı pattern, keys ayrı sakla)
docker exec -it platform-vault-test vault operator init -key-shares=3 -key-threshold=2
# 3 key + root token (test için daha küçük shamir eşik OK)
docker exec -it platform-vault-test vault operator unseal <key1>
docker exec -it platform-vault-test vault operator unseal <key2>

# KV + policy + AppRole
export VAULT_ADDR=http://localhost:8201
vault login <test-root-token>
vault secrets enable -version=2 -path=kv kv
vault policy write eso-runtime ../../../bootstrap/vault-policies/test/eso-runtime.hcl
vault auth enable approle
vault write auth/approle/role/eso-runtime token_policies=eso-runtime token_ttl=1h

# Test overlay role_id patch (overlays/test/eso/clustersecretstore-patch.yaml)
vault read auth/approle/role/eso-runtime/role-id
```

## İzolasyon

- Test Vault verileri prod Vault'a akmaz
- Aynı `kv/platform/<svc>` path iki Vault'ta bağımsız
- secret_id rotation: 14 gün (day-2-governance §2.1)

## Referanslar

- [ADR-0002 §3.6](../../../docs/adr/0002-single-host-dual-cluster.md)
- [host-compose/README.md](../../README.md)
