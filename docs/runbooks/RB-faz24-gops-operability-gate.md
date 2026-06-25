# RB — Faz 24 G-OPS operability gate verifier

> **Status**: ACTIVE — source-side verifier/runbook package only.
> **Scope**: Faz 24 on-prem/self-host operability evidence validation.
> **Boundary**: This runbook does not execute install, upgrade, backup,
> restore, rollback, secret rotation, cluster mutation, or production
> readiness acceptance. It defines the redacted evidence shape expected before
> a G-OPS claim is attached to an issue.

## Context

Faz 24 is sold as an enterprise meeting-intelligence product where
on-prem/self-host operability is a differentiator. G-OPS evidence must prove
more than a service being up: install, upgrade, backup, restore, rollback,
secret delivery, observability, and runbook repeatability need bounded
metadata evidence.

The verifier rejects credential material, raw audio, transcript text,
prompt/response payloads, and production-readiness overclaims. It should be run
after an operator or CI job creates a redacted
`faz24.gopsOperabilityEvidence.v1` envelope.

## Evidence Shape

The evidence file must be a JSON object with:

- `schemaVersion=faz24.gopsOperabilityEvidence.v1`
- `status=pass`
- `tokenIncluded=false`
- `environment.class` in `lab`, `staging`, `pilot`, `onprem-pilot`, or
  `dr-drill`
- one named check for each required operation:
  `install`, `upgrade`, `backup`, `restore`, `rollback`, `secret_delivery`,
  `observability`, `runbook`
- one bounded `evidenceRef` per check using one of:
  `github://`, `github-actions://`, `artifact://`, `operator://`,
  `protected://`, `runbook://`
- numeric metrics:
  `installDurationMinutes`, `upgradeDurationMinutes`, `backupAgeHours`,
  `restoreRtoMinutes`, `restoreRpoMinutes`, `rollbackRtoMinutes`,
  `secretRotationMinutes`, `observabilityCoverage`
- boundary fields explicitly keeping secret/audio/transcript/live-production
  and production-readiness claims false.

## Command

```bash
python3 scripts/faz24/verify_gops_operability_gate_evidence.py \
  --evidence-file /tmp/faz24-gops-operability-evidence.json \
  --max-install-minutes 120 \
  --max-upgrade-minutes 90 \
  --max-backup-age-hours 24 \
  --max-restore-rto-minutes 240 \
  --max-restore-rpo-minutes 1440 \
  --max-rollback-rto-minutes 60 \
  --max-secret-rotation-minutes 60 \
  --min-observability-coverage 0.90 \
  --output-file /tmp/faz24-gops-operability.verify.json
```

## Status Semantics

- `status=pass`: all required evidence classes are present and all thresholds
  pass.
- `status=blocked`: evidence is missing, skipped, malformed at the evidence
  class level, or too weak to decide.
- `status=fail`: submitted evidence has a privacy/schema/overclaim rejection,
  or enough evidence exists but an RPO/RTO/coverage threshold is missed.
- `status=error`: JSON could not be loaded.

## Attachment Rule

Attach only the redacted evidence JSON and verifier JSON after checking both
have `tokenIncluded=false`. Do not attach raw shell transcripts, kubeconfigs,
Vault output, JWTs, private keys, backup archives, raw audio, transcript text,
or endpoint logs with credentials.

## Boundary

This verifier can support G-OPS source-side acceptance discipline. It does not
prove live production readiness, final on-prem supportability, direct-STT,
compute-plane audit, desktop mic/loopback, or customer pilot success by itself.
