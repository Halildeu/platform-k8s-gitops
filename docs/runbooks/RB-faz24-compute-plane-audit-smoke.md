# RB — Faz 24 compute-plane audit smoke evidence

> **Status**: ACTIVE — metadata-only verifier package.
> **Scope**: `platform-ai#188`, audio-gateway direct-STT audit event,
> `platform-test` / `testai.acik.com`.
> **Boundary**: This runbook does not enable direct-STT and does not prove
> transcript quality, desktop capture, WG-B+, or production readiness. It only
> defines how to package and verify the
> `CHUNK_FORWARDED_TO_COMPUTE_PLANE` audit event once an approved direct-STT
> smoke is run.

## Context

`platform-backend#749` added the
`CHUNK_FORWARDED_TO_COMPUTE_PLANE` audit event and Redis sink mapping.
`platform-backend#751` added direct-STT HTTPS/mTLS client wiring. GitOps has
pinned the mTLS-capable `audio-gateway` artifact to test overlay, but
`audio.gateway.direct-stt.enabled` remains default-off until the live gate is
accepted.

`platform-ai#188` is the live activation gate before `platform-ai#182` can
claim raw-audio compute-plane transit. The required proof is same-session,
same-chunk, same-correlation audit evidence for
`CHUNK_FORWARDED_TO_COMPUTE_PLANE` with no raw audio, no transcript text, no
destination URL, no token material, and no production/readiness overclaim.

## Evidence Envelope

After an approved direct-STT smoke, create a metadata-only JSON envelope in an
owner-local temp directory:

```bash
EVIDENCE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/faz24-compute-plane-audit.XXXXXX")
EVIDENCE_FILE="$EVIDENCE_DIR/evidence.json"
VERIFY_FILE="$EVIDENCE_DIR/verify.json"
```

Envelope shape:

```json
{
  "schemaVersion": "faz24.computePlaneAuditEvidence.v1",
  "status": "pass",
  "tokenIncluded": false,
  "source": {
    "streamKey": "audit:events",
    "redisStreamRecordId": "1782370000000-0"
  },
  "expected": {
    "sessionId": "SES-...",
    "meetingId": "22222222-2222-4222-8222-222222222222",
    "chunkSeq": 0,
    "correlationId": "faz24-direct-stt-...",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "byteLength": 512,
    "computePlane": "live-stt"
  },
  "event": {
    "eventType": "CHUNK_FORWARDED_TO_COMPUTE_PLANE",
    "sessionId": "SES-...",
    "tenantId": "42",
    "userId": "7",
    "meetingId": "22222222-2222-4222-8222-222222222222",
    "deviceId": "desktop-smoke-1",
    "language": "tr",
    "chunkSeq": "0",
    "audioFormat": "WAV",
    "sampleRateHz": "16000",
    "channels": "1",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "byteLength": "512",
    "correlationId": "faz24-direct-stt-...",
    "forwardedAtMs": "1782370000000",
    "computePlane": "live-stt"
  },
  "boundaries": {
    "chunkForwardedToComputePlaneProven": true,
    "rawAudioIncluded": false,
    "rawTranscriptIncluded": false,
    "destinationUrlIncluded": false,
    "directSttTranscriptProven": false,
    "desktopMicLoopbackProven": false,
    "productionReady": false
  },
  "failures": []
}
```

Do not include raw Redis command output, bearer tokens, JWTs, idempotency keys,
audio bytes, transcript text, transcript segments, `transcribeUrl`, or raw
destination URL.

## Verify

Run:

```bash
python3 scripts/faz24/verify_compute_plane_audit_evidence.py \
  --evidence-file "$EVIDENCE_FILE" \
  --output-file "$VERIFY_FILE"
```

Expected verifier evidence:

- `$VERIFY_FILE` has
  `schemaVersion=faz24.computePlaneAuditVerifier.v1`, `status=pass`, and
  `tokenIncluded=false`.
- `event.eventType=CHUNK_FORWARDED_TO_COMPUTE_PLANE`.
- `event.sessionId`, `meetingId`, `chunkSeq`, `correlationId`, `sha256`,
  `byteLength`, and `computePlane` match the `expected` block.
- `event.computePlane=live-stt`.
- Boundary fields keep transcript, desktop mic/loopback and production claims
  false.

## Attachment Rule

Attach only these two redacted JSON files to `platform-ai#188` or the linked
GitOps evidence comment:

- `$EVIDENCE_FILE`
- `$VERIFY_FILE`

This evidence may move #188 forward only when the verifier returns `pass`.
It does not satisfy `platform-ai#182` transcript routing, desktop mic/loopback,
WG-B+ #1864/#1867, or production readiness.

## Cleanup

```bash
rm -rf "$EVIDENCE_DIR"
```

## References

- Gate issue: `platform-ai#188`
- Direct-STT e2e issue: `platform-ai#182`
- Backend audit event: `platform-backend#749`
- Backend direct-STT mTLS wiring: `platform-backend#751`
- Verifier: `scripts/faz24/verify_compute_plane_audit_evidence.py`
