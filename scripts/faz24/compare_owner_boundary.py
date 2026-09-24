"""Opt-in synthetic client-wire comparison; does not change runtime settings.

Runs inside the existing temporary TEST identity lifecycle. These are source
encoder profiles, not installed APK/Electron or physical microphone acceptance.
Only newly-created synthetic meetings may be observed. Credentials stay private.
"""
from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
from pathlib import Path
import re
import ssl
import struct
import subprocess
import time

import run_speechmatics_realtime_lifecycle_acceptance as lifecycle

FIXTURES = Path(__file__).parent / 'fixtures/owner-boundary-tr-v1'
WIRE_SHA = {
    'normal': '9573f69abec9abced9f830a9aa6c90f93a325b7c405fa38818ae14529985fa08',
    'paused': '8d0269c2ce8fb455cee742658ce8e011dec60dc5d8f9da48fa8eef097b24a38a',
}
GATEWAY_IMAGE = 'sha256:4e1f4431bd7ef7f78cd1cc934b8472ce6dd9ac84675dad2a9564dfe309ac4307'
ANALYSIS_FIELDS = ('version', 'is_partial', 'summary', 'decisions', 'action_items',
                   'citations', 'rejected_claims', 'live_cursor', 'backend', 'model',
                   'elapsed_ms', 'grounding_policy', 'summary_grounding_status')


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def wire_frames(case, profile):
    data = (FIXTURES / f'{case}-{profile}.wire').read_bytes()
    if digest(data) != WIRE_SHA[case]:
        raise ValueError('wire-identity-mismatch')
    frames, offset = [], 0
    while offset < len(data):
        if len(data)-offset < 19:
            raise ValueError('wire-truncated-header')
        version, seq, captured, size = struct.unpack('>BQQH', data[offset:offset+19])
        if version != 1 or seq != len(frames) or not 0 < size <= 3200 or size % 2:
            raise ValueError('wire-format-mismatch')
        frame = data[offset:offset+19+size]
        if len(frame) != size+19:
            raise ValueError('wire-truncated-payload')
        frames.append(frame)
        offset += len(frame)
    return frames


def verified_input(finals, snapshot):
    text = ' '.join(event['text'].strip() for event in finals if event['text'].strip())
    cursor = snapshot.get('live_cursor') or {}
    length = cursor.get('source_length')
    if type(length) is not int or not 0 < length <= len(text):
        return None
    prefix = text[:length]
    return prefix if digest(prefix) == cursor.get('source_sha256') else None


class SnapshotObserver(lifecycle.AnalysisObserver):
    def __init__(self):
        super().__init__()
        self.trace_carry = b''
        self.snapshots = []

    def push(self, chunk):
        super().push(chunk)
        self.trace_carry += chunk
        if len(self.trace_carry) > 262144:
            raise ValueError('trace-frame-limit')
        parts = re.split(rb'\r?\n\r?\n', self.trace_carry)
        self.trace_carry = parts.pop()
        for part in parts:
            lines = part.decode('utf-8').splitlines()
            event = next((line[6:].strip() for line in lines if line.startswith('event:')), '')
            if event != 'analysis':
                continue
            body = json.loads('\n'.join(line[5:].lstrip(' ') for line in lines if line.startswith('data:')))
            if len(self.snapshots) >= 80:
                raise ValueError('trace-snapshot-limit')
            self.snapshots.append({
                'beforeEof': self.recording,
                'receivedSeconds': round(time.monotonic()-self.audio_started_at, 3) if self.audio_started_at else None,
                'analysis': {key: body[key] for key in ANALYSIS_FIELDS if key in body},
            })


def runtime_identity():
    args = ['kubectl', '--context', 'k3d-test', '-n', 'platform-test', 'get', 'pods',
            '-l', 'app.kubernetes.io/name=audio-gateway', '-o', 'json']
    proc = subprocess.run(args, capture_output=True, timeout=20, check=True)
    pods = [p for p in json.loads(proc.stdout)['items'] if not p['metadata'].get('deletionTimestamp')]
    if len(pods) != 1:
        raise ValueError('requires-one-gateway')
    pod = pods[0]
    images = [c['imageID'] for c in pod['status']['containerStatuses'] if c['name'] == 'audio-gateway']
    if len(images) != 1 or not images[0].endswith(GATEWAY_IMAGE):
        raise ValueError('gateway-version-changed')
    keys = ['AUDIO_GATEWAY_DIRECT_STT_SPEECHMATICS_MAX_DELAY_SECONDS',
            'AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_SEGMENT_WINDOW',
            'AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_MIN_INTERVAL_MS',
            'AUDIO_GATEWAY_DIRECT_STT_LIVE_ANALYZE_ENABLED']
    values = subprocess.run(['kubectl','--context','k3d-test','-n','platform-test','exec',
        pod['metadata']['name'],'-c','audio-gateway','--','printenv',*keys], capture_output=True, timeout=20)
    # printenv may report missing optional values. Never dump other environment.
    return {'imageID': images[0], 'podUid': pod['metadata']['uid'],
            'allowlistedEnv': values.stdout.decode().splitlines(), 'envExit': values.returncode}


async def stream_case(args, token, case, profile):
    import websockets
    frames = wire_frames(case, profile)
    statuses = {}
    meeting, session, started = lifecycle.create_lifecycle(base_url=args.base_url, token=token,
        timeout_seconds=20, statuses=statuses)
    observer = SnapshotObserver()
    observer_task = asyncio.create_task(observer.observe(
        lifecycle.bounded_url(args.base_url, f'/api/v1/audio-gateway/meetings/{meeting}/live-analysis/stream'), token, 150))
    row = {'case':case, 'clientSourceProfile':profile, 'meetingId':meeting, 'sessionId':session,
           'wireSha256':WIRE_SHA[case], 'finalEvents':[], 'audioAcks':0, 'drained':False}
    ready, drained = asyncio.Event(), asyncio.Event()
    try:
        await asyncio.wait_for(observer.ready.wait(), 20)
        async with websockets.connect(f'wss://testai.acik.com/api/v1/audio-gateway/sessions/{session}/stream',
                ssl=ssl.create_default_context(), additional_headers={'Authorization':'Bearer '+token},
                open_timeout=20, close_timeout=5, max_size=1048576) as socket:
            async def receive():
                async for raw in socket:
                    if not isinstance(raw,str):
                        continue
                    event=json.loads(raw)
                    kind=event.get('type')
                    if kind=='ready': ready.set()
                    elif kind=='audio_ack': row['audioAcks']+=1
                    elif kind=='final':
                        if len(row['finalEvents'])>=300 or len(event.get('text',''))>8000:
                            raise ValueError('synthetic-output-limit')
                        row['finalEvents'].append({key:event[key] for key in (
                            'seq','text','source_start_sample','source_end_sample','speakerAttribution') if key in event})
                    elif kind=='drained':
                        row['drained']=True;drained.set();return
                    elif kind=='error': raise ValueError('gateway-stream-error')
            receiver=asyncio.create_task(receive())
            try:
                await asyncio.wait_for(ready.wait(),20)
                observer.audio_started_at=time.monotonic();observer.recording=True
                epoch=int(time.time()*1000);sample_offset=0;sent=0
                for frame in frames:
                    adjusted=bytearray(frame)
                    struct.pack_into('>Q',adjusted,9,epoch+round(sample_offset/32))
                    await socket.send(adjusted);sent+=1;sample_offset+=len(frame)-19
                    await asyncio.sleep(max(0,observer.audio_started_at+sample_offset/32000-time.monotonic()))
                row['spokenAudioEndSeconds']=round(time.monotonic()-observer.audio_started_at,3)
                # Fixed 45s observation window, never a latency success threshold.
                # Paced silence keeps recording active; no EOF before observation.
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    await socket.send(struct.pack('>BQQH',1,sent,int(time.time()*1000),3200)+bytes(3200))
                    sent+=1
                    await asyncio.sleep(.1)
                observer.recording=False
                row['eofSeconds']=round(time.monotonic()-observer.audio_started_at,3)
                await socket.send('{"type":"eof"}')
                await asyncio.wait_for(drained.wait(),35)
                await receiver
                row['audioFrames']=sent
            finally:
                receiver.cancel();await asyncio.gather(receiver,return_exceptions=True)
    finally:
        observer.recording=False
        observer_task.cancel();await asyncio.gather(observer_task,return_exceptions=True)
        finished,_=lifecycle.finish_lifecycle(base_url=args.base_url,token=token,meeting_id=meeting,
            session_id=session,started_at=started,timeout_seconds=20,statuses=statuses)
        row['httpFinished']=finished
    row['snapshots']=observer.snapshots
    row['observer']=observer.metrics
    for snapshot in row['snapshots']:
        source=verified_input(row['finalEvents'],snapshot['analysis'])
        snapshot['inputVerifiedByServerCursor']=source is not None
        if source is not None:
            snapshot['syntheticAnalysisInput']=source
            snapshot['inputSha256']=digest(source)
    row['syntheticFinalText']=' '.join(e['text'].strip() for e in row['finalEvents'] if e['text'].strip())
    row['syntheticFinalSha256']=digest(row['syntheticFinalText'])
    return row


async def compare(args):
    token=lifecycle.read_token(Path(args.token_file))
    report={'schema':'synthetic-owner-client-comparison-v1','syntheticContentIncluded':True,
        'phoneAccepted':False,'installedDesktopAccepted':False,'runtimeSettingsChanged':False,
        'scope':'pinned client-source binary frames through real public TEST gateway; excludes capture/UI',
        'contextTerms':[], 'cases':[],'status':'running'}
    output=Path(args.output_file)
    try:
        report['runtimeBefore']=runtime_identity()
        report['cases'].append(await stream_case(args,token,args.case,args.profile))
        report['runtimeAfter']=runtime_identity()
        if report['runtimeBefore']!=report['runtimeAfter']:
            raise ValueError('runtime-changed-during-comparison')
        report['status']='measured'
    except Exception as error:
        report['status']='incomplete';report['errorClass']=type(error).__name__
        # Only locally-defined fixed error labels are safe; no endpoint response.
        message=str(error)
        if re.fullmatch(r'[a-z-]{1,90}',message): report['errorCode']=message
    finally:
        lifecycle.write_private_json(output,report)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--token-file',required=True)
    parser.add_argument('--output-file',required=True)
    parser.add_argument('--base-url',default=lifecycle.DEFAULT_BASE_URL)
    parser.add_argument('--case',choices=('normal','paused'),required=True)
    parser.add_argument('--profile',choices=('mobile','desktop'),required=True)
    args=parser.parse_args()
    lifecycle.bounded_url(args.base_url,'/')
    report=asyncio.run(compare(args))
    print(json.dumps({'comparisonStatus':report['status'],'caseCount':len(report['cases'])}))
    return 0 if report['status']=='measured' else 2


if __name__=='__main__':
    raise SystemExit(main())
