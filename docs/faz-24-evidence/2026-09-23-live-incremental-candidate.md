# Mobile live updates: candidate, runtime acceptance pending

User requirement: decisions and tasks must update as speech progresses. A result
minutes later or a single partial summary before EOF is not sufficient.

Sources: platform-ai#349 (incremental grounded context), platform-backend#1184
(sentence boundary trigger, per-meeting cursor and timing), platform-mobile#45
(readable sentence paragraphs and analysis diagnostics).

TEST candidate config: sentence-triggered=true, min-interval-ms=1000,
max-wait-ms=5000. Sentence completion triggers immediately subject to single-flight
and cadence; the five-second window only bounds punctuation-free speech. This is
not a guarantee of five-second phone rendering. Default/prod config is unchanged.

Gateway source is platform-backend#1184, merged at
`80c08d0abeff2d635e10395243ffefaa8bff9663` after all PR checks passed.
Build run `35838016116`, successful gateway job `107106048811`, published
`sha256:3c7a653479b4b8bbce27190e339b0636a38ab493291c6f617fd2274a2711d81d`;
GitHub provenance attestation `49469570`. The TEST overlay pins this exact image.
AI source is platform-ai#349, merged at
`08671f44b39de262ef7030a8716ae62967becc22` after all checks passed.
GPU rollout run `35837305448` failed. Source returned to `e386b996`, but
runtime rollback failed and both application tasks were fenced. Read-only
run `35847268522` identifies the meeting-AI startup permit rejection as
`TRUST_ROOT_VALIDITY_INVALID`; the pinned root expired September 17.
PR3814 provides same-key TEST renewal and full recovery; PR3815 corrects
the staging serializer after the first apply stopped before writing config.
Runtime restoration is still unverified at this update.
Do not promote this overlay until #349 is on the GPU host with rollout acceptance. The revision
annotation reloads the ConfigMap. Rollback restores the previous image and source,
sentence-triggered=false, min-interval-ms=15000, max-wait-ms=15000, and bumps the
revision annotation. Do not silently switch off model/digest/TLS/grounding checks.

The new main-only TEST probe uses the existing gateway mTLS identity in place to
send five synthetic live updates to the fixed AI endpoint. It creates no durable
meeting and exports no credentials or transcript/model response. It checks retained
decisions, task creation, cancellation and reassignment, grounded owner/date metadata,
increasing partial versions, cursor support, and a proposed five-second HTTP update
budget (including first call). Explicit cancellation decisions are optional, but
cancelled tasks must disappear. Model test failure must not be counted as a phone pass.

Further acceptance: measure the completed spoken cue to rendered phone update while
recording stays open, verify repeated updates and final saved result. The UI must
show a live draft; the durable result remains distinct. None of these runtime checks
has passed for this candidate yet. No issue closure is requested.
