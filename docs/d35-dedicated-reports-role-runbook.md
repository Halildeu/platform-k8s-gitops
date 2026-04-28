# D35 Follow-up — Dedicated `reports_db` Role + Vault Populate Runbook

> **Operator-driven, post-PR-merge.** Removes the PR #191 shared-credential
> caveat and lands the proper SoD (separation-of-duties) for permission-service
> against `reports_db` on staging-sw k3d-test.

**Codex thread**: `019dd2af` (verdict on grant matrix + sequencing).

## Pre-conditions

- This PR (V24 ops SQL + runbook + test overlay revert of PR #191 alias patches) is MERGED to `main`.
- staging-sw `git pull origin main` brings the new `sql/ops/01_reports_db_permission_role.sql` to the host.
- V19+V20+V21+V22+V23 are already applied to `reports_db` (verified in 2026-04-28 outbox preflight evidence).
- Permission-service is running on PR-G follow-up image (`sha-4f408f4`).

## Step 0 — Inventory (single command)

```bash
ssh halil@staging-sw "cd ~/platform-k8s-gitops && git log --oneline -1 && \
  echo '---' && \
  PG_PWD=\$(sudo grep '^REPORT_PG_PASSWORD=' /home/halil/platform/env/backend.env | cut -d= -f2) && \
  docker exec -e PGPASSWORD=\"\$PG_PWD\" platform-pg-test psql -U postgres -d reports_db -t -c \
    \"SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname IN ('platform','permission_reports_writer');\""
```

Expected:
- HEAD pointing at the V24 ops merge commit
- Exactly one row: `platform | t`
- (No `permission_reports_writer` row yet — Step 1 creates it)

## Step 1 — Apply V24 ops SQL as DB superuser

```bash
ssh halil@staging-sw "cd ~/platform-k8s-gitops && \
  PG_PWD=\$(sudo grep '^REPORT_PG_PASSWORD=' /home/halil/platform/env/backend.env | cut -d= -f2) && \
  docker exec -i -e PGPASSWORD=\"\$PG_PWD\" platform-pg-test \
    psql -U postgres -d reports_db -v ON_ERROR_STOP=1 \
    < sql/ops/01_reports_db_permission_role.sql"
```

Expected output (last 5 lines):
```text
DO
GRANT
GRANT
ALTER DEFAULT PRIVILEGES
COMMIT
```

Verify role exists with NOLOGIN:
```bash
ssh halil@staging-sw "PG_PWD=\$(sudo grep '^REPORT_PG_PASSWORD=' /home/halil/platform/env/backend.env | cut -d= -f2) && \
  docker exec -e PGPASSWORD=\"\$PG_PWD\" platform-pg-test psql -U postgres -d reports_db -c \
    \"SELECT rolname, rolcanlogin, rolsuper, rolcreaterole, rolcreatedb FROM pg_roles \
       WHERE rolname = 'permission_reports_writer';\""
```

Expected: `permission_reports_writer | f | f | f | f` (login disabled, no super/create rights).

## Step 2 — Generate password + ALTER ROLE LOGIN

```bash
ssh halil@staging-sw "
NEW_PWD=\$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | cut -c1-44)
echo \"\$NEW_PWD\" > /tmp/permission-reports-writer-pwd.txt
chmod 600 /tmp/permission-reports-writer-pwd.txt
echo 'Generated password (length: '\${#NEW_PWD}'). Saved to /tmp/permission-reports-writer-pwd.txt for next steps.'

PG_PWD=\$(sudo grep '^REPORT_PG_PASSWORD=' /home/halil/platform/env/backend.env | cut -d= -f2)
docker exec -e PGPASSWORD=\"\$PG_PWD\" platform-pg-test psql -U postgres -d reports_db -c \
  \"ALTER ROLE permission_reports_writer WITH LOGIN PASSWORD '\$NEW_PWD';\"
"
```

Expected: `ALTER ROLE`. Operator notes the file `/tmp/permission-reports-writer-pwd.txt` for Step 4 (delete after Vault populate).

## Step 3 — DB smoke test (BEFORE Vault populate)

This is the gate per Codex: confirm grants are correct against the live PG.

```bash
ssh halil@staging-sw "
NEW_PWD=\$(cat /tmp/permission-reports-writer-pwd.txt)
docker exec -e PGPASSWORD=\"\$NEW_PWD\" platform-pg-test psql -U permission_reports_writer -d reports_db <<'EOF'
SELECT current_user;
SELECT has_table_privilege('permission_reports_writer','data_access.scope','SELECT,INSERT,UPDATE')      AS scope_can_select_insert_update;
SELECT has_table_privilege('permission_reports_writer','data_access.scope','DELETE')                    AS scope_delete_must_be_false;
SELECT has_table_privilege('permission_reports_writer','data_access.scope_outbox','SELECT,INSERT,UPDATE') AS outbox_can_select_insert_update;
SELECT has_table_privilege('permission_reports_writer','data_access.scope_outbox','DELETE')             AS outbox_delete_must_be_false;
SELECT has_table_privilege('permission_reports_writer','data_access.organization','SELECT')             AS org_can_select;
SELECT has_table_privilege('permission_reports_writer','data_access.organization_company','SELECT')     AS orgcomp_can_select;
SELECT has_table_privilege('permission_reports_writer','workcube_mikrolink.company','SELECT')           AS wc_company_can_select;
SELECT has_table_privilege('permission_reports_writer','workcube_mikrolink.pro_projects','SELECT')      AS wc_proj_can_select;
SELECT has_table_privilege('permission_reports_writer','workcube_mikrolink.branch','SELECT')            AS wc_branch_can_select;
SELECT has_table_privilege('permission_reports_writer','workcube_mikrolink.department','SELECT')        AS wc_dept_can_select;
SELECT has_function_privilege('permission_reports_writer','data_access.validate_scope_ref(text,text,text)','EXECUTE') AS can_execute_validate;
SELECT has_function_privilege('permission_reports_writer','data_access.recover_stuck_outbox_rows(interval)','EXECUTE') AS can_execute_recover;
SELECT has_sequence_privilege('permission_reports_writer','data_access.scope_id_seq','USAGE')           AS scope_seq_usable;
SELECT has_sequence_privilege('permission_reports_writer','data_access.scope_outbox_id_seq','USAGE')    AS outbox_seq_usable;
EOF
"
```

Expected results table (in order):
```text
current_user                          | permission_reports_writer
scope_can_select_insert_update        | t
scope_delete_must_be_false            | f
outbox_can_select_insert_update       | t
outbox_delete_must_be_false           | f
org_can_select                        | t
orgcomp_can_select                    | t
wc_company_can_select                 | t
wc_proj_can_select                    | t
wc_branch_can_select                  | t
wc_dept_can_select                    | t
can_execute_validate                  | t
can_execute_recover                   | t
scope_seq_usable                      | t
outbox_seq_usable                     | t
```

**Gate**: every row must be `t`, except the two `*_delete_must_be_false` rows which must be `f`. Any other shape → STOP, do not proceed to Vault populate.

## Step 4 — Vault populate

### 4a (preferred) — Use AppRole if it has write capability on `kv/platform/permission-service`

If the existing ESO approle has `update` capability (test):

```bash
ssh halil@staging-sw "
SID=\$(kubectl --context k3d-test -n external-secrets get secret vault-approle-secret \
  -o jsonpath='{.data.secret-id}' | base64 -d)
RID='6e2e8407-74d4-6e21-0ad7-ba200f601761'
TOKEN=\$(curl -s -X POST http://172.19.0.4:8200/v1/auth/approle/login \
  -d \"{\\\"role_id\\\":\\\"\${RID}\\\",\\\"secret_id\\\":\\\"\${SID}\\\"}\" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"auth\"][\"client_token\"])')

curl -sf -X POST -H \"X-Vault-Token: \$TOKEN\" \
  http://172.19.0.4:8200/v1/sys/capabilities-self \
  -d '{\"paths\":[\"kv/data/platform/permission-service\"]}' \
  | python3 -c 'import sys,json; print(\"caps:\", json.load(sys.stdin)[\"capabilities\"])'
"
```

If output includes `update` → proceed below. If only `read` (current state confirmed 2026-04-28) → skip to Step 4b.

```bash
ssh halil@staging-sw "
NEW_PWD=\$(cat /tmp/permission-reports-writer-pwd.txt)
SID=\$(kubectl --context k3d-test -n external-secrets get secret vault-approle-secret \
  -o jsonpath='{.data.secret-id}' | base64 -d)
RID='6e2e8407-74d4-6e21-0ad7-ba200f601761'
TOKEN=\$(curl -s -X POST http://172.19.0.4:8200/v1/auth/approle/login \
  -d \"{\\\"role_id\\\":\\\"\${RID}\\\",\\\"secret_id\\\":\\\"\${SID}\\\"}\" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"auth\"][\"client_token\"])')

# Read existing data first (kv-v2 patch requires preserving keys)
EXISTING=\$(curl -sf -H \"X-Vault-Token: \$TOKEN\" \
  http://172.19.0.4:8200/v1/kv/data/platform/permission-service \
  | python3 -c 'import sys,json; print(json.dumps(json.load(sys.stdin)[\"data\"][\"data\"]))')

# Merge new keys
PATCHED=\$(echo \"\$EXISTING\" | python3 -c \"
import sys, json
d = json.load(sys.stdin)
d['reports_db_username'] = 'permission_reports_writer'
d['reports_db_password'] = '\$NEW_PWD'
print(json.dumps(d))\")

# Write back via kv-v2 PATCH
curl -sf -X POST -H \"X-Vault-Token: \$TOKEN\" \
  http://172.19.0.4:8200/v1/kv/data/platform/permission-service \
  -d \"{\\\"data\\\": \$PATCHED}\"
"
```

Expected: a JSON response with `\"data\":{\"version\":<n+1>}` indicating success.

### 4b (fallback) — Generate root token via 3 unseal keys

If approle lacks `update` capability:

```bash
ssh halil@staging-sw "
export VAULT_ADDR=http://127.0.0.1:8301  # test Vault host port

OTP=\$(vault operator generate-root -generate-otp 2>/dev/null || echo \"INSTALL VAULT CLI FIRST\")
# Or use the API equivalent:
# curl -s -X PUT -d '{}' http://127.0.0.1:8301/v1/sys/generate-root/attempt
# (returns nonce + otp pair)

# Operator follows the standard generate-root flow with the 3 unseal keys
# stored at /home/halil/platform/state/vault/vault-unseal-key-{1,2,3}.
# After decode, ROOT_TOKEN environment variable is set.

# vault kv patch -mount=kv platform/permission-service \\
#   reports_db_username=permission_reports_writer \\
#   reports_db_password=\\\"\\\$(cat /tmp/permission-reports-writer-pwd.txt)\\\"

# vault token revoke -self
"
```

(Detailed root-regen procedure outside this runbook — see Vault docs §Root token generation. Operator notes: the unseal keys are at `/home/halil/platform/state/vault/vault-unseal-key-{1,2,3}` per host inventory 2026-04-28.)

## Step 5 — ESO force-refresh + Secret verify

```bash
ssh halil@staging-sw "
kubectl --context k3d-test -n platform-test annotate externalsecret \
  permission-service-secrets force-sync=\$(date +%s) --overwrite

# Wait for SecretSynced
for i in \$(seq 1 12); do
  REASON=\$(kubectl --context k3d-test -n platform-test get externalsecret \
    permission-service-secrets -o jsonpath='{.status.conditions[-1].reason}')
  echo \"  attempt \$i: reason=\$REASON\"
  if [[ \"\$REASON\" == 'SecretSynced' ]]; then break; fi
  sleep 4
done

echo '--- Secret REPORTS_DB_USERNAME (decoded):'
kubectl --context k3d-test -n platform-test get secret permission-service-secrets \
  -o jsonpath='{.data.REPORTS_DB_USERNAME}' | base64 -d
echo
"
```

Expected: `permission_reports_writer` (NOT `platform`).

## Step 6 — Permission-service rollout restart

```bash
ssh halil@staging-sw "
kubectl --context k3d-test -n platform-test rollout restart deploy/permission-service
kubectl --context k3d-test -n platform-test rollout status deploy/permission-service --timeout=180s
"
```

Expected: `deployment 'permission-service' successfully rolled out`.

## Step 7 — Verify runtime env + outbox poller still alive

```bash
ssh halil@staging-sw "
POD=\$(kubectl --context k3d-test -n platform-test get pod \
  -l app.kubernetes.io/name=permission-service \
  -o jsonpath='{.items[0].metadata.name}')

echo '--- env:'
kubectl --context k3d-test -n platform-test exec \$POD -- env \
  | grep -E 'REPORTS_DB_(ENABLED|USERNAME|URL)'

echo '--- outbox poller alive (prometheus):'
kubectl --context k3d-test -n platform-test exec \$POD \
  -- wget -qO- http://localhost:8081/actuator/prometheus 2>/dev/null \
  | grep -E 'tasks_scheduled_execution_seconds_count\\{.*OutboxPoller.*outcome=\"SUCCESS\"\\}'
"
```

Expected:
- `REPORTS_DB_USERNAME=permission_reports_writer`
- A non-zero `tasks_scheduled_execution_seconds_count{...OutboxPoller...outcome="SUCCESS"}` value

## Step 8 — Capture second preflight evidence

```bash
ssh halil@staging-sw "
RUN_ID=\"d35-prereq-second-\$(date +%Y%m%d-%H%M)\"
echo \"Capturing evidence as docs/faz-21-3-evidence/\$RUN_ID-dedicated-role.md\"
# Operator copies the new pod's imageID, env vars (with REDACTED for password),
# poller metrics, and reports_db psql verification (login as permission_reports_writer)
# into a fresh evidence file. Same template as 2026-04-28-outbox-isolated-preflight.md
# but with caveat removed and dedicated-role attestation added.
"
```

## Step 9 — Cleanup

```bash
ssh halil@staging-sw "
shred -u /tmp/permission-reports-writer-pwd.txt
echo 'Password file shredded.'
"
```

## Rollback (if anything fails)

1. **Bad grant or missing privilege**: re-apply `sql/ops/01_reports_db_permission_role.sql` (idempotent), retry Step 3 smoke.

2. **Vault patch wrong**: re-patch with the OLD shared-cred values (`reports_db_username=platform`, `reports_db_password=<existing db_password>`), force-refresh ESO, rollout restart. Permission-service falls back to PR #191 behavior (operational, with caveat).

3. **Permission-service crashloop after rollout**: scale deployment to 0, revert Vault to old values, scale back up. Investigate before retrying.

4. **Need to fully disable role temporarily**:
   ```sql
   ALTER ROLE permission_reports_writer NOLOGIN;
   ```
   Permission-service Hikari connection retries will fail; this is the kill-switch.

## Verification — what changes after this runbook

| Aspect | Before (PR #191) | After (this runbook) |
|---|---|---|
| `REPORTS_DB_USERNAME` | `platform` (DB owner) | `permission_reports_writer` (LP role) |
| `REPORTS_DB_PASSWORD` | shared with `db_password` | dedicated 44-char random |
| Vault `kv/platform/permission-service` keys | `db_username`, `db_password`, …, no `reports_db_*` | + `reports_db_username`, `reports_db_password` |
| ExternalSecret `/spec/data/6,7/remoteRef/property` | `db_username`/`db_password` (test overlay alias) | `reports_db_username`/`reports_db_password` (base contract) |
| `data_access.scope` DELETE on production role | available (owner privilege) | DENIED (Codex 019dd2af) |
| Audit trail | `revoked_at` UPDATE only | `revoked_at` UPDATE only — same |
| Outbox PROCESSED rows retained | yes | yes — DELETE not in role grants |

## D35 status after this runbook

This runbook does NOT unblock D35 first evidence by itself. D35 still waits on real Workcube ETL data in `workcube_mikrolink.company`. After ETL load, run PR #189 runbook Step 9.4-9.11 with this dedicated role active — that becomes the authoritative D35 first evidence with proper SoD.

## References

- PR #191 (test overlay shared-cred patch — Codex `019dd296` verdict B; reverted by this PR)
- PR #192 (outbox isolated preflight evidence with shared-cred caveat)
- PR #193 (current-state Session 31 delta)
- platform-backend PR #16 (PR-G follow-up — AccessScopeService.revoke() soft-delete confirmed)
- Codex thread `019dd2af` (this design review)
- ADR-0009 (canlı scoped E2E gate — D35 contract)
