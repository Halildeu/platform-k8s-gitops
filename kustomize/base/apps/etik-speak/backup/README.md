# Faz 35 ES-309 — Durability backup component

Nightly durability backups for the Etik Speak product cell:

| CronJob | Schedule (UTC) | Target |
|---|---|---|
| `etik-speak-pg-dump` | 03:00 | `/archive/pg/<db>-<ts>.sql.gz` (30-day retention) |
| `etik-speak-openfga-export` | 03:10 | `/archive/openfga/<ts>/{store,authorization-models,tuples-N}.json` (30-day) |
| `etik-speak-vault-snapshot` | 03:20 | `/archive/vault/vault-raft-<ts>.snap` (14-day) |

## Not enabled by default

The component is under `kustomize/base/apps/etik-speak/backup/` but **not**
referenced from the base `kustomization.yaml`. Overlays opt-in by
appending `../../../../base/apps/etik-speak/backup` to their `resources`
list AFTER seeding these three secrets:

- `etik-speak-backup-pg`: keys `{database, user, password}` — read-only PG
  role able to `pg_dump` the ethics_service schema
- `etik-speak-backup-openfga`: keys `{store_id, token}` — OpenFGA store
  read scope token
- `etik-speak-backup-vault`: key `{token}` — Vault token with policy
  `path "sys/storage/raft/snapshot" { capabilities = ["read"] }`

## Prod overlay activation (ES-311 gate)

After ES-311 owner-approval package designates the backup service accounts,
prod overlay `kustomize/overlays/prod/activation/etik-speak/kustomization.yaml`
will:

1. Include this component
2. Swap `pvc-archive.yaml` with an S3 CSI driver PVC (off-cluster bucket)
3. Apply the seven-signature secret manifests through ESO
4. Enable a companion CronJob for weekly rehearsal restore into a scratch
   namespace (see `RB-faz35-backup-restore.md`)

Manifests are self-contained + immutable — the same base ships to test and
prod, only the destination PVC differs.
