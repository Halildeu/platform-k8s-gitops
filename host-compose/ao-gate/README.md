# `host-compose/ao-gate` — GPP-2 AO Gate Runtime

Operator-owned host-compose for the two AO gate services that the
`ao-kernel` repo publishes:

| Service | Port (loopback) | Image | program_id |
|---|---|---|---|
| Live-adapter Gate Policy | `127.0.0.1:18081` | `ghcr.io/halildeu/ao-kernel-live-adapter-gate-policy-service` | `GPP-2q` |
| AO Release Gate | `127.0.0.1:18082` | `ghcr.io/halildeu/ao-kernel-ao-release-gate-service` | `GPP-2w` |

This file targets the **AO-GATE-1 / AO-GATE-2 / AO-GATE-3** preparation step
of GPP-2. Health-evidence must pass before anything later (live adapter
execution, GitHub webhook config, branch protection, required checks). None
of those are in scope here.

## Pre-flight

1. **GHCR images** — published by ao-kernel CI workflows
   (`policy-container-publish.yml`, `ao-release-gate-container-publish.yml`)
   on every main push. Both `:main` and `:sha-<SHA>` tags exist.
   ```bash
   docker pull ghcr.io/halildeu/ao-kernel-live-adapter-gate-policy-service:main
   docker pull ghcr.io/halildeu/ao-kernel-ao-release-gate-service:main
   ```
   If pull fails with 401/403, the operator needs to log in to GHCR with a
   PAT that carries `read:packages`:
   ```bash
   echo "$GHCR_PULL_PAT" | docker login ghcr.io -u <github-user> --password-stdin
   ```
2. **`platform-prod-net`** — the existing Docker network the prod-side
   `vault-prod` and `keycloak-prod` host-compose stacks attach to. Verify:
   ```bash
   docker network ls | grep platform-prod-net
   ```
3. **Vault** — `host-compose/vault/prod` up; container hostname
   `platform-vault-prod` resolves on the prod network.

## Bring up

```bash
cp .env.example .env
# Fill REQUIRED values (compose fails-fast on empty):
#   VAULT_TOKEN                          (Vault auth, read from operator vault setup)
#   AO_GITHUB_APP_ID                     (numeric GitHub App ID, public-safe)
#   AO_RELEASE_GATE_GPP_STATUS_HOST_PATH (read-only host path to gpp_status.v1.json)
# Optional: pin AO_POLICY_IMAGE_TAG / AO_RELEASE_GATE_IMAGE_TAG to :sha-<SHA> for evidence.
docker compose --env-file .env up -d
docker compose ps
```

### GPP status file

The release-gate runtime requires a JSON status file mounted at
`/app/gpp_status.v1.json`. Operator places the file on the host (suggested
`/srv/platform/stateful/prod/ao-release-gate/gpp_status.v1.json`) and points
`AO_RELEASE_GATE_GPP_STATUS_HOST_PATH` at it; the file is mounted read-only.
Without this mount the `/github/ao-release-gate` callback raises
`ao_release_gate_runtime_gpp_status_unavailable` (Codex `019dfa18` finding 2
absorb). `/healthz` itself does NOT need the file — only the callback path.

## Localhost smoke (acceptance)

```bash
# Both must succeed (exit 0):
curl -fsS http://127.0.0.1:18081/healthz | jq -e '.program_id == "GPP-2q"'
curl -fsS http://127.0.0.1:18082/healthz | jq -e '.program_id == "GPP-2w"'

# Both containers must report healthy:
docker ps --filter "name=ao-gate-" --format 'table {{.Names}}\t{{.Status}}'
```

Expected:
```
NAMES               STATUS
ao-gate-policy      Up 1m (healthy)
ao-gate-release     Up 1m (healthy)
```

If either healthcheck stays in `starting` for more than the `start_period:
30s` window, check Vault reachability — the runtime needs the GitHub App
private key + webhook secrets at boot:
```bash
docker exec ao-gate-policy curl -fsS http://platform-vault-prod:8200/v1/sys/health
```

## Public route

This compose intentionally does **not** bind 80 / 443 / public TLS. The
public `/ao-gate/*` route lives in
`host-compose/web-nginx/default.conf` and is added in the **frontend brief**
follow-up — proxying:

| Public path | Upstream |
|---|---|
| `/ao-gate/policy/healthz` | `http://127.0.0.1:18081/healthz` |
| `/ao-gate/release-gate/healthz` | `http://127.0.0.1:18082/healthz` |
| `/ao-gate/github/deployment-protection` | `http://127.0.0.1:18081/github/deployment-protection` |
| `/ao-gate/github/ao-release-gate` | `http://127.0.0.1:18082/github/ao-release-gate` |

The frontend follow-up MUST set `proxy_intercept_errors off` so an upstream
outage returns a JSON 503 instead of falling through to the SPA's
`error_page 404 /index.html;` and serving HTML.

## Hardening

| Setting | Value | Why |
|---|---|---|
| `user` | `10001:10001` | Non-root; matches the `ao-kernel` UID created by `deploy/live-adapter-gate-policy-service/Dockerfile` (and the parallel release-gate Dockerfile). Codex `019dfa18` finding 4 absorb. |
| `read_only` | `true` | Image filesystem is immutable at runtime. |
| `tmpfs` | `/tmp` | gunicorn + Python need a writable scratch dir. |
| `security_opt` | `no-new-privileges:true` | No setuid escalation paths. |
| `deploy.resources.limits` | 256M / 0.5 CPU | Burst-protection; gates are health-only and tiny. |
| `logging.options.max-size/max-file` | 20m / 5 | Prevents log volumes from growing unbounded. |
| Healthcheck | `program_id` JSON assert | Wrong artefact (release-gate built as policy by mistake) flips to unhealthy. |

## Tag strategy

`:main` is the deploy artefact (auto-follows latest `ao-kernel` main push).
For **GPP-2 evidence** override to `:sha-<SHA>` via `.env`:

```bash
# .env override for evidence pin
AO_POLICY_IMAGE_TAG=sha-abc1234567890abcdef...
AO_RELEASE_GATE_IMAGE_TAG=sha-abc1234567890abcdef...
```

Both tags are produced by the same publish workflow run, so the SHA is
identical for paired services.

## What this stack does NOT do

- Public TLS / 80 / 443 — `host-compose/web-nginx`.
- GitHub App webhook config / branch protection / required checks — operator
  follow-up after evidence passes.
- Live adapter execution — only `/healthz` + `/github/*` callback surface.
- Any kustomize / k8s deploy — host-compose is operator workstation runtime.

## Refs

- Codex 019dd24f post-merge follow-up brief
- ao-kernel `deploy/live-adapter-gate-policy-service/Dockerfile`
- ao-kernel `deploy/ao-release-gate-service/Dockerfile`
- ao-kernel `.github/workflows/policy-container-publish.yml`
- ao-kernel `.github/workflows/ao-release-gate-container-publish.yml`
- gitops `host-compose/vault/prod` (Vault network + hostname pattern)
