# RB — GPP-2 Webhook Phase Rollout (Operator Checklist)

> **Issue**: Halildeu/platform-k8s-gitops#937 (closed — hosting phase done) → webhook phase tracking
> **Authority**: ao-kernel SSOT `.claude/plans/gpp_status.v1.json` (HEAD `e0be6e8`, `exit_decision = internal_gate_host_health_probe_collected_webhook_config_not_collected_no_support_widening`)
> **Codex thread**: `019e4a10-0fd5-7ff3-9601-80f56a9c8e81` (Decision 2 AGREE_A — two GitHub Apps routing model)
> **Status**: ACTIVE — operator-bound; agent observation + acceptance probes only

## Tetik

GPP-2 hosting phase tamamlandı (PR'lar: platform-k8s-gitops#938 + #942, ao-kernel#569 + #570 + #571). Public HTTPS health evidence collected. **GPP-2 overall hâlâ `blocked`**; webhook config + dry-run check-run + branch protection cutover remaining gates.

Bu runbook AGREE_A locked sequencing (operator karar değil, Codex thread'in 9-adımlı sıralaması) takip eder; **adımları atlamak veya paralel yapmak YASAK** (drift önleme).

---

## Hard stops

Bu runbook'un hiçbir adımında YAPILMAZ:

- Secret değeri (VAULT_TOKEN, GitHub App private key PEM, webhook secret) chat/log/repo/issue/PR'a yazma
- `VAULT_TOKEN`, PEM, ya da webhook secret değerini `echo`/`printf`/`cat`/`grep` ile terminale veya log'a basma
- `set -x` / `bash -x` / `bash -v` ile debug mode'da Vault komutlarını çalıştırma (token + value tracing açılır)
- `.env` dosyasını `cat`/`sed -n`/`grep VAULT_TOKEN` ile basma (her satır çoklu secret içeriyor olabilir)
- GitHub App private key PEM dosyasını shell argument olarak veya HEREDOC ile inline geçirme (file/stdin pattern zorunlu)
- Live adapter execution
- Support widening
- Production platform claim
- Branch protection cutover (Adım 9'a kadar)
- Admin bypass (`--admin`, "Merge without waiting for requirements") (HARD RULE — Admin Merge YASAK)
- Webhook URL config'i public health evidence collected olmadan

---

## Sıralı adımlar

### Step 1 — İki GitHub App oluştur

**Operator** (manual GitHub UI):

- App #1: **policy** (deployment-protection callback)
- App #2: **release-gate** (check-run posting)

Her App için config:

| Field | policy | release-gate |
|---|---|---|
| Name | `ao-kernel-live-adapter-gate-policy` (örnek) | `ao-release-gate` (örnek) |
| Webhook URL | (Step 6'da set) | (Step 6'da set) |
| Webhook secret | (Step 6'da generate + Vault seed) | (Step 6'da generate + Vault seed) |
| Permissions: Deployments | Read + Write | — |
| Permissions: Pull requests | Read | Read + Write |
| Permissions: Checks | — | Read + Write |
| Permissions: Contents | Read | Read |
| Subscribe to events | `deployment_protection_rule` | `pull_request`, `pull_request_review` |
| Install on | `Halildeu/*` (or specific repos) | `Halildeu/*` (or specific repos) |

**Agent acceptance**: Operator iletir → numeric App ID'leri (public-safe, chat'te paylaşılabilir):

- `AO_POLICY_GITHUB_APP_ID=<numeric>`
- `AO_RELEASE_GATE_GITHUB_APP_ID=<numeric>`

App private key PEM dosyalarını **download et + lokal'de tut**; bir sonraki adımda Vault'a seed edilecek.

### Step 2 — Vault PEM seed (real, no placeholder)

**Operator** (staging-sw):

```bash
# Read-only — check existing placeholder is replaceable
TOKEN=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)

# Seed policy App PEM (operator pipes PEM file; never paste)
docker exec -i -e VAULT_TOKEN=$TOKEN platform-vault-prod \
  vault kv put -mount=secret gpp2/github/policy-private-key-pem \
  pem=@- < /local/path/to/policy-app-private-key.pem

# Seed release-gate App PEM
docker exec -i -e VAULT_TOKEN=$TOKEN platform-vault-prod \
  vault kv put -mount=secret gpp2/github/release-gate-private-key-pem \
  pem=@- < /local/path/to/release-gate-app-private-key.pem

# Verify metadata only (no values printed)
for p in gpp2/github/policy-private-key-pem gpp2/github/release-gate-private-key-pem; do
  docker exec -e VAULT_TOKEN=$TOKEN platform-vault-prod \
    vault kv metadata get -mount=secret $p | grep current_version
done
```

**Agent acceptance**:
- 2 path version >= 1 (metadata-only verify)
- Eski `gpp2/github/private-key-pem` placeholder path durabilir (backward-compat fallback için)

### Step 3 — Live `.env` per-service form

**Operator** (staging-sw):

```bash
# Edit /home/halil/platform-k8s-gitops/host-compose/ao-gate/.env
# Add (or replace) these per-service keys:
AO_POLICY_GITHUB_APP_ID=<policy-app-id-from-step-1>
AO_POLICY_GITHUB_APP_PRIVATE_KEY_PEM_ID=gpp2/github/policy-private-key-pem
AO_RELEASE_GATE_GITHUB_APP_ID=<release-gate-app-id-from-step-1>
AO_RELEASE_GATE_GITHUB_APP_PRIVATE_KEY_PEM_ID=gpp2/github/release-gate-private-key-pem

# (Eski legacy AO_GITHUB_APP_ID + AO_GITHUB_APP_PRIVATE_KEY_PEM_ID
# çıkarılabilir veya commented-out olarak korunabilir — fallback değil
# active path artık per-service)

chmod 600 /home/halil/platform-k8s-gitops/host-compose/ao-gate/.env
```

**Agent acceptance** (chat'te değer paylaşmadan):
```bash
ssh halil@staging-sw "grep -c '^AO_POLICY_GITHUB_APP_ID=' /home/halil/platform-k8s-gitops/host-compose/ao-gate/.env"
# expected: 1
ssh halil@staging-sw "grep -c '^AO_RELEASE_GATE_GITHUB_APP_ID=' /home/halil/platform-k8s-gitops/host-compose/ao-gate/.env"
# expected: 1
ssh halil@staging-sw "stat -c '%a' /home/halil/platform-k8s-gitops/host-compose/ao-gate/.env"
# expected: 600
```

### Step 4 — Container recreate + per-service env verify

```bash
ssh halil@staging-sw "cd /home/halil/platform-k8s-gitops/host-compose/ao-gate && \
  docker compose --env-file .env up -d --force-recreate --wait --wait-timeout 180"
```

**Agent acceptance**:
```bash
# Both containers Healthy
ssh halil@staging-sw "docker ps --filter 'name=ao-gate-' --format '{{.Names}}\t{{.Status}}'"

# Per-service App ID picked up (verify each container sees its own App ID)
ssh halil@staging-sw "docker exec ao-gate-policy env | grep AO_GITHUB_APP_ID"
ssh halil@staging-sw "docker exec ao-gate-release env | grep AO_GITHUB_APP_ID"
# Expected: policy container shows policy app ID; release container shows release-gate app ID
# (Both should differ; if same → fallback to legacy shared env triggered → fix .env)
```

### Step 5 — Health re-verify (same as Step 4 of original hosting phase)

```bash
# Local
curl -fsS http://127.0.0.1:18081/healthz | jq -e '.program_id == "GPP-2q"'
curl -fsS http://127.0.0.1:18082/healthz | jq -e '.program_id == "GPP-2w"'

# Public
curl -sk https://testai.acik.com/ao-gate/policy/healthz | jq -e '.program_id == "GPP-2q"'
curl -sk https://testai.acik.com/ao-gate/release-gate/healthz | jq -e '.program_id == "GPP-2w"'
```

**Agent acceptance**: 4/4 PASS.

**Stop condition**: Eğer healthz fail olursa, **Step 6'ya geçme** — gerçek PEM Vault'a seed edildikten sonra container restart sırasında secret resolve fail olabilir (PEM format yanlış, App ID Vault path uyumsuzluk vb.). Log redact ile teşhis:
```bash
ssh halil@staging-sw "docker logs ao-gate-policy --tail 50 2>&1 | grep -iE 'error|fail|vault' | head -10"
```

### Step 6 — GitHub App webhook URL configure et

**Operator** (manual GitHub App settings):

- policy App webhook URL: `https://testai.acik.com/ao-gate/github/deployment-protection`
- release-gate App webhook URL: `https://testai.acik.com/ao-gate/github/ao-release-gate`

Her App için webhook secret:
1. Yeni webhook secret üret — **operator-side, GitHub UI üretmez**. Tek
   doğru kaynak `openssl rand -hex 32`; aynı string hem GitHub App
   Webhook Secret UI alanına yapıştırılacak hem Vault'a seed edilecek.
   UI'nın "kendi üretmesi" diye bir pattern yok — boş bırakılırsa
   GitHub HMAC signing yapmaz ve delivery signature verify fail eder.
2. GitHub App settings → Webhook Secret alanına yapıştır (tek değer)
3. Aynı değeri Vault'a seed. Secret değerini komut satırı argümanı olarak
   yazma; process list, shell history veya terminal log'una sızmaması için
   stdin/temp-file pattern kullan:
   ```bash
   set +x
   umask 077

   POLICY_WEBHOOK_SECRET_FILE="$(mktemp)"
   RELEASE_GATE_WEBHOOK_SECRET_FILE="$(mktemp)"
   trap 'rm -f "$POLICY_WEBHOOK_SECRET_FILE" "$RELEASE_GATE_WEBHOOK_SECRET_FILE"' EXIT

   openssl rand -hex 32 > "$POLICY_WEBHOOK_SECRET_FILE"
   openssl rand -hex 32 > "$RELEASE_GATE_WEBHOOK_SECRET_FILE"

   # Paste the policy file content into the policy GitHub App Webhook Secret UI.
   # Paste the release-gate file content into the release-gate GitHub App Webhook Secret UI.
   # Do not paste either value into chat, logs, PRs, issues, or repo files.

   docker exec -i -e VAULT_TOKEN="$TOKEN" platform-vault-prod sh -ceu '
     tmp="$(mktemp)"
     trap "rm -f \"$tmp\"" EXIT
     cat > "$tmp"
     vault kv put -mount=secret gpp2/policy/webhook-secret value=@"$tmp"
   ' < "$POLICY_WEBHOOK_SECRET_FILE"

   docker exec -i -e VAULT_TOKEN="$TOKEN" platform-vault-prod sh -ceu '
     tmp="$(mktemp)"
     trap "rm -f \"$tmp\"" EXIT
     cat > "$tmp"
     vault kv put -mount=secret gpp2/release-gate/webhook-secret value=@"$tmp"
   ' < "$RELEASE_GATE_WEBHOOK_SECRET_FILE"
   ```

**Vault path version artar** (zaten placeholder vardı; bu replace).

Container restart gerekmez — secret-id .env'de aynı path; runtime her request'te Vault'tan çeker.

### Step 7 — Webhook delivery evidence

**Operator** (GitHub UI):
- GitHub App → Advanced → Recent Deliveries → tetikle bir ping/test event
- HTTP response 200/2xx görmeli; secret signature verify pass

**Agent acceptance** (no live adapter execution):
```bash
# Container log redacted check — sadece "received webhook" satırları
ssh halil@staging-sw "docker logs ao-gate-policy --since 5m 2>&1 | grep -iE 'webhook|callback' | grep -v -i 'secret\|token\|pem' | head -10"
ssh halil@staging-sw "docker logs ao-gate-release --since 5m 2>&1 | grep -iE 'webhook|check.run' | grep -v -i 'secret\|token\|pem' | head -10"
```

Evidence artifact: `docs/evidence/ao-gate/github-app-webhook-config.v1.md` (operator yazar, secret value içermez)

### Step 8 — Real PR dry-run check-run evidence

**Operator** (test PR):
- Halildeu/ao-kernel veya benzeri repo'da test PR aç
- release-gate App PR event alır → check-run posts (dry-run, branch protection required değil)
- Check-run name + status visible on PR page

**Agent acceptance**:
- GitHub PR page'inde "ao-release-gate" check-run görünür
- Status: success/failure/neutral (decision logic'e göre)
- Evidence artifact: `docs/evidence/ao-gate/ao-release-gate-dry-run-pr.v1.md` (PR number + commit SHA + check-run state)

### Step 9 — Branch protection cutover (en son)

**Operator** (GitHub Settings):
- `Halildeu/<target-repo>` Settings → Branches → main → Edit protection
- Required status checks → Add: `ao-release-gate`
- Save

**Agent acceptance**:
- Required check listesinde `ao-release-gate` var
- Bir sonraki PR merge attempt'te check-run pass olmadıkça merge blocked
- Admin bypass YASAK (HARD RULE — Admin Merge YASAK + GPP program PRs)

**Evidence artifact**: `docs/evidence/ao-gate/ao-release-gate-required-check-cutover.v1.md`

### Step 10 — GPP-2 closeout

**Operator + Agent** (ao-kernel PR):
- `.claude/plans/gpp_status.v1.json` update:
  - `current_wp.status: blocked → completed` (eğer tüm gates evidence-backed)
  - `current_wp.exit_decision` final value (Codex consultation gerek)
  - `completed_wps[]`'a yeni audit row (AO-GATE-8 closeout)
  - `pending_external_actions[]` boşalt (6 items resolved)
  - `live_adapter_execution_allowed: false` (still)
  - `support_widening_allowed: false` (still)
  - `production_platform_claim_allowed: false` (still)

- Cross-AI peer review zorunlu (same Codex thread `019e4a10`)
- Same branch protection bypass pattern (temp relax → merge → restore)

---

## Rollback

Step bazlı rollback:

| Step fail | Rollback |
|---|---|
| Step 4 (compose up fail) | `.env` revert + restart |
| Step 5 (healthz fail) | Container log diagnose (secret resolve / App ID format) → fix |
| Step 6 (webhook 5xx) | GitHub App webhook config gevşet (e.g. Active=false) → diagnose |
| Step 7 (no delivery) | GitHub App "Recent Deliveries" retry, network/firewall check |
| Step 8 (no check-run) | release-gate App permissions verify (Checks=Write) |
| Step 9 (branch protection regression) | Settings → Edit protection → Remove `ao-release-gate` required check |

**Hosting layer rollback** (Step 4-5 ile sınırlı):
- Eski single-App fallback: `.env`'de per-service env'leri sil, legacy `AO_GITHUB_APP_ID` set et → fallback chain devreye girer → compose recreate

---

## Constraints (HARD)

- Bu runbook'un hiçbir adımında secret value chat/log/repo/issue/PR'a yazılmaz
- Step 9 (branch protection cutover) Step 8 (dry-run check-run evidence) **olmadan** yapılmaz
- Step 10 (GPP-2 closeout) Step 9 **olmadan** yapılmaz
- Admin bypass YASAK
- live_adapter_execution=false korunur
- support_widening=false + production_platform_claim=false korunur

---

## Tracked by

- Issue: closed Halildeu/platform-k8s-gitops#937 (hosting phase)
- ao-kernel SSOT: `.claude/plans/gpp_status.v1.json` HEAD `e0be6e8`
- Roadmap doc: Halildeu/ao-kernel `.claude/plans/AO-GATE-ROADMAP-TODO.md` (PR #571)
- Codex thread: `019e4a10-0fd5-7ff3-9601-80f56a9c8e81`
