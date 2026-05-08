# Notify ESO Prod Overlay (Faz 23.9 Step D — ACTIVE)

> **Status**: ACTIVE (Faz 23.9 Step D — Codex thread `019e08df` REVISE absorb 2026-05-08)
> **ADR**: [ADR-0013-notification-orchestration](../../../../docs/adr/0013-notification-orchestration.md)
> **Vault path**: `kv/platform/notification-orchestrator` (flat single-path; auth-service/user-service convention)

Bu dizin Faz 23.9 prod cutover'ın **Step D hardening** sonucu — direct kubectl
Secret bootstrap'i ESO/Vault managed Secret'e dönüştürür. ExternalSecret prod
environment için ACTIVE.

## Vault path layout (flat)

`kv/platform/notification-orchestrator`:

| Property | Secret env var | Note |
|---|---|---|
| `db_username` | `SPRING_DATASOURCE_USERNAME` | platform user (paylaşılan; gelecek PR'da notify_user dedicated) |
| `db_password` | `SPRING_DATASOURCE_PASSWORD` | scram-sha-256 hash; rotate via `ALTER USER` + Vault patch |
| `webhook_signing_secret` | `NOTIFY_ADAPTERS_WEBHOOK_SIGNING_SECRET` | HMAC; rotation `*_NEXT` + `ACTIVE_KID` follow-up PR |
| `authz_internal_api_key` | `NOTIFY_AUTHZ_INTERNAL_API_KEY` | permission-service S2S |
| `redaction_pepper` | `NOTIFY_REDACTION_PEPPER` | HMAC recipient hash; rotation breaks lookup, plan migration window |

> **History**: Faz 23.2 PR-D.3 split path `kv/platform/notify/{db,redaction,
> webhook,authz,smtp,slack}` over-engineered for SMTP/Slack channels not yet
> wired. Faz 23.9 Step D consolidates to flat path matching the 10 working
> platform service ExternalSecrets (auth-service, user-service, etc.). Future
> SMTP/Slack additions extend this path with extra properties; rotation
> divergence triggers split if needed.

## Activation Sequence (one-shot, performed 2026-05-08)

1. Operator populated Vault path via root token (one-shot, scripted in
   `docs/runbooks/RB-faz-23-2-notify-vault-paths.md`)
2. ExternalSecret manifest `externalsecret-notify.yaml` created (this dir)
3. `kustomization.yaml` created
4. Reference added to `kustomize/overlays/prod/eso/kustomization.yaml`
5. Vault policy `eso-runtime` extended with
   `kv/data/platform/notification-orchestrator` read
   (`bootstrap/vault-policies/common/eso-runtime.hcl`)
6. ArgoCD platform-eso-prod sync (auto)
7. Verify SecretSynced=True + ownerReferences=ExternalSecret + Secret content
   byte-identical to pre-swap

## Pending follow-ups

- Dedicated `notify_user` PG user (currently shares `platform` superuser-ish
  credentials with auth-service)
- Rotation runbook: webhook `*_NEXT` + `ACTIVE_KID` registry, redaction pepper
  migration window
- 72h observation window — DLQ count = 0, error rate < 0.1%
- Multi-tenant scope: per-org provider credentials (Faz 21)

Detay: `docs/runbooks/RB-faz-23-charter.md` §Faz 23.9 Prod Cutover.
