# Runbook — Vault Root Token Recovery (Owner-Gated, ADR-0011 credential-write)

> **Belge kodu**: `RB-vault-root-token-recovery`
> **Tarih**: 2026-05-14
> **Sahip**: Halil
> **Sprint**: V2.1 prod-readiness (Ops-A receiver coupling blocker)
> **Codex thread**: `019e27e1` (B primary verdict — owner-gated)
> **Action class**: ADR-0011 §2.3 `credential-read` + `credential-write` (operator domain)

---

## 1. Bağlam

V2.1 Ops-A receiver coupling (Vault `kv/platform/perf-alertmanager` write + ESO policy re-apply) için Vault root token gerek. Session 52 tespit:

- `/home/halil/platform/state/vault-dev/vault-root-token` (test cluster): `vault token lookup-self` → **403 forbidden**
- `vault status` OK (sealed=false, initialized=true)
- Root token revoked/expired veya yanlış instance

**Codex `019e27e1` verdict**:
- (A) Agent autonomous root regenerate: **NO-GO** (root token operator domain, credential-write boundary)
- (B) Owner action: **PRIMARY** (test + prod ayrı maddeler, DR-8/DR-9 disiplini)
- (C) Eski token reuse: **conditional** (owner terminalde dene, agent değil)

Bu runbook owner-terminal recovery recipe sunar.

---

## 2. Owner Action — Test Vault Root Recovery (DR-8 disiplini)

### 2.0 Önce candidate token doğrula (C path)

```bash
# Aday tokenlar:
TEST_CANDIDATES=(
  "$(cat /home/halil/platform/state/vault-dev/vault-root-token 2>/dev/null)"
  "$(python3 -c 'import json; print(json.load(open("/home/halil/platform/state/vault-dev/vault-init.json")).get("root_token",""))' 2>/dev/null)"
)

for CANDIDATE in "${TEST_CANDIDATES[@]}"; do
  [[ -z "$CANDIDATE" ]] && continue
  echo "Trying token prefix: ${CANDIDATE:0:10}..."
  RESULT=$(docker exec -e VAULT_TOKEN="$CANDIDATE" platform-vault-test vault token lookup-self 2>&1)
  if echo "$RESULT" | grep -q "policies"; then
    echo "VALID — kullanılabilir"
    export TEST_ROOT_TOKEN="$CANDIDATE"
    break
  fi
done
```

Eğer biri valid'se §3'e atla. Yoksa devam §2.1.

### 2.1 Emergency root regenerate (B path — generate-root)

```bash
# 0) Doğru instance doğrula
docker exec platform-vault-test vault status

# 1) Önceki abandoned generate-root cancel
docker exec platform-vault-test vault operator generate-root -cancel 2>&1 || true

# 2) OTP üret
OTP=$(docker exec platform-vault-test vault operator generate-root -generate-otp)
echo "OTP captured (length: ${#OTP})"

# 3) Init generate-root with OTP
INIT_OUTPUT=$(docker exec platform-vault-test vault operator generate-root -init -otp="$OTP")
NONCE=$(printf '%s\n' "$INIT_OUTPUT" | awk '/Nonce/ {print $NF}')
echo "Nonce captured (length: ${#NONCE})"

# 4) Unseal key shares ile generate-root submit (Threshold 2 — 2 share gerek)
# Owner kendi shellinde girer; agent transcript'ine yazılmasın:
read -r -s UNSEAL_KEY_1
read -r -s UNSEAL_KEY_2

docker exec platform-vault-test vault operator generate-root -nonce="$NONCE" "$UNSEAL_KEY_1" 2>&1 | head -3
RESULT=$(docker exec platform-vault-test vault operator generate-root -nonce="$NONCE" "$UNSEAL_KEY_2" 2>&1)

ENCODED=$(printf '%s\n' "$RESULT" | awk '/Encoded Token/ {print $NF}')

# 5) Decode emergency root token
TEST_ROOT_TOKEN=$(docker exec platform-vault-test vault operator generate-root -decode="$ENCODED" -otp="$OTP")
echo "Emergency root token generated (length: ${#TEST_ROOT_TOKEN})"

# 6) Verify
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test vault token lookup-self | head -10

# Cleanup şu an YOK — §3 ESO policy + Vault write için kullanılacak
```

---

## 3. Owner Action — Vault Write + Policy Re-apply (V2.1 Ops-A unlock)

```bash
# Önce: §2'de TEST_ROOT_TOKEN alındı

# 1) ESO runtime policy re-apply (perf-alertmanager path eklendi PR #627)
docker exec -i -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  sh -c "cat > /tmp/eso-runtime.hcl" \
  < ~/platform-k8s-gitops/bootstrap/vault-policies/common/eso-runtime.hcl

docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  vault policy write eso-runtime /tmp/eso-runtime.hcl

docker exec platform-vault-test rm /tmp/eso-runtime.hcl

# Verify policy contains perf-alertmanager path
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  vault policy read eso-runtime | grep -A1 "perf-alertmanager"

# 2) Slack webhook URL seed (owner-input, secret hijab)
read -r -s SLACK_PERF_WEBHOOK
[[ "$SLACK_PERF_WEBHOOK" =~ ^https://hooks\.slack\.com/services/ ]] && echo "URL prefix OK" || echo "FAIL — input invalid"

docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  vault kv put kv/platform/perf-alertmanager \
  SLACK_WEBHOOK_URL="$SLACK_PERF_WEBHOOK"

# 3) Verify write
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  vault kv get -format=json kv/platform/perf-alertmanager | \
  jq -r '.data.data.SLACK_WEBHOOK_URL | length'
# Expected: 70-90 (Slack webhook URL length)

# 4) Cleanup — emergency root revoke + env hijab
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  vault token revoke -self

unset TEST_ROOT_TOKEN SLACK_PERF_WEBHOOK OTP NONCE ENCODED RESULT INIT_OUTPUT UNSEAL_KEY_1 UNSEAL_KEY_2
```

---

## 4. Agent autonomous verify chain (post-owner action)

Owner §3'ü tamamladıktan sonra agent:

```bash
# ESO force reconcile + state check
ssh halil@staging-sw 'kubectl --context k3d-test -n monitoring annotate externalsecret \
  perf-alertmanager-secrets force-sync="$(date +%s)" --overwrite

# 1-2 dakika bekle (ESO refresh)
sleep 90

kubectl --context k3d-test -n monitoring get externalsecret \
  perf-alertmanager-secrets -o jsonpath="{.status.conditions[0]}"; echo

# Secret render verify (URL kendisi log'a basılmıyor)
WEBHOOK=$(kubectl --context k3d-test -n monitoring get secret \
  perf-alertmanager-secrets -o jsonpath="{.data.SLACK_WEBHOOK_URL}" 2>/dev/null | base64 -d)
echo "URL length: ${#WEBHOOK}"
[[ -n "$WEBHOOK" ]] && printf "URL fingerprint: %s\n" "$(printf %s "$WEBHOOK" | sha256sum | head -c 16)"
[[ "$WEBHOOK" =~ ^https://hooks\.slack\.com/services/ ]] && echo "Shape: OK" || echo "Shape: FAIL"'
```

---

## 5. Prod Vault Recovery (DR-9 disiplini — AYRI ZAMANLAMA)

Codex iter-4 verdict: "Prod'a aynı anda refleksif root regen yapmayın; prod ExternalSecret/receiver attach zamanı geldiğinde DR-8/DR-9 disiplininde ele alın."

**Prod recovery şartları**:
- (a) Test recovery tamamlandı + ESO test cluster'da `SecretSynced=True`
- (b) Synthetic alert E2E verify test cluster'da PASS (Slack receipt)
- (c) Owner ayrı zamanda prod cluster için aynı recipe (test cluster'la **AYNI ANDA OLMAZ**)
- (d) Prod root token revoke + cleanup zorunlu

Prod recipe test recipe'siyle birebir aynı, sadece:
- Container: `platform-vault-prod`
- Path: `/home/halil/platform/state/vault/...`
- Vault path: `kv/platform/perf-alertmanager` (aynı path; webhook URL test ile aynı veya ayrı kanal — owner tercihi)

---

## 6. Acceptance kriteri

- [ ] Test Vault root token recovered (operator confirmed)
- [ ] Test Vault ESO policy `eso-runtime` perf-alertmanager path read OK
- [ ] Test Vault `kv/platform/perf-alertmanager.SLACK_WEBHOOK_URL` write OK
- [ ] Test cluster ESO `perf-alertmanager-secrets` `SecretSynced=True`
- [ ] Synthetic alert E2E test cluster — Slack receipt verify
- [ ] Prod Vault recovery DR-9 disiplini (ayrı zaman, ayrı onay)
- [ ] Emergency root token revoke + env hijab cleanup

---

## 7. Audit trail

- **Codex thread**: `019e27e1` — B primary verdict (owner-gated)
- **Spike**: PR #582 Ops-A spike Codex `019e267a` AGREE_AFTER_REVISIONS
- **Impl prep**: PR #627 sha `ff102b97` MERGED 2026-05-14T17:00Z
- **Vault discovery**: Session 52 — `vault token lookup-self` 403, root token expired/revoked
- **Cross-AI peer review**: Claude (impl proposed) + Codex (B verdict) consensus

---

## 8. Referanslar

- ADR-0010 §2.5 Vault credential lifecycle (operator domain)
- ADR-0011 §2.3 action taxonomy (credential-write)
- RB-vault-test-dr-rekey.md (DR-8 pattern referansı)
- RB-eso-vault-approle-rotate.md:84 (docker exec stdin pattern)
- V2.1-perf-alert-receiver.md §3.0 (post-recovery ESO + Alertmanager verify)
