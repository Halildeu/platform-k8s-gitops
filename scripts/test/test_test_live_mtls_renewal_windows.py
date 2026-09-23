"""Isolated Windows/OpenSSL proof for the exact leaf renewal procedure."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID


@unittest.skipUnless(os.name == 'nt', 'native Windows contract')
class RenewalTests(unittest.TestCase):
    def test_crypto_preservation_dry_run_and_mismatched_leaf_refusal(self):
        workspace = Path(__file__).resolve().parents[3] / 'outputs'
        with tempfile.TemporaryDirectory(prefix='mtls-synthetic-', dir=workspace) as directory:
            root = Path(directory).resolve()
            self.assertTrue(root.is_relative_to(workspace.resolve()))
            now = datetime.now(timezone.utc)
            ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'synthetic-renewal-ca')])
            ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
                  .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
                  .not_valid_before(now-timedelta(days=2)).not_valid_after(now+timedelta(days=365))
                  .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
                  .sign(ca_key, hashes.SHA256()))
            leaf = (x509.CertificateBuilder()
                    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'live-stt.denetim')]))
                    .issuer_name(ca_name).public_key(server_key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now-timedelta(days=2)).not_valid_after(now-timedelta(days=1))
                    .add_extension(x509.SubjectAlternativeName([x509.DNSName('live-stt.denetim')]), False)
                    .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
                    .sign(ca_key, hashes.SHA256()))
            for name, cert, key in (('ca', ca, ca_key), ('server', leaf, server_key)):
                (root / (name+'.crt')).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                (root / (name+'.key')).write_bytes(key.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            (root / 'Caddyfile').write_text('{\n admin off\n}\n', encoding='utf-8')
            source = (Path(__file__).resolve().parents[1] / 'faz24/renew_test_live_mtls.ps1').read_text(encoding='utf-8')
            source = source.replace("$Root = 'C:\\caddy\\certs'", f"$Root = '{root}'")
            source = source.replace("$Caddy = 'C:\\caddy\\caddy.exe'", "$Caddy = 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe'")
            source = source.replace('C:\\caddy\\Caddyfile', str(root/'Caddyfile'))
            source = source.replace('5b7039cb5514ff88eafe6afebdda484b9580a6ea5288a5fdce3157a5a1ed0a23', leaf.fingerprint(hashes.SHA256()).hex())
            source = source.replace('723b3af2c8fdb6cc044bf0297e975c7cb9f6814d4d107c20c1ce5255dbeb17c7', ca.fingerprint(hashes.SHA256()).hex())
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*') if p.is_file()}
            script = root/'fixture.ps1'
            script.write_text(source, encoding='utf-8')
            result = subprocess.run(['powershell', '-NoProfile', '-File', str(script)], capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(next(line.split(':', 1)[1] for line in result.stdout.splitlines() if line.startswith('TEST_MTLS_RENEWAL:')))
            self.assertEqual(report['status'], 'dry-run-validated')
            self.assertTrue(report['samePublicKey'])
            self.assertTrue(report['sameSubjectAlternativeNames'])
            self.assertFalse(report['serverCertificateChanged'])
            for name, digest in before.items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), digest)
            script.write_text(source.replace(leaf.fingerprint(hashes.SHA256()).hex(), '0'*64), encoding='utf-8')
            rejected = subprocess.run(['powershell', '-NoProfile', '-File', str(script)], capture_output=True, text=True, timeout=20)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn('"stage":"preflight"', rejected.stdout)
            self.assertNotIn('PRIVATE KEY', result.stdout + result.stderr + rejected.stdout + rejected.stderr)
            # Exercise real atomic replacement and backup restoration, with only
            # task/native-Caddy calls stubbed so no host service is touched.
            failure_source = source.replace('$Apply = $false # APPLY_MARKER', '$Apply = $true # APPLY_MARKER')
            failure_source = failure_source.replace('$Report.errorClass = $_.Exception.GetType().Name',
                                                    '$Report.errorClass = $_.Exception.GetType().Name; $Report.fixtureError = $_.Exception.Message')
            failure_source = failure_source.replace('function Invoke-Bounded(', 'function Invoke-RealBounded(')
            stubs = '''
function Get-ScheduledTask([string]$TaskName) {
  if ($TaskName -eq 'CaddyI7AppMtls') { return @{State='Running'} }
  return @{State='Ready'}
}
function Get-NetTCPConnection { return @() }
function Invoke-Bounded([string]$Executable, [string[]]$Arguments) {
  if ($Executable -eq $Caddy) { return }
  Invoke-RealBounded $Executable $Arguments
}
$script:restartCalls = 0
function Restart-Caddy {
  $script:restartCalls++
  if ($script:restartCalls -eq 1) { throw 'synthetic-restart-failure' }
}
'''
            failure_source = failure_source.replace('try {\n  Import-Module', stubs + '\ntry {\n  Import-Module')
            script.write_text(failure_source, encoding='utf-8')
            failed = subprocess.run(['powershell', '-NoProfile', '-File', str(script)], capture_output=True, text=True, timeout=45)
            self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
            failure_report = json.loads(next(line.split(':', 1)[1] for line in failed.stdout.splitlines() if line.startswith('TEST_MTLS_RENEWAL:')))
            self.assertTrue(failure_report['rollbackAttempted'], failure_report)
            self.assertTrue(failure_report['rollbackSucceeded'], failure_report)
            self.assertFalse(failure_report['serverCertificateChanged'])
            for name, digest in before.items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
