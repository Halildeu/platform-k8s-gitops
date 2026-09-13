# Meeting speaker quality - bounded TEST acceptance

Product Slice: #3399. Execution: #3740 (backend), #3741 (web), #3742 (TEST).

The customer path is recording with consent -> streamed transcript -> finish ->
durable analysis -> authorized browser reopen with anonymous speaker turns and
source citations. A build, API probe, or synthetic benchmark alone is not a
real-customer delivery or production readiness declaration.

## Metric contract

`scripts/faz24/fixtures/meeting-speaker-tr-v1` contains only generated Turkish
speech: 113 words, four alternating turns, two TTS voices, 76.696 seconds,
16 kHz mono PCM16. Generation used edge-tts 7.2.8, AhmetNeural and EmelNeural.
The WAV and reference JSON are both SHA-256 pinned by the runner. A changed
file fails before a network call. Do not substitute customer audio.

- WER: jiwer 4.0.0; NFKC, Turkish case normalization, punctuation replaced with
  spaces, whitespace collapsed. Report substitutions, deletions and insertions.
- DER: pyannote.metrics 4.1, pyannote.core 6.0.1; report missed speech, false
  alarm and speaker confusion. Unknown `UU` is not guessed as a known speaker.
- Report both 0.25-second collar and zero collar, `skip_overlap=false`.
  The reference uses TTS word boundaries, not human-annotated continuous speech.
  Collar removes much of this short reference: denominator 24.25 seconds versus
  51.45 seconds with zero collar. These scores are not a human meeting benchmark.
- Project regression bounds are WER <= 0.10 and DER <= 0.30 at the declared
  collar. They are project limits, not universal industry standards. Keep the
  failed candidate receipt; never tune a threshold to pass that candidate.
- Verify stream-to-storage attribution equality, reopened rows, same persisted
  analysis result, target browser access and denied access separately.
  Every final in this pinned two-speaker fixture must retain attribution in
  storage. A low aggregate DER cannot excuse missing metadata or zero finals.

Provider contract: [Speechmatics realtime API](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket).
Metric definitions: [pyannote.metrics reference](https://pyannote.github.io/pyannote-metrics/reference.html)
and [evaluation paper](https://www.isca-archive.org/interspeech_2017/bredin17_interspeech.pdf).

## Execution

Offline, without provider credentials:

```bash
uv run --with-requirements scripts/faz24/requirements-speaker-quality.txt \
  python -m unittest discover -s tests/faz24 -p test_meeting_speaker_quality.py -v
```

The same command runs in the isolated `Meeting Speaker Quality Offline Contract`
CI job. Offline tests prove fixture and scorer behavior, not transcription quality.

Runtime uses `run-platform-desktop-token-evidence-chain.sh`'s bounded TEST persona
and its realtime lifecycle hook. Set `QUALITY_REPO` to this checkout,
`QUALITY_FIXTURES` to the committed fixture directory and `QUALITY_PHASE=after`.
The hook is `meeting-speaker-quality-wrapper.py`; run with the pinned requirements.
It requires the exact `https://testai.acik.com` URL, pinned audio path, a fresh
output directory and a mode-0600 token file. Credentials stay outside evidence.
Finalization currently waits at least six minutes; the result poll budget is
600 seconds. EOF/drain alone must not be treated as persisted analysis.

On the approved TEST runner, from the root of this checkout (the existing
evidence chain resolves its contract validator from the current directory):

```bash
umask 077
VENV="$(mktemp -d /tmp/meeting-quality-venv.XXXXXX)"
EVIDENCE="$(mktemp -d /tmp/meeting-quality-evidence.XXXXXX)"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -r scripts/faz24/requirements-speaker-quality.txt
QUALITY_REPO="$PWD" \
QUALITY_FIXTURES="$PWD/scripts/faz24/fixtures/meeting-speaker-tr-v1" \
QUALITY_PHASE=after \
RUN_EXTERNAL_SMOKE=0 RUN_SPEECHMATICS_REALTIME=1 \
REALTIME_PYTHON="$VENV/bin/python" \
REALTIME_HELPER="$PWD/scripts/faz24/meeting-speaker-quality-wrapper.py" \
REALTIME_AUDIO_FILE="$PWD/scripts/faz24/fixtures/meeting-speaker-tr-v1/two-speaker-tr.wav" \
OUT_DIR="$EVIDENCE" \
bash scripts/faz24/run-platform-desktop-token-evidence-chain.sh
jq '{status, cleanup}' "$EVIDENCE/faz24-platform-desktop-token-diagnostic.json"
jq '{status, gates, wer, syntheticDER}' "$EVIDENCE/faz24-speechmatics-realtime-lifecycle-acceptance.json"
```

This command temporarily provisions only the canonical allowlisted TEST smoke
identity and restores direct-grant state. Verify cleanup even when acceptance
fails. Follow the claim and TEST mutation rules before executing it.

Without an independent browser receipt, a successful wrapper result is only
synthetic API acceptance. Optional `QUALITY_BROWSER_WAIT` waits up to 300 seconds
for a separate browser result and fails closed on timeout. Do not overwrite a
failed combined report when a later separate browser run passes.

Browser acceptance must use the real TEST ingress and identity provider, verify
desktop/mobile anonymous labels, all transcript pages, persisted result identity,
and a fresh login after revoking temporary transcript permissions. Use only
synthetic test identities. Do not alter a human account or add raw FGA tuples.
Permission-service reconciles direct feature grants: snapshot effective grants
before assigning a temporary SQL role. Preserve prior grants through its canonical
writer; removing a temporary role does not necessarily restore legacy direct tuples.

## Known limits

This small clean TTS sample does not cover room reverberation, cross-talk, accents,
code switching, distant microphones or a representative customer vocabulary.
Speaker labels are scoped anonymous identities, not names or voiceprints.
Real-world quality needs a consented, representative, human-annotated corpus with
speaker-count/noise/overlap slices and held-out evaluation. No production/legal
approval or real-audio external-provider permission is inferred from this test.
The internal diarization adapter gap is tracked separately in #3746.
`durable.usableProductResult` is the existing workflow/source gate, not a gold
decision/action score. The unchanged Ollama `llama3.1:8b` result classified a
past design-review report as a decision in this fixture; semantic precision,
recall and confidence calibration are tracked in #3753. A valid source quote
does not prove its classification is correct. Elapsed-time display is #3751.

## TEST reactivation after a producer change

Use the strict policy and `issue-transcript-ready-permit.sh`; see the legacy
pre-enable runbook. Collect while the ready consumer is disabled, then activate
a fresh single-use permit. Never remove consumption markers or bypass freshness.
If automatic trust-root discovery cannot quote the remote Windows path, fetch
the currently pinned public trust root, verify its SHA-256 and pass `--trust-root`.

Before disabling, preserve the DPAPI config backup and its hash. Disable drops
ready-only settings. When re-enabling a *new* producer, supply the old Redis URL
as a SecureString decrypted only in memory, and explicitly carry forward replay
horizon, stream, group, analysis spec and snapshot path from the verified backup.
`-RestoreBackup` intentionally uses the backup's old expected artifact pins; it
is not a new-producer activation mechanism. Failed activation can consume a
permit before atomic config validation; issue a fresh permit for every retry.
Restart only `platform-ai-meeting-ai`, prove a new task/listener with canonical
restart helpers, unchanged live-STT, ready workers and a new persisted result.
