# Runbook — DR-8 Prod Vault DR Inventory (Read-Only Verify, User-Driven)

> **DR-8 of ADR-0010** (`docs/adr/0010-vault-credential-lifecycle-and-dr.md` §2.2).
> **Codex consensus**: thread `019dd2c9` (xhigh effort architecture).
> **Authority**: user-driven only. Per ADR-0010 §2.5: "Prod Vault rekey, seal/unseal drill, restart, root token generate, admin token usage" require explicit user approval. This runbook is **read-only verify** but still touches prod vault state files → user-driven.
> **Why**: Test vault DR found stale (PR #202 runbook executed). Prod must not be assumed; verify before assuming readiness. **Read-only inventory** does NOT modify prod state.

## Pre-conditions

- [ ] Test vault DR rekey complete (PR #202 runbook executed; result captured).
- [ ] You are logged in to staging-sw as `halil` user.
- [ ] Prod vault container `platform-vault-prod` running (`docker ps | grep platform-vault-prod`).
- [ ] Operator awareness: this is **read-only**. Any write/rekey/restart on prod is DR-9, separate runbook + separate approval.

## Phase 1 — Prod Vault status (read-only)

```bash
docker exec platform-vault-prod vault status
```

Expected (current per 2026-04-28 inventory):
```text
Initialized: true
Sealed: false
Total Shares: 5
Threshold: 3
Version: 1.17.6
HA Mode: active
```

If Sealed=true → STOP. Prod vault sealed = production incident. Separate runbook (Vault unseal recovery) before continuing here.

## Phase 2 — Inventory prod key files

```bash
ls -la /home/halil/platform/state/vault/ | grep -iE 'prod|init'
```

Capture file timestamps. Per ADR-0010 §2.2 recovery bundle:

```bash
# Identify which files claim to be for prod
echo "=== Files with shares=5 threshold=3 (prod shape):"
for f in /home/halil/platform/state/vault/*.json; do
  shares=$(sudo python3 -c "import json; print(json.load(open('$f')).get('unseal_shares','?'))" 2>/dev/null)
  threshold=$(sudo python3 -c "import json; print(json.load(open('$f')).get('unseal_threshold','?'))" 2>/dev/null)
  echo "  $f: shares=$shares threshold=$threshold"
done
```

Expected: at least one file with shares=5 threshold=3 (matches prod current shape).

## Phase 3 — Validate at least N (= threshold) prod unseal keys

For each candidate prod key file/share, test against prod vault using `generate-root` flow (cancel after Progress check, do NOT complete the flow):

```bash
# Cancel any pending generate-root attempts first
docker exec platform-vault-prod vault operator generate-root -cancel

OTP=$(docker exec platform-vault-prod vault operator generate-root -generate-otp)
INIT=$(docker exec platform-vault-prod vault operator generate-root -init -otp="$OTP")
NONCE=$(echo "$INIT" | grep -E '^Nonce' | awk '{print $NF}')

# Submit each candidate prod unseal key
for KEY_FILE in /home/halil/platform/state/vault/<prod-keys>; do
  KEY=$(sudo cat "$KEY_FILE")
  RESULT=$(docker exec platform-vault-prod vault operator generate-root -nonce="$NONCE" "$KEY" 2>&1)
  PROGRESS=$(echo "$RESULT" | grep -E '^Progress' | awk '{print $NF}')
  echo "  $KEY_FILE → progress: $PROGRESS"
  # If progress increments → key is valid
  # If "decrypt fail" / "cipher: message authentication failed" → stale
done

# CANCEL the attempt — we are NOT proceeding to root regeneration
docker exec platform-vault-prod vault operator generate-root -cancel
```

**Verify**: count of valid keys ≥ threshold (= 3). If yes → prod DR is recoverable. If no → prod DR is broken; this is a production incident and triggers DR-9.

## Phase 4 — Verify prod ESO approle still works (read-only)

```bash
# ESO ClusterSecretStore approle role-id (publicly visible in cluster)
ROLE_ID=$(kubectl --context k3d-prod -n external-secrets get clustersecretstore vault-platform-gitops \
  -o jsonpath='{.spec.provider.vault.auth.appRole.roleId}')
SECRET_ID=$(kubectl --context k3d-prod -n external-secrets get secret vault-approle-secret \
  -o jsonpath='{.data.secret-id}' | base64 -d)

# Login + capabilities-self check (read-only — does NOT modify prod state)
TOKEN=$(curl -sf -X POST http://172.21.0.6:8200/v1/auth/approle/login \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["auth"]["client_token"])')

curl -sf -X POST -H "X-Vault-Token: $TOKEN" \
  http://172.21.0.6:8200/v1/sys/capabilities-self \
  -d '{"paths":["kv/data/platform/permission-service"]}' \
  | python3 -m json.tool
```

Expected: capabilities = ["read"] (eso-runtime read-only access). Self-revoke immediately:

```bash
curl -sf -X POST -H "X-Vault-Token: $TOKEN" \
  http://172.21.0.6:8200/v1/auth/token/revoke-self
unset TOKEN
```

## Phase 5 — Inventory prod KV path versions (read-only via approle)

For each platform service path, read current data version (NOT data values):

```bash
ROLE_ID=...  # from Phase 4
SECRET_ID=...
TOKEN=...

for svc in auth-service user-service variant-service core-data-service \
           report-service schema-service permission-service openfga; do
  metadata=$(curl -sf -H "X-Vault-Token: $TOKEN" \
    "http://172.21.0.6:8200/v1/kv/metadata/platform/$svc" 2>&1)
  current_version=$(echo "$metadata" | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["current_version"])' 2>/dev/null)
  echo "  $svc: current_version=$current_version"
done
```

Capture into evidence file. This shows which paths exist + their current version (audit trail proxy).

## Phase 6 — Prod audit backend status (read-only)

```bash
# Check if prod vault has audit backends configured
# Requires admin token; if no token available → can only verify from logs
docker logs platform-vault-prod 2>&1 | tail -50 | grep -iE 'audit|file' || echo 'No audit log lines found in container output'
```

Per ADR-0010 §2.2: audit MUST be enabled on prod. If absent → file follow-up issue.

## Phase 7 — Capture inventory evidence

Write `docs/faz-21-3-evidence/<date>-d35-prod-vault-dr-inventory.md`:

```markdown
# DR-8 — Prod Vault DR Inventory (Read-Only)

**Tier**: Infrastructure DR (NOT a D35-X tier — same classification as DR-6 readiness check)
**Date**: <UTC ISO date>
**Cluster**: staging-sw (host bridge platform-net-prod 172.21.0.x)
**Operator**: <user>

## Status (Phase 1)

(paste `vault status` output)

## Key file inventory (Phase 2)

(paste matching files + shares/threshold)

## Key validation (Phase 3)

| Key file | Progress observed | Verdict |
|---|---|---|
| (file 1) | 1/3 | VALID |
| (file 2) | 1/3 → 2/3 | VALID |
| (file 3) | "decrypt fail" | STALE |

Valid keys count: <N>. Threshold: 3.

## ESO approle (Phase 4)

capabilities-self: ["read"] ✓ — eso-runtime contract holds.

## KV path inventory (Phase 5)

| Service | Current version |
|---|---|
| auth-service | <N> |
| ... | ... |

## Audit backend (Phase 6)

(present | absent)

## Verdict

(prod DR recoverable | prod DR broken — file P1 incident → DR-9 required)

## Next

If recoverable + audit configured + ESO healthy → prod ready for DR-9 (bootstrap-writer apply).
If not → block DR-9 until prod DR fix prioritized.
```

## After successful inventory

- **DR-9 candidates**: prod DR readiness confirmed → DR-9 (bootstrap-writer prod policy + secret-id rotation) becomes user-approval-able.
- **Schedule prod drill**: first quarterly drill 30 days from inventory date.
- **Drift-detection automation**: agent can prepare a CI cron job to re-run Phase 1+3+5 monthly (separate PR; user-approval for cron, but inventory is read-only).

## What this runbook does NOT do

- Does NOT modify prod vault state (read-only).
- Does NOT generate prod root token (cancel after Progress check).
- Does NOT rotate prod ESO approle (DR-9 territory).
- Does NOT touch test vault (PR #202 territory).

## References

- ADR-0010 §2.2 (DR contract), §2.5 (operator/agent authority)
- PR #202 — test vault DR rekey runbook (companion)
- DR finding chip (resolved by PR #202 + this runbook)
- Codex thread `019dd2c9`
