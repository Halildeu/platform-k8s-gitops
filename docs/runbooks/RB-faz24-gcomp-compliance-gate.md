# RB — Faz 24 G-COMP compliance gate verifier

> **Status**: ACTIVE — source-side verifier/runbook package only.
> **Scope**: Faz 24 compliance-product readiness evidence validation.
> **Boundary**: This runbook does not provide legal advice, does not record
> VERBIS acceptance, does not execute DB cleanup, does not mutate runtime, and
> does not accept raw audio/transcript/prompt/response or personal data.

## Context

Faz 24 is positioned for regulated and data-sensitive enterprise segments.
G-COMP evidence must prove more than a policy document exists: consent,
retention, legal-hold, access-audit, deletion/export, KVKK/VERBIS, redaction,
and operator runbook evidence need a bounded metadata envelope before a
compliance-readiness claim can be attached to an issue.

The verifier rejects credential material, personal data, raw audio,
transcript text, prompt/response payloads, legal-advice overclaims,
live-production mutations, and production-readiness claims. It should be run
after an operator, CI job, or legal/compliance owner creates a redacted
`faz24.gcompComplianceEvidence.v1` envelope.

## Evidence Shape

The evidence file must be a JSON object with:

- `schemaVersion=faz24.gcompComplianceEvidence.v1`
- `status=pass`
- `tokenIncluded=false`
- `environment.class` in `lab`, `staging`, `pilot`, `onprem-pilot`,
  `legal-review`, or `compliance-drill`
- one named check for each required evidence class:
  `consent`, `retention`, `legal_hold`, `access_audit`,
  `deletion_export`, `kvkk_verbis`, `redaction`, `runbook`
- one bounded `evidenceRef` per check using one of:
  `github://`, `github-actions://`, `artifact://`, `operator://`,
  `protected://`, `runbook://`, `legal://`, `dpo://`
- numeric metrics:
  `consentCoverage`, `retentionPolicyCoverage`, `accessAuditCoverage`,
  `deletionExportCoverage`, `redactionCoverage`,
  `dataSubjectResponseDays`, `legalHoldDrillAgeDays`,
  `dbCleanupEvidenceAgeDays`
- boundary fields explicitly keeping secret, raw payload, personal data,
  legal-advice, live-production, and production-readiness claims false.

## Command

```bash
python3 scripts/faz24/verify_gcomp_compliance_gate_evidence.py \
  --evidence-file /tmp/faz24-gcomp-compliance-evidence.json \
  --min-consent-coverage 1.0 \
  --min-retention-policy-coverage 1.0 \
  --min-access-audit-coverage 0.95 \
  --min-deletion-export-coverage 1.0 \
  --min-redaction-coverage 1.0 \
  --max-data-subject-response-days 30 \
  --max-legal-hold-drill-age-days 90 \
  --max-db-cleanup-evidence-age-days 30 \
  --output-file /tmp/faz24-gcomp-compliance.verify.json
```

## Status Semantics

- `status=pass`: all required evidence classes are present and all thresholds
  pass.
- `status=blocked`: evidence is missing, skipped, malformed at the evidence
  class level, or too weak to decide.
- `status=fail`: submitted evidence has a privacy/schema/overclaim rejection,
  or enough evidence exists but a coverage/response-age threshold is missed.
- `status=error`: JSON could not be loaded.

## Attachment Rule

Attach only the redacted evidence JSON and verifier JSON after checking both
have `tokenIncluded=false`. Do not attach raw shell transcripts, JWTs, private
keys, kubeconfigs, Vault output, raw audio, transcript text, prompt/response
payloads, named participant data, direct email/phone identifiers, or DB export
rows containing personal data.

## Boundary

This verifier can support G-COMP source-side acceptance discipline. It does
not prove final legal acceptance, does not replace DPO/operator review, does
not satisfy VERBIS or exemption evidence by itself, does not perform erasure or
DB cleanup, and does not make Faz 24 production-ready.
