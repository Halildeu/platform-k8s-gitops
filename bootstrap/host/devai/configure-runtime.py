#!/usr/bin/env python3
"""Apply the DEV public origin after the existing private runtime renderer."""
import json
import os
from pathlib import Path
import socket
import subprocess

ORIGIN = 'https://devai.acik.com'
OLD_ISSUER = 'http://127.0.0.1:33081/realms/platform-dev'
ISSUER = ORIGIN + '/realms/platform-dev'
ISSUER_KEYS = {
    'KEYCLOAK_ISSUER_URI', 'SECURITY_JWT_ISSUER', 'SERVICE_AUTH_ISSUER',
    'AUTO_PROVISION_ALLOWED_ISSUERS',
}


def transform_env(content, keycloak=False):
    env = dict(line.split('=', 1) for line in content.splitlines() if line)
    if keycloak:
        if env.get('KC_HOSTNAME') not in ('http://127.0.0.1:33081', ORIGIN):
            raise ValueError('Unexpected DEV Keycloak hostname')
        env.update(KC_HOSTNAME=ORIGIN, KC_PROXY_HEADERS='xforwarded',
                   KC_PROXY_TRUSTED_ADDRESSES='127.0.0.1', KC_HTTP_ENABLED='true')
    else:
        for key in ISSUER_KEYS:
            if env.get(key) not in (OLD_ISSUER, ISSUER):
                raise ValueError('Unexpected DEV issuer configuration')
            env[key] = ISSUER
        # Signature retrieval and service token transport remain loopback-only.
        env['GATEWAY_CORS_ALLOWED_ORIGINS'] = ORIGIN + ',http://127.0.0.1:33000'
    return ''.join(f'{key}={value}\n' for key, value in env.items())


def update_realm(realm):
    if realm['realm'] != 'platform-dev':
        raise ValueError('Unexpected realm')
    clients = [c for c in realm['clients'] if c['clientId'] == 'frontend']
    if len(clients) != 1:
        raise ValueError('Expected one frontend client')
    client = clients[0]
    client['redirectUris'] = [ORIGIN + '/*', 'http://127.0.0.1:33000/*']
    client['webOrigins'] = [ORIGIN, 'http://127.0.0.1:33000']
    return realm


def main():
    if socket.gethostname() != 'stagingsw' or '10.9.10.53' not in subprocess.check_output(['hostname', '-I'], text=True).split():
        raise SystemExit('Unexpected host')
    root = Path('/run/platform-dev-config')
    if subprocess.check_output(['findmnt', '-T', str(root), '-n', '-o', 'FSTYPE'], text=True).strip() != 'tmpfs':
        raise SystemExit('DEV secret configuration must stay on tmpfs')
    files = list(root.glob('*.env'))
    backends = [p for p in files if p.name not in ('postgres.env', 'keycloak.env', 'openfga.env', 'mssql.env', 'mailpit.env')]
    backends = [p for p in backends if 'KEYCLOAK_ISSUER_URI=' in p.read_text()]
    if len(backends) != 13:
        raise SystemExit('Expected thirteen DEV backend configurations')
    changes = {p: transform_env(p.read_text()) for p in backends}
    kc = root / 'keycloak.env'
    changes[kc] = transform_env(kc.read_text(), keycloak=True)
    realm = root / 'realm.json'
    changes[realm] = json.dumps(update_realm(json.loads(realm.read_text())))
    for file, content in changes.items():
        fd = os.open(file, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        if file.read_text() != content:
            raise RuntimeError('DEV configuration readback mismatch')
    print('DEV origin readback: 13 backends, Keycloak and realm import; secrets not printed')


if __name__ == '__main__':
    main()
