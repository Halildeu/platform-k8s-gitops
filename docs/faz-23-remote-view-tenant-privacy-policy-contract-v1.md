# Faz 23 Remote VIEW_ONLY Tenant Privacy Policy Contract v1

> **Status:** Proposed implementation contract (`#2451`). This document does not
> reopen Faz 22.6 and does not claim legal clearance for any tenant.
>
> **Scope:** Product-level, tenant-configurable privacy and legal-policy source,
> platform safety floor, and same-session runtime decision envelope.

## 1. Decision boundary

The VIEW_ONLY product is not tied to one company's KVKK interpretation. Every
tenant may configure its own notice, legal references, retention, residency,
recording and sensitive-data response. Tenant configuration cannot weaken the
platform's transport and human-safety invariants.

Three artifacts deliberately have different owners and lifecycles:

1. `remote-view-platform-safety-baseline-v1` is the product safety floor. A
   tenant cannot override it.
2. `remote-view-tenant-privacy-policy-v1` is the tenant-owned policy source.
   Its `policy` block is operational configuration; `legalEvidence` is a
   content-addressed decision reference and lifecycle record. Legal evidence is
   not executable authorization by itself.
3. `remote-view-session-policy-envelope-v1` is the backend-resolved,
   same-session, Ed25519-signed runtime projection consumed by web and agent.
   Source policy files are never consumed directly by an endpoint.

The existing Faz 22.6 `#2374` record remains an Acik-specific legal tracking
instance. It is not the global schema and its `tracked_pending` state does not
change the already-passing `F22_6_COMPLETION` engineering gate.

## 2. Non-overridable safety floor

The canonical baseline is
`config/remote-view-platform-safety-baseline.v1.json`. It requires:

- attended `VIEW_ONLY` only;
- no auto-consent;
- no keyboard, mouse, clipboard, file transfer or tunnel authority;
- a visible endpoint indicator and local abort;
- bounded session TTL and viewer count;
- an envelope lifetime no longer than the platform session TTL;
- deny on absent, malformed, stale or unsupported policy;
- verify masking before frame emission and deny on mask failure, partial masking
  or timeout;
- a signed envelope bound to the same tenant, device and session.

Tenant files do not contain these fields. This is intentional: omission avoids
an ambiguous merge where a tenant could appear to override a hard invariant.
The resolver injects the invariant block from the digest-pinned baseline into
every session envelope.

## 3. Tenant-configurable surface

The tenant policy may configure:

- session TTL and viewer count within platform maxima;
- localized notice and session authorization text, labels and version;
- recording mode and separate screen-content, session-metadata and audit
  retention;
- controller/processor metadata, storage regions and cross-border decision;
- sensitive-category behavior within the platform floor: detector failure denies,
  and a selected mask action may continue only after verified masking;
- privacy, data-subject-rights and incident contact references;
- processing purpose, tenant-selected legal basis/reference and legal decision
  lifecycle.

The product does not choose a legal basis for the tenant. `legalBasisCode` and
the referenced decision are tenant-owner inputs; the code is an opaque tenant
identifier and the platform does not interpret it as legal advice. Production requires
`legalEvidence.status=approved`; a bounded test may remain `tracked-pending`
while engineering controls are evaluated.

A `bounded-test` policy is deliberately narrower than production: exactly one
viewer, recording disabled, zero screen-content retention and cross-border
transfer denied. `tracked-pending` legal evidence is valid only in that bounded
class. Withdrawn or expired evidence denies every deployment class.

## 4. Resolution and precedence

Resolution is deterministic and fail-closed:

1. Validate the platform baseline against its strict schema.
2. Validate the tenant source against its strict schema.
3. Recompute canonical baseline SHA-256 and require exact `baselineDigest`.
4. Reject expired baseline, tenant policy or legal review window.
5. Reject values above platform maxima or contradictory mode/retention and
   residency/transfer combinations.
6. Select the requested locale. If it is absent, use `defaultLocale`; if that
   localization is absent or its text digest differs, deny.
7. Resolve hard invariants from the baseline and tenant-selectable values from
   the policy. No generic recursive object merge is permitted.
8. Create and sign a new same-session envelope. Cache reuse across session IDs,
   tenant IDs or device IDs is prohibited.

The initial verifier implements steps 1-5 and the source-validation portion of
step 6. Request-time locale selection and fallback remain resolver behavior:

```bash
python3 scripts/faz23/verify-remote-view-policy.py \
  --baseline config/remote-view-platform-safety-baseline.v1.json \
  --policy examples/remote-view/example-tr-domestic-tenant-policy.v1.json
```

## 5. Canonicalization and digest rules

All digest-bearing v1 artifacts use RFC 8785 JCS semantics. The current schemas
allow only strings, booleans, nulls, arrays, objects and bounded integers, so
the repository verifier's UTF-8, sorted-key, compact JSON serialization is the
JCS-compatible projection for this domain. Floats and non-finite values are not
allowed.

Localization `contentDigest` is calculated over the localization object after
removing only `contentDigest`. The tenant `policyDigest`, baseline digest and
legal-evidence digest are calculated over their complete canonical source
objects; none is a caller-authored trust claim.

The baseline digest covers the complete committed baseline artifact, including
its lifecycle. Extending `reviewBy` therefore changes the digest and requires
all tenant baseline bindings to be reviewed and updated; lifecycle is not an
unsigned metadata escape hatch. The verifier independently recomputes this
digest in CI and rejects a stale literal binding.

## 6. Runtime signed envelope

The backend must resolve a fresh envelope after authenticated tenant and device
resolution. The Ed25519 signature covers the JCS canonical object after removing
only `integrity.payloadDigest` and `integrity.signatureBase64`. Consequently the
signature binds at least:

- `sessionId`, `tenantId`, `deviceId`, nonce, `issuedAt`, `expiresAt`;
- deployment class and explicit envelope TTL;
- policy and baseline IDs, versions, source-policy URN and recomputed digests;
- legal-evidence status and recomputed digest;
- hard capability/consent/indicator/abort and mask-before-emission invariants;
- selected notice text and content digest;
- recording, retention, transfer and sensitive-data behavior; selected storage
  regions and transfer mode are explicit, while complete source residency details
  remain transitively bound through the signed `policyDigest`;
- signing `keyId` and signature algorithm.

Before signing, the resolver must recompute `baselineDigest`, `policyDigest` and
`legalEvidenceDigest` from their canonical source objects. The
`session.tenantId` must equal the source policy tenant, and `sourcePolicyRef`
must equal `urn:remote-view-tenant-policy:sha256:<policyDigest>`. The resolved
notice locale must exist in the source policy and its envelope `contentDigest`
must equal that localization's recomputed digest.

The payload digest is SHA-256 of that same projection. `expiresAt` must be later
than `issuedAt`; their exact difference must equal `session.ttlSeconds`, which
must not exceed both baseline `maxEnvelopeLifetimeSeconds` and the resolved
session TTL. The envelope schema's broad structural TTL ceiling is not an
authorization ceiling; the runtime resolver must clamp it to those active
baseline and policy limits. Envelope IDs and nonces are single-use per session. An unknown/revoked key,
signature failure, digest mismatch, tenant/device/session mismatch, stale
`issuedAt`, or expired envelope is a typed deny. A server-private HMAC is not
used because web and endpoint agent could not independently verify it.

The key registry, rotation overlap, revocation distribution and maximum envelope
age are backend implementation responsibilities. Rotation must support an
explicit overlap window; unknown and revoked key IDs deny.

## 7. Consumer behavior

### Backend

- Own policy storage, resolver, canonical digest, key registry and envelope
  signing.
- Derive tenant from authenticated identity, never request body.
- Bind the envelope digest into the remote-session/permit audit chain.
- Emit typed reasons including `POLICY_UNAVAILABLE`, `POLICY_INVALID`,
  `POLICY_STALE`, `POLICY_EXPIRED`, `POLICY_REVOKED`,
  `POLICY_SESSION_MISMATCH` and `NOTICE_DIGEST_MISMATCH`.

### Web

- Never infer `recording=false` or `attended=true` when metadata is absent.
- Verify/consume the exact server decision envelope and render a non-dismissible
  deny state on missing, malformed, mismatched or expired policy metadata.
- Render recording state, active indicator and local stop from authoritative
  values; no input/control transport is introduced.

### Endpoint agent

- Verify the signed envelope with a pinned/rotatable trusted key registry before
  showing consent or sending frames.
- Render only the selected, digest-verified notice text. The current hardcoded
  English consent text is not a valid fallback after v1 policy mode is enabled.
- Complete and verify masking before emitting a frame. A mask execution failure,
  partial mask or timeout denies the session; it cannot silently continue.
- Recheck expiry and local indicator/abort health throughout the session.

## 8. Repository ownership

This GitOps issue owns schemas, safety baseline, example policy, verifier, CI and
deployment wiring. Runtime source changes remain in canonical repositories:

- `platform-backend`: resolver, signing, session binding, audit and revocation;
- `platform-web`: fail-closed metadata and operator policy surfaces;
- `platform-agent`: Go envelope verification, localized consent and runtime
  enforcement.

Each runtime repository gets a linked child issue. A GitOps PR cannot claim
runtime completion or product acceptance without those repository-owned changes
and live evidence.

## 9. Explicit non-goals for v1 source contract

- legal advice or automated lawful-basis selection;
- legal clearance for Acik or another tenant;
- full frame-level DLP implementation beyond the signed fail-closed mask-ordering
  and mask-failure invariants;
- reseller/multiple-controller resolution;
- air-gapped policy distribution;
- production activation.

The example tenant UUID is a reserved test sentinel and must not be copied to a
production tenant. Example policy digests are verifier outputs, not fields added
to source policy JSON; downstream resolvers recompute them at load time.

These are separate product decisions or implementation children. Detector failure
means the product cannot determine whether sensitive content exists; mask execution
failure means detected content could not be safely redacted. Both deny under the
platform floor, while the v1 source contract leaves the frame-level implementation
to the agent child and prevents unsafe implicit defaults.
