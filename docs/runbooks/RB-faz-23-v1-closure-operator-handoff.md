# Faz 23 V1 Closure — Comprehensive Operator Handoff Runbook (2026-05-24)

> **Trigger**: Session 49+ doc-truth-sync sweep (PR #1002-#1013) + H read-only live evidence (PR #1011) saturation noktasında. Agent-actionable doc surface'ler kapatıldı; canonical Faz 23 source-side substantively LIVE (~95%). **Bu runbook v1 closure için operator-bound + external + board + strategic items'ı tek consolidated handoff'a toplar**.
>
> **Format**: Her item için (a) öncelik (b) önkoşul (c) komut/adım dizisi (sanitized) (d) doğrulama (e) rollback (f) doc surface güncellemeleri
>
> **HARD RULE adherence**: Operator-executed; agent-prepared. No Fake Work — runbook executable; raw secret values redacted/placeholder. No state mutation in this runbook (sadece talimat).

---

## §1 — Critical Path Operator Items (M7 V1 Closure için Bloker)

### §1.1 BL-004 + BL-005 + BL-006 + BL-007 — Vault Canonical Patch Chain

**Önkoşul**: Operator'un current Vault root token erişimi var (`/home/halil/platform/state/vault/vault-root-token` agent probesinde rotated/invalid çıktı — operator current token konumunu bilmeli).

**Adım dizisi**:

```bash
# 1. SSH staging-sw + current Vault token tespit
ssh halil@staging-sw
# Operator: current Vault root token konumu /home/halil/platform/state/vault/vault-root-token muhtemelen
# stale. Operator yeniden init/rotate ettiyse current path'i hatırlamalı veya:
docker exec platform-vault-prod cat /vault/file/INIT-RESPONSE.json 2>/dev/null | jq -r .root_token
# veya operator'un kendi notes/Vault initdocs

# 2. Token'ı set + patch komutları
export VAULT_TOKEN=<current_token>
export VAULT_ADDR=http://127.0.0.1:8200

# BL-004 PART A — OpenFGA model_id patch
docker exec -e VAULT_TOKEN=$VAULT_TOKEN -e VAULT_ADDR=$VAULT_ADDR platform-vault-prod \
  vault kv patch kv/platform/openfga model_id=01KS8QE8T1EJ2DF5CRS4VV9YX1

# BL-004 PART B — Orchestrator internal_api_key canonical align
# (currently overlay-overridden via PR #996 to match permission-service value)
# Get permission-service value first:
docker exec -e VAULT_TOKEN=$VAULT_TOKEN -e VAULT_ADDR=$VAULT_ADDR platform-vault-prod \
  vault kv get -field=internal_api_key kv/platform/permission-service
# Apply to notification-orchestrator path:
docker exec -e VAULT_TOKEN=$VAULT_TOKEN -e VAULT_ADDR=$VAULT_ADDR platform-vault-prod \
  vault kv patch kv/platform/notification-orchestrator authz_internal_api_key=<value-from-above>

# 3. ESO reconcile + secret render verify
kubectl --context k3d-test -n platform-test annotate externalsecret \
  notification-orchestrator force-sync="$(date +%s)" --overwrite
kubectl --context k3d-test -n platform-test annotate externalsecret \
  openfga force-sync="$(date +%s)" --overwrite
sleep 10
kubectl --context k3d-test -n platform-test get externalsecret -o wide | grep -E 'notification-orchestrator|openfga'

# 4. Pod env verify (post ESO reconcile)
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s
# Verify env after restart
kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- \
  env | grep '^NOTIFY_AUTHZ_INTERNAL_API_KEY=' | head -1 | wc -c   # should match permission-service value len
```

**Doğrulama (post-patch)**:
1. `vault kv get kv/platform/openfga` → `model_id=01KS8QE8T1EJ2DF5CRS4VV9YX1` ✓
2. ESO `notification-orchestrator` ExternalSecret `Ready=True` `SecretSynced=True`
3. Pod env `NOTIFY_AUTHZ_INTERNAL_API_KEY` orchestrator + `PERMISSION_SERVICE_INTERNAL_API_KEY` permission-service identik (sha256 equal)
4. `/actuator/health` both UP
5. `notify_dispatch_outcome_total{channel="push",status="DELIVERED"}` counter still ≥ 1 (post pod restart counter rolls but new push delivery should work)

### §1.2 BL-005 — Post Vault Canonical Patch: Overlay Override Revert PRs

**Önkoşul**: §1.1 BL-004 başarıyla execute edildi + verify edildi.

```bash
# Open revert PR for PR #995 (test overlay permission-service ERP_OPENFGA_MODEL_ID env override)
cd ~/Documents/platform-k8s-gitops
git checkout main && git pull
git checkout -b revert/pr-995-erp-openfga-model-id-overlay-override
# Revert the JSON patch in kustomize/overlays/test/kustomization.yaml lines that explicitly set
# ERP_OPENFGA_MODEL_ID env on permission-service Deployment
# (rely on Vault-sourced value via ESO + envFrom instead)
# ... edit kustomize/overlays/test/kustomization.yaml accordingly
git commit -m "chore: revert PR #995 overlay override; ERP_OPENFGA_MODEL_ID now from Vault canonical"
gh pr create --title "chore: revert PR #995 overlay override (post Vault canonical patch)" --body "..."

# Open revert PR for PR #996 (orchestrator NOTIFY_AUTHZ_INTERNAL_API_KEY ESO remoteRef redirect)
git checkout main && git pull
git checkout -b revert/pr-996-eso-remoteref-redirect
# Edit kustomize/overlays/test/eso/notify/externalsecret-notify.yaml:
# Restore NOTIFY_AUTHZ_INTERNAL_API_KEY remoteRef back to
# kv/platform/notification-orchestrator.authz_internal_api_key (canonical path)
git commit -m "chore: revert PR #996 ESO remoteRef redirect; canonical Vault path restored"
gh pr create --title "chore: revert PR #996 ESO remoteRef redirect" --body "..."
```

**Cross-AI peer review HARD RULE**: Her revert PR Codex review iter chain'inden geçirilmeli.

### §1.3 BL-006 — Runtime-Artifact Ledger `runtime_selector` Update

**Önkoşul**: §1.1 BL-004 başarıyla execute edildi.

```bash
cd ~/Documents/platform-k8s-gitops
git checkout main && git pull
git checkout -b chore/runtime-artifact-ledger-vault-selector

# Edit runtime-artifacts/openfga-model/a48a49198c70bd3f928bbac2b87ef3fd83903f00691996c04778f892146f0f9c.json
# Change "runtime_selector": null → "runtime_selector": "vault"
# Add "promoted_via_vault_at": "2026-MM-DDTHH:MM:SSZ" timestamp

git commit -m "chore(runtime-artifacts): openfga model promoted via Vault selector (post canonical patch)"
gh pr create --title "chore(runtime-artifacts): OpenFGA model Vault selector promotion" --body "..."
```

### §1.4 BL-007 — `platform-backend/backend/openfga/model.fga` Canonical Update

Agent `a233ba0a6703e6595` paralel olarak bunu yapıyor — Part 1 olarak. Eğer agent bitti AGREE merge ettiyse bu adım atlanır; aksi halde agent çıktısı incelenir.

---

## §2 — Ops Slot Execution (Operator Action)

### §2.1 BL-008 — R9 D43 Drill: Slack Real Webhook + Prod Vault Seed + Helm Upgrade

**Önkoşul**: Slack workspace admin + prod Vault canonical patch yapıldı.

```bash
# 1. Slack workspace: create #alerts-d43-drill channel + incoming-webhook integration
# Webhook URL: https://hooks.slack.com/services/<TEAM>/<CHANNEL>/<TOKEN>

# 2. Seed Vault prod with webhook URL
export VAULT_TOKEN=<current_token>
docker exec -e VAULT_TOKEN=$VAULT_TOKEN -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-prod \
  vault kv patch kv/platform/alertmanager-fallback slack_webhook_url=<webhook-url>

# 3. helm upgrade alertmanager with dual-route config (PR #855 staged config already MERGED)
# Apply prod overlay
kubectl --context k3d-prod -n monitoring apply -k kustomize/overlays/prod/monitoring

# 4. Execute drill — trigger synthetic NotifyServiceAbsent alert (per RB-notification-outage-fallback)
# Inject test alert via Alertmanager API:
curl -X POST http://localhost:9093/api/v2/alerts -H 'Content-Type: application/json' -d '[{
  "labels": {"alertname":"NotifyServiceAbsent","severity":"critical","drill":"true"},
  "annotations": {"summary":"Drill: notification-orchestrator absent simulation"},
  "startsAt": "'"$(date -u +%FT%TZ)"'"
}]'

# 5. Verify dual-receipt:
# - Mailpit SMTP receipt (test cluster) + or test inbox direct fallback
# - Slack #alerts-d43-drill real notification posted

# 6. Update board issues #853 + #854 with drill execution evidence
```

**Doğrulama**: Dual-receipt evidence — SMTP receipt at Mailpit + Slack message in #alerts-d43-drill within 5 min of injection. R9 🟡 partial → 🟢 mitigated.

### §2.2 BL-009 — DKIM Tenant Enable + DNS CNAME Publish (Office 365 Admin + DNS)

**Önkoşul**: Office 365 admin tenant access + DNS registrar admin access.

```
# 1. Office 365 Admin Console (manual):
# - Microsoft 365 Admin Center → Domains → Select acik.com
# - Enable Outbound DKIM signing for acik.com domain
# - Note the 2 CNAME records Microsoft displays:
#   - selector1._domainkey.acik.com → selector1-acik-com._domainkey.<tenant>.onmicrosoft.com
#   - selector2._domainkey.acik.com → selector2-acik-com._domainkey.<tenant>.onmicrosoft.com

# 2. DNS Registrar (manual):
# - Publish both CNAME records
# - Wait for DNS propagation (~30 min)

# 3. Microsoft 365 Admin Center:
# - Click "Enable" on the domain (Microsoft validates CNAMEs)
# - Sign DKIM should turn green

# 4. Verify
dig +short selector1._domainkey.acik.com CNAME
dig +short selector2._domainkey.acik.com CNAME

# 5. Send test email → verify DKIM-Signature header present at recipient
# (use Mailpit dev relay or test ai@acik.com)
```

**Doğrulama**: `dig` returns CNAME values + DKIM signing active in Microsoft 365 + recipient DKIM-Signature header verified.

### §2.3 BL-010 — Keycloak `org_id=default` Claim Setup (Prod Canary Önkoşulu)

**Önkoşul**: Keycloak `platform-kc-prod` admin password.

```bash
# 1. KC admin password — find at standard locations:
# - /home/halil/platform/state/keycloak-prod/admin-pwd (probe earlier showed not at /opt/keycloak)
# - Or docker env: docker inspect platform-kc-prod | grep KC_BOOTSTRAP_ADMIN_PASSWORD
docker inspect platform-kc-prod | grep -E 'KC_BOOTSTRAP_ADMIN' | head -3

# 2. Login as admin to KC prod via kcadm.sh
docker exec -it platform-kc-prod /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master --user admin --password '<KC_ADMIN_PWD>'

# 3. Add hardcoded org_id=default claim to acik realm token mapper
# Per RB-prod-canary-kc-claim-setup runbook:
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh create \
  client-scopes/acik/protocol-mappers/models \
  -r acik \
  -s name=org-id-default \
  -s protocol=openid-connect \
  -s protocolMapper=oidc-hardcoded-claim-mapper \
  -s 'config."claim.name"=org_id' \
  -s 'config."claim.value"=default' \
  -s 'config."access.token.claim"=true' \
  -s 'config."id.token.claim"=true'

# 4. Restart KC realm import OR force token refresh on tester
# 5. Mint test JWT and verify org_id=default claim present
```

**Doğrulama**: New JWT decoded → `org_id=default` claim present. M4 prod canary smoke unblocks.

### §2.4 BL-011 — Post §2.3: Prod SMS Functional Canary Smoke

**Önkoşul**: §2.3 KC org_id=default LIVE + R24 BL-016 Biotekno OTP allowlist hazır (eğer OTP topic test edilecekse).

```bash
# Test persona JWT mint with org_id=default + Subject persona
# Submit SMS intent to notification-orchestrator
curl -X POST https://ai.acik.com/api/v1/notify/intents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "topic_key": "marketing.campaign",
    "channel": "sms",
    "recipient": {"phone": "+905551815564", "subscriberId": "<test>"},
    "payload": {"subject": "M4 prod canary smoke", "body": "Test SMS"}
  }'

# Verify:
# - Pod log: jetsms SOAP ACCEPTED msg_id=jetsms-...
# - notify_dispatch_outcome_total{channel="sms",status="ACCEPTED"} counter
# - DLR polling worker pulls DELIVERED status
# - Real SMS received on +905551815564
```

### §2.5 BL-014 — FBL Mailbox Activation

**Önkoşul**: Office 365 dedicated FBL mailbox (e.g., `fbl@acik.com`) + IMAP credentials.

```bash
# 1. Provision Office 365 mailbox: fbl@acik.com (Microsoft 365 Admin Center)
# 2. Configure IMAP receive: imap.office365.com:993 SSL
# 3. Seed Vault with mailbox credentials:
docker exec -e VAULT_TOKEN=$VAULT_TOKEN -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-prod \
  vault kv patch kv/platform/notification-orchestrator \
    fbl_mailbox_username=fbl@acik.com \
    fbl_mailbox_password=<app-password>

# 4. Enable FblMailboxPollingWorker (uncomment ConfigMap entries per RB-fbl-mailbox-activation)
# 5. Rollout restart notification-orchestrator
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator

# 6. Verify FblMailboxPollingWorker scheduling
kubectl logs deploy/notification-orchestrator | grep -i FblMailboxPollingWorker | head -5
# expect "FblMailboxPollingWorker activated: schedule=PT5M ..."

# 7. Send a test ARF report to fbl@acik.com → verify suppression list entry created
```

### §2.6 BL-015 — Per-Template Grafana DB RO Role

**Önkoşul**: PostgreSQL admin role + Grafana datasource config access.

```bash
# 1. PostgreSQL: create RO role
# (PG location: check kubectl get pod -A | grep postgres or external host instance)
psql -U postgres -h <pg-host> -c "
  CREATE USER grafana_ro WITH PASSWORD '<password>';
  GRANT CONNECT ON DATABASE notify TO grafana_ro;
  GRANT USAGE ON SCHEMA notify TO grafana_ro;
  GRANT SELECT ON ALL TABLES IN SCHEMA notify TO grafana_ro;
  ALTER DEFAULT PRIVILEGES IN SCHEMA notify GRANT SELECT ON TABLES TO grafana_ro;
"

# 2. Vault seed grafana RO password
docker exec -e VAULT_TOKEN=$VAULT_TOKEN -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-prod \
  vault kv patch kv/platform/grafana \
    notify_pg_ro_username=grafana_ro \
    notify_pg_ro_password=<password>

# 3. Configure Grafana datasource (PR #966 staged config; just need credentials seeded)
# kubectl --context k3d-test -n monitoring rollout restart deploy/grafana

# 4. Verify per-template panel loads (T4.3.7 Top 20 panel)
# Open Grafana per-tenant dashboard → per-template panel → should show data
```

---

## §3 — External Provider Items (Out of Operator/Agent Scope)

### §3.1 BL-016 — R24 Biotekno OTP Allowlist (External Provider Provisioning)

**Owner**: Biotekno müşteri temsilcisi + JetSMS provider config

**Adımlar**:
1. Biotekno müşteri temsilcisi ile iletişim → sender ID OTP allowlist provisioning chain
2. JetSMS dashboard'da VFO outbound sender ID için OTP topic provisioning request
3. Karşı taraf provisioning'i complete edip onayladığında VFO routing automatically devreye girer (code side LIVE)
4. Verify: test SMS to auth.mfa-otp topic → actual_channel=VFO audit row + delivered

**ETA**: Provider provisioning chain ~1-2 hafta external lead time.

---

## §4 — Board Acceptance Decisions (User/Board Role)

### §4.1 BL-017 — M3 23.2 Board #755 Final Acceptance

**Önkoşul**: 
- R2 KVKK CLOSED ✓ (Codex `019e5189` 2026-05-23)
- K6 P1 follow-up (BL-001 agent çalışıyor; absorbed olunca acceptance ready)

**Acceptance evidence**: `docs/faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md`

**Board action**: Set issue #755 status → Done; close milestone.

### §4.2 BL-018 — M4 23.3 Board #756 Final Acceptance

**Önkoşul**: 
- M4 prod cutover LIVE ✓ (2026-05-20 sha-6307428)
- BL-011 prod canary smoke (post §2.3 + §3.1)
- DLR terminal evidence

**Acceptance evidence**: `docs/faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md`

**Board action**: BL-011 sonrası issue #756 → Done.

### §4.3 BL-019 — M5 23.5 Board #757 Final Acceptance

**Önkoşul**:
- Source-side LIVE ✓ (M5 23.5 6/6 LIVE)
- BL-003 live cluster runtime evidence (agent `aa3d862bed5a8b408` çalışıyor)

**Acceptance evidence**: BL-003 agent çıktısı PR

**Board action**: BL-003 PR merged sonrası issue #757 → Done.

### §4.4 BL-020 — M6 23.4 Board #758 Acceptance Confirmation

**Önkoşul**: M6a + M6b 6/6 LIVE ✓ (zaten 2026-05-20)

**Board action**: Confirm issue #758 → Done (eğer henüz değilse).

---

## §5 — Strategic Decisions (Kullanıcı Karar Gerek)

### §5.1 BL-021 — 23.7 Push Scope Tanımı

**Karar gereken**: 
- **Seçenek A**: Mobile FCM/APNS dahil edilir → BL-023 Mobile impl (Faz 22.2 dep, ~8-16h) → 23.7 🟡 → 🟢 (M7 v1 closure tam)
- **Seçenek B**: "Browser-only WebPush = 23.7 v1 closure" → 23.7 🟢 (scope-narrowed) + mobile Faz 22.2/Faz 24'e taşınır

**Codex önerisi gerek**: kullanıcı `019e5189` pattern'i ile Codex'e sorabilir veya direkt karar verebilir.

**Etki**: 23.7 → 🟢 transition path; M7 v1 closure timing.

### §5.2 BL-022 — NetGSM Secondary Contract

**Mevcut durum**: 2026-05-23 kullanıcı kararı R1 ⏳ DEFER asset-preserved. JetSMS-only kabul edilen kalıcı işletim durumu.

**Eğer sözleşme imzalanırsa**: R1 ⏳ → reactivation chain devreye girer (Vault NetGSM keys seed → ConfigMap secondary enable → digest bump → failover acceptance test).

**Şu an karar**: NetGSM secondary sözleşme yapılacak mı, yoksa JetSMS-only kalıcı mı?

**Etki**: M4 acceptance şekli (R1 DEFER vs R1 reactivation chain).

---

## §6 — Time-Passive (30-Day Window)

### §6.1 BL-012 — M7 V1 30-Day Prod Observation Window

**Önkoşul**: M7 v1 stable (tüm v1 sub-faz markers 🟢 OR scope-narrowed via §5.1)

**Adımlar**:
1. M7 v1 closure date'i belirle (T-0)
2. T+30 day boyunca prod observation:
   - 25 PrometheusRule alerts inactive (or correctly-pending)
   - DLQ unreplayed counter stable
   - notify_dispatch_outcome_total{status="DELIVERED"} steady growth
   - No regression in audit retention worker
3. T+30 day milestones M7 → 🟢 done; M8 multi-tenant trigger gate açılır

**Calendar**: 30 day from M7 v1 closure date (TBD post strategic + agent work).

---

## §7 — Konsolide Action Checklist (Operator için)

Sıralı execute edilmesi önerilen sequence:

- [ ] §1.1 BL-004 Vault canonical patch (model_id + internal_api_key)
- [ ] §1.2 BL-005 Revert PRs #995 + #996 (post §1.1 verify)
- [ ] §1.3 BL-006 Runtime-artifact ledger Vault selector update
- [ ] §1.4 BL-007 platform-backend model.fga update (agent `a233ba0a6703e6595` paralel; eğer agent bitti merge ettiyse atla)
- [ ] §2.1 BL-008 R9 D43 drill (Slack webhook + Vault seed + helm upgrade + drill execution)
- [ ] §2.2 BL-009 DKIM tenant enable + DNS CNAME publish (Office 365 + DNS admin)
- [ ] §2.3 BL-010 KC org_id=default claim setup (KC admin)
- [ ] §2.4 BL-011 Prod SMS functional canary smoke (post §2.3 + §3.1)
- [ ] §2.5 BL-014 FBL mailbox activation
- [ ] §2.6 BL-015 Per-template Grafana DB RO role
- [ ] §3.1 BL-016 R24 Biotekno OTP (external lead time ~1-2 hafta)
- [ ] §4.1-§4.4 BL-017-020 Board acceptance decisions
- [ ] §5.1 BL-021 23.7 push scope strategic karar
- [ ] §5.2 BL-022 NetGSM contract strategic karar
- [ ] §6.1 BL-012 M7 v1 30-day prod observation window

---

## §8 — Agent Work Parallel Track (No Operator Action Required)

5 background agent şu anda çalışıyor — sonuçları M7 closure'a katkı yapar:

- **Agent #1** (BL-001 K6 backend dev): platform-backend cross-repo sprint; M3 P1 closure
- **Agent #2** (BL-002 Layer-2 OpenFGA enforce): platform-backend cross-repo; 23.1 🟡 → 🟢
- **Agent #3** (BL-003 M5 live runtime evidence): Browser smoke; M5 board #757 acceptance ready
- **Agent #4** (BL-013 T3.1.8 4 workflow test partial): Test cluster smoke
- **Agent #5** (BL-007 + BL-024-027 consolidation): platform-backend model.fga canonical + secondary docs hygiene

Tüm 5 agent cross-AI peer review (provider-different) HARD RULE altında. PR sonuçları geldiğinde merge zinciri agent-driven.

---

## §9 — V1 Closure Trace (Bütünleyici Görünüm)

| Adım | Type | Owner | ETA |
|---|---|---|---|
| Agent #1-#5 PR'ları MERGED | Agent | Agent (Codex AGREE iter) | bu session sonu |
| §1.1-§1.4 Vault canonical chain | Operator | ops | ~1h |
| §2.1 R9 D43 drill | Operator | ops + Slack admin | ~2-4h |
| §2.2 DKIM DNS | Operator | ops + DNS admin | ~30 min + 30 min DNS propagation |
| §2.3 KC org_id setup | Operator | ops + KC admin | ~15-30 min |
| §2.4 Prod SMS canary | Operator + Agent | ops + agent | ~1h |
| §2.5 FBL mailbox | Operator | ops + mailbox admin | ~1-2h |
| §2.6 DB RO role | Operator | ops + PG admin | ~30 min |
| §3.1 Biotekno OTP | External | Biotekno + JetSMS | ~1-2 hafta |
| §4.1-§4.4 Board acceptance | Board | board / user | ~1 hafta |
| §5.1-§5.2 Strategic karar | User | kullanıcı | immediate |
| §6.1 30-day observation | Time | calendar | 30 day from M7 closure |

**Toplam Agent effort**: ~14-30h (bu session 5 paralel agent çalışıyor)
**Toplam Operator effort**: ~6-12h
**External lead time**: ~1-2 hafta (Biotekno) + ~1 hafta (board acceptance)
**Calendar time to M8 trigger**: M7 closure + 30 day window = ~5-6 hafta

---

## §10 — Cross-AI Peer Review

- **Implementer**: Claude (Anthropic) — Session 49+ otonom doc-truth-sync sweep ekipi
- **Reviewer**: Codex (OpenAI) — bu PR review thread'i ayrı açılacak
- **HARD RULE adherence**: No Fake Work (operator-gated items honest carve-out); No Closure Language; Cross-AI provider-different; SSH+sudo+kubectl HARD RULE #7 read-only smoke only; Pre-Production Full Authority (agent credential probe yaptı + gerçek erişim sınırı tespit edildi); secret hygiene (raw values placeholder/redacted).

## Referanslar

- Backlog: `docs/notify/sprint-plan.md` operator queue + risk-register `Next Review` section
- Vault canonical evidence: `docs/faz-23-evidence/2026-05-22-openfga-notification-model-extension.md` §5
- WebPush activation: `docs/runbooks/RB-webpush-activation.md` §3.10 + §3.11
- M3 R2 KVKK closure: `docs/faz-23-evidence/2026-05-21-m3-r2-kvkk-closure-evidence.md` §R2 FINAL CLOSURE
- M4 prod cutover: `docs/faz-23-evidence/2026-05-20-m4-prod-cutover-closure-evidence.md`
- D29 disipllin: `docs/adr/0010-vault-credential-lifecycle-and-dr.md`
- Outage fallback: `docs/runbooks/RB-notification-outage-fallback.md`
- KC prod canary: `docs/runbooks/RB-prod-canary-kc-claim-setup.md`
- FBL mailbox: `docs/runbooks/RB-fbl-mailbox-activation.md`
- Graph mail adapter (deferred): `docs/adr/0024-graph-mail-adapter-defer.md`
- Session 49+ truth-sync chain: PR #1002 + #1003 + #935 + #1005 + #1006 + #1009 + #1011 + #1013
- H read-only live evidence: `docs/faz-23-evidence/2026-05-24-h-live-evidence-resync.md`
