# Runbook — DR-9 Prod Bootstrap-Writer Apply (User-Driven)

> **DR-9 of ADR-0010** (`docs/adr/0010-vault-credential-lifecycle-and-dr.md` §2.1, §2.5).
> **Codex consensus**: thread `019dd2c9` (xhigh effort architecture).
> **Authority**: user-driven only. Per ADR-0010 §2.5: prod write/rotation requires explicit user approval.
> **Why**: completes the 9-PR sequence; replicates DR-2/DR-3/DR-4 outcomes on prod after DR-8 inventory confirms prod DR readiness.

## Pre-conditions

- [ ] DR-8 inventory complete (`docs/RB-vault-prod-dr-inventory.md` executed; verdict: prod DR recoverable + audit configured + ESO healthy).
- [ ] DR-8 evidence file committed (`docs/faz-21-3-evidence/<date>-d35-prod-vault-dr-inventory.md`).
- [ ] User has prod admin token OR DR-8 confirmed sufficient unseal keys + threshold to generate one.
- [ ] DR-2/DR-3/DR-4 already validated on test vault (test side proven working before prod).

## Phase 1 — Apply policy (admin token)

```bash
ssh halil@staging-sw '
ADMIN_TOKEN="$1"  # operator provides; root or admin policy on prod vault

# Verify token has policy-write capability before applying
docker exec -e VAULT_TOKEN="$ADMIN_TOKEN" platform-vault-prod \
  vault token capabilities sys/policy/platform-bootstrap-writer
# Expected: ["create", "update", "delete", "read", "list"]

# Apply policy
docker cp /home/halil/platform-k8s-gitops/bootstrap/vault-policies/common/bootstrap-writer.hcl \
  platform-vault-prod:/tmp/bootstrap-writer.hcl
docker exec -e VAULT_TOKEN="$ADMIN_TOKEN" platform-vault-prod \
  vault policy write platform-bootstrap-writer /tmp/bootstrap-writer.hcl
docker exec platform-vault-prod rm /tmp/bootstrap-writer.hcl
' apply -- "$PROD_ADMIN_TOKEN"
```

Expected: `Success! Uploaded policy: platform-bootstrap-writer`.

## Phase 2 — Create prod AppRole

```bash
ssh halil@staging-sw '
docker exec -e VAULT_TOKEN="$1" platform-vault-prod \
  vault write auth/approle/role/platform-bootstrap-writer-prod \
  token_policies=platform-bootstrap-writer \
  token_ttl=15m \
  token_max_ttl=30m \
  secret_id_ttl=30m \
  secret_id_num_uses=5 \
  bind_secret_id=true
' approle-create -- "$PROD_ADMIN_TOKEN"
```

**Note prod-specific tightening vs test (DR-2 had token_ttl=30m, secret_id_num_uses=10)**:
- Prod token_ttl reduced 30m → 15m
- Prod secret_id_ttl reduced 60m → 30m
- Prod secret_id_num_uses reduced 10 → 5

These tighter constraints are appropriate for prod blast radius.

## Phase 3 — Generate prod role-id + secret-id

```bash
ssh halil@staging-sw '
ROLE_ID=$(docker exec -e VAULT_TOKEN="$1" platform-vault-prod \
  vault read -field=role_id auth/approle/role/platform-bootstrap-writer-prod/role-id)
SECRET_ID=$(docker exec -e VAULT_TOKEN="$1" platform-vault-prod \
  vault write -force -field=secret_id auth/approle/role/platform-bootstrap-writer-prod/secret-id)

echo "role-id (semi-public): $ROLE_ID"
echo "$SECRET_ID" > /tmp/bootstrap-writer-prod-secret-id.txt
chmod 600 /tmp/bootstrap-writer-prod-secret-id.txt
echo "secret-id saved to /tmp/bootstrap-writer-prod-secret-id.txt (perms 600)"
echo "secret-id TTL: 30m, num-uses: 5 — use efficiently"
' approle-credentials -- "$PROD_ADMIN_TOKEN"
```

## Phase 4 — Capabilities-self positive verification (prod approle)

```bash
ssh halil@staging-sw '
ROLE_ID="$1"
SECRET_ID=$(cat /tmp/bootstrap-writer-prod-secret-id.txt)

# Login (consumes 1 of 5 uses)
TOKEN=$(curl -sf -X POST http://172.21.0.6:8200/v1/auth/approle/login \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[\"auth\"][\"client_token\"])")

# Verify create+update+read on each platform service
echo "=== Capability check on prod kv/data/platform/* ==="
for svc in auth-service user-service variant-service core-data-service \
           report-service schema-service permission-service openfga; do
  caps=$(curl -sf -X POST -H "X-Vault-Token: $TOKEN" \
    http://172.21.0.6:8200/v1/sys/capabilities-self \
    -d "{\"paths\":[\"kv/data/platform/$svc\"]}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(",".join(sorted(d[\"capabilities\"])))")
  expected="create,read,update"
  if [ "$caps" = "$expected" ]; then
    echo "  PASS  $svc  ($caps)"
  else
    echo "  FAIL  $svc  (got: $caps; expected: $expected)"
  fi
done

# Self-revoke (1 of 5 uses still consumed)
curl -sf -X POST -H "X-Vault-Token: $TOKEN" \
  http://172.21.0.6:8200/v1/auth/token/revoke-self
unset TOKEN
' caps-positive -- "$ROLE_ID"
```

**Gate**: All 8 services PASS. Any FAIL → STOP, debug policy, do not proceed.

## Phase 5 — Negative tests (prod boundary verification)

Same negative tests as test (`bootstrap/vault-policies/test/bootstrap-writer-verify.sh`); all 8 must return HTTP 403 on prod.

(Re-uses 1 of 5 secret-id uses; if you've already done Phase 4 + Phase 5, you have 3 uses left for actual writes.)

```bash
# Run the verify script with prod vault addr
ssh halil@staging-sw '
ROLE_ID="$1"
export VAULT_ADDR=http://172.21.0.6:8200
export SECRET_ID_FILE=/tmp/bootstrap-writer-prod-secret-id.txt
bash /home/halil/platform-k8s-gitops/bootstrap/vault-policies/test/bootstrap-writer-verify.sh
' verify-prod -- "$ROLE_ID"
```

**Gate**: All negative tests return HTTP 403. Any 2xx → STOP, fix policy.

## Phase 6 — Prod credential populate (per-service, ONE service at a time)

Per ADR-0010 §2.5: each prod credential populate requires user explicit approval. Do NOT batch.

For each service that needs credential rotation or new key (e.g., `permission-service` reports_db_*):

```bash
# For permission-service reports_db (parallel to DR-4 test exercise):
ssh halil@staging-sw '
ROLE_ID="$1"
export VAULT_BOOTSTRAP_ROLE_ID="$ROLE_ID"
export VAULT_BOOTSTRAP_SECRET_ID_FILE=/tmp/bootstrap-writer-prod-secret-id.txt
export VAULT_ADDR=http://172.21.0.6:8200

# Generate prod-specific reports_db password
PROD_REPORTS_PWD=$(openssl rand -base64 48 | tr -dc "A-Za-z0-9" | cut -c1-44)

# Use the wrapper (DR-3) — identical flow to test
echo "$PROD_REPORTS_PWD" | /home/halil/platform-k8s-gitops/scripts/ops/platform-ops-vault-patch.sh \
  --service permission-service \
  --field reports_db_username=permission_reports_writer_prod \
  --field-from-stdin reports_db_password \
  --vault-addr http://172.21.0.6:8200

# Save password to file for next step (PG ALTER ROLE)
echo "$PROD_REPORTS_PWD" > /tmp/permission-reports-writer-prod-pwd.txt
chmod 600 /tmp/permission-reports-writer-prod-pwd.txt
' patch -- "$ROLE_ID"
```

**Note**: prod uses `permission_reports_writer_prod` role (separate from test). DB-side role apply for prod is parallel to `sql/ops/01_reports_db_permission_role.sql` but against prod PG (separate runbook for prod DB role bootstrap).

## Phase 7 — Cleanup

```bash
ssh halil@staging-sw '
shred -u /tmp/bootstrap-writer-prod-secret-id.txt
shred -u /tmp/permission-reports-writer-prod-pwd.txt
echo "Prod secrets shredded."
'
```

## Phase 8 — Audit verify

```bash
docker logs platform-vault-prod 2>&1 | tail -30 | grep -E 'auth|kv/data' || echo 'check audit backend output if file backend'
# Expected: auth login + kv/data writes for the operations performed.
# All operations must be visible in audit trail.
```

## Phase 9 — Capture DR-9 evidence

Write `docs/faz-21-3-evidence/<date>-d35-dr-9-prod-bootstrap-writer.md`:

- Phase 1 policy apply confirmation
- Phase 2 AppRole creation confirmation
- Phase 4 + 5 capabilities-self results (positive + negative)
- Phase 6 patch confirmation (kv version increment shown, NO credential values)
- Phase 8 audit log proof
- Cleanup confirmation

This is **infrastructure DR** evidence (same classification as DR-8); NOT a D35-X tier capture.

## Rollback

If anything fails at Phase 1-7:

```bash
docker exec -e VAULT_TOKEN="$ADMIN_TOKEN" platform-vault-prod \
  vault delete auth/approle/role/platform-bootstrap-writer-prod
docker exec -e VAULT_TOKEN="$ADMIN_TOKEN" platform-vault-prod \
  vault policy delete platform-bootstrap-writer
```

If Phase 6 (credential populate) was partial:
- `vault kv get` to check current state
- `vault kv patch` (via root) to revert to old values OR rotate to new ones
- Force ESO refresh on affected ExternalSecrets
- Restart affected services

## Production safety reminders

- **Never share prod secret-id outside the user-driven session**.
- **Never log prod credentials in plain text**.
- **Never apply test artifacts to prod without DR-8 verify + DR-9 explicit approval**.
- **Audit trail must be enabled** before any prod write (verify Phase 8 BEFORE Phase 6).
- **One service at a time** in Phase 6 — easier rollback, lower blast radius.

## Closes 9-PR sequence

DR-1..DR-9 sequence per ADR-0010:

| # | Status |
|---|---|
| DR-1 (PR #196) | ✓ MERGED |
| DR-2 (PR #197) | ✓ MERGED |
| DR-3 (PR #198) | ✓ MERGED |
| DR-4 (test SoD unblock) | Pending — depends on PR #202 runbook execution |
| DR-5 (PR #199) | ✓ MERGED |
| DR-6 (PR #200, readiness PR #201, MSSQL refresh pending) | Partial |
| DR-7 (test D35-2 first canlı) | Pending — depends on DR-6 + DR-4 |
| DR-8 (this runbook + read-only inventory) | Pending — user-driven |
| DR-9 (this runbook + prod write) | Pending — gated on DR-8 |

After DR-8 + DR-9 evidence committed → ADR-0010 9-PR sequence's documentation + execution closed; ongoing operations governed by drill cadence (§2.2) + per-PR D35 ladder declarations (§2.3).

## References

- ADR-0010 §2.1 (credential lifecycle), §2.2 (DR contract), §2.5 (authority)
- DR-2 PR #197 (test vault bootstrap-writer policy)
- DR-3 PR #198 (vault-patch wrapper)
- DR-8 runbook `docs/RB-vault-prod-dr-inventory.md`
- Codex thread `019dd2c9`
