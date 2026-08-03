# Faz 24 — Gerçek-Zamanlı STT Sektör Araştırması (2026-08-03)

> Bağlam (TR): Kullanıcı canlı transkriptin Speechmatics portalı gibi
> kelime-kelime akmasını istiyor; bizde ~5s'lik toplu satırlar görünüyor ve her
> commit yeni satır açıyor. Bu doküman Speechmatics/Deepgram/AssemblyAI/Azure/
> Google/OpenAI ve Whisper-streaming açık kaynak yığınlarının partial/final,
> endpointing ve satır-kırma stratejilerini kaynaklarıyla derler; §8-§9 bizim
> mimarimize eşleme ve önerilen parametre default'larıdır. RT revizyon işi:
> gitops#3419 (Tracked by #3419). Araştırma tarihçesi: claude 2026-08-03,
> tüm iddialar resmî doküman URL'leriyle bağlanmıştır.

**Purpose:** Evidence base for redesigning our live transcription pipeline (desktop app → audio-gateway 5s aggregation → Whisper live-stt forced 5s commits → SSE → web UI). Users see text in ~5s batches and every commit opens a new line. This document surveys how Speechmatics, Deepgram, AssemblyAI, Azure, Google, OpenAI, and open-source Whisper streaming stacks solve the same problem, then maps their mechanisms onto our knobs.

**Two findings dominate everything below:**

1. Every major vendor uses a **two-lane event model**: a *mutable partial/interim* lane rendered by replace-in-place, and an *immutable final* lane appended to the running transcript. Nobody renders only finals.
2. **No vendor commits or line-breaks on fixed wall-clock windows.** Commit boundaries are driven by silence/VAD endpointing, semantic end-of-turn models, or a max-delay *cap* — and paragraph/line breaks are driven by sentence punctuation and speaker change, never by "N seconds elapsed."

---

## 1. Speechmatics Real-Time SaaS API (priority)

### 1.1 WebSocket message protocol

Documented in the [Realtime API Reference](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket):

| Message | Direction | Semantics |
|---|---|---|
| `StartRecognition` | client → server | Opens the session. Carries `audio_format` (e.g. `pcm_s16le` raw) and `transcription_config` (language required, plus `enable_partials`, `max_delay`, `max_delay_mode`, `diarization`, `punctuation_overrides`, `conversation_config`). |
| `AddAudio` | client → server | Binary WebSocket frame containing an audio chunk. |
| `AudioAdded` | server → client | Ack for each audio chunk, carries `seq_no` for tracking. |
| `AddPartialTranscript` | server → client | **Mutable** work-in-progress transcript; only sent when `enable_partials: true`. Same structure as finals (`transcript` string + `results` word array), but "the `confidence` field … has no meaning". |
| `AddTranscript` | server → client | **Final, immutable** transcript for a span of audio. |
| `EndOfStream` | client → server | "Declares no additional audio follows. Requires `last_seq_no`" (sequence number of the last chunk sent). |
| `EndOfTranscript` | server → client | "Server response to `EndOfStream`, after the server has finished sending all AddTranscript messages." |

A partial "can be changed in a future AddPartialTranscript as more words are spoken until the AddTranscript Final message is sent for that audio" ([Realtime output docs](https://docs.speechmatics.com/speech-to-text/realtime/output)).

**Backpressure:** the service "will tolerate no more than 10 seconds of audio data or 500 individual AddAudio messages ahead of time. If you send more than this amount you will not receive an AudioAdded response until there is capacity in the buffer" ([legacy RT API guide](https://legacy.docs.speechmatics.com/en/real-time-appliance/api-v2/api-example-usage/v4.0.0/), same buffer contract referenced from the [current API ref](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket)). This implies clients stream small frames continuously and use `AudioAdded` acks for flow control — not multi-second batches.

### 1.2 Latency / partials configuration

From [Realtime output & latency docs](https://docs.speechmatics.com/features/realtime-latency) (same content served at [/speech-to-text/realtime/output](https://docs.speechmatics.com/speech-to-text/realtime/output)):

- **`enable_partials`** — boolean, **default `false`**. Partials "allow you to receive preliminary transcription and update as more context is available until the higher-accuracy Finals are returned."
- **Partial cadence/latency:** "Typically Partials are returned in less than 500 milliseconds" and partials are "not affected by the `max_delay` setting."
- **Partial quality caveat:** "Accuracy is usually 10-25% lower than the Final transcript. This includes punctuation and capitalization of words."
- **`max_delay`** — float seconds, **range 0.7–4, default 4**. Controls the maximum delay between a word being spoken and its *final* being emitted. Vendor-recommended values:
  - **0.7–1.5 s** — voice agents needing ultra-fast finals (~5% relative accuracy loss)
  - **2.0 s** — "most use cases … such as captioning or contact centres" (~1% degradation)
  - **4.0 s** — accuracy-critical (legal); equivalent to batch accuracy
- **`max_delay_mode`** — `flexible` (default) lets the engine exceed `max_delay` slightly to keep a formatted entity (number/date) intact in one final; `fixed` enforces strict latency at the cost of formatting.
- **Punctuation:** `transcription_config.punctuation_overrides` with `permitted_marks` (array or `"all"`) and `sensitivity` (0–1, **default 0.5**; "Higher values will produce more punctuation") ([API ref](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket)).

### 1.3 How the word-by-word display works (partial replace-in-place)

The [output docs](https://docs.speechmatics.com/speech-to-text/realtime/output) give the canonical rendering flow — partials mutate one screen region in place; the final replaces the partial region and commits:

```
[Partial]: Hello
[Partial]: Hello welcome to
[Final]:   Hello, welcome to Speechmatics.
```

Two load-bearing semantics from the same page:

- "Finals represent the best transcription for a span of audio and are **never updated once emitted**. Partials are emitted immediately as audio arrives and **may be revised** as more context is processed."
- "On each Final transcript you will immediately receive a Partial transcript with any remaining words which have not been finalized" — i.e. the partial lane never goes dark; leftover unfinalized words instantly re-appear as a new partial after each final, so the tail of the paragraph is always live.

So the portal-style UI is: `displayed_text = committed_finals + current_partial`, where the current partial overwrites itself on every `AddPartialTranscript` (sub-500ms cadence) and migrates into the committed region on each `AddTranscript`. Finals are *merged into the running paragraph* — a final does **not** imply a line break.

### 1.4 End-of-utterance detection

From [End of Turn Detection docs](https://docs.speechmatics.com/speech-to-text/realtime/end-of-turn) (also at [/features/end-of-turn](https://docs.speechmatics.com/features/end-of-turn)) and the [API ref](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket):

- **`conversation_config.end_of_utterance_silence_trigger`** — float, **0–2 s** ("the time in seconds after which the server will assume that the speaker has finished speaking, and will emit an `EndOfUtterance` message"). `0` disables.
- Recommended: **0.5–0.8 s for voice AI; 0.8–1.2 s for dictation** use cases.
- Constraint: keep it **lower than `max_delay`**.
- `EndOfUtterance` "messages are only sent after some speech is recognised and duplicate EndOfUtterance messages will never be sent for the same period of silence," and the message carries no speaker attribution.

### 1.5 Realtime speaker diarization

From [Realtime diarization docs](https://docs.speechmatics.com/speech-to-text/realtime/realtime-diarization):

- Enable with `"diarization": "speaker"` in `transcription_config`; every word/punctuation object in `results` gets a speaker label (`S1`, `S2`, …; `UU` = unknown).
- **`speaker_sensitivity`** (0–1, **default 0.5**), **`max_speakers`** (min 2, default unlimited), **`prefer_current_speaker`** (reduces false speaker switches between similar voices).
- "Speaker diarization uses punctuation to improve accuracy. Small corrections are applied to speaker labels based on sentence boundaries" — i.e. even the vendor treats sentence boundaries and speaker turns as coupled display concepts.

### 1.6 Session close handshake (our lost-final-ack problem)

The documented graceful shutdown ([legacy WS guide](https://legacy.docs.speechmatics.com/en/real-time-appliance/api-v2/speech-api-guide/v3.7.0/), current [API ref](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket)):

1. Client sends `EndOfStream` (with `last_seq_no`) **as its last message** — "No more messages are handled by the API afterwards, and the API processes whatever audio it has buffered at that point and sends all the AddTranscript and AddPartialTranscript messages accordingly."
2. Server flushes remaining `AddTranscript` messages, **then** sends `EndOfTranscript`.
3. "Upon receiving this message the client can safely disconnect immediately because there will be no more messages coming from the API."

Closing the socket without waiting for `EndOfTranscript` forfeits the tail finals; error conditions arrive as "an in-band error message … followed by a WebSocket close message" with documented close codes ([API ref](https://docs.speechmatics.com/api-ref/realtime-transcription-websocket)). **Directly applicable to us:** the client must wait (bounded) for `EndOfTranscript` after `EndOfStream` instead of tearing the socket down.

---

## 2. Deepgram streaming API

### 2.1 Interim results (`interim_results`)

[Interim Results docs](https://developers.deepgram.com/docs/interim-results): with `interim_results=true`, "Deepgram guesses about the words being spoken and sends these guesses to you as interim transcripts"; when `is_final: false` "Deepgram will continue waiting to see if more data will improve its predictions." Interims for a segment supersede previous interims (UI replace-in-place), and the final for that segment persists.

**Cadence (explicit number):** "Deepgram's Interim Results are sent **every 1 second**" ([End of Speech Detection docs](https://developers.deepgram.com/docs/understanding-end-of-speech-detection)).

### 2.2 `is_final` vs `speech_final` (two *different* finalities)

[Using Endpointing and Interim Results](https://developers.deepgram.com/docs/understand-endpointing-interim-results):

- `is_final: true` = "Finalized transcript for this audio segment" (text stops changing).
- `speech_final: true` = endpointing "detects pauses in speech" — the *utterance* is over.
- Warning quoted verbatim: "**Do not use `speech_final: true` alone to capture full transcripts. Long utterances may have multiple `is_final: true` responses before `speech_final: true` is returned.**"
- Recommended pattern: "Append each `is_final: true` transcript to a buffer. When `speech_final: true` arrives, the buffer contains the complete utterance" — i.e. finals are concatenated into one utterance/paragraph; only `speech_final` (not every final) is an utterance boundary. **This is exactly the distinction our UI is missing: our 5s commits behave like `is_final` events but we render them like `speech_final` line breaks.**

### 2.3 Endpointing and `utterance_end_ms`

- [Endpointing docs](https://developers.deepgram.com/docs/endpointing): `endpointing` is VAD-silence–based, **enabled by default at 10 ms**; customizable (e.g. `endpointing=300`) or `endpointing=false`, in which case "transcriptions will be returned at a cadence determined by Deepgram's chunking algorithms." A detected pause yields `speech_final: true`.
- [UtteranceEnd](https://developers.deepgram.com/docs/understanding-end-of-speech-detection): `utterance_end_ms=N` looks at **word-timing gaps** in interim+final results (robust to background noise — it "ignores non-speech audio such as: door knocking, a phone ringing or street noise"), emits `{"type":"UtteranceEnd", "last_word_end": …}`. Requires `interim_results=true`. Recommended value **≥1000 ms** ("Interim Results are sent every 1 second, so using a value of less than 1 second will not offer any benefits"). Recommended trigger logic: act on `speech_final=true` OR an `UtteranceEnd` arriving without a preceding `speech_final`.

### 2.4 Formatting and paragraphs

- [`smart_format=true`](https://developers.deepgram.com/docs/smart-format) applies punctuation + paragraphs + entity formatting (dates, currency, phones); it "enables Deepgram's Punctuation feature." In streaming it "will attempt to format entities as they are spoken" and waits for continued non-entity speech or "3 seconds of silence" before finalizing entity formatting (`no_delay=true` opts out).
- [Paragraphs](https://developers.deepgram.com/docs/paragraphs): "paragraphs are identified based on the transcript's punctuation," and "When the Diarization feature is enabled and multiple speakers are present, paragraphs breaks are influenced by speaker changes." → **Paragraph = f(punctuation, speaker change)**, not time.

### 2.5 Graceful close

[Finalize docs](https://developers.deepgram.com/docs/finalize): `{"type":"Finalize"}` forces the server "to immediately process any unprocessed audio data and return the final transcription results," flagged with `"from_finalize": true` (not guaranteed if there's no significant buffered audio). Graceful shutdown sequence in the official examples: send `Finalize` → send `{"type":"CloseStream"}` → then `ws.close()` — "This ensures buffered audio is processed before terminating the connection, preventing transcript loss."

---

## 3. AssemblyAI Universal-Streaming

### 3.1 Immutable-transcript model (the contrarian design)

AssemblyAI deliberately rejected mutable partials: "transcriptions are immutable—the text that has already been produced will not be overwritten in future transcription responses" ([Universal-Streaming docs](https://www.assemblyai.com/docs/streaming/universal-streaming), [launch blog](https://www.assemblyai.com/blog/introducing-universal-streaming)). The blog: "every character emitted is final and never changes, and the model does this so fast, even generating subwords before completing full words." Reported latency: **~307 ms P50 word-emission** (vs 516 ms Deepgram Nova-3) and 1,012 ms P99 ([blog](https://www.assemblyai.com/blog/introducing-universal-streaming)). Lesson for us: with a fast enough confirmed-prefix pipeline, even the "finals-only" lane can feel word-by-word — but that requires ~300ms emission, not 5s.

### 3.2 Turn objects

Streaming responses are `Turn` messages containing `turn_order`, `end_of_turn` (bool), `turn_is_formatted`, `end_of_turn_confidence`, `transcript` (text so far in this turn), and `words[]` with per-word `start`/`end`/`confidence`/`word_is_final` ([API reference](https://www.assemblyai.com/docs/api-reference/streaming-api/streaming-api), [quickstart](https://www.assemblyai.com/docs/speech-to-text/universal-streaming)). "Expect several partial updates before each `end_of_turn: true`" — the turn transcript grows monotonically (immutability), and `end_of_turn: true` closes the turn (≈ paragraph unit in reference UIs).

### 3.3 End-of-turn detection (semantic + acoustic hybrid)

[Turn detection docs](https://www.assemblyai.com/docs/streaming/universal-streaming/turn-detection): two-stage — "The model predicts when speech naturally ends; if confidence exceeds `end_of_turn_confidence_threshold` and `min_turn_silence` has passed, the turn ends," with "Acoustic (silence-based) detection … as a fallback after `max_turn_silence`."

| Parameter | Default (current turn-detection page) | Note |
|---|---|---|
| `end_of_turn_confidence_threshold` | **0.4** | 0–1; higher = waits for more confidence. (Older Universal-Streaming reference documents **0.5** — [streaming API ref](https://assemblyai.com/docs/api-reference/streaming-api/streaming-api).) |
| `min_turn_silence` | **400 ms** | silence required when the semantic model is confident. (Deprecated older name: `min_end_of_turn_silence_when_confident`, default **800 ms** in the v3 reference — [migration guide](https://www.assemblyai.com/docs/streaming/migration-guides/universal-to-u3-pro-streaming.md).) |
| `max_turn_silence` | **1280 ms** | hard silence cap forcing turn end. (Older reference default: **2000 ms**.) |
| `vad_threshold` | 0.4 | speech detection confidence. |

Use-case presets from the same page: IVR/rapid exchange 160/400 ms; healthcare/legal (thoughtful pauses) threshold 0.7 with 800–3600 ms silences. Clients can force a boundary with a `ForceEndpoint` event.

### 3.4 Formatting and chunking

- `format_turns=true` → a formatted (punctuated/cased) copy of the turn arrives with `turn_is_formatted: true` ([API reference](https://assemblyai.com/docs/api-reference/streaming-api/streaming-api)). Reference pattern: render raw immutable text instantly, upgrade the turn's text when the formatted version lands.
- **Audio chunk size:** "The payload must be … between 50ms and 1000ms"; for custom audio "aim for **50–250ms frames**," with 50 ms as the low-latency recommendation ([streaming API reference](https://assemblyai.com/docs/api-reference/streaming-api/streaming-api), [Universal-Streaming docs](https://www.assemblyai.com/docs/streaming/universal-streaming)).

### 3.5 Session termination

Send a `Terminate` message before closing; the server replies with a `Termination` confirmation, and unterminated sessions auto-close (and bill) after 3 hours ([terminate guide](https://www.assemblyai.com/docs/streaming/guides/terminate_realtime_programmatically), [session errors & closures](https://www.assemblyai.com/docs/speech-to-text/universal-streaming/common-session-errors-and-closures)).

---

## 4. Azure Speech SDK streaming

### 4.1 `Recognizing` vs `Recognized` events

[How to recognize speech](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech): continuous recognition "requires you to subscribe to the `Recognizing`, `Recognized`, and `Canceled` events." `Recognizing` fires repeatedly with intermediate hypotheses (mutable); `Recognized` fires once per utterance with the final text. Session lifecycle via `SessionStarted`/`SessionStopped`/`Canceled`.

[Captioning concepts](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/captioning-concepts) is Microsoft's official display-UX doc:

- "Speech recognition results are subject to change while an utterance is still being recognized. Partial results are returned with each `Recognizing` event. As each word is processed, the Speech service re-evaluates an utterance in the new context and again returns the best result. The new result isn't guaranteed to be the same as the previous result."
- "**Punctuation of partial results isn't available.**" (matches Speechmatics' partial-quality caveat)
- "The complete and final transcription of an utterance is returned with the `Recognized` event."

### 4.2 Anti-flicker: stable partial results

Same captioning doc: `SpeechServiceResponse_StablePartialResultThreshold` (0–2147483647) = "the number of times a word has to be recognized before the Speech service returns a `Recognizing` event." Example with threshold 5 shows the partial stream collapsing from 5 noisy updates to 3 stable ones; "Requesting more stable partial results reduce the 'flickering' or changing text, but it can increase latency." This is the industry's canonical treatment of the *flicker vs latency* dial for the partial lane.

### 4.3 Segmentation (phrase boundary) knobs

- `Speech_SegmentationSilenceTimeoutMs`: silence duration that ends the current phrase and triggers `Recognized`; settable **100–5000 ms**, with **~500 ms** the service default. "Higher values generally make results longer and allow longer pauses from the speaker within a phrase, but … can combine separate phrases into a single result when set too high" ([Microsoft Q&A — segmentation property](https://learn.microsoft.com/en-us/answers/questions/1397127/speech-segmentationsilencetimeoutms-and-speech-seg), [Q&A — segmentation timeout behavior](https://learn.microsoft.com/en-us/answers/questions/2128774/speech-sdk-speech-to-text-segmentation-silence-tim)).
- `Speech_SegmentationMaximumTimeMs`: "the absolute maximum length permitted for a single spoken segment" — a **cap**, not the primary boundary driver ([GitHub issue on the two properties](https://github.com/Azure-Samples/cognitive-services-speech-sdk/issues/2740)).

So Azure's phrase boundary = silence timeout (default ~500 ms), with a max-time backstop — the model our forced 5 s commit should converge to (silence-primary, time-cap-secondary).

---

## 5. Google Cloud STT v2 streaming

- Transport: "Streaming speech recognition is available through gRPC only," with "a 25 KB limit on audio sent in the requests of a stream" per message ([v2 streaming guide](https://docs.cloud.google.com/speech-to-text/v2/docs/streaming-recognize)).
- **Chunk-size best practice (explicit):** "A 100-millisecond frame size is recommended as a good tradeoff between latency and efficiency" ([best practices](https://docs.cloud.google.com/speech-to-text/docs/v1/best-practices); the official samples use `CHUNK = RATE/10` = 100 ms — [streaming sample](https://docs.cloud.google.com/speech-to-text/docs/samples/speech-streaming-recognize)).
- Interim results: `StreamingRecognitionFeatures.interim_results` — "if set to true, interim results will be streamed to the client"; each response has at most one `is_final: true` result (the newly settled portion) plus interim results ([v2 RPC reference](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v2), [StreamingRecognitionFeatures reference](https://docs.cloud.google.com/ruby/docs/reference/google-cloud-speech-v2/latest/Google-Cloud-Speech-V2-StreamingRecognitionFeatures)).
- **`stability`** field (0.0–1.0): "Interim results may have a high stability portion that is less likely to change and a low stability portion that is very likely to change" ([v2 RPC reference](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v2)) — Google's version of the confirmed-prefix idea: a UI can render high-stability interim text in normal style and low-stability tail in dimmed style.
- Voice activity events: `enable_voice_activity_events` — "responses with voice activity speech events will be returned as they are detected" (`SPEECH_ACTIVITY_BEGIN`/`SPEECH_ACTIVITY_END`), plus `voice_activity_timeout` ([StreamingRecognitionFeatures reference](https://docs.cloud.google.com/ruby/docs/reference/google-cloud-speech-v2/latest/Google-Cloud-Speech-V2-StreamingRecognitionFeatures)).

---

## 6. Whisper-family streaming (what competitors on *our* model do)

### 6.1 UFAL `whisper_streaming` — LocalAgreement-2

[github.com/ufal/whisper_streaming](https://github.com/ufal/whisper_streaming) converts batch Whisper into a streaming system:

- **Policy:** LocalAgreement-n — "if n consecutive updates, each with a newly available audio stream chunk, agree on a prefix transcript, it is confirmed" (n=2 in practice): "we consecutively process new audio chunks, emit the transcripts that are confirmed by 2 iterations, and scroll the audio processing buffer on a timestamp of a confirmed complete sentence."
- **Step size:** `--min-chunk-size` seconds — "Minimum audio chunk size in seconds. It waits up to this time to do processing"; the reference example runs with **1 s** steps.
- **Output model:** confirmed (stable, emit) vs unconfirmed (tentative tail) — exactly the partial/final two-lane split, produced *client-side of the model* by agreement rather than by the model itself.
- **Buffer trimming:** `--buffer_trimming {sentence,segment}` + `--buffer_trimming_sec` — the rolling buffer is cut at **completed sentence or Whisper-segment boundaries**, not fixed windows; context is preserved by re-prompting with the confirmed prefix ("init prompt").
- **Latency:** "Whisper-Streaming achieves high quality and **3.3 seconds latency** on unsegmented long-form speech" (paper quoted in README).

**Implication for our live-stt:** a Whisper GPU service fed 0.5–1 s increments with LocalAgreement-2 gives a continuously-growing confirmed prefix (final lane) plus a tentative tail (partial lane) — no 5 s forced acoustic commit needed. Our current design (aggregate 5 s → transcribe → commit whole window) is the batch pattern these projects exist to eliminate.

### 6.2 whisper.cpp `stream` example

[whisper.cpp/examples/stream](https://github.com/ggml-org/whisper.cpp/tree/master/examples/stream): sliding-window mic transcription, canonical invocation `--step 500 --length 5000` — re-inference every **500 ms** over a 5 s rolling window, with overlap keep-back for context; setting `--step 0` switches to **VAD-triggered** mode (transcribe on detected speech end) ([stream.cpp source](https://github.com/ggml-org/whisper.cpp/blob/master/examples/stream/stream.cpp)). I.e., even the minimal C++ demo refreshes text twice a second; the 5000 ms is the *context window*, not the emission cadence.

### 6.3 WhisperLive (faster-whisper server)

[github.com/collabora/WhisperLive](https://github.com/collabora/WhisperLive): WebSocket client-server on faster-whisper; accepts "any cadence, any chunk size" 16 kHz PCM; optional server VAD (`use_vad`); client API exposes exactly the two lanes — `on_partial_transcript` ("In-progress segment updated") vs `on_committed_transcript` ("Segment finalized") — and emitted segments carry a `completed` flag. The trailing segment is mutable until committed; committed segments are append-only.

### 6.4 OpenAI Realtime API transcription mode

[Realtime transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription):

- Client streams audio with `input_audio_buffer.append` (base64 PCM chunks, continuous); with turn detection disabled, `input_audio_buffer.commit` manually ends a turn.
- **Events:** `conversation.item.input_audio_transcription.delta` — "newly available transcript text" (incremental, append-only within the item) — and `conversation.item.input_audio_transcription.completed` — "the final transcript for the committed item." Delta = partial lane, completed = final lane, item = turn/paragraph unit.
- Turn detection ([VAD guide](https://developers.openai.com/api/docs/guides/realtime-vad)): `server_vad` (default) with `threshold` (**default 0.5**), `prefix_padding_ms` (**default 300 ms**), `silence_duration_ms` (**default 500 ms** — "With shorter values turns will be detected more quickly"); boundary events `input_audio_buffer.speech_started`/`speech_stopped`. Alternative `semantic_vad` mode classifies *whether the user is done speaking* with an `eagerness` parameter (`low`/`medium`/`high`/`auto`). Defaults confirmed in the [Realtime client events reference](https://developers.openai.com/api/reference/resources/realtime/client-events).
- Latency/accuracy is tunable via a `delay` parameter (`minimal`/`low`/`medium`/`high`/`xhigh`) on current transcription models ([transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription)).

---

## 7. UI line-breaking & segmentation conventions

Cross-vendor synthesis of when reference UIs break lines/paragraphs — and when they don't:

| Boundary driver | Who uses it | Evidence |
|---|---|---|
| **Sentence-final punctuation from the model** | Deepgram Paragraphs; whisper_streaming buffer trim; Speechmatics diarization corrections | "paragraphs are identified based on the transcript's punctuation" ([Deepgram](https://developers.deepgram.com/docs/paragraphs)); buffer scrolled "on a timestamp of a confirmed complete sentence" ([whisper_streaming](https://github.com/ufal/whisper_streaming)); "Small corrections are applied to speaker labels based on sentence boundaries" ([Speechmatics](https://docs.speechmatics.com/speech-to-text/realtime/realtime-diarization)) |
| **Utterance/turn end (silence or semantic)** | Deepgram `speech_final`/`UtteranceEnd`; AssemblyAI `end_of_turn`; Azure `Recognized` (segmentation silence); Speechmatics `EndOfUtterance`; OpenAI VAD-committed items | Sections 1.4, 2.2–2.3, 3.3, 4.3, 6.4 above |
| **Speaker change (diarization)** | Deepgram Paragraphs + diarization; Speechmatics per-word speaker labels | "paragraphs breaks are influenced by speaker changes" ([Deepgram](https://developers.deepgram.com/docs/paragraphs)); S# labels per word ([Speechmatics](https://docs.speechmatics.com/speech-to-text/realtime/realtime-diarization)) |
| **Fixed wall-clock window** | **Nobody** | No vendor doc surveyed commits or line-breaks on elapsed time alone; time appears only as a *cap* (Speechmatics `max_delay`, Azure `Speech_SegmentationMaximumTimeMs`, AssemblyAI `max_turn_silence`) |

**Mid-utterance finals do not break lines.** Deepgram is explicit: buffer `is_final` pieces and treat only `speech_final`/`UtteranceEnd` as the utterance boundary ([docs](https://developers.deepgram.com/docs/understand-endpointing-interim-results)). Speechmatics finals merge into the running paragraph with the remainder re-emitted as a partial ([docs](https://docs.speechmatics.com/speech-to-text/realtime/output)). AssemblyAI turns grow in place until `end_of_turn` ([docs](https://www.assemblyai.com/docs/streaming/universal-streaming)).

**OS dictation behavior matches:** Apple's Speech framework returns partial hypotheses by default (`shouldReportPartialResults` — "A Boolean value that indicates whether you want intermediate results returned for each utterance. The default value of this property is `true`" — [Apple docs](https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/shouldreportpartialresults)); each callback carries the best transcription of the utterance-so-far, so text appears immediately and mutates in place until `isFinal`, with no premature line breaks. Azure's captioning guidance likewise assumes in-place mutation of the current utterance with anti-flicker damping ([captioning concepts](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/captioning-concepts)).

**Flicker control on the partial lane** (so replace-in-place doesn't look jittery): Azure `SpeechServiceResponse_StablePartialResultThreshold` (word seen N times before display) ([captioning concepts](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/captioning-concepts)); Google `stability` score for dimming the volatile tail ([v2 reference](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v2)); AssemblyAI sidesteps it entirely with immutable emission ([blog](https://www.assemblyai.com/blog/introducing-universal-streaming)); whisper_streaming sidesteps it with LocalAgreement-confirmed prefixes ([repo](https://github.com/ufal/whisper_streaming)).

---

## 8. Synthesis for our architecture

Current pipeline: desktop PCM16/WebSocket → audio-gateway (**aggregates 5 s windows**, `windowSeconds=5`, validation [5,30]) → Whisper live-stt (**forced commit every 5 s on acoustic boundaries**) → SSE → UI (**new line per commit**). Both user complaints are direct consequences: 5 s aggregation + finals-only single-lane = batchy text; commit-per-line = fragmented sentences.

| Our knob | Industry mechanism | Vendor evidence | Concrete change |
|---|---|---|---|
| **(a) Replace 5 s aggregation with continuous small-chunk forwarding** | All vendors ingest continuous small frames; aggregation is the server's job, not the transport's | Google best practice **100 ms** frames ([docs](https://docs.cloud.google.com/speech-to-text/docs/v1/best-practices)); AssemblyAI **50 ms** recommended, 50–250 ms for custom audio, 50–1000 ms accepted ([docs](https://assemblyai.com/docs/api-reference/streaming-api/streaming-api)); Speechmatics buffers ≤10 s / 500 `AddAudio` msgs with per-chunk `AudioAdded` acks ([legacy guide](https://legacy.docs.speechmatics.com/en/real-time-appliance/api-v2/api-example-usage/v4.0.0/)); OpenAI `input_audio_buffer.append` continuous ([docs](https://developers.openai.com/api/docs/guides/realtime-transcription)) | Gateway forwards PCM16 frames at **100–250 ms** cadence to live-stt; drop `windowSeconds` aggregation from the hot path (keep only as a legacy/fallback mode). The [5,30] validation range is itself the bug — the industry transport unit is *milliseconds*, and the *model step* (Whisper) is 0.5–1 s ([whisper_streaming](https://github.com/ufal/whisper_streaming), [whisper.cpp stream](https://github.com/ggml-org/whisper.cpp/tree/master/examples/stream)) |
| **(b) Two-lane partial/final event model** | Mutable partial (replace-in-place) + immutable final (append) everywhere | Speechmatics `AddPartialTranscript`/`AddTranscript` ([docs](https://docs.speechmatics.com/speech-to-text/realtime/output)); Deepgram `is_final` ([docs](https://developers.deepgram.com/docs/interim-results)); Azure `Recognizing`/`Recognized` ([docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech)); OpenAI `…transcription.delta`/`.completed` ([docs](https://developers.openai.com/api/docs/guides/realtime-transcription)); WhisperLive `on_partial_transcript`/`on_committed_transcript` ([repo](https://github.com/collabora/WhisperLive)) | live-stt emits `partial` (tentative tail, may be revised) + `final` (confirmed prefix) events over SSE; UI renders `finals + current_partial`, partial region overwritten per event, styled distinctly (dim/italic per Google `stability` precedent). Enabling our existing dormant `SpeechmaticsRealtimeTranscriptionClient`/`Streaming` path gives lane (b) for free on the SaaS route |
| **(c) Linguistic/utterance boundary commit instead of fixed 5 s acoustic commit** | Silence/VAD endpointing or semantic end-of-turn as *primary* commit driver; time only as *cap* | Speechmatics `end_of_utterance_silence_trigger` 0–2 s + `max_delay` cap ([docs](https://docs.speechmatics.com/speech-to-text/realtime/end-of-turn)); Deepgram `endpointing` (default 10 ms) + `utterance_end_ms` ≥1 s ([docs](https://developers.deepgram.com/docs/endpointing)); AssemblyAI semantic threshold 0.4 + 400/1280 ms silences ([docs](https://www.assemblyai.com/docs/streaming/universal-streaming/turn-detection)); Azure silence ~500 ms default + max-time cap ([Q&A](https://learn.microsoft.com/en-us/answers/questions/1397127/speech-segmentationsilencetimeoutms-and-speech-seg)); whisper_streaming LocalAgreement-2 confirmed prefix + sentence-boundary buffer trim ([repo](https://github.com/ufal/whisper_streaming)) | live-stt: run VAD; commit final on **silence ≥0.8–1.2 s** or on LocalAgreement-2 confirmed sentence boundary; keep a **max-delay cap of 2–4 s** so finals never lag words by more than that (Speechmatics semantics) — the 5 s timer becomes the *upper bound*, never the trigger identity |
| **(d) Speaker-change-driven paragraph breaks** | Paragraph = utterance end ∧ (speaker change ∨ sentence punctuation) | Deepgram: "paragraphs breaks are influenced by speaker changes" ([docs](https://developers.deepgram.com/docs/paragraphs)); Speechmatics per-word `S#` labels with sentence-boundary corrections ([docs](https://docs.speechmatics.com/speech-to-text/realtime/realtime-diarization)) | UI breaks a paragraph only on: utterance-end event **and** (speaker label changed **or** sentence-final punctuation). Consecutive finals from the same speaker mid-sentence concatenate with a space into the current paragraph (Deepgram buffer pattern) |
| **(e) Graceful EndOfStream with bounded wait for final ack** | Explicit end-of-audio message → server flushes finals → terminal ack → then close | Speechmatics `EndOfStream(last_seq_no)` → drain `AddTranscript` → `EndOfTranscript` → "client can safely disconnect immediately" ([legacy guide](https://legacy.docs.speechmatics.com/en/real-time-appliance/api-v2/speech-api-guide/v3.7.0/)); Deepgram `Finalize` → `from_finalize:true` → `CloseStream` → close ([docs](https://developers.deepgram.com/docs/finalize)); AssemblyAI `Terminate` → `Termination` ack ([docs](https://www.assemblyai.com/docs/streaming/guides/terminate_realtime_programmatically)); OpenAI `input_audio_buffer.commit` ([docs](https://developers.openai.com/api/docs/guides/realtime-transcription)) | Fixes our socket-close-error bug: on stop, gateway sends end-of-audio upstream, then **waits bounded (5–10 s, ≥ max_delay + margin)** for the terminal message (`EndOfTranscript` on the Speechmatics path; a flush-complete event on the internal path) before closing; timeout → log + close, never close-first |

---

## 9. Recommended parameter defaults (vendor-anchored)

| Parameter (ours) | Recommended default | Vendor anchor |
|---|---|---|
| Transport audio frame (desktop→gateway→live-stt) | **100 ms** (accept 50–250 ms) | Google "100-millisecond frame size … good tradeoff" ([best practices](https://docs.cloud.google.com/speech-to-text/docs/v1/best-practices)); AssemblyAI 50 ms rec., 50–250 ms custom ([API ref](https://assemblyai.com/docs/api-reference/streaming-api/streaming-api)) |
| Whisper inference step (live-stt) | **0.5–1.0 s** per LocalAgreement iteration | whisper_streaming `--min-chunk-size 1` ([repo](https://github.com/ufal/whisper_streaming)); whisper.cpp `--step 500` ([example](https://github.com/ggml-org/whisper.cpp/tree/master/examples/stream)) |
| Partial emission cadence target (UI) | **≤500 ms** (aspirational ~300 ms) | Speechmatics partials "less than 500 milliseconds" ([docs](https://docs.speechmatics.com/features/realtime-latency)); AssemblyAI ~307 ms P50 ([blog](https://www.assemblyai.com/blog/introducing-universal-streaming)); Deepgram interims every 1 s = industry slow end ([docs](https://developers.deepgram.com/docs/understanding-end-of-speech-detection)) |
| Final max-delay cap (word spoken → final committed) | **2.0 s** (range 0.7–4) | Speechmatics `max_delay=2` "for most use cases … captioning" with ~1% degradation, `max_delay_mode=flexible` ([docs](https://docs.speechmatics.com/features/realtime-latency)) |
| Utterance-end silence trigger (meeting transcription) | **0.8–1.2 s** | Speechmatics "0.8-1.2s … better for dictation" ([docs](https://docs.speechmatics.com/speech-to-text/realtime/end-of-turn)); Deepgram `utterance_end_ms` ≥1000 ms ([docs](https://developers.deepgram.com/docs/understanding-end-of-speech-detection)); AssemblyAI `max_turn_silence` 1280 ms ([docs](https://www.assemblyai.com/docs/streaming/universal-streaming/turn-detection)); Azure/OpenAI ~500 ms defaults are conversational-agent tuned — too aggressive for meetings |
| Hard segment cap (safety) | **15–30 s** | Azure `Speech_SegmentationMaximumTimeMs` cap concept ([issue](https://github.com/Azure-Samples/cognitive-services-speech-sdk/issues/2740)); whisper_streaming `--buffer_trimming_sec` ([repo](https://github.com/ufal/whisper_streaming)) — our old 5 s window is repurposed here, as a cap |
| Speechmatics SaaS path (`Streaming` config) | `enable_partials=true`, `max_delay=2`, `max_delay_mode=flexible`, `end_of_utterance_silence_trigger=1.0`, `diarization=speaker` | Sections 1.2, 1.4, 1.5 |
| Shutdown wait for terminal ack | **5–10 s** bounded (≥ max_delay + flush margin) | Speechmatics `EndOfStream`→`EndOfTranscript` contract ([guide](https://legacy.docs.speechmatics.com/en/real-time-appliance/api-v2/speech-api-guide/v3.7.0/)); Deepgram `Finalize`+`CloseStream` ([docs](https://developers.deepgram.com/docs/finalize)) |
| Partial-lane flicker damping | Optional: require 2× agreement before showing a word (or dim unstable tail) | Azure `SpeechServiceResponse_StablePartialResultThreshold` ([docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/captioning-concepts)); Google `stability` ([ref](https://docs.cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v2)); LocalAgreement-2 ([repo](https://github.com/ufal/whisper_streaming)) |

**Known doc-version caveat:** AssemblyAI's turn-detection defaults differ between doc generations — current turn-detection page: threshold 0.4 / `min_turn_silence` 400 ms / `max_turn_silence` 1280 ms ([turn detection](https://www.assemblyai.com/docs/streaming/universal-streaming/turn-detection)); older v3 streaming reference: threshold 0.5 / `min_end_of_turn_silence_when_confident` 800 ms / `max_turn_silence` 2000 ms ([streaming API ref](https://assemblyai.com/docs/api-reference/streaming-api/streaming-api), [migration guide](https://www.assemblyai.com/docs/streaming/migration-guides/universal-to-u3-pro-streaming.md)). Both cited so the doc survives their next rename.
