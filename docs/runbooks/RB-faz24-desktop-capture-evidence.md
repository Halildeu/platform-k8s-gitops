# RB — Faz 24 platform-desktop mic + loopback capture evidence

> **Status**: ACTIVE — metadata-only verifier/runbook package.
> **Scope**: `platform-desktop` real-device microphone + system-loopback capture
> reaching the public `audio-gateway` recorder lifecycle.
> **Boundary**: This runbook does not perform a desktop smoke by itself, does not
> send raw audio, and does not prove direct-STT, diarization, transcript quality,
> compute-plane audit, I7, or production readiness.

## Why This Gate Exists

Faz 24 must become a standalone meeting-intelligence product, not only a backend
fixture. The accepted gateway lifecycle smoke proves the public
`audio-gateway` recorder API can accept consent/session/chunk/finish calls, but
it does not prove a real desktop client can capture both:

- microphone input; and
- system-loopback / meeting-audio output.

The desktop capture gate therefore requires a redacted evidence envelope from a
real `platform-desktop` run. The verifier accepts only metadata and rejects raw
audio, transcript text, token material, direct client-to-STT calls, and broad
readiness claims.

## Metadata-Only Handoff Package

For an operator-facing command bundle, build the source-side handoff artifact:

```bash
gh workflow run faz24-desktop-capture-operator-handoff.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f operator_batch_id=faz24-desktop-capture-20260628 \
  -f gitops_ref=main
```

The artifact contains `README.md`,
`faz24-desktop-capture-operator-handoff.json`, and `SHA256SUMS`. It is a
coordination artifact only: it does not run the desktop app, read tokens,
connect to `testai.acik.com`, mutate Kubernetes/Vault, send audio, collect live
evidence, or advance #1615. Use it to hand the exact real-desktop-run ->
redacted-evidence-review -> verifier -> G-CAP aggregate command order to the
operator without embedding raw audio, token material, device labels, desktop
logs, or shell transcripts.

## Evidence Contract

Verifier:

```bash
python3 scripts/faz24/verify_desktop_capture_evidence.py \
  /tmp/faz24-desktop-capture-evidence.json \
  --summary-json /tmp/faz24-desktop-capture-evidence.verify.json
```

Accepted input schema:

- `schemaVersion=faz24.desktopCaptureEvidence.v1`
- `status=pass`
- `tokenIncluded=false`
- `client.kind=platform-desktop`
- `client.captureMode=real-device`
- `client.activeIndicatorVisible=true`
- `consent.recordingConsentCaptured=true`
- `consent.consentTextIncluded=false`
- `sources.microphone` and `sources.loopback` both:
  - `proven=true`
  - `synthetic=false`
  - `deviceLabelHash=sha256:<64 hex>`
  - bounded duration/sample-rate/channel/byte-length metadata
  - `sha256=<64 hex>` digest of the submitted chunk bytes
  - `rawAudioIncluded=false`
- exact step order:
  1. `desktop_app_started`
  2. `permission_check`
  3. `mic_capture`
  4. `loopback_capture`
  5. `record_consent`
  6. `start_session`
  7. `upload_mic_chunk`
  8. `upload_loopback_chunk`
  9. `finish_session`
  10. `session_status`
- HTTP steps use only public `audio-gateway` route templates, not destination
  URLs.
- upload step `sha256` values match the corresponding source digests.

Required boundary flags:

```json
{
  "desktopMicLoopbackProven": true,
  "gatewayOnly": true,
  "rawAudioIncluded": false,
  "rawTranscriptIncluded": false,
  "directClientToStt": false,
  "directSttTranscriptProven": false,
  "computePlaneAuditProven": false,
  "productionReady": false
}
```

## Attachment Rules

Attach only these files after local review:

- `/tmp/faz24-desktop-capture-evidence.json`
- `/tmp/faz24-desktop-capture-evidence.verify.json`

Both files must have:

- `tokenIncluded=false`
- verifier `status=pass`
- no raw audio bytes, base64 audio, transcript text, JWT/Bearer token,
  Authorization header, destination URL, cookie, private key, password, or raw
  command output.

Do not attach shell transcripts, desktop logs, raw capture files, device labels,
JWT payloads, or network traces.

## What This Does Not Prove

A passing desktop capture verifier proves only:

- the desktop app captured real microphone and loopback sources;
- consent/session/chunk/finish/status reached the public `audio-gateway`
  recorder lifecycle; and
- the evidence is redacted and bounded.

It does not prove:

- direct-STT transcript e2e (`platform-ai#182`);
- compute-plane audit (`platform-ai#188`, already accepted separately);
- full I7 app-mTLS prod-gate (`platform-ai#198`);
- diarization/DER, WER, G-INT, or G-LAT/COST;
- G-CAP aggregate reliability by itself; the verifier summary may be submitted
  as one `verify_gcap_capture_gate_evidence.py` input after `status=pass`, but
  aggregate G-CAP still requires enough accepted attempts to meet thresholds;
- G-COMP compliance readiness;
- production readiness.

## Failure Interpretation

- `status=fail` from the verifier means the evidence must not be attached as
  acceptance evidence.
- Raw audio/token/transcript findings are privacy/security failures; regenerate
  the evidence envelope instead of editing out leaked values by hand.
- Missing loopback means the run is only microphone capture, not desktop meeting
  capture.
- `directClientToStt=true` means the no-direct-client-to-STT architecture rule
  was violated; desktop must go through `audio-gateway`.
