#!/usr/bin/env python3
"""Install DEV-only HTTPS integration. Requires an already approved valid TLS pair."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

SOURCE = Path(__file__).resolve().parent
OPS = Path('/srv/platform-dev/ops/devai')
BACKUP = Path('/etc/platform-dev/pre-devai-20260912')
APPS = {'suggestions': 33001, 'ethic': 33002, 'users': 33004, 'access': 33005,
        'audit': 33006, 'reporting': 33007, 'schema-explorer': 33008,
        'endpoint-admin': 33009, 'meeting': 33010, 'interview-evidence': 33011}
ORIGIN = 'https://devai.acik.com'


def run(*args):
    subprocess.run(args, check=True)


def write(path, content, mode=0o644):
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    if file.exists() and not (BACKUP / file.relative_to('/')).exists():
        target = BACKUP / file.relative_to('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    os.fchmod(fd, mode)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    if file.read_text() != content:
        raise RuntimeError('Installed file readback mismatch')


def main():
    if os.geteuid() != 0 or socket.gethostname() != 'stagingsw' or '10.9.10.53' not in subprocess.check_output(['hostname', '-I'], text=True).split():
        raise SystemExit('Run with sudo on DEV .53 only')
    tls = Path('/etc/platform-dev/proxy/tls')
    run('openssl', 'x509', '-in', str(tls / 'fullchain.pem'), '-noout', '-checkhost', 'devai.acik.com')
    run('openssl', 'x509', '-in', str(tls / 'fullchain.pem'), '-noout', '-checkend', '86400')
    run('openssl', 'verify', '-purpose', 'sslserver', '-verify_hostname', 'devai.acik.com', '-untrusted', str(tls / 'fullchain.pem'), str(tls / 'fullchain.pem'))
    cert_pub = subprocess.check_output(['openssl', 'x509', '-in', str(tls / 'fullchain.pem'), '-pubkey', '-noout'])
    key_pub = subprocess.check_output(['openssl', 'pkey', '-in', str(tls / 'privkey.pem'), '-pubout'])
    if cert_pub != key_pub:
        raise SystemExit('Certificate/key mismatch')
    BACKUP.mkdir(mode=0o700, exist_ok=True)
    OPS.mkdir(parents=True, exist_ok=True)
    for name in ('devai-vite.config.mts', 'configure-runtime.py', 'configure-client.py'):
        write(OPS / name, (SOURCE / name).read_text())
    write('/etc/platform-dev/proxy/Caddyfile', (SOURCE / 'Caddyfile').read_text())
    run('sudo', '-u', 'caddy', 'caddy', 'validate', '--config', '/etc/platform-dev/proxy/Caddyfile', '--adapter', 'caddyfile')
    write('/etc/systemd/system/platform-dev-proxy.service', (SOURCE / 'platform-dev-proxy.service').read_text())
    write('/etc/systemd/system/platform-dev-runtime-config.service.d/devai.conf',
          '[Service]\nExecStartPost=/usr/bin/python3 /srv/platform-dev/ops/devai/configure-runtime.py\n')
    common = dict(line.split('=', 1) for line in Path('/etc/platform-dev/frontend-common.env').read_text().splitlines() if line)
    common.update(VITE_FRONTEND_PUBLIC_ORIGIN=ORIGIN, VITE_KEYCLOAK_URL=ORIGIN,
                  MFE_SHELL_URL=ORIGIN + '/remoteEntry.js', VITE_ENABLE_FAKE_AUTH='false')
    for name in APPS:
        common['MFE_' + name.upper().replace('-', '_') + '_URL'] = ORIGIN + '/mfe/' + name + '/remoteEntry.js'
    write('/etc/platform-dev/frontend-common.env', ''.join(f'{key}={value}\n' for key, value in common.items()))
    for unit, port in (('platform-dev-preview.service', '33000'), ('platform-dev-mfe@.service', '${DEV_PORT}')):
        write('/etc/systemd/system/' + unit + '.d/devai.conf',
              '[Service]\nExecStart=\nExecStart=/home/halil/.local/bin/pnpm exec vite --config /srv/platform-dev/ops/devai/devai-vite.config.mts --host 127.0.0.1 --port ' + port + ' --strictPort\n')
    run('systemd-analyze', 'verify', '/etc/systemd/system/platform-dev-proxy.service')
    run('systemctl', 'daemon-reload')
    # The proxy also enforces the actual socket peer, never client-supplied XFF.
    for port in ('80', '443'):
        run('ufw', 'insert', '1', 'deny', 'in', 'proto', 'tcp', 'from', 'any', 'to', '10.9.10.53', 'port', port, 'comment', 'devai-internal-only')
        for network in ('10.250.250.0/24', '10.9.0.0/16'):
            run('ufw', 'insert', '1', 'allow', 'in', 'proto', 'tcp', 'from', network, 'to', '10.9.10.53', 'port', port, 'comment', 'devai-company-vpn')
    print(json.dumps({'installed': True, 'services_not_restarted': True, 'backup': str(BACKUP)}))


if __name__ == '__main__':
    main()
