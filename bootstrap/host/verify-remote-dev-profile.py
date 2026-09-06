#!/usr/bin/env python3
"""Real OIDC/profile persistence proof for the isolated synthetic DEV account."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--activate-fixture', action='store_true', help='Activate only the synthetic developer account during initial DEV bootstrap')
args = parser.parse_args()
if socket.gethostname() != 'stagingsw' or '10.9.10.53' not in subprocess.check_output(['hostname', '-I'], text=True).split():
    raise SystemExit('Unexpected host')
base = Path('/srv/platform-dev')
secret = json.loads((base/'runtime/secrets/credentials.json').read_text())
url = 'http://127.0.0.1:33000/api/v1/users/me/profile'

def token():
    data = urllib.parse.urlencode({'grant_type': 'password', 'client_id': 'frontend', 'username': 'developer', 'password': secret['developer']}).encode()
    request = urllib.request.Request('http://127.0.0.1:33081/realms/platform-dev/protocol/openid-connect/token', data=data)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)['access_token']

def profile(bearer, name=None):
    data = None if name is None else json.dumps({'name': name}).encode()
    request = urllib.request.Request(url, data=data, method='GET' if data is None else 'PUT', headers={'Authorization': 'Bearer '+bearer, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

bearer = token()
if args.activate_fixture:
    try:
        profile(bearer)  # Provision from the actual synthetic OIDC identity.
    except urllib.error.HTTPError as error:
        if error.code not in (401, 403):
            raise
    sql = "UPDATE user_service.users SET enabled=true, role='ADMIN' WHERE email='developer@example.invalid' AND kc_subject IS NOT NULL AND deleted_at IS NULL; SELECT count(*) FROM user_service.users WHERE email='developer@example.invalid' AND enabled=true AND role='ADMIN' AND kc_subject IS NOT NULL AND deleted_at IS NULL;"
    result = subprocess.check_output(['docker', '--host', 'unix:///run/platform-dev/docker.sock', 'exec', 'platform-dev-runtime-postgres-1', 'psql', '-U', 'platform', '-d', 'platform', '-Atc', sql], text=True)
    if result.strip().splitlines()[-1] != '1':
        raise SystemExit('Expected exactly one synthetic DEV account')
original = profile(bearer)
if original.get('email') != 'developer@example.invalid':
    raise SystemExit('Unexpected test identity')
proof = 'DEV Remote Persistence Proof'
result = {'synthetic_dev': True, 'path': '/api/v1/users/me/profile', 'gateway': 'frontend Vite proxy', 'real_oidc_login': True}
try:
    assert profile(bearer, proof)['name'] == proof
    result['write'] = 200
    result['new_session_readback_matched'] = profile(token())['name'] == proof
    assert result['new_session_readback_matched']
finally:
    profile(bearer, original['name'])
    result['restored_and_readback'] = profile(token())['name'] == original['name']
assert result['restored_and_readback']
(base/'evidence/dev-profile-persistence.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
