# GH-AUTH-VAULT-POINTERS (SSOT)

## Amaç
Local SSOT akışında GitHub CLI (`gh`) için token kaynağını tekleştirmek.

## Vault KV v2 Pointer
- `GH_AUTH_VAULT_PATH`: `secret/stage/ops/github`
- `GH_AUTH_VAULT_FIELD`: `GH_LOCAL_AUTOPILOT_TOKEN`

Kaynak izi:
- `scripts/ops/local_ops_start.sh` (GH_LOCAL_AUTOPILOT_TOKEN kullanımı)
- `docs/04-operations/RUNBOOKS/RB-insansiz-flow.md` (token notları)

## Not
Token değeri asla loglanmaz; sadece stdin ile `gh auth login --with-token`’a verilir.
