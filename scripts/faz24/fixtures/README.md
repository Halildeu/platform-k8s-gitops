# Faz 24 Speechmatics acceptance fixture

`speechmatics-realtime-tr-v1.wav` is synthetic Turkish speech generated with the
macOS `Yelda` voice. It contains no personal data and is used only by the
platform-test Speechmatics realtime lifecycle acceptance.

Contract: mono, 16 kHz, signed 16-bit little-endian PCM WAV. The workflow never
copies the fixture into the evidence artifact; it records only stream counters,
latencies, keyword-match count, and durable read-back metadata.

Expected SHA-256:
`a759fd250937a70c4a780c8e6118f0bd5f4ff5f68b40f5d007bbae5bdc08775f`.

The optional `require_live_analysis` product gate uses the existing
`meeting-speaker-tr-v1/two-speaker-tr.wav` instead. Its checked-in reference
contains explicit accepted decisions and assigned actions, including keeping
the budget unchanged, testing before release, and preparing the test report.
The 76.696s two-voice synthetic recording is streamed at realtime pace; no
microphone, human identity or real meeting content is used.

Audio SHA256: `702c3a94e34ca09915237e3fabf11a037602514bb93cec13555ecd3ab7fe2676`.
Reference SHA256 (LF): `8b1c2807dbccdef85f9c6f44c16e48c88fca8e5abba054c32af521627bf02204`.
The helper verifies both before streaming. A summary, decision and action must
arrive in one verified snapshot before EOF; saved-result requirements remain
unchanged. The old keyword fixture is retained for the default lifecycle mode.
