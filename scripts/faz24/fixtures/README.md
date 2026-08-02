# Faz 24 Speechmatics acceptance fixture

`speechmatics-realtime-tr-v1.wav` is synthetic Turkish speech generated with the
macOS `Yelda` voice. It contains no personal data and is used only by the
platform-test Speechmatics realtime lifecycle acceptance.

Contract: mono, 16 kHz, signed 16-bit little-endian PCM WAV. The workflow never
copies the fixture into the evidence artifact; it records only stream counters,
latencies, keyword-match count, and durable read-back metadata.

Expected SHA-256:
`a759fd250937a70c4a780c8e6118f0bd5f4ff5f68b40f5d007bbae5bdc08775f`.
