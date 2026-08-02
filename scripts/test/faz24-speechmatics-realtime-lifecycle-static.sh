#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HELPER="${ROOT}/scripts/faz24/run_speechmatics_realtime_lifecycle_acceptance.py"
RUNNER="${ROOT}/scripts/faz24/run-platform-desktop-token-evidence-chain.sh"
WORKFLOW="${ROOT}/.github/workflows/faz24-platform-desktop-token-evidence.yml"
FIXTURE="${ROOT}/scripts/faz24/fixtures/speechmatics-realtime-tr-v1.wav"

python3 -m py_compile "${HELPER}"
python3 "${HELPER}" --help >/dev/null
python3 - "${FIXTURE}" <<'PY'
import hashlib
import sys
import wave

expected = "a759fd250937a70c4a780c8e6118f0bd5f4ff5f68b40f5d007bbae5bdc08775f"
assert hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest() == expected
with wave.open(sys.argv[1], "rb") as audio:
    assert audio.getnchannels() == 1
    assert audio.getframerate() == 16000
    assert audio.getsampwidth() == 2
    assert 8 <= audio.getnframes() / audio.getframerate() <= 45
PY

grep -q 'RUN_SPEECHMATICS_REALTIME' "${RUNNER}"
grep -q 'run_speechmatics_realtime' "${WORKFLOW}"
grep -q 'durableApiReadBackProven' "${HELPER}"
grep -q 'transcriptIncluded.*False' "${HELPER}"
grep -q 'audioIncluded.*False' "${HELPER}"

if grep -Eq 'print\(.+(token|transcript_fragments|pcm)' "${HELPER}"; then
  echo "ERROR: helper may print private runtime material" >&2
  exit 1
fi

echo "Faz 24 Speechmatics realtime lifecycle static checks passed"
