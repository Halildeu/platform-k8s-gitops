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

## 5. GPU immutable source pin, client sertifikası ve DPAPI import

### 5.1 Onaylı source revision'ı pinle

GPU deploy clone'u geliştirme clone'u değildir. `origin/main` yalnız discovery
ref'idir; deploy artifact'i olarak kullanılmaz. İlk private-gateway rollout'u
Project #4 evidence alanına kaydedilmiş `platform-ai` PR
[#254](https://github.com/Halildeu/platform-ai/pull/254) merge commit'ine
pinlenir:

```powershell
$ApprovedCommit = '5b716c3281ba5df4a63c391f6cf13cce62e68a45'
Set-Location C:\platform-ai

# Guard, object ve origin/main ancestry kontrolleri; kaynak mutasyonu yapmaz.
.\deploy\gpu-host\update.ps1 `
  -TargetCommit $ApprovedCommit -NoRestart -WhatIf
if ($LASTEXITCODE -ne 0) {
  throw "Immutable source preflight failed with exit $LASTEXITCODE"
}

# Secret/config provisioning tamamlanmadan servisleri yeniden başlatma.
.\deploy\gpu-host\update.ps1 `
  -TargetCommit $ApprovedCommit -NoRestart -Confirm:$false
if ($LASTEXITCODE -ne 0) {
  throw "Immutable source pin failed with exit $LASTEXITCODE"
}

$StatePath = 'C:\ProgramData\Acik\platform-ai\deployment-state.json'
$State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
if ($State.schemaVersion -ne 1 -or
    $State.currentCommit -ne $ApprovedCommit -or
    $State.lastResult -ne 'pinned-no-restart') {
  throw 'Deployment ledger does not match the approved source pin'
}

$ActualCommit = (git rev-parse HEAD).Trim().ToLowerInvariant()
git symbolic-ref -q HEAD 1>$null 2>$null
if ($ActualCommit -ne $ApprovedCommit -or $LASTEXITCODE -eq 0) {
  throw 'GPU deploy clone is not detached at the approved commit'
}
.\deploy\gpu-host\drift-guard.ps1
if ($LASTEXITCODE -ne 0) {
  throw "Immutable source drift guard failed with exit $LASTEXITCODE"
}
```

`update.ps1` dirty tracked tree, push'lanmamış commit, eksik/short object,
`origin/main` ancestry kopması, malformed/insecure ledger veya mevcut
HEAD/ledger uyuşmazlığında kaynak mutasyonu yapmadan exit `2` döner. Source pin
landed fakat scheduled-task restart başarısızsa exit `3`; rollback mutation ya
da otomatik source restore başarısızsa exit `4` döner. Override, `git pull`,
`git checkout main` ve `git reset --hard origin/main` kullanılmaz.

Sonraki promotion'larda `$ApprovedCommit`, Project #4 Evidence alanındaki yeni
tam 40-hex merge commit olur. Pin yeni `origin/main` soyunda doğrulanmadan
değiştirilmez. İlk pin ledger'da `previousCommit=null` bırakabilir; bu durumda
source rollback yoktur ve önceki revision operatör tarafından tahmin edilmez.

### 5.2 Client sertifikası ve DPAPI import

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

Source pin ve drift guard PASS sonrasında elevated Windows PowerShell 5.1'de,
secure transfer hedef dosyalarıyla:

```powershell
Set-Location C:\platform-ai
.\deploy\gpu-host\configure-private-gateway-host.ps1 `
  -TestHostShim `
  -GatewayHostname 'meeting-ai-gateway.internal' `
  -GatewayIPv4 '10.99.0.1' `
  -Confirm:$false

$secret = Read-Host 'meeting-ai OAuth client secret' -AsSecureString
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

Hosts bootstrap kaynağı `platform-ai` PR
[#254](https://github.com/Halildeu/platform-ai/pull/254) merge commit'i
`5b716c3281ba5df4a63c391f6cf13cce62e68a45` üzerinde immutable pinli olmalıdır;
bu revision PR #252'nin hardened hosts shim'ini de içerir. Script test-only
managed block, aktif çakışma reddi, canonical IPv4/hostname validation,
same-directory atomik replace, semantic ACL postcondition, backup/restore/remove
ve DNS flush + exact IPv4 doğrulaması uygular. Resolver doğrulaması başarısızsa
hosts dosyasını pre-mutation backup'tan otomatik geri alır. Production'da hosts
shim kullanılmaz; `meeting-ai-gateway.internal` split-horizon private DNS ile
çözülür. Ad çözümleme mTLS SAN/CA doğrulamasının yerine geçmez.

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

Önce GPU ingestion default-off yapılır ve task kontrollü restart edilir. Sorun
source revision ile ilişkiliyse operator commit seçmez; yalnız hardened
deployment ledger'daki tek `previousCommit` slotu kullanılır:

```powershell
Set-Location C:\platform-ai
.\deploy\gpu-host\update.ps1 -Rollback -Confirm:$false
switch ($LASTEXITCODE) {
  0 {
    .\deploy\gpu-host\drift-guard.ps1
    if ($LASTEXITCODE -ne 0) {
      throw "Post-rollback drift guard failed with exit $LASTEXITCODE"
    }
  }
  2 { throw 'Rollback guard rejected the request without source mutation' }
  3 { throw 'Previous source pin landed but scheduled-task restart failed' }
  4 { throw 'Rollback mutation or automatic source restore failed' }
  default { throw "Unexpected rollback exit code: $LASTEXITCODE" }
}
```

Başarılı rollback previous slotunu tüketir; aynı iki revision arasında
ping-pong üretmez. `previousCommit=null` ise rollback fail-closed exit `2`
döner. Operator elle SHA vererek rollback yapmaz. Runtime config değişikliği
source rollback gerektirmiyorsa önce DPAPI-protected config'in atomik backup'ı
`configure-meeting-ai.ps1 -RestoreBackup` ile geri alınır ve task yeniden
başlatılır.

Private gateway hosts shim'i kaldırılacaksa:

```powershell
Set-Location C:\platform-ai
.\deploy\gpu-host\configure-private-gateway-host.ps1 `
  -TestHostShim -Remove -Confirm:$false
```

Hosts rollback yalnız platform-ai managed block'unu ve varsa eski runbook'un
aynı hedefe ait dedicated legacy satırını kaldırır; diğer hosts girdileri
korunur. Son pre-mutation state'e dönmek gerekiyorsa `-Remove` yerine
`-RestoreBackup` kullanılır.

Gateway host servisleri için:

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
