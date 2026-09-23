"""Pinned small-model synthetic qualification; no service setting or meeting write."""
import base64
import json
from pathlib import Path

import recover_test_ready_permit as ceremony

SOURCE_COMMIT = '38ef0f3648c8e092599c0578764a4f2f075dd0a1'
PROFILES = [
    ('qwen3.5:4b', '2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd'),
]


def prepare_candidate():
    import hashlib
    import shutil
    import httpx
    model, digest = PROFILES[0]
    inventory = httpx.get('http://127.0.0.1:11434/api/tags', timeout=5)
    inventory.raise_for_status()
    matches = [row for row in inventory.json()['models'] if row['name'] == model]
    if matches:
        if len(matches) != 1 or matches[0]['digest'] != digest:
            raise RuntimeError('candidate-inventory-digest-mismatch')
        return {'downloaded': False, 'digestVerified': True}
    # Only this reviewed official-registry manifest may add a model. A moved tag
    # fails before pull; downloaded bytes are verified again by the runtime guard.
    response = httpx.get('https://registry.ollama.ai/v2/library/qwen3.5/manifests/4b', timeout=30)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != digest:
        raise RuntimeError('candidate-registry-digest-mismatch')
    manifest = response.json()
    size = manifest['config']['size'] + sum(layer['size'] for layer in manifest['layers'])
    if size > 4_000_000_000 or shutil.disk_usage('C:\\').free < 10_000_000_000:
        raise RuntimeError('candidate-disk-budget-rejected')
    response = httpx.post('http://127.0.0.1:11434/api/pull',
                          json={'model': model, 'stream': False}, timeout=600)
    response.raise_for_status()
    if response.json().get('status') != 'success':
        raise RuntimeError('candidate-pull-rejected')
    inventory = httpx.get('http://127.0.0.1:11434/api/tags', timeout=5)
    inventory.raise_for_status()
    matches = [row for row in inventory.json()['models'] if row['name'] == model]
    if len(matches) != 1 or matches[0]['digest'] != digest:
        raise RuntimeError('candidate-downloaded-digest-mismatch')
    return {'downloaded': True, 'digestVerified': True, 'manifestBytes': size}


def qualify():
    import time
    import httpx
    import subprocess
    from app.core.config import Settings
    from app.services.analyze import MeetingAnalysisService
    rows = []
    memory = subprocess.run(['nvidia-smi','--query-gpu=memory.total,memory.used,utilization.gpu',
        '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10,check=False)
    gpu_memory = [dict(zip(('totalMiB','usedMiB','utilizationPercent'),map(int,line.split(','))))
                  for line in memory.stdout.splitlines()] if memory.returncode == 0 else []
    preparation = prepare_candidate()
    for model, digest in PROFILES:
        settings = Settings(_env_file=None, app_env='dev', backend='ollama',
            ollama_host='http://127.0.0.1:11434', ollama_model=model,
            ollama_expected_digest=digest, ollama_num_ctx=4096, ollama_keep_alive='5m', ollama_think=False,
            request_timeout=60, ingestion_enabled=False, ready_consumer_enabled=False)
        service = MeetingAnalysisService(settings)
        transcript, cursor, samples = '', None, []
        try:
            for version, (addition, decisions, actions) in enumerate(STAGES, 1):
                transcript = (transcript + ' ' + addition).strip()
                started = time.monotonic()
                result = service.analyze(transcript, live=True, live_cursor=cursor)
                # This is service-method content qualification, not HTTP/SSE.
                content = result.model_dump()
                content.update(is_partial=True, version=version)
                sample = metadata(content, version, decisions, actions, time.monotonic()-started)
                sample['phase'] = 'incremental'
                samples.append(sample)
                cursor = result.live_cursor
            for text in (
                'Bütçeyi artırmayı öneriyorum; henüz karar almadık.',
                'Mehmet raporu hazırlayabilir mi? Henüz görev verilmedi.',
                'Geçen yıl sunumu çevrim içi yapmaya karar vermiştik.',
                'Ali raporu hazırladı; başka görev yok.',
                'Tamam.',
            ):
                started = time.monotonic()
                result = service.analyze(text, live=True)
                elapsed = time.monotonic()-started
                samples.append({'phase':'negative', 'elapsedSeconds':round(elapsed,3),
                    'withinFiveSeconds':elapsed<=5,
                    'qualityPass':not result.decisions and not result.action_items,
                    'cursorReturned':result.live_cursor is not None})
            rows.append({'model':model, 'digest':digest, 'numCtx':4096, 'think':False, 'samples':samples,
                'status':'qualified' if all(s['qualityPass'] and s['withinFiveSeconds']
                    and s['cursorReturned'] for s in samples) else 'not-qualified'})
        except Exception as error:
            failure = {'model':model, 'digest':digest, 'samples':samples,
                       'status':'error', 'errorClass':type(error).__name__,
                       'failedCallSeconds':round(time.monotonic()-started,3)}
            cause = error.__cause__
            if cause is not None:
                failure['causeClass'] = type(cause).__name__
                response = getattr(cause,'response',None)
                if response is not None:
                    failure['httpStatus'] = response.status_code
                    # Enumerated infrastructure categories only, never raw error.
                    message = response.text.lower()
                    failure['memoryError'] = 'memory' in message or 'cuda' in message
                    failure['unsupportedOption'] = 'not support' in message
            rows.append(failure)
        finally:
            # Release only the benchmark candidate, never unload the deployed model.
            try:
                httpx.post(settings.ollama_host+'/api/generate',
                    json={'model':model,'keep_alive':0}, timeout=15).raise_for_status()
            except httpx.HTTPError:
                rows[-1]['candidateUnloadVerified'] = False
            else:
                rows[-1]['candidateUnloadVerified'] = True
        if rows[-1]['status'] == 'qualified':
            break
    return {'status':'measured', 'profiles':rows, 'synthetic':True, 'sourceCommit':SOURCE_COMMIT,
            'gpuMemoryBefore':gpu_memory, 'preparation':preparation,
            'runtimeAccepted':False, 'phoneAccepted':False, 'durableWrites':False,
            'scope':'isolated candidate service method on existing TEST inference host'}


REMOTE = ceremony.HEADER.replace(ceremony.SOURCE, SOURCE_COMMIT) + r'''
$target='__TARGET__'
$controller=Join-Path $env:TEMP ('platform-ai-live-benchmark-'+[Guid]::NewGuid().ToString('N'))
$created=$false
function Git-Silent([string[]]$argsList) {
  $old=$ErrorActionPreference
  try { $ErrorActionPreference='Continue'; & git @argsList 1>$null 2>$null; return $LASTEXITCODE }
  finally { $ErrorActionPreference=$old }
}
try {
  if ((Git-Silent @('-C',$repo,'fetch','origin','main')) -ne 0 -or
      (Git-Silent @('-C',$repo,'merge-base','--is-ancestor',$target,'origin/main')) -ne 0) {
    throw 'benchmark-source-not-main'
  }
  if ((Git-Silent @('-C',$repo,'worktree','add','--detach',$controller,$target)) -ne 0) {
    throw 'benchmark-worktree-rejected'
  }
  $created=$true
  $body=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__CODE__'))
  $psi=New-Object Diagnostics.ProcessStartInfo
  $psi.FileName=$python; $psi.WorkingDirectory=$controller
  $psi.Arguments=(@('-c',$body) | ForEach-Object { ConvertTo-GpuHostWindowsArgument -Value ([string]$_) }) -join ' '
  $psi.UseShellExecute=$false; $psi.CreateNoWindow=$true
  $psi.RedirectStandardOutput=$true; $psi.RedirectStandardError=$true
  foreach ($key in @($psi.EnvironmentVariables.Keys)) {
    if ([string]$key -like 'MAI_*') { $psi.EnvironmentVariables.Remove($key) }
  }
  $psi.EnvironmentVariables['PYTHONPATH']=(Join-Path $controller 'services\meeting-ai-service')
  $psi.EnvironmentVariables['PYTHONDONTWRITEBYTECODE']='1'
  $psi.EnvironmentVariables['PYTHONUTF8']='1'
  $proc=New-Object Diagnostics.Process; $proc.StartInfo=$psi; $null=$proc.Start()
  $outRead=$proc.StandardOutput.ReadToEndAsync(); $errRead=$proc.StandardError.ReadToEndAsync()
  if (!$proc.WaitForExit(1450000)) { $proc.Kill(); $proc.WaitForExit(); throw 'benchmark-timeout' }
  if ($proc.ExitCode -ne 0) { throw 'benchmark-process-rejected' }
  Emit ($outRead.Result | ConvertFrom-Json)
  $proc.Dispose()
} finally {
  if ($created) {
    $resolved=[IO.Path]::GetFullPath($controller)
    $tempRoot=[IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')+'\'
    if (!$resolved.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolved) -cnotmatch '^platform-ai-live-benchmark-[0-9a-f]{32}$') {
      throw 'benchmark-cleanup-path-rejected'
    }
    if ((Git-Silent @('-C',$repo,'worktree','remove',$resolved)) -ne 0) { throw 'benchmark-cleanup-rejected' }
  }
}
'''


def main():
    source = Path(__file__).read_text(encoding='utf-8')
    common = Path(__file__).with_name('live_incremental_latency_probe.py').read_text(encoding='utf-8')
    body = 'import json\nSOURCE_COMMIT='+repr(SOURCE_COMMIT)+'\nPROFILES='+repr(PROFILES)+'\n'
    body += common[common.index('STAGES ='):common.index('\ndef probe():')]
    body += source[source.index('def prepare_candidate():'):source.index('\nREMOTE =')]
    body += '\nprint(json.dumps(qualify()))\n'
    result = ceremony.remote(REMOTE.replace('__TARGET__',SOURCE_COMMIT).replace(
        '__CODE__',base64.b64encode(body.encode()).decode()), timeout=1500)
    print(json.dumps(result,sort_keys=True))
    return 0 if result.get('status') == 'measured' else 1


if __name__ == '__main__':
    raise SystemExit(main())
