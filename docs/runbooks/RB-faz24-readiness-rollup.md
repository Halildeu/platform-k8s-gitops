# RB - Faz 24 readiness rollup verifier

> **Status**: ACTIVE - source-side verifier and ingest path only.
> **Scope**: platform-k8s-gitops#1615 multi-gate rollup evidence validation.
> **Boundary**: This runbook does not collect runtime evidence, seed secrets,
> mutate Kubernetes/Vault/Caddy/firewall, run desktop capture, enable
> direct-STT, perform legal acceptance, or claim production readiness.

## Context

Faz 24 has several independently verified gate families. A single passing
slice, such as external-recorder G-CAP aggregate evidence, is not enough to
accept the broader #1615 rollup while direct-STT, desktop capture, WG-B+ I3,
full I7, G-OPS, G-COMP, pilot WER/DER, pilot G-INT, G-LAT/COST, retention
lifecycle, or client smoke evidence remains open.

`scripts/faz24/verify_faz24_readiness_rollup.py` validates a redacted
`faz24.readinessRollupEvidence.v1` envelope that references the accepted
verifier artifacts for every required gate. It is a final aggregation guard,
not a replacement for the underlying gate verifiers.

## Required Gates

The envelope must include all gate names below with `status=pass`,
`acceptedByVerifier=true`, bounded `evidenceRef`, `issueRef`, `observedAt`, and
a single-line summary:

- `foundation_deploy`
- `recorder_edge_lifecycle`
- `gcap_aggregate`
- `desktop_capture`
- `direct_stt_preflight`
- `direct_stt_e2e`
- `compute_plane_audit`
- `wg_bplus_i3`
- `wg_bplus_i6`
- `i7_live_stt_app_mtls`
- `i7_full_prod_gate`
- `gops_operability`
- `gcomp_engineering`
- `retention_lifecycle`
- `gwer_der_pilot`
- `gint_pilot`
- `glat_cost_pilot`
- `browser_smoke`

Approved `evidenceRef` schemes are `github://`, `github-actions://`,
`artifact://`, `operator://`, `protected://`, and `runbook://`. Do not attach
raw logs, raw meeting payloads, tokens, certificates, private keys, personal
data, or endpoint command output.

## Command

```bash
python3 scripts/faz24/verify_faz24_readiness_rollup.py \
  --evidence-file /tmp/faz24-readiness-rollup.json \
  --output-file /tmp/faz24-readiness-rollup.verify.json
```

## GitHub Ingest

Use the no-mutation workflow only after all child gates have accepted redacted
verifier evidence:

```bash
base64 -i /tmp/faz24-readiness-rollup.json | tr -d '\n'
```

Then dispatch `Faz 24 Readiness Rollup Evidence Ingest` with the single-line
base64 string.

## Status Semantics

- `pass`: every required gate is present, all gate statuses are `pass`, all
  gates have `acceptedByVerifier=true`, and boundary fields prevent legal,
  runtime, secret, raw-media, and production overclaims.
- `blocked`: at least one gate is missing, still open, malformed, or not
  accepted by its own verifier. Required gates cannot be marked
  `not_applicable`; the value is diagnostic only and still blocks the rollup.
- `fail`: the envelope contains sensitive material, direct personal data,
  forbidden boundary claims, production/legal overclaims, or an incompatible
  schema.
- `error`: JSON cannot be loaded.

## Boundary

The rollup verifier can support #1615 acceptance discipline only after child
evidence exists. It does not prove direct-STT, desktop capture, I3, I7,
G-OPS, G-COMP, pilot quality, legal acceptance, or production readiness by
itself.
