"""Profile the existing TEST model; no settings changes or meeting persistence."""
import base64
import json
from pathlib import Path

import qualify_test_live_model as candidate
import recover_test_ready_permit as ceremony
from live_incremental_latency_probe import probe


def envelope_metadata(envelope):
    """Provider content is deliberately excluded from the diagnostic result."""
    result = {}
    for key in ('total_duration', 'load_duration', 'prompt_eval_duration', 'eval_duration'):
        value = envelope.get(key)
        if type(value) is int and 0 <= value < 2**63:
            result[key.removesuffix('_duration') + 'Seconds'] = round(value / 1e9, 6)
    for key in ('prompt_eval_count', 'eval_count'):
        value = envelope.get(key)
        if type(value) is int and 0 <= value <= 1_000_000:
            result[key] = value
    return result


def local_host(public):
    # The validated Scheduled Task uses start-meeting-ai.ps1's localhost
    # default. HOST is not a required key in the managed runtime config file.
    host = public.get('MAI_OLLAMA_HOST', 'http://localhost:11434')
    if host not in ('http://127.0.0.1:11434', 'http://localhost:11434'):
        raise ValueError('local-inference-required')
    return host


def profile():
    import os
    import time
    import httpx
    from app.core.config import Settings
    from app.services.analyze import MeetingAnalysisService

    public = json.loads(os.environ['LIVE_PROFILE_SETTINGS'])
    if public['MAI_OLLAMA_MODEL'] != 'qwen3.8:27b' or public['MAI_OLLAMA_EXPECTED_DIGEST'] != (
            '22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643'):
        raise ValueError('deployed-model-changed')
    public['MAI_OLLAMA_HOST'] = local_host(public)
    # Copy only non-secret inference controls from the existing deployed config.
    fields = {key.removeprefix('MAI_').lower(): value for key, value in public.items() if value != ''}
    settings = Settings(_env_file=None, app_env='dev', backend='ollama',
                        ingestion_enabled=False, ready_consumer_enabled=False, **fields)
    native_get, native_post = httpx.get, httpx.post
    calls, rows = [], []
    client = None

    def timed(method, url, **kwargs):
        if url not in (settings.ollama_host + '/api/tags', settings.ollama_host + '/api/generate'):
            raise ValueError('unexpected-profile-endpoint')
        begin = time.monotonic()
        fn = getattr(client, method) if client is not None else (native_get if method == 'get' else native_post)
        response = fn(url, **kwargs)
        call = {'operation': 'identity' if method == 'get' else 'generation',
                'wallSeconds': round(time.monotonic() - begin, 6),
                'transportSeconds': round(response.elapsed.total_seconds(), 6),
                'httpStatus': response.status_code}
        if method == 'post' and response.status_code == 200:
            call['provider'] = envelope_metadata(response.json())
        calls.append(call)
        return response

    httpx.get = lambda url, **kwargs: timed('get', url, **kwargs)
    httpx.post = lambda url, **kwargs: timed('post', url, **kwargs)
    try:
        for mode in ('existing-clients', 'shared-client', 'existing-clients-repeat'):
            initialization = time.monotonic()
            if mode == 'shared-client':
                client = httpx.Client()
            initialization = time.monotonic() - initialization
            service = MeetingAnalysisService(settings)
            transcript, cursor = '', None
            stages = STAGES[:1] if mode.endswith('repeat') else STAGES
            for version, (addition, decisions, actions) in enumerate(stages, 1):
                calls.clear()
                transcript = (transcript + ' ' + addition).strip()
                started = time.monotonic()
                try:
                    result = service.analyze(transcript, live=True, live_cursor=cursor)
                    elapsed = time.monotonic() - started
                    body = result.model_dump()
                    body.update(is_partial=True, version=version)
                    row = metadata(body, version, decisions, actions, elapsed)
                    row.update(mode=mode, calls=list(calls), serviceElapsedMs=result.elapsed_ms,
                               clientInitializationSeconds=round(initialization if version == 1 else 0, 6))
                    rows.append(row)
                    cursor = result.live_cursor
                except Exception as error:
                    rows.append({'mode': mode, 'version': version, 'errorClass': type(error).__name__,
                                 'elapsedSeconds': round(time.monotonic()-started, 3), 'calls': list(calls)})
                    break
            if client is not None:
                client.close()
                client = None
    finally:
        httpx.get, httpx.post = native_get, native_post
        if client is not None:
            client.close()
    return {'status': 'measured', 'sourceCommit': SOURCE_COMMIT, 'rows': rows,
            'model': settings.ollama_model, 'modelDigest': settings.ollama_expected_digest,
            'options': settings.ollama_options(), 'keepAlive': settings.ollama_keep_alive,
            'think': settings.ollama_think,
            'scope': 'isolated deployed-source method; sequential profiles may benefit from warm caches',
            'runtimeSettingsChanged': False, 'modelDownloaded': False, 'durableWrites': False,
            'phoneAccepted': False, 'contentIncluded': False}


def remote_script():
    source = Path(__file__).read_text(encoding='utf-8')
    common = Path(__file__).with_name('live_incremental_latency_probe.py').read_text(encoding='utf-8')
    body = 'import json\nSOURCE_COMMIT=' + repr(candidate.SOURCE_COMMIT) + '\n'
    body += common[common.index('STAGES ='):common.index('\ndef probe():')]
    body += source[source.index('def envelope_metadata('):source.index('\ndef remote_script():')]
    body += '''
try:
    result = profile()
except Exception as error:
    result = {'status': 'profile-error', 'errorClass': type(error).__name__, 'contentIncluded': False}
print(json.dumps(result))
'''
    script = candidate.REMOTE.replace('__TARGET__', candidate.SOURCE_COMMIT).replace(
        '__CODE__', base64.b64encode(body.encode()).decode())
    # The launcher already validates source, TEST task identity and local paths.
    # Export an explicit allowlist; do not import runtime secrets into the child.
    addition = r'''
  $public=[ordered]@{}
  foreach ($name in @('MAI_OLLAMA_HOST','MAI_OLLAMA_MODEL','MAI_OLLAMA_EXPECTED_DIGEST',
      'MAI_OLLAMA_NUM_CTX','MAI_OLLAMA_KEEP_ALIVE','MAI_OLLAMA_THINK',
      'MAI_OLLAMA_TEMPERATURE','MAI_OLLAMA_TOP_P','MAI_OLLAMA_SEED','MAI_REQUEST_TIMEOUT')) {
    if ($values.ContainsKey($name)) { $public[$name]=[string]$values[$name] }
  }
  $psi.EnvironmentVariables['LIVE_PROFILE_SETTINGS']=($public | ConvertTo-Json -Compress)
'''
    return script.replace('  $proc=New-Object Diagnostics.Process;', addition + '\n  $proc=New-Object Diagnostics.Process;')


def main():
    # The first phase exercises deployed HTTP, before the isolated comparison.
    report = {'phoneAccepted': False, 'status': 'failed', 'phase': 'http'}
    try:
        report['http'] = probe()
        report['phase'] = 'isolated-stages'
        report['stages'] = ceremony.remote(remote_script(), timeout=1500)
        report['status'] = 'measured' if report['stages'].get('status') == 'measured' else 'failed'
    except Exception as error:
        # Preserve completed numeric evidence; never export exception messages,
        # which can include subprocess output or runtime configuration values.
        report['errorClass'] = type(error).__name__
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'measured' else 1


if __name__ == '__main__':
    raise SystemExit(main())
