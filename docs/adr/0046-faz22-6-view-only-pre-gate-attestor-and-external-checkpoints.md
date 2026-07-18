# ADR-0046 - Faz 22.6 VIEW_ONLY pre-gate attestor and external checkpoints

> **Status:** PROPOSED, fail-closed. The contract is source-defined; the
> GitHub OIDC claim canaries, attestor key, trust pin, backend endpoints and
> TEST runtime are not active.
> **Date:** 2026-07-18
> **Owner issue:** [#2644](https://github.com/Halildeu/platform-k8s-gitops/issues/2644)
> **Authority integration:** [#2502](https://github.com/Halildeu/platform-k8s-gitops/issues/2502)
> **Customer slice:** [#2373](https://github.com/Halildeu/platform-k8s-gitops/issues/2373)

## Context

The current transaction performs source-only checks on a GitHub-hosted runner
and sets `liveChecksDeferredToProtectedJob=true`. Target identity, product auth,
browser, cluster, image and rollback checks first run after the protected
Environment decision. The legacy auth-route helper also obtains a Keycloak
admin token and mutates a persona before claiming a no-side-effect result.

That shape does not satisfy #2644. A failing target or browser route must stop
before an approval prompt and with zero product, Keycloak or cluster mutation.
Moving kubeconfig, SSH or Keycloak admin credentials into an unprotected job is
also forbidden.

## Decision

Use a fixed-function TEST attestor over public HTTPS and a durable signed
checkpoint service. Four non-interchangeable GitHub OIDC profiles authorize
only their matching endpoint:

| Profile | Runner | Subject | Audience | Capability |
|---|---|---|---|---|
| `binding` | GitHub-hosted | `repo:Halildeu/platform-k8s-gitops:ref:<registry.intentRef>` | `faz22-view-only-binding` | fetch one coordinator-signed binding for one accepted dispatch |
| `preflight` | GitHub-hosted | `repo:Halildeu/platform-k8s-gitops:ref:<binding.intentRef>` | `faz22-view-only-preflight` | one fixed read-only preflight |
| `authorization` | GitHub-hosted, protected job | `repo:Halildeu/platform-k8s-gitops:environment:faz22-view-only-pilot` | `faz22-view-only-checkpoint-lease` | redeem one signed authority into one lease |
| `executor` | self-hosted | `repo:Halildeu/platform-k8s-gitops:ref:<binding.intentRef>` | `faz22-view-only-checkpoint` | read/write the lease-bound checkpoint chain |

The normative authority file is
`config/faz22-6-view-only-live-preflight-authority.v1.json`. Until its
`activation.state` is `active`, all blocker strings are removed by evidence,
and both Transit signing fields are non-null, every consumer rejects the lane.

### OIDC claims and permissions

The repository currently uses GitHub's default subject template. A normal,
non-reusable `workflow_dispatch` token is required. Therefore
`job_workflow_ref`, `job_workflow_sha`, `environment`, `head_ref` and
`base_ref` are not represented by empty strings: each profile explicitly lists
which of these claims must be absent. `environment` is required only on the
protected authorization profile. `job_workflow_ref` is never required because
this workflow is not reusable.

Every profile validates RS256/JWKS, issuer, audience, subject, repository ID,
repository, event, ref, workflow ref, runner environment, `sha`, `run_id`,
`run_attempt`, `jti`, `iat`, `nbf` and `exp`. Token lifetime is at most 300
seconds. `run_attempt` is exactly one. The SHA, run and attempt must equal the
request binding. `ref` equals `binding.intentRef`, and `workflow_ref` equals
the canonical workflow path suffixed by `@<binding.intentRef>`. The preflight
and executor `sub` values are derived from the same immutable intent tag; only
the authorization `sub` uses the protected Environment. The raw JWT and JTI
are never persisted; only a domain-bound
JTI SHA-256 may appear in a receipt.

This follows the live #2502 source contract:
`scripts/github_apps/cross_ai_deployment_policy/dispatcher.py` creates and
dispatches the transaction, while
`scripts/github_apps/cross_ai_deployment_policy/github.py` creates
`refs/tags/cross-ai-intent/<requestId>` and dispatches the workflow with
`ref=cross-ai-intent/<requestId>`. A `main` claim pin would reject every valid
v3 dispatch and is forbidden.

The workflow root permission set becomes empty. OIDC and GitHub read access are
granted per job only. The preflight job has no Environment. The authorization
job is the only job with `faz22-view-only-pilot`; it has no Kubernetes, SSH,
Keycloak admin, Vault signing or endpoint credential. The executor has no
Environment and can operate only with the signed lease from the authorization
job. A GitHub OIDC token is an ephemeral credential; "credential-free" in this
ADR means no long-lived secret and no target/runtime mutation credential, not
the absence of that short-lived identity proof.

The current v2 self-hosted/environment-bound bootstrap profile is not reused.
Before activation, redacted canaries must prove the actual claim set for all
four profiles. A missing required claim or a present forbidden claim fails
closed; there is no empty-string compatibility mode.

## Canonical binding and digests

`schema/faz22-6-view-only-transaction-binding-v1.schema.json` is the exact
binding shared by the request, preflight receipt, authority bundle, lease and
every checkpoint receipt. It carries the intent tag and bundle digest as
separate values. `intentRef` is a
`refs/tags/cross-ai-intent/<uuid>` reference; it is never a digest.
`intentBundleSha256` is the signed #2502 bundle envelope digest.
`transactionSessionSha256` is the #2502 machine-authority transaction session,
not the later product remote-session ID.

The binding explicitly carries repository/environment, head and workflow
identity, workflow/dependency/concurrency/authority digests, run/attempt,
endpoint/operator/hostname hashes, consent/owner/mask policies, image digest,
pilot duration, transaction scope and runner policy/admission lease. No
`transactionScopeSha256` proxy may replace these fields.

The coordinator derives the binding from verified sources, never from caller
workflow inputs. The exact mapping is:

| Binding field | Verified source |
|---|---|
| `intentBundleSha256` | verified v3 outer DSSE envelope digest |
| `transactionSessionSha256` | `bundle.subject.sessionSha256` |
| `workflowPath`, `workflowBlobSha256`, `dependencyLockSha256` | `bundle.stages[transaction]` exact fields |
| `workflowRef` | `<repository>/<workflowPath>@<intentRef>` |
| `concurrencySha256` | `bundle.stages[transaction].concurrencyGroupSha256` |
| `authoritySetSha256` | `sha256_digest({domain:"acik.cross-ai-transaction-authority-set.v1",files:sort(stage.authorityFiles,path)})` |
| `triggeringActorId` | `bundle.grant.triggeringActorId` |
| `machineAuthorityPolicySha256` | `bundle.subject.policySha256` |
| artifact, rollback, verifier, bootstrap, endpoint, operator, device, consent, owner, mask, image, pilot, scope, runner and admission fields | same-name `bundle.subject` field |
| `tenantIdSha256`, `preflightPersonaIdentitySha256` | exact-head preflight authority file whose path and SHA are themselves in `stage.authorityFiles` |
| run, attempt, head, immutable intent-ref object and live actor fields | finalized registry plus exact accepted-dispatch/live GitHub run truth |

`authoritySetSha256` and the v3 `transactionScopeSha256` use the same sorted
authority-file projection and must be equal. The binding endpoint re-fetches
every authority file at `headSha`, verifies its blob hash against the signed
`stage.authorityFiles` entry, and only then reads tenant/persona pins. A missing,
renamed or tampered authority file is rejected before signing. Normative
equalities also require request ID = intent tag UUID suffix = grant request ID;
OIDC `actor_id` = grant triggering actor ID = accepted dispatch actor ID = live
run `triggering_actor.id`; and intent-ref object ID/head = finalized registry
object ID/head.

All JSON hashing uses RFC 8785 JCS UTF-8 bytes and a lowercase SHA-256 rendered
as `sha256:<64 lowercase hex>`. The four domain strings and exact inputs are in
the authority file:

- request digest: validated request body;
- binding digest: exact binding object;
- transaction ID: exact binding object under a separate domain;
- stored-object digest: validated checkpoint create request excluding the
  repeated lease envelope.

The DSSE envelope digest is over the exact validated envelope under its own
domain. It is not the payload digest and is never embedded into itself.

## Fixed-function live preflight

The GitHub-hosted job first calls the fixed #2502 binding endpoint and receives
the coordinator-signed handoff. It then calls
`POST https://testai.acik.com/api/v1/endpoint-admin/remote-access/preflight/attest`,
which accepts only
`schema/faz22-6-view-only-live-preflight-request-v1.schema.json`, with a hard
HTTP body limit of 256 KiB. The request carries the coordinator-signed binding
handoff, idempotency key and exact ordered twelve-check list. It has no plain
caller-authored binding, persona, status, evidence, verdict or `PASS` field.
The maximum signed response is 512 KiB. Lease redemption is bounded to 1 MiB
request/response and checkpoint create to 512 KiB request/response.

The attestor validates OIDC and #2502 intent binding before doing work. It then
performs all checks itself and returns one DSSE envelope whose payload validates
against
`schema/faz22-6-view-only-live-preflight-attestation-v1.schema.json`:

1. target identity;
2. Authorization Code + PKCE;
3. real token refresh;
4. route/API;
5. browser console baseline;
6. replay isolation;
7. cluster context;
8. ports/tunnels;
9. live image digests;
10. policy and mask;
11. runner capacity;
12. watchdog and rollback readiness.

Each check has a fixed implementation version, source, evidence digest,
observation time and expiry. The receipt repeats the exact binding and binds
the request, transaction, OIDC run and hashed JTI. It is fresh for at most 300
seconds, usable once, and records `mutationCount=0` and
`attendedConsentAttempted=false`.

The TEST persona is provisioned out of band before the run. Its tenant and
identity hashes must equal the signed binding pins and its expiry must be at
least 900 seconds after receipt issuance. The backend cannot choose another
tenant or persona. Preflight performs
a normal browser login and refresh-token rotation but does not create, update
or delete a Keycloak user, password, role, client or realm. Short-lived login
session records are protocol effects, not configuration mutations; the receipt
still proves `adminCredentialUsed=false` and
`userConfigurationMutationCount=0`.

## DSSE and trust verification

Every signed response uses
`schema/faz22-6-dsse-envelope-v1.schema.json`, exactly one Ed25519 signature and
canonical JCS payload bytes. The verifier must, in this order:

1. enforce the bounded envelope and exact payload type;
2. Base64-decode and reject non-canonical payload bytes;
3. validate the strict payload schema with unknown fields rejected;
4. require the exact pinned `vault-transit://...#vN` key ID;
5. require that key to be active, unrevoked and valid at `issuedAt` in the
   independently pinned trust root;
6. verify DSSE PAE and signature;
7. recompute envelope, request, binding and transaction digests;
8. enforce issued/expiry/skew, max-use and replay state.

The #2502 binding handoff remains under the independently pinned cross-AI
coordinator trust root. Runtime preflight, refreshed preflight, lease and
checkpoint receipts use the separate strict resource
`config/faz22-6-view-only-runtime-trust-root.v1.json`, validated by
`schema/faz22-6-view-only-runtime-trust-root-v1.schema.json`. The resource
contains canonical Ed25519 public key bytes, key ID/version, signer role,
validity window and explicit revocations. `runtime-attestor` may sign only
preflight receipts; `checkpoint-signer` may sign only leases and checkpoints.
Unknown, revoked, expired, role-mismatched or non-Ed25519 keys fail closed.
The resource digest is JCS over
`{domain:"faz22.6/view-only/runtime-trust-root/v1",trustRoot:<exact object>}`.
Its exact path and digest must be in the signed authority set. The current
resource deliberately contains no keys and is `tracked_pending`; activation
cannot occur until real Transit public keys are provisioned and pinned.

The Transit private key never enters GitHub or application configuration. Key
rotation requires an additive trust-root update followed by policy pin update;
revoked or unknown key IDs are rejected. Trust-root or signer unavailability
never falls back to an unsigned response.

## Protected decision and checkpoint lease

After the preflight receipt is verified, the protected authorization job
obtains the `authorization` OIDC token and calls:

`POST https://testai.acik.com/api/v1/endpoint-admin/remote-access/preflight/checkpoint-leases/redeem`

The strict request schema is
`schema/faz22-6-view-only-checkpoint-lease-redeem-v1.schema.json`. It carries
the preflight DSSE envelope, the exact signed #2502 v3 authority envelope, the
binding, and a request for 64 writes with a maximum 7200-second TTL. The backend
verifies both envelopes, same binding/run/head and revocation. It treats the
machine-decision receipt as evaluation evidence even if its five-minute window
elapsed while the human reviewer waited. Evaluation evidence may be at most
7200 seconds old and may never outlive the signed authorization envelope. At
redemption it internally reruns
the same twelve fixed-function checks with zero mutation and no new Environment
approval, produces a fresh signed redemption preflight receipt, then atomically
consumes the authority once and returns a signed lease conforming to
`schema/faz22-6-view-only-checkpoint-lease-v1.schema.json`.

One authority redemption creates at most one lease. A different redemption
request fails after consumption; an exact transport retry returns the original
byte-identical lease and leaves `authorizationRedemptionCount=1`. Grant expiry
still requires a new intent. The resulting lease permits sequences 0 through
63, at most 64 total checkpoint writes. This is not repeated authorization
redemption. Closing or expiring the lease prevents every later write.

The executor obtains a separate `executor` OIDC token and presents it together
with the signed lease on create. Read uses the same OIDC profile and a
non-secret `X-Faz22-Checkpoint-Lease-Id` UUID header. The backend binds the
first valid executor run/head/attempt to the lease and rejects every mismatch.
Raw OIDC, product bearer, refresh token, password, private key, consent
decision and screen content are never stored.

## External checkpoint CAS

The runner-local `/tmp` hash chain remains a cache only. Durable state uses:

- create: `POST /api/v1/endpoint-admin/remote-access/preflight/checkpoints`;
- read: `GET /api/v1/endpoint-admin/remote-access/preflight/checkpoints/{transactionIdSha256}/{sequence}`;
- create request:
  `schema/faz22-6-view-only-external-checkpoint-create-v1.schema.json`;
- signed receipt:
  `schema/faz22-6-view-only-external-checkpoint-receipt-v1.schema.json`;
- receipt payload type:
  `application/vnd.acik.faz22-6-view-only-external-checkpoint-receipt.v1+json`.

The first durable checkpoint is sequence 0 in `DECISION_AUTHORIZED`; INIT and
preflight evidence are already durable in the signed preflight and lease. Every
later sequence must be exactly previous sequence plus one and must supply the
previous stored-object digest and prior receipt state. Sequence 0 requires null
previous digest/state and exactly `DECISION_AUTHORIZED`; sequences 1 through 63
require both previous values. The backend requires `previousState` to equal the
prior signed receipt state and the requested state to appear in the normative
`checkpointCas.stateMachine.transitions[previousState]` list. This transition
map is identical to the runner-local state machine from `DECISION_AUTHORIZED`
through terminal reconciliation. Repeating the same transaction,
sequence, request body and idempotency digest returns the byte-identical signed
receipt. Any different body at that sequence is a conflict.

### Response-loss idempotency

Every POST request carries `requestId` and `idempotencyKeySha256`. The key is
the operation-specific domain hash over the request ID, canonical validated
body digest and stable authenticated identity projection: issuer, subject,
actor ID, repository ID, run ID, run attempt, ref and SHA. Volatile OIDC JTI,
iat and exp are verified and replay-recorded but excluded from that stable
projection so a fresh token from the same run can recover a lost response. The
body digest is computed over the validated request with
`idempotencyKeySha256` removed; therefore the key is not self-referential.

Binding lookup, preflight, lease redemption and checkpoint create commit the
validated request, identity projection and exact signed DSSE response in one DB
transaction under a unique operation/key constraint. Exact retry returns the
stored byte-identical envelope. Reusing a key or request ID with a different
body or identity returns 409. A deliberate redemption-time preflight refresh
uses a new refresh request ID/domain; it is not a retry of the evaluation
preflight. Activation requires response-loss fault injection after commit and
before response for all four POST operations.

Runner-local checkpoint and payload digests use the same restricted JCS UTF-8
encoding as the contract. The backend still treats them as bound opaque evidence
digests: it stores and signs them but does not substitute them for the external
stored-object digest or trust them as lifecycle authority.

Every receipt repeats the exact binding and carries lease, preflight,
authorization, executor run, local checkpoint/payload and stored-object
digests. `storedObjectSha256` names the immutable validated CAS object;
the DSSE envelope digest names the receipt. Neither is self-referential.

`authorizationEnvelopeSha256` is mandatory for every durable state because the
chain begins after authorization. `ROLLED_BACK` may be a non-terminal
intermediate checkpoint before `COMPLETED` or `FAILED_CLEAN`, or terminal when
rollback is the final safe outcome. `COMPLETED` and `FAILED_CLEAN` must always
be terminal. A terminal receipt atomically closes the lease. Only a
child-process failure inside the same live GitHub job may resume: a bounded
supervisor retries at most twice with 5 and 15 second backoff, first reading and
verifying the latest external signed checkpoint and then invoking an idempotent
phase. Runner host loss, GitHub job loss and workflow rerun are not resumable
under the authority; `run_attempt=2` is rejected. No product session, consent or
bearer is resumed. If process continuity is lost after consent, watchdog cleanup
is authoritative and a new attempt requires a new #2502 intent, new
authorization and new attended consent. `ROLLED_BACK` may be a non-terminal
reconciliation checkpoint before `COMPLETED` or `FAILED_CLEAN`.

## Errors

Every non-2xx body validates against
`schema/faz22-6-view-only-preflight-error-v1.schema.json`, contains no raw
credential and reports zero API mutation. Status mapping is fixed:

- `400`: request/schema/state invalid;
- `401`: invalid, expired or mismatched OIDC;
- `403`: intent, authority or lease binding mismatch;
- `409`: replay, idempotency, sequence or previous-digest conflict;
- `410`: expired/closed receipt, authority or lease;
- `422`: a live preflight check failed;
- `503`: Transit signing or required source unavailable.

## Ownership

`platform-backend` owns the attestor, source-specific checks, four OIDC
verifiers, Transit signer, one-use redemption and checkpoint CAS API. This
GitOps repo owns endpoint deployment, narrow Kubernetes RBAC, NetworkPolicy,
ESO/Vault policy, workflow DAG, authority policy and live canary. #2502 owns the
signed authority bundle and verification/consumption of these exact receipts.

## Acceptance

Source completion is not runtime completion. Before this ADR can become
`ACCEPTED`, TEST must prove:

- redacted live OIDC claim canaries for all four profiles;
- negative canary: a failed live check produces zero approval prompt and zero
  mutation;
- positive canary: one live receipt, one protected decision, one attended
  consent, rendered/ACK evidence, signed checkpoints and automatic cleanup;
- crash canary: verified signed resume or watchdog rollback with no session or
  consent reuse;
- replay, wrong-run, wrong-head, expired-key, revoked-key, sequence-conflict,
  wrong-tenant, wrong-persona, authority-file-tamper, idempotency-conflict and
  signing-unavailable denials;
- response-loss recovery returns byte-identical binding, preflight, lease and
  checkpoint envelopes without a second authority redemption;
- same-job child-process fault injection resumes at most twice from a verified
  external checkpoint; host/job loss follows watchdog rollback and new intent;
- no GitHub, SSH or staging-sw dependency in the product runtime path;
- exact Transit public key and trust-root digest pinned in the authority file;
- fresh Claude Opus 4.8 and provider-distinct Codex exact-head `AGREE` receipts.
