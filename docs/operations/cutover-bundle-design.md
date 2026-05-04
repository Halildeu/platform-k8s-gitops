# Cutover Bundle Design — Codex Sprint A P0 Item 4

> Codex 2026-05-04 retrospective: "Cutover bundle yok. D30 atomic cutover'a
> giderken stateful tier (PG, OpenFGA, KC, Vault) için backup snapshot
> playbook eksik. 72h rollback window'una giderken bundle'sız geri dönüş yok."

## Sorun

D30 atomic cutover sırasında compose stack → k8s-prod transit'i.
72h rollback window pattern'i (HARD RULE #6) gerektiriyor:

- compose freeze + ayakta tutma (rollback hedefi)
- k3d-prod canlı, gerçek trafik

Eğer cutover sonrası 72h içinde bir state corruption / data loss tespit
edilirse, geri dönüş yolu:

1. Drift detector P1 alarm
2. Operator: cluster traffic'i compose'a yönlendir (DNS/proxy)
3. Compose state'i kapsamlı olarak doğrula
4. Eğer compose state'inde T+0 öncesi data var → geri al, bekle, retry
5. Eğer compose state'inde T+0 sonrası işlem **var** (write trafiği geldi) → bundle restore'a git

Bu doc bundle yapısını ve restore playbook'unu netleştirir.

## Bileşenler

### 1. PostgreSQL (compose-side)

Single shared PG instance hosting:
- `users_db` — auth/profile master data
- `permission_db` — role assignments + bootstrap-admin-assigner state
- `openfga` — OpenFGA backend store (tuples + auth_models)
- `keycloak` — KC realm config + sessions
- `schema_service` — Workcube schema snapshot cache
- `core_data_service` — companies/projects/warehouses cache

Snapshot: `pg_dumpall -h <host> -p <port> -U postgres` → gzipped SQL dump.

**Restore**: `gunzip -c | psql ... --quiet`. Note: pg_dumpall includes
DROP DATABASE for each db, so restore is fully destructive (matches
"replace all PG state" semantics for cutover rollback).

### 2. OpenFGA store + tuples

Logical tuples managed via OpenFGA REST API (port 8081 compose-side).

Snapshot:
- `GET /stores` → list all stores
- For each store: `GET /stores/<id>/authorization-models` → all auth models
- For each store: `POST /stores/<id>/read` (empty filter) → all tuples

Result: composite JSON with `{stores: [{store, auth_models, tuples}]}`.

**Restore**: Multi-step manual operation (auto-restore deferred to Sprint B):
1. Re-create stores (`POST /stores`)
2. Re-upload auth models (`POST /stores/<id>/authorization-models`)
3. Re-write tuples in batches (`POST /stores/<id>/write`)

### 3. Keycloak realm export

Critical realm: `serban` (prod). Test uses `platform-test` realm
(not backed up in this bundle — test cutover not in scope D30).

Snapshot: KC admin REST `GET /admin/realms/serban` → JSON export.
Includes: clients, roles, groups, identity providers, but NOT users
by default.

**For users**: separate realm export with `users=true` query param,
OR docker exec realm export `kc.sh export --users realm_file`.

**Restore**: `POST /admin/realms` with the JSON body.

### 4. Vault raft snapshot

Vault data plane backup using built-in `vault operator raft snapshot save`.
Snapshot is encrypted with Vault's seal key — restoring requires the same
unseal keys (or auto-unseal trust).

**Restore**: `vault operator raft snapshot restore <file>` after Vault
operator login.

### 5. ConfigMap live state (test + prod)

`kubectl get cm -o yaml` for both clusters. Captures current cluster
ConfigMap state which may have drift vs gitops yaml (e.g. break-glass
operator changes during cutover prep).

Used during restore as a **diff reference** — operator compares
live-cluster-post-restore vs bundle ConfigMaps to identify drift.

### 6. Overlay render + pod imageIDs

`kubectl kustomize` of test/prod overlays (snapshot of "what gitops says")
+ `kubectl get pods -o jsonpath` for imageIDs (snapshot of "what cluster
actually runs").

Used to verify post-restore that:
- gitops yaml matches the cluster pod state
- No drift from the bundle's ground truth

## Pre-flight gates

Bundle script (`cutover-bundle.sh`) runs preflight before any snapshot:

- All required tools installed: `pg_dumpall`, `curl`, `jq`, `kubectl`, `python3`
- PG reachable at expected host:port
- Both cluster contexts reachable (k3d-test, k3d-prod)

If any pre-flight fails: exit 2 (no partial bundle written).

## Operator runbook (D30 cutover sequence)

### T-24h: Pre-cutover backup
```bash
# On staging-sw, with credentials populated:
export PGPASSWORD=<pg-password>
export KC_ADMIN_USER=admin
export KC_ADMIN_PASSWORD=<kc-admin-password>
export VAULT_TOKEN=<vault-root-token>

# Create bundle in default location (/var/backups/cutover/)
sudo -E bash scripts/cutover/cutover-bundle.sh

# Verify
ls -la /var/backups/cutover/cutover-bundle-<latest-ts>/
jq '.components' /var/backups/cutover/cutover-bundle-<latest-ts>/MANIFEST.json
```

### T-2h: Final pre-cutover bundle
Re-run bundle creation just before cutover for minimal data loss window.

### T+0h: Cutover (separate runbook — D32 bootstrap)
ArgoCD prod manual sync, ingress switch, etc.

### T+24h–T+72h: Rollback window
If P1 issue detected, operator decides rollback:

```bash
# Inspect bundle integrity first
ls /var/backups/cutover/

# Pick most recent + verified bundle
LATEST_BUNDLE=$(ls -dt /var/backups/cutover/cutover-bundle-* | head -1)

# Run restore (DESTRUCTIVE — overwrites current state)
sudo -E bash scripts/cutover/cutover-restore.sh $LATEST_BUNDLE
# Will prompt for timestamp confirmation

# Then traffic-switch back to compose stack via DNS/proxy edge
# (separate edge runbook — manual step)
```

### T+72h: Bundle archival
Move surviving bundles to long-term archive:
```bash
sudo mv /var/backups/cutover/cutover-bundle-* /var/backups/archive/cutover-2026-05-XX/
```

## Bundle storage policy

| Stage | Location | Retention |
|---|---|---|
| **Active** (T-24h to T+72h) | `/var/backups/cutover/` | 4 days |
| **Archive** (post-72h) | `/var/backups/archive/cutover-<YYYY-MM-DD>/` | 90 days |
| **Long-term** (compliance) | offsite (operator's responsibility) | 1 year |

systemd timer `cutover-bundle-nightly.timer` runs daily at 03:00 local.
First few runs before D30 establish baseline; the cutover-day bundles
are manually triggered for tighter timing.

## Hata senaryoları

### Snapshot component fails (e.g. KC admin token rejected)

- Bundle script returns exit 1 with `components_failed` count
- Partial bundle directory remains for manual investigation
- **DO NOT** rely on partial bundle for rollback
- Operator: fix root cause (check KC admin password, network), retry

### Restore checksums fail

- Bundle is corrupted (disk error, partial write)
- Restore script refuses to proceed (exit 1)
- Operator: pick older verified bundle, OR restore individually
  with `--components pg` to skip corrupt components

### OpenFGA restore complexity

- OpenFGA doesn't support direct `kc.sh import`-style realm restore
- Multi-step API calls required (stores → auth_models → tuples)
- For D30 immediate post-cutover rollback: manual operator task
- Sprint B/C: auto-restore script that walks the export JSON

## See also

- `scripts/cutover/cutover-bundle.sh` — bundle creator
- `scripts/cutover/cutover-restore.sh` — companion restore
- `scripts/cutover/systemd/cutover-bundle-nightly.{service,timer}` — scheduled
- `docs/D32-bootstrap-runbook.md` — D30 cutover full sequence
- HARD RULE #6 (CLAUDE.md) — D30 atomic + 72h rollback contract
