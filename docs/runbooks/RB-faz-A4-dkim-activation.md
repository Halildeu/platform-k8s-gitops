# Runbook — Faz 23.A4 DKIM Activation (Prod Profile)

> **Owner**: ops + DNS operator
> **Sprint**: M4 prod cutover unblock (Codex thread `019e4514` chain)
> **Trigger**: PR #911 (M4 prod cutover) sha-6ed593e ProductionConfigValidator
> startup-fail (`notify.dkim.enabled=false`); revert PR #912 → DKIM activation
> atomic prereq sprint (this PR)
> **Codex verdict**: AGREE — atomic DKIM activation PR + RE-ATTEMPT M4 ayrı sprint

---

## 1. Bağlam

Yeni notification-orchestrator image (sha-6ed593e, PR #151 DKIM + PR-A3.1.1
JetSMS context routing) `ProductionConfigValidator.validateDkim()` strict
gate ile prod profile'da `notify.dkim.enabled=true` + selector + domain +
private-key-pem zorunlu kılıyor. Prod overlay'de hâlâ `NOTIFY_DKIM_ENABLED=false`
olduğu için yeni image deploy edildiğinde pod startup crash:

```
Production config validation FAILED (1 error(s)):
  - notify.dkim.enabled=false — production must enable app-side DKIM
    (R3 mitigation: outbound mail integrity + spam folder defense).
```

Bu runbook DKIM activation 5-step prereq sequence'i tanımlar.

## 2. Tamamlanan adımlar (this PR)

### Step 2 — DKIM key generation ✅

Agent staging-sw'de 2026-05-20T18:45Z generated:

```bash
WORKDIR=$(mktemp -d)
chmod 700 $WORKDIR
cd $WORKDIR
openssl genrsa -out dkim-prod.pem 2048
openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt \
  -in dkim-prod.pem -out dkim-prod-pkcs8.pem
# Public key extracted for DNS TXT
PUBKEY=$(openssl rsa -in dkim-prod.pem -pubout -outform PEM | sed -e '1d;$d' | tr -d '\n')
```

### Step 3 — Vault prod seed ✅

```bash
cat dkim-prod-pkcs8.pem | docker exec -i -e VAULT_TOKEN=$BS_ROOT \
  platform-vault-prod vault kv patch \
  kv/platform/notification-orchestrator dkim_private_key_pem=-
# Verified: version 8, dkim_private_key_pem key length=1704
# Cleanup: rm -rf $WORKDIR (no plaintext residue)
```

Kanıt:

```bash
docker exec -e VAULT_TOKEN=$BS_ROOT platform-vault-prod \
  vault kv get -format=json kv/platform/notification-orchestrator \
  | jq -r '.data.data | keys[]' | grep dkim
# Output: dkim_private_key_pem
```

### Step 4 — ESO Secret render verify (post-merge)

```bash
kubectl --context k3d-prod -n platform-prod annotate externalsecret \
  notification-orchestrator-secrets force-sync="$(date +%s)" --overwrite
kubectl --context k3d-prod -n platform-prod get secret \
  notification-orchestrator-secrets -o json \
  | jq '.data | keys[] | select(. == "NOTIFY_DKIM_PRIVATE_KEY_PEM")'
# Expected: "NOTIFY_DKIM_PRIVATE_KEY_PEM"
# DO NOT decode base64 — key-only verify
```

## 3. Operator action — DNS TXT publish (this runbook's user prereq)

### DNS TXT record (acik.com domain DNS provider panel)

```text
Hostname:  acik2026._domainkey.acik.com
Type:      TXT
Value:     v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAiY1HB6lKDB7E+dN90nKCHIhWqXZvfKz/MKKfCdn01oHwiVj1ck2dcJ8EWxoJK9mJOA8YYaSv08mkJoOs4aHmZbCrskZsG+kvXDMPFCzrvC3UVXFHgZJHzMbho7QTPOarR9zWrq68RAQFNCGIo1poaYm4Ycv/Rhu473ZfnhkeNlzGoH0pPH+RdWMOi2oxp+Ydf+Oi1VFbw2uunhYxKl8qvMd4Xym8JaPDeqs5EAz6TzGMTMXXE+1ivWZ+HB8aIuoCvOXoEb2c9EEP5qW4vUjFfRvfu5Um7fdY5YjOHSTpL/vh7bldfu2CmWI3MFZL6FCvKEUK+8YPfu//DnBFJ0w4vQIDAQAB
TTL:       3600 (1 hour)
```

> **NOT**: Public key (392 char base64) Vault'taki private key'in karşılığı.
> Eğer key rotation gerekirse: Vault'a yeni key seed + ESO sync + DNS TXT update.

### Propagation verify

```bash
dig +short TXT acik2026._domainkey.acik.com
# Beklenen: "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAA..." (yukarıdaki değer)
# Propagation süresi: TTL'e bağlı (3600s = 1 saat); DNS provider'a göre değişebilir
```

> ⚠️ **DNS TXT 255-char chunking** (Codex iter-1 P2 absorb): DKIM `p=`
> base64 değeri 392 char; DNS TXT RFC 1035 §3.3.14 single character-string
> limiti 255 char. Bazı DNS provider panelleri otomatik split eder
> (iki quoted chunk), bazıları etmez. Provider panelinde:
>
> 1. Auto-split yapan provider (Cloudflare, Route53, Google Domains): tek
>    value field'a tam değer gir — provider arka planda chunk eder
> 2. Manuel chunking gereken provider: iki quoted chunk olarak gir:
>    ```
>    "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAiY1HB6lKDB7E+dN90nKCHIhWqXZvfKz/MKKfCdn01oHwiVj1ck2dcJ8EWxoJK9mJOA8YYaSv08mkJoOs4aHmZbCrskZsG+kvXDMPFCzrvC3UVXFHgZJHzMbho7QTPOarR9zWrq68RAQFNCGIo1poaYm4Ycv/Rhu473ZfnhkeNlzGoH0pPH+RdWMOi2oxp+Ydf+Oi1VFbw2uunhYxKl8qvMd4Xym8" "JaPDeqs5EAz6TzGMTMXXE+1ivWZ+HB8aIuoCvOXoEb2c9EEP5qW4vUjFfRvfu5Um7fdY5YjOHSTpL/vh7bldfu2CmWI3MFZL6FCvKEUK+8YPfu//DnBFJ0w4vQIDAQAB"
>    ```
>
> Verification: `dig +short TXT acik2026._domainkey.acik.com` çıktısında
> concat edilen `p=` değeri birebir 392 char public key ile eşleşmeli.

## 4. Bu PR (kustomize patches)

### kustomize/overlays/prod/kustomization.yaml

1. Image digest: sha-70491543 → sha-6ed593e (sha256:30b0bf658dcd...)
2. ConfigMap NOTIFY_DKIM_ENABLED: "false" → "true"
3. Rollout annotation: `mail.acik.com/dkim-activation: a4-prod-2026-05-20-sha-6ed593e`

### kustomize/overlays/prod/eso/notify/externalsecret-notify.yaml

ESO `NOTIFY_DKIM_PRIVATE_KEY_PEM` secretKey reference **zaten aktif** (line
208-211); bu PR ESO manifest değiştirmiyor (Codex iter-1 P2 absorb: clarification).

### kustomize/overlays/prod/netpol-notification-egress-smtp.yaml (NEW)

Minimal SMTP 587 egress (DKIM signer enabled outbound mail için). Default-deny
+ base host-bridge (5432/8080/8200) port 587 kapsamıyor → outbound DKIM smoke
fail. Selector triple-label (Codex 019e15ee pattern).

JetSMS 443 + Graph 443 ayrı M4 RE-ATTEMPT PR scope; bu PR DKIM activation atomic.

## 5. Acceptance gates

### Pre-merge (this PR)

- [x] DKIM PKCS#8 RSA 2048 key generated (staging-sw temp dir, cleanup verified)
- [x] Vault prod seed (kv/platform/notification-orchestrator, version 8, length=1704)
- [ ] DNS TXT acik2026._domainkey.acik.com published + propagated (`dig +short TXT` confirms)
- [x] Kustomize build sanity (4411 lines)
- [ ] Codex cross-AI peer review (this PR)
- [ ] CI all green

### Merge + apply (operator strategic karar)

- [ ] PR merge approval (kullanıcı)
- [ ] `kubectl apply -k kustomize/overlays/prod/eso/notify` (ESO yaml updates)
- [ ] `kubectl apply -k kustomize/overlays/prod` (ConfigMap + Deployment)
- [ ] ESO force-sync + `Ready=True` verify
- [ ] Rollout restart + status (240s timeout)

### Post-apply verify

- [ ] Pod imageID == sha256:30b0bf658dcd...
- [ ] Pod env (key-only): `NOTIFY_DKIM_PRIVATE_KEY_PEM` Secret key mevcut
  ```bash
  kubectl --context k3d-prod -n platform-prod get secret \
    notification-orchestrator-secrets -o json \
    | jq '.data | keys[] | select(startswith("NOTIFY_DKIM_"))'
  ```
- [ ] ConfigMap NOTIFY_DKIM_ENABLED=true rendered
- [ ] Pod log: `DkimSigner activated` (or similar — verify exact log line via backend impl)
- [ ] **No startup crash** (ProductionConfigValidator passes)

### Outbound mail smoke (R3 mitigation kanıt)

```bash
# Submit a test mail intent via prod-smoke-tester
TOKEN="<prod smoke-tester JWT>"
INTENT_ID="dkim-activation-canary-$(date +%s)"

curl -sS -X POST https://ai.acik.com/api/v1/notify/intents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"intentId\": \"$INTENT_ID\",
    \"idempotencyKey\": \"$INTENT_ID\",
    \"orgId\": \"default\",
    \"topicKey\": \"system.canary.dkim\",
    \"severity\": \"info\",
    \"dataClassification\": \"system\",
    \"recipients\": [{\"type\":\"external\",\"email\":\"check-auth@verifier.port25.com\"}],
    \"template\": {\"templateId\":\"t1\",\"version\":1,\"locale\":\"en\"},
    \"channels\": [\"email\"],
    \"payload\": {\"name\":\"DKIM smoke test\"}
  }" | jq .

# port25.com verifier returns SPF/DKIM/DMARC verification report via reply
# Expected: DKIM=pass + signature header verified + d=acik.com s=acik2026
```

VEYA mail-tester.com:
1. mail-tester.com adresinden test email ID al (e.g. test-XXXXX@mail-tester.com)
2. Intent gönder o adrese
3. mail-tester.com'da DKIM section: `Your message contains a valid DKIM signature ✓`
4. Overall score ≥9/10 (DKIM + SPF + DMARC dependent)

## 6. Rollback (D30 72h warm)

```bash
# Option 1: PR revert (preferred GitOps)
git revert <this PR commit>
git push
# (CI + Codex AGREE) → merge → cluster apply → pod restart with old digest

# Option 2: Break-glass (emergency — same-incident reconciliation PR şart)
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod patch configmap \
  notification-orchestrator-config --type=json \
  -p='[{\"op\":\"replace\",\"path\":\"/data/NOTIFY_DKIM_ENABLED\",\"value\":\"false\"}]'"
# AND image rollback
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod set image \
  deploy/notification-orchestrator notification-orchestrator=ghcr.io/halildeu/platform-backend-notification-orchestrator@sha256:70491543fdc3341fbf7685773efec74a6ca2ca473c90e38f89a5247e3568b1c3"
# IMMEDIATELY open reconciliation PR
```

## 7. Sıradaki sprint (post-DKIM activation)

**M4 prod cutover RE-ATTEMPT** (yeni PR):
- JetSMS ConfigMap 8 keys (PRIMARY=jetsms + multipart + SOAP single + OTP allowlist)
- NetworkPolicy egress 587/443 mirror from test overlay
- R24 OTP_TOPIC_KEYS="" mitigation initial; Biotekno provisioning sonrası operator config patch

PR #911 + #912 cycle'dan ders: aynı PR'da hem prereq hem feature olunca debug zorlaşır.
DKIM activation atomic + M4 RE-ATTEMPT ayrı = blast radius minimize.

## 8. References

- ADR-0013: notification-orchestration architecture
- ADR-0011: PR boundary declaration governance
- Codex thread `019e4514-e961-7d50-b2cc-493f66cee4bc` (PR-A1 → PR-A3.2 + #911 + #912 cycle)
- platform-backend PR #151 (DKIM RFC 6376 full impl)
- platform-k8s-gitops PR #912 (revert PR #911 M4 cutover — DKIM blocker lessons)
- docs/runbooks/RB-faz-23-3-jetsms-cutover.md (M4 prod cutover original runbook — addendum eklenecek)
- docs/runbooks/RB-faz-23-dns-records-acik-com.md (SPF/DMARC base records — DKIM şu PR ile eklenir)

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
