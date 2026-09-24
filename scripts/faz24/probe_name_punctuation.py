"""Compare provider punctuation on pinned synthetic Turkish speech, without deployment.

The TEST Speechmatics key stays in process memory on the existing acceptance runner.
Only counts, hashes and timings are emitted; exceptions never echo provider responses.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import re
import subprocess
import time
import wave
from pathlib import Path

FIXTURE = Path(__file__).parent / 'fixtures/name-punctuation-tr-v1/audio.wav'
FIXTURE_SHA = '7d46bed52c4dc8773da74423fbe0aa37586e6ea77fe436f08a5fd707da7435ca'
LONG_FIXTURE = Path(__file__).parent / 'fixtures/name-punctuation-tr-long-pauses-v1/audio.wav'
LONG_FIXTURE_SHA = 'edec20595373433ccb5e2df5f7682ee6ade9d9db2198e21b330891a358959d84'
ENDPOINT = 'wss://eu2.rt.speechmatics.com/v2/tr'


def metrics(text):
    text = re.sub(r'\s+', ' ', text).strip()
    names = ('Zeynep', 'Mehmet', 'Ayşe')
    return {
        'namesFound': sum(bool(re.search(r'\b' + name + r'\b', text, re.I)) for name in names),
        'nameFullStops': sum(bool(re.search(r'\b' + name + r'\s*[.!?…]', text, re.I)) for name in names),
        'intactOwnerTasks': sum(bool(re.search(pattern, text, re.I)) for pattern in (
            r'Zeynep\s+sunum dosyasını hazırlayacak',
            r'Mehmet\s+bütçe tablosunu kontrol edecek',
            r'Ayşe\s+test raporunu hazırlayacak',
        )),
        'sentenceTerminators': len(re.findall(r'(?:verdik|hazırlayacak|edecek)\s*[.!?…]', text, re.I)),
        'transcriptSha256': hashlib.sha256(text.encode()).hexdigest(),
        'characters': len(text),
    }


def fixture_pcm(path=FIXTURE, expected_sha=FIXTURE_SHA):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError('fixture-identity')
    with wave.open(str(path), 'rb') as wav:
        if (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) != (1, 16000, 2):
            raise ValueError('fixture-format')
        return wav.readframes(wav.getnframes())


async def measure(key, pcm, sensitivity, delay):
    import websockets
    ready, ended, acknowledged = asyncio.Event(), asyncio.Event(), asyncio.Event()
    finals, first_final, last_ack, sent = [], None, 0, 0
    start, ready_time = time.monotonic(), None
    async with websockets.connect(ENDPOINT, additional_headers={'Authorization': 'Bearer ' + key},
                                  open_timeout=20, close_timeout=5, max_size=1048576) as socket:
        async def receive():
            nonlocal first_final, last_ack, ready_time
            async for raw in socket:
                event = json.loads(raw)
                kind = event.get('message')
                if kind == 'Error':
                    raise RuntimeError('provider-error')
                if kind == 'RecognitionStarted':
                    ready_time = time.monotonic()
                    ready.set()
                if kind == 'AudioAdded':
                    last_ack = event['seq_no']
                    acknowledged.set()
                if kind == 'AddTranscript':
                    first_final = first_final or time.monotonic()
                    finals.append(event.get('metadata', {}).get('transcript', ''))
                if kind == 'EndOfTranscript':
                    ended.set()
                    break
        receiver = asyncio.create_task(receive())
        try:
            await socket.send(json.dumps({'message': 'StartRecognition',
                'audio_format': {'type': 'raw', 'encoding': 'pcm_s16le', 'sample_rate': 16000},
                'transcription_config': {'language': 'tr', 'diarization': 'speaker', 'enable_partials': True,
                    'max_delay': delay, 'max_delay_mode': 'flexible',
                    'punctuation_overrides': {'sensitivity': sensitivity}}}))
            await asyncio.wait_for(ready.wait(), 30)
            audio_start = time.monotonic()
            for offset in range(0, len(pcm), 3200):
                await socket.send(pcm[offset:offset + 3200])
                sent += 1
                await asyncio.sleep(max(0, audio_start + sent * .1 - time.monotonic()))
            async def all_ack():
                while last_ack < sent:
                    acknowledged.clear()
                    await acknowledged.wait()
            await asyncio.wait_for(all_ack(), 10)
            await socket.send(json.dumps({'message': 'EndOfStream', 'last_seq_no': last_ack}))
            await asyncio.wait_for(ended.wait(), 30)
            await receiver
            return {'sensitivity': sensitivity, 'maxDelay': delay, 'finalEvents': len(finals),
                    'audioAcknowledged': last_ack == sent, 'endOfTranscript': ended.is_set(),
                    'readySeconds': round(ready_time - start, 3),
                    'firstFinalSeconds': round(first_final - audio_start, 3) if first_final else None,
                    **metrics(' '.join(finals))}
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)


async def main(comparison_round='coarse'):
    pcm = fixture_pcm()
    long_pcm = fixture_pcm(LONG_FIXTURE, LONG_FIXTURE_SHA)
    # Read only this already-authorized TEST secret; never shell-expand or print it.
    result = subprocess.run(['kubectl', '--context', 'k3d-test', '-n', 'platform-test',
        'get', 'secret', 'audio-gateway-speechmatics', '-o', 'jsonpath={.data.api-key}'],
        capture_output=True, timeout=20, check=False)
    if result.returncode:
        raise RuntimeError('test-key-unavailable')
    key = base64.b64decode(result.stdout, validate=True).decode().strip()
    if not key or '\n' in key or '\r' in key:
        raise ValueError('test-key-invalid')
    rows, long_rows = [], []
    cases = ((.05, 1.), (.01, 1.), (.001, 1.), (.25, 4.)) if comparison_round == 'fine' else (
        (.5, 1.), (.25, 1.), (.1, 1.), (.0, 1.), (.5, 2.), (.25, 2.))
    for audio, results in ((pcm, rows), (long_pcm, long_rows)):
        for sensitivity, delay in cases:
            try:
                results.append(await measure(key, audio, sensitivity, delay))
            except Exception as error:
                results.append({'sensitivity': sensitivity, 'maxDelay': delay, 'errorClass': type(error).__name__})
    print(json.dumps({'schema': 'faz24.namePunctuationProbe.v1', 'fixtureSha256': FIXTURE_SHA,
        'comparisonRound': comparison_round,
        'durationSeconds': len(pcm) / 32000, 'deploymentChanged': False, 'phoneAccepted': False,
        'results': rows, 'longPauseFixtureSha256': LONG_FIXTURE_SHA,
        'longPauseDurationSeconds': len(long_pcm) / 32000, 'longPauseResults': long_rows}, indent=2))
    if any('errorClass' in row for row in rows + long_rows):
        raise RuntimeError('probe-incomplete')


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('--round', choices=('coarse', 'fine'), default='coarse')
        asyncio.run(main(parser.parse_args().round))
    except Exception as error:
        print(json.dumps({'errorClass': type(error).__name__, 'status': 'failed'}))
        raise SystemExit(1) from None
