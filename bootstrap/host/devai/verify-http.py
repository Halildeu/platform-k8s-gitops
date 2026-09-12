#!/usr/bin/env python3
"""Verify the real DEV hostname with normal system DNS and certificate trust."""
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ORIGIN = 'https://devai.acik.com'
APPS = ['suggestions', 'ethic', 'users', 'access', 'audit', 'reporting',
        'schema-explorer', 'endpoint-admin', 'meeting', 'interview-evidence']


def request(path, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(ORIGIN + path, headers=headers or {}), timeout=45) as response:
            return response.status, response.headers.get('Content-Type', ''), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get('Content-Type', ''), b''


def main():
    result = {'origin': ORIGIN, 'tls_bypass': False, 'checks': []}
    checks = result['checks']
    for app in ['shell'] + APPS:
        path = '/remoteEntry.js' if app == 'shell' else '/mfe/' + app + '/remoteEntry.js'
        status, content_type, body = request(path)
        checks.append({'name': app, 'status': status, 'javascript': 'javascript' in content_type and b'export' in body})
        assert status == 200 and checks[-1]['javascript'], app
    status, _, body = request('/realms/platform-dev/.well-known/openid-configuration')
    oidc = json.loads(body)
    assert status == 200 and oidc['issuer'] == ORIGIN + '/realms/platform-dev'
    assert all(oidc[key].startswith(ORIGIN + '/') for key in ('authorization_endpoint', 'token_endpoint', 'jwks_uri'))
    result['oidc_origin'] = True
    for path, expected in [('/api/services', 404), ('/api/services/any/restart', 404),
                           ('/admin/realms/platform-dev', 404), ('/realms/master', 404),
                           ('/actuator/health', 404), ('/api/v1/users', 401)]:
        status, _, _ = request(path)
        checks.append({'path': path, 'status': status, 'expected': expected})
        assert status == expected, path
    assert request('/', {'Origin': 'https://foreign.example'})[0] == 403
    result['foreign_origin_denied'] = True
    invalid_login = urllib.request.Request(ORIGIN + '/realms/platform-dev/login-actions/authenticate',
                                           data=b'', headers={'Origin': 'null'})
    try:
        urllib.request.urlopen(invalid_login, timeout=10)
        raise AssertionError('Login without a bound session must be refused')
    except urllib.error.HTTPError as error:
        assert error.code == 400
    result['unbound_login_form_denied'] = True
    for header in ([], ['-H', 'X-Forwarded-For: 10.9.9.6']):
        code = subprocess.check_output(['curl', '--silent', '--show-error', '--interface', '127.0.0.1', '--max-time', '10', '-o', '/dev/null', '-w', '%{http_code}'] + header + [ORIGIN], text=True)
        assert code == '403', 'untrusted socket peer must not be authorized by XFF'
    result['socket_peer_and_spoofed_xff_denied'] = True
    result['passed'] = True
    Path('/srv/platform-dev/evidence/devai-20260912/http.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
