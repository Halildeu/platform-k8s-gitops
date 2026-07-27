# ADR-0048 — Faz 35 evidence dual-artifact custody ve attachment safety

**Status:** Accepted for TEST implementation
**Date:** 2026-07-24
**Decision owner:** Product Security / Platform Engineering
**Tracks:** ES-005, ES-104, ES-206, ES-210
**Contract:** [`faz35-evidence-custody/v1`](../contracts/faz35-evidence-custody.v1.json)
**Related:** [ADR-0047 compartment and key custody](./0047-faz35-case-identity-link-compartments.md),
[Etik Speak API/MFE contract](../contracts/faz35-etik-speak-api-mfe-v1.md),
[product charter](../faz-35-etik-speak-product-charter.md)

## 1. Decision

Etik Speak does not expose a reporter upload as ordinary application storage.
Every attachment is handled as two cryptographically related, operationally
separate artifacts:

1. **sealed original** — byte-identical upload, immutable and unavailable to
   normal case roles;
2. **sanitized derivative** — scanner/CDR output used by authorized case
   workers after all admission gates pass.

The public reporter journey stays truthful and usable when the attachment
pipeline is unavailable. A report can still be submitted without an
attachment, but the UI and API must visibly reject or defer the attachment.
Content is never copied into the narrative, silently accepted, or exposed
directly from quarantine. Until ES-104/ES-206 runtime acceptance, attachments
remain disabled and the product operates as an explicit text-only slice.

The machine-readable contract is authoritative for state names, storage zones,
standing capabilities, admission limits, access profiles, failure modes and
negative tests. This ADR explains the security intent; the JSON contract keeps
it executable and versioned.

## 2. Why this is required

Whistleblowing attachments may contain:

- malware, macros, scripts, polyglots or active PDF content;
- EXIF, author, company, printer, path or document-history metadata that
  identifies a reporter;
- archive bombs, nested containers and parser exploits;
- evidence whose byte-preserving original is required for custody;
- content that a normal case handler must not download.

A single mutable object with a `scanned=true` flag cannot meet both evidence
preservation and safe daily viewing. Replacing the original destroys custody;
showing the original to ordinary staff defeats sanitization. The dual-artifact
model retains both properties without giving one standing principal broad
read access.

This baseline translates the relevant engineering controls from ISO 37002,
ISO/IEC 27001 and 27002, ISO/IEC 27037, GDPR Art. 5/25/32, KVKK Md. 12, NIST
SP 800-53 SI-3/AU-9/SC-28, OWASP ASVS file-handling controls and the OWASP File
Upload Cheat Sheet. It is an engineering baseline, not legal advice or a
certification claim.

## 3. Attachment lifecycle

The only accepted forward path is:

```text
DECLARED
  -> UPLOADING
  -> QUARANTINED
  -> INTEGRITY_VERIFIED
  -> ORIGINAL_SEALED
  -> SCANNING
  -> SANITIZING
  -> DERIVATIVE_READY
  -> AVAILABLE
```

Terminal or bounded side paths are:

- `REJECTED_INTEGRITY`: size, digest, media-signature or upload binding failed;
- `REJECTED_POLICY`: unsupported type, active content, nesting or configured
  product policy failed;
- `MALICIOUS_QUARANTINED`: malware or exploit signal; never case-visible;
- `SCAN_PENDING`: scanner outage or bounded back-pressure; never
  case-visible;
- `SANITIZE_FAILED`: no derivative is published;
- `EXPIRED_UNBOUND`: incomplete/unbound upload exceeded its TTL and is
  cryptographically disposed;
- `DISPOSED`: retention and legal-hold policy allowed final disposal.

No transition skips `INTEGRITY_VERIFIED`, `ORIGINAL_SEALED`, `SCANNING` or
`SANITIZING`. A database status update cannot make bytes available by itself;
the finalizer re-reads the immutable manifest and object-store properties.

Report commit and attachment finalization are separate transactions. A report
receipt is not delayed by an unavailable scanner, and an attachment is not
claimed as attached until `AVAILABLE`. Idempotency is bound to the declared
attachment digest, size and media policy; reusing a key with different bytes
is rejected.

## 4. Admission and upload boundary

The browser first declares the attachment through the public API. The server
returns a short-lived, job-scoped, write-only upload capability for one opaque
object key. It cannot list, read, overwrite another object or choose a bucket.

Admission is deny-by-default:

- file extension is advisory; magic bytes and bounded parser results decide;
- initial allowlist is PDF, UTF-8 plain text, JPEG and PNG;
- executable, script, HTML, SVG, macro-enabled Office, disk-image and unknown
  formats are rejected;
- archive/container formats are rejected in the baseline. Future recursive
  support requires bounded entry count, nesting, expanded-size and compression
  ratio plus a new contract version;
- declared size, streamed byte count, content length and SHA-256 must agree;
- upload capability has a short TTL, exact content-length ceiling and exact
  object binding;
- partial/multipart uploads are aborted after a bounded TTL;
- the original client filename is not an object key, metric label, trace
  attribute or immutable audit field.

The default limits in the contract are product safety ceilings, not customer
legal policy. A customer can select a lower, versioned limit. Increasing the
ceiling or enabling a new format requires parser/scanner capacity evidence and
a contract change.

## 5. Storage zones and immutable lineage

Four zones have different credentials, policies and lifecycle:

| Zone | Purpose | Ordinary staff read |
|---|---|---|
| `quarantine` | untrusted upload and bounded scan input | denied |
| `sealed-original` | byte-identical, encrypted, WORM original | denied |
| `sanitized-derivative` | safe case-worker projection | authorized case scope only |
| `controlled-export` | redacted, time-bound export package | named export gate only |

Object names are opaque random references. Bucket metadata contains only
bounded operational values: artifact role, size, SHA-256, policy version and
coarse state. Reporter identity, original filename, narrative, receipt,
employee identifier and human-readable case number are forbidden.

After transport integrity succeeds, a server-side promotion writes the
byte-identical upload to `sealed-original` with encryption, object-lock/WORM
retention and a content-addressed manifest. The manifest is signed by the
control plane, not by the upload client or scanner alone.

The derivation manifest binds:

- sealed-original SHA-256 and size;
- sanitized-derivative SHA-256 and size;
- media type before and after sanitization;
- scanner, sanitizer and parser immutable image digests;
- malware signature/rule-set versions;
- policy version and deterministic transformation profile;
- timestamps, outcome classes and previous manifest hash.

It never carries content, identity, original filename or raw storage
credential. Re-running sanitization produces a new derivative version and a
new append-only derivation record; it does not overwrite history.

## 6. Scanner and sanitizer contract

Scanner and sanitizer tools are pinned by immutable image digest and carry
SBOM/provenance evidence. Moving tags or an unrecorded signature database are
not release evidence.

The baseline pipeline:

1. verifies media signature and bounded structural parse;
2. checks malware/exploit signatures and suspicious active features;
3. rejects archives and unsupported embedded content;
4. strips EXIF, document author/company/path/history, comments, scripts,
   actions, forms, external references and embedded files;
5. re-encodes images and renders documents through an isolated, no-network,
   read-only-root, non-root sandbox with CPU/memory/time/output caps;
6. scans the generated derivative again;
7. verifies that the output type is allowlisted and metadata policy is clean;
8. writes a new derivative object and signed lineage manifest.

Scanner success alone is insufficient. `AVAILABLE` requires both the malicious
content verdict and the sanitization/metadata verdict. If either tool times
out, crashes, exceeds limits or returns an unknown result, the attachment
remains unavailable.

The scan/sanitize workers have no public ingress, no general internet egress
and no Case/ReporterIdentity database credential. A job grants access to one
opaque quarantine object only. Standing workload credentials cannot read the
sealed-original zone.

## 7. Access and reveal

Normal `case_viewer`, `case_triager` and `case_handler` roles can request only
the latest accepted sanitized derivative for an authorized organization and
case. Access is served through the staff API with:

- product entitlement, server-resolved organization and OpenFGA decision;
- a same-origin, short-lived, single-object response capability;
- `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`,
  restrictive CSP/sandbox behavior and no object-store credential exposure;
- append-only privacy-safe access event.

The sealed original requires the ADR-0047 reveal ceremony:

- two different human approvers;
- case-bound request digest and explicit purpose;
- conflict, recusal, self/proxy/wrong-org checks;
- one-use grant with maximum ten-minute TTL;
- non-standing `sealed-reveal-session` capability;
- no bulk/list access and no direct object-store console access;
- immutable request/deny/consume/result audit events.

Technical admin, product admin, case handler, scanner, backup operator and
platform operator roles do not imply sealed-original read.

Controlled export uses only an approved derivative or an explicitly approved
sealed reveal result. It creates a new content-addressed export artifact with
its own manifest, expiry and immutable access trail; it does not copy the
source bucket credential to the caller.

## 8. Audit, privacy and custody

The lifecycle emits redacted outbox events for declaration, integrity result,
seal, scan result, derivative creation, availability, read, reveal request,
deny, consume, export and disposal. Delivery uses the ES-207 append-only WORM
path and does not make the upload transaction synchronously depend on the
external sink.

Allowed audit fields are opaque attachment reference, artifact role, bounded
outcome/reason, actor class, policy/tool version, size class, digest and coarse
timestamp. The following are forbidden:

- attachment bytes or extracted text;
- original filename or reporter-supplied path;
- reporter identity, contact or device/network metadata;
- narrative, receipt/access secret or mailbox credential;
- raw storage URL, presigned URL, token, key or bucket credential.

Metrics remain aggregate: queue depth, bounded outcome, latency histogram,
scanner rule version and deployment digest. Object, case, receipt, reporter or
filename identifiers are never metric labels.

## 9. Failure isolation and recovery

- Scanner, sanitizer or object-store outage does not block text-only report
  submission or mailbox messaging.
- The public UI displays attachment unavailability before selection when
  health/capacity is not accepted, and displays the per-attachment terminal
  outcome after upload.
- Unknown outcomes stay `SCAN_PENDING` or `SANITIZE_FAILED`; no optimistic
  `clean` status exists.
- Quarantine backlog, oldest age, failed count and capacity are alerted without
  exposing object identifiers.
- A bounded retry uses the same declared digest/idempotency binding. It cannot
  create a second sealed original or duplicate custody event.
- Quarantine and derivative deletion obey a versioned retention/hold policy.
  Sealed-original WORM retention and legal hold are never bypassed by ordinary
  application deletion.
- Crypto-erasure happens only after retention and legal-hold conditions are
  satisfied, under the compartment-specific key-custody contract.
- A failed restore or re-scan runs in an isolated scratch environment and does
  not mutate the live artifact or its manifest.

## 10. Required TEST evidence

ES-104/ES-206 cannot become accepted until exact artifacts and TEST runtime
prove all of the following:

1. clean PDF/image/text produces a different sanitized derivative where
   metadata/active-content removal is applicable and lineage verifies;
2. EICAR/synthetic malware, polyglot, wrong magic, oversized, nested archive,
   decompression bomb and parser-timeout inputs are denied;
3. scan/sanitize outage leaves the report/mailbox path functional and the
   attachment unavailable;
4. ordinary manager roles cannot read quarantine or sealed original;
5. authorized manager can read only the correct-org sanitized derivative;
6. wrong-org, technical-admin, reporter credential and stale/replayed
   capability fail without existence disclosure;
7. dual-control reveal permits one exact sealed object once; self, same-person,
   proxy, recused, expired, replay and bulk/list attempts fail closed;
8. object metadata, logs, traces, metrics, audit events and browser
   storage/URL contain no forbidden values;
9. source digest, image digest, live imageID, scanner/rule versions and
   signed lineage match;
10. rollback disables new attachment declarations first, drains or preserves
    bounded quarantine safely, and leaves text intake/mailbox operational.

Browser and live evidence uses synthetic files and synthetic personas. Raw
malware, attachment content, credentials or real PII are not uploaded to
GitHub/CI evidence.

## 11. Consequences and boundaries

This decision adds storage zones, immutable manifests, isolated workers and a
dual-control reveal path. That cost is intentional: a whistleblowing product
must preserve evidential bytes without exposing unsafe or identifying content
to routine case operations.

This ADR and contract prove a source/design decision only. They do not prove
scanner effectiveness, runtime isolation, malware-free content, legal
admissibility, customer retention choices, production activation, named
Legal/DPO acceptance or real-reporter safety. Production attachment enablement
requires exact TEST evidence plus named Product Security, Privacy/Legal and
Secret Owner acceptance.
