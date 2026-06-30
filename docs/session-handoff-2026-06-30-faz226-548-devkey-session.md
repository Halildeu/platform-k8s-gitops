# Session Handoff — 2026-06-30 — Faz 22.6 #548 device-key SESSION strong-path (`:443` yolu geri yüklendi)

> Format: D28 5-alan + sıradaki agent P0 aksiyon listesi
> Standing /goal: "faz 22.6 yı tam otonom, sektör standartlarına uygun, sistem ile uyumlu tamamla"
> Scope: #548 device-key TPM attestation **SESSION** verdict (`deviceTrusted=true / HARDWARE_KEY_ATTESTATION`) — **AgentPC2** (tek device-key-enrolled cihaz).

---

## 1. Bağlam (neden bu handoff)

- #548 strong-path'in **ENROLLMENT** ayağı 2026-06-30 **LIVE-PROVEN** (binding row tam — aşağıda İspatlar). Kalan tek kapı = **device-key SESSION verdict**.
- Bu oturumda **yanlış bir yol** denendi: yeni bir `:9446` socat forwarder + `ufw allow` kuralı. **Kullanıcı düzeltti** — TÜM bilgisayarlarda yalnızca `:443` açık; #208'in kullandığı **sertifikalı, çalışan yol zaten vardı**. Yeni port/firewall icat etmek YASAK. Yol `:443`'e geri taşındı.
- **WireGuard AYRI bir iş** (sunucular-arası güvenli haberleşme, Faz 24 AI data-plane). Bu device-key işiyle **KARIŞTIRILMAZ** (kullanıcı net direktif).

## 2. İddia (bu oturumda yapılan)

- `:443` ssl-passthrough ingress `endpoint-admin-remote-bridge-mtls` pilot broker → **device-key broker'a repoint edildi** (live kubectl patch; port 9444 sabit). Geri alınabilir.
- İcat edilen `:9446` forwarder'lar **KALDIRILDI**; pilot forwarder'lara dokunulmadı.
- (Önceki faz — audit) gitops **PR #2185 MERGED**: Infineon OPTIGA EK-chain pin (enrollment blocker fix) + Vault role `pki_int/roles/tpm-device` `key_type` rsa→ec (live patch — DURABILITY DEBT).

## 3. İspatlar (2026-06-30 — kendi-tarafım/agent-side doğrulama, staging-sw)

| Kanıt | Sonuç |
|---|---|
| `:443` ingress backend | `endpoint-admin-remote-bridge-device-key:9444` ✓ (repoint LIVE) |
| `:443` edge probe (SNI=`remote-bridge-mtls.testai.acik.com`, `openssl s_client -connect 127.0.0.1:443`) | broker server cert `CN=remote-bridge-mtls.testai.acik.com`, issuer `CN=Acik-Endpoint-CA`, valid→2028-06-18 ✓ — uçtan uca `:443` yolu device-key broker'a ulaşıyor |
| broker pod'ları | pilot `…-w9vw4` Running 10h; device-key `…-6c94f` Running 2d5h ✓ |
| device-key runtime verifier env | `DEVICE_KEY_ATTESTATION_REAL` + `KEY_BASED` + `REAL_PKI` + `PERMIT_KID=rb-test-denetim-device-key-20260627-01` ✓ |
| binding row (`endpoint_admin_service.endpoint_tpm_device_binding`) | device `6ed7bd53-83be-4ff3-9f91-7fa3a8b222f3` — ak+ek+spki **TAM**, enrolled `2026-06-30 15:18:52+00`, revoked=**NULL** ✓ |
| `:9446` forwarder cruft | yok (temiz) ✓ |
| permit pubkey + mTLS peer-trust (önceki oturum) | permit pubkey **MATCH** (`PERMIT_BROKER_PUBLIC_KEY_B64=MFkwEwYH…atSLb/Q==`); peer-trust `device_ca_pem`=`CN=platform-test endpoint device CA`= Vault `pki_int` issuing CA = agent device-cert issuer ✓ |

> Routing zinciri (LIVE): AgentPC2 → `remote-bridge-mtls.testai.acik.com:443` → staging-sw host-nginx `stream` SNI map (`kustomize/base/endpoint-agent-mtls/host-nginx-stream-snippet.conf`) → `127.0.0.1:31443` (k3d-test serverlb 443) → ingress-nginx `--enable-ssl-passthrough` → Ingress `endpoint-admin-remote-bridge-mtls` (host-SNI demux) → **device-key broker Service :9444**. ssl-passthrough SNI başına TEK Service bağlar; iki broker AYNI cert/SNI'yi paylaştığı için device-key'e ulaşmanın tek yolu o ingress'i repoint etmek (2. aynı-host ingress eklenemez).

## 4. İspatlamaz (henüz kanıtlanmadı)

- **Device-key SESSION verdict YOK.** Device-key broker logunda son 20 dk HELLO/challenge/handshake/TLS **boş** — agent henüz bağlanmadı.
- **Sebep:** AgentPC2 agent'ı hâlâ `BROKER_ADDR=remote-bridge-mtls.testai.acik.com:9446`'da (STEP 1'de benim değiştirdiğim, forwarder kaldırıldığı için artık kırık). `:443`'e geri alınmalı.
- **AgentPC2 `tpm:`-SAN cert riski** (runbook `RB-faz22.6-548-device-key-session-live-run.md` §3.1 "tek en olası operatör tuzağı"): agent cert check'i daha önce boş döndü. Agent `:443`'e bağlanıp mTLS handshake'e girince teşhis edilecek (henüz görülmedi).

## 5. Bilinen Boşluk + Sıradaki P0 Aksiyon Listesi

### P0 — TEK kalan PC-side aksiyon (AgentPC2, kullanıcının PowerShell'i): agent `BROKER_ADDR` `:9446` → `:443`

remote-bridge **OUTBOUND-ONLY** → AgentPC2'ye inbound yok + kullanıcının aktif login'i kullanılmaz → bu değişiklik **AgentPC2'de** çalışmalı. Servis env'i REG_MULTI_SZ `HKLM\SYSTEM\CurrentControlSet\Services\EndpointAgent\Environment`'tan okur (install.ps1 mekanizması; Codex 019e7314 — Machine env tek başına picked-up DEĞİL, servis registry value merge-write + restart gerek).

Minimal PowerShell (yönetici) — yalnızca BROKER_ADDR'ı `:443`'e alır, diğer device-key env'lerine dokunmaz:

```powershell
$p='HKLM:\SYSTEM\CurrentControlSet\Services\EndpointAgent'
$env=(Get-ItemProperty -Path $p -Name Environment).Environment
$env=$env | Where-Object { $_ -notmatch '^ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR=' }
$env += 'ENDPOINT_AGENT_REMOTE_BRIDGE_BROKER_ADDR=remote-bridge-mtls.testai.acik.com:443'
Set-ItemProperty -Path $p -Name Environment -Value $env
Restart-Service EndpointAgent
```

Değişmeden kalması gereken device-key env'leri (kontrol amaçlı):
`…_REMOTE_BRIDGE_ENABLED=true`, `…_OPERATIONS_ENABLED=true`, `…_DEVICE_KEY_SESSION_ENABLED=true`, `…_INSECURE_PLAINTEXT=false`, `…_TLS_SERVER_NAME=remote-bridge-mtls.testai.acik.com`, `…_PERMIT_KEY_ID=rb-test-denetim-device-key-20260627-01`, `…_PERMIT_BROKER_PUBLIC_KEY_B64=MFkwEwYH…atSLb/Q==`, `…_MTLS_CERT_SAN_URI_PREFIX=tpm:`, `…_PILOT_AUTO_CONSENT=true`. (`…_DEVICE_KEY_*_B64`/`SIGNATURE` software-override'ları hardware yol için UNSET kalmalı.)

### P0-verify (agent tarafı — BEN/sıradaki agent yapar, kullanıcıya ek komut yıkmadan)
Restart sonrası device-key broker logunda **HELLO + mTLS handshake** izle; pod içi ESTABLISHED `:9444` kontrol. Kanıt komutu:
```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test logs -f endpoint-admin-remote-bridge-device-key-c7548d6bc-6c94f --since=2m | grep -iE 'hello|challenge|handshake|tls|peer|verdict|trust'"
```

### P1 — handshake fail ederse: `tpm:`-SAN cert teşhisi (runbook §3.1)
AgentPC2 `LocalMachine\My` içinde `tpm:` URI-SAN cert var mı + private key acquirable mı; yoksa Vault-issued device cert'in store'a doğru yerleştiğini doğrula.

### P1 — attended/auto session → verdict
DeviceKeyChallenge → TPM device-key response → triple-SPKI verify → `deviceTrusted=true / HARDWARE_KEY_ATTESTATION`.

### P2 (owner-gated) — acceptance marker
Verdict alınınca owner `F22_6_B1_4_HARDWARE_ATTESTATION_ACCEPTANCE: v1` mint eder (`scripts/faz22-remote-ops/faz22-6-b1-4-acceptance-package.sh --mode strong`) → **#548 closes**. (Marker forge/self-attest YASAK — owner mints.)

### Durability debt
1. **ingress repoint** live kubectl patch (test'te ArgoCD yok → sticks). Kalıcılık için device-key overlay'i bu ingress'i (veya dokümante edilmiş re-point adımını) gitops'ta sahiplenmeli.
2. Vault role `key_type=ec` live patch — Vault-PKI setup runbook/IaC'a yansıtılmalı (re-seed RSA'ya dönmesin).
3. memory `project-faz22-6-548-devkey-live-enroll-proven` bu oturumda `:443` metoduna güncellendi (önceden terk edilen `:9446` forwarder yöntemini dokümante ediyordu).

---

**Karar kuralı (tek cümle):** `:443` yolu (kendi tarafım) uçtan uca sağlıklı + device-key broker'a repointli; tek kalan = AgentPC2 agent'ını `:9446`'dan `:443`'e geri almak → sonra broker HELLO/handshake izle → verdict → owner marker → #548.
