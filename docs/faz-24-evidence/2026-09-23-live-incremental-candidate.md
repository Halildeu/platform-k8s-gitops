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

Do not promote this overlay until the exact gateway image built from #1184 replaces
the existing pin and #349 is on the GPU host with rollout acceptance. The revision
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
