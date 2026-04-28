# Runbook — Apply `platform-bootstrap-writer` AppRole (Test Vault First)

> **DR-2 of ADR-0010** (`docs/adr/0010-vault-credential-lifecycle-and-dr.md`).
> **Codex consensus**: thread `019dd2c9`.
> **User-approval boundary**: this runbook applies to **test vault only**. Prod equivalent is DR-9 and requires explicit user approval per ADR-0010 §2.5.

## Purpose

Apply `bootstrap/vault-policies/common/bootstrap-writer.hcl` policy + create the `platform-bootstrap-writer` AppRole on the **test vault** instance. Run capabilities-self verification + negative tests to confirm the boundary holds.

**Pre-condition**: A Vault token with policy-write capability. This is currently blocked on test vault because of the stale unseal keyset (Codex `019dd2c9` §5: prod Vault rekey/restart is user-approval-gated; test Vault re-init is also user-approval-gated). Until that resolves, this runbook is **planned but unapplied**. DR-3 (wrapper script) and DR-4 (SoD unblock) consume the apply outcome.

If you have a valid root or admin token (e.g., regenerated via the DR keyset fix tracked in the spawned chip), proceed with the steps below. Otherwise, this runbook stays in "planned" state and downstream DRs (DR-3/DR-4) wait.

## Step 0 — Verify pre-conditions

```bash
ssh halil@staging-sw 'docker exec platform-vault-test vault status' \
  | grep -E "Sealed|Initialized|Threshold|Total Shares"
```

Expected: `Sealed=false`, `Initialized=true`, `Total Shares=3`, `Threshold=2`.

If sealed → stop. Unseal first (separate operator action).

## Step 1 — Apply the policy (admin token required)

```bash
ssh halil@staging-sw '
ADMIN_TOKEN="$1"  # operator provides; root or admin policy
docker exec -e VAULT_TOKEN="$ADMIN_TOKEN" platform-vault-test \
  vault policy write platform-bootstrap-writer \
  /vault/policies/bootstrap-writer.hcl
' apply -- "$ADMIN_TOKEN"
```

(Operator must mount or copy `bootstrap/vault-policies/common/bootstrap-writer.hcl` into the container under `/vault/policies/`. Compose mount: `./bootstrap/vault-policies/common/:/vault/policies/:ro` is recommended; check `host-compose/vault/test/docker-compose.yml`.)

Expected: `Success! Uploaded policy: platform-bootstrap-writer`.

## Step 2 — Verify policy contents

```bash
ssh halil@staging-sw '
docker exec -e VAULT_TOKEN="$1" platform-vault-test \
  vault policy read platform-bootstrap-writer
' read -- "$ADMIN_TOKEN"
```

Expected: full HCL contents echoed back. Compare against the file in repo.

## Step 3 — Create the AppRole

```bash
ssh halil@staging-sw '
docker exec -e VAULT_TOKEN="$1" platform-vault-test \
  vault write auth/approle/role/platform-bootstrap-writer \
  token_policies=platform-bootstrap-writer \
  token_ttl=30m \
  token_max_ttl=60m \
  secret_id_ttl=60m \
  secret_id_num_uses=10 \
  bind_secret_id=true
' approle-create -- "$ADMIN_TOKEN"
```

Expected: `Success! Data written to auth/approle/role/platform-bootstrap-writer`.

## Step 4 — Generate role-id + secret-id (for DR-3 wrapper)

```bash
ssh halil@staging-sw '
ROLE_ID=$(docker exec -e VAULT_TOKEN="$1" platform-vault-test \
  vault read -field=role_id auth/approle/role/platform-bootstrap-writer/role-id)
SECRET_ID=$(docker exec -e VAULT_TOKEN="$1" platform-vault-test \
  vault write -force -field=secret_id auth/approle/role/platform-bootstrap-writer/secret-id)

echo "role-id (commit-safe, semi-public): $ROLE_ID"
# secret-id is sensitive — DO NOT log; transfer via secure channel only
echo "$SECRET_ID" > /tmp/bootstrap-writer-secret-id.txt
chmod 600 /tmp/bootstrap-writer-secret-id.txt
echo "secret-id saved to /tmp/bootstrap-writer-secret-id.txt (perms 600)"
' approle-credentials -- "$ADMIN_TOKEN"
```

`role-id` is OK to print to terminal. `secret-id` MUST stay in the protected temp file. The wrapper (DR-3) reads both at invocation time.

## Step 5 — capabilities-self positive verification

Verify the bootstrap-writer can do what it should:

```bash
ssh halil@staging-sw '
ROLE_ID="$1"
SECRET_ID=$(cat /tmp/bootstrap-writer-secret-id.txt)
TOKEN=$(curl -s -X POST http://127.0.0.1:8301/v1/auth/approle/login \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[\"auth\"][\"client_token\"])")

# Positive — should have create + update + read on permission-service path
curl -s -X POST -H "X-Vault-Token: $TOKEN" \
  http://127.0.0.1:8301/v1/sys/capabilities-self \
  -d "{\"paths\":[\"kv/data/platform/permission-service\"]}" \
  | python3 -m json.tool
' caps-positive -- "$ROLE_ID"
```

Expected JSON:
```json
{
  "kv/data/platform/permission-service": ["create", "read", "update"],
  "capabilities": ["create", "read", "update"],
  ...
}
```

**Gate**: must contain `create` + `update` + `read`. Must NOT contain `delete` or `sudo`.

## Step 6 — Negative tests (boundary verification)

The role must FAIL on each of these:

```bash
ssh halil@staging-sw '
ROLE_ID="$1"
SECRET_ID=$(cat /tmp/bootstrap-writer-secret-id.txt)
TOKEN=$(curl -s -X POST http://127.0.0.1:8301/v1/auth/approle/login \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[\"auth\"][\"client_token\"])")

echo "--- Test 1: DELETE on kv/metadata (must fail 403):"
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X DELETE -H "X-Vault-Token: $TOKEN" \
  http://127.0.0.1:8301/v1/kv/metadata/platform/permission-service

echo "--- Test 2: sys/policy write (must fail 403):"
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X PUT -H "X-Vault-Token: $TOKEN" \
  http://127.0.0.1:8301/v1/sys/policy/platform-bootstrap-writer \
  -d "{\"policy\":\"path \\\"foo\\\" { capabilities = [\\\"sudo\\\"] }\"}"

echo "--- Test 3: sys/generate-root/attempt (must fail 403):"
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST -H "X-Vault-Token: $TOKEN" \
  http://127.0.0.1:8301/v1/sys/generate-root/attempt

echo "--- Test 4: auth/approle write (must fail 403):"
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST -H "X-Vault-Token: $TOKEN" \
  http://127.0.0.1:8301/v1/auth/approle/role/platform-bootstrap-writer \
  -d "{\"token_ttl\":\"1h\"}"

echo "--- Test 5: kv/data write on a foreign path (must fail 403):"
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST -H "X-Vault-Token: $TOKEN" \
  http://127.0.0.1:8301/v1/kv/data/platform/non-existent-service \
  -d "{\"data\":{\"foo\":\"bar\"}}"
' negative-tests -- "$ROLE_ID"
```

**Gate**: All 5 tests return HTTP 403. Any 2xx → STOP, fix the policy, do not deploy.

## Step 7 — Audit trail check

If audit is enabled on this Vault, verify the operations from Steps 5+6 left audit log entries with the bootstrap-writer token's accessor:

```bash
ssh halil@staging-sw '
ADMIN_TOKEN="$1"
docker exec -e VAULT_TOKEN="$ADMIN_TOKEN" platform-vault-test \
  vault list sys/audit
' audit-list -- "$ADMIN_TOKEN"
```

If no audit backend → file an issue (separate from this runbook); audit must be enabled per ADR-0010 §2.2.

## Step 8 — Hand off to DR-3

The output of this runbook for DR-3:

- `role-id` (OK to publish in private inventory)
- `secret-id` at `/tmp/bootstrap-writer-secret-id.txt` (perms 600)
- Verified capabilities-self output (Step 5)
- Verified negative tests (Step 6)

DR-3 (wrapper script) consumes role-id + secret-id at invocation; wrapper script handles login + KV v2 patch + token cleanup.

## Rollback

```bash
ssh halil@staging-sw '
ADMIN_TOKEN="$1"
docker exec -e VAULT_TOKEN="$ADMIN_TOKEN" platform-vault-test \
  vault delete auth/approle/role/platform-bootstrap-writer

docker exec -e VAULT_TOKEN="$ADMIN_TOKEN" platform-vault-test \
  vault policy delete platform-bootstrap-writer
' rollback -- "$ADMIN_TOKEN"
```

Vault state returns to pre-DR-2 (only `eso-runtime` policy active for platform paths).

## Cleanup

```bash
ssh halil@staging-sw '
shred -u /tmp/bootstrap-writer-secret-id.txt 2>/dev/null
echo "secret-id file shredded"
'
```

## Verification — success criteria

- [ ] Step 1: policy applied, `vault policy read` echoes contents
- [ ] Step 2: policy verified vs file
- [ ] Step 3: AppRole created with TTL constraints
- [ ] Step 4: role-id captured, secret-id saved (file mode 600)
- [ ] Step 5: capabilities-self returns `["create", "read", "update"]` for permission-service path; no `delete`
- [ ] Step 6: All 5 negative tests return HTTP 403
- [ ] Step 7: audit trail visible (or audit-not-enabled issue filed)

When all checked → DR-2 complete. Proceed to DR-3 (wrapper script PR).

## References

- ADR-0010 (`docs/adr/0010-vault-credential-lifecycle-and-dr.md`) §2.1 — credential lifecycle
- `bootstrap/vault-policies/common/bootstrap-writer.hcl` — the policy applied here
- Codex thread `019dd2c9` — strategic context
- DR-3 (next): `scripts/platform-ops-vault-patch.sh` wrapper consuming this AppRole
