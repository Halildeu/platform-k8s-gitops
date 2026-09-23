"""Recover one reviewed TEST retry exhaustion using the exact retained event.

No event body, identity, model output or credential leaves the GPU host. The
canonical inbox rearm retains its audit trail; stream messages are never deleted.
"""
import argparse
import base64
import json
from pathlib import Path

import recover_test_ready_permit as ceremony

FINGERPRINT = '50906e03f13cacc61ecd16a97854fe9a2a4099bd448f040499e078e54ea0e693'
AUDIT = 'https://github.com/Halildeu/platform-k8s-gitops/issues/3440'


def recover(settings, inbox, broker, *, apply, parse_event, read_row, diagnose=None):
    if apply and diagnose is not None:
        raise ValueError('diagnosis-cannot-rearm')
    row = read_row()
    if row is None:
        raise ValueError('reviewed-row-missing')
    if (row['state'] != 'DEAD' or row['dead_reason'] != 'RETRY_EXHAUSTED'
            or row['last_error_code'] != 'processing_OllamaSchemaInvalidError'
            or row['redrive_count'] != (1 if diagnose is not None else 0)
            or row['dlq_published_at'] is None):
        raise ValueError('reviewed-row-state-changed')
    _, digest, run_id, lookup_key = inbox._decrypt_event_metadata(row)
    if not run_id:
        raise ValueError('reviewed-row-identity-invalid')
    # Find retained original bytes before rearming. Never reconstruct an event
    # from identity fields or reset the group cursor/replay other meetings.
    start, scanned, match = '-', 0, None
    while scanned < 10000 and match is None:
        page = broker.xrange(settings.ready_redis_stream, min=start, max='+', count=100)
        if not page:
            break
        for _, fields in page:
            scanned += 1
            try:
                event = parse_event(fields, analysis_spec_version=settings.analysis_spec_version)
            except (ValueError, UnicodeDecodeError):
                continue
            if event.lookup_key != lookup_key:
                continue
            if event.payload_sha256 != digest or str(event.analysis_run_id) != run_id:
                raise ValueError('retained-event-conflicts-with-reviewed-row')
            match = fields
            break
        last_id = page[-1][0]
        start = '(' + (last_id.decode('ascii') if isinstance(last_id, bytes) else last_id)
    if match is None:
        raise ValueError('exact-original-event-not-retained')
    report = {'lookupFingerprint': FINGERPRINT, 'originalPayloadVerified': True,
              'eventBodyIncluded': False, 'scannedCount': scanned,
              'status': 'preflight-only', 'rearmed': False}
    if diagnose is not None:
        report.update(status='diagnosed-without-rearm', diagnosis=diagnose(settings, event))
    if apply:
        if not inbox.rearm_retry_exhausted_by_fingerprint(FINGERPRINT, audit_reference=AUDIT):
            raise ValueError('canonical-rearm-rejected')
        report['rearmed'] = True
        # If publication fails, leave the audited RECEIVED row visible for
        # explicit recovery. Never undo the audit or report it as delivered.
        broker.xadd(settings.ready_redis_stream, match)
        report['status'] = 'exact-original-event-republished'
    return report


def safe_schema_error(error):
    allowed_fields = {'summary_sentences', 'decision_sentences', 'action_item_sentences',
                      'sentence', 'owner', 'due_date', 'summary', 'decisions', 'action_items', 'text'}
    report = {'errorClass': type(error).__name__}
    cause = error.__cause__
    if cause is not None and hasattr(cause, 'errors'):
        issues = cause.errors(include_input=False, include_context=False, include_url=False)
        report['validation'] = [{'type': item['type'],
            'location': [part if type(part) is int or part in allowed_fields else 'other'
                         for part in item['loc']]} for item in issues[:20]]
    messages = {'Ollama JSON is not an object', "field 'summary' must be a string",
                "field 'decisions' must be a list of strings", "field 'action_items' must be a list",
                'action_items entry must be an object', 'action_items[].text must be a string',
                'action_items[].owner must be a string or null',
                'action_items[].due_date must be a string or null',
                'Ollama returned invalid sentence selection'}
    if str(error) in messages:
        report['schemaRule'] = str(error)
    return report


def diagnose_model(settings, event):
    import asyncio
    import httpx
    import time
    from app.services.canonical_transcript_client import HttpCanonicalTranscriptClient
    from app.services import analyze
    async def fetch():
        client = HttpCanonicalTranscriptClient(settings)
        try:
            return await client.fetch(event)
        finally:
            await client.aclose()
    snapshot = asyncio.run(fetch())
    report = {'sourceCharacterCount': len(snapshot.transcript), 'sourceSegmentCount': len(snapshot.segments),
              'responseContentIncluded': False, 'durableResultWritten': False}
    if settings.backend != 'ollama':
        raise ValueError('actual-ollama-backend-required')
    loaded = httpx.get(settings.ollama_host + '/api/ps', timeout=5).json().get('models', [])
    report['loadedModelMemory'] = [{key:item.get(key) for key in ('size','size_vram','context_length')}
                                 for item in loaded if item.get('name') == settings.ollama_model]
    original = analyze.generate
    def instrumented_generate(*args, **kwargs):
        response = original(*args, **kwargs)
        envelope = response.json()
        report['durationsSeconds'] = {stage: envelope[stage + '_duration']/1e9
            for stage in ('load','prompt_eval','eval') if type(envelope.get(stage + '_duration')) is int}
        return response
    analyze.generate = instrumented_generate
    started = time.monotonic()
    try:
        result = analyze.get_service(settings).analyze(snapshot.transcript,
                    [segment.model_dump() for segment in snapshot.segments])
        report.update(outcome='valid-response', decisions=len(result.decisions), actions=len(result.action_items))
    except Exception as error:
        report.update(outcome='reproduced-error', **safe_schema_error(error))
    finally:
        analyze.generate = original
    report['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return report


def host_main(apply, diagnose=False):
    import sqlite3
    import time
    import redis
    from app.core.config import get_settings
    from app.models.ready_event import parse_transcript_ready_event
    from app.services.durable_outbox import PayloadCipher, SqliteOutboxStore
    from app.services.ready_event_inbox import SqliteReadyEventInbox

    settings = get_settings()
    if settings.app_env != 'test' or not settings.ready_consumer_enabled:
        raise ValueError('enabled-test-consumer-required')
    store = SqliteOutboxStore(settings.ingestion_store_path,
        PayloadCipher(settings.ingestion_payload_encryption_keys(), settings.ingestion_active_key_id,
                      lookup_key=settings.ingestion_lookup_key()), max_rows=settings.ingestion_max_rows)
    inbox = SqliteReadyEventInbox(store, max_rows=settings.ready_consumer_inbox_max_rows,
                                 max_failures=settings.ready_consumer_max_failures)
    def read_row():
        with sqlite3.connect(settings.ingestion_store_path) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute('SELECT * FROM meeting_transcript_ready_inbox WHERE event_key_digest=?',
                                      (FINGERPRINT,)).fetchone()
    broker = redis.Redis.from_url(settings.ready_redis_url.get_secret_value(),
                                 socket_timeout=10, socket_connect_timeout=10)
    try:
        report = recover(settings, inbox, broker, apply=apply, parse_event=parse_transcript_ready_event,
                         read_row=read_row, diagnose=diagnose_model if diagnose else None)
        if apply:
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                row = read_row()
                state = row['state']
                if state in ('OUTBOXED', 'DEAD'):
                    report.update(status='processed' if state == 'OUTBOXED' else 'retry-failed',
                                  finalState=state, failureCount=row['failure_count'])
                    break
                time.sleep(5)
            else:
                report.update(status='processing-not-yet-verified', finalState=state)
        return report
    finally:
        broker.close()


REMOTE = ceremony.HEADER + r'''
if ($task.State -ne 'Running') { throw 'baseline-consumer-not-running' }
$body=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__CODE__'))
$service=Join-Path $repo 'services\meeting-ai-service'
$env:PYTHONPATH=$service
try {
  $null=Import-MeetingAiRuntimeEnvironment -Path $configPath
  $health=Invoke-RestMethod 'http://127.0.0.1:8300/health' -TimeoutSec 10
  if ($health.backend -cne 'ollama' -or $health.model -cne $values['MAI_OLLAMA_MODEL']) {
    throw 'actual-backend-profile-mismatch'
  }
  # Backend is a canonical launcher default, not a protected config key.
  # Mirror it explicitly; diagnostic children must never use Settings' mock default.
  $env:MAI_BACKEND='ollama'
  $psi=New-Object Diagnostics.ProcessStartInfo
  $psi.FileName=$python; $psi.WorkingDirectory=$service
  $psi.Arguments=(@('-c',$body) | ForEach-Object { ConvertTo-GpuHostWindowsArgument -Value ([string]$_) }) -join ' '
  $psi.UseShellExecute=$false; $psi.CreateNoWindow=$true
  $psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true
  $proc=New-Object Diagnostics.Process; $proc.StartInfo=$psi; $null=$proc.Start()
  $outRead=$proc.StandardOutput.ReadToEndAsync(); $errRead=$proc.StandardError.ReadToEndAsync()
  if (!$proc.WaitForExit(680000)) { $proc.Kill(); throw 'recovery-completion-unknown' }
  if ($proc.ExitCode -ne 0) { throw 'recovery-host-process-rejected' }
  Emit ($outRead.Result | ConvertFrom-Json)
  $proc.Dispose()
} finally { Clear-MeetingAiManagedProcessEnvironment; $env:MAI_BACKEND=$null }
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--diagnose', action='store_true')
    args = parser.parse_args()
    if args.apply and args.diagnose:
        parser.error('diagnosis cannot rearm')
    # Only the host-safe definitions travel; orchestration imports stay local.
    source = Path(__file__).read_text(encoding='utf-8')
    body = 'import json\nFINGERPRINT=' + repr(FINGERPRINT) + '\nAUDIT=' + repr(AUDIT) + '\n'
    body += source[source.index('def recover('):source.index('\nREMOTE =')]
    body += '\ntry:\n print(json.dumps(host_main(' + repr(args.apply) + ',' + repr(args.diagnose) + ')))\n'
    body += "except Exception as error:\n import re\n result={'status':'failed','errorClass':type(error).__name__}\n"
    body += " if isinstance(error,ValueError) and re.fullmatch('[a-z-]{1,90}',str(error)): result['reason']=str(error)\n print(json.dumps(result))\n"
    result = ceremony.remote(REMOTE.replace('__CODE__', base64.b64encode(body.encode()).decode()), timeout=720)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') in ('preflight-only', 'processed', 'diagnosed-without-rearm') else 1


if __name__ == '__main__':
    raise SystemExit(main())
