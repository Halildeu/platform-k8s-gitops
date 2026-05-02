# Runbook — Faz 22.1.IT: EndpointPilot OU + Pilot Cihaz Hazırlığı

> **Sprint**: "Prod post-cutover compliance" — Faz 22.1.IT async track
> **Owner**: Engineering taslağı + IT execution + IT bilgi doldurma
> **Reference**: ADR-0012-EA `docs/adr/0012-EA-endpoint-admin-governance-charter.md`
> **Codex**: thread `019de00f` revize — engineering writes runbook, IT fills execution details
> **Status**: TASLAK (IT cevap bekliyor)

## Amaç

Faz 22.2 IT-owned pilot scope için Active Directory `acik.local` domain'inde `EndpointPilot` Organizational Unit (OU) oluşturma + 1-3 IT kontrollü Windows 10/11 test cihaz hazırlama. **22.2 unlock** için minimum **1 cihaz inventory baseline** gerekli.

## Scope (22.1.IT)

| In-scope | Out-of-scope |
|---|---|
| `acik.local` domain | BOREAS, CESS (Faz 22.3+) |
| EndpointPilot OU oluşturma | Domain-wide deployment (~800 cihaz; 22.3+ gradual) |
| 1-3 IT-owned Windows 10/11 test cihaz | Gerçek son kullanıcı cihazları (22.3 Restricted) |
| OU baseline + cihaz inventory | Authenticode trusted signing (22.2 mandatory) |
| Manual install IT-controlled (pilot) | GPO/Intune/SCCM auto-deploy (22.3+) |

## 22.1 invariantları (yapılMAYACAK)

EndpointPilot pilot cihazlarda 22.1 boyunca **kesinlikle yapılmaz** (ADR-0012-EA §22.1 invariantları):

- ❌ Password reset (lokal SAM, AD, Entra, M365 — hepsi 22.2+)
- ❌ Arbitrary file access (Desktop/Documents/Downloads whitelist 22.2+)
- ❌ Destructive command execution (D35-EA-3..5 dual-control 22.2+)
- ❌ BOREAS, CESS domain işlemleri
- ❌ Trusted signing olmadan EndpointPilot dışı dağıtım (lab-only-evidence imza yalnız Parallels lab; IT-owned cihazlara yetkili değil)

## Engineering tarafı yapacaklar (TAMAM/HAZIR)

✅ Faz 22.1.0 milestone tamamlandı (`platform-agent` repo):
- `endpoint-agent.exe` Windows amd64 cross-build
- Lab-only-evidence imza (ephemeral self-signed cert)
- `install.ps1` + `uninstall.ps1` Windows installer scripts
- Windows service install/start/status/stop/uninstall + tamper protection (AG-019 DONE)
- Local user read-only adapter (AG-013 DONE)
- File log + Event Log source + write-time secret redaction (AG-014 DONE)
- README + LICENSE Apache 2.0 + 10 docs

🔄 Faz 22.1.1 + 22.1.2 + 22.1.3 paralel:
- BE-009 OpenFGA live (admin allow/deny + audit)
- BE-013 maintenance token live
- DD-EA-1 manifest contract drift gate
- DD-EA-5 minimal ESO secret path allowlist

## IT Tarafı Soruları (5 madde — IT lütfen cevapla)

Aşağıdaki 5 soruyu cevap olarak gönder. Engineering bu cevapları aldıktan sonra runbook'u finalize eder + EndpointPilot OU baseline + cihaz inventory için detaylı IT execution adımları ekler.

### Soru 1: OU Distinguished Name

**`EndpointPilot` OU hangi parent OU altında oluşturulacak?**

Örnek formatlar:
- `OU=EndpointPilot,OU=Workstations,DC=acik,DC=local`
- `OU=EndpointPilot,OU=Pilots,DC=acik,DC=local`
- `OU=EndpointPilot,DC=acik,DC=local` (root altında)

**Cevap**: `<DN bilgisini buraya yaz>`

### Soru 2: İlk Pilot Cihaz

**22.1 sonu için minimum 1 IT kontrollü Windows 10/11 cihaz baseline gerekli.**

Lütfen şu bilgileri ver:
- **Hostname**: (örn. `WS-PILOT-001`)
- **OS sürümü**: (Windows 10 versiyon? Windows 11 versiyon?)
- **IT owner**: (sahibinin/sorumlu IT personelinin adı)
- **Fiziksel/VM**: (gerçek hardware mı, Hyper-V/VMware/Parallels mı?)
- **Local admin erişim**: (RDP, console, IT yardım çağrısı?)
- **Mevcut domain join state**: (acik.local'e join'li mi yoksa workgroup mu?)
- **Mevcut EDR/AV**: (Defender, CrowdStrike, vb. — hangisi)

**Cevap**:
```
Hostname: <...>
OS: <Windows 10/11 + version>
IT owner: <isim>
Type: <fiziksel/VM>
Admin access: <yöntem>
Domain state: <acik.local-joined / workgroup>
EDR/AV: <isim>
```

### Soru 3: Kurulum Yöntemi (22.1 için)

**22.1 boyunca pilot cihaza `endpoint-agent.exe` nasıl kurulacak?**

Seçenekler:
- **(a) Manual IT-controlled install** — IT operatör RDP ile bağlanır, `install.ps1` çalıştırır, log toplar (lab-only-evidence imza geçerli, sınırlı kullanım)
- **(b) GPO sadece hazırlık** — GPO struct EndpointPilot OU üzerinde tanımlı ama startup script aktif değil (22.2'de Authenticode signed exe ile aktif edilir)
- **(c) Intune temporary scope** — Intune'da EndpointPilot device group, 22.2'de signed package upload

**Önerim**: (a) Manual IT-controlled — 22.1 invariantlarıyla uyumlu (trusted signing yok, dış dağıtım yok).

**Cevap**: `<a / b / c>`

### Soru 4: 22.1 Invariant Onayı

Yukarıdaki "22.1 invariantları" listesini IT olarak onaylıyor musun?

- ❌ Password reset YOK (lokal SAM, AD, Entra, M365)
- ❌ Arbitrary file access YOK
- ❌ Destructive command execution YOK
- ❌ BOREAS, CESS dokunulmaz
- ❌ Trusted signing olmadan EndpointPilot dışı dağıtım YOK

**Cevap**: `Onaylıyorum / Şu maddede çekincem var: <madde>`

### Soru 5: Evidence Formatı

**22.1.IT close evidence olarak ne kabul edilecek?**

Tercih:
- (a) Komut çıktısı (PowerShell terminal text dump): `service install/start/status/stop/uninstall`, `endpoint-agent.exe --version`, `dsregcmd /status`, `Get-WmiObject Win32_ComputerSystem`, `Get-CimInstance Win32_OperatingSystem`
- (b) Screenshot (UI confirmation, görsel)
- (c) Mixed (terminal text + 1-2 screenshot başlangıç + son durum)

**Önerim**: (a) Tek başına yeterli, reproducible + diff-friendly.

**Cevap**: `<a / b / c>`

## IT Cevap Sonrası Engineering Yapacaklar

5 cevap geldikten sonra engineering tarafı:

1. **OU baseline runbook**: `docs/RB-22-1-IT-endpointpilot-ou-execution.md` — IT-step-by-step (Active Directory Users and Computers, `New-ADOrganizationalUnit` PowerShell, security delegation, group policy link).
2. **Pilot cihaz inventory baseline**: agent enrollment dry-run, identity inventory komut çıktıları (`dsregcmd`, `Get-ADComputer`, `nltest`), evidence formatı.
3. **22.2 unlock kriteri**: "1 IT-owned Windows 10/11 cihaz inventory baseline alındı" check listesi.

## Bağımlılık ve Akış

```
22.1.IT scope (bu doküman)
    ↓
IT 5 soru cevap
    ↓
Engineering execution runbook + agent enrollment dry-run
    ↓
Pilot cihaz inventory baseline (Up/Functional)
    ↓
22.2 unlock kriteri: "minimum 1 IT-owned cihaz inventory baseline"
```

22.2 unlock için diğer 3 evidence sınıfı (Codex revize ADR-0012-EA §22.1 → 22.2 geçiş kriteri):
- **Agent**: CI'den üretilen artifact ile Parallels Win11 evidence ✅ (22.1.0 close)
- **Backend**: BE-009 + BE-013 Up/Functional/Secured ayrı kanıt 🔄 (22.1.1 + 22.1.2)
- **GitOps**: test overlay rollout digest match + ESO sync + 0 placeholder 🔄 (22.1.3)
- **IT**: EndpointPilot OU + 1 IT-owned cihaz baseline 🔄 (bu doküman, 22.1.IT)

Hepsi tamam → 22.2 IT-owned pilot tier başlatılır.

## Out-of-scope — bu doküman'a yazılmaz

- Authenticode trusted signing (Azure Trusted Signing — 22.2 pre-req docs ayrı)
- GPO startup script content (22.2 mandatory; 22.1 sadece OU struct)
- Intune device configuration profile (22.3 scope)
- EDR allowlist tam matrisi (22.2 — Defender/CrowdStrike binary path + signing thumbprint allowlist)

## Codex referans

- Thread `019de00f` — sprint review + IT track engineering/IT split önerisi (engineering runbook + IT execution details)
- ADR-0012-EA — pilot tier matrisi (Lab → IT-owned acik.local → Restricted)
- 22.1 invariantları (7 yapılMAYACAK madde)
