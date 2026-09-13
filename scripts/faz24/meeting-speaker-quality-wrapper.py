import argparse
import io
import json
import os
import runpy
import stat
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--token-file', required=True)
parser.add_argument('--audio-file', required=True)
parser.add_argument('--output-file', required=True)
parser.add_argument('--base-url', required=True)
parser.add_argument('--durable-timeout-seconds')
args = parser.parse_args()
if args.base_url != 'https://testai.acik.com':
    raise ValueError('test-environment-required')
token = Path(args.token_file)
if stat.S_IMODE(token.stat().st_mode) != 0o600:
    raise ValueError('private-token-file-required')
phase = os.environ['QUALITY_PHASE']
if Path(args.audio_file).resolve() != (Path(os.environ['QUALITY_FIXTURES']) / 'two-speaker-tr.wav').resolve():
    raise ValueError('pinned-fixture-path-required')
report = Path(args.output_file).with_name('quality-report.json')
if report.exists():
    raise ValueError('quality-report-already-exists')
os.environ['QUALITY_REPORT'] = str(report)
sys.stdin = io.StringIO(json.dumps({'token': token.read_text().strip()}))
sys.argv = ['quality-run', phase]
try:
    runpy.run_path(str(Path(__file__).with_name('meeting-speaker-quality-run.py')), run_name='__main__')
finally:
    if report.exists():
        data = json.loads(report.read_text())
        if os.environ.get('QUALITY_BROWSER_WAIT'):
            ready = Path(args.output_file).with_name('browser-ready.json')
            done = ready.with_name('browser-result.json')
            ready.write_text(json.dumps({'meetingId': data['meetingId']}))
            print(json.dumps({'stage': 'browser-ready', 'meetingId': data['meetingId']}), flush=True)
            deadline = time.monotonic() + min(int(os.environ['QUALITY_BROWSER_WAIT']), 300)
            while not done.exists() and time.monotonic() < deadline:
                time.sleep(2)
            data['browser'] = json.loads(done.read_text()) if done.exists() else {'status': 'timeout'}
        gates = {
            'sessionFinished': data['sessionFinished'],
            'terminalDrain': data['metrics']['drained'] and data['metrics']['eofAck'],
            'noStreamErrors': data['metrics']['errors'] == 0,
            'durableResult': data['durable']['usableProductResult'],
            'exactSourceReopen': data['durable']['canonicalSourceReadBackProven'],
            'sameResultReopen': data['durable']['sameResultReopened'],
        }
        if phase == 'after':
            gates.update({
                'speakerFinals': data['speakerAttributedFinals'] == data['metrics']['finalEvents'] > 0,
                'speakerStored': data['storedAttributedSegments'] == data['metrics']['finalEvents'] > 0,
                'speakerReopen': data['speakerMetadataExactReopen'],
                'speakerStreamToStore': data['speakerMetadataExactStreamToStore'],
                'syntheticWordErrorGate': data['wer'] <= 0.10,
                'syntheticSpeakerErrorGate': data['syntheticDER']['diarization error rate'] <= 0.30,
            })
        if os.environ.get('QUALITY_BROWSER_WAIT'):
            gates['browserJourney'] = data['browser']['status'] == 'pass'
        data['gates'] = gates
        data['status'] = 'pass' if all(gates.values()) else 'fail'
        Path(args.output_file).write_text(json.dumps(data, indent=2))
        if data['status'] != 'pass': sys.exit(1)
