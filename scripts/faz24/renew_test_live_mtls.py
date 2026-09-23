"""One-shot TEST expired-server-leaf renewal; keys and CA stay on the GPU host."""
import argparse
import json
from pathlib import Path
import subprocess

from gpu_mtls_metadata import governed_ssh_paths
from run_gpu_host_exact_sha_rollout import encode_remote_input, ssh_command


SCRIPT_PATH = Path(__file__).with_suffix('.ps1')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config, known_hosts = governed_ssh_paths()
    source = SCRIPT_PATH.read_text(encoding='utf-8')
    if source.count('$Apply = $false # APPLY_MARKER') != 1:
        raise ValueError('renewal-source-marker-invalid')
    if args.apply:
        source = source.replace('$Apply = $false # APPLY_MARKER', '$Apply = $true # APPLY_MARKER')
    result = subprocess.run(ssh_command(config, known_hosts), input=encode_remote_input(source),
                            capture_output=True, text=True, timeout=150, check=False)
    records = [line.removeprefix('TEST_MTLS_RENEWAL:') for line in result.stdout.splitlines()
               if line.startswith('TEST_MTLS_RENEWAL:')]
    if len(records) != 1:
        print(json.dumps({'status': 'no-evidence', 'exitCode': result.returncode,
                          'stdoutBytes': len(result.stdout), 'stderrBytes': len(result.stderr)}))
        return 1
    report = json.loads(records[0])
    print(json.dumps(report, sort_keys=True))
    return 0 if result.returncode == 0 and report.get('status') in ('dry-run-validated', 'renewed') else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'status': 'error', 'errorClass': type(error).__name__}))
        raise SystemExit(1)
