# RB Faz 23 A6 — Prod SMTP Gateway Setup (Office 365 Default + Multi-Provider)

> **Trigger**: PR-X1 merged. Mail service prod-live aktivasyonu için A6 → A7 sequence.
> **Estimated**: ~30dk operator (Microsoft 365 admin) + ~30dk operator (DNS provider) + ~10dk agent (Vault seed)
> **Risk**: medium (yanlış SMTP credentials → spam folder; yanlış DKIM key → signature fail; yanlış SPF → bounce)

## Context

PR-X1 (`feat/notify-23-3-a6-prod-smtp-office365-gateway`) Session 44 user kararı:
**Office 365 SMTP gateway default + multi-provider design**. Backend Spring Boot
JavaMailSender autoconfig vendor-agnostic; STARTTLS 587 SMTP AUTH standart
kontrat. Vendor değişimi config-only (kod değiştirilmez).

PR-X1 değişiklikleri (gitops):
- Prod ESO ExternalSecret: 3 yeni key (smtp_username, smtp_password, dkim_private_key_pem)
- Prod ConfigMap: SMTP HOST=smtp.office365.com + AUTH=true + DKIM_ENABLED=true + DKIM_SELECTOR=acik2026 + DKIM_DOMAIN=acik.com
- NOTIFY_DISPATCH_ENABLED=false unchanged (separate PR for flip after credentials seeded)

## A6 Operator Action Sequence

### Step 1: Microsoft 365 admin — service account oluştur

```text
1. portal.azure.com / admin.microsoft.com → Users → Active users → Add a user
2. Username: notify-noreply@acik.com
3. Password: rastgele güçlü (kullanıcı login user değil; servis hesabı)
4. License: Microsoft 365 Business Basic (en az; SMTP relay yeterli)
5. Roles: yok (servis hesabı, admin yetki gerekmez)
```

### Step 2: Microsoft 365 admin — App Password (2FA bypass for SMTP AUTH)

Modern auth + MFA aktifse SMTP AUTH yapamaz. App Password gerek:

```text
1. portal.azure.com → Users → notify-noreply@acik.com → Authentication methods
2. Enable "App passwords" (organizational policy izin vermeli)
3. notify-noreply@acik.com login → mysignins.microsoft.com → "Create new app password"
4. App name: ACIK Notify Orchestrator
5. Copy generated password (16-char alphanumeric, ONE-SHOT — bir daha gösterilmez)
```

**Alternative**: SMTP AUTH disabled tenant'ta — security defaults disable + Conditional Access exclude (organizational policy review).

### Step 3: Vault prod seed — agent yapabilir (Pre-Production Full Authority)

```bash
ssh halil@staging-sw "
ROOT_TOKEN=\$(python3 -c 'import json; print(json.load(open(\"/home/halil/bootstrap-drill/vault-init-prod.json\"))[\"root_token\"])')
docker exec -e VAULT_TOKEN=\$ROOT_TOKEN -e VAULT_ADDR=http://127.0.0.1:8200 \
  platform-vault-prod vault kv patch kv/platform/notification-orchestrator \
    smtp_username='notify-noreply@acik.com' \
    smtp_password='<APP_PASSWORD_FROM_STEP_2>'
"
```

### Step 4: DKIM key generation + Vault seed — agent yapabilir

```bash
# Generate DKIM private key (RSA 2048, PKCS#8)
openssl genrsa -out /tmp/dkim-prod.pem 2048
openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt \
  -in /tmp/dkim-prod.pem -out /tmp/dkim-prod-pkcs8.pem

# Extract public key for DNS TXT record
openssl rsa -in /tmp/dkim-prod.pem -pubout -outform PEM | \
  sed -e '1d;$d' | tr -d '\n' > /tmp/dkim-prod-pub.txt

# Display DNS TXT record value
echo "DKIM DNS TXT record (acik2026._domainkey.acik.com):"
echo "v=DKIM1; k=rsa; p=$(cat /tmp/dkim-prod-pub.txt)"

# Vault prod seed (Pre-Production Full Authority)
ssh halil@staging-sw "
ROOT_TOKEN=\$(python3 -c 'import json; print(json.load(open(\"/home/halil/bootstrap-drill/vault-init-prod.json\"))[\"root_token\"])')
docker exec -e VAULT_TOKEN=\$ROOT_TOKEN -e VAULT_ADDR=http://127.0.0.1:8200 \
  platform-vault-prod vault kv patch kv/platform/notification-orchestrator \
    dkim_private_key_pem=\"\$(cat /tmp/dkim-prod-pkcs8.pem)\"
"

# CLEAN UP local key files (security hygiene)
shred -u /tmp/dkim-prod.pem /tmp/dkim-prod-pkcs8.pem /tmp/dkim-prod-pub.txt
```

### Step 5: DNS records — operator external (acik.com DNS provider)

Three TXT records required for full email deliverability:

```text
# DKIM (signing public key)
acik2026._domainkey.acik.com IN TXT "v=DKIM1; k=rsa; p=<from Step 4>"

# SPF (authorized senders for acik.com From: domain)
acik.com IN TXT "v=spf1 include:spf.protection.outlook.com -all"

# DMARC (authentication policy)
_dmarc.acik.com IN TXT "v=DMARC1; p=quarantine; rua=mailto:dmarc@acik.com; pct=100"
```

DNS propagation: 5-15 dakika (TTL'e bağlı). Verify:

```bash
dig +short TXT acik2026._domainkey.acik.com
dig +short TXT acik.com | grep "v=spf1"
dig +short TXT _dmarc.acik.com
```

### Step 6: ESO force-sync — agent

```bash
ssh halil@staging-sw "
kubectl --context k3d-prod -n platform-prod \
  annotate externalsecret notification-orchestrator-secrets \
  force-sync=\$(date +%s) --overwrite

sleep 8

# Verify Secret keys (was 15, now 18: +smtp_username +smtp_password +dkim_private_key_pem)
kubectl --context k3d-prod -n platform-prod get secret \
  notification-orchestrator-secrets -o jsonpath='{.data}' | \
  python3 -c 'import json,sys,base64; d=json.load(sys.stdin); print(\"keys (\"+str(len(d))+\"):\", sorted(d.keys()))'
"
```

Expected: 18 keys.

### Step 7: Pod rollout — agent

```bash
ssh halil@staging-sw "
kubectl --context k3d-prod -n platform-prod rollout restart deploy/notification-orchestrator
kubectl --context k3d-prod -n platform-prod rollout status deploy/notification-orchestrator --timeout=180s

POD=\$(kubectl --context k3d-prod -n platform-prod get pod -l app.kubernetes.io/name=notification-orchestrator -o jsonpath='{.items[0].metadata.name}')

echo '=== Pod state ==='
kubectl --context k3d-prod -n platform-prod get pod \$POD -o jsonpath='Phase: {.status.phase}, Ready: {.status.containerStatuses[0].ready}{\"\n\"}'

echo '=== Validator log ==='
kubectl --context k3d-prod -n platform-prod logs \$POD --tail=200 | grep -E 'ProductionConfigValidator|DkimSigner|SmtpAdapter'

echo '=== Env verify ==='
kubectl --context k3d-prod -n platform-prod exec \$POD -- env | grep -E '^SPRING_MAIL_HOST|^NOTIFY_ADAPTERS_SMTP_HOST|^NOTIFY_DKIM_ENABLED'
"
```

Expected:
- Pod ready=true
- Validator log: "all production guards PASSED" (9 guards now including DKIM)
- DkimSigner activated: selector=acik2026 domain=acik.com
- SmtpAdapter activated: dkimEnabled=true
- SPRING_MAIL_HOST=smtp.office365.com
- NOTIFY_DKIM_ENABLED=true

### Step 8: A7 dispatch flip — separate PR

PR creation post-Step 7 (after Vault seed + DNS verify):

```yaml
# kustomize/overlays/prod/kustomization.yaml ConfigMap patch:
- op: replace
  path: /data/NOTIFY_DISPATCH_ENABLED
  value: "true"
```

Then:
1. Apply prod overlay
2. ESO sync + pod rollout
3. Smoke send: `curl POST /api/v1/notify/intent` with valid JWT (test persona)
4. Mailpit verify: outbound mail received with DKIM-Signature header
5. Browser verify: deliverability check via mail-tester.com (≥9/10 score expected)

## Multi-Provider Switching

Backend kod değişmez. Vendor değişimi:

| Vendor | SPRING_MAIL_HOST | smtp_username | smtp_password |
|---|---|---|---|
| **Office 365** (default) | smtp.office365.com | notify-noreply@acik.com | App Password |
| SendGrid | smtp.sendgrid.net | apikey | <SENDGRID_API_KEY> |
| AWS SES | email-smtp.eu-west-1.amazonaws.com | <IAM SMTP user> | <IAM SMTP secret> |
| Postmark | smtp.postmarkapp.com | <server token> | <server token> |
| Mailgun | smtp.mailgun.org | postmaster@<domain> | <SMTP password> |
| Internal MTA | <host> | <service account> | <password> |

Vendor change PR:
```yaml
# Just two lines:
- op: replace
  path: /data/SPRING_MAIL_HOST
  value: "<new-vendor-smtp-host>"
- op: replace
  path: /data/NOTIFY_ADAPTERS_SMTP_HOST
  value: "<new-vendor-smtp-host>"
# Plus Vault prod seed: vault kv patch ... smtp_username=<new> smtp_password=<new>
```

DKIM key vendor-agnostic (private key + public DNS TXT same regardless of relay).

## Rollback

If A7 dispatch flip fails (mail bounces / SMTP AUTH error):

```bash
# Quick rollback — local hot patch
kubectl --context k3d-prod -n platform-prod \
  set env deploy/notification-orchestrator NOTIFY_DISPATCH_ENABLED=false

# Wait rollout
kubectl --context k3d-prod -n platform-prod rollout status deploy/notification-orchestrator

# Diagnose:
kubectl --context k3d-prod -n platform-prod logs deploy/notification-orchestrator --tail=100 | \
  grep -E "MailSendException|MessagingException|AuthenticationFailedException|535|503"
```

Common causes:
- 535 5.7.3 — App Password yanlış / Modern auth disabled
- 503 5.7.0 — Rate limit (Office 365 quota: 10000 mail/day per service account)
- DKIM signature fail — DNS propagation incomplete
- SPF fail — sender host not in spf.protection.outlook.com

## References

- A4 DKIM RFC 6376 PR #151 (backend MERGED)
- A6 PR-X1 (this PR — gitops infra)
- A7 follow-up PR (dispatch flip after credentials + DNS verify)
- Charter sub-faz 23.2 mail security boundary
- HARD RULE — Pre-Production Full Authority (Vault prod seed agent yetkisi)
- HARD RULE — No fake work (real Office 365 SMTP path; not stub)
