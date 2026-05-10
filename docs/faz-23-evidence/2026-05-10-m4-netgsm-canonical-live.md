# M4 — NetGSM SMS Canonical Vault Path LIVE Evidence

> **Status**: 🟢 LIVE (Session 42 2026-05-10 06:55Z)
> **Sub-faz**: 23.3.1 (Production MVP geniş — SMS NetGSM)
> **Risk**: R1 (NetGSM contract gating; Vault path infrastructure mitigated)
> **PR**: #482 squash 2ae040d (PR #384 redesign)

## Summary

PR #384 (split-path `kv/platform/notify/sms/netgsm`) Codex iter-3 (thread `019e109b`) REVISE absorb: split path deprecated; canonical flat path `kv/platform/notification-orchestrator` is the working convention used by 10 platform services + new prod manifest. PR #482 redesigned the manifest + Vault seed to align with canonical pattern.

Cross-AI peer review chain (HARD RULE 2026-05-05):
- Codex iter-3 (thread `019e109b`) — REVISE: split path deprecated, 4-key DLR drift, mergeable=false
- Codex iter-4 (thread `019e10a4`) — AGREE: technical content OK, ready_to_merge pending CI green
- CI: 12/12 green (BG-1 retrigger after PR body 7-class boundary fix)
- Merge: 2ae040d squash 2026-05-10 06:51Z

## Vault seed evidence (Pre-Production Full Authority 2026-05-10 06:41:16Z)

```bash
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" -e VAULT_ADDR=http://127.0.0.1:8200 \
  platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator \
    sms_netgsm_username='' \
    sms_netgsm_password='' \
    sms_netgsm_msgheader='Notify'
```

`patch` (not `put`) preserves existing 5 keys (db_username, db_password, webhook_signing_secret, authz_internal_api_key, redaction_pepper) so ESO sync continues uninterrupted.

Vault verify (`kv get`):

```
Key                       Value
---                       -----
authz_internal_api_key    dev-only-key-not-for-production
db_password               <rotated 2026-05-10 06:54Z — see PG drift fix below>
db_username               platform
redaction_pepper          dev-only-pepper-not-for-production
sms_netgsm_msgheader      Notify
sms_netgsm_password       (empty — fail-closed)
sms_netgsm_username       (empty — fail-closed)
webhook_signing_secret    <unchanged>
```

## Cluster apply evidence

```bash
kubectl --context k3d-test apply -k kustomize/overlays/test/eso
# Output:
# clustersecretstore.external-secrets.io/vault-platform-gitops unchanged
# externalsecret.external-secrets.io/alertmanager-fallback-secrets configured
# externalsecret.external-secrets.io/endpoint-admin-service-secrets configured
# externalsecret.external-secrets.io/ghcr-pull configured
# externalsecret.external-secrets.io/notification-orchestrator-secrets configured
```

## ESO sync evidence

After `kubectl annotate externalsecret notification-orchestrator-secrets force-sync=$ts --overwrite`:

```bash
kubectl --context k3d-test -n platform-test get secret notification-orchestrator-secrets -o jsonpath='{.data}' | python3 -c '...'
# Output: 8 keys: NOTIFY_ADAPTERS_SMS_NETGSM_MSGHEADER, NOTIFY_ADAPTERS_SMS_NETGSM_PASSWORD,
#                 NOTIFY_ADAPTERS_SMS_NETGSM_USERNAME, NOTIFY_ADAPTERS_WEBHOOK_SIGNING_SECRET,
#                 NOTIFY_AUTHZ_INTERNAL_API_KEY, NOTIFY_REDACTION_PEPPER,
#                 SPRING_DATASOURCE_PASSWORD, SPRING_DATASOURCE_USERNAME
```

Status:
```
.status.conditions[0].status=True
.status.conditions[0].message=secret synced
```

## Pod env injection evidence

```bash
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s
# deployment "notification-orchestrator" successfully rolled out

kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- env | grep '^NOTIFY_ADAPTERS_SMS_NETGSM_'
# NOTIFY_ADAPTERS_SMS_NETGSM_MSGHEADER=Notify
# NOTIFY_ADAPTERS_SMS_NETGSM_PASSWORD=
# NOTIFY_ADAPTERS_SMS_NETGSM_USERNAME=
```

Pod state: 1/1 Running, RESTARTS=0, env injection complete.

## PG password drift fix (operational fix — out-of-band)

**Issue**: ESO `creationPolicy: Owner` mode on first force-sync overwrote the K8s `notification-orchestrator-secrets` Secret with Vault placeholder values (`db_password=change-me-local-only`). PG had a different password (drift from earlier session). Hikari authentication failed → notify-orchestrator pod CrashLoopBackOff.

**Fix** (rotation pattern, alphanumeric to avoid Spring `$` interpolation):

```bash
PWD=$(openssl rand -hex 16)
docker exec platform-pg-test psql -U postgres -d notify_db \
  -c "ALTER USER platform WITH PASSWORD '$PWD';"
# ALTER ROLE

docker exec -e VAULT_TOKEN="$TOKEN" -e VAULT_ADDR=http://127.0.0.1:8200 \
  platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator db_password="$PWD"
# Success: kv/data/platform/notification-orchestrator (version bumped)

kubectl --context k3d-test -n platform-test annotate externalsecret \
  notification-orchestrator-secrets force-sync=$(date +%s) --overwrite
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s
# deployment "notification-orchestrator" successfully rolled out
```

**Pattern note**: ESO Owner mode + K8s Secret authoritative. Future password drift fixes require both PG `ALTER USER` and Vault `kv patch` in a single operator action; manual `kubectl edit secret` is a no-op (overwritten on next ESO reconcile).

## Browser console evidence (HARD RULE 2026-05-08 deploy verify)

```
URL: https://testai.acik.com/
Console messages: 3 DEBUG (ag-grid-license resolved, no error/warn)
Network requests: page-internal MFE assets, no 401/403/404/500
```

PR #482 ConfigMap-only test overlay change; no frontend regression observed.

## D29-NOTIFY-Functional state

| Layer | Pre-PR #482 | Post-PR #482 |
|---|---|---|
| Up | 1/1 Running notify-orchestrator | 1/1 Running notify-orchestrator |
| Functional | Mailgun + Slack + webhook adapters wired | + SMS NetGSM env vars present (empty creds → fail-closed) |
| Authorized | Strict identity guards LIVE | Unchanged |
| **Vault path** | 5 keys (5/5 Ready) | **8 keys (8/8 Ready, canonical flat path)** |

## R1 NetGSM contract status

| Aspect | Status |
|---|---|
| Vault path infrastructure | 🟢 LIVE (canonical kv/platform/notification-orchestrator with sms_netgsm_*) |
| ExternalSecret manifest | 🟢 LIVE (3 secretKey entries on canonical path) |
| Pod env injection | 🟢 LIVE (MSGHEADER=Notify, USERNAME/PASSWORD empty) |
| Adapter fail-closed behavior | 🟢 Verified by spec (R12 fail-closed pattern) |
| **NetGSM contract activation** | 🟡 R1 ACTIVE (owner: ops + legal, ETA 2026-05-30) |
| Real credentials populated | 🔴 Pending contract; populated via `vault kv put` post-contract |

## Sub-faz 23.3.1 progress

| Component | Status |
|---|---|
| Backend SmsAdapter (NetGSM) | 🟢 LIVE (platform-backend PR #77) |
| Vault path canonical | 🟢 LIVE (this PR #482) |
| Test overlay ESO entries | 🟢 LIVE (this PR #482) |
| Prod overlay ESO entries | ⏳ Pending (D29 evidence gate, separate PR) |
| DLR token entry | ⏳ Pending (follow-up PR + Vault seed) |
| HPA SMS metric (`notify_sms_send_total{status}`) | ⏳ Pending (Faz 23.3.2) |
| IYS consent gate | ⏳ Pending (Faz 23.3.2) |
| Multi-provider failover (Twilio fallback) | ⏳ Pending (Faz 23.3.3) |

## PR #384 closure

Closed 2026-05-10 06:52Z with cross-reference comment to PR #482 (superseded — split path deprecated).

## Refs

- PR #482: https://github.com/Halildeu/platform-k8s-gitops/pull/482
- PR #384 (closed): https://github.com/Halildeu/platform-k8s-gitops/pull/384
- Codex iter-3 thread: `019e109b`
- Codex iter-4 thread: `019e10a4`
- Charter sub-faz 23.3.1: `docs/runbooks/RB-faz-23-charter.md`
- Risk register R1 (NetGSM contract): `docs/notify/risk-register.md`
- ADR-0013 §SMS adapter: `docs/adr/0013-notification-orchestration.md`
