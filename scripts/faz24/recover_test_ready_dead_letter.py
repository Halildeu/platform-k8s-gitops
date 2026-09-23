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


def recover(settings, inbox, broker, *, apply, parse_event, read_row):
    row = read_row()
    if row is None:
        raise ValueError('reviewed-row-missing')
    if (row['state'] != 'DEAD' or row['dead_reason'] != 'RETRY_EXHAUSTED'
            or row['last_error_code'] != 'processing_OllamaSchemaInvalidError'
            or row['redrive_count'] != 0 or row['dlq_published_at'] is None):
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
    if apply:
        if not inbox.rearm_retry_exhausted_by_fingerprint(FINGERPRINT, audit_reference=AUDIT):
            raise ValueError('canonical-rearm-rejected')
        report['rearmed'] = True
        # If publication fails, leave the audited RECEIVED row visible for
        # explicit recovery. Never undo the audit or report it as delivered.
        broker.xadd(settings.ready_redis_stream, match)
        report['status'] = 'exact-original-event-republished'
    return report


def host_main(apply):
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
                         read_row=read_row)
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
} finally { Clear-MeetingAiManagedProcessEnvironment }
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    # Only the host-safe definitions travel; orchestration imports stay local.
    source = Path(__file__).read_text(encoding='utf-8')
    body = 'import json\nFINGERPRINT=' + repr(FINGERPRINT) + '\nAUDIT=' + repr(AUDIT) + '\n'
    body += source[source.index('def recover('):source.index('\nREMOTE =')]
    body += '\ntry:\n print(json.dumps(host_main(' + repr(args.apply) + ')))\n'
    body += "except Exception as error:\n import re\n result={'status':'failed','errorClass':type(error).__name__}\n"
    body += " if isinstance(error,ValueError) and re.fullmatch('[a-z-]{1,90}',str(error)): result['reason']=str(error)\n print(json.dumps(result))\n"
    result = ceremony.remote(REMOTE.replace('__CODE__', base64.b64encode(body.encode()).decode()), timeout=720)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') in ('preflight-only', 'processed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
