# Runbook — Test Vault DR Keyset Rekey + Recovery Bundle (User-Driven)

> **Companion to ADR-0010 §2.2 (DR contract)** + §2.5 (operator/agent authority).
> **Codex consensus**: thread `019dd2c9` (xhigh effort architecture).
> **Authority**: user-driven only. Per ADR-0010 §2.5, all Vault rekey/seal/root-regen operations require explicit user approval; agent SSH+sudo authority does NOT cover Vault credential operations even with Codex consensus.
> **Why this exists**: 2026-04-28 DR-6 readiness check surfaced that test vault unseal keyset is partially stale (KEY1 valid, KEY2 + KEY3 fail decrypt with `cipher: message authentication failed`). DR is not currently feasible. This runbook fixes that.

## Why agent cannot drive this

- Reading vault state files (`vault-init.json`, `vault-init-prod.json`, `init-output.json`, `vault-unseal-key-*`) is treated as credential exploration by the auto-mode sandbox even when scoped to test vault.
- `vault operator generate-root` + `vault operator rekey` are credential-mutation operations.
- Codex `019dd2c9` Recommendation **A** + ADR-0010 §2.5 explicitly carve out: "Test Vault re-init/reseed gibi mevcut Vault state'ini değiştiren kurtarma yolu" requires user approval.

## Pre-conditions

- [ ] You are logged in to staging-sw as `halil` user (the only account with read access to `/home/halil/platform/state/vault/`).
- [ ] Test vault container `platform-vault-test` is running (`docker ps | grep platform-vault-test`).
- [ ] You have **at least one valid unseal key** (the 2026-04-28 inventory found KEY1 to be valid; KEY2/3 are stale).

## Phase A — Diagnostic (read-only, ~5 min)

Identify exactly which key files (across all directories) match the test vault's current state. The 2026-04-28 quick scan found:

```text
/home/halil/platform/state/vault/vault-unseal-key-1   prefix uptPpej+   → VALID against test vault
/home/halil/platform/state/vault/vault-unseal-key-2   prefix LhjuNzhA   → STALE (decrypt fail)
/home/halil/platform/state/vault/vault-unseal-key-3   prefix hnbyYHTV   → STALE (decrypt fail)
/home/halil/platform/state/vault/vault-unseal-key     prefix NhAMmu/M   → unverified (single key file, 5/3 era?)
/home/halil/platform/state/vault/vault-init.json      shares=5 thr=3    → from initial init (test was 5/3 then rekeyed)
/home/halil/platform/state/vault/vault-init-prod.json shares=3 thr=2    → matches CURRENT TEST vault threshold (could be misnamed!)
/home/halil/platform/state/vault/init-output.json     ?                 → unverified (Apr 13 timestamp = same as -1/-2/-3 files)
```

Diagnostic priority order:

```bash
# Cancel any pending generate-root attempts (cleanup state)
docker exec platform-vault-test vault operator generate-root -cancel

# 1. Check init-output.json shares/threshold (Apr 13 — same date as unseal-key-{1,2,3})
sudo head -c 800 /home/halil/platform/state/vault/init-output.json
# If shares=3 threshold=2 + matches test vault → this is the canonical test init state
#   (the unseal-key-1/2/3 files were derived from this — but only KEY1 currently works)

# 2. Check vault-init-prod.json (3/2 — matches test current shape!)
#    POSSIBLE: file was misnamed; might actually be the test rekey output.
sudo head -c 800 /home/halil/platform/state/vault/vault-init-prod.json
# Compare key prefixes against unseal-key-1/2/3:
#   - If matches → vault-init-prod.json IS the canonical test rekey snapshot, but one share
#     was overwritten somehow. unseal-key-1 still works because it survives.
#   - If different → vault-init-prod.json is for a different vault instance; ignore.

# 3. Try vault-unseal-key (no suffix, Apr 5)
KEY_NOSUFFIX=$(sudo cat /home/halil/platform/state/vault/vault-unseal-key)
docker exec platform-vault-test vault operator generate-root -cancel
OTP=$(docker exec platform-vault-test vault operator generate-root -generate-otp)
docker exec platform-vault-test vault operator generate-root -init -otp="$OTP"
# Get NONCE from output
docker exec platform-vault-test vault operator generate-root -nonce=<NONCE> "$KEY_NOSUFFIX"
# If "Progress 1/2" → this key is also valid; combine with KEY1 → root token!
```

Outcome of Phase A:
- **Best case**: 2 valid keys found across files → proceed to Phase B (controlled rekey).
- **Worst case**: only KEY1 valid across all files → must use Phase C (full reset).

## Phase B — Controlled rekey (best case)

If you have 2 valid current unseal keys (e.g., KEY1 + KEY-from-other-file):

```bash
# 1. Generate root token via generate-root (one-time, revoked at end)
docker exec platform-vault-test vault operator generate-root -cancel

OTP=$(docker exec platform-vault-test vault operator generate-root -generate-otp)
INIT=$(docker exec platform-vault-test vault operator generate-root -init -otp="$OTP")
NONCE=$(echo "$INIT" | grep -E '^Nonce' | awk '{print $NF}')
echo "OTP=${OTP}  NONCE=${NONCE}"

# Submit 2 valid keys
docker exec platform-vault-test vault operator generate-root -nonce="$NONCE" "<VALID_KEY_1>"
RESULT=$(docker exec platform-vault-test vault operator generate-root -nonce="$NONCE" "<VALID_KEY_2>")
ENCODED=$(echo "$RESULT" | grep -E '^Encoded Token' | awk '{print $NF}')

ROOT_TOKEN=$(docker exec platform-vault-test vault operator generate-root -decode="$ENCODED" -otp="$OTP")
echo "Root token obtained (length: ${#ROOT_TOKEN})"

# 2. Rekey vault with fresh shares
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault operator rekey -init -key-shares=3 -key-threshold=2

# Submit the same 2 valid keys to the rekey flow → produces NEW shares
# (output will show new keys 1-3; capture them all to a temp file then write to host)
# (Detailed rekey walk-through: vault docs § "Rekeying Vault")

# 3. Save new keys to /home/halil/platform/state/vault/vault-unseal-key-{1,2,3}
#    (overwrite stale; backup old keys with timestamp)
mv /home/halil/platform/state/vault/vault-unseal-key-1 \
   /home/halil/platform/state/vault/vault-unseal-key-1.pre-rekey-$(date +%Y%m%d).bak
# ... repeat for -2 -3
# Write new keys (1 line per file, perms 600)

# 4. Re-init recovery bundle (per ADR-0010 §2.2)
mkdir -p /home/halil/platform/state/vault/dr-bundle-$(date +%Y%m%d)
docker exec platform-vault-test vault operator raft snapshot save /tmp/raft.snap
docker cp platform-vault-test:/tmp/raft.snap /home/halil/platform/state/vault/dr-bundle-$(date +%Y%m%d)/
# Copy new key set + checksums into bundle
sha256sum /home/halil/platform/state/vault/vault-unseal-key-{1,2,3} \
  > /home/halil/platform/state/vault/dr-bundle-$(date +%Y%m%d)/keys.sha256

# 5. Self-revoke root token
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault token revoke -self
unset ROOT_TOKEN
```

## Phase C — Full reset (worst case, last resort)

Only if Phase A finds NO 2 valid keys + NO admin token recoverable.

> **Destructive**: Vault container reset = ESO secrets resync gerek + tüm services restart. KV data is in raft storage; if raft volume preserved, snapshot can be restored to a fresh init.

```bash
# 1. Snapshot the existing (unsealed) raft state — preserve KV data even if seal lost
docker exec platform-vault-test vault operator raft snapshot save /tmp/raft.snap
docker cp platform-vault-test:/tmp/raft.snap \
  /home/halil/platform/state/vault/pre-reset-$(date +%Y%m%d-%H%M)-raft.snap

# 2. Backup all KV data while vault is still unsealed
#    (use ESO approle to read every kv/data/platform/* path; encrypt with sops/age before storing)
ROLE_ID=<ESO approle role-id from ClusterSecretStore>
SECRET_ID=<from kubernetes secret eso-runtime-secret-id>
TOKEN=$(curl -sf -X POST http://172.19.0.4:8200/v1/auth/approle/login \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["auth"]["client_token"])')

for svc in auth-service user-service variant-service core-data-service \
           report-service schema-service permission-service openfga; do
  curl -sf -H "X-Vault-Token: $TOKEN" \
    "http://172.19.0.4:8200/v1/kv/data/platform/$svc" \
    > /tmp/kv-$svc.json
done
# Encrypt + commit to repo via sops/age (separate runbook)

# 3. Stop test vault container, wipe seal data, re-init fresh
cd /home/halil/platform-k8s-gitops/host-compose/vault/test
docker-compose stop platform-vault-test
# Backup raft data dir (depends on volume mount; do NOT delete)
# Re-create container with fresh init
docker-compose up -d platform-vault-test
docker exec platform-vault-test vault operator init \
  -key-shares=3 -key-threshold=2

# 4. Save new keys + root token to state files
# 5. Restore raft snapshot (KV data preserved!)
docker exec platform-vault-test vault operator raft snapshot restore \
  -force /path/to/snapshot

# 6. Re-apply policies (eso-runtime, platform-bootstrap-writer per DR-2)
# 7. Re-create AppRoles
# 8. Force ESO refresh on all ExternalSecrets
# 9. Verify all services pick up resync'd secrets
```

## Phase D — Verify + Hand off

After Phase B (or Phase C):

```bash
# Verify rekey complete + new keyset works
docker exec platform-vault-test vault status | grep -E 'Sealed|Threshold|Total Shares'
# Sealed=false, Total Shares=3, Threshold=2

# Sanity test: try unseal flow with new keys (mock — simulates DR drill)
# (cancel rekey-init if you don't want to actually rekey again; use rekey -verify-init)

# Verify ESO sync still healthy on test cluster
kubectl --context k3d-test -n platform-test get externalsecret -A
# All ESO ES rows should show STATUS=SecretSynced

# Hand off to next agent session: provide
# - new admin token (or AppRole secret-id) for DR-2 bootstrap-writer apply
# - DR drill cadence confirmed (next drill in 30 days per ADR-0010 §2.2)
```

## After successful rekey

- **DR-4 unblocked**: agent (next session) can apply `platform-bootstrap-writer` policy + AppRole + run wrapper script per `docs/RB-vault-bootstrap-writer-apply.md`.
- **DR drill**: schedule first quarterly drill 30 days from rekey date (per ADR-0010 §2.2).
- **DR bundle commit**: `dr-bundle-<date>/` content (raft snapshot + key checksums + AppRole inventory) committed to encrypted bundle storage (NOT plain Git; use sops/age or out-of-band encrypted location).
- **Prod DR inventory**: DR-8 PR (read-only verify of prod vault DR readiness) — agent can drive, but actual prod rekey if needed = DR-9 with separate user approval.

## Security notes

- **Never write root token to plain file**: use environment variable + immediately revoke after use.
- **Never commit raft snapshots to Git**: they contain encrypted KV data; treat as ESO-equivalent.
- **Audit trail**: all rekey operations should be visible in audit logs if `vault audit enable` is configured (verify in Phase D).
- **Rotation**: AppRole secret-ids issued in Phase D should have TTL ≤ 60min; rotate them in DR-3 wrapper invocations per ADR-0010 §2.1.

## References

- ADR-0010 §2.2 (DR contract), §2.5 (operator/agent authority)
- 2026-04-28 DR-6 readiness check evidence (`docs/faz-21-3-evidence/2026-04-28-dr-6-readiness-check.md`)
- 2026-04-28 ADR-0010 PR #196 — DR drift note in `current-state.md`
- Codex thread `019dd2c9` (strategic foundation)
- Vault docs: § Rekeying Vault, § Generate Root, § Raft Snapshot, § Audit Devices
