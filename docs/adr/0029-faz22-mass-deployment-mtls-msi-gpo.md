# ADR-0029 — Faz 22 Endpoint Agent Mass Deployment: mTLS self-enroll + AD CS code signing + MSI + GPO

**Status:** Proposed (Plan A, owner-approved 2026-05-26, iter-6 Codex REVISE 3 finding absorbed; iter-7 review pending)
**Decision date:** 2026-05-26
**Authors:** Halil Koçoğlu, AI agent (Claude)
**Cross-AI review:** Codex (OpenAI) review chain — thread `019e665f` (iter-1 REVISE 10 finding + iter-2 REVISE 6 high/medium + 6 yeni risk → iter-3 absorbed); thread `019e667f-98a5-7980-8f80-613fc1a1ed82` (iter-4 REVISE 5 finding F1-F5 → iter-5 absorb f45b7a2; iter-5 REVISE 4 finding F1-F4 → iter-6 absorb 3e5570f; iter-6 REVISE 3 finding F1-F3 → iter-7 absorb this commit; iter-7 review pending)
**Scope addition statement:** Bu ADR **ADR-0012 §22.2'yi AMEND ETMEZ ve §22.3 Restricted (historical, ex-22.3 renamed 2026-05-26 → §22.4 Restricted) tier'ını SUPERSEDE ETMEZ** — mevcut 22.2.A non-domain primary + 22.2.B `acik.local` opsiyonel scope kararı **KORUNUR**; eski "22.3 Restricted" tier (advanced production pilot) ADR-0012'de §22.4 Restricted olarak yeniden numaralandırıldı (semantik aynı, Faz numbering note bkz ADR-0012 §22.3 scope addition öncesi). Bu ADR Faz 22 portföyüne **22.3 olarak YENİ scope (mass deployment)** ekler: domain-joined Windows fleet'i için **mass deployment via mTLS + AD CS + MSI + GPO Software Installation** kanalı. 22.2.A workgroup pattern (SRB-AIDENETIMPC + benzer) **AYRI PATH** olarak korunur (AnyDesk + manual install via PR #1070 evidence). PLAN.md + ADR-0012 + RB headers truth-sync **bu iter-4 absorb içinde aynı PR'da** yapılır.
**Related:**
- ADR-0012-EA Endpoint Admin Governance Charter (§22.2 scope amendment 2026-05-24 + §22.3 scope ADDITION 2026-05-26 — bu ADR scope addition; eski §22.3 Restricted tier §22.4'e renamed)
- RB-faz22-non-domain-windows-pilot.md (22.2.A non-domain primary path KORUNUR; identity model 22.2.A bearer-token, 22.3 SAN URI:adcomputer:{objectGUID} primary — ayrı)
- RB-faz22-endpoint-pilot-it-owned.md (22.2.B opsiyonel `acik.local` pilot KORUNUR — 22.3 paralel üçüncü kanal)
- RB-faz22-strategy-d-dc-orchestrated-install.md (Strategy D superseded by GPO Software Installation in domain-joined 22.3 path)
- PR #1070 (SRB-AIDENETIMPC A1 workgroup pattern, korunur)
- Codex strategic consult thread `019e634a` (2026-05-26 HYBRID önerisi, owner-rejected)
- Codex ADR review thread `019e665f` (iter-1 REVISE + iter-2 REVISE + iter-3 absorb) + iter-4 review thread `019e667f` (iter-4 REVISE 5 finding F1-F5 → iter-5 absorb)

---

## Context

### Faz 22 mevcut durum

Faz 22 endpoint agent (Go, Windows) backend control-plane (`endpoint-admin-service`) ile birlikte BE-011/BE-013/BE-014/BE-016/BE-017 kabiliyetlerini production-grade olarak sağlıyor. Single-device pilot kanıt mevcut: **SRB-AIDENETIMPC** (workgroup PC) AnyDesk pattern ile manuel install + enroll (PR #1070); command lifecycle SUCCEEDED 2026-05-26 12:30 TR (COLLECT_INVENTORY).

### Sorun: 800 PC mass deployment yokluğu

Hedef corp ortamı: ~800 Windows PC, acik.local AD domain, 10.9.2.x + 10.9.161.x + diğer corp subnet'ler. DC subnet 10.9.10.x cross-subnet firewall block (inbound RDP/SMB/WinRM/WMI/RPC).

**9 saatlik AGENTPC2 install denemesi** (2026-05-26 gece-sabah) net durumu ortaya çıkardı:
- ✅ DC'de GPO Computer Preferences > Scheduled Tasks deploy edildi
- ✅ AGENTPC2 GPO download yaptı (Event 5145 kanıt)
- ❌ **install fire ETMEDI** — periodic refresh + StartWhenAvailable=true + BootTrigger + LogonTrigger redundant pattern fail
- ❌ Backend enrollment yok (token consumed=null)

**Corp ortam keşfi** (DC management plane discovery):
- ❌ SCCM/Intune/PDQ/ManageEngine/WSUS YOK
- ❌ Centralized endpoint deployment kanalı YOK
- ✅ Zabbix Agent corp standard (read-only monitoring)
- ✅ AD CS rolü kurulabilir (Windows Server built-in, ücretsiz)
- ✅ IT muhtemelen "elden manuel + AnyDesk client-side" pattern kullanıyor

### Faz 22 agent'ın critical eksik

Mevcut agent **self-enrollment desteklemiyor** — her PC için manuel `POST /endpoint-enrollments` çağrısı ile single-use token mint gerekiyor. 800 PC = 800 manuel mint = imkansız.

### Strategic decision context: Codex HYBRID önerisi vs Plan A

Codex stratejik consult (thread `019e634a`, 2026-05-26 sabah) HYBRID önerisi verdi: Wazuh/native commodity telemetry + Faz 22 control-plane (OpenFGA + BE-017 + BE-016 + UI). Custom Windows agent rollout çekilsin.

**Owner kararı 2026-05-26 (Halil)**: Plan A — Faz 22 custom agent production rollout DEVAM. Eşsiz değer önerileri (OpenFGA fine-grained authz, BE-017 dual control, BE-016 hash-chain audit, custom backend UI) corp ihtiyacı için yatırıma değer; Wazuh pivot reddedildi.

Bu ADR Plan A'nın detaylı uygulama mimarisini canonical olarak işler.

---

## Decision

Faz 22 endpoint agent 800 PC mass deployment için aşağıdaki **6-katman** mimari benimsenir (Codex iter-1 önerisiyle **Phase 0 preflight** eklendi):

0. **Phase 0 — Preflight evidence checklist** (gate, herhangi bir deploy adımı öncesi zorunlu)
1. **AD CS (Active Directory Certificate Services)** — corp internal CA, ücretsiz, Windows Server rolü; machine certificate auto-enrollment GPO ile her **domain-joined** PC'ye TPM-attested cert mint
2. **Backend mTLS self-enrollment endpoint** — `POST /api/v1/endpoint-admin/endpoint-enrollments/auto` (yeni); **client cert'ten backend-derived identity** (body'den değil), AD computer SID/GUID stable identity + cert thumbprint chain
3. **Agent auto-enroll feature** — `--auto-enroll` flag; TPM cert ile mTLS-continuous (token sadece cert sahibi tarafından kullanılabilir)
4. **MSI package (WiX Toolset)** — `endpoint-agent.exe` → `endpoint-agent.msi`; ProductCode/UpgradeCode versioned, MST transform ile APIURL property, **internal Windows signing runner** ile imzalı (GitHub Actions PFX YASAK)
5. **GPO Software Installation** — Computer Configuration > Software Settings > Software Installation; package `\\ACIKDC01\endpoint-agent-deploy\endpoint-agent.msi`; deployment **Assigned to Computer** (boot anında OS-level install); wave-based security group control

### Pilot ramp-up (revize)

| Phase | PC | Süre | Acceptance |
|---|---|---|---|
| **Phase 0** | DC + 1 test domain PC | 2-3 gün | Tüm preflight evidence kanıt PASS |
| Phase 1 | **5 PC, sadece domain-joined** (AGENTPC2 + AGENTPC1/MKR-A1 + HALILKOCOGLU + 2 IT volunteer; SRB-AIDENETIMPC workgroup için **AYRI install path**) | 1 hafta | Objektif kanıt source-of-truth ile (aşağıda) |
| Phase 2 | 50 PC (IT department, domain-joined) | 1 hafta | 95%+ install + 90%+ heartbeat 24h |
| Phase 3 | 800 PC (full Domain Computers) | 1-2 hafta | Wave 200/gün, <5% fail rate per wave |

### Code signing strategy (revize)

**Karar**: **Internal/private CA-issued code signing cert** (AD CS Enterprise CA template), Windows Server built-in, ücretsiz. Wazuh/OSQuery pattern ile uyumlu. Private key custody: **internal Windows signing runner** (HSM-backed veya non-exportable TPM key); GitHub Actions PFX **YASAK** (Codex security finding).

**Reddedilen alternatifler**:
- ❌ EV Code Signing cert (~$300-500/yıl) — corp internal scope için overkill
- ❌ GitHub Actions PFX + password — Codex iter-1 RED flag (key custody zayıflık)
- ❌ Unsigned — Defender/AppLocker conflict riski

---

## Detailed design

### Phase 0 — Preflight evidence checklist (yeni, Codex önerisi)

**Hedef**: Hiçbir mass deployment adımı bu Phase 0 gate'i geçmeden başlamaz. Gerçek operasyonel risk profili sahada doğrulanır.

**Phase 0 checklist** (DC + 1 test domain PC üzerinde):

| # | Check | Acceptance | Source |
|---|---|---|---|
| P0-1 | **Domain join membership** | Test PC `(Get-WmiObject Win32_ComputerSystem).PartOfDomain` = True | PowerShell |
| P0-2 | **Secure channel health** | `Test-ComputerSecureChannel -Verbose` PASS | PowerShell |
| P0-3 | **gpresult /scope:computer** test PC'de | Bizim GPO link görünür + Apply'lanmış (filtered değil) | Test PC PowerShell |
| P0-4 | **OU/scope kanıt** | Hedef PC'lerin DN'i + Computers OU veya custom OU bilgisi + GPO link target | `Get-ADComputer` + `Get-GPInheritance` |
| P0-5 | **Machine account UNC read** | DC share `\\ACIKDC01\endpoint-agent-deploy` test PC'den `dir` ile listable (machine account context) | Test PC admin PSSession |
| P0-6 | **"Always wait for the network at computer startup and logon"** GPO | Computer Config > Administrative Templates > System > Logon = Enabled | GPO check |
| P0-7 | **Slow-link policy** detection | `Get-ItemProperty 'HKLM:\Software\Policies\Microsoft\Windows\Group Policy'` slow link threshold > corp WAN reality | Registry |
| P0-8 | **GPO Software Installation CSE health** | Application Event Log Source `Application Management` veya `MsiInstaller` errors yok | Event Log |
| P0-9 | **MSI install Event Log baseline** | Test MSI (1KB no-op) install + Event Log entry verify | Test MSI deploy |
| P0-10 | **AD CS cert auto-enrollment Event Log** | Test PC `Get-WinEvent -ProviderName "Microsoft-Windows-CertificateServicesClient-AutoEnrollment"` PASS | Event Log |
| P0-11 | **TPM availability** | `Get-Tpm` test PC'de Enabled + Ready | PowerShell |
| P0-12 | **mTLS reachability test** | DEVICE_API_BASE_URL `https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-admin` mTLS handshake + no-cert negative test (handshake reject expected) | openssl s_client veya PowerShell mTLS test |
| P0-13 | **Ingress mTLS termination kanıtı** | nginx ingress mTLS passthrough config + canlı route smoke (request endpoint pod'a kadar mTLS context taşır mı kanıt) | Cluster config inspect + tcpdump/Wireshark veya backend audit cert ext log |
| P0-14 | **CRL/OCSP reachability** | AD CS CRL URL test PC'den reachable + cache invalidation < 7 gün; **plus CRL outage davranış testi**: CRL endpoint disable + backend response — **enrollment-time davranış**: fail-closed default expected (yeni cert validation reddedilir); **already-enrolled davranış (R24, iter-6 F2 bounded formula)**: `grace_until = min(cert_not_after, last_good_revocation_check + 24h)` — 24h hard cap last good CRL check'inden itibaren, cert_not_after üst limit; long-lived cert + uzun CRL outage senaryosunda fail-closed enforced (grace yıllarca uzayamaz); plus agent batch alert (>%10 device grace state) | curl + certutil + simulated CRL outage (2 sub-scenario: (a) yeni enroll fail-closed, (b) already-enrolled grace bounded formula verify + near-expiry hard-cap test) |
| **P0-15** | **SYSTEM context UNC share read** | Test PC `psexec -s cmd /c "dir \\\\ACIKDC01\\endpoint-agent-deploy"` SYSTEM context PASS (admin PSSession değil) | PsExec SYSTEM context |
| **P0-16** | **Backend-to-AD LDAPS reachability** | Backend pod from cluster network → DC LDAPS (port 636) reachable; service account read computer object SID/GUID | kubectl exec backend pod + ldapsearch |
| **P0-17** | **Time sync (Kerberos clock skew)** | DC + corp PC ≤ 5 dk clock skew (`w32tm /query /status` veya `Get-Date` cross-check) | w32tm |
| **P0-18** | **EDR/WDAC/AppLocker baseline check** | Trusted Publisher AD CS root cert AppLocker policy + Defender exclusion install dir + WDAC signer rule (varsa) | gpresult AppLocker + Defender PowerShell |
| **P0-19** | **Trusted Publisher store** | Test PC `Cert:\LocalMachine\TrustedPublisher` AD CS code signing cert thumbprint mevcut (manuel test install öncesi) | Certificates MMC |
| **P0-20** | **Proxy/TLS inspection** | Corp proxy/TLS inspection AD CS root cert intercept etmez (mTLS handshake passthrough) | mitmproxy/Wireshark veya proxy config inspect |
| **P0-21** | **Egress firewall (mTLS host)** | Corp PC subnet → `endpoint-agent-mtls.testai.acik.com` (port 443 standart SNI) egress allow | Test PC TCP probe |
| **P0-22** | **Fleet TPM readiness sample** | 10 PC sample → `Get-Tpm` Enabled + Ready ratio (≥95% expected); ratio düşükse mass deploy scope reduce | PowerShell sample |
| **P0-23** | **Cert SAN URI:adcomputer:{objectGUID} verify (iter-4 F2 + iter-6 F1 absorb)** | Test PC machine cert mint edildikten sonra `certutil -store -enterprise My <thumbprint>` (LocalMachine\My store, `-user` flag YOK — machine cert) → output SAN section'da `URL=adcomputer:<guid>` extension'ı mevcut; **plus** doğrulama: DirectorySearcher (RSAT-free) ile `objectGUID` LDAP query + cert SAN URI içindeki GUID match etmeli (renewal-safe binding garanti) | certutil LocalMachine\My + DirectorySearcher cross-check |

**P0 fail** → **mass deploy fire YASAK**. Önce P0 fail noktası fix.

### Katman 1 — AD CS (Active Directory Certificate Services)

**Setup adımları** (Windows Server 2022 DC):

```powershell
# 1. Role install
Install-WindowsFeature ADCS-Cert-Authority -IncludeManagementTools

# 2. CA initialize (Enterprise Root CA, key TPM-protected ise tercih)
Install-AdcsCertificationAuthority -CAType EnterpriseRootCA `
  -CACommonName "ACIK Endpoint CA" `
  -KeyLength 4096 -HashAlgorithm SHA256 `
  -CryptoProviderName "Microsoft Platform Crypto Provider"  # TPM-backed

# 3. Machine cert template (duplicate Computer)
# certtmpl.msc → "Computer" → Duplicate → "EndpointAgent-MachineCert"
#  - Subject Name: Build from AD info: CN = $Computer.DNSHostName
#  - **SAN (built-in)**: User Principal Name (UPN) + DNS name (Build from AD)
#  - Key Usage: Digital Signature + Key Encipherment
#  - EKU: Client Authentication (1.3.6.1.5.5.7.3.2)
#  - Compatibility tab: Windows Server 2016+ / Windows 10+
#  - Cryptography tab: Provider "Microsoft Platform Crypto Provider" (TPM-only)
#  - Issuance Requirements: TPM attestation required
#
# 4. Custom URI:adcomputer:{objectGUID} SAN extension — GPO startup script mekanizması
#    (iter-4 F2 absorb + iter-6 F1 absorb: RSAT-free DirectorySearcher + 3-step certreq -new/-submit/-accept)
# Standart AD CS template Auto-Enrollment URI extension'ı dinamik objectGUID ile basamaz.
# Çözüm: GPO Computer Configuration > Startup Scripts > PowerShell:
#   Enroll-EndpointAgentCert.ps1 (deploy via GPO scope same as MSI):
#
#   # RSAT-free: DirectorySearcher (built-in .NET, no PSModule dependency)
#   $searcher = [System.DirectoryServices.DirectorySearcher]::new()
#   $searcher.Filter = "(&(objectClass=computer)(name=$env:COMPUTERNAME))"
#   $searcher.PropertiesToLoad.Add("objectGUID") | Out-Null
#   $result = $searcher.FindOne()
#   if (-not $result) { Write-Error "Computer object not found in AD"; exit 1 }
#   $guidBytes = $result.Properties["objectguid"][0]
#   $guid = ([System.Guid]::new($guidBytes)).ToString().ToLower()
#
#   $domain = (Get-WmiObject Win32_ComputerSystem).Domain
#   $dnsName = "$($env:COMPUTERNAME).$domain"
#
#   # Idempotent: skip if existing machine cert with matching SAN URI exists
#   $existingCert = Get-ChildItem Cert:\LocalMachine\My | Where-Object {
#       $_.Subject -like "CN=$dnsName*" -and
#       $_.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" -and ($_.Format($false) -match "URL=adcomputer:$guid") }
#   }
#   if ($existingCert) { exit 0 }
#
#   # certreq 3-step flow (valid syntax: -new → -submit → -accept)
#   $inf = @"
#   [NewRequest]
#   Subject = "CN=$dnsName"
#   KeySpec = 1
#   KeyLength = 2048
#   Exportable = FALSE
#   MachineKeySet = TRUE
#   ProviderName = "Microsoft Platform Crypto Provider"
#   RequestType = PKCS10
#
#   [RequestAttributes]
#   CertificateTemplate = "EndpointAgent-MachineCert"
#
#   [Extensions]
#   2.5.29.17 = "{text}"
#   _continue_ = "dns=$dnsName&"
#   _continue_ = "URL=adcomputer:$guid"
#   "@
#   $infFile = "$env:TEMP\endpoint-agent-cert.inf"
#   $reqFile = "$env:TEMP\endpoint-agent-cert.req"
#   $cerFile = "$env:TEMP\endpoint-agent-cert.cer"
#   $inf | Out-File -FilePath $infFile -Encoding ASCII -Force
#
#   # Step 1: -new (create request from INF)
#   certreq.exe -new -q -f $infFile $reqFile
#   if ($LASTEXITCODE -ne 0) { Write-Error "certreq -new failed"; exit 1 }
#
#   # Step 2: -submit (submit to CA, get cert)
#   certreq.exe -submit -q -f -config "ACIKDC01\ACIK Endpoint CA" $reqFile $cerFile
#   if ($LASTEXITCODE -ne 0) { Write-Error "certreq -submit failed"; exit 1 }
#
#   # Step 3: -accept (install cert to LocalMachine\My with private key binding)
#   certreq.exe -accept -q -f -machine $cerFile
#   if ($LASTEXITCODE -ne 0) { Write-Error "certreq -accept failed"; exit 1 }
#
#   Remove-Item $infFile, $reqFile, $cerFile -Force -ErrorAction SilentlyContinue
#
# 5. Auto-renewal — GPO Computer Schedule Task (deploy via same GPO):
#   Trigger: At 03:00, daily; Action: PowerShell -File Enroll-EndpointAgentCert.ps1
#   Idempotent — yeni cert mint sadece existing SAN URI absent veya cert expiry < 30 gün ise
#
# Alternative (operasyonel basit): CEP/CES (Certificate Enrollment Web Services)
#   - Custom enrollment policy ile URI SAN extension AD CS template'e bound,
#     ama implementation karmaşık (Web Services + IIS + policy/server pair install)
#   - Şu an Plan: GPO startup script + certreq inf (simpler, durable, no extra infra)
#
# 6. AutoEnrollment GPO (built-in Windows cert)
#   Computer Configuration > Windows Settings > Security > Public Key Policies >
#     Certificate Services Client - Auto-Enrollment = Enabled + Renew expired/update pending
#   Bu BUILT-IN AD cert renewal'ı handle eder; URI SAN extension için GPO startup script gerek (yukarı).
#  - Validity: 2 yıl, auto-renew at 80%
# NOT: SAN URI:adcomputer:{objectGUID} backend identity binding primary kaynak (Codex iter-3 finding)

# 4. Code Signing template (duplicate Code Signing)
# certtmpl.msc → "Code Signing" → Duplicate → "EndpointAgent-CodeSign"
#  - Subject: CN=EndpointAgent CodeSign, OU=ACIK Build
#  - Key Usage: Digital Signature
#  - EKU: Code Signing (1.3.6.1.5.5.7.3.3)
#  - Validity: 1 yıl
#  - Issuance: manuel certreq (dev/build runner only)

# 5. AutoEnrollment GPO
# Computer Config > Policies > Windows Settings > Security Settings >
#   Public Key Policies > Certificate Services Client - Auto-Enrollment
#   → Enabled (renew expired + update pending + update from template)
# Scope: Domain Computers

# 6. CRL publish (HTTP, AIA + CDP)
# AD CS Properties > Extensions → CRL Distribution Point
#   http://crl.acik.local/CertEnroll/<CAName><CRLNameSuffix>.crl
# IIS site or simple HTTP serve from share
```

**Acceptance**:
- ✅ Test PC reboot/gpupdate sonrası TPM-attested cert mint (Certificates MMC = Personal store)
- ✅ Code Signing cert development workstation'da issued
- ✅ Root CA cert tüm Domain Computers Trust store'unda (gpresult kanıt)
- ✅ CRL URL HTTP reachable + cert chain validation PASS

### Katman 2 — Backend mTLS self-enrollment endpoint (revize)

**Critical Codex iter-1 finding**: machine_fingerprint backend'in **client cert'ten** türetmesi gerekir, request body'den değil (spoofing prevention).

**Critical Codex iter-2 finding (route/identity)**:
- **DEVICE_API_BASE_URL** explicit, separate SNI/port (TLS passthrough path-based routing yapamaz)
- Identity binding: SID/GUID **cert SAN/extension** içinde (otherwise CN reuse/rejoin/stale risk)

**API surface split**:

| Surface | Base URL | mTLS required? | Routing |
|---|---|---|---|
| **Device API** (auto-enroll + heartbeat + command poll/result) | `https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-admin` (canonical; `:8443` lab fallback non-canonical) | ✅ MANDATORY | Separate Ingress + Service, mTLS passthrough, standart port 443 SNI |
| **Admin API** (UI Yönetim > Uç Birimler, command queue, audit query) | `https://testai.acik.com` | ❌ JWT-only | Mevcut nginx ingress, no breaking change |

**Karar**: SNI ayrı host (`endpoint-agent-mtls.testai.acik.com`) — TLS passthrough basit + audit chain net. Ayrı Service + Ingress + Cluster IP, mevcut admin/UI traffic ile çakışmaz.

**Identity binding strategy (revize)**:
- **Primary**: Cert SAN extension `URI:adcomputer:{objectGUID}` (AD CS template ile mint; certreq policy.inf'de SAN extension)
- **Fallback**: Subject CN → backend AD LDAPS lookup → SID/GUID (CN reuse guard: rejoin durumunda eski SID match olmazsa **AUTO_ENROLL_DENIED** + alert)
- **Audit**: thumbprint sadece audit field, identity değil

**Yeni endpoint** (Spring Boot, `endpoint-admin-service`):

```
POST /api/v1/endpoint-admin/endpoint-enrollments/auto
Content-Type: application/json
[MANDATORY: Client mTLS cert; backend validates chain to AD CS Root CA]

Request body (minimal, identity NOT carried in body):
{
  "os_info": {
    "os_type": "WINDOWS",
    "os_version": "10.0.26100",
    "architecture": "amd64"
  },
  "agent_version": "0.2.0"
}

Backend processing:
1. Extract client cert from TLS handshake
2. Validate cert chain to AD CS Root CA
3. Check EKU = Client Authentication (1.3.6.1.5.5.7.3.2)
4. Check template OID = "EndpointAgent-MachineCert"
5. Check issuer = "CN=ACIK Endpoint CA"
6. Check SAN/CN domain suffix = ".acik.local"
7. Check key usage = Digital Signature + Key Encipherment
8. CRL/OCSP revocation check (cached 24h)
9. Extract STABLE IDENTITY (renewal-safe, **SAN primary**):
   - **Primary**: cert SAN extension `URI:adcomputer:{objectGUID}` (template mint sırasında dahil edildi — bkz Katman 1)
   - **Fallback**: SAN absent ise Subject CN → backend LDAPS lookup → SID/GUID
   - **Reuse guard**: AD lookup'ta computer object'in mevcut SID'i ile son ENDPOINT_AUTO_ENROLLED audit'taki SID match olmazsa (CN reuse / rejoin / stale obj) → **AUTO_ENROLL_DENIED** + alert
   - Thumbprint: sadece audit field, identity DEĞİL
10. Idempotency: SID match → existing device_id return (re-enroll = no duplicate, cert renewal-safe)
11. Service token: short-lived (24h) bound to cert thumbprint; subsequent heartbeat/command calls require mTLS-continuous (cert-bound bearer)
12. Audit event: ENDPOINT_AUTO_ENROLLED with {cert_subject_cn, ad_sid, thumbprint, source_ip}

Response (200):
{
  "device_id": "<uuid>",
  "service_token": "<jwt 24h cert-bound>",
  "token_expires_at": "<iso8601>",
  "is_existing_device": true|false
}
```

**Critical security model** (Codex iter-1 findings absorbed):
- Identity = AD SID/GUID (renewal-safe), thumbprint sadece audit log
- Service token cert-bound — kullanılması için aynı mTLS cert şart (DPAPI machine scope + strict ACL)
- mTLS-continuous: heartbeat/command APIs de mTLS required (token tek başına bypass etmez)
- Rate limiting: 10 enrollment/min **per SID** (NAT/proxy IP yanlış throttling önle)
- Token rotation: 24h short-lived, refresh continuous mTLS ile

**TLS termination strategy** (Codex iter-1 ek finding):
- nginx ingress mTLS **passthrough** (TLS sonlanma backend pod'da)
- Veya: ingress mTLS terminate + `X-Client-Cert` header forward (güvenli proxy chain)
- Karar: **passthrough** (basit + audit chain net) — ingress config Phase 0'da kanıtlanır

**Backend implementation**:
- Spring Boot mTLS: `server.ssl.client-auth=need` + Pod-direct TLS (passthrough ingress)
- Trust store: AD CS Root CA bundle (cert chain validation)
- Audit: ENDPOINT_AUTO_ENROLLED + ENDPOINT_AUTO_ENROLL_DENIED (CRL fail, template mismatch, etc.)

**Mevcut endpoint coexistence**:
- Manuel single-use enrollment (`POST /endpoint-enrollments`) korunur (test fixture pattern için)
- Auto-enrollment ek katman, mevcut breaking change yok

**Dev efforu**: ~5-6 gün (mTLS passthrough ingress + endpoint impl + cert-bound token + audit + test)

### Katman 3 — Agent auto-enroll feature (revize)

**Agent enhancements** (`platform-agent` Go repo):

```go
// New CLI flag
// IMPORTANT (iter-4 F1): --api-url FULL canonical base path including /api/v1/endpoint-admin
// Backend join only relative segment ("/endpoint-enrollments/auto", "/endpoint-heartbeat" etc.)
// Wrong: --api-url=https://endpoint-agent-mtls.testai.acik.com (path düşer)
// Right: --api-url=https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-admin
endpoint-agent --auto-enroll [--api-url=https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-admin]

// iter-6 F4 absorb: jitter config from registry (MSI persisted to HKLM)
// MSI writes EnrollmentJitterSeconds to HKLM\SOFTWARE\EndpointAgent at install time
// Agent service startup reads + applies random delay BEFORE auto-enroll call
jitterSec := readRegistryInt("HKLM:\\SOFTWARE\\EndpointAgent", "EnrollmentJitterSeconds", 0) // 0 = no jitter
if jitterSec > 0 && !configExists() {
    delay := time.Duration(rand.Intn(jitterSec)) * time.Second
    log.Printf("auto-enroll jitter: sleeping %v (R26 mass enrollment storm mitigation)", delay)
    time.Sleep(delay)
}

// First-run logic (mTLS-continuous, NOT token-only)
if !configExists() {
    cert := loadMachineCertFromWindowsStore() // Personal store, EndpointAgent-MachineCert template OID
    if cert == nil {
        log.Fatal("Machine cert not found — AD CS auto-enrollment may not have completed yet, retry in 5 min")
    }

    // mTLS client config (cert-bound tüm istekler için)
    httpClient := createMtlsClient(cert)

    // F1 absorb: apiUrl = full base path (canonical: https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-admin)
    // Path join sadece relative segment ekler — base path /api/v1/endpoint-admin korunur
    resp := httpClient.Post(apiUrl + "/endpoint-enrollments/auto", {
        os_info: collectOsInfo(),
        agent_version: VERSION,
    })

    persistConfig({
        device_id: resp.device_id,
        service_token: resp.service_token,  // cert-bound, 24h
        token_expires_at: resp.token_expires_at,
    })
}

// All subsequent calls (heartbeat, command poll, result post)
//   MUST use mTLS-continuous + cert-bound token
heartbeatLoop(httpClient, serviceToken) // cert-bound, mTLS required
commandPollLoop(httpClient, serviceToken)

// Token rotation (24h, auto)
if tokenExpiresIn(2 * time.Hour) {
    rotateToken(httpClient) // refresh via mTLS, new cert-bound token
}

// Cert renewal handling
if certExpiresIn(7 * 24 * time.Hour) {
    // AD CS auto-renewal triggers; new cert mint, agent reload
    // SID stable → backend dedupe, device_id korunur
    reloadCertFromStore()
}
```

**Service token storage**: DPAPI machine scope + strict ACL (LocalSystem + Administrators only, write deny WorldEveryone).

**Tests**:
- Unit: cert load + mTLS client config + cert-bound token validation
- Integration: 3 backend test fixture device auto-enroll + token rotation + cert renewal scenario
- E2E: SRB-AIDENETIMPC migrate test (mevcut device auto-enroll trigger, dedupe verify)

**Dev efforu**: ~3-4 gün (cert load + mTLS-continuous client + token DPAPI + tests)

### Katman 4 — MSI package (WiX Toolset, revize)

**WiX project** (`platform-agent/installer/`):

```xml
<Wix>
  <Product Id="*"
           Name="ACIK EndpointAgent"
           Version="0.2.0"
           Manufacturer="ACIK Platform"
           UpgradeCode="{FIXED-GUID-UPGRADE-CODE-NEVER-CHANGE}">

    <Package InstallScope="perMachine" InstallerVersion="500" Compressed="yes" />

    <!-- Upgrade behavior (critical for GPO Software Installation) -->
    <MajorUpgrade
      Schedule="afterInstallInitialize"
      DowngradeErrorMessage="A newer version is already installed."
      AllowSameVersionUpgrades="no" />

    <!-- Properties (overridable via MST transform) -->
    <!-- F1 absorb: APIURL = full canonical base path including /api/v1/endpoint-admin -->
    <Property Id="APIURL" Value="https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-admin" Secure="yes" />
    <Property Id="ARPHELPLINK" Value="https://testai.acik.com/endpoint-admin" />
    <Property Id="ARPNOREPAIR" Value="1" />
    <Property Id="ENROLLMENTJITTERSECONDS" Value="300" Secure="yes" /> <!-- F5 absorb: agent reads this; randomized 0-N at startup -->
    <!-- R26 jitter MSI'da Type 51 ile yapılamaz (Type 51 property set, command execution değil).
         Jitter agent service startup'ta `EnrollmentJitterSeconds` config'i okur + random 0-N delay uygular.
         MSI sadece property write yapar; agent service start logic'i delay'i çalıştırır. -->
    

    <Feature Id="ProductFeature" Title="EndpointAgent" Level="1">
      <ComponentRef Id="MainExecutable" />
      <ComponentRef Id="ServiceInstall" />
      <ComponentRef Id="RegistryEntries" />
    </Feature>

    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFiles64Folder">
        <Directory Id="INSTALLDIR" Name="EndpointAgent">
          <Component Id="MainExecutable" Guid="{...}">
            <File Id="EndpointAgentExe" Source="endpoint-agent.exe" KeyPath="yes" />
          </Component>
          <Component Id="ServiceInstall" Guid="{...}">
            <ServiceInstall Name="EndpointAgent"
                           DisplayName="ACIK EndpointAgent"
                           Type="ownProcess" Start="auto"
                           Account="LocalSystem" ErrorControl="normal"
                           Vital="yes" />
            <ServiceControl Id="StartService" Name="EndpointAgent"
                           Start="install" Stop="both" Remove="uninstall" Wait="yes" />
            <util:EventManifest MessageFile="[INSTALLDIR]endpoint-agent.exe" />
          </Component>
          <Component Id="RegistryEntries" Guid="{...}">
            <RegistryKey Root="HKLM" Key="SOFTWARE\EndpointAgent" Action="createAndRemoveOnUninstall">
              <RegistryValue Name="ApiUrl" Type="string" Value="[APIURL]" />
              <RegistryValue Name="Version" Type="string" Value="0.2.0" />
              <!-- iter-6 F4 absorb: jitter property persist HKLM so agent service can read -->
              <RegistryValue Name="EnrollmentJitterSeconds" Type="integer" Value="[ENROLLMENTJITTERSECONDS]" />
            </RegistryKey>
          </Component>
        </Directory>
      </Directory>
    </Directory>

    <!-- Service SDDL tamper protection (post-install custom action) -->
    <CustomAction Id="ApplyServiceSDDL"
                  ExeCommand='sc sdset EndpointAgent "D:(A;;CCLCSWLOCRRC;;;AU)(A;;CCLCSWRPWPDTLOCRSDRCWDWO;;;BA)S:(AU;FA;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;WD)"'
                  Directory="INSTALLDIR" Execute="deferred" Impersonate="no" Return="check" />

    <InstallExecuteSequence>
      <Custom Action="ApplyServiceSDDL" After="StartServices">NOT REMOVE</Custom>
    </InstallExecuteSequence>
  </Product>
</Wix>
```

**Critical fields** (Codex iter-1 findings absorbed):
- **UpgradeCode**: FIXED GUID, **NEVER CHANGE** (her version'da aynı) — GPO Software Installation upgrade detection için şart
- **ProductCode**: `Id="*"` (her build farklı) — versioning
- **MajorUpgrade**: auto-handle eski version uninstall + yeni install (cached MSI stuck önle)
- **APIURL as Property + MST transform**: GPO Software Installation property pass etmez; ya MSI default (testai.acik.com) ya **MST transform file** (`.mst`) GPO assignment'a eklenmeli

**Build + sign pipeline** (revize — Codex iter-1 finding: GitHub Actions PFX YASAK):

```yaml
# .github/workflows/build-msi.yml (build only, NO sign)
- name: Build MSI
  run: |
    candle.exe installer.wxs
    light.exe installer.wixobj -ext WixUtilExtension -out endpoint-agent.msi
- name: Upload unsigned artifact
  uses: actions/upload-artifact@v4
  with:
    name: endpoint-agent-unsigned-msi
    path: endpoint-agent.msi

# Internal Windows signing runner (separate, HSM/TPM key)
# - Runner: corp Windows VM, AD-joined, AD CS code signing cert installed
# - Trigger: manual approval after GitHub Actions build artifact ready
# - Signtool with timestamp:
signtool sign /sm /n "EndpointAgent CodeSign" `
  /t http://timestamp.digicert.com `
  /fd SHA256 `
  endpoint-agent.msi

# Upload signed MSI to internal artifact server or DC share
Copy-Item endpoint-agent.msi -Destination \\ACIKDC01\endpoint-agent-deploy\
```

**Install/upgrade/uninstall commands** (manuel test):
```
# Fresh install (F1 absorb: APIURL = full canonical base path)
msiexec /i endpoint-agent.msi /qn APIURL=https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-admin ENROLLMENTJITTERSECONDS=300

# Upgrade (MajorUpgrade auto-handles)
msiexec /i endpoint-agent-v0.2.1.msi /qn  # eski uninstall + yeni install

# Uninstall
msiexec /x endpoint-agent.msi /qn  # veya /x {ProductCode-GUID}

# Repair (if service crashed)
msiexec /fa endpoint-agent.msi /qn
```

**Verification**:
- ProductCode + UpgradeCode kayıt: `Get-WmiObject Win32_Product | Where {$_.Name -match "EndpointAgent"}`
- Service: `Get-Service EndpointAgent` (Status=Running, StartType=Automatic)
- Tamper SDDL: `sc sdshow EndpointAgent`
- Code signature: `Get-AuthenticodeSignature endpoint-agent.exe` (Status=Valid)
- Application Event Log: MsiInstaller event 1033 (install success)

**Dev efforu**: ~3-4 gün (WiX project + MST transform + internal signing runner setup + test)

### Katman 5 — GPO Software Installation + Pilot ramp (revize)

**Critical Codex finding**: SRB-AIDENETIMPC **workgroup** PC, GPO Software Installation hedefi olamaz. Domain-joined pilot ayrı, workgroup pilot ayrı path.

**GPO setup** (DC PowerShell admin):

```powershell
# 1. Share preparation (NTFS + SMB ACL)
$share = "C:\EndpointAgentDeploy"
New-Item -Path $share -ItemType Directory -Force
Copy-Item endpoint-agent-signed.msi -Destination $share
Copy-Item endpoint-agent-mst-transform.mst -Destination $share  # APIURL override

# NTFS ACL: Domain Computers Read+Execute, Domain Admins Full
$acl = Get-Acl $share
$acl.SetAccessRuleProtection($true, $false)
$dcRule = New-Object System.Security.AccessControl.FileSystemAccessRule("ACIK\Domain Computers","ReadAndExecute","ContainerInherit,ObjectInherit","None","Allow")
$adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule("ACIK\Domain Admins","FullControl","ContainerInherit,ObjectInherit","None","Allow")
$acl.SetAccessRule($dcRule)
$acl.SetAccessRule($adminRule)
Set-Acl $share $acl

# SMB share
New-SmbShare -Name "endpoint-agent-deploy" -Path $share `
  -ReadAccess "ACIK\Domain Computers" `
  -FullAccess "ACIK\Domain Admins"

# 2. GPO create
$gpo = New-GPO -Name "EndpointAgent Mass Deployment" `
  -Comment "Faz 22 mass deploy — see ADR-0029"

# 3. Wave Security Group setup (Phase 1 + 2 + 3 scope control)
New-ADGroup -Name "EndpointAgent-Wave1-Pilot" -GroupScope DomainLocal -GroupCategory Security
Add-ADGroupMember -Identity "EndpointAgent-Wave1-Pilot" -Members "AGENTPC2$","HALILKOCOGLU$",...

# 4. Security Filter (Wave 1)
Set-GPPermission -Name "EndpointAgent Mass Deployment" `
  -TargetName "Authenticated Users" -TargetType Group -PermissionLevel None -Replace
Set-GPPermission -Name "EndpointAgent Mass Deployment" `
  -TargetName "EndpointAgent-Wave1-Pilot" -TargetType Group -PermissionLevel GpoApply
Set-GPPermission -Name "EndpointAgent Mass Deployment" `
  -TargetName "Domain Computers" -TargetType Group -PermissionLevel GpoRead  # KB3163622

# 5. Computer Configuration > Software Settings > Software Installation
# (GPMC GUI manuel:)
#   Right-click Software Installation > New > Package
#   Path: \\ACIKDC01\endpoint-agent-deploy\endpoint-agent.msi
#   Deployment: Assigned
#   Modifications tab: Add → endpoint-agent-mst-transform.mst (APIURL override)
#   Advanced > "Make this 32-bit X86 application available to Win64 machines": disabled
#   Advanced > "Uninstall this application when it falls out of the scope of management": ENABLED
#   Advanced > "Install this application at logon": disabled (Assigned to Computer = boot install)

# 6. Link
New-GPLink -Name "EndpointAgent Mass Deployment" `
  -Target "DC=acik,DC=local" -LinkEnabled Yes
```

**Pilot Phase 1 — 5 domain-joined PC**:

| # | PC | Domain join | Pilot strategy |
|---|---|---|---|
| 1 | **AGENTPC2** (10.9.2.98) | ✅ acik.local | GPO Software Installation hedefi |
| 2 | **AGENTPC1 / MKR-A1** (10.9.2.97) | IT onayı bekleniyor | GPO hedefi (onay sonra) |
| 3 | **HALILKOCOGLU** (10.9.2.151) | ✅ acik.local | GPO hedefi |
| 4 | **1 IT volunteer PC** | ✅ acik.local | GPO hedefi |
| 5 | **1 IT department PC** | ✅ acik.local | GPO hedefi |
| (ayrı path) | **SRB-AIDENETIMPC** (10.9.161.105) | ❌ WORKGROUP | **Mevcut AnyDesk + manual install path korunur** (PR #1070 evidence pattern); GPO Software Installation **DEĞİL** |

**Phase 1 acceptance gates** (Codex iter-1 revise: objektif source-of-truth):

| # | Gate | Source-of-truth | Acceptance |
|---|---|---|---|
| 1 | AD CS cert mint | Test PC Certificates MMC (Personal store) `Get-ChildItem Cert:\LocalMachine\My` + template OID match | 5/5 PC TPM-attested cert mevcut |
| 2 | MSI install fire | Test PC Application Event Log `Get-WinEvent -ProviderName MsiInstaller -FilterHashtable @{Id=1033}` | 5/5 PC event entry, ProductCode match |
| 3 | Service Running | Test PC `Get-Service EndpointAgent` Status=Running, StartType=Automatic | 5/5 PC PASS |
| 4 | Backend auto-enroll audit | Backend audit log `ENDPOINT_AUTO_ENROLLED` event count 5+ unique device_id | 5/5 device_id mint |
| 5 | Heartbeat aktif | Backend `endpoint-devices` API `lastSeenAt` < 5 dk per device | 5/5 device PASS |
| 6 | Command lifecycle | Backend `endpoint-commands` API: 1+ SUCCEEDED COLLECT_INVENTORY per device | 5/5 device 1+ command |
| 7 | "No per-device manuel" | Process tanım: per-device manual install/enroll yok; sadece merkezi GPO link + reboot/gpupdate allowed | Process audit OK |
| 8 | Denominator clarity | Offline/decommissioned/broken-trust PC sayımdan exclude; explicit list documented | Pre-pilot list freeze + post-pilot delta |

**Phase 2 acceptance** (50 PC, IT dept):
- 95%+ install success rate (denominator: pre-pilot freeze list, post offline exclude)
- 90%+ heartbeat success 24h window
- Helpdesk runbook fail-recovery TEST: 1 PC manuel fail simüle + recovery PASS
- Backend monitoring dashboard live (enroll rate, heartbeat success, command rate)

**Phase 3 acceptance** (800 PC, wave 200/gün):
- <5% fail rate per wave (4 wave × 200 PC)
- Rollback plan TESTLI: 1 wave reverse + recovery PASS
- Codex final review AGREE (governance precondition)

---

## Risk register (revize, R13-R20 yeni eklendi)

| ID | Risk | Olasılık | Severity | Mitigation |
|---|---|---|---|---|
| R1 | AD CS auto-enrollment fail (PC GPO refresh yok / TPM disabled / policy conflict) | Orta | High | Phase 0 P0-2/P0-10/P0-11 gate; TPM enable corp policy; AD CS test cert manuel + GPO scope dar başla |
| R2 | mTLS endpoint security exploit | Düşük | Critical | Backend cert-derived identity (body değil); EKU/template/SAN/issuer/CRL check; rate limit per SID |
| R3 | MSI install fail (Defender / AppLocker conflict) | Orta | Medium | Code signing cert thumbprint AppLocker allowlist; Defender exclusion install dir; pilot test 5 PC |
| R4 | GPO scope error | Düşük | Medium | Wave Security Group strict; hostname guard agent self-check; multi-layer safety |
| R5 | Network bandwidth (800 PC simultaneous boot) | Orta | Medium | Wave rollout 200/gün; MSI BITS cache; off-hours boot policy |
| R6 | Token rotation chaos | Orta | High | Auto-rotate at 80% lifetime; cert-bound token (mTLS required); monitoring alert on expiry |
| R7 | Tamper protection conflict (Defender RTP / AppLocker / GPO) | Orta | High | Internal CA Trusted Publisher AppLocker; Defender exclusion; signed manifest |
| R8 | User uninstall | Düşük | Low | Service SDDL strict; AppLocker policy block uninstall by non-Admin |
| R9 | Backend pod overload (800 simultaneous auto-enroll) | Düşük | Medium | Rate limiting per SID; horizontal autoscale endpoint-admin-service; wave timing |
| R10 | AD CS root CA compromise | Çok düşük | Critical | TPM-protected root key; offline issuing CA option; CRL ready; HSM upgrade roadmap |
| R11 | 9-saatlik AGENTPC2 pattern fail tekrarı | **Risk reduced, not eliminated** | High | GPO Software Installation farklı CSE; Phase 0 + Phase 1 evidence ile gerçek pattern reliability kanıtlanır; aynı sınıf failure (GPO scope/SYSVOL/share ACL/slow-link) MSI'da da olabilir |
| R12 | Frontend grid render bug ("Cihazlar yükleniyor…") | Mevcut | Medium | Ayrı task chip #175; MSI deploy bağımsız ilerler |
| **R13** | **Domain/workgroup mismatch — GPO Software Installation workgroup PC'ye gitmez** | Bilinen | High | Pilot path ayrı: workgroup PC (SRB-AIDENETIMPC) **AnyDesk + manual install** pattern korunur; GPO hedefi sadece domain-joined |
| **R14** | **TLS termination/ingress mTLS** Spring Boot tek başına yetmez (Kubernetes ingress arkasında) | Yüksek | High | nginx ingress mTLS **passthrough** config (TLS pod'da sonlanır); Phase 0 P0-13 evidence gate |
| **R15** | **Cert renewal duplicate** — cert thumbprint renewal'da değişir, duplicate device riski | Yüksek | High | Identity = AD SID/GUID (renewal-safe); thumbprint sadece audit; Phase 1 gate evidence (renewal scenario test) |
| **R16** | **Revocation (CRL/OCSP) reachability** | Orta | High | CRL HTTP serve + cache 24h; backend fail-closed default; Phase 0 P0-14 gate |
| **R17** | **Code signing private key custody** — GitHub Actions PFX zayıflık | Yüksek | Critical | **Internal Windows signing runner** (HSM/TPM-backed key); GitHub Actions sadece unsigned build; manual approval signing |
| **R18** | **MSI ProductCode/UpgradeCode/upgrade-on-fallout** | Orta | Medium | WiX MajorUpgrade auto-handle; UpgradeCode FIXED GUID; "Uninstall when out of scope" enabled |
| **R19** | **APIURL property GPO** — `msiexec APIURL=...` GPO direct pass etmez | Yüksek | Medium | MST transform file (`endpoint-agent-mst-transform.mst`) GPO Modifications tab; Phase 0 P0-9 evidence |
| **R20** | **Rate limiting NAT/proxy** — `10 req/min per IP` 800 PC yanlış throttle | Orta | Medium | Rate limit **per SID** (cert-derived), IP'den bağımsız |
| **R21** | **Scope truth drift** — ADR-0029 ↔ PLAN.md/ADR-0012/RB-faz22 supersedence dili belirsizliği | Bilinen | High | ADR üst kısmı scope amendment statement explicit; iter-3 absorb PR'a PLAN.md + ADR-0012 + RB header truth-sync ekle |
| **R22** | **mTLS route split** — admin/browser API JWT-only, device API mTLS-mandatory; route mismatch admin'i kırabilir | Yüksek | High | Ayrı Ingress + SNI host (`endpoint-agent-mtls.testai.acik.com`) + Service; admin traffic mevcut nginx ingress; Phase 0 P0-13 canlı smoke gate |
| **R23** | **CN-to-AD identity binding** — Cert subject CN unique değil (CN reuse, rejoin, stale obj), SID/GUID extraction zinciri zayıf | Yüksek | High | Cert SAN extension `URI:adcomputer:{objectGUID}` template ile mint; fallback CN→LDAPS lookup + reuse guard (SID mismatch → AUTO_ENROLL_DENIED + alert); P0-16 backend LDAPS gate |
| **R24** | **Token refresh outage cascade** — 24h short-lived + ingress fault + CRL outage simultaneous → 800 cihaz offline cascade | Orta | High | **İki davranış AYRI uygulanır (iter-4 F3 absorb + iter-6 F2 absorb)**: **(a) Enrollment-time** (yeni cert validation): CRL fail → **fail-closed default** (yeni cihaz enroll reddedilir, P0-14 expected behavior); **(b) Already-enrolled** (token refresh / heartbeat): CRL fail → backend `grace_until = min(cert_not_after, last_good_revocation_check + 24h)` — 24h grace yalnız last good CRL check'inden itibaren; cert_not_after hard cap (cert zaten expired ise grace_window OFF, fail-closed enforced). Long-lived certs (2 yıl) için CRL outage 24h'den uzun sürerse fail-closed enforced; grace yıllarca uzayamaz. Agent heartbeat response'unda `grace_window: true` + `grace_until` field iletilir; agent service continues; **fail-closed sadece grace_until aşıldıktan sonra** (cihaz offline state). Plus: Phase 1 acceptance fault injection tests (3 senaryo: forced token expiry, ingress mTLS fault, CRL outage); agent exponential backoff (1-2-4-8-16dk caps 60dk); CRL outage anında **batch alert** (>%10 device grace state)。 Token TTL 24h cert-expiry'den daha kısa olduğu için cert hâlâ valid + CRL inaccessible durumunda already-enrolled hosts grace window ile sağ kalır |
| **R25** | **Fleet TPM/CA trust/EDR readiness** — TPM disable/EDR block/Trusted Publisher missing %5'i geçerse mass deploy fail explode | Orta | High | P0-22 fleet TPM sample (≥95%); P0-18 EDR allowlist + WDAC; P0-19 Trusted Publisher store; ratio düşükse scope reduce |
| **R26** | **Aggregate enrollment storm** — 800 PC simultaneous boot (Monday morning) backend overload | Orta | Medium | Wave 200/gün; backend horizontal autoscale; rate limit per SID + aggregate throttle (rolling window 1dk); **agent startup jitter** (iter-4 F5 absorb): MSI sadece `ENROLLMENTJITTERSECONDS` property write (registry/config dosyasına); agent service startup'ta config'den okur, `time.Sleep(rand.Intn(jitterSec) * time.Second)` uygular auto-enroll call'undan önce. **WiX CustomAction Type 51 yaklaşımı yanlıştır** (Type 51 property set pattern, command execution değil; ayrıca After="StartServices" Sleep service startup'tan sonra çalışırdı → agent çoktan koşmaya başlamış olur). Tek doğru pattern: jitter agent process içinde, MSI sadece config taşır. |

---

## Consequences

### Positive

- 800 PC mass deployment gerçek production-grade çözüm
- AD CS infrastructure corp için reusable (diğer corp services signing cert kullanabilir)
- Faz 22 backend control-plane (OpenFGA, BE-017, BE-016, UI) değer korunur
- 9 saatlik AGENTPC2 uğraşı discovery value (Phase 0 preflight gate'in oluşmasına neden oldu)
- Cross-platform roadmap kapısı açık (mTLS pattern OS-agnostic)
- Sektör standardı code signing (internal CA, Wazuh/OSQuery pattern, ücretsiz)

### Negative

- 4 hafta dev iş yatırımı (Phase 0 + BE + agent + MSI + GPO + pilot)
- AD CS infrastructure ek IT operasyonel sorumluluk (CRL, cert renewal, HSM roadmap)
- Internal Windows signing runner setup (corp VM, AD-joined)
- mTLS passthrough nginx ingress config karmaşıklığı
- IT bağımlılığı (AD CS role install, GPO scope karar, Phase 0 PC test koordinasyon)

### Neutral

- Faz 22 endpoint agent custom kalır — vendor lock yok
- Code signing AD CS dış müşteri için yeterli değil — ileride EV cert opsiyonu açık
- Codex'in HYBRID önerisi reddedildi ama Wazuh pivot **evidence-gated fallback** olarak saklı

---

## Rollback strategy (revize)

Phase 1 pilot fail (>50% PC install fail rate) durumunda:

1. **GPO unlink** — Software Installation GPO link disable (mass deploy stop)
2. **MSI uninstall** — pilot PC'lerde `msiexec /x endpoint-agent.msi /qn` veya "Uninstall when out of scope" auto-fire
3. **Service tamper SDDL cleanup** — service remove
4. **NTFS+SMB share cleanup** — `\\ACIKDC01\endpoint-agent-deploy` kalır (asset preserved)
5. **Backend device rows retire** — pilot device_id `status=DECOMMISSIONED` mark
6. **Backend service token revoke** — cert-bound token blacklist + audit
7. **Cert revoke (gerekirse)** — AD CS CRL update
8. **AD CS cert + GPO link kalır** — başka corp service için reusable
9. **Backend auto-enroll endpoint dormant** — manuel single-use enrollment endpoint korunur
10. **Audit/postmortem** — fail root cause + Faz 22 strategic review trigger

**Wazuh pivot reactivation (evidence-gated, NOT 1-week claim)**:
- Codex iter-1 finding: "Wazuh agent da MSI/GPO/installer kanalı ister — install-channel fallback değil, ürün/telemetry fallback"
- Realistic Wazuh deploy timeline: 2-3 hafta (manager VM + agent MSI/GPO + corp test + tuning)
- Pre-condition: install channel (MSI/GPO/AnyDesk) ayrıca kanıtlanmalı
- Plus: Phase 1 freeze + mevcut manual-installed cihazlarla sınırlı devam + Zabbix read-only korunur

---

## Acceptance gates (revize, Codex iter-1 absorb)

### Phase 0 (preflight, MANDATORY)
- [ ] **P0-1...P0-23** tüm checklist PASS (objektif source-of-truth ile, **P0-23 cert SAN URI:adcomputer:{guid} verify dahil — iter-6 F2 absorb mandatory gate**)
- [ ] Phase 0 fail noktası fix edilmeden Phase 1'e geçilmez

Plus P0-5 vs P0-15 ayrımı net:
- **P0-5** "Machine account UNC read (admin PSSession quick check)" — human-context smoke
- **P0-15** "SYSTEM context UNC read (PsExec /s)" — **authoritative gate** (SYSTEM context şart, install-time context emülasyonu)

### Phase 1 (5 domain-joined PC pilot)

**Denominator T0 freeze procedure** (iter-3 absorb): Phase 1 başlangıcı T0'da snapshot al:
- Wave Security Group member listesi (AD object SID + GUID + DisplayName)
- AD Enabled=True filter
- AD LastLogonDate ≥ T0-30 days filter (offline/decommissioned exclude pre-defined)
- IT-confirmed exclusion liste (DNS conflict, hardware fault, BYOD, vb.)
- Snapshot dosya: `docs/faz-22-evidence/phase1-denominator-freeze-{date}.json`
- Post-pilot delta: yeni offline → audit field `excluded_post_t0` (success rate inflation önle)

**UI conditional karar (iter-3 absorb netleştirme)**:
- **Karar: Phase 1 BACKEND-ONLY acceptance** — UI grid render bug ayrı task #175 paralel; Phase 1 success backend API kanıtı yeterli (devices list + audit + command).
- Phase 2 acceptance gate'inde UI grid render PASS ek conditional (50 PC UI'da görünür olmalı, kritik UX).
- Rationale: backend mass deploy fonksiyonel kanıt UI bug fix'ten bağımsız ilerleyebilir.

- [ ] 5/5 AD CS TPM-attested cert mint (Certificates MMC kanıt)
- [ ] 5/5 MSI install fire (MsiInstaller Event Log 1033 kanıt)
- [ ] 5/5 Service Running (Get-Service kanıt)
- [ ] 5/5 backend ENDPOINT_AUTO_ENROLLED audit (backend log)
- [ ] 5/5 heartbeat aktif (endpoint-devices API lastSeenAt < 5 dk)
- [ ] 5/5 command lifecycle SUCCEEDED (endpoint-commands API 1+ COLLECT_INVENTORY per device)
- [ ] 0 per-device manuel müdahale (process audit)
- [ ] **Denominator T0 freeze documented** (5/5 wave SG snapshot + LastLogonDate filter)
- [ ] Cert renewal scenario tested (1 PC manuel renewal trigger, SID stable dedupe verify, no duplicate device)
- [ ] **Forced token-expiry test** (R24): 1 PC token TTL'i 5dk'a düşür, agent refresh PASS
- [ ] **Ingress mTLS fault injection** (R24): nginx ingress restart sırasında agent backoff + recovery PASS
- [ ] **CRL outage scenario** (R24, R16, F3 absorb + F2 iter-6 absorb — 2 sub-scenario AYRI verify): (a) **Enrollment-time**: CRL endpoint disable 30sn, yeni PC enroll attempt → backend reddetmeli (fail-closed default); (b) **Already-enrolled**: CRL endpoint disable 30sn sırasında mevcut 5 PC heartbeat continue + `grace_window: true` + `grace_until` field iletilir; **grace_until formula `min(cert_not_after, last_good_revocation_check + 24h)`** — 24h hard cap (cert_expiry değil), long-lived cert + uzun CRL outage senaryosunda fail-closed enforced. Batch alert >%10 device grace state'de tetiklenir verify. **Test scenario**: 2 PC cert near-expiry simülasyon — grace window cert_expiry'den önce kapanmalı.
- [ ] **Workgroup PC (SRB-AIDENETIMPC) Phase 1 dışı** — ayrı AnyDesk path korunur
- [ ] **REMOVED: Codex AGREE acceptance gate** (governance precondition only, not runtime)
- [ ] **Phase 1 backend-only** — UI grid render bug task #175 paralel, Phase 1 fail nedeni değil

### Phase 2 (50 PC IT dept)

**Denominator T0 freeze procedure (Phase 2)** (Codex iter-3 absorb):
- Phase 2 başlangıcı T0'da snapshot: wave SG SID/GUID + Enabled + LastLogonDate ≥ T0-30d
- IT-confirmed exclusion liste (Phase 2 başlangıcı pre-defined, post-pilot "ek offline" excluded_post_t0 audit field)
- Snapshot dosya: `docs/faz-22-evidence/phase2-denominator-freeze-{date}.json`

- [ ] **Denominator T0 freeze documented** (50 PC wave SG snapshot)
- [ ] 95%+ install success rate (denominator T0 freeze + IT-confirmed pre-defined exclusion only)
- [ ] 90%+ heartbeat success 24h window
- [ ] Helpdesk runbook fail-recovery test PASS (en az 1 PC manuel fail simüle + recovery)
- [ ] Backend monitoring dashboard live (4 metric: enroll, heartbeat, command, fail rate)
- [ ] **UI grid render** HARD GATE — frontend devices grid 50/50 device görünür ve renderable (Codex iter-3 absorb: prose değil checkbox)
- [ ] Forced cert renewal test (1 PC) — SID stable, dedupe verify, no duplicate device

### Phase 3 (800 PC full)
- [ ] 95%+ install success per wave
- [ ] 90%+ heartbeat 24h aggregate
- [ ] Wave 200/gün <5% fail rate
- [ ] Rollback plan TESTLI (1 wave reverse + recovery PASS)
- [ ] 800 PC roll-out karar (governance, Codex final review precondition)

---

## Reactivation/exit triggers

### Wazuh pivot reactivation (Codex HYBRID önerisi geri al, EVIDENCE-GATED)
- Phase 1 pilot >50% fail rate **+ root cause Wazuh ile çözülebilir kanıt**
- Phase 2 ramp 4 hafta üzeri gecikme
- AD CS infrastructure unsustainable
- Cross-platform (Linux/macOS) acil ihtiyaç

### EV Code Signing cert (ücretli) trigger
- Dış müşteri/dış corp deployment talebi
- Defender SmartScreen warning end-user adoption blocker
- Compliance audit (SOC2 / ISO27001) EV cert mandatory tespiti

### Faz 22 scope reduction (Codex önerisi geri kabul)
- 12 ay sonrası ROI re-evaluation
- Corp organizational pivot

---

## References

- ADR-0012-EA Endpoint Admin Governance Charter (parent governance)
- RB-faz22-non-domain-windows-pilot.md (manuel pilot pattern, A1 baseline)
- RB-faz22-strategy-d-dc-orchestrated-install.md (Strategy D runbook, deprecated by GPO Software Installation)
- PR #1070 (SRB-AIDENETIMPC A1 direct install evidence, workgroup pattern)
- Codex thread `019e634a` (2026-05-26 HYBRID stratejik önerisi, owner-rejected)
- Codex thread `019e665f` (2026-05-26 ADR iter-1 REVISE review, 10 finding absorbed)
- Microsoft AD CS: https://learn.microsoft.com/en-us/windows-server/identity/ad-cs/
- WiX Toolset: https://wixtoolset.org/
- Faz 22 Phase 2 (Mass Deployment) sprint board: GitHub Project #2

---

## HARD RULE compliance

- ✅ **Pre-Production Full Authority**: agent end-to-end koşar
- ✅ **No Closure Language**: "kapandı/bitti" yok
- ✅ **Cross-AI Peer Review**: Codex (OpenAI) cross-provider review chain (thread `019e665f` iter-1/2/3 absorbed + thread `019e667f-98a5-7980-8f80-613fc1a1ed82` iter-4/5/6 REVISE all 12 finding F1-F5 + F1-F4 + F1-F3 absorbed; iter-7 review pending)
- ✅ **No Fake Work**: 9 saatlik AGENTPC2 deneyimi transparent ifade, Phase 0 P0-1..22 evidence gate + denominator T0 freeze ile sahte yeşil önle
- ✅ **CI Kırmızıyken Merge YASAK**: ADR PR governance check'leri yeşil bekleniyor
- ✅ **Admin Merge YASAK**: normal squash merge, CI yeşil sonrası
- ✅ **Continuous Autonomous Mode**: owner approval (Plan A) ile otonom devam
- ✅ **Iter-1 REVISE absorbed (Codex 10 finding)**: Phase 0 + workgroup path + mTLS ingress + cert renewal stable identity + cert-bound token + MSI Upgrade/MST + signing key custody + R11 nuance + Wazuh rollback realism + acceptance gates objektif source-of-truth
- ✅ **Iter-2 REVISE absorbed (Codex 6 high/medium + 6 yeni risk)**: scope amendment statement + mTLS route split (DEVICE_API_BASE_URL, ayrı SNI) + identity SAN extension + token rotation soak/fault tests + P0 expansion (15-22) + denominator T0 freeze + UI Phase 1 backend-only karar + R21-R26 risk register
- ✅ **Iter-3 REVISE absorbed (Codex 5 finding)**: truth-sync MERGE BLOCKER (PLAN.md + ADR-0012 + 2 RB header) + mTLS URL canonical (endpoint-agent-mtls.testai.acik.com) + backend processing step 9 SAN-primary identity + AD CS template SAN extension instructions + Phase 0 P0-1..P0-22 + Phase 2 UI HARD GATE + denominator T0 freeze + R24 24h grace + R26 WiX jitter (initial) + scope addition statement
- ✅ **Iter-4 REVISE absorbed (Codex 5 finding F1-F5)** [historical — superseded ifadeleri iter-5/6 absorb'larında düzeltildi]: F1 mTLS canonical URL Option A (APIURL full base path /api/v1/endpoint-admin canonical) + F2 AD CS SAN URI:adcomputer:{objectGUID} mekanizma (initial: ~~Get-ADComputer + certreq -enroll -inf~~ — **superseded by iter-5 F1**: RSAT-free DirectorySearcher + certreq 3-step `-new`/`-submit`/`-accept`; P0-23 verify gate eklendi) + F3 R24 2-davranış ayrımı (enrollment-time fail-closed + already-enrolled grace; initial formula ~~`expiry+24h`~~ — **superseded by iter-5 F2**: bounded formula `min(cert_not_after, last_good_revocation_check + 24h)`) + F4 scope addition truth-sync (ADR-0029:9 Related "ADDITION" + ADR-0012 22.3 Restricted→22.4 rename + RB-non-domain SAN URI invariant 22.3 path-only) + F5 R26 WiX CustomAction yanlış (jitter agent service startup'a taşındı; MSI ENROLLMENTJITTERSECONDS property; initial commit registry persist eksik — **superseded by iter-5 F4**: WiX RegistryValue HKLM persist + agent registry read pseudo-code eklendi)
- ✅ **Iter-5 REVISE absorbed (Codex 4 finding F1-F4)**: F1 GPO + certreq executable mekanizma (RSAT-free DirectorySearcher LDAP query + certreq 3-step `-new`/`-submit`/`-accept` valid flow + P0-23 LocalMachine\My store) + F2 R24 grace_until bounded formula (`min(cert_not_after, last_good_revocation_check + 24h)`) + F3 ADR-0012 identity model PARTIAL invariant (22.2.A non-domain AD computer object yok → SAN URI geçersiz; 22.2.B small-scale manual cert; 22.3 SAN URI primary; backend/audit ortak invariant) + F4 WiX RegistryEntries EnrollmentJitterSeconds persist + agent service startup config read
- ✅ **Iter-6 REVISE absorbed (Codex 3 finding F1-F3, this commit)**: F1 P0-14 grace formula bounded (R24/Phase 1 ile uyumlu, in-doc çelişki kapatıldı) + F2 Phase 0 acceptance gate P0-22 → P0-23 (cert SAN URI verify mandatory gate) + F3 cross-doc truth-sync homojen (RB-IT-owned scope superseded note identity invariant PARTIAL alignment + PLAN.md iter-6 chain state + ADR-0029 HARD RULE summary historical "superseded by" markers)
