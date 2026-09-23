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
AI source is platform-ai#350, including #349, merged at
`38ef0f3648c8e092599c0578764a4f2f075dd0a1`. Full GPU runtime acceptance
passed in `35858606120` after same-key trust-root renewal and the reviewed
exact-event recovery. The old retry-exhausted event reached OUTBOXED with zero
failures; no row was deleted and no runtime health check was relaxed.

The deployed source passed all five decision/task/owner/date, cancellation and
reassignment cases through gateway-pod mTLS HTTP in `35859197577`. However,
latencies were 20.124/42.059/24.088/23.373/23.666 seconds, so none met five seconds.
Installed smaller models were rejected in `35858050978`; the separately pinned
4B candidate is being measured in `35860239203` and has not been deployed.
Do not promote this overlay until live inference latency is qualified. The revision
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
