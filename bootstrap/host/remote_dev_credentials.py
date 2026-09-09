#!/usr/bin/env python3
"""Encrypted DEV credential store; generated runtime configuration lives in /run."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess

STORE = Path('/srv/platform-dev/runtime/secrets/credentials.enc')
KEY = '/etc/platform-dev/secret-store/credential.key'


def require_host():
    if socket.gethostname() != 'stagingsw' or '10.9.10.53' not in subprocess.check_output(['hostname', '-I'], text=True).split():
        raise SystemExit('Unexpected host')


def cipher(create=False):
    require_host()
    from cryptography.fernet import Fernet
    exists = subprocess.run(['sudo', '-n', 'test', '-f', KEY]).returncode == 0
    if not exists:
        if not create or STORE.exists():
            raise RuntimeError('DEV credential key is unavailable; refusing to replace it')
        subprocess.run(['sudo', '-n', 'install', '-d', '-m', '700', str(Path(KEY).parent)], check=True)
        # O_EXCL protects concurrent first-run attempts; key bytes never reach logs.
        program = "import os,sys; p=sys.argv[1]; data=sys.stdin.buffer.read();\ntry: fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)\nexcept FileExistsError: pass\nelse:\n os.write(fd,data); os.close(fd)"
        subprocess.run(['sudo', '-n', 'python3', '-c', program, KEY], input=Fernet.generate_key(), check=True, stdout=subprocess.DEVNULL)
    material = subprocess.check_output(['sudo', '-n', 'cat', KEY])
    return Fernet(material)


def load_credentials():
    return json.loads(cipher().decrypt(STORE.read_bytes()))


def initialize_credentials():
    if STORE.exists():
        return load_credentials()
    protector = cipher(create=True)
    legacy = STORE.with_name('credentials.json')
    if legacy.exists():
        values = json.loads(legacy.read_text())
    else:
        values = {name: secrets.token_urlsafe(32) for name in ['postgres', 'keycloak_admin', 'developer', 'service']}
    payload = protector.encrypt(json.dumps(values).encode())
    temporary = STORE.with_suffix('.enc.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)
    temporary.replace(STORE)
    if load_credentials() != values:
        raise RuntimeError('Encrypted DEV credential readback mismatch')
    return values


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--show-dev-login', action='store_true', required=True, help='Display only the synthetic DEV login in your own terminal; never paste it into chat or logs')
    parser.parse_args()
    data = load_credentials()
    print('URL: http://127.0.0.1:33000/\nUsername: developer\nPassword: '+data['developer'])
