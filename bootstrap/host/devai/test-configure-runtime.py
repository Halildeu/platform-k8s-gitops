import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('runtime', Path(__file__).with_name('configure-runtime.py'))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeConfigTests(unittest.TestCase):
    def test_issuer_changes_but_secrets_and_jwks_do_not(self):
        source = ''.join(f'{k}={runtime.OLD_ISSUER}\n' for k in sorted(runtime.ISSUER_KEYS))
        source += 'SECRET=synthetic=a=b\nKEYCLOAK_JWKS_URI=http://127.0.0.1:33081/certs\n'
        result = runtime.transform_env(source)
        self.assertIn('SECRET=synthetic=a=b\n', result)
        self.assertIn('KEYCLOAK_JWKS_URI=http://127.0.0.1:33081/certs\n', result)
        self.assertEqual(result.count(runtime.ISSUER), 4)
        self.assertEqual(runtime.transform_env(result), result)

    def test_unexpected_issuer_refused(self):
        with self.assertRaises(ValueError):
            runtime.transform_env('KEYCLOAK_ISSUER_URI=https://ai.acik.com\n')

    def test_keycloak_proxy_trust_scoped(self):
        result = runtime.transform_env('KC_HOSTNAME=http://127.0.0.1:33081\nSECRET=synthetic\n', True)
        self.assertIn('KC_PROXY_TRUSTED_ADDRESSES=127.0.0.1\n', result)
        self.assertIn('SECRET=synthetic\n', result)

    def test_other_realm_refused(self):
        with self.assertRaises(ValueError):
            runtime.update_realm({'realm': 'production'})

    def test_client_auth_contract_preserved(self):
        realm = {'realm': 'platform-dev', 'clients': [{'clientId': 'frontend', 'attributes': {'pkce.code.challenge.method': 'S256'}, 'publicClient': True}], 'users': [{'id': 'synthetic'}]}
        result = runtime.update_realm(realm)
        self.assertEqual(result['clients'][0]['webOrigins'][0], runtime.ORIGIN)
        self.assertEqual(result['clients'][0]['attributes']['pkce.code.challenge.method'], 'S256')
        self.assertEqual(result['users'], [{'id': 'synthetic'}])


if __name__ == '__main__':
    unittest.main()
