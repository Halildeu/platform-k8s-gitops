# RB-faz24-product-gate-evidence-ingest

## Purpose

This runbook describes the no-mutation GitHub Actions ingest path for Faz 24
product-gate evidence:

- G-CAP capture reliability evidence from
  `scripts/faz24/verify_gcap_capture_gate_evidence.py` using redacted
  external-recorder and/or desktop-capture verifier summaries. External
  recorder summaries must be post-hardening summaries with
  `directClientToStt=false`, `directSttTranscriptProven=false`, and the
  corresponding passed boundary checks; stale pre-hardening summaries are not
  aggregate acceptance evidence.
- G-OPS on-prem operability evidence from
  `scripts/faz24/verify_gops_operability_gate_evidence.py`
- G-COMP compliance readiness evidence from
  `scripts/faz24/verify_gcomp_compliance_gate_evidence.py`. If G-COMP evidence
  includes owner-supplied effective retention values, it must include bounded
  `retentionParameters.ownerDecisionRef`, `appliedAsConfig=true`, and
  `hardcodedInCode=false`; otherwise the unset/default path must remain
  fail-closed.

The workflow is `.github/workflows/faz24-product-gate-evidence-ingest.yml`.
It validates redacted metadata evidence only. It does not run a pilot, mutate
runtime/Kubernetes/Vault/firewall/legal state, store raw meeting data, accept
VERBIS/legal sign-off, enable direct-STT, or make production ready.

## Inputs

Dispatch the workflow with:

- `gate`: one of `gcap`, `gops`, `gcomp`
- `evidence_json_base64`: a single-line base64 representation of the selected
  gate's redacted JSON evidence envelope

For `gcap`, the workflow input is the set of redacted verifier summaries
accepted by `verify_gcap_capture_gate_evidence.py`, commonly as a wrapper such
as `{"reports":[...]}`. Do not submit the aggregate verifier output itself as
the workflow input; the workflow reruns the verifier and uploads its own
summary artifact. For `gops` and `gcomp`, submit the redacted evidence envelope
for the selected gate.

Do not paste secrets, tokens, JWTs, private keys, certificates, raw audio,
raw transcript text, prompts, responses, personal data, cookies, kubeconfig,
Vault material, or legal advice text into the evidence JSON.

## Operator Handoff Package

`scripts/faz24/build-product-gate-operator-handoff.py` and workflow
`.github/workflows/faz24-product-gate-operator-handoff.yml` build a
metadata-only handoff package for the G-CAP/G-OPS/G-COMP sequence. The package
contains `README.md`, `faz24-product-gate-operator-handoff.json`, and
`SHA256SUMS`.

The package is coordination evidence only. It does not collect live evidence,
run a pilot, mutate Kubernetes/Vault/firewall/legal state, ingest evidence,
accept legal/KVKK/VERBIS sign-off, or move `platform-k8s-gitops#1615` beyond
`Needs Verify`.

## Local Encoding

From a trusted local file:

```bash
base64 -i /path/to/redacted-evidence.json | tr -d '\n'
```

If the local `base64` implementation does not support `-i`, use:

```bash
base64 /path/to/redacted-evidence.json | tr -d '\n'
```

## Expected Outputs

The workflow uploads an artifact named:

```text
faz24-product-gate-evidence-<gate>-<run_id>
```

The artifact contains:

- pretty-printed decoded evidence JSON
- verifier stdout/stderr
- `summary.json`

The workflow fails when the selected verifier returns non-zero or when the
artifact scan detects private/secret/raw-sensitive key material. Failed runs
are still useful for diagnosis, but they are not acceptance evidence.

## Acceptance Boundary

A passing ingest run proves only that the submitted redacted metadata envelope
met the selected verifier's source-side schema, threshold, and boundary checks.
It does not prove:

- live G-CAP/G-OPS/G-COMP product acceptance
- direct-STT transcript readiness
- compute-plane audit readiness
- fresh desktop mic/loopback readiness beyond any submitted desktop verifier
  summaries
- direct client-to-STT or direct-STT transcript readiness from external
  recorder summaries
- VERBIS/legal acceptance
- DB cleanup completion
- production readiness

Attach the workflow URL, artifact name, verifier status, and reviewer notes to
the relevant gate issue before moving any gate beyond `Needs Verify`.
