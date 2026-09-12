#!/usr/bin/env python3
"""Update only the existing synthetic DEV frontend client's origins, with readback."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, '/srv/platform-dev/ops')
from remote_dev_credentials import cipher, load_credentials, require_host

ORIGIN = 'https://devai.acik.com'
BASE = 'http://127.0.0.1:33081'
BACKUP = Path('/srv/platform-dev/runtime/secrets/frontend-client.pre-devai.enc')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    require_host()
    secret = load_credentials()
    form = urllib.parse.urlencode({'grant_type': 'password', 'client_id': 'admin-cli',
                                  'username': 'dev-admin', 'password': secret['keycloak_admin']}).encode()
    with urllib.request.urlopen(BASE + '/realms/master/protocol/openid-connect/token', form, timeout=30) as response:
        token = json.load(response)['access_token']

    def call(path, value=None):
        request = urllib.request.Request(BASE + path, method='GET' if value is None else 'PUT',
                                         data=None if value is None else json.dumps(value).encode(),
                                         headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else None

    clients = call('/admin/realms/platform-dev/clients?clientId=frontend')
    if len(clients) != 1 or clients[0]['clientId'] != 'frontend' or not clients[0]['publicClient']:
        raise SystemExit('Unexpected DEV frontend client')
    path = '/admin/realms/platform-dev/clients/' + clients[0]['id']
    client = call(path)
    if not BACKUP.exists():
        if args.rollback:
            raise SystemExit('Rollback snapshot absent')
        encrypted = cipher().encrypt(json.dumps(client).encode())
        fd = os.open(BACKUP, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encrypted)
        if json.loads(cipher().decrypt(BACKUP.read_bytes())) != client:
            raise SystemExit('Client backup readback mismatch')
    desired = dict(client)
    if args.rollback:
        original = json.loads(cipher().decrypt(BACKUP.read_bytes()))
        for key in ('redirectUris', 'webOrigins'):
            desired[key] = original[key]
    else:
        desired['redirectUris'] = list(dict.fromkeys(client['redirectUris'] + [ORIGIN + '/*']))
        desired['webOrigins'] = list(dict.fromkeys(client['webOrigins'] + [ORIGIN]))
    call(path, desired)
    actual = call(path)
    baseline = json.loads(cipher().decrypt(BACKUP.read_bytes()))
    unchanged = set(baseline) | set(actual)
    unchanged -= {'redirectUris', 'webOrigins'}
    if any(actual.get(key) != baseline.get(key) for key in unchanged):
        raise SystemExit('Unrelated client settings differ from original snapshot')
    # Keycloak can canonicalize the ordering of these set-valued fields.
    for key in ('redirectUris', 'webOrigins'):
        actual[key] = sorted(actual[key])
        desired[key] = sorted(desired[key])
    differences = [key for key in set(actual) | set(desired) if actual.get(key) != desired.get(key)]
    if differences:
        raise SystemExit('Client readback differs at fields: ' + ','.join(sorted(differences)))
    print(json.dumps({'realm': 'platform-dev', 'client': 'frontend',
                      'rollback': args.rollback, 'origin_readback': True,
                      'other_client_settings_preserved': True, 'encrypted_backup_verified': True}))


if __name__ == '__main__':
    main()
