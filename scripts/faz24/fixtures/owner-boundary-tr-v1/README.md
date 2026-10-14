# Synthetic owner/date comparison, 24 September 2026

These recordings are generated Turkish speech (Microsoft Tolga, local Windows
SAPI). They are not a user voice recording. `normal.xml` and `paused.xml` contain
the exact synthesis input. The paused variant adds 1800 ms after both names.
Dates are spoken as words, including "iki bin yirmi altı" (2026).

Both contain one decision (online presentation on 28 September 2026 at 14:00)
and two assignments: Zeynep prepares the presentation by 25 September 2026 17:00;
Mehmet checks the budget by 26 September 2026 12:00.

`manifest.json` pins the WAV files and audio format. `client-wire.json` pins
the actual mobile ForegroundStream and desktop frame-encoder source commits
and source hashes used to produce the `.wire` files. For each recording the
two profiles are byte-identical, including the fixed capture-time baseline.
Each wire payload reconstructs the corresponding WAV PCM exactly. At replay
only the capture timestamps are rebased to the current wall clock, identically
for either source profile. Samples, sequence and packet sizes are preserved.

This isolates source encoding through the real public TEST gateway. It does
not launch the installed APK/Electron, test microphones/resamplers, or prove
application UI acceptance. The same temporary TEST persona is used for both
profiles; native client authentication differences are outside this test.

The harness creates new empty synthetic meetings and supplies no client
context terms. Shared STT settings, source text, AI prompt, model, workloads,
and installed applications are not modified. Public final events and SSE
analysis snapshots are captured only for the newly-created synthetic meetings.
A source prefix is called verified ONLY when its hash/length matches the
server's `live_cursor`. A reconstructed prefix without that match is not
reported as the exact analysis input. Retained actions, rejections and source
references remain separate from the provider final text.

The original recorder acceptance still runs first. Its temporary user, role,
direct-grant and credential cleanup remains unchanged. The four additional
cases mint fresh access tokens for that same temporary identity and close
each recording through the standard lifecycle. No acceptance pass is inferred
from the probe merely completing: owners/dates and latency require inspection.
