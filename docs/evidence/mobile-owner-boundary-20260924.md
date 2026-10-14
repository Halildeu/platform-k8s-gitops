# Identical-audio owner comparison — 24 September 2026

## Result

The reported `Mehmet. Bütçe ...` owner loss was reproduced through both pinned
client-source encoders against the real TEST gateway. For each audio fixture,
the mobile and desktop profiles produced identical provider final text,
identical verified analysis input and identical last action items.

This is **not a product acceptance pass**. The normal fixture leaves Mehmet's
action unassigned. The run completed successfully as a measurement.

Run: https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35971201863

Measured harness commit: `4178794d7216b3c12073baedd9446e4887934118`.
Artifact: `faz24-platform-desktop-token-evidence-35971201863-1`.
Execution: 07:43:51–07:57:14 UTC. The original lifecycle acceptance precedes
the four comparisons; total workflow duration is not live analysis latency.

## Paired observations

| Synthetic recording | Profile | Last actions | Owners | Text boundary | All dates |
| --- | --- | --- | --- | --- | --- |
| Normal, 22.155 s | Mobile source | 2 | Zeynep, null | `Mehmet. Bütçe tablosunu ...` | 2026 |
| Normal, 22.155 s | Desktop source | 2 | Zeynep, null | `Mehmet. Bütçe tablosunu ...` | 2026 |
| Names paused 1.8 s, 25.990 s | Desktop source | 2 | Zeynep, Mehmet | `Mehmet bütçe tablosunu ...` | 2026 |
| Names paused 1.8 s, 25.990 s | Mobile source | 2 | Zeynep, Mehmet | `Mehmet bütçe tablosunu ...` | 2026 |

All four returned the expected presentation decision. All 14 captured analysis
snapshots arrived before EOF, and all 14 input prefixes matched the server's
`live_cursor.source_length` and `source_sha256`. `active_indices` in each
snapshot records the analysis window; a verified full source prefix is not a
claim to have captured the exact internal LLM prompt or raw model draft.

There were **zero `rejected_claims` across the 14 snapshots**, including zero
`action_owner` rejections. This run therefore does not support the earlier
claim that the guard removed Mehmet. It shows an unassigned action returned
without a reported rejection. A raw pre-guard model draft was not captured.

Normal full source SHA-256, both profiles:
`5a889d11d1ab70acec1ddd8289464f795a7e9ae011091b1df4a776711ca8d7e3`.

Paused full source SHA-256, both profiles:
`b63456c26441182fce0e894bbd4feb95a68606dd71ccdecc1f6f5b3937bb86cd`.

The paused fixture performing better also refutes a simple assumption that a
longer name pause necessarily causes the split. The 2016 year error from the
phone was **not reproduced** by these synthetic recordings; it remains open.

## Timing (seconds from first audio send)

| Recording/profile | First action | Last two-action result | Speech ended | EOF sent |
| --- | ---: | ---: | ---: | ---: |
| Normal/mobile | 32.197 | 53.395, Mehmet null | 22.155 | 67.241 |
| Normal/desktop | 32.254 | 53.052, Mehmet null | 22.155 | 67.251 |
| Paused/desktop | 33.010 | 68.914, both owners | 25.991 | 71.050 |
| Paused/mobile | 32.896 | 69.443, both owners | 25.991 | 71.053 |

The complete paused result arrived 42.923/43.452 seconds after speech ended,
while recording remained active. These are two measurements, not a latency
guarantee. Individual analysis `elapsed_ms` values were roughly 5.7–21.1 s;
they do not include all source batching, scheduling, earlier analyses or delivery.
All snapshots reported backend/model metadata for `qwen3.8:27b`.

## Controls and limits

- Mobile source: `c7ec44364e01c27816094e047a6a8d9f64fb8d9a`.
- Desktop source: `59acb4af59b748261d51907dcaa36a8954443730`.
- Actual source functions encoded the fixed PCM. Their binary frames were
  byte-identical before the common replay timestamp rebasing.
- Same temporary TEST persona, fresh synthetic meetings, no client context terms.
- Gateway image before/after every case:
  `sha256:4e1f4431bd7ef7f78cd1cc934b8472ce6dd9ac84675dad2a9564dfe309ac4307`.
- Gateway pod UID remained `41aad260-3466-445a-86bf-386999ee288e`.
- Read-only runtime checks returned max delay `1.0`, segment window `5`, minimum
  live-analysis interval `15000` ms, live analysis enabled `true`.
- No punctuation, delay, prompt, model, deployed workload or application settings
  were changed. The existing TEST authentication ceremony restored direct grants,
  deleted its temporary user and removed its token file (diagnostic receipt).
- All four recordings returned drained and HTTP finish confirmation.
- The workflow's original realtime lifecycle/durable acceptance also passed.
- No installed APK/Electron, physical microphone/resampling or app UI was tested.
  Native client authentication differences and participant dictionaries were not
  compared. This is a source-encoder/public-gateway comparison, not full app parity.
- Only gateway-delivered final events were captured, not Speechmatics' complete
  native wire protocol. Provider partial revisions and word alternatives were not
  captured. AI deployment code identity was not independently attested by this
  harness; identical model labels alone do not attest a code version.

## Implications for the fix

This evidence localizes the reproduced loss beyond the client binary encoder:
the detached name is already in the gateway text and the identical analysis
input. It does not establish when the historical regression began. The prior
word-per-row UI regression and this semantic ownership problem remain distinct.
There is still no verified last-good **live phone owner** version to bisect.

The same-sentence-only ownership approach must be reconsidered: a provider
punctuation boundary is not reliable evidence of a new semantic subject. A
candidate alternative is ownership supported by multiple adjacent source spans,
with explicit speaker/time/context checks and preserved source references.
This is a design candidate, not a deployed fix; it needs negative tests for
speaker changes, unrelated name mentions and conflicting owners. Evaluating a
different STT engine with the same recordings is another option if segmentation
quality remains inadequate. Blind period removal or global punctuation tuning
is not justified by these four measurements.

Next acceptance must reproduce the normal fixture failure before a change and
retain both correct owners afterward, without changing the source text or losing
citation mapping. Real sentence boundaries, conflicting context and desktop/web
behavior require regression checks. The phone case and the year recognition
issue cannot be closed on this report alone.

## Evidence file hashes

| File | SHA-256 |
| --- | --- |
| owner-comparison-normal-desktop.json | `02ad7279e5ccae96e00c053f95f0ed9f27710c9c35fb33470c7961f6b95fbbfd` |
| owner-comparison-normal-mobile.json | `6ef1c04071b07dd618688f815f2296bf34253d06bdc3cbab6a04ee1603a7f44d` |
| owner-comparison-paused-desktop.json | `548e0d4b77cada603db24c12b31aec351418ebfc4f3d15efbed1ec8859ef8028` |
| owner-comparison-paused-mobile.json | `60c0c9acef7a4ebc3b4cad1b0012aa55ec8915681f21f426be43ae266b92143f` |
