# Faz 22.2.A KVKK Data Inventory (DPO Sign-off Template)

> **Status**: DRAFT — DPO/Legal review required before sign-off / DPO/Hukuk incelemesi yapılmadan onay verilmez
> **Scope**: Faz 22.2.A non-domain Windows pilot (A1 standalone / A2 BYOD / A3 Entra-joined / A4 Workplace-registered)
> **Tracked by**: RB-faz22-non-domain-windows-pilot.md §12 + ADR-0012-EA "22.2 scope amendment"
> **Predecessor**: gitops PR #1043 RB MERGED `47fca508`, gitops PR #1041 ADR amendment MERGED `a9bc7ab6`
> **Codex strategic thread**: `019e5b38-cce8-71b3-ad84-07de7e99ab7a` REVISE iter-1 with `ready_for_impl=true` for docs-only data inventory draft + DPO sign-off form
> **Hard constraint**: Bu doküman **policy target** ve **enforcement gate** olarak iki kısma ayrılır. BE-019 (KVKK retention enforcement) backend implementasyonu MERGED olmadan otomatik enforcement iddiası kurulmaz.

---

## 1. Amaç

Faz 22.2.A non-domain Windows pilot için Endpoint Agent (`endpoint-agent.exe`) tarafından toplanan kişisel veri kategorilerinin envanteri + retention politikası + redaction kuralları + DPO sign-off formu. KVKK Madde 5/6/7/10/11/13 + GDPR Article 5/6/15-22 uyumlu.

## 2. Veri Sorumlusu + DPO

**Veri Sorumlusu**: [Şirket Adı] (KVKK 3/1-ı; GDPR Article 4(7) data controller)
**DPO**: [DPO Adı + İletişim — placeholder]
**Adres**: [Şirket Adres — placeholder]
**Telefon / E-posta**: [DPO İletişim — placeholder]
**KVKK VERBİS sicil no**: [VERBİS Sicil — placeholder]

## 3. Kişisel Veri Envanteri

### 3.1 Cihaz Tanımlayıcı Veriler

| Field | Source | Sensitivity | Personal? |
|---|---|---|---|
| `hostname` | `Win32_ComputerSystem.DNSHostName` | Low | Yes (cihaz üzerinden tanımlanabilir) |
| `machine_fingerprint` | Agent state file (HMAC seed) | Low | Yes (cihaz-bazlı pseudo-id) |
| `os_caption` | `Win32_OperatingSystem.Caption` | None | No (genel sistem bilgisi) |
| `os_version` | `Win32_OperatingSystem.Version` | None | No |
| `os_build` | `Win32_OperatingSystem.BuildNumber` | None | No |
| `architecture` | `Win32_OperatingSystem.OSArchitecture` | None | No |
| `ip_address` | `Get-NetIPConfiguration` IPv4Address | Medium | Yes (ağ-üzerinden tanımlanabilir; KVKK Madde 6) |

### 3.2 Kullanıcı Kimliği Verileri

| Field | Source | Sensitivity | Personal? |
|---|---|---|---|
| `current_user` | `$env:USERNAME` veya `Win32_LoggedOnUser` | Medium | Yes (KVKK Madde 5/1 kişisel veri) |
| `user_upn` | `dsregcmd /status` veya `whoami /upn` | High | Yes (KVKK Madde 5/1 kişisel veri) |
| `user_sid` | `Win32_UserAccount.SID` | High | Yes (KVKK Madde 5/1 kişisel veri) |
| `user_display_name` | `Get-LocalUser` veya `Win32_UserAccount.FullName` | High | Yes (KVKK Madde 5/1 kişisel veri) |
| `last_logon_timestamp` | `Win32_UserAccount.LastLogon` | Medium | Yes (KVKK Madde 5/1) |

### 3.3 Yerel Kullanıcı Listesi (Windows)

| Field | Source | Sensitivity | Personal? |
|---|---|---|---|
| `local_users[].username` | `Get-LocalUser` (AG-013 capability) | Medium | Yes (cihaz üzerindeki kullanıcı adları) |
| `local_users[].enabled` | `Get-LocalUser.Enabled` | Low | Indirect (kullanıcı durumu) |
| `local_users[].last_logon` | `Get-LocalUser.LastLogon` | Medium | Yes |

### 3.4 Kurulu Yazılım Envanteri (varsa)

| Field | Source | Sensitivity | Personal? |
|---|---|---|---|
| `installed_software[].name` | `Get-Package` veya `Win32_Product` (varsa enable edilirse) | Low | Indirect (kullanıcının yazılım profili) |
| `installed_software[].version` | aynı | Low | No |
| `installed_software[].publisher` | aynı | Low | No |
| `installed_software[].install_date` | aynı | Low | Indirect |

**Note**: Installed software collection mevcut agent capability'inde değil; bu envanter A2-A4 tier'da ileride enable edilebilir.

### 3.5 Telemetri (Operasyonel Metadata)

| Field | Source | Sensitivity | Personal? |
|---|---|---|---|
| `heartbeat_timestamp` | Agent runner internal | None | No (operasyonel) |
| `agent_version` | Agent build SHA | None | No |
| `last_seen` | Backend `endpoint_heartbeats.received_at` | None | Yes (cihaz aktivite traceable) |
| `health_state` | Agent state tracker (online/degraded/offline) | None | No |

### 3.6 Audit Log (Compliance)

| Field | Source | Sensitivity | Personal? |
|---|---|---|---|
| `command_type` | `endpoint_commands.command_type` | Low | No (komut tipi enum) |
| `command_status` | `endpoint_commands.status` | Low | No |
| `command_issuer_subject` | `endpoint_commands.issued_by_subject` (Keycloak sub UUID) | Low | Indirect (kim queue etti — operator tarafı) |
| `command_target_user` | command payload (LOCK_USER_LOGIN için target — pilot scope dışı) | High | Yes (eğer destructive command real device'de queue edilse — YASAK) |
| `audit_row_hash` | `endpoint_audit_events.event_hash` (V4 hash-chain) | None | No (integrity hash) |
| `audit_row_prev_hash` | `endpoint_audit_events.prev_event_hash` | None | No |

### 3.7 Uzaktan Erişim Oturum Verileri (Faz 22.6 — YENİ, DPO-confirm)

> **Faz 22.6 Remote Access Bridge** kapsamında eklenmiştir ([ADR-0033](adr/0033-faz-22-6-remote-access-bridge-broker.md), [#1388 acceptance package](faz-22-6-1388-acceptance-package.md)). **Yüksek hassasiyet**: oturum kaydı destek alan kullanıcının ekranını/terminalini içerebilir → **olası üçüncü-taraf PII**. **DPIA + VERBİS gözden geçirmesi gerekir.** Bu kategoriler **runtime'da #1388 acceptance + DPO onayı olmadan toplanmaz.**

| Field | Source | Sensitivity | Personal? |
|---|---|---|---|
| `session_id` / `device_id` / `tenant_id` | `remote_sessions` | Low | Indirect |
| `actor` / `approver` | session grant (operator tarafı) | Low | Indirect (operator kimliği) |
| `capability_tier` / `reason` / `scope` | `remote_session_audit` | Low | No (enum/metadata) |
| **Session transcript** (4-E / 4-F-PTY terminal I/O) | broker recording (immutable transcript) | **High** | **Yes** (komut/çıktı kullanıcı verisi içerebilir) |
| **Session video recording** (4-F-REMOTE-CONTROL / RDP) | broker recording (encrypted blob) | **Critical** | **Yes** (ekran içeriği = olası 3rd-party PII) |
| `audit_row_hash` / `prev_hash` | `remote_session_audit` (BE-016 chain) | None | No |

**Erişim:** least-priv viewer + per-view audit; ilgili kişi kendi kaydına erişim **DPO/redaction-mediated** (raw self-service değil); 3rd-party PII için redaction-on-playback (ISO A.5.34).

## 4. Retention Politikası

### 4.1 Policy Target (Documented)

> **Codex `019e5b38` Q6 absorb**: Bu retention table **policy target**; BE-019 backend MERGED olmadan **enforce** edilmez.

| Kategori | Raw Retention | Anonymization/Pseudonymization | Total Retention |
|---|---|---|---|
| Heartbeat | 90 gün | timestamp rounded to day post-30d | 90 gün, sonra silinir |
| Cihaz envanteri (raw) | 30 gün | hostname machine-level, UPN/SID hash | 90 gün hashed, sonra silinir |
| IP adresi | 30 gün raw | last octet masked (`192.168.1.***`) | 90 gün masked, sonra silinir |
| UPN / SID | 30 gün raw | UPN `sha256:abc...`, SID `S-1-5-21-***-***-***-NNNN` | 90 gün hashed, sonra silinir |
| Local user list | 30 gün | username retained machine-level | 30 gün, sonra silinir |
| Installed software | 30 gün | full retained (machine config) | 30 gün, sonra silinir |
| Audit log (yapı bütünlüğü) | 365 gün | hash-chain preserved (BE-016) | 365 gün, KVKK Madde 7 silme talebi öncelikli |
| Audit log (kişi-tanımlayıcı içerik) | aynı 365 gün | UPN/SID hashed; target_user hashed | aynı |
| **Session transcript** (4-E/4-F-PTY) *(Faz 22.6, DPO-confirm)* | 90 gün | access-audited | 90 gün, sonra silinir |
| **Session video recording** (4-F-RDP) *(Faz 22.6, DPO-confirm)* | 90 gün raw | **crypto-erase** (key destruction) | 90 gün, sonra crypto-erase; DPIA-bound |

### 4.2 Enforcement Gate (BE-019 Backend)

| Mekanizma | Status (2026-05-24) | Enforcement Level |
|---|---|---|
| Backend automatic deletion (cron) | ❌ NOT MERGED (BE-019 TRACKING-ROADMAP backlog TODO) | **Policy documented only** |
| Backend anonymization (hash + truncate) | ❌ NOT MERGED | **Policy documented only** |
| Backend audit row immutability (BE-016) | ✅ MERGED (V4 hash-chain LIVE) | **Active** |
| Manual deletion via DPO request | ✅ Active (DPO başvuru → DBA query) | **Active manual process** |
| Manual anonymization | ✅ Active (DPO başvuru → DBA query) | **Active manual process** |

**BE-019 MERGED öncesi**: KVKK Madde 7 silme talebi DPO manual işlem (DBA query); otomatik retention enforce **edilmez**.

## 5. Redaction Policy (Sanitized Evidence Output)

### 5.1 Allowed (full-text)

- `hostname` (machine-level, not personal directly)
- `os_caption`, `os_version`, `os_build`, `architecture`
- `domain` (workgroup name, not user)
- `agent_version`, `health_state`
- Timestamp fields (rounded to day post-30d for personal correlation)

### 5.2 Hashed / Truncated

- `user_upn` → `sha256:abc123...` (last-4 visible: `sha256:abc123...XYZ4`)
- `user_sid` → `S-1-5-21-***-***-***-NNNN` (last-4 RID visible)
- `user_display_name` → first-initial only (`J.D.`)
- `tenant_id` (AAD/Entra) → `sha256:def456...` veya last-4 (`***-***-XYZ8`)
- `device_id` (backend UUID) → first-8 + last-4 (`d0efb00a...XYZ8`)

### 5.3 Masked (partial display)

- `ip_address` → last octet masked (`192.168.1.***`) post-30d
- `mac_address` → middle 4 chars hidden (`00:11:**:**:**:55`) if collected
- `last_logon_timestamp` → rounded to day post-30d

### 5.4 Never logged (NEVER write to evidence / log / artifact)

- ❌ Plaintext password / token / JWT / Bearer / session cookie
- ❌ Enrollment token (single-use; agent state file encrypted, not logged)
- ❌ Agent device credential (HMAC secret; encrypted at rest per AG-019)
- ❌ Domain admin credential (operator interactive `Get-Credential` only; never `--password` flag)
- ❌ Personal email content / file content / clipboard content
- ❌ Browser history / bookmarks / saved passwords
- ❌ Cryptocurrency wallet content / SSH keys / GPG keys / signing certificates

### 5.5 Automated redaction enforcement

Mevcut redaction enforcement:
- `scripts/test/parallels-windows11-ci.sh` + `parallels-acik-local-precheck.sh` stream `redact` filter (Bearer/Authorization/password/token/secret/JWT pattern sed regex)
- Post-write secret scan (`grep -rEi 'eyJ...|Bearer ...|password.*"[^"]+"'`) fail-closed
- BE-019 backend redaction enforcement: TODO (manual policy enforcement via DPO query)

## 6. Veri Paylaşımı + Aktarım

### 6.1 Üçüncü Taraf Paylaşımı

**NONE by default** (KVKK Madde 8). İstisnalar:

- **Yasal zorunluluk**: mahkeme kararı, SGK, vergi, vb. — DPO + legal counsel approval required
- **Kurum içi need-to-know**: SOC, IT, DPO, hukuk — role-based access control
- **Cloud service provider**: backend `endpoint-admin-service` corporate infrastructure (`testai.acik.com` test cluster, `ai.acik.com` prod cluster — both corporate-hosted); harici bulut yok
- **Cross-AI peer review**: Codex API (OpenAI) için sadece **anonymized hash** + **structural metadata** (audit row hash, command type enum) — gerçek kişisel veri (UPN/SID/IP) Codex API'ye gönderilmez

### 6.2 Yurt Dışına Aktarım (KVKK Madde 9)

- **Hosting**: corporate infrastructure, yurt içi (TR) datacenter veya operator karar
- **Cross-AI peer review**: Codex API endpoint OpenAI (USA) — sadece anonymized metadata
- **GitHub repo**: code + docs + audit row hash (NO personal data) — repo public-or-private kurum kararı
- **Yurt dışına aktarım için KVKK Madde 9 onay**: gerekli ise DPO + Kişisel Verileri Koruma Kurulu izni

## 7. KVKK Madde 11 İlgili Kişi Hakları (Implementation)

| Right | Implementation | Response Time |
|---|---|---|
| (a) İşlenip işlenmediğini öğrenme | DPO query → cihaz/user UPN ile DB lookup | 30 gün |
| (b) İşlenmişse bilgi talep etme | DPO query → kategori + amaç + sebep raporu | 30 gün |
| (c) Amacı ve uygunluğu öğrenme | Bu doküman + RB-faz22-non-domain-windows-pilot.md §12 | 30 gün |
| (ç) Üçüncü kişileri bilme | Madde 6 + paylaşım kayıt | 30 gün |
| (d) Düzeltme | DPO query → DBA UPDATE (audit row insert) | 30 gün |
| (e) Silme | DPO query → DBA DELETE veya anonymize (BE-019 MERGED öncesi manual) | 30 gün |
| (f) Üçüncü kişilere bildirim | Madde 6 paylaşım takip kayıtları | 30 gün |
| (g) Otomatik sistem itirazı | DPO query → command queue / dispatch logic değerlendirme | 30 gün |
| (ğ) Zarar tazmini | Hukuk birim + sigorta + KVKK kurul başvuru | 30 gün |

## 8. DPO Sign-off Form (Template)

> **Bu form taslaktır**; gerçek imza/kişi bilgisi repo'ya girmemeli. DPO sign-off ayrı bir governance dokümanı veya digital signature platform üzerinden alınır.

### 8.1 Pre-Sign-off Checklist (Operator + DPO Review)

- [ ] Veri envanteri (§3) kurum mevcut KVKK politikasıyla uyumlu
- [ ] Retention politikası (§4) kurum mevcut data retention politikasıyla uyumlu
- [ ] Redaction kuralları (§5) kurum security/privacy standartlarıyla uyumlu
- [ ] Veri paylaşımı (§6) kurum data sharing policy ile uyumlu
- [ ] KVKK Madde 11 hakları (§7) implementation süre + kanal ile uyumlu
- [ ] BE-019 backend enforcement gap explicit acknowledged (manual DPO process)
- [ ] BYOD consent template (`22-2-byod-consent-template.md`) ile uyumlu
- [ ] Cross-AI peer review (Codex API) anonymization sınırı kabul

### 8.2 DPO Sign-off

| Field | Value |
|---|---|
| DPO Adı | `[DPO Adı — placeholder]` |
| Ünvan | `[DPO Title — placeholder]` |
| Tarih | `[YYYY-MM-DD]` |
| Sign-off Status | `[ ] Approved` / `[ ] Approved with conditions` / `[ ] Rejected` |
| Conditions (varsa) | `[Liste — placeholder]` |
| Re-review Tarihi | `[YYYY-MM-DD + 12 ay]` (yıllık review) |

### 8.3 Legal Counsel Sign-off (varsa)

| Field | Value |
|---|---|
| Legal Counsel Adı | `[Placeholder]` |
| Firma | `[Placeholder]` |
| Tarih | `[YYYY-MM-DD]` |
| Sign-off Status | `[ ] Approved` / `[ ] Rejected` |
| Notes | `[Placeholder]` |

## 9. Boundary (HARD)

- **DRAFT only** — operator/DPO/legal review required before active enforcement
- **No actual person identifiers** in this template (DPO name, UPN, sign-off date placeholder only)
- **BE-019 enforcement gap** — automatic retention/anonymization NOT MERGED; manual DPO process active
- **A2 BYOD scope** primary use case; A1 standalone (kurumsal cihaz) meşru menfaat zemini DPO kararına bağlı; A3/A4 Entra/Workplace ayrı consent flow
- **Cross-AI Codex API** sadece anonymized metadata (hash) gönderilir; gerçek kişisel veri (UPN/SID/IP plaintext) yasak
- **NOT prod-ready** — pilot acceptance only; production deployment ayrı KVKK acceptance gate

## 10. Tracked by

- RB-faz22-non-domain-windows-pilot.md §12 BYOD consent + privacy + KVKK + uninstall
- ADR-0012-EA "22.2 scope amendment" section
- gitops PR #1043 RB MERGED `47fca508`
- 22-2-byod-consent-template.md (BYOD consent partner doc)
- BE-019 KVKK retention enforcement (TRACKING-ROADMAP backlog TODO)
- BE-016 audit integrity hash-chain (V4 LIVE; backend bütünlük desteği)
- Codex strategic `019e5b38` Q6 KVKK data inventory absorb
