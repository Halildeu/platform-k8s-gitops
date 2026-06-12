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

### 4.1 Vault Credential Verify

```bash
ssh halil@staging-sw '
VAULT_ROOT_TOKEN=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json 2>/dev/null || \
                   jq -r .root_token /home/halil/bootstrap-drill/vault-init.json)
docker exec -i -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-prod \
    vault kv get kv/platform/graph 2>/dev/null || \
docker exec -i -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault \
    vault kv get kv/platform/graph | head -20
unset VAULT_ROOT_TOKEN
' | grep -E "graph_client_id|graph_tenant_id" | head -5
# Expected: graph_client_id + graph_tenant_id keys visible (client_secret value not echoed)
```

### 4.2 Token Smoke

```bash
ssh halil@staging-sw '
VAULT_ROOT_TOKEN=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json 2>/dev/null || \
                   jq -r .root_token /home/halil/bootstrap-drill/vault-init.json)
GRAPH_DATA=$(docker exec -i -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault-prod \
    vault kv get -format=json kv/platform/graph 2>/dev/null || \
    docker exec -i -e VAULT_TOKEN="$VAULT_ROOT_TOKEN" platform-vault \
    vault kv get -format=json kv/platform/graph)

CLIENT_ID=$(echo "$GRAPH_DATA" | jq -r ".data.data.graph_client_id // .data.data.client_id")
CLIENT_SECRET=$(echo "$GRAPH_DATA" | jq -r ".data.data.graph_client_secret // .data.data.client_secret")
TENANT_ID=$(echo "$GRAPH_DATA" | jq -r ".data.data.graph_tenant_id // .data.data.tenant_id")

TOKEN_RESPONSE=$(curl -sS -X POST \
    "https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "client_id=${CLIENT_ID}" \
    --data-urlencode "client_secret=${CLIENT_SECRET}" \
    -d "scope=https://graph.microsoft.com/.default" \
    -d "grant_type=client_credentials")

# Sanitized: only token type + expiry shown, never the access_token value
echo "$TOKEN_RESPONSE" | jq "{token_type, expires_in, has_access_token: (.access_token != null)}"

unset CLIENT_SECRET VAULT_ROOT_TOKEN GRAPH_DATA TOKEN_RESPONSE
'
# Expected: {"token_type":"Bearer","expires_in":3599,"has_access_token":true}
```

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

- `graph_client_secret` SADECE `staging-sw` Vault'unda; her çağrıda SSH round-trip okur
- Token cache YOK default (1h TTL Graph; her çağrı yeni token = 2s latency)
- Helper script `unset` chain final (token + secret asla disk veya log'a düşmez)

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

This runbook is **operator-activatable**. Activation steps:

- [ ] §3.1 Entra app Mail.Read permission added
- [ ] §3.2 Tenant admin consent granted
- [ ] §3.3 ApplicationAccessPolicy verified or created (ai@acik.com only)
- [ ] §4.1 Vault credential verify (Vault kv/platform/graph graph_* keys present)
- [ ] §4.2 Token smoke pass (has_access_token=true)
- [ ] §4.3 Graph list smoke pass (5 messages JSON output)
- [ ] §4.4 AAP enforcement test pass (other mailbox Denied)
- [ ] ADR-0024 D7 §"Last Update" + current-state.md live delta updated with activation date
- [ ] Helper script smoke recorded (first sanitized output)

## 8. Cross-AI Peer Review

- **Implementer**: Claude (Anthropic) — Session 51 Graph Mail.Read agent inbox read scope
- **Reviewer (plan-time)**: Codex (OpenAI GPT-5.2) thread `019ebac1` PARTIAL → 4 absorb done
  - Mail.Read (not Mail.ReadBasic) — bodyPreview için doğru scope
  - ApplicationAccessPolicy app-wide + mail-enabled security group pattern
  - Token TTL 1h Graph default; cache disabled by default
  - ADR-0024 D7 addendum (not single-line note)
- **Verdict**: AGREE after 4 absorb (source-side scope LIVE; operator activation pending §3)

**Closure ≠ runbook merge**: Bu runbook MERGED ≠ Graph Mail.Read activated. Closure operator §3 + agent §4 smoke + §7 8-item checklist sonra.
