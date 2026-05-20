# RB Faz 23 — DNS Records Setup (acik.com domain)

> **Trigger**: A6 + A7 merged + Vault prod seeded. Mail dispatch live but unsigned.
> Mail-tester score ~6-7/10. Score ≥9/10 için SPF + DMARC + DKIM TXT records gerek.
> **Operator**: kullanıcı (acik.com domain DNS provider erişimi)
> **Estimated**: ~10dk (DNS provider panel) + 5-15 dk DNS propagation

## Context

Office 365 SMTP gateway active (Session 44 mail service kapanış). Mail dispatched
from `ai@acik.com` via `smtp.office365.com:587 STARTTLS`. External recipient
mailbox'lar mail almaya başladı ama:

- ⚠️ SPF policy missing → Authentication-Results "spf=none" → spam folder risk
- ⚠️ DMARC policy missing → reputation low
- ⏸️ DKIM signature missing → DKIM=none (post A5 PR-B + RAID I6 unblock activation)

DNS records eklendikten sonra mail-tester.com score ≥9/10 (DKIM eklendiğinde
≥10/10).

## Required DNS TXT records

DNS provider (acik.com domain registrar) panelinde 3 TXT record:

### 1. SPF (Sender Policy Framework) — MANDATORY

> ⚠️ **Pre-flight inventory zorunlu** (Codex `019e1433` P1 absorb): SPF TXT
> RFC 7208 § 3.2 = bir domain için **tek bir** `v=spf1` TXT olabilir. İkinci
> SPF eklenirse `PermError`. Önce mevcut inventory:
>
> ```bash
> dig +short TXT acik.com | grep "v=spf1"
> ```
>
> Çıktı boşsa: yeni record ekle (aşağıdaki value).
> Çıktı dolu ise: mevcut record'u **edit** + Office 365 include'ı **mevcut
> kayıt içine** birleştir, yeni TXT **ekleme**.

```text
Hostname:  acik.com (root, @ symbol or empty)
Type:      TXT
Value:     v=spf1 include:spf.protection.outlook.com -all
TTL:       3600 (1 hour)
```

Anlamı: `acik.com` adına mail gönderebilen yetkili sunucular = Office 365
(`spf.protection.outlook.com` Microsoft 365 IP range'ini içerir). `-all` =
listede olmayan diğer tüm IP'lerden gelen mail SPF fail.

**Existing SPF varsa merge** (örnek):
- Mevcut: `v=spf1 include:_spf.google.com -all`
- Eklenecek: Office 365
- Sonuç (tek TXT içinde): `v=spf1 include:_spf.google.com include:spf.protection.outlook.com -all`

### 2. DMARC (Domain-based Message Authentication, Reporting & Conformance) — MANDATORY

> ⚠️ **Sender inventory önce** (Codex `019e1433` P1 absorb): Eğer acik.com'dan
> sadece Office 365 gönderiyorsa `p=quarantine; pct=100` baştan güvenli.
> Eğer eski sender'lar (eski MTA, marketing platform, CI mailer, vb.) varsa
> ve hepsinin SPF/DKIM align durumu net değilse, **önce 30 gün `p=none;
> pct=100`** ile observation mode (rua raporları topla), sonra `p=quarantine;
> pct=25` → `pct=50` → `pct=100`, en sonunda `p=reject`. Aceleci policy
> başlatma → meşru mail'lerin spam folder'a düşmesi.

**Observation mode (Phase 1, eğer multi-sender inventory belirsizse)**:
```text
Hostname:  _dmarc.acik.com
Type:      TXT
Value:     v=DMARC1; p=none; rua=mailto:dmarc@acik.com; pct=100; aspf=r; adkim=r
TTL:       3600
```

**Quarantine mode (Phase 2 — only-Office-365 senders veya 30 gün observation sonrası)**:
```text
Hostname:  _dmarc.acik.com
Type:      TXT
Value:     v=DMARC1; p=quarantine; rua=mailto:dmarc@acik.com; pct=100; aspf=r; adkim=r
TTL:       3600
```

**Reject mode (Phase 3 — full DKIM activation sonrası 30 gün quarantine clean)**:
```text
Value:     v=DMARC1; p=reject; rua=mailto:dmarc@acik.com; pct=100; aspf=r; adkim=r
```

Anlamı:
- `p=none` — sadece observation (rua reports yine gelir, mail policy uygulanmaz)
- `p=quarantine` — SPF/DKIM fail mesajları spam folder'a
- `p=reject` — SPF/DKIM fail mesajları reject (en sıkı, prod final state)
- `rua=mailto:dmarc@acik.com` — günlük DMARC raporu mailbox (operator inbox)
- `pct=100` — politika %100 mail'e uygula
- `aspf=r` (relaxed SPF alignment), `adkim=r` (relaxed DKIM alignment)

### 3. DKIM (DomainKeys Identified Mail) — DEFERRED + İki yol

> ⚠️ **İki ayrı DKIM yolu** (Codex `019e1433` P1 absorb): Office 365 native
> DKIM (CNAME → M365 yönetir keys) veya app-side DkimSigner (TXT, A4 path).
> Aynı domain'de **ikisi aynı anda etkin olmaz** (selector çakışması). Hangi
> yol kullanılacak operator karar:

#### Yol A: Office 365 Native DKIM (RECOMMENDED for production)

M365 admin center → Email authentication settings → DKIM → "Enable" acik.com.
M365 selector1 + selector2 CNAME değerleri verir; DNS provider'a ekle:

```text
Hostname:  selector1._domainkey.acik.com
Type:      CNAME
Value:     selector1-acik-com._domainkey.<TENANT>.onmicrosoft.com
TTL:       3600

Hostname:  selector2._domainkey.acik.com
Type:      CNAME
Value:     selector2-acik-com._domainkey.<TENANT>.onmicrosoft.com
TTL:       3600
```

Avantaj: M365 key rotation otomatik (selector1 ↔ selector2 swap). App-side
DkimSigner gerek yok. SmtpAdapter outbound flow Microsoft sign yapar.

#### Yol B: App-side DkimSigner (A4 path, post A5 PR-B + RAID I6 unblock)

A5 PR-B reopen + DKIM live activation runbook (`RB-faz-23-A6-prod-smtp-gateway-office365.md` Step 4) tamamlandıktan sonra:

```text
Hostname:  acik2026._domainkey.acik.com
Type:      TXT
Value:     v=DKIM1; k=rsa; p=<base64-public-key-from-vault-dkim-key-gen>
TTL:       3600
```

Public key kaynak: `openssl rsa -in dkim-prod.pem -pubout -outform PEM | sed -e '1d;$d' | tr -d '\n'`

Avantaj: SmtpAdapter app-side DkimSigner (PR #151) outbound mail signing. Graph adapter path'inde DKIM zaten Microsoft tarafında.

#### Karar matrisi

| Mail path | DKIM kaynağı | Önerilen yol |
|---|---|---|
| SmtpAdapter (port 587) Office 365 | M365 native imzalar | Yol A (CNAME) |
| GraphMailAdapter (port 443) Graph API | Microsoft tarafında imzalar | Yol A (CNAME) |
| Future SendGrid / AWS SES / custom SMTP relay | App-side DkimSigner zorunlu | Yol B (TXT) |

**Current state (Session 44 sonu)**: Mail path Office 365 (A6 SmtpAdapter +
A8 GraphMailAdapter). DKIM önerilen = **Yol A native CNAME** — A5 PR-B
reopen blokeri kalkmasa bile çalışır (app-side signer gerek yok). Yol B
multi-provider opsiyonu için tutulur.

## DNS Provider Panel Steps

Generic adımlar (provider-specific UI değişebilir):

1. DNS provider panel login (acik.com kayıt firmasının panel — Cloudflare, GoDaddy, 1&1, vs.)
2. acik.com domain → DNS Settings / Manage DNS / DNS Records
3. "Add Record" → Type: TXT
4. Hostname/Name field:
   - SPF: `@` veya boş veya `acik.com` (root)
   - DMARC: `_dmarc` (provider otomatik `.acik.com` ekler)
   - DKIM: `acik2026._domainkey` (provider otomatik `.acik.com` ekler)
5. Value/Content field: yukarıdaki value string'leri (kopyala-yapıştır)
6. TTL: 3600 (1 hour) veya provider default
7. Save / Add Record
8. Repeat for SPF + DMARC

## Verify (5-15 dk DNS propagation sonrası)

```bash
# SPF verify
dig +short TXT acik.com | grep "v=spf1"
# Expected: "v=spf1 include:spf.protection.outlook.com -all"

# DMARC verify
dig +short TXT _dmarc.acik.com
# Expected: "v=DMARC1; p=quarantine; rua=mailto:dmarc@acik.com; pct=100; aspf=r; adkim=r"

# DKIM verify (post A5 PR-B activation)
dig +short TXT acik2026._domainkey.acik.com
# Expected: "v=DKIM1; k=rsa; p=<base64-key>"
```

Online verify tools:
- https://www.mail-tester.com/ — overall deliverability score
- https://mxtoolbox.com/spf.aspx — SPF parser
- https://mxtoolbox.com/dmarc.aspx — DMARC parser
- https://dmarcian.com/dmarc-inspector/ — DMARC alignment check
- https://www.kitterman.com/dkim/dkim_check.html — DKIM verifier

## Smoke send test

DNS propagation sonrası:

1. Production'dan test mail gönder (DB direct INSERT veya REST API)
2. External recipient mailbox (Gmail/Outlook external/personal):
   - Open mail → "Show Original" / "View Headers"
   - `Authentication-Results` line:
     ```
     Authentication-Results: mx.google.com;
       spf=pass (sender IP: 40.92.X.X) smtp.mailfrom=ai@acik.com;
       dmarc=pass (policy=quarantine) header.from=acik.com;
       dkim=none (post-DKIM activation: dkim=pass)
     ```
3. mail-tester.com:
   - Send sample mail to mail-tester address
   - Score:
     - Pre-DKIM: 6-7/10 (SPF + DMARC pass; DKIM missing)
     - Post-DKIM: ≥9/10 (full pass)

## DMARC report monitoring

Post-deploy `dmarc@acik.com` mailbox'a günlük XML reports gelmeye başlar.
Microsoft 365, Google, Yahoo gibi büyük receiver'lar gönderir.

Sample DMARC report parser:
- https://dmarcian.com/ free tier (small sender quota)
- self-hosted: https://github.com/techsneeze/dmarcts-report-parser

İlk hafta `p=quarantine` ile gözle, sonra:
- Tüm mail SPF/DKIM pass → `p=reject` ile sertleştir
- SPF/DKIM fail mesajları → debug + alignment fix

## Post-DNS records mail-tester score path

| State | Score | Reason |
|---|---|---|
| Pre-DNS records (now) | ~5/10 | SPF/DMARC missing, DKIM missing |
| Post SPF + DMARC | ~7-8/10 | SPF + DMARC pass, DKIM=none |
| Post DKIM activation (A5 PR-B + RAID I6) | ≥9/10 | Full Authentication-Results pass |
| Plus DMARC `p=reject` | 10/10 | Strict policy |

## References

- A4 backend PR #151 MERGED (DKIM RFC 6376 source-ready)
- A6 gitops PR #506 MERGED (Office 365 SMTP infra)
- A7 gitops PR #508 MERGED (dispatch flip)
- DKIM live activation = post A5 PR-B + RAID I6 unblock
- HARD RULE — Pre-Production Full Authority (DNS records operatör external — agent yapamaz)
