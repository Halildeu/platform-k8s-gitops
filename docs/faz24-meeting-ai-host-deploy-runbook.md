# RB Faz 24 — meeting-ai GPU host deploy (denetim PC, RTX 4070)

**Owner**: platform-ops (Denetim PC steward)
**Target**: denetim PC (10.99.0.2, WireGuard tunnel from staging-sw); NOT
kubernetes — the K8s `meeting-ai-service` in the test overlay is a
host-bridge Service pointing at this host on port 8300.
**Reversible**: yes — `docker stop` reverts to the previous container.

---

## When to run

- The meeting-ai code has landed on `main` (currently platform-ai#268 +
  #270 for Faz 24 canlı analiz: `/analyze/live` + `/analyze/live/stream`)
  and audio-gateway's İ4 trigger needs a reachable target.
- **NOT before** the k8s bridge Service exists (see
  `kustomize/overlays/test/meeting-ai-service-bridge.yaml`) — the enable
  runbook's Preflight A depends on it.

---

## Prerequisites (all on the denetim PC)

- WireGuard tunnel up to staging-sw (10.99.0.1 ↔ 10.99.0.2).
- Docker + docker compose plugin installed.
- Ollama model already pulled (`llama3.1:8b` today; see
  `services/meeting-ai-service/README.md` for the recorded model tag).
- Vault-issued mTLS material mounted where the compose file expects it
  (see `deploy/gpu-host/configure-meeting-ai.ps1` reference; on Linux
  the same paths are under `/etc/meeting-ai-mtls/`).

If any prerequisite is missing → STOP, escalate to the Denetim PC steward
before pulling a new image.

---

## Build + push (from your workstation)

The GPU host does NOT build; images are pulled from GHCR after a build
on a workstation with GHCR write.

```bash
# 1. Clone the exact main-head commit you intend to ship
cd platform-ai
git fetch origin main --quiet
git checkout <sha>       # the main-head sha you reviewed

# 2. Build + push meeting-ai
docker buildx build \
  --platform linux/amd64 \
  --tag ghcr.io/halildeu/platform-ai-meeting-ai-service:sha-<short> \
  --file services/meeting-ai-service/Dockerfile \
  --push \
  services/meeting-ai-service

# 3. Record the pushed digest (paste into the runbook log — this is
#    what the GPU host will pull).
docker buildx imagetools inspect \
  ghcr.io/halildeu/platform-ai-meeting-ai-service:sha-<short> \
  | grep -i 'digest:'
```

---

## Pull + start on the GPU host

Denetim PC has NO outbound egress by default — WireGuard is only the
inbound tunnel from staging-sw. To pull from GHCR the steward opens a
brief GHCR-only allow window (owner-touch). Do not tell the runbook
reader to shell in a curl bearer for you.

```bash
# On the GPU host (via reverse-SSH tunnel from staging-sw:22024):
IMG=ghcr.io/halildeu/platform-ai-meeting-ai-service@sha256:<digest>

# 1. Pull (owner opens the GHCR allow window; run this inside that window)
docker login ghcr.io   # PAT from Vault, owner-supplied at pull time
docker pull "$IMG"

# 2. Stop the previous container gracefully
docker ps --filter name=meeting-ai --format '{{.ID}}' | xargs -r docker stop -t 15

# 3. Start with the compose profile that already carries the mTLS + Ollama
#    wiring (`configure-meeting-ai.ps1` is the authoritative source for the
#    env matrix; the compose file below re-uses those variables so no
#    per-deploy env editing is needed).
cd /opt/meeting-ai
IMAGE_REF="$IMG" docker compose up -d meeting-ai
```

---

## Verify

```bash
# On the GPU host
docker logs --tail 40 meeting-ai
# → look for the "meeting-ai-service starting" line with version + backend;
#   no stack traces, no port bind errors.

# On staging-sw (via WG tunnel)
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' -m 5 \
     http://10.99.0.2:8300/health
# → HTTP 200

# From inside the k3d-test cluster (the bridge Service, the way
# audio-gateway will see it once İ4 is enabled)
kubectl --context k3d-test -n platform-test run mai-verify --rm -it \
  --image=curlimages/curl:8.4.0 --restart=Never -- \
  -sS -o /dev/null -w 'HTTP %{http_code}\n' -m 5 \
      http://meeting-ai-service:8080/health
# → HTTP 200 (the bridge routes 8080 → 10.99.0.2:8300)

# Live analysis + SSE end-to-end (the İ5 smoke script does all of this;
# run it against the bridge URL because that is what İ4 will use):
MEETING_AI_URL=http://meeting-ai-service:8080 \
  scripts/faz24/live-analyze-sse-smoke.sh
# → PASS: SSE delivered an event: analysis frame with is_partial=true
```

If any of the three health checks fails, roll back (below) and
investigate the container logs on the host.

---

## Rollback

```bash
# On the GPU host — the previous image ref is still in `docker images`
# for at least the current session (Docker's LRU eviction is manual).
docker ps --filter name=meeting-ai --format '{{.ID}}' | xargs -r docker stop -t 15
PREV_IMG=$(docker images --format '{{.Repository}}@{{.Digest}}' \
             ghcr.io/halildeu/platform-ai-meeting-ai-service | \
           awk 'NR==2 { print }')
IMAGE_REF="$PREV_IMG" docker compose up -d meeting-ai
```

If audio-gateway's live-analyze was enabled against the failed image,
follow the İ4 runbook's rollback (flip `ENABLED=false`) — DO NOT leave
the trigger firing against a rolled-back meeting-ai.

---

## Known-good today (2026-07-21)

- meeting-ai code: platform-ai `main` head after PR #270 (SSE relay hub).
- Ollama backend model: `llama3.1:8b` (recorded in
  `services/meeting-ai-service/app/core/config.py` as
  `ollama_model` default).
- Redaction policy: KVKK PII fail-closed (ADR-0043 D3); do NOT enable
  a real LLM backend without the redactor active.
- Bridge Service target port: `8300` (denetim PC container listens
  on `0.0.0.0:8300`).
- k3d bridge Service port: `8080` (published in
  `kustomize/overlays/test/meeting-ai-service-bridge.yaml`).

Ref: platform-ai#268 (analyze/live scaffold), platform-ai#270 (SSE relay),
     kustomize/overlays/test/meeting-ai-service-bridge.yaml,
     docs/faz24-i4-live-analyze-enable-runbook.md.
