# Vault Test Instance — ADR-0002 Same-Host Isolation

> **Container:** `platform-vault-test` · **Ports:** 8201 HTTP, 8302 HTTPS host-local · **Network:** `platform-test-net`
> **Disk:** `/home/halil/platform-stateful/test/vault/{data,logs,tls}`
> **Default state:** kapalı (scale-to-zero); ESO apply öncesi up edilir

## Kurulum

```bash
mkdir -p /home/halil/platform-stateful/test/vault/{data,logs,tls}

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
vault policy write eso-runtime ../../../bootstrap/vault-policies/eso-runtime.hcl   # PR-next-3 sonrası test/eso-runtime.hcl
vault auth enable approle
vault write auth/approle/role/eso-runtime token_policies=eso-runtime token_ttl=1h

# Test overlay role_id patch (overlays/test/eso/clustersecretstore-patch.yaml)
vault read auth/approle/role/eso-runtime/role-id
```

## Faz 22.6 A1 HTTPS listener

The existing HTTP listener on `:8200` remains the ESO path. The `:8202` HTTPS
listener is reserved for backend TPM-attestation PKI signing:

```text
https://vault.platform-test.svc.cluster.local:8202
```

Before restarting Vault with the HTTPS listener, provision TLS material outside
git:

```text
/home/halil/platform-stateful/test/vault/tls/ca.crt
/home/halil/platform-stateful/test/vault/tls/tls.crt
/home/halil/platform-stateful/test/vault/tls/tls.key
```

The certificate SAN set must include at least:

```text
vault.platform-test.svc.cluster.local
vault.platform-test.svc
vault
localhost
127.0.0.1
```

Validation without printing key material:

```bash
docker exec platform-vault-test sh -c \
  'VAULT_ADDR=https://127.0.0.1:8202 VAULT_CACERT=/vault/tls/ca.crt vault status'
```

## İzolasyon

- Test Vault verileri prod Vault'a akmaz
- Aynı `kv/platform/<svc>` path iki Vault'ta bağımsız
- secret_id rotation: 14 gün (day-2-governance §2.1)

## Referanslar

- [ADR-0002 §3.6](../../../docs/adr/0002-single-host-dual-cluster.md)
- [host-compose/README.md](../../README.md)
