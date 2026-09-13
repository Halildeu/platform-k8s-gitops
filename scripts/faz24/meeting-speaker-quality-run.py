import asyncio
import hashlib
import importlib.util
import json
import os
import ssl
import struct
import sys
import time
import unicodedata
import urllib.parse
import wave
from pathlib import Path
import jiwer
import websockets
from pyannote.core import Annotation, Segment
from pyannote.metrics.diarization import DiarizationErrorRate

spec = importlib.util.spec_from_file_location('lifecycle', str(Path(os.environ.get('QUALITY_REPO', Path(__file__).resolve().parents[2])) / 'scripts/faz24/run_speechmatics_realtime_lifecycle_acceptance.py'))
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
ROOT = Path(os.environ['QUALITY_FIXTURES'])
EXPECTED = '702c3a94e34ca09915237e3fabf11a037602514bb93cec13555ecd3ab7fe2676'
EXPECTED_REFERENCE = '8b1c2807dbccdef85f9c6f44c16e48c88fca8e5abba054c32af521627bf02204'

def normalized(text):
    text = unicodedata.normalize('NFKC', text).replace('I', '\u0131').replace('\u0130', 'i').lower()
    return ' '.join(''.join(' ' if unicodedata.category(c).startswith('P') else c for c in text).split())

def validate_fixture():
    audio = ROOT / 'two-speaker-tr.wav'
    reference_bytes = (ROOT / 'reference.json').read_bytes()
    if hashlib.sha256(reference_bytes).hexdigest() != EXPECTED_REFERENCE:
        raise ValueError('only-pinned-synthetic-reference')
    reference = json.loads(reference_bytes)
    if hashlib.sha256(audio.read_bytes()).hexdigest() != EXPECTED or reference.get('sha256') != EXPECTED:
        raise ValueError('only-pinned-synthetic-fixture')
    with wave.open(str(audio), 'rb') as wav:
        if (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) != (1, 16000, 2):
            raise ValueError('invalid-fixture-format')
    return reference

def annotations(reference, finals):
    truth, hypothesis = Annotation(), Annotation()
    for ti, turn in enumerate(reference['turns']):
        for wi, word in enumerate(turn['words']):
            if word['end'] > word['start']:
                truth[Segment(word['start'], word['end']), f'{ti}:{wi}'] = turn['speaker']
    for fi, event in enumerate(finals):
        attribution = event.get('speakerAttribution')
        if not attribution:
            continue
        offset = event['source_start_sample'] / 16000
        for wi, turn in enumerate(attribution['turns']):
            if turn['speaker'] == 'UU' or turn['endMs'] <= turn['startMs']:
                continue
            hypothesis[Segment(offset + turn['startMs']/1000, offset + turn['endMs']/1000), f'{fi}:{wi}'] = attribution['scope'] + ':' + turn['speaker']
    return truth, hypothesis

async def stream(token, session):
    audio = ROOT / 'two-speaker-tr.wav'
    assert hashlib.sha256(audio.read_bytes()).hexdigest() == EXPECTED
    with wave.open(str(audio), 'rb') as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) == (1, 16000, 2)
        pcm = wav.readframes(wav.getnframes())
    ready, drained = asyncio.Event(), asyncio.Event()
    finals, partials = [], []
    metrics = {'audioAcks': 0, 'eofAck': False, 'drained': False, 'errors': 0}
    started = time.monotonic()
    async with websockets.connect(f'wss://testai.acik.com/api/v1/audio-gateway/sessions/{session}/stream',
            ssl=ssl.create_default_context(), additional_headers={'Authorization': 'Bearer ' + token},
            open_timeout=30, max_size=1048576) as socket:
        async def receive():
            async for raw in socket:
                if not isinstance(raw, str): continue
                e = json.loads(raw)
                kind = e.get('type')
                if kind == 'ready': ready.set()
                elif kind == 'audio_ack': metrics['audioAcks'] += 1
                elif kind == 'partial': partials.append(time.monotonic() - started)
                elif kind == 'final':
                    e['_receivedMs'] = round((time.monotonic() - started) * 1000)
                    finals.append(e)
                elif kind == 'eof_ack': metrics['eofAck'] = True
                elif kind == 'drained': metrics['drained'] = True; drained.set(); return
                elif kind == 'error': metrics['errors'] += 1; raise RuntimeError('gateway-stream-error')
        receiver = asyncio.create_task(receive())
        try:
            await asyncio.wait_for(ready.wait(), 30)
            await socket.send(json.dumps({'type': 'context', 'terms': []}))
            started = time.monotonic()
            for seq, offset in enumerate(range(0, len(pcm), 3200)):
                if receiver.done(): await receiver
                chunk = pcm[offset:offset+3200]
                await socket.send(struct.pack('>BQQH', 1, seq, round(time.time() * 1000), len(chunk)) + chunk)
                await asyncio.sleep(max(0, (offset + len(chunk)) / 32000 - (time.monotonic() - started)))
            await socket.send('{"type":"eof"}')
            await asyncio.wait_for(drained.wait(), 40)
            await receiver
        finally:
            if not receiver.done(): receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
    metrics.update({'finalEvents': len(finals), 'partialEvents': len(partials),
        'firstPartialMs': round(partials[0] * 1000) if partials else None,
        'firstFinalMs': finals[0]['_receivedMs'] if finals else None})
    return finals, metrics

async def main():
    token = json.load(sys.stdin)['token']
    phase = sys.argv[1]
    assert phase in ('before', 'after')
    reference = validate_fixture()
    statuses = {}
    common = dict(base_url='https://testai.acik.com', token=token, timeout_seconds=30, statuses=statuses)
    meeting, session, started_at = api.create_lifecycle(**common)
    print(json.dumps({'stage':'started', 'phase':phase, 'meetingId':meeting, 'sourceSessionId':session}), flush=True)
    try:
        finals, metrics = await stream(token, session)
    finally:
        finished, canonical = api.finish_lifecycle(**common, meeting_id=meeting, session_id=session, started_at=started_at)
    finish_observed = time.monotonic()
    print(json.dumps({'stage':'stream-finished', 'phase':phase, 'metrics':metrics,
        'attributedFinals':sum(bool(e.get('speakerAttribution')) for e in finals)}), flush=True)
    ref_text = normalized(' '.join(t['text'] for t in reference['turns']))
    hyp_text = normalized(' '.join(e['text'] for e in finals))
    words = jiwer.process_words(ref_text, hyp_text)
    truth, hypothesis = annotations(reference, finals)
    attributed = sum(bool(e.get('speakerAttribution')) for e in finals)
    der = DiarizationErrorRate(collar=0.25, skip_overlap=False)(truth, hypothesis, detailed=True)
    zero_collar_der = DiarizationErrorRate(collar=0, skip_overlap=False)(truth, hypothesis, detailed=True)
    durable = api.durable_readback(**common, meeting_id=meeting, canonical_session_id=canonical, poll_timeout_seconds=600)
    result_wait_ms = round((time.monotonic() - finish_observed) * 1000)
    _, page = api.http_json(base_url=common['base_url'], token=token, method='GET',
        path='/api/v1/admin/transcripts?' + urllib.parse.urlencode({'sessionId':canonical,'page':0,'size':200}),
        expected={200}, timeout_seconds=30)
    rows = page.get('content', [])
    stored = [r.get('speakerAttribution') for r in rows if r.get('speakerAttribution')]
    _, reopened = api.http_json(base_url=common['base_url'], token=token, method='GET',
        path='/api/v1/admin/transcripts?' + urllib.parse.urlencode({'sessionId':canonical,'page':0,'size':200}),
        expected={200}, timeout_seconds=30)
    report = {'schema':'meeting-speaker-quality-synthetic-v1', 'phase':phase, 'kind':'synthetic-TTS-privileged-TEST-persona',
        'fixtureSha256':EXPECTED,'referenceSha256':EXPECTED_REFERENCE,'meetingId':meeting,'sourceSessionId':session,'canonicalSessionId':canonical,
        'sessionFinished':finished,'metrics':metrics,'wer':words.wer,'refWords':len(ref_text.split()),
        'postFinishResultWaitMs':result_wait_ms,
        'wordSubstitutions':words.substitutions,'wordDeletions':words.deletions,'wordInsertions':words.insertions,
        'normalization':'NFKC, Turkish lowercase, punctuation to spaces, whitespace collapsed',
        'speakerAttributedFinals':attributed,'storedAttributedSegments':len(stored),
        'speakerMetadataExactReopen':rows == reopened.get('content'),
        'speakerMetadataExactStreamToStore': sorted(json.dumps(e['speakerAttribution'], sort_keys=True) for e in finals if e.get('speakerAttribution')) == sorted(json.dumps(a, sort_keys=True) for a in stored),
        'syntheticDER':dict(der),'derReference':reference['derReference'],'collarSeconds':0.25,'skipOverlap':False,
        'syntheticDERZeroCollar':dict(zero_collar_der),
        'durable':durable,'statuses':statuses,'containsRealAudio':False,'containsCredentials':False}
    with Path(os.environ['QUALITY_REPORT']).open('x') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print(json.dumps({'stage':'failed','errorClass':type(error).__name__,
            'code':str(error) if isinstance(error, api.AcceptanceError) else 'details-suppressed'}), flush=True)
        sys.exit(1)
