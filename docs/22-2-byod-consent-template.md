# Faz 22.2.A BYOD Consent Template (TR + EN)

> **Status**: DRAFT — `Operator/DPO/Legal review required before use` / `Operator/DPO/Hukuk incelemesi yapılmadan kullanıma sunulamaz`
> **Scope**: Faz 22.2.A non-domain Windows pilot, tier A2 (BYOD unmanaged Windows) only
> **Tracked by**: RB-faz22-non-domain-windows-pilot.md §12 BYOD consent, privacy, KVKK, uninstall + ADR-0012-EA "22.2 scope amendment" section
> **Predecessor**: gitops PR #1043 RB MERGED `47fca508`
> **Codex strategic thread**: `019e5b38-cce8-71b3-ad84-07de7e99ab7a` REVISE iter-1 with `ready_for_impl=true` for docs-only consent template draft
> **Hard constraint (template)**: Gerçek kişi adı, UPN, SID, telefon, e-posta gibi kişisel veri **TEMPLATE'E YAZILMAZ**. Bu doküman form/şablondur; gerçek consent metni operator/DPO/legal review sonrası ayrı bir consent platform veya yazılı form ile imzalanır.

---

## TR — BYOD Endpoint Agent Kullanıcı Aydınlatma ve Açık Onay Metni (TASLAK)

> **Bu bir taslaktır.** Operator/DPO/Hukuk birim incelemesi yapılmadan son kullanıcıya sunulmaz. Gerçek consent metni Codex `019e5b38` strategic önerisi + KVKK Madde 5/10/11 + kurum DPO politikası ile uyumlu olarak operator tarafından sonlandırılır.

### Madde 1 — Veri Sorumlusu

**Veri Sorumlusu**: [Şirket Adı] (KVKK kapsamında veri sorumlusu sıfatıyla)
**DPO İletişim**: [DPO İletişim Bilgisi — placeholder]
**Adres**: [Şirket Adres — placeholder]
**Telefon / E-posta**: [DPO İletişim Bilgisi — placeholder]

### Madde 2 — İşlenen Veri Kategorileri

Endpoint Agent (`endpoint-agent.exe`) kişisel cihazınıza kurulduğunda aşağıdaki **kişisel veri kategorileri** işlenir:

| Veri Kategorisi | Örnek Alanlar | KVKK sınıflandırması (genel / özel nitelikli ayrımı) |
|---|---|---|
| **Cihaz tanımlayıcı** | hostname, machine_fingerprint, OS version/build, IP adresi | Genel nitelikli kişisel veri (cihaz üzerinden tanımlanabilir kişi) |
| **Kullanıcı kimliği** | UPN (User Principal Name), SID, görünen ad, son login zaman damgası | Genel nitelikli kişisel veri |
| **Yerel kullanıcı listesi** (Windows) | username, etkin/devre dışı durumu, son login | Genel nitelikli kişisel veri |
| **Kurulu yazılım envanteri** | uygulama adı, sürüm, yayıncı, kurulum tarihi | Genel veri (cihaz konfigürasyonu) |
| **Telemetri** | heartbeat zaman damgaları, agent sürümü | Genel veri (operasyonel) |
| **Audit log** | komut tipi, durum, süre, audit row hash | Genel veri (uyumluluk amaçlı) |

**Özel nitelikli kişisel veri (KVKK Madde 6/1) İŞLENMEZ**: sağlık, etnik köken, dini inanç, biyometrik, mahkumiyet bilgisi vb. agent kapsamı dışındadır. Yukarıdaki tablonun tüm satırları **genel nitelikli** kişisel/cihaz verileridir; KVKK Madde 6 özel kategori dışındadır.

### Madde 3 — Veri İşleme Amacı

Toplanan kişisel veriler aşağıdaki amaçlarla işlenir:

1. **Endpoint güvenlik telemetri** — cihaz envanteri + heartbeat + non-destructive komut log'u
2. **Audit + uyumluluk** — yasal/sözleşmesel uyumluluk gereği işlem kaydı (BE-016 hash-chain integrity)
3. **Pilot test ve acceptance evidence** — Faz 22.2.A non-domain Windows pilot acceptance kanıtı
4. **Operasyonel destek** — agent crash/tamper tespiti + cihaz reachability monitor

**Reklam, profilleme, üçüncü taraf pazarlama veya kişisel verilerin satışı amacıyla İŞLENMEZ.**

### Madde 4 — Hukuki Sebep (KVKK Madde 5)

Veri işleme hukuki sebebi:

- **KVKK Madde 5/1**: **Açık rızanız** (BYOD bağlamında, kurumsal cihaz değil kendi cihazınız için)
- **KVKK Madde 5/2(c)**: Sözleşmenin kurulması veya ifası için gerekli olması (eğer iş sözleşmesi BYOD pilot katılımı içeriyorsa)
- **KVKK Madde 5/2(f)**: İlgili kişinin temel hak ve özgürlüklerine zarar vermemek kaydıyla meşru menfaat (kurumsal güvenlik bağlamında — bu sebebe sadece açık rıza yedek olduğunda dayanılır)

Bu BYOD pilot için **açık rıza esastır**. Rıza vermediğinizde agent kurulumu yapılmaz; kurumsal alternatif olarak A1 standalone (kurumsal cihaz) opsiyonu sunulur.

### Madde 5 — Saklama Süresi

Veri kategorileri bazında saklama süreleri:

| Kategori | Saklama süresi | Anonimleştirme/Silme |
|---|---|---|
| Heartbeat | 90 gün | sonra silinir |
| Cihaz envanteri (raw) | 30 gün | sonra anonimleştirilir (hostname machine-level; UPN hash) |
| IP adresi | 30 gün raw | son oktet maskelenir (`192.168.1.***`) sonrası 90 gün; sonra silinir |
| UPN / SID | 30 gün raw | hash (`sha256:abc...`) + SID truncate (`S-1-5-21-***-***-***-NNNN`) sonrası 90 gün; sonra silinir |
| Yerel kullanıcı listesi | 30 gün | sonra silinir |
| Kurulu yazılım envanteri | 30 gün | sonra silinir |
| Audit log | 365 gün | yasal uyumluluk gereği; KVKK Madde 7 uyarınca silme talebi öncelikli |

**BE-019 (KVKK retention enforcement)** backend implementasyonu MERGED olmadan otomatik silme **enforce edilmez**. Manuel silme talepleri DPO üzerinden işlenir (Madde 8).

### Madde 6 — Veri Paylaşımı

Toplanan kişisel veriler **üçüncü taraflarla paylaşılmaz**, istisnalar:

- **Yasal zorunluluk**: mahkeme kararı, SGK, vergi, vb. kamu otoriteleri
- **Kurum içi**: SOC, IT, DPO, hukuk birimleri (need-to-know basis)
- **Bulut hizmet sağlayıcı**: backend (`endpoint-admin-service`) kurum sunucusunda barındırılır; harici bulut yok
- **Cross-AI peer review**: code review için anonimleştirilmiş audit row hash'leri (Codex API; gerçek kişisel veri yok)

### Madde 7 — Cihaz Üzerinde Agent Kaldırma (Uninstall Self-Service)

Agent'ı dilediğiniz zaman kaldırabilirsiniz. Üç yöntem:

**Yöntem 1 — Installer uninstall script (önerilen)**:
```powershell
cd "C:\Program Files\EndpointAgent"
.\uninstall.ps1 -RemoveConfig -RemoveLogs
```

**Yöntem 2 — Add/Remove Programs**:
- Windows Settings → Apps → Installed Apps → EndpointAgent → Uninstall

**Yöntem 3 — PowerShell direct (fallback)**:
```powershell
Stop-Service EndpointAgent
sc.exe delete EndpointAgent
Remove-Item -Path "C:\Program Files\EndpointAgent" -Recurse -Force
Remove-Item -Path "C:\ProgramData\EndpointAgent" -Recurse -Force
```

Kaldırma sonrası:
- Backend tarafında cihaz decommission edilir (audit row insert)
- Kişisel veriler KVKK Madde 7 + Madde 5 retention politikası uyarınca silinir/anonimleştirilir
- Kullanıcıya bilgilendirme: "Agent kaldırıldı; backend'de data [X] gün içinde silinecek"

### Madde 8 — KVKK Madde 11 İlgili Kişi Hakları

KVKK Madde 11 uyarınca DPO'ya başvurarak aşağıdaki haklarınızı kullanabilirsiniz:

a) Kişisel verilerinizin işlenip işlenmediğini öğrenme
b) İşlenmişse buna ilişkin bilgi talep etme
c) İşlenme amacını ve amacına uygun kullanılıp kullanılmadığını öğrenme
ç) Yurt içinde veya yurt dışında kişisel verilerin aktarıldığı üçüncü kişileri bilme
d) Kişisel verilerin eksik veya yanlış işlenmiş olması hâlinde bunların düzeltilmesini isteme
e) KVKK Madde 7'de öngörülen şartlar çerçevesinde kişisel verilerin silinmesini veya yok edilmesini isteme
f) (d) ve (e) bentleri uyarınca yapılan işlemlerin, kişisel verilerin aktarıldığı üçüncü kişilere bildirilmesini isteme
g) İşlenen verilerin münhasıran otomatik sistemler vasıtasıyla analiz edilmesi suretiyle kişinin kendisi aleyhine bir sonucun ortaya çıkmasına itiraz etme
ğ) Kişisel verilerin kanuna aykırı olarak işlenmesi sebebiyle zarara uğraması hâlinde zararın giderilmesini talep etme

**DPO başvuru**: [DPO İletişim — placeholder]

Yanıt süresi: 30 gün (KVKK Madde 13/2).

### Madde 9 — Açık Onay (Açık Rıza)

Aşağıdaki açıklamayı okuduğumu, anladığımı ve serbest iradem ile **açık rızamla**:

- [ ] Madde 2'deki **kişisel veri kategorilerinin** Madde 3'teki **amaçlarla** Madde 5'teki **saklama süresince** işlenmesine açık rıza veriyorum
- [ ] **Cihazımı uninstall self-service** ile dilediğim zaman geri çekebileceğimi anladım (Madde 7)
- [ ] KVKK Madde 11 ilgili kişi haklarımı DPO başvuru kanalı ile kullanabileceğimi anladım (Madde 8)
- [ ] Bu rızayı dilediğim zaman geri alabileceğimi anladım (Madde 7 uninstall self-service ile aynı zamanda rıza geri alımı sayılır)

**Consent ID** (otomatik atanır; gerçek kişi bilgisi değil): `[CONSENT-YYYY-MM-DD-NNNN]`
**Tarih**: `[YYYY-MM-DD]`
**İmza** (kullanıcı manual; bu template'e gerçek imza/kişi adı/UPN yazılmaz)

---

## EN — BYOD Endpoint Agent User Information and Explicit Consent (DRAFT)

> **This is a DRAFT.** Cannot be presented to end users without Operator/DPO/Legal review. Real consent text must be finalized by operator per Codex `019e5b38` strategic recommendation + GDPR/KVKK Article 5/10/11 + organization DPO policy.

### Article 1 — Data Controller

**Data Controller**: [Company Name] (in capacity of data controller under KVKK / GDPR)
**DPO Contact**: [DPO Contact Information — placeholder]
**Address**: [Company Address — placeholder]
**Phone / Email**: [DPO Contact — placeholder]

### Article 2 — Personal Data Categories Processed

When Endpoint Agent (`endpoint-agent.exe`) is installed on your personal device, the following **personal data categories** are processed:

| Data Category | Example Fields | KVKK Classification (general / special category distinction) |
|---|---|---|
| **Device identifier** | hostname, machine_fingerprint, OS version/build, IP address | Personal data (device-identifiable) |
| **User identity** | UPN (User Principal Name), SID, display name, last login timestamp | Personal data (general) |
| **Local user list** (Windows) | username, enabled status, last login | Personal data (general) |
| **Installed software inventory** | application name, version, publisher, install date | General data (device configuration) |
| **Telemetry** | heartbeat timestamps, agent version | General data (operational) |
| **Audit log** | command type, status, duration, audit row hash | General data (compliance) |

**Special category personal data (KVKK Article 6/1) is NOT PROCESSED**: health, ethnic origin, religious belief, biometric, criminal record etc. are outside agent scope.

### Article 3 — Purpose of Processing

Collected personal data is processed for the following purposes:

1. **Endpoint security telemetry** — device inventory + heartbeat + non-destructive command log
2. **Audit + compliance** — legal/contractual compliance audit (BE-016 hash-chain integrity)
3. **Pilot test and acceptance evidence** — Faz 22.2.A non-domain Windows pilot acceptance proof
4. **Operational support** — agent crash/tamper detection + device reachability monitor

**NOT PROCESSED for advertising, profiling, third-party marketing, or sale of personal data.**

### Article 4 — Legal Basis (KVKK Article 5 / GDPR Article 6)

Legal basis for data processing:

- **KVKK Article 5/1**: **Your explicit consent** (in BYOD context, your own personal device, not corporate device)
- **KVKK Article 5/2(c)**: Necessity for establishment or performance of contract (if employment contract includes BYOD pilot participation)
- **KVKK Article 5/2(f)**: Legitimate interest provided it does not harm fundamental rights and freedoms (corporate security context — relied upon only when explicit consent is auxiliary)

For this BYOD pilot, **explicit consent is primary**. Without your consent, agent will not be installed; corporate alternative A1 standalone (corporate-owned device) option is offered.

### Article 5 — Retention Period

Retention periods per data category:

| Category | Retention | Anonymization/Deletion |
|---|---|---|
| Heartbeat | 90 days | then deleted |
| Device inventory (raw) | 30 days | then anonymized (hostname machine-level; UPN hashed) |
| IP address | 30 days raw | last octet masked (`192.168.1.***`) for next 90 days; then deleted |
| UPN / SID | 30 days raw | hashed (`sha256:abc...`) + SID truncate (`S-1-5-21-***-***-***-NNNN`) for next 90 days; then deleted |
| Local user list | 30 days | then deleted |
| Installed software inventory | 30 days | then deleted |
| Audit log | 365 days | legal compliance; KVKK Article 7 deletion request takes priority |

**BE-019 (KVKK retention enforcement)** backend implementation is NOT MERGED; automatic deletion **not enforced** yet. Manual deletion requests processed via DPO (Article 8).

### Article 6 — Data Sharing

Collected personal data is **NOT SHARED with third parties**, exceptions:

- **Legal obligation**: court order, SGK, tax, etc. public authorities
- **Internal**: SOC, IT, DPO, legal departments (need-to-know basis)
- **Cloud service provider**: backend (`endpoint-admin-service`) hosted on corporate infrastructure; no external cloud
- **Cross-AI peer review**: anonymized audit row hashes for code review (Codex API; no actual personal data)

### Article 7 — Agent Uninstall Self-Service

You may uninstall the agent at any time. Three methods:

**Method 1 — Installer uninstall script (recommended)**:
```powershell
cd "C:\Program Files\EndpointAgent"
.\uninstall.ps1 -RemoveConfig -RemoveLogs
```

**Method 2 — Add/Remove Programs**:
- Windows Settings → Apps → Installed Apps → EndpointAgent → Uninstall

**Method 3 — PowerShell direct (fallback)**:
```powershell
Stop-Service EndpointAgent
sc.exe delete EndpointAgent
Remove-Item -Path "C:\Program Files\EndpointAgent" -Recurse -Force
Remove-Item -Path "C:\ProgramData\EndpointAgent" -Recurse -Force
```

Post-uninstall:
- Backend decommissions device (audit row inserted)
- Personal data deleted/anonymized per KVKK Article 7 + Article 5 retention policy
- User notification: "Agent uninstalled; backend data will be deleted within [X] days"

### Article 8 — KVKK Article 11 Data Subject Rights

You can exercise the following rights by contacting the DPO:

a) Learn whether your personal data is being processed
b) Request information if processed
c) Learn the purpose of processing and whether used in accordance with the purpose
d) Know the third parties in Turkey or abroad to whom personal data has been transferred
e) Request correction of incomplete or incorrectly processed personal data
f) Request deletion or destruction of personal data within the framework of conditions set forth in KVKK Article 7
g) Request notification of operations conducted pursuant to subparagraphs (d) and (e) to third parties to whom personal data has been transferred
h) Object to processing solely through automated systems resulting in unfavorable outcomes
i) Claim compensation for damage suffered due to unlawful processing of personal data

**DPO Application**: [DPO Contact — placeholder]

Response time: 30 days (KVKK Article 13/2).

### Article 8B — GDPR Article 15-22 Data Subject Rights (parallel mapping for EEA/EU users)

If you are subject to GDPR (EEA/EU residence), the following data subject rights apply in parallel to KVKK Article 11. These are listed separately because GDPR rights are not a strict subset of KVKK Article 11 and have distinct enforcement timelines and remedies.

| GDPR Article | Right | Notes vs KVKK Article 11 |
|---|---|---|
| **Article 15** | Right of access by the data subject | Aligns with KVKK 11(a)(b) |
| **Article 16** | Right to rectification | Aligns with KVKK 11(e) |
| **Article 17** | Right to erasure ("right to be forgotten") | Aligns with KVKK 11(f); GDPR adds erasure timing requirements |
| **Article 18** | Right to restriction of processing | Not explicitly mirrored in KVKK 11 (KVKK rectification + objection cover overlap) |
| **Article 19** | Notification obligation regarding rectification/erasure/restriction | Aligns with KVKK 11(g) |
| **Article 20** | Right to data portability | Not explicitly mirrored in KVKK 11 (KVKK currently lacks portability mandate) |
| **Article 21** | Right to object | Aligns with KVKK 11(h) |
| **Article 22** | Automated individual decision-making (including profiling) | Aligns with KVKK 11(h); GDPR adds explicit "not subject to" right |

**DPO Application**: [DPO Contact — placeholder]
Response time: 1 month (GDPR Article 12/3), extendable by 2 months for complex requests.

**Note**: GDPR rights apply only to EEA/EU-resident data subjects. For Turkey-resident users, KVKK Article 11 is the primary regime. Operator legal counsel determines which framework applies based on user residence + processing location.

### Article 9 — Explicit Consent

I declare that I have read, understood, and **with my explicit consent of my free will** agree to:

- [ ] processing of **personal data categories** in Article 2 for **purposes** in Article 3 during **retention periods** in Article 5
- [ ] I understand I can **uninstall self-service** my device at any time (Article 7)
- [ ] I understand I can exercise my KVKK Article 11 data subject rights through DPO application channel (Article 8)
- [ ] I understand I can withdraw this consent at any time (Article 7 uninstall self-service also counts as consent withdrawal)

**Consent ID** (auto-assigned; not actual person info): `[CONSENT-YYYY-MM-DD-NNNN]`
**Date**: `[YYYY-MM-DD]`
**Signature** (user manual; no actual signature/person name/UPN written in this template)

---

## Operator / DPO / Legal review checklist

Before presenting to end users:

- [ ] DPO approves data categories + purpose + legal basis (Article 4) per KVKK
- [ ] Legal counsel reviews KVKK Article 11 + retention periods alignment with corporate policy
- [ ] Operator confirms uninstall self-service tested per Method 1-3 (Article 7)
- [ ] IT confirms backend BE-019 KVKK retention enforcement status (active vs documented-only)
- [ ] Consent platform / form integration: digital consent platform or written form (consent ID auto-assignment)
- [ ] Localization: TR + EN paralel; başka dil gerekirse genişlet
- [ ] Final sign-off: [Operator Name / DPO Name / Legal Counsel Name + date + signature]

## Boundary

- **DRAFT only** — operator/DPO/legal review required
- **No actual person name / UPN / signature / phone / email** in this template (Codex `019e5b38` Q5 absorb)
- **BE-019 enforcement gate** — automatic deletion not active; manual deletion via DPO
- **A2 BYOD tier only** — A1 standalone / A3 Entra-joined / A4 Workplace-registered different consent requirements (legitimate interest may apply)
- **NOT prod-ready** — pilot acceptance only; production deployment requires separate consent template per corporate policy

## Tracked by

- RB-faz22-non-domain-windows-pilot.md §12 BYOD consent + privacy + KVKK + uninstall
- ADR-0012-EA "22.2 scope amendment" section
- gitops PR #1043 RB MERGED `47fca508`
- BE-019 KVKK retention enforcement (TRACKING-ROADMAP backlog)
- Codex strategic `019e5b38` Q5 BYOD consent template absorb
