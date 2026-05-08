# Notify ESO Test Overlay (Faz 23.9 Step D — ACTIVE)

> **Status**: ACTIVE (Faz 23.9 Step D — Codex thread `019e08df` REVISE absorb 2026-05-08)
> **ADR**: [ADR-0013-notification-orchestration](../../../../docs/adr/0013-notification-orchestration.md)
> **Vault path**: `kv/platform/notification-orchestrator` (flat single-path; matches prod overlay)

Bu dizin Faz 23.1 PR5'te kuruldu, Faz 23.9 Step D'de flat path consolidation
(Codex `019e08df` iter-1 absorb) ile prod manifest'e hizalandı.

## Vault path layout (flat)

`kv/platform/notification-orchestrator`:

| Property | Secret env var | Note |
|---|---|---|
| `db_username` | `SPRING_DATASOURCE_USERNAME` | platform user (paylaşılan) |
| `db_password` | `SPRING_DATASOURCE_PASSWORD` | scram-sha-256 hash |
| `webhook_signing_secret` | `NOTIFY_ADAPTERS_WEBHOOK_SIGNING_SECRET` | HMAC; rotation `*_NEXT` follow-up |
| `authz_internal_api_key` | `NOTIFY_AUTHZ_INTERNAL_API_KEY` | permission-service S2S |
| `redaction_pepper` | `NOTIFY_REDACTION_PEPPER` | HMAC recipient hash |

> **History**: This file was originally split path (kv/platform/notify/{db,
> redaction,webhook,authz,smtp,slack}) — over-engineered for SMTP/Slack
> channels not yet wired. ExternalSecret stayed in `SecretSyncedError` from
> 2026-05-07 to 2026-05-08. Faz 23.9 Step D rewrite consolidates to flat
> single-path matching the 10 working platform service ExternalSecrets.

## Activation Sequence

1. Operator populates Vault test path with 5 keys (one-shot, scripted in
   `docs/runbooks/RB-faz-23-2-notify-vault-paths.md`)
2. ExternalSecret applied: `kubectl --context k3d-test apply -f
   kustomize/overlays/test/eso/notify/externalsecret-notify.yaml`
3. Verify SecretSynced=True + ownerReferences=ExternalSecret

## Pending follow-up (test cluster operator action)

Test Vault path henüz populate edilmedi (this PR scope dışı). Activation
şartı: operator one-shot Vault write — `RB-faz-23-2-notify-vault-paths.md`
adımlarını izle.
