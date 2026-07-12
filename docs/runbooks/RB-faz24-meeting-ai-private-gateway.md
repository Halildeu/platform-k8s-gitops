# RB-faz24-meeting-ai-private-gateway

## 1. Amaç ve sınır

`meeting-ai-service` GPU hostundan (`10.99.0.2`) staging-sw üzerindeki auth ve
meeting servislerine yalnız aşağıdaki zincirle erişir:

`GPU process -> WireGuard wg0 -> Caddy 10.99.0.1:9445 -> host loopback 127.0.0.1:31080 -> private Ingress -> service`

Kontroller birbirinin yerine geçmez:

- WireGuard transit şifreleme ve iki host arasında private route sağlar.
- Host firewall yalnız `wg0`, `10.99.0.2/32 -> 10.99.0.1/32`, TCP/9445 kabul eder.
- Caddy TLS sunucu kimliğini ve yalnız `meeting-ai` issuance role'una ayrılmış
  dedicated client CA zincirini doğrular. Client role yalnız
  `meeting-ai.client.faz24.internal` adına clientAuth leaf üretebilir.
- Caddy yalnız `POST /oauth2/token`, UUID-scoped analysis-result `POST` ve
  client-authenticated `GET /healthz` yollarını taşır; generic proxy yoktur.
- Auth-service yalnız `meeting-ai` client için `meeting-service` audience ve
  `meeting:analysis-result:write` izniyle kısa ömürlü token üretir.
- Meeting-service issuer, audience, `sub == client_id == svc == meeting-ai` ve
  permission bağlarını tekrar doğrular.

Bu runbook **test aktivasyonu** içindir. Kaynak/CI geçişi canlı bağlantı,
sertifika rotasyonu veya ürün kabulü değildir.

## 2. Secret ve PKI trust-domain ayrımı

Endpoint/device PKI `pki_int` bu kanal için kullanılmaz. İki dedicated test
mount kullanılır:

- `pki_meeting_ai_server`: GPU'nun güvendiği gateway server CA.
- `pki_meeting_ai_client`: Caddy'nin güvendiği tek workload client CA.

Testte self-signed roots kabul edilebilir. Prod için iki mount organizasyon
intermediate CA zincirlerine bağlanır; aynı role/EKU/SAN sınırları korunur.

Vault CLI önceden login olmuş, yetkili operator shell'inde:

```bash
set -euo pipefail
for mount in pki_meeting_ai_server pki_meeting_ai_client; do
  vault secrets list -format=json | jq -e --arg p "${mount}/" 'has($p)' >/dev/null || \
    vault secrets enable -path="${mount}" pki
  vault secrets tune -max-lease-ttl=2160h "${mount}"
done

vault read -field=certificate pki_meeting_ai_server/cert/ca >/dev/null 2>&1 || \
  vault write -field=certificate pki_meeting_ai_server/root/generate/internal \
    common_name='Acik Faz24 Meeting-AI Test Server CA' ttl=2160h \
    key_type=ec key_bits=256 >/dev/null
vault read -field=certificate pki_meeting_ai_client/cert/ca >/dev/null 2>&1 || \
  vault write -field=certificate pki_meeting_ai_client/root/generate/internal \
    common_name='Acik Faz24 Meeting-AI Test Client CA' ttl=2160h \
    key_type=ec key_bits=256 >/dev/null

vault write pki_meeting_ai_server/roles/staging-gateway \
  allowed_domains=meeting-ai-gateway.internal allow_bare_domains=true \
  allow_ip_sans=false server_flag=true client_flag=false \
  key_type=ec key_bits=256 max_ttl=24h
vault write pki_meeting_ai_client/roles/meeting-ai \
  allowed_domains=meeting-ai.client.faz24.internal allow_bare_domains=true \
  allow_ip_sans=false server_flag=false client_flag=true \
  key_type=ec key_bits=256 max_ttl=24h
```

Gateway rotation identity yalnız server role'a erişir:

```bash
vault policy write meeting-ai-gateway-server - <<'EOF'
path "pki_meeting_ai_server/issue/staging-gateway" { capabilities = ["update"] }
path "pki_meeting_ai_server/cert/ca"               { capabilities = ["read"] }
EOF

umask 077
token_file="$(mktemp)"
trap 'rm -f -- "${token_file}"' EXIT
vault token create -orphan -period=48h -policy=meeting-ai-gateway-server \
  -field=token >"${token_file}"
sudo install -o root -g root -m 0600 "${token_file}" \
  /etc/platform/meeting-ai-gateway/vault-token
```

Client issuance operator policy yalnız
`pki_meeting_ai_client/issue/meeting-ai` ve CA read hakkı alır. Root token,
JWT, OAuth secret veya private key terminal çıktısına, issue comment'e ya da
evidence paketine yazılmaz.

## 3. Auth client secret seed

Secret en az 256-bit CSPRNG ile üretilir ve stdout'a yazılmadan Vault'a konur:

```bash
umask 077
secret_file="$(mktemp)"
trap 'rm -f -- "${secret_file}"' EXIT
openssl rand -base64 48 >"${secret_file}"
vault kv patch kv/platform/auth-service service_client_meeting_ai_secret=- \
  <"${secret_file}"
```

`auth-service-secrets` ExternalSecret `Ready=True` ve pod yeni secret revision
ile rollout olmadan GPU yapılandırılmaz. Aynı değer GPU'da
`configure-meeting-ai.ps1 -ClientSecret` SecureString girdisine verilir ve
DPAPI LocalMachine ciphertext olarak saklanır; command line'a yazılmaz.

## 4. Gateway host kurulumu

Repo main merge ve host clone fast-forward sonrası:

```bash
cd /home/halil/platform-k8s-gitops
sudo deploy/staging-sw/meeting-ai-private-gateway/install.sh
```

Server cert rotation için scoped, renewable Vault token root-owned
`/etc/platform/meeting-ai-gateway/vault-token` dosyasına `0600` ile yerleştirilir.
Token yalnız server issuance policy'sine bağlı, periodik ve en az 48 saatlik
period ile üretilir; her sekiz saatlik başarılı job token'ı yeniler. Token expiry
ve rotation failure systemd/monitoring alarmıdır; root token bu dosyada tutulmaz.
Test Vault HTTPS listener CA'sı da
`/etc/platform/meeting-ai-gateway/vault-ca.crt` altında pinlenir; TLS doğrulama
kapatılmaz.
Client CA public certificate:

```bash
sudo sh -c 'VAULT_FORMAT=json vault read pki_meeting_ai_client/cert/ca | \
  jq -er .data.certificate > /etc/platform/meeting-ai-gateway/tls/client-ca.crt'
sudo chown root:caddy /etc/platform/meeting-ai-gateway/tls/client-ca.crt
sudo chmod 0640 /etc/platform/meeting-ai-gateway/tls/client-ca.crt
sudo /usr/local/libexec/platform/meeting-ai-gateway-rotate-server-cert
sudo caddy validate --config /etc/caddy/meeting-ai-private.Caddyfile --adapter caddyfile
sudo systemctl enable --now meeting-ai-gateway-firewall.service
sudo systemctl enable --now meeting-ai-private-gateway.service
sudo systemctl enable --now meeting-ai-server-cert-rotation.timer
```

Rotasyon yeni cert/key çiftini versioned dizinde doğrular, `tls/current`
symlink'ini tek atomik rename ile değiştirir ve ancak sonra Caddy reload eder.
Reload başarısızsa pointer önceki çifte döner; aktif sürümle birlikte son iki
sürüm kontrollü rollback için korunur. Leaf ve issuing CA `server.crt`
fullchain'inde birlikte sunulur; prod intermediate zinciri bu nedenle eksilmez.
Her deneme `/var/lib/node_exporter/meeting_ai_gateway.prom` dosyasını atomik
günceller. `MeetingAIGatewayCertificateRotationFailed`, `...RotationStale` ve
`...CertificateExpiring` kuralları failure, 12 saatlik stale ve 12 saatlik
expiry pencerelerini prod monitoring hub'ına taşır. Test private Ingress KSM'de
göründüğü halde textfile serisi 15 dakika yoksa `MeetingAIGatewayTelemetryAbsent`
ayrıca firing olur; kaynak merge tek başına bu absence alarmını açmaz.

## 5. GPU client sertifikası ve DPAPI import

Yetkili operator client bundle'ı `0700` geçici klasöre üretir. Private key
stdout'a yazılmaz, güvenli yönetim kanalıyla GPU'ya taşınır ve import sonrası
iki uçta silinir:

```bash
umask 077
bundle="$(mktemp -d)"
vault write -format=json pki_meeting_ai_client/issue/meeting-ai \
  common_name=meeting-ai.client.faz24.internal \
  alt_names=meeting-ai.client.faz24.internal ttl=24h >"${bundle}/response.json"
jq -er .data.certificate "${bundle}/response.json" >"${bundle}/client.crt"
jq -er .data.private_key "${bundle}/response.json" >"${bundle}/client.key"
vault read -format=json pki_meeting_ai_server/cert/ca | \
  jq -er .data.certificate >"${bundle}/server-ca.crt"
chmod 0600 "${bundle}"/*
```

Elevated Windows PowerShell 5.1'de, secure transfer hedef dosyalarıyla:

```powershell
$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$mapping = '10.99.0.1 meeting-ai-gateway.internal'
$existingMapping = Select-String -LiteralPath $hostsPath `
  -Pattern '^\s*10\.99\.0\.1\s+meeting-ai-gateway\.internal(?:\s|$)' -Quiet
if (-not $existingMapping) {
  if (Select-String -LiteralPath $hostsPath `
      -Pattern '^\s*\S+\s+meeting-ai-gateway\.internal(?:\s|$)' -Quiet) {
    throw 'meeting-ai-gateway.internal already maps to another address.'
  }
  Add-Content -LiteralPath $hostsPath -Value "`r`n$mapping" -Encoding ASCII
  ipconfig.exe /flushdns | Out-Null
}
$resolvedGateway = @([Net.Dns]::GetHostAddresses('meeting-ai-gateway.internal') |
  Where-Object { $_.ToString() -eq '10.99.0.1' } |
  Select-Object -First 1)
if ($resolvedGateway.Count -ne 1) { throw 'Private gateway DNS resolution failed.' }

$secret = Read-Host 'meeting-ai OAuth client secret' -AsSecureString
Set-Location C:\platform-ai
.\deploy\gpu-host\configure-meeting-ai.ps1 `
  -MeetingServiceBaseUrl 'https://meeting-ai-gateway.internal:9445' `
  -MeetingServiceTokenUrl 'https://meeting-ai-gateway.internal:9445/oauth2/token' `
  -ClientId 'meeting-ai' -ClientSecret $secret `
  -Audience 'meeting-service' `
  -Permission 'meeting:analysis-result:write' `
  -TlsMode mutual `
  -TlsCaPath C:\secure-transfer\server-ca.crt `
  -TlsClientCertPath C:\secure-transfer\client.crt `
  -TlsClientKeyPath C:\secure-transfer\client.key
Remove-Item -LiteralPath C:\secure-transfer\server-ca.crt, `
  C:\secure-transfer\client.crt,C:\secure-transfer\client.key -Force
schtasks.exe /End /TN platform-ai-meeting-ai 2>$null
schtasks.exe /Run /TN platform-ai-meeting-ai
```

## 6. Fail-closed doğrulama

Canlı kabul tek başarılı istek değildir. Redacted evidence aşağıdakilerin
tamamını içermelidir:

1. `ss -lntp`: yalnız `10.99.0.1:9445`, `0.0.0.0:9445` yok.
2. `firewall.sh check` PASS; başka interface/source TCP/9445 deny.
3. Doğru client cert `/healthz` HTTP 200.
4. Client cert yok: TLS handshake fail.
5. Başka CA cert'i: TLS handshake fail.
6. Client CA role/policy negatif testi: role izinli ad dışındaki CN/SAN issuance
   denemesi Vault tarafından reddedilir.
7. Yanlış method/path: HTTP 404; `/oauth2/jwks`, actuator ve admin yüzeyleri yok.
8. Token claim özeti: `iss=auth-service`, `aud=meeting-service`,
   `sub=client_id=svc=meeting-ai`, TTL <= 60 saniye, yalnız write permission.
9. Geçersiz/expired/wrong-audience token ingestion 401; doğru token fakat
   yanlış client/permission 403; geçerli ilk POST 201; aynı Idempotency-Key 200.
10. Meeting-AI task restartında encrypted SQLite outbox korunur, geçici outage
    sonrası drain olur; raw transcript/Authorization/private key loglarda yoktur.
11. Public negative: `testai.acik.com` ve `ai.acik.com` üzerinden
    `/api/v1/internal/meetings/.../analysis-results` route edilmez.
12. Sekiz saatlik sertifika rotation timer sonrası yeni leaf ile kesintisiz istek
    ve alert-fire drill sonucu kaydedilir. Caddy file trust pool CRL/OCSP
    tüketmediği için client leaf iptali anlık değildir; sızıntı halinde firewall
    source block + client CA rollover uygulanır, normal üst sınır 24 saatlik leaf
    TTL'idir.

## 7. Rollback

Önce GPU ingestion default-off yapılır ve task kontrollü restart edilir. Sonra:

```bash
sudo systemctl disable --now meeting-ai-server-cert-rotation.timer
sudo systemctl disable --now meeting-ai-private-gateway.service
sudo systemctl disable --now meeting-ai-gateway-firewall.service
sudo /usr/local/libexec/platform/meeting-ai-gateway-firewall rollback || true
```

Test overlay rollback PR'ı private Ingress resource'unu, meeting verifier
bindings'i ve test-only ESO mapping'i birlikte geri alır. DB'deki daha önce
commit edilmiş analysis run/outbox kayıtları silinmez; rollback data loss veya
history rewrite yapmaz.
