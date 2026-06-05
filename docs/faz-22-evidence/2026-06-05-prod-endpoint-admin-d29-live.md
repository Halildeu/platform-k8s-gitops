# Faz 22 — Prod Endpoint Admin D29 Live Evidence (2026-06-05)

## Scope

This evidence records prod workload presence and D29 smoke for `endpoint-admin-service` after #1241 and #1242. It does not claim D30 atomic cutover, decommission, domain-wide rollout, or sensitive/file-action readiness.

## Merge Chain

| PR | Scope | Merge commit | Result |
|---|---|---|---|
| #1241 | prod ExternalSecret for endpoint-admin-service | `e268854c63ed29b91818d378041f812a814d26d6` | MERGED |
| #1242 | prod workload/config + D29 ledgered digest | `4202e17c1d0d3f7d72ec7943601fd453bba0bde3` | MERGED |

## Secret Delivery

- `ExternalSecret/platform-prod/endpoint-admin-service-secrets`: `Ready=True:SecretSynced`
- Kubernetes Secret `endpoint-admin-service-secrets`: 4 keys present
- Vault path `kv/platform/endpoint-admin-service` was populated with required keys; only key names, lengths, and hash prefix were recorded. Secret values were not printed.

## DB Auth

- Prod PG database/role: `endpoint_admin`
- Restricted temp pod using `app.kubernetes.io/part-of=platform`, password sourced from the Kubernetes Secret, connected through pod-network and returned `endpoint_admin@endpoint_admin`.
- A first temp pod without the `part-of=platform` label was blocked by prod egress policy, confirming NetworkPolicy behavior.

## Runtime

- Deployment: `endpoint-admin-service`, ready `1/1`
- Pod: `endpoint-admin-service-777c66f5c9-wl5kr`, Running/Ready
- ImageID: `ghcr.io/halildeu/platform-backend-endpoint-admin-service@sha256:7fa5975c1d0c54e3611db5d89d7b8f8919c1952f6b74f94e562ffd1d90a0f9d2`
- Boot logs: Hikari connection added; Flyway applied 49 migrations to `endpoint_admin_service` now at `v50`; OpenFGA client created; Tomcat started on 8096 and 8081; application started.

## D29 Prod Smoke

Command:

```bash
ssh staging-sw 'bash -s -- prod' < scripts/smoke/d29-smoke-runner.sh
```

Report: `/tmp/smoke-report-prod-20260605T195032Z.json`

| Tier | Status | Evidence |
|---|---|---|
| Up | GREEN | all 10 services Running+Ready |
| Functional | GREEN | all 10 endpoints returned 200/401/403 with auth chain intact |
| Secured | GREEN | all 10 services have correct Keycloak issuer for prod |
| Zanzibar | GREEN | synthetic allow/deny PASS: `user:1204` allow, `user:9999999` deny |

## Residual Gates

- D30 atomic cutover and broad exposure are separate gates.
- `platform-prod` ArgoCD app remains overall OutOfSync due unrelated pre-existing `r29-teams-smoke` resources; endpoint-admin resources are Synced/Healthy.
- AG-029 signed self-update, controlled rollout policies, IT/domain-wide rollout, and sensitive/file-action charter remain open roadmap items.
