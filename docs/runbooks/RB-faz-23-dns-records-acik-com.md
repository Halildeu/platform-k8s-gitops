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

```text
Hostname:  acik.com (root, @ symbol or empty)
Type:      TXT
Value:     v=spf1 include:spf.protection.outlook.com -all
TTL:       3600 (1 hour)
```

Anlamı: `acik.com` adına mail gönderebilen yetkili sunucular = Office 365
(`spf.protection.outlook.com` Microsoft 365 IP range'ini içerir). `-all` =
listede olmayan diğer tüm IP'lerden gelen mail SPF fail.

### 2. DMARC (Domain-based Message Authentication, Reporting & Conformance) — MANDATORY

```text
Hostname:  _dmarc.acik.com
Type:      TXT
Value:     v=DMARC1; p=quarantine; rua=mailto:dmarc@acik.com; pct=100; aspf=r; adkim=r
TTL:       3600
```

Anlamı:
- `p=quarantine` — SPF/DKIM fail mesajları spam folder'a (start with quarantine,
  geçişte `p=reject` ile sertleştir 30 gün sonra)
- `rua=mailto:dmarc@acik.com` — günlük DMARC raporu mailbox (operator inbox)
- `pct=100` — politika %100 mail'e uygula
- `aspf=r` (relaxed SPF alignment), `adkim=r` (relaxed DKIM alignment)

### 3. DKIM (DomainKeys Identified Mail) — DEFERRED

DKIM TXT record A5 PR-B + RAID I6 unblock + Vault DKIM key gen sonrası eklenecek:

```text
Hostname:  acik2026._domainkey.acik.com
Type:      TXT
Value:     v=DKIM1; k=rsa; p=<base64-public-key-from-vault-dkim-key-gen>
TTL:       3600
```

Public key DKIM live activation runbook'tan: `RB-faz-23-A6-prod-smtp-gateway-office365.md` Step 4.

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
