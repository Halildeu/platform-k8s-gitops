# RB Faz 22.3 — AD CS Infrastructure Setup (DC operator runbook)

> **Status**: PREP (operator runbook — agent scripts ready; IT operator execution required)
> **Scope**: Faz 22.3 domain-wide mass deployment Katman 1 (AD CS) preflight + GPO infrastructure
> **Canonical decision**: ADR-0029 (PR #1078 MERGED 2026-05-26) §"Katman 1 — AD CS (Active Directory Certificate Services)"
> **Tracked by**: [#1079](https://github.com/Halildeu/platform-k8s-gitops/issues/1079) (Task #177 AD CS preflight)
> **Cross-AI peer review**:
> - Codex (OpenAI) thread `019e667f-98a5-7980-8f80-613fc1a1ed82` iter-7 AGREE (ADR-0029 12 finding F1-F5 + F1-F4 + F1-F3 absorbed)
> - Codex (OpenAI) PR #1080 iter-1 5 finding (F1 short name + F2 EditFlag SAN2 + F3 TPM fail-closed + F4 cert prune + F5 -Force) absorbed
> - Codex (OpenAI) PR #1080 iter-2 REVISE 5 finding absorbed: F2-A (authorized signatures vs CA Manager approval), F2-B (pending approval 2-fazlı enrollment), F2-C (CertSvc restart fail-closed), F3-A (existing CA path provider audit), F1-A (HRESULT mapping canonical)
> - Codex (OpenAI) PR #1080 iter-3 REVISE remaining 3 finding absorbed: F2-B iter-4 (pending JSON fail-CLOSED + atomic write + cross-process mutex), F2-C iter-4 (idempotent path Get-Service Running check), F1-A iter-4 (HRESULT canonical disposition semantik tablosu yeniden yazıldı)

---

## 1. Amaç

Faz 22.3 domain-wide mass deployment kanalı için DC üzerinde Active Directory Certificate Services (AD CS) infrastructure'ını initialize etmek. Bu runbook:

- AD CS rolünü install + Enterprise Root CA initialize
- 2 cert template create + publish (machine cert + code signing cert)
- AutoEnrollment GPO + custom URI SAN extension için GPO startup script deploy
- Phase 0 P0-1..P0-23 acceptance gate'lerinin bir kısmını kanıtlamaya hazır hale getirme
- 5 pilot PC için cert mint-ready durum (Phase 1'in source-side ön-koşulu)

**Kapsam dışı (ayrı PR/runbook)**:
- Backend mTLS endpoint impl (Task #178 — `POST /endpoint-enrollments/auto`, ayrı session/spawn)
- Agent `--auto-enroll` feature (Task #179 — Go agent, ayrı session/spawn)
- MSI WiX build + AD CS code signing (Task #180 — operator-bound)
- GPO Software Installation + 5 PC pilot deploy (Task #181 — operator-bound)
- 50/800 PC ramp (Task #182 — operator-bound)

---

## 2. Operator Prerequisites

### 2.1 Environment

- Windows Server 2019+ DC (Enterprise Root CA gerek; Standalone yetmiyor)
- Domain: `acik.local` (canonical; production scope, BOREAS/CESS scope dışı)
- **TPM 2.0 chip (mandatory)** — DC'de TPM-backed CA key için + pilot PC'lerde TPM-backed machine cert key için (F3 absorb iter-1).
  - DC'de TPM yoksa `ad-cs-preflight.ps1 -AllowSoftwareKey` flag explicit gerek; aksi halde script fail-closed (TPM ready bekler).
  - Pilot PC'lerde TPM yoksa machine cert mint fail; PC TPM upgrade veya pilot scope dışında.
  - `-AllowSoftwareKey` ile software KSP fallback: R10 risk **artar** (CA private key software-stored; TPM-bound DEĞİL); owner approval log'a yazılır.
- DC disk free > 5 GB (CRL + cert DB + audit log)
- IIS Web-Server feature (opsiyonel ama HTTP CRL distribution için önerilir)
- Backup taken (system state + AD; rollback için)

### 2.2 Operator Permissions

- Domain Admin (GPO create/link + AD object create)
- Enterprise Admin (cert template create + publish)
- Schema Admin (cert template schema değişimi gerekirse — duplicate template yeterli, schema mod yok)
- Local Administrator (DC üzerinde script run)

### 2.3 Pre-Step Verifications (P0-1..P0-22 baseline)

| Gate | Komut | Beklenen |
|---|---|---|
| P0-1 | `(Get-WmiObject Win32_ComputerSystem).PartOfDomain` | True (DC'de True; pilot PC'lerde de True olmalı) |
| P0-11 | `Get-Tpm` | Enabled + Ready (DC'de + pilot PC'lerde) |
| P0-17 | `w32tm /query /status` | clock skew ≤ 5 dk (Kerberos için kritik) |
| P0-18 | `gpresult /scope:computer` | AppLocker/WDAC policy snapshot, EDR exclusion list inventory |

Tam P0-1..P0-23 listesi: ADR-0029 §"Phase 0 — Operator Manual Preflight Checklist".

---

## 3. Execution Sequence

### 3.1 Preflight script run (DC üzerinde, Administrator)

```powershell
# Clone gitops repo veya sadece scripts/faz22-mass-deployment/ dizinini DC'ye kopyala
cd C:\faz22-mass-deployment\scripts\
.\ad-cs-preflight.ps1                          # interactive default (TPM ready required)
# veya
.\ad-cs-preflight.ps1 -WhatIf                  # dry-run, görme amaçlı
.\ad-cs-preflight.ps1 -Step Feature -Force     # tek adım force (F5: manual MMC/IIS checkpoint'leri de skip)
.\ad-cs-preflight.ps1 -AllowSoftwareKey        # F3: TPM degraded ise software KSP fallback (R10 risk)
.\ad-cs-preflight.ps1 -Step EditFlag           # F2: sadece EDITF_ATTRIBUTESUBJECTALTNAME2 enable
```

Script 11 adımı interactive sırayla yürütür (F2 absorb iter-1 ile Step 2.5 eklendi; iter-2 F2-C fail-closed + F3-A existing CA audit absorb):

1. **Install ADCS-Cert-Authority** Windows feature (PowerShell automated)
2. **Initialize Enterprise Root CA** `ACIK Endpoint CA` (TPM-backed key default; F3 absorb: TPM ready fail-closed unless `-AllowSoftwareKey`; **F3-A absorb iter-2**: existing CA varsa `Test-CACryptoProvider` ile gerçek CSP/KSP audit; software-keyed CA tespitinde `-AllowSoftwareKey` yoksa throw)
2.5. **F2 absorb — Enable EDITF_ATTRIBUTESUBJECTALTNAME2** + restart CertSvc (custom URI SAN için mandatory; CA Manager approval pipeline ile birlikte — §3.2.5; **F2-C absorb iter-2**: registry SET + restart exit code + `Get-Service CertSvc` Status=Running double-check; fail-closed pattern)
3. **Create EndpointAgentMachineCert template** (MMC manual — operator certtmpl.msc; HYPHENLESS short name canonical, display "EndpointAgent Machine Cert" — F1 absorb; **F2-A absorb iter-2**: Issuance Requirements doğru config = `Authorized signatures: 0` + `CA certificate manager approval: ENABLED`; F5: `-Force` mode'da skip + WARN log)
4. **Create EndpointAgentCodeSigning template** (MMC manual; HYPHENLESS short name canonical; **F2-A absorb iter-2**: aynı Issuance Requirements config; F5: `-Force` mode'da skip)
5. **Publish templates** to enterprise CA (`certutil -setcatemplates +EndpointAgentMachineCert,EndpointAgentCodeSigning`)
6. **Configure CRL Distribution Points** (HTTP via IIS — operator manual config; F5: `-Force` mode'da skip + WARN log)
7. **Configure AutoEnrollment GPO** (`New-GPO` automated + MMC manual policy enable)
8. **Deploy enroll-endpoint-agent-cert.ps1** to SYSVOL (script copy automated + GPO startup script link manual; **F2-B absorb iter-2**: 2-fazlı enrollment — pending state JSON persist + daily retry)
9. **Deploy Schedule Task GPO** (daily 03:00 renewal trigger — operator GPMC manual; F2-B: schedule task `-retrieve` ile pending request'leri çeker)
10. **Verify all artifacts** (P0-23 baseline summary; iter-2: F2-C CertSvc Running + F3-A CA Key Binding ayrı audit field'lar)

### 3.2 Template properties (MMC manual — Step 3 detay)

> **F1 absorb (iter-1 HIGH MERGE BLOCKER) — Display name vs template short name**:
> AD CS request attribute `CertificateTemplate` **SHORT NAME** ister (display name DEĞİL).
> MMC duplicate dialog'unda verilen "Display name" alanı **otomatik hyphen-strip** edilerek
> AD'de stored short name üretir. Yani:
>
> | UI Display Name (visual) | AD Stored Short Name (canonical — certreq/certutil için) |
> |---|---|
> | `EndpointAgent Machine Cert` | `EndpointAgentMachineCert` (HYPHENLESS) |
> | `EndpointAgent Code Signing` | `EndpointAgentCodeSigning` (HYPHENLESS) |
>
> Script defaults (`ad-cs-preflight.ps1` + `enroll-endpoint-agent-cert.ps1`) canonical
> short name'i (hyphenless) kullanır. MMC'de Properties → General → Template name alanı
> mutlaka HYPHENLESS short name ile eşleşmeli; aksi halde `certreq -submit` 0x80094012
> "template not found" hatası verir.

`certtmpl.msc` → `Computer` template Duplicate → `EndpointAgent Machine Cert` (display) /
`EndpointAgentMachineCert` (short) properties:

| Tab | Setting | Value |
|---|---|---|
| General | Display name (visual) | `EndpointAgent Machine Cert` |
| General | Template short name (canonical) | `EndpointAgentMachineCert` (HYPHENLESS — certreq/certutil bunu kullanır) |
| Compatibility | CA + recipient | Windows Server 2016 + Windows 10 |
| Cryptography | Provider category | `Key Storage Provider` |
| Cryptography | Provider | `Microsoft Platform Crypto Provider` (TPM-only) |
| Cryptography | Key size | 2048 (4096 mümkün ama TPM perf düşer) |
| Request Handling | Purpose | Signature and encryption |
| Subject Name | Source | **`Supply in the request`** (F2 absorb iter-1 HIGH — custom SAN URI için Build-from-AD yerine Supply-in-request; ayrıntı §3.2.5) |
| Extensions | Application Policies | Client Authentication (1.3.6.1.5.5.7.3.2) |
| Extensions | Key Usage | Digital Signature + Key Encipherment |
| Issuance Requirements | **Authorized signatures: 0** | **F2-A absorb iter-2 HIGH** — Enrollment Agent flow YOK (bizim INF/certreq akışı agent signed-request üretmiyor); önceki "authorized signatures: 1" YANLIŞTI (o ayar farklı semantik) |
| Issuance Requirements | **CA certificate manager approval: ENABLED** (ayrı checkbox) | **F2-A absorb iter-2 HIGH** — manual sign-off checkbox; request **pending state'e geçer (API `CR_DISP_UNDER_SUBMISSION`=5 / CA DB `Disposition` column=9; HRESULT YOK — certreq output "taken under submission" text); CA Manager Certification Authority MMC > Pending Requests'tan approve eder**; 5 PC pilot sürdürülebilir, 50/800 ramp için custom policy module gerek (§3.2.5). [F1-A absorb iter-5/6: pending'in dedicated HRESULT yok; disposition iki ayrı katmanda — API ICertRequest::Submit return CR_DISP_UNDER_SUBMISSION=5; CA database `Disposition` column `certutil -view -restrict "Disposition=9"` ile sorgulanır] |
| Issuance Requirements | TPM attestation | Required (Windows Server 2016+ özelliği) |
| Security | Domain Computers | Read + Autoenroll (sadece Enroll yetmiyor) |

`EndpointAgent Code Signing` (display) / `EndpointAgentCodeSigning` (short) template (Step 4):

| Tab | Setting | Value |
|---|---|---|
| General | Display name (visual) | `EndpointAgent Code Signing` |
| General | Template short name (canonical) | `EndpointAgentCodeSigning` (HYPHENLESS — certreq/certutil bunu kullanır) |
| Compatibility | CA + recipient | Windows Server 2016 + Windows 10 |
| Cryptography | Provider | TPM OK; Hash = SHA256 |
| Subject Name | Source | `Supply in the request` (manuel certreq) |
| Extensions | Application Policies | Code Signing (1.3.6.1.5.5.7.3.3) |
| Issuance Requirements | **Authorized signatures: 0** | **F2-A absorb iter-2 HIGH** — Enrollment Agent flow YOK |
| Issuance Requirements | **CA certificate manager approval: ENABLED** | **F2-A absorb iter-2 HIGH** — operator manuel sign-off pipeline (pending state → CA Manager approve); R17 HARD RULE compliance |
| Security | agent-team-restricted group | Read + Enroll (NOT Autoenroll) |

> **R17 HARD RULE compliance**: code signing private key TPM/HSM-backed Windows signing runner'da kalır. GitHub Actions PFX yok; CA Manager approval ile manuel sign pipeline.

### 3.2.5 F2 absorb — EDITF_ATTRIBUTESUBJECTALTNAME2 + CA Manager approval pipeline

> **F2 absorb (iter-1 HIGH MERGE BLOCKER) — Custom URI SAN issuance policy**
> **F2-A absorb (iter-2 HIGH MERGE BLOCKER)** — `authorized signatures` vs `CA certificate manager approval` ayrı semantikler; doğru config: `Authorized signatures: 0` + `CA certificate manager approval: ENABLED`
> **F2-C absorb (iter-2 MEDIUM)** — Step 2.5 restart fail-closed: registry SET + restart exit code + CertSvc Running double-check
>
> AD CS standart template "Build from AD" davranışı dinamik custom URI SAN extension
> (`URL=adcomputer:{objectGUID}`) basamaz. enroll-endpoint-agent-cert.ps1 INF üzerinden
> custom `2.5.29.17` SAN extension gönderiyor; bu extension'ın CA tarafından **kabul
> edilmesi** için iki policy ayarı birlikte gerek:
>
> **1. Template Subject Name = "Supply in the request"** (Build-from-AD değil — §3.2 tablo)
>
> **2. CA EditFlags: EDITF_ATTRIBUTESUBJECTALTNAME2** (DC'de CA setting; preflight Step 2.5):
>
> ```powershell
> certutil -setreg policy\EditFlags +EDITF_ATTRIBUTESUBJECTALTNAME2
> net stop certsvc   # F2-C: exit code kontrol
> net start certsvc  # F2-C: exit code + Get-Service Running double-check
> ```
>
> > **SECURITY**: Bu flag ENABLE edildiğinde CA herhangi bir requester'ın istediği SAN'ı
> > kabul eder. Mitigation OLMADAN **impersonation riski**: herhangi bir machine başka
> > `adcomputer:{guid}` talep edebilir.
>
> **3. Mitigation: Template Issuance Requirements (F2-A absorb iter-2)** — TEMPLATE Properties → Issuance Requirements tab:
>
> | Setting | Value | Anlam |
> |---|---|---|
> | Authorized signatures | **`0`** | Enrollment Agent flow YOK — bizim INF/certreq akışı agent signed-request üretmiyor |
> | CA certificate manager approval | **`ENABLED`** (checkbox) | Manual sign-off pipeline; request **pending state'e geçer (API `CR_DISP_UNDER_SUBMISSION`=5 / CA DB `Disposition` column=9; HRESULT YOK — certreq output "taken under submission" text)**; CA Manager Certification Authority MMC > Pending Requests'tan approve eder. [F1-A absorb iter-5/6: iki ayrı disposition katmanı — API (ICertRequest::Submit return CR_DISP_*) vs CA DB Disposition column (certutil -view -restrict); API ve DB değerleri eşleşmez, hangisi geçerli operator'ın kullandığı tool'a bağlı] |
>
> **DİKKAT**: `Authorized signatures: 1` setting'i farklı semantiktir — Enrollment Agent
> tarafından N tane CA-approved enrollment agent'in request'i co-sign etmesini gerektirir.
> Bu modeli kullanmıyoruz; bizim akış INF üzerinden direkt machine submit + CA Manager
> manual approve. Önceki versiyonda "authorized signatures: 1" yanlış yazılmıştı (iter-1
> dokümanı); F2-A absorb iter-2 ile düzeltildi.
>
> Her cert request **manuel CA Manager onayı** bekler. Operator MMC'de "Pending Requests"
> kuyrugundan inceler:
>
> - PowerShell: `certutil -view -restrict "Disposition=9"` (9 = TAKEN UNDER SUBMISSION)
> - Manuel: machine objectGUID == requested adcomputer GUID match doğrulanır
> - Issue: `certutil -resubmit <RequestId>`
> - Deny: `certutil -deny <RequestId>` + audit log
>
> **F2-B absorb iter-2** — Client side (enroll-endpoint-agent-cert.ps1) pending-aware:
> certreq -submit "RequestId: N" döner → script JSON state'e persist eder
> (`$env:ProgramData\faz22.3-pending-requests.json`) → next daily run `certreq -retrieve`
> ile cert hazır olduğunda alır → -accept install. 7+ gün pending stale → operator alert.
> Duplicate guard: pending varsa yeni submit YASAK.
>
> **Scope sürdürülebilirliği**:
>
> | PC count | Manuel CA Manager pipeline? | Mitigation |
> |---|---|---|
> | 5 PC (Phase 1 pilot) | OK (5 manuel review/hafta — sürdürülebilir) | Manuel review yeterli |
> | 50 PC (Phase 2 IT dept) | Marjinal (50 review/hafta zorlaşır) | **Custom AD CS policy module gerek** (Phase 2 ön-koşulu) |
> | 800 PC (Phase 3 full) | İmkansız | **Custom AD CS policy module mandatory** |
>
> **Custom AD CS policy module** (Phase 2 ön-koşulu, ayrı board issue):
> - .NET assembly DC üzerinde `ICertPolicy2` interface implement eder
> - Her request submit edildiğinde: requester machine objectGUID extract → requested
>   `adcomputer:{guid}` parse → match check → auto-approve veya auto-deny
> - Manuel CA Manager queue tamamen bypass edilir; impersonation bypass YAPILAMAZ
> - Reference impl: https://learn.microsoft.com/en-us/windows/win32/seccertenroll/cert-policy-module
>
> **Bu runbook (pilot 5 PC scope)** manuel pipeline ile sınırlı; custom policy module Phase 2
> öncesi ayrı board issue ile ele alınacak.

### 3.3 Custom URI:adcomputer:{objectGUID} SAN extension mekanizması

Standart AD CS template auto-enrollment URI extension'ı dinamik objectGUID ile basamaz (iter-4 F2 + iter-5 F1 + iter-6 F1 absorb). Çözüm: GPO startup script + certreq 3-step flow.

**Script**: `scripts/faz22-mass-deployment/enroll-endpoint-agent-cert.ps1`

Davranış (her pilot PC üzerinde boot sırasında ve günlük 03:00):

1. **DirectorySearcher LDAP query** (RSAT-free, built-in .NET): `objectGUID` AD'den oku
2. **Idempotent check**: existing cert SAN URI:adcomputer:{guid} + NotAfter > 30 gün → skip (exit 0); plus stale pending state temizliği (cert mint edildiyse leftover JSON entry remove)
3. **F2-B 2-fazlı certreq flow (iter-2 absorb)**:
   - **Faz 1 (initial submit)** — eğer `faz22.3-pending-requests.json` bu PC için entry içermiyorsa:
     - `certreq -new -q -f $inf $req` — INF'den request oluştur
     - `certreq -submit -q -f -config "ACIKDC01\ACIK Endpoint CA" $req $cer` — CA'ya gönder
     - Output parse: `RequestId: <int>` regex (CA Manager approval ENABLED → pending state)
       - RequestId döndü ise → JSON state persist (RequestId + submitted_at + dns_name + guid) + exit (cert henüz yok)
       - Cert hemen geldiyse (CA approval bypass) → direkt `-accept` + state-free
   - **Faz 2 (pending retrieve)** — eğer JSON state'de pending entry varsa (duplicate guard: yeni submit YASAK):
     - Stale check: `submitted_at > 7 gün` → operator alert (state korunur; manuel inspection gerek)
     - `certreq -retrieve -config $CAConfig $RequestId $cer` — CA'dan cert hazır mı çek
       - Cert hazır (exit 0 + cer file > 0) → `certreq -accept -q -f -machine $cer` install + pending state remove
       - Hâlâ pending (`taken under submission`) → warn log + skip (next daily run retry)
       - Denied (API `CR_DISP_DENIED`=2; certreq -retrieve exit non-zero + output contains "denied" text — F1-A absorb iter-5/6/7: HRESULT 0x80094004 != denied semantik; CA DB Disposition column değeri için RequestId-based lookup kullanın `certutil -view -restrict "RequestId=<id>" -out "RequestId,Disposition,DispositionMessage,RequesterName"` — gerçek CA DB değeri operator pilot run sonrası live evidence ile teyit edilmeli, hardcoded sayı kullanılmaz) → error log + pending state remove (next run yeni submit eder)

INF içeriği:
```ini
[NewRequest]
Subject = "CN=$dnsName"
KeySpec = 1
KeyLength = 2048
Exportable = FALSE
MachineKeySet = TRUE
ProviderName = "Microsoft Platform Crypto Provider"
RequestType = PKCS10

[RequestAttributes]
CertificateTemplate = "EndpointAgentMachineCert"  # F1 absorb: SHORT NAME (hyphenless), NOT display name

[Extensions]
2.5.29.17 = "{text}"
_continue_ = "dns=$dnsName&"
_continue_ = "URL=adcomputer:$guid"
```

**GPO startup script deploy**: SYSVOL `\\acik.local\sysvol\acik.local\scripts\faz22-mass-deployment\enroll-endpoint-agent-cert.ps1`

**GPO link**: Computer Configuration > Policies > Windows Settings > Scripts (Startup/Shutdown) > Startup > PowerShell Scripts tab

**Schedule Task GPO** (renewal): Computer Configuration > Preferences > Control Panel Settings > Scheduled Tasks > New Scheduled Task (Windows 7+)
- Trigger: Daily 03:00
- Action: `powershell.exe -ExecutionPolicy Bypass -NoProfile -File \\acik.local\sysvol\acik.local\scripts\faz22-mass-deployment\enroll-endpoint-agent-cert.ps1`
- Run as: NT AUTHORITY\SYSTEM with highest privileges

---

## 4. Pilot PC verification (P0-23 acceptance)

### 4.1 OU + GPO link

**Pilot OU**: `OU=EndpointPilot,DC=acik,DC=local`

```powershell
# OU yoksa create
New-ADOrganizationalUnit -Name "EndpointPilot" -Path "DC=acik,DC=local"

# GPO link
$gpo = Get-GPO -Name "Faz22.3-EndpointAgent-MachineCertEnroll"
New-GPLink -Guid $gpo.Id -Target "OU=EndpointPilot,DC=acik,DC=local"

# 5 pilot PC'yi OU'ya taşı (operator IT karar)
Get-ADComputer -Identity "PILOT-PC-01" | Move-ADObject -TargetPath "OU=EndpointPilot,DC=acik,DC=local"
# ... PILOT-PC-02..05
```

### 4.2 GPO refresh + cert mint trigger

```powershell
# Pilot PC'lerde
gpupdate /force /target:computer
# veya boot bekle (90-120 dk gpresult cycle)
```

### 4.3 P0-23 verify (her pilot PC'de)

```powershell
# scripts/faz22-mass-deployment/verify-machine-cert.ps1 deploy edip pilot PC'de run
.\verify-machine-cert.ps1                  # human readable
.\verify-machine-cert.ps1 -Json            # JSON automation output
.\verify-machine-cert.ps1 -ExitCodeOnFail  # CI gate
```

**Beklenen output (PASS)**:
```
  Computer:       PILOT-PC-01
  Domain:         acik.local
  Domain-joined:  True
  AD objectGUID:  abc12345-...
  Cert found:     True
  SAN URI match:  True
  Thumbprint:     A1B2C3D4...
  Days to expiry: 365
  Template:       EndpointAgentMachineCert
  ✓ P0-23 PASS
```

**FAIL durumları**:

| Symptom | Olasılık | Fix |
|---|---|---|
| `Cert found: False` | GPO startup script henüz çalışmadı | `gpupdate /force /target:computer` + reboot + 5dk bekle |
| `SAN URI match: False` | Cert mint edildi ama URI extension yok | Template `EndpointAgentMachineCert` (HYPHENLESS short name — F1 absorb) published mi? certreq inf doğru mu? |
| `Days to expiry: <= 0` | Cert expired (template validity period bug) | Template properties → Issuance Requirements → Validity period 1 year+ |
| `error: PC not domain-joined` | 22.3 scope dışı PC | OU'dan çıkar veya 22.2.A non-domain scope kullan |

### 4.4 Phase 0 acceptance gate

5/5 pilot PC `verify-machine-cert.ps1 -ExitCodeOnFail` exit 0 → P0-23 PASS.

**Plus**: Phase 0 P0-1..P0-22 diğer gate'leri (ADR-0029 §"Phase 0 — Operator Manual Preflight Checklist") tamamlanmalı:

- P0-12 mTLS reachability (corp PC → `mtls.testai.acik.com:443` for test/pilot; `mtls.ai.acik.com:443` only after prod promotion) — Task #178 backend deploy bekleyebilir
- P0-13 nginx ingress mTLS passthrough config — gitops PR ayrı
- P0-14 CRL/OCSP reachability (R24 bounded grace) — IIS CRL distribution (§3.6 manual)
- P0-15 SYSTEM context UNC share read (PsExec /s) — operator pilot PC test
- P0-16 backend-to-AD LDAPS reachability — Task #178 dep
- P0-18 EDR/WDAC/AppLocker baseline (Trusted Publisher AD CS root cert) — operator IT manual
- P0-19 Trusted Publisher store (LocalMachine\TrustedPublisher) — code signing cert manual deploy
- P0-21 Egress firewall (corp subnet → `mtls.testai.acik.com:443`; later prod wave → `mtls.ai.acik.com:443`) — operator IT manual
- P0-22 Fleet TPM readiness sample (10 PC ≥95% TPM Enabled+Ready)

Phase 0 fail noktası fix edilmeden Phase 1 5-PC pilot başlatılmaz.

---

## 5. Failure modes + rollback

### 5.1 Common errors

> **F1-A absorb (iter-4)** — HRESULT mapping önceki versiyonlarda canonical disposition
> semantik ile uyumsuzdu: `0x80094012` hem `CERTSRV_E_TEMPLATE_DENIED` hem "template not
> found" gibi yorumlanıyordu; `0x80094800` permission denied + unsupported birlikte;
> `0x80094004` `CERTSRV_E_PROPERTY_EMPTY` ile "Request denied by CA Manager" karışmıştı.
> Aşağıdaki tablo Microsoft AD CS canonical disposition semantik (Win Error sembolik
> isimler) ile uyumlu yeniden yazıldı. Her HRESULT tek anlam taşır + doğru olası fix
> önerilir.

| HRESULT | Win Error | AD CS Disposition Semantik | Olası Fix |
|---|---|---|---|
| `0x80094012` | `CERTSRV_E_TEMPLATE_DENIED` | Template request denied — template policy/permission fail. Olası nedenler: (a) requesting principal Template ACL'de yok (Domain Computers Read+Autoenroll grant eksik), (b) EKU constraint mismatch, (c) template AD'de var ama short name'i INF/certreq verilenle eşleşmiyor (MMC display name vs canonical hyphenless short name). | F1 absorb: HYPHENLESS short name canonical (`EndpointAgentMachineCert`) — MMC Properties → General → Template name HYPHENLESS; INF `CertificateTemplate = "..."` aynı string. Plus: Template Security → Domain Computers grant **Read + Autoenroll**. Plus: Extensions → Application Policies → Client Authentication (1.3.6.1.5.5.7.3.2) EKU. |
| `0x80094800` | `CERTSRV_E_UNSUPPORTED_CERT_TYPE` | Template cert type unsupported by CA. Olası nedenler: (a) CA template publish missing (`certutil -setcatemplates +EndpointAgentMachineCert,EndpointAgentCodeSigning` çalıştırılmadı), (b) Template Compatibility setting CA'nın desteklediğinin dışında (Windows Server 2008 vs 2016+ vb.). | Publish: `certutil -setcatemplates +EndpointAgentMachineCert,EndpointAgentCodeSigning` (DC üzerinde Enterprise Admin). Plus Template Compatibility tab: CA = Windows Server 2016 + Recipient = Windows 10 (script default). Plus `certutil -catemplates` ile published list verify. |
| `0x80094003` | `CERTSRV_E_PROPERTY_EMPTY` | Request property missing — INF'de zorunlu attribute eksik (örn. Subject CN empty, KeyLength 0, SAN missing). NOT: AD CS "Request taken under submission" disposition message DE bu kodla return etmez; o CA Manager pending state için `0x80094003` ile karıştırılan bir Windows error message string'tir (gerçek disposition kodu = `5` pending). Bu satır kod-level property fail içindir. | Template Subject Name = "Supply in the request" (F2 absorb) + INF `Subject = "CN=$dnsName"` non-empty + `KeyLength = 2048` + `[Extensions] 2.5.29.17 = "{text}" _continue_ = "URL=adcomputer:$Guid"` (SAN non-empty). |
| `0x80094004` | `CERTSRV_E_BAD_RENEWAL_CERT_ATTRIBUTE` | Renewal cert attribute bad — cert renewal context'inde mevcut cert ile bad/missing attribute mismatch (örn. renewal request'inde existing cert SAN URI yok). Bu kod operator manual deny DEĞİL; "Request denied by CA Manager" pending request reject case'i Disposition=`2` (CERT_DENIED) field'ı ile döner ve genelde HRESULT `0x80094800` veya event log via raporlanır. | Renewal flow için: existing cert SAN URI:adcomputer:{guid} match olmalı (idempotent check zaten yapıyor). Template Issuance Requirements "Require the following for re-enrollment: Valid existing certificate" check. Initial enrollment için bu kod beklenmez; tetiklerse Template re-enrollment policy review gerek. |
| `0x80092004` | `CRYPT_E_NOT_FOUND` | Private key binding fail — CSP/KSP mismatch. INF `ProviderName` ile template Cryptography Provider eşleşmiyor (örn. INF Platform Crypto Provider isterken template Software KSP), veya machine cert store empty + machine key set parameter missing. | INF `ProviderName = "Microsoft Platform Crypto Provider"` + Template Cryptography Provider = Platform Crypto Provider (TPM) eşleşmeli. Plus INF `MachineKeySet = TRUE` + `certreq -accept -machine` flag. F3 software fallback durumunda her ikisini de `Microsoft Software Key Storage Provider`a güncelle. |
| `Pending state, no HRESULT, "Request taken under submission"` | — | CA Manager approval **ENABLED** (F2-A) → cert pending operator manual sign-off. **Disposition iki ayrı katmanda (F1-A iter-6 absorb)**: API ICertRequest::Submit return value `CR_DISP_UNDER_SUBMISSION` = `5`; CA database `Disposition` column `certutil -view -restrict "Disposition=9"` ile sorgulanır = `9`. certreq output: "Request was added to the database with Request Id: <int>. The request is taken under submission." | Normal davranış — F2-B 2-fazlı flow: certreq -submit RequestId parse → JSON state persist → daily `certreq -retrieve` ile cert hazır olduğunda alır. Operator MMC certsrv.msc → Pending Requests'ten approve (`certutil -resubmit <RequestId>`). |
| `Denied state, "denied" text in certreq output` | — | Operator CA Manager queue'da request'i deny etti (manuel inspection sonrası — örn. requested adcomputer GUID match check fail). **API katmanı (canonical, dökümante)**: `CR_DISP_DENIED` = `2` (ICertRequest::Submit return value, certreq output). **CA DB Disposition column** için RequestId-based lookup kullanın: `certutil -view -restrict "RequestId=<id>" -out "RequestId,Disposition,DispositionMessage,RequesterName"` — F1-A iter-7 absorb: önceki "Disposition=8" claim'i AD CS canonical docs ile cross-verify edilmedi, evidence-derived value operator pilot run sonrası live test ile teyit edilmeli; hardcoded CA DB column value runbook'tan kaldırıldı. | F2-B: pending state cleanup yapar (script log'da "F2-B DENIED" görünür) → sonraki run yeni submit eder. Eğer aynı PC sürekli deny ediliyorsa root cause analysis gerek (PC OU dışında mı, machine objectGUID rotated mı, custom policy module reject mi). |
| `Install-AdcsCertificationAuthority: The CA Already Installed` | — | CA initialize daha önce yapılmış (idempotent skip path) | `certutil -getconfig` ile var olan CA'yı kontrol et + F3-A `Test-CACryptoProvider` ile provider audit (software KSP varsa `-AllowSoftwareKey` veya re-init). |
| `Install-AdcsCertificationAuthority: A required privilege is not held` | — | Enterprise Admin yetkisi yok | Domain Admin + Enterprise Admin login |
| `F3 fail-closed: TPM not ready and -AllowSoftwareKey NOT given` | — | Test-TpmCapability fail (TPM disable/absent veya Platform CSP yok) | Hardware: BIOS'tan TPM 2.0 enable + `Initialize-Tpm`. Software fallback (degraded): script'i `-AllowSoftwareKey` flag ile yeniden çalıştır (R10 risk owner approval log'a yazılır). |
| `F3-A fail-closed: Existing CA key not TPM-bound + -AllowSoftwareKey not specified` | — | Existing CA software CSP/KSP ile init edilmiş (eski install veya TPM degraded init) | İki seçenek: (a) `-AllowSoftwareKey` flag ile owner approval (R10 risk artar), (b) CA destructive re-init Platform CSP ile (`Uninstall-AdcsCertificationAuthority` + backup + re-init — etki: tüm cert template'leri reissue gerek). |
| `F2-C: CertSvc not Running after restart` veya idempotent path Running check fail | — | Step 2.5 restart fail (net start exit non-zero veya service degraded post-restart), VEYA idempotent skip path'inde flag set olduğu halde servis down. iter-4 F2-C: idempotent path'te de Running check zorunlu. | `Get-Service CertSvc` + Event Viewer "Application" log → root cause (port conflict, AD CS DB corruption, missing dep). Manual fix sonrası `Start-Service CertSvc` + script `-Step EditFlag` re-run (idempotent skip yine Running double-check yapar). |
| `enroll-endpoint-agent-cert.ps1: AD lookup failed` | PC domain-joined değil | 22.3 scope dışı; 22.2.A non-domain runbook'a yönlendir |
| `F2-B STALE: Pending request older than X days` | CA Manager pending queue'da unattended request | Operator MMC certsrv.msc → Pending Requests inceleme + approve veya deny. Approve sonrası enroll script next run -retrieve ile cert alır. Deny sonrası state cleanup + yeni submit. |
| `F2-B iter-4 fail-closed: pending-requests.json corrupt` | JSON parse fail veya schema eksik field (kısmi yazım / disk dolu / process kill race) | Operator manuel reset gerek — §5.4 "Corrupt pending JSON recovery" |
| `F2-B iter-4: Mutex timeout (30s)` | GPO startup + Schedule Task aynı anda tetiklendi; ikinci instance 30s waitOne sonra skip etti | Normal davranış (idempotent — next daily run cert mint eder); 24h içinde tekrar tekrarlanırsa GPO/scheduler tetik zamanı stagger |
| `Get-GPO: A specified directory service object could not be found` | GPO yoktu, runtime yarattık ama scope yanlış | `New-GPO + New-GPLink` order correct |

### 5.2 Full rollback (5 dk içinde)

```powershell
# 1. GPO unlink + delete
Remove-GPLink -Name "Faz22.3-EndpointAgent-MachineCertEnroll" -Target "OU=EndpointPilot,DC=acik,DC=local"
Remove-GPO -Name "Faz22.3-EndpointAgent-MachineCertEnroll" -Confirm:$false

# 2. CRL distribution rollback (IIS site disable)
# (manual via IIS Manager — Stop Site "crl.acik.local")

# 3. Cert templates unpublish (NOT delete — başka kullanım olabilir)
certutil -setcatemplates -EndpointAgentMachineCert,EndpointAgentCodeSigning  # F1 absorb: short name (hyphenless)

# 4. (DESTRUCTIVE — only if absolute necessity) CA rollback
# Stop-Service CertSvc
# Uninstall-AdcsCertificationAuthority -Force
# Uninstall-WindowsFeature ADCS-Cert-Authority -IncludeManagementTools -Restart
# Note: CA uninstall AD'deki tüm cert template'leri AFFECT eder
#       (başka servis kullanıyor olabilir) — DİKKAT

# 5. Pilot PC'lerden cert temizle (operator IT)
# Foreach pilot PC:
# Get-ChildItem Cert:\LocalMachine\My | Where { $_.Issuer -like "*ACIK Endpoint CA*" } | Remove-Item
```

### 5.3 Pilot PC'de cert mint fail

Per-PC investigation:
```powershell
# Log dosyası
Get-Content "C:\ProgramData\faz22.3-enroll-cert.log" -Tail 50

# AD CS event log (DC üzerinde)
Get-WinEvent -LogName "Application" -ProviderName "Microsoft-Windows-CertificateServicesClient-AutoEnrollment" -MaxEvents 20

# certreq retry manual
\\acik.local\sysvol\acik.local\scripts\faz22-mass-deployment\enroll-endpoint-agent-cert.ps1 -Verbose
```

### 5.4 F2-B iter-4 — Corrupt pending JSON recovery + CA Manager approval backlog

> **F2-B iter-4 absorb (Codex REVISE remaining 3 finding)** — `Read-PendingRequestsJson`
> önceki versiyonda corrupt JSON durumunda fail-OPEN davranıyordu (`@{}` return + log warn);
> bu, `Get-PendingRequest` `$null` döndürdüğünde script "no pending" branch'ine girip
> YENİ submit yapıyordu → CA Manager queue'da duplicate request. iter-4 fail-CLOSED:
> parse hatası veya schema eksik field tespit edildiğinde script throw eder + operator
> manuel inspect/reset gerek. Atomic write (`temp + Move-Item`) + cross-process mutex
> (`Global\Faz22.3.PendingRequests`) ile race condition önlenir.

**Senaryo 1 — Corrupt pending JSON recovery (pilot PC üzerinde):**

```powershell
# 1. Corrupt JSON inspect (operator visual check)
Get-Content "$env:ProgramData\faz22.3-pending-requests.json" -Raw

# 2. Backup (forensic — sebep analizi için saklanır)
$ts = Get-Date -Format yyyyMMdd-HHmmss
Copy-Item "$env:ProgramData\faz22.3-pending-requests.json" "$env:ProgramData\faz22.3-pending-requests.json.corrupt-$ts"

# 3. CA queue'da bu PC için pending var mı kontrol (DC üzerinde)
# certutil -view -restrict komutu DC'de çalışır; operator IT inspect eder.
# Eğer pending request varsa: machine objectGUID match check + CA Manager approve veya deny
# (örnek: certutil -view -out "RequestId,RequesterName,NotBefore,NotAfter,Disposition" -restrict "Disposition=9,RequesterName=$env:USERDNSDOMAIN\$env:COMPUTERNAME$")

# 4. Reset: corrupt JSON sil → script next run yeni submit yapar
Remove-Item "$env:ProgramData\faz22.3-pending-requests.json" -Force

# 5. Script manuel tetik (next 24h scheduled run beklenmez)
\\acik.local\sysvol\acik.local\scripts\faz22-mass-deployment\enroll-endpoint-agent-cert.ps1 -Verbose

# 6. Audit log capture (corrupt sebebi analizi)
Get-Content "$env:ProgramData\faz22.3-enroll-cert.log" -Tail 100 |
  Select-String -Pattern "F2-B iter-4|corrupt|atomic write|Mutex"
```

**Senaryo 2 — CA Manager pending approval backlog (DC operator):**

5 PC pilot için CA Manager manual approval workload **tolerable** (5 cert / hafta + renewal cycle).
50/800 ramp öncesi custom AD CS policy module schedule edilmeli; o noktaya kadar:

| Phase | PC count | Approval workload | Mitigation |
|---|---|---|---|
| Phase 1 (pilot) | 5 | ~5/hafta + renewal (yıl başına 5 renewal) | Manual MMC certsrv.msc → Pending Requests; haftalık operator IT 5dk |
| Phase 2 (IT dept) | 50 | ~50/hafta + 50 renewal/yıl | **Custom AD CS policy module gerek** — Phase 2 ön-koşulu (ayrı board issue) |
| Phase 3 (full) | 800 | ~800/hafta — imkansız manuel | **Custom policy module mandatory** (auto-approve based on machine objectGUID match) |

```powershell
# CA Manager pending queue inspect (DC üzerinde, Enterprise Admin)
certutil -view -out "RequestId,RequesterName,NotBefore,Disposition" -restrict "Disposition=9"

# Approve single request
certutil -resubmit <RequestId>

# Deny + audit log
certutil -deny <RequestId>
# Log: Event Viewer → Applications and Services → AD CS

# Bulk approve (script — pilot PC scope match check ile)
$pending = certutil -view -out "RequestId,RequesterName" -restrict "Disposition=9" 2>&1 |
  Select-String -Pattern "^\s*Request ID:" -Context 0,1
foreach ($entry in $pending) {
    # MANUAL: requester == OU=EndpointPilot kontrol; otomatik bulk approve YASAK (security)
    Write-Host "RequestId: $entry — operator manuel inceleme gerek"
}
```

**Atomic write / mutex doğrulama (post-recovery verify):**

```powershell
# Atomic write: temp file orphan kalmamalı
Test-Path "$env:ProgramData\faz22.3-pending-requests.json.tmp"
# Beklenen: False — temp dosya sadece write esnasında var olur, başarılı Move-Item sonrası kaybolur

# Mutex doğrulama: concurrent run simulasyonu (2 paralel ps -File ile)
Start-Job { .\enroll-endpoint-agent-cert.ps1 -Verbose }
Start-Job { .\enroll-endpoint-agent-cert.ps1 -Verbose }
# Beklenen: log'da "Mutex acquired" 1 instance + "Mutex timeout" 1 instance
# Plus: post-run pending-requests.json tek bir entry (race olmadığı kanıtı)
```

---

## 6. Handoff to Faz 22.3 Phase 1 (5 PC pilot)

AD CS preflight + GPO + 5 pilot PC cert mint OK olduğunda:

1. **Backend mTLS endpoint LIVE** (Task #178 — `POST /api/v1/endpoint-agent/endpoint-enrollments/auto`)
2. **Agent --auto-enroll feature** built + signed (Task #179 + Task #180)
3. **MSI WiX package** AD CS code signing imzalı (Task #180)
4. **GPO Software Installation** policy create + link `OU=EndpointPilot` (Task #181)
5. **5 pilot PC reboot** → MSI install fire → agent service start → mTLS auto-enroll → backend `ENDPOINT_AUTO_ENROLLED` audit
6. **Phase 1 acceptance gate** ADR-0029 §"Phase 1 (5 domain-joined PC pilot)" — 5/5 cert mint + install + heartbeat + command lifecycle + denominator T0 freeze + R24 CRL outage 2 sub-scenario verify

Phase 1 PASS → Phase 2 (50 PC IT dept) → Phase 3 (800 PC full).

---

## 7. Cross-AI peer review provenance

### ADR-0029 (Plan A) iter chain (PR #1078 MERGED 2026-05-26)

| Iter | Verdict | Findings | Absorb commit |
|---|---|---|---|
| 1 | REVISE | 10 | `7fe41f2` |
| 2 | REVISE | 6 + 6 risk | `5a60e6c` |
| 3 | REVISE | 5 | `98d2527` |
| 4 | REVISE | 5 (F1-F5) | `f45b7a2` |
| 5 | REVISE | 4 (F1-F4) | `3e5570f` |
| 6 | REVISE | 3 (F1-F3) | `4a5531b` |
| **7** | **AGREE** | — | `731d5b3` (nit) |

Reviewer provider: OpenAI Codex (cross-AI per HARD RULE — implementer Claude Anthropic). Thread: `019e667f-98a5-7980-8f80-613fc1a1ed82`.

ADR-0029 Plan A owner-approved 2026-05-26 ("tam otonom devam et"). MERGED PR #1078 commit `d677511e` (gitops main).

### PR #1080 (AD CS preflight scripts + runbook) iter chain

| Iter | Verdict | Findings | Absorb commit |
|---|---|---|---|
| 1 | REVISE | 5 (F1 short name + F2 EditFlag SAN2 + F3 TPM fail-closed + F4 cert prune + F5 -Force) | `d9db1e2` |
| 2 | REVISE | 5 (F2-A authorized-signatures vs CA-Manager-approval + F2-B pending-aware enrollment + F2-C CertSvc restart fail-closed + F3-A existing CA provider audit + F1-A HRESULT canonical mapping) | `806a513` |
| 3 | REVISE | 3 remaining (F2-B iter-4 pending JSON fail-CLOSED + atomic write + mutex; F2-C iter-4 idempotent Running check; F1-A iter-4 HRESULT canonical disposition semantik tablosu yeniden yazıldı) | this commit |

Reviewer provider: OpenAI Codex. PR #1080 board issue: #1079.
