# RB Graph Mail Agent Read — ai@acik.com Inbox Read Scope (Application Mail.Read)

> **Status**: SOURCE DRAFT (operator activation pending — see §3 prerequisites)
> **Scope**: Agent/ops Graph API read access to `ai@acik.com` mailbox (Application Mail.Read, app-only token)
> **NOT backend adapter activation**: This runbook does **not** activate `notify.adapters.graph.enabled=true`; backend GraphMailAdapter remains DEFERRED per [ADR-0024 D1-D6](../adr/0024-graph-mail-adapter-defer.md). Separate concern from send-path.
> **ADR ref**: [ADR-0024 §D7](../adr/0024-graph-mail-adapter-defer.md) — agent/ops inbox read scope addition (2026-05-28 decision date)
> **Codex thread**: `019ebac1` plan-time PARTIAL absorb (4 fix: Mail.Read scope, AAP app-wide+mail-enabled security group, token TTL 1h no cache default, ADR D7 addendum)
> **Helper script**: `scripts/ops/graph-mail-list.sh`

---

## 1. Bağlam

Kullanıcı 2026-05-28: "Doğrudan yetki vereyim, gerektiğinde gelen mailleri görmek bu sohbetten sana sormak istiyorum."

Mevcut mail durumu:
- **Outbound**: Alertmanager / notification-orchestrator → SMTP `ai@acik.com` → O365 relay → alıcı (LIVE; R9 BL-008 Yol B 2026-05-28)
- **Inbound**: `ai@acik.com` mailbox'a gelen mail (notify-ops yanıtları, NDR, abuse, vb.) → backend service YOK

Bu runbook **agent-side ops inbox read** sürface'ini ekler — Microsoft Graph Application Mail.Read scope ile bu sohbetten direkt `/users/ai@acik.com/messages` çağrısı. Backend GraphMailAdapter (send-path) ayrı kapı; aktive edilmez.

## 2. Boundary

Bu runbook **sadece** şu erişimi etkinleştirir:
- Application Mail.Read permission (Microsoft Graph)
- Token client_credentials grant (app-only — kullanıcı oturumu yok)
- Read-only Graph REST endpoint'ler: `/users/ai@acik.com/messages*`, `/users/ai@acik.com/mailFolders/*`
- ApplicationAccessPolicy ile `ai@acik.com` mailbox'ına SINIRLI (Exchange Online policy gate)
- Helper script `scripts/ops/graph-mail-list.sh` sanitized JSON output

Bu runbook **etkinleştirmez**:
- Mail write/delete/move (sadece read)
- Diğer mailbox'lara erişim (AAP gate)
- Backend GraphMailAdapter aktivasyonu (send-path defer korunur)
- Per-user delegated permission (sadece application/app-only)
- IMAP/POP3 alternatif client
- Mailbox content persistence/indexing (sadece anlık list)

## 3. Operator Prerequisites (one-time, ~5 dakika)

### 3.1 Entra App Permission

```
Azure portal → Entra ID → App registrations → acik-mail-graph-api
  → API permissions → Add permission → Microsoft Graph
  → Application permissions → Mail.Read → Add
```

### 3.2 Tenant Admin Consent

```
Same page (acik-mail-graph-api → API permissions):
  → "Grant admin consent for acik" button click
  → Confirm
  → Verify status column shows "Granted for acik" with green check
```

### 3.3 Exchange Online ApplicationAccessPolicy

```powershell
# Connect to Exchange Online (PowerShell):
Connect-ExchangeOnline

$AppId = "<acik-mail-graph-api client_id>"  # Vault kv/platform/graph graph_client_id

# Check existing policy
Get-ApplicationAccessPolicy | Where-Object { $_.AppId -eq $AppId }

# Test before policy create
Test-ApplicationAccessPolicy -Identity "ai@acik.com" -AppId $AppId
Test-ApplicationAccessPolicy -Identity "halil@acik.com" -AppId $AppId
# Initial expected (no policy): both Granted (default app-wide)
```

If **no existing policy** (snapshot current-state suggests not present):

```powershell
# Create mail-enabled security group
New-DistributionGroup -Name "Mail-Graph-Allowed-Mailboxes" `
  -Type "Security" `
  -PrimarySmtpAddress "mail-graph-allowed@acik.com"

# Add ai@acik.com to group
Add-DistributionGroupMember -Identity "Mail-Graph-Allowed-Mailboxes" `
  -Member "ai@acik.com"

# Create RestrictAccess policy (app-wide; affects Mail.Send + Mail.Read both)
New-ApplicationAccessPolicy `
  -AppId $AppId `
  -PolicyScopeGroupId "Mail-Graph-Allowed-Mailboxes" `
  -AccessRight RestrictAccess `
  -Description "Restrict acik-mail-graph-api mailbox access to ai@acik.com only (Mail.Send + Mail.Read)"
```

If **existing policy** (from Mail.Send setup):

```powershell
# Verify policy already restricts to ai@acik.com only
Test-ApplicationAccessPolicy -Identity "ai@acik.com" -AppId $AppId
# Expected: AccessCheckResult=Granted

Test-ApplicationAccessPolicy -Identity "halil@acik.com" -AppId $AppId
# Expected: AccessCheckResult=Denied
```

If existing policy doesn't include `ai@acik.com` in group, add it:

```powershell
Add-DistributionGroupMember -Identity "<existing-policy-group-name>" `
  -Member "ai@acik.com"
```

### 3.4 Propagation

- Permission grant: ~5 min Microsoft Graph cache
- ApplicationAccessPolicy: ~30-60 min Exchange policy propagation
- Test smoke after propagation window before declaring LIVE

## 4. Activation Smoke (agent-driven, post-operator)

### 4.1 Dedicated Vault AppRole Provision / Rotation

```bash
./scripts/ops/provision-graph-mail-vault-approle.sh
```

Beklenen sanitized çıktı:

```json
{
  "status": "provisioned_and_verified",
  "role": "graph-mail-ops",
  "policy": "graph-mail-ops-ro",
  "token_ttl_seconds": 900,
  "token_num_uses": 3,
  "default_policy": false,
  "allowed_path": "kv/data/platform/graph",
  "denied_other_path": true,
  "denied_list": true,
  "bootstrap_files": "400:root:root"
}
```

Provisioner root token'ı yalnız explicit bootstrap/rotation işlemi içinde okur; ham
değeri argv, stdout veya evidence'e yazmaz. Yeni secret-id, exact-path pozitif test
ve iki negatif authorization testi geçmeden kalıcı dosyalara alınmaz. Başarılı
doğrulamadan sonra eski secret-id accessor'ları imha edilir.

### 4.2 AppRole Contract Verify

```bash
ssh aiadmin@aiserver '
sudo -n stat -c "%a:%U:%G %n" \
  /srv/platform/secrets/graph-mail-vault/role-id \
  /srv/platform/secrets/graph-mail-vault/secret-id
'
# Expected: both files 400:root:root

python3 -m pytest -q tests/operations/test_graph_mail_vault_approle_contract.py
```

Helper sözleşmesi fail-closed'dur:

- Sadece `graph-mail-ops-ro` policy kabul edilir; `default` dahil ek policy reddedilir.
- Token TTL `1..1800` saniye dışında ise Graph credential okunmaz.
- KV yolu sabit `kv/data/platform/graph`; CLI ile başka Vault yolu seçilemez.
- Her çağrı sonunda `auth/token/revoke-self` çalışır.
- AppRole login veya bootstrap dosyası yoksa root-token fallback yapılmaz.

### 4.3 Graph List Smoke

```bash
# Use helper script (already includes Vault + token + Graph in one SSH session)
./scripts/ops/graph-mail-list.sh --top 5
# Expected: JSON array of 5 most recent messages with subject/from/received/has_attachments
```

### 4.4 ApplicationAccessPolicy Enforcement Test

```bash
# Try a mailbox that should be DENIED (e.g., halil@acik.com)
./scripts/ops/graph-mail-list.sh --mailbox halil@acik.com
# Expected: HTTP 403 ErrorAccessDenied or similar "ApplicationAccessPolicy denies access"
# NOT: empty array (which would indicate policy not applied)
```

## 5. Agent Usage Patterns (post-activation)

### 5.1 Manual list (from chat)

User: "ai@acik.com son 5 mail nedir?"
Agent: `./scripts/ops/graph-mail-list.sh --top 5` → sanitized JSON çıktı → user'a özet

### 5.2 Filtered list (subject/from search)

User: "Alert email var mı?"
Agent: `./scripts/ops/graph-mail-list.sh --search "alert" --top 10`

User: "Bounce var mı geçen 24 saatte?"
Agent: `./scripts/ops/graph-mail-list.sh --filter "receivedDateTime gt 2026-05-27T00:00:00Z and contains(subject,'bounce')"`

### 5.3 Body include (full message preview)

User: "<message id> içeriği ne?"
Agent: `./scripts/ops/graph-mail-list.sh --top 1 --include-body --filter "id eq '<message-id>'"`

(NOT: agent inbox monitor cron; user-driven only — bu runbook scope.)

## 6. Security Boundary

### 6.1 Credential

- `graph_client_secret` SADECE aiserver production Vault `kv/platform/graph` yolunda
- Helper'lar root token okumaz; root-only `0400` AppRole bootstrap dosyalarıyla login olur
- Vault policy exact-path read + self-revoke ile sınırlıdır; wildcard/list/default policy yoktur
- Vault token TTL 15 dakika, max TTL 30 dakika, use limit 3; her helper çağrısı sonunda revoke edilir
- Graph access-token cache YOK (Graph default ~1h TTL; her çağrı yeni token)
- Secret ve token değerleri stdout/evidence'e veya kalıcı helper cache'ine yazılmaz
- Host `aiadmin` hesabının mevcut geniş `sudo` yetkisi ayrı R17 host-admin riskidir;
  bu AppRole değişikliği o hesabı root'tan izole ettiğini iddia etmez

### 6.2 ApplicationAccessPolicy gate

- AAP YOK = app tüm tenant mailbox'larına erişebilir → **YASAK** (security boundary violation)
- AAP `ai@acik.com` only = sadece bu mailbox erişilebilir → **doğru**
- §4.4 enforcement test post-activation zorunlu (Denied beklenir başka mailbox için)

### 6.3 Read-only invariant

- Helper script SADECE GET çağrıları kullanır
- Mail.Read permission write/delete/move IZIN VERMEZ (Microsoft enforced)
- `--include-body` body preview 500 chars max (full body access user explicit opt-in)
- Attachment download YOK (helper script attachment-content-fetch desteklemez)

### 6.4 Redaction

- Helper output `subject`, `from`, `to`, `receivedDateTime`, `hasAttachments`, optionally `bodyPreview[:500]`
- Default secret/token-bearing patterns body preview'da filtrelenmez (manual review gerekirse user dikkat)
- Future enhancement: regex-based body redaction (URL userinfo, token-like strings)

## 7. Closure / Acceptance

This runbook is **operator-activatable**. Activation steps — **LIVE 2026-06-12** (Microsoft Graph PowerShell SDK + Exchange Online PowerShell):

- [x] §3.1 Entra app Mail.Read permission added (`Add-MgApplicationPassword` chain; role assignment Mail.Read `810c84a8-...`)
- [x] §3.2 Tenant admin consent granted (`New-MgServicePrincipalAppRoleAssignment`)
- [x] §3.3 ApplicationAccessPolicy created (`New-ApplicationAccessPolicy` RestrictAccess → group `Mail-Graph-Allowed-Mailboxes` → ai@acik.com only)
- [x] §4.1 Vault credential verify (`kv/platform/graph` 3 keys: graph_client_id/graph_tenant_id/graph_client_secret seeded via stdin-pipe)
- [x] §4.2 Token smoke pass (`has_access_token=true`, expires_in=3599)
- [x] §4.3 Graph list smoke pass (5 messages JSON output — ai@acik.com inbox read)
- [x] §4.4 AAP enforcement test pass (ai@acik.com Granted; ai.enes@acik.com + halil.kocoglu@serban.com.tr `ErrorAccessDenied` "Blocked by tenant configured AppOnly AccessPolicy")
- [x] ADR-0024 D7 §"Last Update" updated with activation date (2026-06-12)
- [x] Helper script smoke recorded (heredoc stdin bug fixed: `docker exec -i` → `docker exec` + quoted-heredoc env-var pattern)

**Activation provenance**: client secret `graph-mail-agent-read-20260612` (12 ay, expiry 2027-06-12). Revoke: `Remove-MgApplicationPassword -ApplicationId f82c4320-257c-4c18-a0f9-0a6f76b92e41 -KeyId <keyid>`.

## 8. Cross-AI Peer Review

- **Implementer**: Claude (Anthropic) — Session 51 Graph Mail.Read agent inbox read scope
- **Reviewer (plan-time)**: Codex (OpenAI GPT-5.2) thread `019ebac1` PARTIAL → 4 absorb done
  - Mail.Read (not Mail.ReadBasic) — bodyPreview için doğru scope
  - ApplicationAccessPolicy app-wide + mail-enabled security group pattern
  - Token TTL 1h Graph default; cache disabled by default
  - ADR-0024 D7 addendum (not single-line note)
- **Verdict**: AGREE after 4 absorb (source-side scope LIVE; operator activation pending §3)

**Closure ≠ runbook merge**: Bu runbook MERGED ≠ Graph Mail.Read activated. Closure operator §3 + agent §4 smoke + §7 8-item checklist sonra.

---

## 9. Send Surface (D7b — agent/ops explicit send)

> **Helper**: `scripts/ops/graph-mail-send.sh` | **ADR**: §D7b | **Codex**: `019ebbdb` PARTIAL→5 absorb | **LIVE 2026-06-12**

D7 read yüzeyinin simetriği: agent `ai@acik.com`'dan **Mail.Send** Application permission ile mail gönderir. **Backend GraphMailAdapter DEĞİŞMEZ** (SMTP send-path canonical korunur).

### 9.1 Boundary (read-only invariant'tan farklı)

D7 helper SADECE GET (read-only). D7b helper **outbound POST** (`/users/ai@acik.com/sendMail`) — bu yüzden ek guard'lar:

- **Dry-run by default**: `--send` olmadan network call YOK; sadece payload preview
- **`--confirm-recipients` mekanik guard**: `--send` için zorunlu; normalize `to+cc` set eşleşmeli
- **From sabit `ai@acik.com`** (AAP sender enforce; `--from` yok)
- **Body argv/env'de değil**: base64 + heredoc script stream → remote process list'te görünmez
- **Send-mode audit**: body değeri loglanmaz (sadece body_len); dry-run body'i gösterir (onay için)
- **No retry** (sendMail idempotent değil); **agent-layer per-message approval** (HARD RULE "send AS user")

### 9.2 Usage

```bash
# Dry-run (default — gönderim YOK, payload preview):
./scripts/ops/graph-mail-send.sh --to someone@acik.com --subject "Konu" --body "Metin"

# Gerçek gönderim (--send + --confirm-recipients ikisi zorunlu):
./scripts/ops/graph-mail-send.sh --to someone@acik.com --subject "Konu" --body "Metin" \
    --send --confirm-recipients someone@acik.com

# HTML + cc + body-file:
./scripts/ops/graph-mail-send.sh --to a@acik.com --cc b@acik.com --subject "Rapor" \
    --body-file /tmp/report.html --content-type html \
    --send --confirm-recipients "a@acik.com,b@acik.com"
```

### 9.3 Self-send smoke (acceptance)

```bash
# 1. Dry-run preview
./scripts/ops/graph-mail-send.sh --to ai@acik.com --subject "<unique>" --body "test"
# → dry_run:true, recipient_confirm:ai@acik.com, external_recipients:[]

# 2. Send
./scripts/ops/graph-mail-send.sh --to ai@acik.com --subject "<unique>" --body "test" \
    --send --confirm-recipients ai@acik.com
# → {"status":"accepted","http_status":202,...}

# 3. Inbox kanıtı
./scripts/ops/graph-mail-list.sh --search "<unique>"
# → mesaj listede görünür (self-delivery + Graph send path kanıtı; external deliverability AYRI)

# 4. AAP enforce (negative — agent-layer, opsiyonel):
# from ai@acik.com only enforce; başka sender app token ile Denied (read helper §4.4 mantığı)
```

### 9.4 Agent Usage Patterns (send)

User: "ai@acik.com'dan X kişisine şu maili at: ..."
Agent:
1. `graph-mail-send.sh ... ` **dry-run** çalıştırır → payload preview'i kullanıcıya gösterir
2. Kullanıcı **açık onay** verir ("evet gönder")
3. Agent `--send --confirm-recipients <exact to+cc>` ile gönderir
4. HTTP 202 + (opsiyonel) `graph-mail-list.sh --search` ile sent kanıtı

**Onay olmadan `--send` YASAK** (HARD RULE "send AS the user").

### 9.5 D7b Closure Acceptance — LIVE 2026-06-12

- [x] Helper dry-run preview LIVE (network yok)
- [x] **External send smoke LIVE** ai@acik.com → halil.kocoglu@serban.com.tr: HTTP 202 Accepted + ai@acik.com sent-copy (13:03Z) + **recipient inbox receipt user-confirmed** (external deliverability proven, self-send'den güçlü kanıt) + 0 NDR
- [x] `--confirm-recipients` mismatch abort kanıtı (exit 4)
- [x] shellcheck clean
- [x] ADR-0024 §D7b LIVE + §"Last Update" stamp

**Live evidence**: `--send --confirm-recipients halil.kocoglu@serban.com.tr` → `{"status":"accepted","http_status":202}`; recipient (Halil, Serban tenant) gerçekten aldı (kullanıcı doğruladı). Bu external deliverability + Graph send path + AAP sender-gate (ai@acik.com only) uçtan uca kanıtı.
