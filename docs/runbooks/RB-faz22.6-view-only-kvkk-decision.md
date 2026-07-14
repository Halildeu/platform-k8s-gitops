# RB — Faz 22.6 VIEW_ONLY KVKK signed decision

## 1. Scope and authority

This runbook prepares and verifies the legal/DPO decision owned by issue #2374.
It does not choose a legal basis, approve retention, impersonate an owner/DPO,
activate the viewer, or claim production readiness. The bounded scope is fixed:

- environment `test`;
- mode `attended-view-only`;
- recording `disabled`, screen content is not persisted;
- one consenting pilot device and one-person operator roster;
- product viewer acceptance is separately owned by #2373.

The decision record is protected personal/compliance evidence. Keep it in
access-controlled evidence storage. The public-key-only approver policy is a
reviewed repo trust root at
`config/faz22-6-view-only-kvkk-approver-policy.v1.json`; it contains opaque key
and principal IDs, never private keys or human names. `identityDirectoryRef`
maps those opaque principals to named people in a protected organizational
directory. Do not post the decision record, private keys, pilot identifiers or
consent proof in an issue, chat, Mavis message, shell argument or repository.
The issue body receives only the verifier-generated, detached-signature marker.

## 2. Why two signatures are mandatory

Free-text names are not approval evidence. The verifier requires two different
human principals with different roles:

1. `privacy-owner`
2. `legal-or-dpo`

Neither principal may be listed in `engineeringPrincipalIds`. Each signature is
Ed25519 over a domain-separated message that includes the canonical decision
payload digest, principal, role, signing time, and decision status. Public keys
and validity windows come from the separately reviewed approver policy. Private
keys remain under the human signers' custody.

## 3. Prepare the records

Start from these intentionally invalid templates:

- `docs/templates/faz22-6-view-only-kvkk-decision-v1.template.json`
- `docs/templates/faz22-6-view-only-kvkk-approver-policy-v1.template.json`

Human owner/legal inputs must replace every `__REQUIRED_*` value. Retention
values are single effective decisions, not application defaults. The legal
record must enumerate the actual purpose/basis, data categories, special-data
handling, notice/consent/withdrawal, processors/transfers, rights and incident
paths. `reviewExpiresAt` must be after approval, unexpired, and no more than 366
days after approval. Scope or governance changes require a new record and hash.
The decision scope binds all three authorities explicitly: engineering `#1580`,
viewer-product acceptance `#2373`, and legal tracking `#2374`. It also binds the
protected `#2373` viewer-product evidence digest/reference so legal approval
cannot silently refer to a different pilot evidence package.

Create the canonical public-key policy from its template through a reviewed PR.
Until that exact file exists on `main`, `GATE_VIEW_ONLY_KVKK` cannot clear. The
policy is safe to review because it contains only public keys, opaque IDs,
validity windows and the protected identity-directory reference.
The policy PR must be reviewed by a governance/security maintainer who is not
one of the two approvers being enrolled and is not the engineering change owner.
Key rotation or compromise requires a new reviewed policy digest and two new
decision signatures. Retired keys are removed at the next policy PR, not merely
left indefinitely with an elapsed `validUntil`.

## 4. Generate signing requests

The decision must contain the two intended principal IDs, roles and signing
timestamps. Signature fields may still contain placeholders in this preparation
step; the tool replaces only those fields with a non-approving dummy value while
validating the rest of the record.

```bash
python3 scripts/faz22-remote-ops/verify-view-only-kvkk-decision.py \
  --input /protected/path/view-only-kvkk-decision.json \
  --approver-policy /protected/path/view-only-kvkk-approver-policy.json \
  --signing-requests-out /protected/path/view-only-kvkk-signing-requests.json
```

Each `requests` value is Base64-encoded exact message bytes. Deliver each request
through the organization's authenticated signing channel to the matching human.
The signer Base64-decodes the request, reviews the underlying human-readable
decision, signs the exact bytes with their authorized Ed25519 key, and returns
only the detached Base64 signature through the controlled channel. Never ask an
AI agent to sign or handle a private key.

The signed message binds three independent digests: the legal decision payload,
the signature-elided canonical record projection (approval identities, roles,
algorithms and times included), and the canonical approver policy. Removing the
signature bytes from the record projection avoids a circular hash while still
making any marker digest/ref or policy substitution invalidate both signatures.

Insert the returned signatures into the matching `signatureBase64` fields. Set
`lifecycle.approvedAt` to the later of the two `signedAt` timestamps. Any payload
change after signing invalidates both signatures and requires re-signing.
Canonical payload bytes use sorted compact UTF-8 JSON in the RFC 8785/JCS
domain constrained by this schema (fixed ASCII keys, integers only); tests
cross-check the digest against independent `jq -cS` serialization.

## 5. Verify and generate the only publishable marker

```bash
python3 scripts/faz22-remote-ops/verify-view-only-kvkk-decision.py \
  --input /protected/path/view-only-kvkk-decision.json \
  --approver-policy /protected/path/view-only-kvkk-approver-policy.json \
  --result-out /protected/path/view-only-kvkk-verifier-result.json \
  --marker-out /protected/path/view-only-kvkk-marker.txt
```

Required result:

```text
status=pass
humanSignatureCount=2
recordContainsRawScreenOrSecret=false
```

The marker exposes no pilot/operator/device reference, human name or storage
location. It contains SHA-256 values and matching content-addressed URNs for the
decision record and reviewed approver policy, plus opaque key IDs, timestamps
and detached signatures. Store the canonical signed decision object under its
URN in the controlled evidence system before publishing the marker. The
evidence store must enforce encryption, access logging, KMS custody,
write-protection/object-lock-equivalent, parameterized retention and a
human-readable export path for rights/audit requests.

Publish exactly one generated `F22_6_VIEW_ONLY_KVKK: v1` block to issue #2374.
Do not hand-edit it. The audit recomputes the canonical policy digest and
verifies both Ed25519 signatures from the marker; free-text paste alone cannot
clear the gate. Python `cryptography` is preferred and OpenSSL 3 is the package-
free verification fallback. Then run the completion audit and require:

```text
GATE_VIEW_ONLY_KVKK=cleared
```

`F22_6_COMPLETION=pass` remains the separate narrow engineering result. KVKK
clearance does not claim viewer delivery, fanout, recording-enabled, production,
5/50/800-device, or broad-rollout readiness.

## 6. Withdrawal, expiry and reissue

- An expired record reports `expired`; it cannot remain cleared.
- A dual-signed record with `status=withdrawn` generates a visible `withdrawn`
  marker state, which the audit treats as tracked pending rather than cleared.
- Purpose/basis, recording mode, data category, controller/processor/transfer,
  retention, incident, product-scope or regulatory-guidance change requires a
  new decision payload, two new signatures, a new digest and a new marker.
- Replace the existing marker atomically; duplicate markers remain pending and
  a forbidden field remains an allowlist violation.
