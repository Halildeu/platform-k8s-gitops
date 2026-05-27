# RB Faz 22.3 — AD CS Infrastructure Setup (DC operator runbook)

> **Status**: PREP (operator runbook — agent scripts ready; IT operator execution required)
> **Scope**: Faz 22.3 domain-wide mass deployment Katman 1 (AD CS) preflight + GPO infrastructure
> **Canonical decision**: ADR-0029 (PR #1078 MERGED 2026-05-26) §"Katman 1 — AD CS (Active Directory Certificate Services)"
> **Tracked by**: [#1079](https://github.com/Halildeu/platform-k8s-gitops/issues/1079) (Task #177 AD CS preflight)
> **Cross-AI peer review**:
> - Codex (OpenAI) thread `019e667f-98a5-7980-8f80-613fc1a1ed82` iter-7 AGREE (ADR-0029 12 finding F1-F5 + F1-F4 + F1-F3 absorbed)
> - Codex (OpenAI) PR #1080 iter-1 5 finding (F1 short name + F2 EditFlag SAN2 + F3 TPM fail-closed + F4 cert prune + F5 -Force) absorbed
> - Codex (OpenAI) PR #1080 iter-2 REVISE 5 finding absorbed: F2-A (authorized signatures vs CA Manager approval), F2-B (pending approval 2-fazlı enrollment), F2-C (CertSvc restart fail-closed), F3-A (existing CA path provider audit), F1-A (HRESULT mapping canonical)

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
| Issuance Requirements | **CA certificate manager approval: ENABLED** (ayrı checkbox) | **F2-A absorb iter-2 HIGH** — manual sign-off checkbox; request pending state'e geçer (HRESULT `0x80094003`); CA Manager Certification Authority MMC'den approve eder; 5 PC pilot sürdürülebilir, 50/800 ramp için custom policy module gerek (§3.2.5) |
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
> | CA certificate manager approval | **`ENABLED`** (checkbox) | Manual sign-off pipeline; request pending state'e geçer (HRESULT `0x80094003`); CA Manager Certification Authority MMC'den approve eder |
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
       - Denied (HRESULT `0x80094004`) → error log + pending state remove (next run yeni submit eder)

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

- P0-12 mTLS reachability (corp PC → endpoint-agent-mtls.testai.acik.com:443) — Task #178 backend deploy bekleyebilir
- P0-13 nginx ingress mTLS passthrough config — gitops PR ayrı
- P0-14 CRL/OCSP reachability (R24 bounded grace) — IIS CRL distribution (§3.6 manual)
- P0-15 SYSTEM context UNC share read (PsExec /s) — operator pilot PC test
- P0-16 backend-to-AD LDAPS reachability — Task #178 dep
- P0-18 EDR/WDAC/AppLocker baseline (Trusted Publisher AD CS root cert) — operator IT manual
- P0-19 Trusted Publisher store (LocalMachine\TrustedPublisher) — code signing cert manual deploy
- P0-21 Egress firewall (corp subnet → endpoint-agent-mtls.testai.acik.com:443) — operator IT manual
- P0-22 Fleet TPM readiness sample (10 PC ≥95% TPM Enabled+Ready)

Phase 0 fail noktası fix edilmeden Phase 1 5-PC pilot başlatılmaz.

---

## 5. Failure modes + rollback

### 5.1 Common errors

> **F1-A absorb (iter-2 LOW)** — HRESULT mapping önceki versiyonda çelişkiliydi (`0x80094012` aynı kodu hem "template not found" hem "permission" gibi taşıyordu). Aşağıdaki tablo tek canonical mapping; her HRESULT bir anlama bağlı.

| Error Code / Symptom | Canonical Meaning | Fix |
|---|---|---|
| `0x80094012` (`CERTSRV_E_TEMPLATE_DENIED` / "template not found") | Template short name yanlış / display vs short name conflated | F1 absorb — MMC certtmpl.msc → Properties → General → Template short name HYPHENLESS (`EndpointAgentMachineCert`); display name farklı olabilir. INF/certreq HYPHENLESS canonical kullanır. |
| `0x80094800` | Template permission denied (Domain Computers Autoenroll yetkisi yok) veya template AD'de publish edilmemiş | Template Security tab → Domain Computers grant **Read + Autoenroll**. Plus `certutil -setcatemplates +EndpointAgentMachineCert,EndpointAgentCodeSigning` ile publish. |
| `0x80092004` | Private key binding fail (Cryptography Provider mismatch — INF `ProviderName` vs template Provider eşleşmiyor) | Template Cryptography tab → Provider = `Microsoft Platform Crypto Provider` (TPM) seçili olmalı; INF `ProviderName` ile birebir match. F3 fallback durumunda `Microsoft Software Key Storage Provider`. |
| `0x80094003` ("taken under submission") | F2-A: `CA certificate manager approval: ENABLED` — request pending CA Manager onay bekliyor | Normal davranış. Operator MMC certsrv.msc → Pending Requests'ten inceleme + approve (`certutil -resubmit <RequestId>`). F2-B 2-fazlı enrollment: daily schedule task `certreq -retrieve` ile cert hazır olduğunda alır. |
| `0x80094004` (`CERTSRV_E_PROPERTY_EMPTY`) | Request denied by CA Manager (operator deny) veya policy module reject | Operator action — CA Manager Pending Requests'ten neden inceleme. F2-B: enroll-endpoint-agent-cert.ps1 pending state cleanup yapar, sonraki run yeni submit eder. Tekrar deny ise audit log + manuel root cause analysis. |
| `Install-AdcsCertificationAuthority: The CA Already Installed` | CA initialize daha önce yapılmış (idempotent skip path) | `certutil -getconfig` ile var olan CA'yı kontrol et + F3-A `Test-CACryptoProvider` ile provider audit (software KSP varsa `-AllowSoftwareKey` veya re-init). |
| `Install-AdcsCertificationAuthority: A required privilege is not held` | Enterprise Admin yetkisi yok | Domain Admin + Enterprise Admin login |
| `F3 fail-closed: TPM not ready and -AllowSoftwareKey NOT given` | Test-TpmCapability fail (TPM disable/absent veya Platform CSP yok) | Hardware: BIOS'tan TPM 2.0 enable + `Initialize-Tpm`. Software fallback (degraded): script'i `-AllowSoftwareKey` flag ile yeniden çalıştır (R10 risk owner approval log'a yazılır). |
| `F3-A fail-closed: Existing CA key not TPM-bound + -AllowSoftwareKey not specified` | Existing CA software CSP/KSP ile init edilmiş (eski install veya TPM degraded init) | İki seçenek: (a) `-AllowSoftwareKey` flag ile owner approval (R10 risk artar), (b) CA destructive re-init Platform CSP ile (`Uninstall-AdcsCertificationAuthority` + backup + re-init — etki: tüm cert template'leri reissue gerek). |
| `F2-C: CertSvc not Running after restart` | Step 2.5 restart fail (net start exit non-zero veya service degraded post-restart) | `Get-Service CertSvc` + Event Viewer "Application" log → root cause (port conflict, AD CS DB corruption, missing dep). Manual fix sonrası `Start-Service CertSvc` + script re-run. |
| `enroll-endpoint-agent-cert.ps1: AD lookup failed` | PC domain-joined değil | 22.3 scope dışı; 22.2.A non-domain runbook'a yönlendir |
| `F2-B STALE: Pending request older than X days` | CA Manager pending queue'da unattended request | Operator MMC certsrv.msc → Pending Requests inceleme + approve veya deny. Approve sonrası enroll script next run -retrieve ile cert alır. Deny sonrası state cleanup + yeni submit. |
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

---

## 6. Handoff to Faz 22.3 Phase 1 (5 PC pilot)

AD CS preflight + GPO + 5 pilot PC cert mint OK olduğunda:

1. **Backend mTLS endpoint LIVE** (Task #178 — `POST /api/v1/endpoint-admin/endpoint-enrollments/auto`)
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
| 2 | REVISE | 5 (F2-A authorized-signatures vs CA-Manager-approval + F2-B pending-aware enrollment + F2-C CertSvc restart fail-closed + F3-A existing CA provider audit + F1-A HRESULT canonical mapping) | this commit |

Reviewer provider: OpenAI Codex. PR #1080 board issue: #1079.
