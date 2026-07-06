# RB-fbl-mailbox-activation — M7 T4.3.5 FBL Mailbox Operator Activation

> **Status**: source-ready 2026-05-22 (Codex 019e4edd plan-time + 019e4fc6/019e4ffd post-impl — Anthropic/OpenAI cross-AI provider-different)
>
> **Scope**: Operator chain — Office 365 Postmaster spam-complaint Feedback Loop (FBL) ARF mailbox activation
>
> **Backend**: platform-backend PR #298 (FBL core — ArfReportParser + FblService + V22) + PR #299 (FblMailboxPollingWorker IMAP) MERGED source-side
>
> **Owner**: ops + dev (joint)

## 1. Bağlam

Faz 23.8 M7 T4.3.5 spam-complaint Feedback Loop. SMTP `250 OK` mailbox-edge kabulüdür; recipient inbox'ta "spam" işaretlerse Office 365 Postmaster ARF (Abuse Reporting Format, RFC 5965) raporu üretir. Bu rapor **bir IMAP mailbox'a e-posta olarak gelir — webhook YOK**. `FblMailboxPollingWorker` bu mailbox'ı periyodik poll eder, `FblService` ARF parse edip ilgili recipient'i `email_suppression` listesine `SPAM_COMPLAINT` ile ekler (provider IP-reputation koruma).

**Backend source-side LIVE** (PR #298 + #299):
- `ArfReportParser` (RFC 5965 multipart/report), `FblService` (@Transactional idempotent ingest), `FblFingerprint` (SHA-256), `EmailBounceEvent` dedupe ledger
- `FblMailboxPollingWorker` — `@ConditionalOnProperty(notify.fbl.mailbox.enabled=true)` defer-aware; default OFF
- V22 migration: `email_bounce_event.source` + `email_suppression.last_source` CHECK → ARF_MAILBOX

**Activation = operator chain** (bu runbook): Postmaster enrollment + IMAP mailbox + Vault seed + ESO + ConfigMap enable.

## 2. Önkoşullar (Preflight)

### 2.1 Backend image FBL-inclusive doğrula

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/notification-orchestrator -- \
  bash -c \"echo \\\"SELECT version FROM notify.flyway_schema_history WHERE version='22'\\\" | PGPASSWORD=\\\$SPRING_DATASOURCE_PASSWORD psql -h postgres -U \\\$SPRING_DATASOURCE_USERNAME -d notify_db\""
```

Beklenen: `22` satırı listede (V22 FBL migration applied). Yoksa backend image FBL PR'larını içermiyor → digest bump gerek.

### 2.2 Microsoft 365 Postmaster / JMRP enrollment

Office 365 FBL **JMRP (Junk Mail Reporting Program)** üzerinden gelir. Operator:

1. Microsoft SNDS/JMRP portalına gönderen domain (`acik.com`) kaydı
2. ARF raporlarının yönleneceği **dedicated mailbox** belirle (örn. `fbl@acik.com` veya `postmaster@acik.com` alt-folder)
3. Bu mailbox **yalnız ARF raporları** için kullanılmalı — worker tüm mesajları FBL olarak işler + işlenince siler (delete-after-process)

⚠️ Microsoft FBL coverage sınırlı — Office 365 native FBL tüm complaint'leri kapsamaz. Outlook.com/Hotmail JMRP ayrı kayıt gerektirir.

### 2.3 IMAP erişim + auth modu doğrula (KRİTİK)

> **Codex 019e4ffd MEDIUM**: Exchange Online IMAP **Basic Auth** tenant bazında **deprecated/disabled** olabilir. PR-1 worker yalnız `basic` auth destekler (`notify.fbl.mailbox.auth-mode=basic`; başka değer fail-fast).

Activation öncesi **canlı IMAP AUTH smoke ZORUNLU**:

```bash
# IMAP basic auth tenant'ta açık mı? (operator workstation'dan)
openssl s_client -connect outlook.office365.com:993 -crlf -quiet 2>/dev/null <<'EOF'
a LOGIN fbl@acik.com '<password>'
a LIST "" "*"
a LOGOUT
EOF
```

Beklenen: `a OK LOGIN completed`. Eğer `a NO AUTHENTICATE failed` veya `LOGIN failed` → tenant IMAP Basic Auth kapalı.
- **Basic Auth kapalıysa**: XOAUTH2 gerekir → PR-1 worker desteklemez; XOAUTH2 token akışı ayrı backend PR (notify.fbl.mailbox.auth-mode=xoauth2 future). Bu durumda activation **bu PR ile yapılamaz** — XOAUTH2 PR'ı bekle.
- **Basic Auth açıksa** (veya app-password destekleniyorsa): devam.

> ⚠️ Bu `openssl` smoke **operator workstation'dan** çalışır — notification-orchestrator **pod'un** IMAPS 993'e çıkabildiğini KANITLAMAZ. Test cluster default-deny-egress NetworkPolicy yalnız 587/443 açar; 993 ayrıca açılmalı (§3.0). Pod-context 993 reachability **G5 hard gate**'inde doğrulanır.

## 3. Operator Activation Chain (sequential — gate geçmeden sonraki adım YOK)

### 3.0 NetworkPolicy — pod IMAPS 993 egress allowlist (KRİTİK — Codex 019e500c BLOCKER)

Test cluster `kustomize/overlays/test/netpol-notification-egress-mail-providers.yaml` default-deny-egress bağlamında çalışır; mevcut allowlist yalnız **587 (SMTP)** + **443 (HTTPS)** açar. IMAPS **993 KAPALI** — FBL mailbox poll notification-orchestrator pod'undan dışarı çıkamaz (worker `connectStore()` connect timeout ile fail eder).

`netpol-notification-egress-mail-providers.yaml` notification-orchestrator egress kuralının `ports` listesine 993 ekle:

```yaml
        - protocol: TCP
          port: 993   # IMAPS — FBL mailbox poll (Office 365 outlook.office365.com)
```

PR aç + Codex review + merge + cluster apply. Pod-context doğrulama **G5 hard gate**'inde (TCP 993 reachability notification-orchestrator pod'undan).

⚠️ **Prod overlay** (`kustomize/overlays/prod/netpol-notification-egress-mail-providers.yaml`) 993 egress'i bu adımda EKLENMEZ — prod FBL activation test 72h soak sonrası ayrı prod slot.

### 3.1 IMAP mailbox credentials hazırla

- host: `outlook.office365.com` (Office 365)
- port: `993` (IMAPS)
- username: FBL mailbox adresi (örn. `fbl@acik.com`)
- password: mailbox şifresi veya **app password** (MFA aktifse app password gerek)
- folder: `INBOX` (default)

### 3.2 Vault seed (test cluster)

```bash
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator \
    fbl_mailbox_host='outlook.office365.com' \
    fbl_mailbox_username='fbl@acik.com' \
    fbl_mailbox_password='<app-password>'
```

Doğrulama (PII-safe — password value terminale basılmaz):

```bash
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  sh -c 'vault kv get -mount=kv -format=json platform/notification-orchestrator \
    | jq -e ".data.data | has(\"fbl_mailbox_host\") and has(\"fbl_mailbox_username\") and has(\"fbl_mailbox_password\")"'
```

Beklenen: `true`.

### 3.3 ExternalSecret 3 entry uncomment (SADECE test overlay)

`kustomize/overlays/test/eso/notify/externalsecret-notify.yaml` içine WebPush/Graph defer-aware pattern'i izleyerek 3 remoteRef entry ekle (uncomment):

```yaml
- secretKey: NOTIFY_FBL_MAILBOX_HOST
  remoteRef:
    key: kv/platform/notification-orchestrator
    property: fbl_mailbox_host
- secretKey: NOTIFY_FBL_MAILBOX_USERNAME
  remoteRef:
    key: kv/platform/notification-orchestrator
    property: fbl_mailbox_username
- secretKey: NOTIFY_FBL_MAILBOX_PASSWORD
  remoteRef:
    key: kv/platform/notification-orchestrator
    property: fbl_mailbox_password
```

⚠️ Prod overlay bu PR'da uncomment EDİLMEZ — prod Vault FBL seed + 72h test soak sonrası ayrı prod activation slot.

### 3.4 Test overlay ConfigMap patch (enabled=true)

`kustomize/overlays/test/kustomization.yaml` `patches` bölümüne (ADR-0023 annotation bump pattern):

```yaml
- target:
    kind: ConfigMap
    name: notification-orchestrator-config
  patch: |-
    - op: add
      path: /data/NOTIFY_FBL_MAILBOX_ENABLED
      value: "true"
    - op: add
      path: /data/NOTIFY_FBL_MAILBOX_FOLDER
      value: "INBOX"
    - op: add
      path: /data/NOTIFY_FBL_MAILBOX_PORT
      value: "993"
- target:
    kind: Deployment
    name: notification-orchestrator
  patch: |-
    - op: add
      path: /spec/template/metadata/annotations/notify-fbl-activated-at
      value: "2026-05-22T00:00Z"
```

### 3.5 PR + Codex review + merge + cluster apply

```bash
git checkout -b feat-fbl-mailbox-activation-test-overlay
# ESO uncomment + ConfigMap patch commit
gh pr create --base main --title "feat(notify-23.8): FBL mailbox activation test overlay"
# CI yeşil + Codex AGREE → squash merge
ssh halil@staging-sw "cd /home/halil/platform-k8s-gitops && git pull origin main --quiet && \
  kubectl --context k3d-test -n platform-test apply -k kustomize/overlays/test 2>&1 | tail -5 && \
  kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s"
```

## 4. Hard Verification Gates

| Gate | Komut | Beklenen |
|---|---|---|
| **G1 ESO Ready** | `kubectl -n platform-test get externalsecret notification-orchestrator-secrets -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'` | `True` |
| **G2 Secret keys** | `kubectl -n platform-test get secret notification-orchestrator-secrets -o json \| jq -e '.data \| has("NOTIFY_FBL_MAILBOX_HOST") and has("NOTIFY_FBL_MAILBOX_PASSWORD")'` | `true` |
| **G3 Worker bean aktif** | `kubectl -n platform-test logs deploy/notification-orchestrator \| grep "FblMailboxPollingWorker activated"` | satır döner (authMode=basic, bounded timeout) |
| **G4 Pod env** | `kubectl -n platform-test exec deploy/notification-orchestrator -- env \| grep '^NOTIFY_FBL_MAILBOX_ENABLED='` | `=true` |
| **G5 Pod → IMAPS 993 reachability** | `kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- bash -c 'timeout 8 bash -c "cat < /dev/null > /dev/tcp/outlook.office365.com/993" && echo TCP_OK \|\| echo TCP_FAIL'` | `TCP_OK` — pod IMAPS 993 egress açık (§3.0 NetworkPolicy uygulandı). `TCP_FAIL` → §3.0 eksik/yanlış |
| **G6 End-to-end ARF smoke** | §5 ARF smoke ZORUNLU — boş mailbox pozitif poll kanıtı ÜRETMEZ (worker yalnız `processed>0` iken `cycle: processed=` log'lar; başarılı poll'un boş-mailbox success path'i sessiz). Test ARF seed → `grep "FBL mailbox message processed"` + email_bounce_event + email_suppression + metrics 5 kanıt birlikte | §5 ZORUNLU; G3-G5 arası log'da `cycle error` YOK (negative gate — tek başına acceptance DEĞİL) |

## 5. Smoke — End-to-End FBL

1. **Test ARF mesajı**: FBL mailbox'a RFC 5965 formatında bir ARF abuse report e-postası gönder (veya gerçek bir complaint bekle). Mesaj `multipart/report; report-type="feedback-report"` + `message/feedback-report` part (Feedback-Type: abuse) + original-message part (Message-ID matching a known `notification_delivery.provider_msg_id`).
2. **Worker poll** (≤ 2 dk — poll-delay-ms default 120s) → `FblService.ingest` çağrılır.
3. **Doğrulama**:
   ```bash
   # email_bounce_event ledger satırı oluştu mu?
   kubectl -n platform-test exec deploy/notification-orchestrator -- bash -c \
     "echo \"SELECT source,classification FROM notify.email_bounce_event WHERE source='ARF_MAILBOX' ORDER BY received_at DESC LIMIT 1\" | PGPASSWORD=\$SPRING_DATASOURCE_PASSWORD psql -h postgres -U \$SPRING_DATASOURCE_USERNAME -d notify_db"
   # email_suppression SPAM_COMPLAINT satırı?
   kubectl -n platform-test exec deploy/notification-orchestrator -- bash -c \
     "echo \"SELECT reason,last_source FROM notify.email_suppression WHERE reason='SPAM_COMPLAINT' ORDER BY updated_at DESC LIMIT 1\" | ..."
   ```
   Beklenen: `email_bounce_event` source=ARF_MAILBOX classification=SPAM_COMPLAINT; `email_suppression` reason=SPAM_COMPLAINT last_source=ARF_MAILBOX.
4. **Metrics**: `notify_fbl_received_total{outcome="suppressed"}` + `notify_fbl_suppressed_total{org_id=...}` Prometheus'ta artmış.
5. **Mailbox temiz**: işlenen mesaj IMAP folder'dan silinmiş (delete-after-process).

## 6. Rollback

```bash
# ConfigMap NOTIFY_FBL_MAILBOX_ENABLED=false (worker bean @ConditionalOnProperty → bean oluşmaz)
# veya overlay patch revert + apply
# ESO 3 entry comment-out (uncomment'i geri al)
# Worker durur; mevcut email_suppression satırları KORUNUR (suppression veri kaybı yok)
```

## 7. Multi-Pod Notu

İki pod aynı mailbox'ı poll ederse `FblService` idempotency (`email_bounce_event` unique `event_fingerprint` + `INSERT ON CONFLICT DO NOTHING`) double-process'i emer — ikinci ingest `duplicate` metric-only. IMAP-level lock gerekmez. Yine de tek-replica ops postürü daha temiz (gereksiz duplicate load/log azaltır).

## 8. Çapraz-referans

- Codex threads `019e4edd` (plan-time) + `019e4fc6` (FBL core impl) + `019e4ffd` (mailbox worker impl)
- platform-backend PR #298 (FBL core) + #299 (FblMailboxPollingWorker)
- V22 migration (`V22__notify_23_8_fbl_sources.sql`)
- T4.3.b email bounce loop (V17 `email_suppression` + `email_bounce_event`)
- ADR-0024 + RB-graph-mail-adapter-activation.md (defer-aware ESO pattern precedent)
- sprint-plan.md T4.3.5 row
