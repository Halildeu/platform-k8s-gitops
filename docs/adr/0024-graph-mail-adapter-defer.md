# 0024 — Notification Mail Delivery: Defer Microsoft Graph Adapter, Preserve SMTP Path

> **Status**: Accepted
> **Tarih**: 2026-05-20
> **Karar otoritesi**: Codex thread `019e44b1` (defer contract alignment review — cross-AI peer review)
> **Antecedent reviews**: `019e42d1` (PR #872 staged-only ESO 3-key + DNS runbook AGREE_B), `019e4445` (#862 wrapper bridge deprecation + bridge truth-cleanup REVISE)
> **Öncüller**: [ADR-0013 — Notification orchestration](./0013-notification-orchestration.md) D40 (TR SMS) + D44 (channel coverage tier) + D45 (5 yeni kategori — Deliverability axis), [docs/runbooks/RB-faz-23-dns-records-acik-com.md](../runbooks/RB-faz-23-dns-records-acik-com.md), [docs/runbooks/RB-prod-alertmanager-activation.md](../runbooks/RB-prod-alertmanager-activation.md) §2 owner-artifact pattern
> **Implementation State**: activation **deferred**; Entra app + admin consent **preserved**; **no** client secret, **no** ApplicationAccessPolicy, **no** Vault secret values, **no** ConfigMap flag flip, **no** digest bump
> **Yürütür**: Faz 23.x notification platform — mail delivery future-proofing track
> **Board tracker**: [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) (P3 Backlog, future-only; reactivation trigger conditions documented)

---

## Context

`notification-orchestrator` servisinin mail delivery'si bugün **SMTP Office 365 path**'i üzerinden çalışır:

- Vault: `kv/platform/notification-orchestrator.smtp_username` (`ai@acik.com`) + `smtp_password` (Microsoft 365 App Password, 16-char generated; mevcut canlı kullanım sırasında 10-char observed — App Password format varyasyonu, Microsoft tenant policy)
- Backend: Spring Boot `JavaMailSender` autoconfig + `SmtpAdapter` (`@ConditionalOnProperty(notify.adapters.graph.enabled, havingValue=false, matchIfMissing=true)`)
- Smarthost: `smtp.office365.com:587` (STARTTLS standard)
- Multi-provider compatibility (env binding aynı kalır; vendor değişiminde sadece `SPRING_MAIL_HOST` + credentials değişir): Office 365 default, SendGrid, AWS SES, Postmark, Mailgun, internal MTA
- Status: 🟢 LIVE — prod cluster `notification-orchestrator` pod aktif kullanım

Backend `GraphMailAdapter` (Microsoft Graph REST API via port 443) **binary ready**:

- `platform-backend` PR #153 MERGED (sha-585b64f); `GraphTokenService` + `GraphMailAdapter` + `MailAdapter` interface ile alternative path
- Activation flag: `notify.adapters.graph.enabled=true` mutual exclusion (`SmtpAdapter` `havingValue=false` ConditionalOnProperty ile devre dışı; `GraphMailAdapter` kendi `havingValue=true` ile devreye girer)
- OAuth2 client credentials flow: tenant_id + client_id + client_secret zorunlu; `GraphTokenService` constructor fail eder eksik credential ile

Gitops staged-only kayıt (Session 42):

- PR #872 (Codex `019e42d1` AGREE_B): `kustomize/overlays/{test,prod}/eso/notify/externalsecret-notify.yaml` — Graph 3-key additive (`NOTIFY_ADAPTERS_GRAPH_TENANT_ID`/`CLIENT_ID`/`CLIENT_SECRET` ← `kv/platform/notification-orchestrator.graph_*`)
- PR #872: `docs/runbooks/RB-faz-23-dns-records-acik-com.md` (DNS SPF/DMARC/DKIM operator runbook; drift-free, mail authentication baseline)
- **NO** activation flag in `kustomize/overlays/{test,prod}/kustomization.yaml` (defer)
- **NO** notification-orchestrator digest bump (`sha-585b64f` Graph-binary-inclusive sha prod'a promote edilmedi)
- **NO** sender-mailbox / save-to-sent-items Graph config

Entra Microsoft 365 tenant setup (Session 42):

- App Registration `acik-mail-graph-api` yaratıldı 2026-05-20 (`Açık Holding` tenant single-tenant, owner halil.kocoglu@serban.com.tr)
- `client_id`: `6e3e5b4b-b819-41b0-a237-8774c6418e32`
- `tenant_id`: `6f49871e-cb5b-4b2f-b986-5b68f16365b9`
- API permissions: Microsoft Graph **Mail.Send (Application — Send mail as any user)** + User.Read (Delegated — bootstrap default)
- **Admin consent verildi** (tenant-wide; granted by `ai.enes@acik.com` global admin)
- Client secret **yaratılmadı** (defer karar; Session 42 kullanıcı kararı: "riski yüksek, sonra yapalım")
- ApplicationAccessPolicy **yapılmadı** (`ai@acik.com` mailbox daraltma; Microsoft Graph PowerShell SDK adımı)

Aktif risk değerlendirmesi (Session 42, post-defer):

- Mail.Send Application permission tenant-wide grant edildi **AMA** client_secret olmadan OAuth2 client_credentials flow token alamaz → app permission'ı kullanamaz
- `client_id` + `tenant_id` tek başına credential **değil**; UUID public identifier'lar
- App reg "yapı kurulu, anahtar üretilmemiş" pasif durumda
- Aktif credential ground-zero; Vault `graph_*` 3 key boş (test + prod); ConfigMap flag false default; pod runtime SmtpAdapter active

### Tetikleyici trend: Microsoft App Password deprecation horizon

Microsoft 365 SMTP AUTH legacy authentication kademeli olarak kullanımdan kaldırılıyor:

- **2022 başı**: Yeni tenant'lar için SMTP AUTH default disabled (`Set-TransportConfig -SmtpClientAuthenticationDisabled $true`)
- **2024-2025**: Mevcut tenant'lar için phased disable (Microsoft duyuruları + tenant-level override pencereleri)
- **App Passwords**: Microsoft 2024 Q3+ Conditional Access / Identity Protection ile kademeli olarak deprecated; Modern Authentication (OAuth2) önerilir
- **Outbound port 587 ISP blocks**: Bazı ISP'ler (TR'de Türk Telekom, Türksat dahil) outbound 587 SMTP'yi spam-control için block edebilir (operasyonel haberler periyodik)

Bu trendler `SmtpAdapter` path'ini riske eder; **Graph adapter alternative path mutual exclusion ile hazırdır** ama activation **trigger-driven** olarak alınır.

---

## Decision

### D1 — SMTP Office 365 path canonical olarak korunur

`notify.adapters.graph.enabled=false` default (`matchIfMissing=true`). `SmtpAdapter` `JavaMailSender` ile `ai@acik.com` Office 365 SMTP relay üzerinden mail gönderir. Mevcut Vault credentials (`smtp_username` + `smtp_password`) `notification-orchestrator` ESO ExternalSecret üzerinden mount edilir.

### D2 — Graph adapter backend binary capability olarak korunur

`platform-backend` PR #153 (`GraphMailAdapter` + `GraphTokenService`) **deprecate edilmez veya kaldırılmaz**. Backend binary `sha-585b64f` ve sonrası Graph-binary-inclusive (`MailAdapter` interface ile mutual exclusion). Test cluster digest promotion'unda Graph code path build artifact'inin parçası olarak gelir; ConditionalOnProperty `false` default ile inactive.

### D3 — Graph activation TRIGGER-driven, planned değil

Activation chain yalnız aşağıdaki tetik koşullarından **en az biri** geldiğinde çalıştırılır:

1. **Microsoft App Password deprecation tenant'ı etkiler** — `ai@acik.com` mailbox App Password ile SMTP AUTH legacy authentication policy break sonucu mail gönderemez
2. **SMTP AUTH tenant policy break** — Microsoft 365 admin (tenant veya organization-level) SMTP AUTH'u disable eder (`Set-TransportConfig -SmtpClientAuthenticationDisabled $true`)
3. **Outbound port 587 ISP/firewall block recurrence** — staging-sw veya cluster outbound 587 block ile karşılaşır + alternative SMTP relay endpoint operasyonel değil
4. **Ops/security tactical decision** — risk register / audit / compliance gereksinimi OAuth2 modern auth'a geçişi zorunlu kılar
5. **Provider migration tactical decision** — Office 365 → başka tenant veya başka mail provider geçişi sırasında Graph path daha kolay (App Password rotation overhead azaltma)

### D4 — Entra App Registration + admin consent **asset olarak korunur**

`acik-mail-graph-api` Entra app reg + Mail.Send Application permission + tenant-wide admin consent yaratıldı ve **silinmez**. Sebep:

- En ağır setup (App Reg yaratma + permission + global admin consent) tamamlandı; reactivation chain 5 adıma indirgendi
- Audit trail temizliği: Entra'da orphan asset değil — bu ADR + RB-runbook + #892 board issue ile auditable kayıtlı
- Reactivation reaction time kritik durumda (örn. App Password tenant break) saatlere indirilir; aksi halde yeni app reg + global admin consent günleri alabilir

### D5 — Reactivation chain ATOMIC; parçalı aktivasyon **yapılmaz**

Defer state'ten activation'a geçiş yalnız aşağıdaki **5 adım birlikte** owner-approved window'da çalıştırılır. Parçalı aktivasyon (örn. sadece Vault seed + flag flip; ApplicationAccessPolicy skip) **YASAK**:

1. **Entra**: Yeni istemci gizli dizisi (client_secret) yarat — Description `notify-orchestrator-vault-seed`, Expires `730 gün` (24 ay), value `📋 kopyala` (1 kez gösterilir)
2. **PowerShell ApplicationAccessPolicy** (`Microsoft Graph PowerShell SDK` + `ExchangeOnlineManagement`): mail-enabled security group oluştur (`Mail-Graph-Allowed-Mailboxes`) + `ai@acik.com`'ı gruba ekle + `New-ApplicationAccessPolicy -AppId <client_id> -PolicyScopeGroupId <group> -AccessRight RestrictAccess`. `Test-ApplicationAccessPolicy` ile `Granted` (`ai@acik.com`) + `Denied` (başka mailbox) ikili kanıt
3. **Vault seed** (test + prod, 3 keys per cluster): `vault kv patch kv/platform/notification-orchestrator graph_tenant_id=... graph_client_id=...` inline + `graph_client_secret` stdin pipe (hidden prompt, bash history + chat transcript safe)
4. **Activation PR**: `kustomize/overlays/{test,prod}/kustomization.yaml` ConfigMap `NOTIFY_ADAPTERS_GRAPH_ENABLED=true` flip + (gerekirse) notification-orchestrator digest bump Graph-binary-inclusive sha'ya — test cluster önce, prod cluster A5 PR-B + RAID I6 sequencing sonra
5. **Smoke send acceptance**: token acquisition success + `POST /users/ai@acik.com/sendMail` Graph REST 202 Accepted + recipient inbox proof (`halil.kocoglu@serban.com.tr`) + sender Sent Items proof + notification-orchestrator pod loglarında `GraphMailAdapter active`, `SmtpAdapter inactive`

### D6 — Mailbox scope daraltma reactivation prereq

ApplicationAccessPolicy (D5 adım 2) zorunlu. App `Mail.Send` permission **tenant-wide grant'tan** sonra `ai@acik.com` mailbox'a **daraltılmalı** (`RestrictAccess`). Aksi halde client_secret çalınırsa kötü actor tenant'taki herhangi bir mailbox'tan mail gönderebilir; ApplicationAccessPolicy bu blast-radius'u **sadece** `ai@acik.com`'a indirir.

### D7 — Agent/ops inbox read **same Entra asset, ayrı scope** (2026-05-28 addendum)

> **Status**: DECISION (2026-05-28; user direktif "doğrudan yetki vereyim gerektiğinde gelen mailleri görmek bu sohbetten sana sormak istiyorum") — operator activation pending (~5 dk; bkz [RB-graph-mail-agent-read.md](../runbooks/RB-graph-mail-agent-read.md) §3)
> **Codex thread**: `019ebac1` PARTIAL → 4 absorb (Mail.Read scope, AAP app-wide+mail-enabled security group, token TTL 1h no cache default, D7 addendum vs single-line)
> **NOT backend adapter activation**: D7 sadece **agent/ops side Graph REST read** access ekler; backend `notify.adapters.graph.enabled` flag DEĞİŞMEZ; SmtpAdapter canonical send-path KORUNUR (D1-D6 unchanged).

Agent (Claude Code chat oturumu) Microsoft Graph `Mail.Read` Application permission ile `ai@acik.com` inbox'ı **read-only** sorgulayabilir. Gerçek kullanım: user soruyu sorduğunda agent `scripts/ops/graph-mail-list.sh` çağırır → Vault credential (mevcut `kv/platform/graph` reuse) + token (1h TTL Graph default, cache disabled by default) + Graph REST `/users/ai@acik.com/messages` → sanitized JSON.

**Scope boundaries**:
- **Permission**: `Mail.Read` Application (NOT `Mail.ReadBasic`/`Mail.ReadWrite`); `bodyPreview` 500 chars truncated default; `--include-body` flag full preview
- **AAP**: D6 `ApplicationAccessPolicy` app-wide (Mail.Send + Mail.Read aynı policy); mail-enabled security group `Mail-Graph-Allowed-Mailboxes` ile `ai@acik.com` only (operator §3.3 verify or create)
- **Read-only invariant**: helper script SADECE GET; Mail.Read permission Microsoft-enforced write/delete/move IZIN VERMEZ
- **Token**: client_credentials grant (app-only; user oturum yok); per-call Vault round-trip (~2s); persistent cache YOK default; opsiyonel `--cache-token` (0600 + expiry-aware, default disabled)
- **Helper**: `scripts/ops/graph-mail-list.sh` SSH staging-sw round-trip; `unset` chain final (credential + token disk/log'a düşmez)
- **Usage pattern**: USER-driven only (cron/monitor değil); agent her çağrı için explicit user prompt gerek

**Trigger conditions** (D3 unchanged + addition):
- D3 backend GraphMailAdapter aktivasyon trigger'ları KORUNUR (SMTP outage, App Password deprecation, port 587 block, vb.)
- D7 **NO trigger** — user direktifi ile direkt aktive (operator §3 3-adım); inbox read backend dependency yok

**Acceptance** (D7 closure):
- §3.1 Mail.Read permission added Entra app
- §3.2 Tenant admin consent granted
- §3.3 AAP verified or extended (mail-enabled security group with `ai@acik.com`)
- §4.2 Token smoke pass (has_access_token=true)
- §4.3 Graph list smoke pass (5 message JSON output)
- §4.4 AAP enforcement test pass (other mailbox Denied)
- `Last Update` section actual activation date stamped

**Out-of-scope D7**:
- Backend GraphMailAdapter activation (D1-D6 send-path unchanged)
- IMAP/POP3 alternative client
- Mailbox content persistence/indexing/audit
- Per-user delegated permission flow
- Mailbox content backup/export
- Inbound webhook subscription (Microsoft Graph subscription)

### D7b — Agent/ops explicit **send** helper (2026-06-12 addendum)

> **Status**: LIVE 2026-06-12 (Codex `019ebbdb` PARTIAL → 5 absorb)
> **NOT backend adapter activation**: D7b sadece **agent/ops side Graph REST send** yüzeyi; backend `notify.adapters.graph.enabled` flag DEĞİŞMEZ; SmtpAdapter canonical send-path KORUNUR (D1-D6 unchanged).

D7 read yüzeyinin simetriği: agent (Claude Code chat) Microsoft Graph **Mail.Send** Application permission ile `ai@acik.com`'dan mail gönderebilir. Helper `scripts/ops/graph-mail-send.sh` Graph REST `POST /users/ai@acik.com/sendMail` çağırır.

**Scope boundaries** (Codex `019ebbdb` 5 absorb):
- **From sabit**: `ai@acik.com` (`--from` YOK); AAP zaten sender mailbox'ı enforce eder (secret sızıntı blast radius = tek mailbox)
- **Dry-run default**: `--send` flag'i olmadan HİÇBİR network call yok; sadece payload preview (to/cc/subject/body/external_recipients/recipient_confirm)
- **`--confirm-recipients` mekanik guard**: `--send` için zorunlu; normalize edilmiş `to+cc` set'iyle eşleşmeli (yanlış-alıcı guard; CC dahil)
- **Body argv/env'de DEĞİL**: payload jq `--arg` ile injection-safe local kurulur, base64 encode edilir, heredoc *script stream*'inde gömülür → body/subject remote process list'te görünmez
- **Send-mode audit**: stderr sadece to/cc/subject/content_type/body_len/external_recipients/http_status; body değeri / token / secret loglanmaz. Dry-run body'i gösterir (kullanıcı onayı için)
- **External recipients görünür**: dry-run + audit `external_recipients` (acik.com olmayan) listesini açık gösterir; hard allowlist ilk slice'ta YOK (agent-layer per-action approval ile yönetilir)
- **No retry**: Graph `sendMail` idempotent değil → tek POST; belirsiz hatada otomatik tekrar YOK (önce sent-items/inbox kanıtı, sonra yeni explicit approval)
- **No token cache, no backend flag change**

**Agent-layer confirm gate** (Anthropic HARD RULE "send AS the user"): helper non-interactive (CI/agent-safe); her gerçek mail için kullanıcı onayı (alıcı+konu+içerik göster, açık yes bekle, sonra `--send`) **agent katmanında** alınır. Helper sadece mekanik guard (`--confirm-recipients`) ile yanlışlıkla gönderimi zorlaştırır.

**Acceptance** (D7b closure):
- Dry-run preview LIVE (network yok)
- Self-send smoke `ai@acik.com → ai@acik.com` → HTTP 202 + inbox'ta görünme (`graph-mail-list.sh --search`)
- `--confirm-recipients` mismatch → abort kanıtı
- Helper end-to-end (shellcheck clean + dry-run + send)

**Out-of-scope D7b**:
- Backend GraphMailAdapter activation (D1-D6 SMTP send-path canonical korunur)
- Bulk/campaign send (notification-orchestrator domain'i, ayrı)
- Attachment send (helper ilk slice attachment desteklemez)
- Template/merge-field send
- Scheduled/deferred send

### D7c — Backend GraphMailAdapter **TEST cutover** (2026-06-12 — D1-D6 reactivation, test slice)

> **Status**: TEST adapter-LIVE 2026-06-12 (Codex thread `019ebc0e` REVISE-with-conditions plan + post-impl AGREE; PR #1477 MERGED `00466d2a`). **PROD hâlâ SMTP** (D1 prod için geçerli; prod cutover ayrı owner-gated slot).
> **Bu D7/D7b'den FARKLI**: D7/D7b = agent/ops yüzeyi (helper script'ler); **D7c = backend notification-orchestrator pipeline'ının kendisi** (D1-D6'da deferred edilen GraphMailAdapter'ın TEST cluster'da activation'ı).

D1-D6 "SMTP canonical, Graph deferred" kararı **TEST cluster için reactivation trigger karşılandı** (ADR-0024 D3 ops/security tactical decision): bu tenant'ta Conditional Access agresif basic-auth deprecation (device-code 4× timeout 2026-06-12 canlı gözlem) + D7b Graph app-only external delivery proof. Backend mail send path SMTP → Graph app-only cutover, TEST cluster.

**Activation** (PR #1477):
- ESO test overlay: 3 Graph remoteRef uncomment (`NOTIFY_ADAPTERS_GRAPH_*` ← `kv/platform/notification-orchestrator.graph_*`, platform-vault-test)
- ConfigMap: `NOTIFY_ADAPTERS_GRAPH_ENABLED=true` + `SENDER_MAILBOX=ai@acik.com` + `SAVE_TO_SENT_ITEMS=true`
- GraphMailAdapter `@ConditionalOnProperty(notify.adapters.graph.enabled=true)` → mutual exclusion: GraphMailAdapter aktif, SmtpAdapter pasif (SMTP config korunur)
- **Digest bump YOK** — GraphMailAdapter.java binary'de mevcut (live image Graph-inclusive)

**LIVE doğrulanan (adapter/infra seviyesi)**:
- ESO Ready=True/SecretSynced + Secret 3 Graph key non-empty
- GraphMailAdapter initialized (sender=ai@acik.com, saveToSentItems=true) + GraphTokenService initialized
- SmtpAdapter absent (count 0) → mutual exclusion proven
- Evidence: `docs/faz-23-evidence/2026-06-12-notify-graph-send-cutover-test.md`

**Credential** (Codex `019ebc0e` #4): backend için **dedicated** client secret (D7/D7b agent helper secret'inden AYRI → bağımsız rotation); test Vault `kv/platform/notification-orchestrator.graph_*`; prod cutover'da ayrı prod backend secret.

**✅ Functional smoke PROVEN (2026-06-12 15:26–15:28 UTC)**:
- **`POST /api/v1/notify/intents`** (email channel, persona JWT) → **202 ACCEPTED** → intent `COMPLETED`; `notification_delivery` status=**DELIVERED** + provider_msg_id `<af51812a-…@notification-orchestrator-graph>`
- Pod log: `GraphMailAdapter : graph mail accepted … status=202` + `GraphTokenService : access_token refreshed` → adapter'ın **kendi code path'i** (in-cluster app-only auth + payload builder + Graph POST) gerçek intent ile **kanıtlandı**
- ai@acik.com **Sent Items** (saveToSentItems) + **Inbox receipt** (self-send) + delivered e-postanın `x-notify-message-id` header'ı = DB provider_msg_id (uçtan-uca izlenebilirlik) + `Authentication-Results: dkim=none` yakalandı (intra-tenant Internal)
- Reçete (proven): t318 ALLOW-path reuse — persona `d29-evidence-tester` (org_id+subscriberId claim) + OpenFGA `can_receive@template:t1` allowed:true + template t1 + subscriber email→ai@acik.com (smoke sonrası restore). Tam kanıt: evidence doc §8
- Tüm eligibility guard'lar AÇIK koşuldu (NOTIFY_AUTHZ OpenFGA + PREFERENCES + SUBSCRIBER_IDENTITY_STRICT)

**PENDING (No Fake Work)**:
- **Prod cutover** — ayrı owner-gated slot (D30 disiplini; ayrı prod backend secret + DKIM Authentication-Results re-validation + 72h soak)

**Rollback** (doğrulanmış güvenli): `NOTIFY_ADAPTERS_GRAPH_ENABLED=false` + rollout restart → SmtpAdapter geri aktif (config korunuyor; AAP/consent/app-reg dokunulmaz).

**D1 statüsü**: TEST için Graph-active; **PROD için SMTP canonical korunur** (D1 prod'da geçerli; prod cutover gelene kadar).

**Out-of-scope D7c**:
- Prod cutover (ayrı owner-gated slot)
- Bulk/campaign send (transactional notification scope; bulk ayrı provider/reputation)
- Bulk/campaign reputation soak (transactional scope; ayrı)

---

## Consequences

### Pros

- **Aktif risk sıfır**: Mail.Send permission grant edildi ama client_secret olmadan OAuth2 token alınamaz; permission "yapı kurulu, anahtar yok" pasif durumda
- **Setup overhead minimum**: En ağır step (Global Admin consent + App Registration) tamamlandı; reactivation 5 adıma indirgendi (~30-60 dk hızlı response)
- **Microsoft App Password deprecation horizon hazırlığı**: Tetik geldiğinde tenant continuity için ground work zaten yapılmış
- **Audit trail temizliği**: Entra'da orphan asset değil; bu ADR + RB-runbook + #892 board issue ile tüm karar zinciri kayıtlı
- **Cross-cutting**: SMTP rollback aniden gerektiğinde Graph reactivation chain hazır; SMTP outage (provider degradation veya port block recurrence) sırasında 5-adım failover

### Cons

- **Single mail path (SMTP)**: Eğer SMTP outage olursa fallback Graph hazır değil; 5 adım reactivation çalıştırılmadan mail kesilebilir. Çözüm: D43 outage fallback bypass pattern (`alertmanager-fallback` direct-fallback receiver SMTP+Slack TRIPLE delivery; bkz. [RB-notification-outage-fallback.md](../runbooks/RB-notification-outage-fallback.md))
- **Entra asset orphan görünebilir**: Audit clarity için bu ADR + RB + #892 zorunlu; doc drift bu asset'i "ne için var" sorusunda muğlak bırakabilir
- **Future App Password rotation**: `ai@acik.com` App Password 2025 sonrası rotate gerekebilir (Microsoft policy); rotation operasyonel manuel iş — Graph adapter aktive edilirse client_secret rotation 24 aylık otomatize edilebilir (modern auth)
- **DKIM/DMARC integration drift**: Graph aktive edildiğinde mail delivery path değişir; DNS records (`docs/runbooks/RB-faz-23-dns-records-acik-com.md` SPF/DMARC/DKIM) re-validate gerekir. Bu reactivation runbook'un kapsamında

### Non-decisions (out of scope)

- Backend `GraphMailAdapter` code review değişimi (PR #153 merged + binary stable)
- DNS records (SPF/DMARC/DKIM) — ayrı operator action [RB-faz-23-dns-records-acik-com.md](../runbooks/RB-faz-23-dns-records-acik-com.md)
- Notification-orchestrator digest promotion stratejisi (A5 PR-B + RAID I6 sequencing; ayrı board tracker)
- Provider migration (Office 365 → SendGrid/AWS SES/internal MTA) — bu ADR'in dışı; vendor-agnostic env binding korunur

---

## Compliance / verify

Bu ADR'a göre **bu repodaki** aşağıdaki kontrat noktaları **iç-tutarlı** olmalı:

| Surface | İçerik | Status |
|---|---|---|
| `PLAN.md` D49 (decisions catalog + status table) | D49 — Graph mail adapter strategy: defer, preserve | ✅ Yansıtıldı (PR #?? merge sonrası) |
| `docs/notify/risk-register.md` R23 | Graph deferral risk + reactivation triggers + mitigation | ✅ Yansıtıldı |
| `docs/notify/milestones.md` M3/M7 | SMTP canonical confirmed; Graph defer not blocker (M3); Graph scope-out v1 (M7) | ✅ Yansıtıldı |
| `docs/notify/feature-matrix.md` A1/H14 | A1 Email parenthetical cross-ref; H14 §8 Provider Management Graph activation path deferred | ✅ Yansıtıldı |
| `docs/state/current-state.md` | Entra state snapshot + Vault graph_* empty + ConfigMap flag false + SmtpAdapter expected/effective | ✅ Yansıtıldı |
| `docs/runbooks/RB-graph-mail-adapter-activation.md` | DEFERRED ACTIVATION RUNBOOK + D5 reactivation chain (6 atomic step set including ESO re-enable PR step 4) | ✅ Yansıtıldı |
| `kustomize/overlays/{test,prod}/eso/notify/externalsecret-notify.yaml` | Graph 3 `remoteRef` entries **commented out** (defer-aware refactor 2026-05-20, Codex `019e45f8` AGREE); deferred reactivation snippet stays inline. ESO aggregate `Ready=True` for active channels; Graph re-enable D5 reactivation chain step 4 (PR-gated, Cross-AI peer review) | ✅ Defer-aware refactor (A.1 issue #903 child) |
| Board issue #892 (P3 Backlog) | Reactivation trigger conditions documented; claim yok future-only | ✅ Mevcut |

---

## References

### Codex peer review chain (Session 42)

- `019e44b1`: Bu ADR + 7-file alignment scope verdict (AGREE_WITH_REVISIONS)
- `019e42d1`: PR #872 staged-only ESO 3-key + DNS runbook (AGREE_B; #510 superseded)
- `019e4445`: #862 wrapper bridge deprecation + bridge `gh` CLI doc-truth cleanup (REVISE)
- `019e45db` / `019e45f8`: ESO aggregate Ready=False blocker tespiti + defer-aware refactor (Çözüm 1 prod+test parity AGREE) — Graph 3 remoteRef comment-out; D5 reactivation chain step 4 re-enable PR-gated

### Cross-references

- Backend: [platform-backend PR #153](https://github.com/Halildeu/platform-backend/pull/153) — `GraphMailAdapter` + `GraphTokenService` + `MailAdapter` interface
- Gitops: PR #872 (`feat(notify-23-A8): gitops Graph adapter ESO 3-key + DNS runbook — staged-only`)
- Runbook: [docs/runbooks/RB-graph-mail-adapter-activation.md](../runbooks/RB-graph-mail-adapter-activation.md) — D5 reactivation chain (6 atomic step set)
- Runbook (DNS): [docs/runbooks/RB-faz-23-dns-records-acik-com.md](../runbooks/RB-faz-23-dns-records-acik-com.md) — SPF/DMARC/DKIM
- Runbook (D43 outage fallback): [docs/runbooks/RB-notification-outage-fallback.md](../runbooks/RB-notification-outage-fallback.md) — owner-artifact pattern reference
- ADR-0013: [Notification orchestration](./0013-notification-orchestration.md) — D40+D44+D45 mail delivery context
- Board: [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) — P3 Backlog future-only tracker

### Predecessor / related ADRs

- `0013-notification-orchestration.md`: D40 (SMS provider), D44 (channel coverage tier — Email kernel), D45 (5 yeni kategori — Deliverability axis)
- `0023-promotion-pipeline-test-overlay-authoritative.md`: test→prod promotion discipline; digest bump strategy

### External references

- Microsoft Graph API Mail.Send documentation: `https://learn.microsoft.com/en-us/graph/api/user-sendmail`
- Microsoft Entra ID Application Access Policy: `https://learn.microsoft.com/en-us/graph/auth-limit-mailbox-access`
- Microsoft 365 SMTP AUTH deprecation announcements: Microsoft Tech Community + roadmap.microsoft.com

---

## Last Update

**2026-06-12 (D7c — backend GraphMailAdapter TEST cutover)** — D1-D6 "SMTP canonical, Graph deferred" kararı **TEST cluster için reactivation** (Codex `019ebc0e` plan REVISE-with-conditions → post-impl AGREE; PR #1477 MERGED `00466d2a`). Backend notification-orchestrator mail send path SMTP → Graph app-only cutover TEST'te adapter-LIVE (GraphMailAdapter active sender=ai@acik.com saveToSentItems=true; SmtpAdapter absent mutual exclusion; ESO Ready + 3 Graph key Secret'te; dedicated backend secret D7 helper'dan ayrı). **PROD hâlâ SMTP** (D1 prod canonical; prod cutover ayrı owner-gated slot). **Functional smoke PROVEN 2026-06-12 15:26-15:28 UTC** (intent `graph-smoke-1781278009` → 202 → DELIVERED + provider_msg_id `@notification-orchestrator-graph` + ai@acik.com Sent Items + Inbox receipt + Authentication-Results; t318 ALLOW-path reuse, tüm guard'lar açık; Codex `019ebc5b`). Evidence: `docs/faz-23-evidence/2026-06-12-notify-graph-send-cutover-test.md` §8. D7c bölümü detay.

**2026-06-12 (D7b LIVE — agent/ops send activated)** — D7b (agent/ops explicit send helper, Codex `019ebbdb` PARTIAL→5 absorb) **LIVE 2026-06-12**:
- `scripts/ops/graph-mail-send.sh` MERGED (dry-run default + `--confirm-recipients` guard + body base64-not-argv + send-mode body-not-logged + no-retry).
- **External send smoke LIVE**: ai@acik.com → halil.kocoglu@serban.com.tr (Serban tenant, external) → Graph `POST /sendMail` **HTTP 202** + ai@acik.com sent-copy görünür + **recipient inbox receipt user-confirmed** + 0 NDR. Bu Graph send path + external deliverability + AAP sender-gate (ai@acik.com only) uçtan uca kanıtı (self-send smoke'a gerek kalmadı).
- `--confirm-recipients` mismatch → exit 4 abort kanıtı.
- **Backend GraphMailAdapter DEĞİŞMEDİ** — `notify.adapters.graph.enabled` disabled; SMTP send-path canonical (D1-D6); D7b sadece agent/ops send yüzeyi. Per-message user approval agent-layer'da (HARD RULE "send AS the user").

**2026-06-12 (D7 LIVE — agent/ops inbox read activated)** — D7 (agent/ops inbox read scope, ekleme tarihi 2026-05-28) **operator activation LIVE 2026-06-12**:
- Entra app `acik-mail-graph-api` **Mail.Read Application permission** eklendi + **tenant admin consent** verildi (Microsoft Graph PowerShell SDK `Add-MgApplicationPassword` + `New-MgServicePrincipalAppRoleAssignment`; role assignments doğrulandı: Mail.Read `810c84a8-...` + Mail.Send `b633e1c5-...`).
- **ApplicationAccessPolicy** kuruldu (`New-ApplicationAccessPolicy` `RestrictAccess`): mail-enabled security group `Mail-Graph-Allowed-Mailboxes` → sadece `ai@acik.com`. **D6 mailbox scope daraltma artık LIVE** (önceki snapshot AAP "yok" idi; Mail.Send tenant-wide risk de bu adımla kapandı).
- **Client secret üretildi** (`graph-mail-agent-read-20260612`, 12 ay, expiry 2027-06-12) + **prod Vault `kv/platform/graph`** seed edildi (3 key: `graph_client_id`/`graph_tenant_id`/`graph_client_secret`, stdin-pipe no-log).
- **Live enforce kanıtı**: `ai@acik.com` → Graph `/messages` **Granted** (5 mesaj okundu); `ai.enes@acik.com` → **`ErrorAccessDenied` "Blocked by tenant configured AppOnly AccessPolicy"**; `halil.kocoglu@serban.com.tr` → **Denied**. Blast radius secret sızıntısında tek mailbox.
- Helper `scripts/ops/graph-mail-list.sh` end-to-end LIVE (token + Graph list + AAP enforce). **Heredoc stdin bug** (`docker exec -i` heredoc stdin'ini tüketiyordu → `-i` kaldırıldı + quoted-heredoc env-var pattern).
- **Backend GraphMailAdapter DEĞİŞMEDİ** — `notify.adapters.graph.enabled` hâlâ disabled (D1-D6 send-path SMTP canonical korunur); D7 sadece agent/ops read yüzeyi.

**2026-05-28 (D7 addendum)** — Agent/ops inbox read scope kararı eklendi (Codex `019ebac1` PARTIAL → 4 absorb): same Entra asset, ayrı scope; Mail.Read app-only + AAP app-wide; user direktif "doğrudan yetki vereyim gerektiğinde gelen mailleri görmek bu sohbetten sana sormak istiyorum". Runbook: RB-graph-mail-agent-read.md.

**2026-05-20 (Session 42 — Codex `019e44b1` defer contract alignment)** — ADR-0024 yaratıldı. Graph mail adapter activation defer kararı + Entra app reg + admin consent asset preservation + reactivation chain (5 adım atomic) + Microsoft App Password deprecation horizon hazırlık.

ADR mode `Accepted`. Backend adapter activation trigger geldiğinde reactivation board issue [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) claim'lenir ve RB-graph-mail-adapter-activation.md takip edilir. **D7 agent/ops read yüzeyi (Mail.Read + AAP) bundan bağımsız ve 2026-06-12 itibarıyla LIVE.**
