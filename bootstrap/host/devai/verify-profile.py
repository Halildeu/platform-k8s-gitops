#!/usr/bin/env python3
"""Real HTTPS synthetic DEV profile write, fresh-session read and restoration."""
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, '/srv/platform-dev/ops')
from remote_dev_credentials import load_credentials, require_host

ORIGIN = 'https://devai.acik.com'


def main():
    require_host()
    secret = load_credentials()

    def token():
        form = urllib.parse.urlencode({'grant_type': 'password', 'client_id': 'frontend',
                                      'username': 'developer', 'password': secret['developer']}).encode()
        with urllib.request.urlopen(ORIGIN + '/realms/platform-dev/protocol/openid-connect/token', form, timeout=30) as response:
            return json.load(response)['access_token']

    def profile(bearer, name=None):
        request = urllib.request.Request(ORIGIN + '/api/v1/users/me/profile',
                                         method='GET' if name is None else 'PUT',
                                         data=None if name is None else json.dumps({'name': name}).encode(),
                                         headers={'Authorization': 'Bearer ' + bearer, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    bearer = token()
    original = profile(bearer)
    assert original.get('email') == 'developer@example.invalid'
    proof = 'DEV HTTPS Persistence Proof'
    result = {'origin': ORIGIN, 'synthetic_dev': True, 'tls_bypass': False}
    try:
        assert profile(bearer, proof)['name'] == proof
        result['write'] = True
        result['fresh_session_readback'] = profile(token())['name'] == proof
        assert result['fresh_session_readback']
    finally:
        profile(token(), original['name'])
        result['restored_and_readback'] = profile(token())['name'] == original['name']
        assert result['restored_and_readback']
    result['passed'] = True
    Path('/srv/platform-dev/evidence/devai-20260912/profile.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
