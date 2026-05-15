# Runbook — V2.1 #3 M2a Authenticated Route Owner Action (Narrow Scope)

> **Belge kodu**: `RB-v2.1-3-m2a-narrow-owner-action`
> **Tarih**: 2026-05-15
> **Sahip**: Halil
> **Sprint**: V2.1 prod-readiness — #3 closure (son owner action)
> **Codex consensus**: thread `019e2a4f` Option B + "M2a0 owner step daraltılmış scope"
> **Status**: Owner action runbook (autonomous prep tamam)

---

## 1. Bağlam — Codex Option B Verdict

Codex `019e2a4f` V2.1 #3 M2a verdict:
> "**Option B (M2a yapın).** ABM-1 reclassification doğru değil. ABM-1'de eksik olan bekleme idi; M2a'da eksik olan **authenticated route ölçümünün kendisi**. PMD bunu gap olarak tanımlıyor."

> "**M2a0 owner step'i daralt:** Vault root recovery'yi genel DR projesine çevirmeden, sadece `kv/platform/test-personas/perf-auth` için güvenli owner credential-write yolu netleştir."

Bu runbook **daraltılmış owner action** scope sunar — full Vault DR projesini avoid ederek sadece M2a için gereken minimum credential-write path'i çizer.

---

## 2. Mevcut State Discovery (Autonomous — Session 53)

### 2.1 Keycloak Compose Stateful

```bash
$ docker ps | grep keycloak
platform-kc-prod  quay.io/keycloak/keycloak:26.5.5  Up 3 days (healthy)
platform-kc-test  quay.io/keycloak/keycloak:26.5.5  Up 2 days (healthy)
```

K8s tarafı:
```bash
$ kubectl --context k3d-prod -n platform-prod get svc keycloak
keycloak  ClusterIP  10.43.78.178  8080/TCP  21d
```

Service → compose `platform-kc-prod` üzerinden gidiyor (host-services pattern).

### 2.2 Keycloak Admin Credential

```bash
$ docker inspect platform-kc-prod --format '{{range .Config.Env}}{{println .}}{{end}}' | grep ADMIN
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD_FILE=/run/secrets/kc_admin_password

$ docker exec platform-kc-prod ls -la /run/secrets/kc_admin_password
-rw-r--r-- 1 1001 1001 33 ... /run/secrets/kc_admin_password
```

Password 32 char Docker secret mount. **Mevcut password fail eden auth** (HTTP 401) — kullanıcının daha önce manuel değiştirmiş olabileceği password (HARD RULE: agent dokunmaz).

### 2.3 Vault State

```bash
$ docker exec platform-vault-test vault status
Total Shares 3, Threshold 2 (test cluster)
$ docker exec platform-vault-prod vault status
Total Shares 5, Threshold 3 (prod cluster)
```

Root token state: 403 forbidden (Codex `019e27e1` B verdict — owner-gated DR).

---

## 3. Owner Action (Narrow Scope — 3 Step)

### 3.1 Vault Test-Personas Credential Write

Codex Q1 önerisi: **full DR projesini avoid et**; sadece test-personas write için emergency root.

**Option A**: Eski recovery shares varsa (init.json) test Vault için generate-root:
```bash
ssh halil@staging-sw

# Test cluster Vault — emergency root via init shares
docker exec platform-vault-test vault operator generate-root -cancel || true
OTP=$(docker exec platform-vault-test vault operator generate-root -generate-otp | tail -1)
NONCE=$(docker exec platform-vault-test vault operator generate-root -init -otp="$OTP" | awk '/Nonce/{print $NF}')
echo "OTP=$OTP NONCE=$NONCE"

# 2 share submit (test Vault threshold 2)
SHARE_1=$(python3 -c "import json; print(json.load(open('/home/halil/platform/state/vault-dev/vault-init.json'))['unseal_keys_b64'][0])")
docker exec platform-vault-test vault operator generate-root -nonce="$NONCE" "$SHARE_1"
# 2'nci share: init.json'da yoksa Owner'ın kendi secure storage'ından alır
read -s SHARE_2
RESULT=$(docker exec platform-vault-test vault operator generate-root -nonce="$NONCE" "$SHARE_2")
ENCODED=$(echo "$RESULT" | awk '/Encoded Token/{print $NF}')

# Decode
ROOT_TOKEN=$(docker exec platform-vault-test vault operator generate-root -decode="$ENCODED" -otp="$OTP" | tail -1)

# Test-personas write
read -s TEST_USER_PASS  # secure password input
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test vault kv put kv/platform/test-personas/perf-auth \
  username="perf-test@local" \
  password="$TEST_USER_PASS" \
  email="perf-test@local" \
  realm="platform"

# Verify
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test vault kv get kv/platform/test-personas/perf-auth

# Cleanup
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test vault token revoke -self
unset ROOT_TOKEN TEST_USER_PASS SHARE_2 OTP NONCE ENCODED RESULT
```

**Option B** (Codex önerdiği fallback): Vault root regen mümkün değilse, **owner-signed temporary K8s Secret waiver**:
```bash
kubectl --context k3d-test -n platform-test create secret generic test-personas-perf-auth \
  --from-literal=username='perf-test@local' \
  --from-literal=password='<owner-chosen-strong-pass>' \
  --from-literal=realm='platform' \
  --dry-run=client -o yaml | kubectl --context k3d-test -n platform-test apply -f -
```

**NOTLU**: PMD'de "deviation from Vault-backed seed" açık işaretlenmeli (Codex consensus — temporary).

### 3.2 Keycloak Persona Create

Mevcut Keycloak admin password kullanıcı kontrolünde (HARD RULE — agent dokunmaz). Owner:

```bash
ssh halil@staging-sw

# Admin password — kullanıcı bilir (Docker secret veya kendi notu)
KC_ADMIN_USER=admin
read -s KC_ADMIN_PASS  # kullanıcı input

# Token al
TOKEN=$(curl -s -X POST "https://testai.acik.com/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=$KC_ADMIN_USER&password=$KC_ADMIN_PASS&grant_type=password&client_id=admin-cli" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Persona create (platform realm)
curl -s -X POST "https://testai.acik.com/admin/realms/platform/users" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "perf-test",
    "email": "perf-test@local",
    "firstName": "Perf",
    "lastName": "Test",
    "enabled": true,
    "emailVerified": true,
    "credentials": [{
      "type": "password",
      "value": "<TEST_USER_PASS_FROM_3.1>",
      "temporary": false
    }]
  }'

# Verify
curl -s -H "Authorization: Bearer $TOKEN" "https://testai.acik.com/admin/realms/platform/users?username=perf-test" \
  | python3 -m json.tool | head -20

unset KC_ADMIN_PASS TOKEN
```

### 3.3 Platform-Web M2a1 Playwright auth-storage Impl

Cross-repo (`Halildeu/platform-web`) M2a1 — owner action'dan **sonra autonomous yapılabilir**:

```bash
cd ~/Documents/platform-web
git checkout -b feat/perf-v2.1-m2a1-auth-storage-runtime-gen

# Implementation scope (platform-web tarafında):
# - tests/perf/auth-storage-setup.ts (Playwright runtime-gen storageState)
# - tests/perf/authenticated-route-budget.spec.ts (4 route × N=3 measure)
# - .github/workflows/gate-m2a-auth-route-budget.yml (PR-time path-filter)
# - tests/perf/baseline.json extend (4 auth route entry: /home + 3 admin)

# Runtime auth-storage pattern:
# 1. Vault path read OR K8s Secret read (test-personas-perf-auth)
# 2. Playwright launch → /login → fill creds → submit → wait auth
# 3. context.storageState() → save JSON (tmp, not committed)
# 4. Subsequent test runs reuse storageState
# 5. Rotation: every CI run regenerates (no stale token risk)
```

Codex `019e2a4f` Option B exec notları:
- "Runtime-generated storageState, committed fixture YOK"
- "4 route rendered-sentinel + BUILD_SHA + browser/cache metadata + N≥3 ölçüm"
- "Sonuçlar iyi/kötü diye değil, **ölçüm zinciri kuruldu** diye kapat"

---

## 4. Acceptance Criteria

### Owner Step (3.1 + 3.2) — ~30-60dk

- [ ] Vault test-personas/perf-auth write OR K8s Secret waiver (Option A/B)
- [ ] Keycloak `perf-test` user create platform realm
- [ ] Password symmetric (Vault/Secret + Keycloak aynı)
- [ ] Test login flow verify: `curl /realms/platform/protocol/openid-connect/token grant_type=password` → access_token döner

### Agent Autonomous Step (3.3) — ~1-2 saat

- [ ] Platform-web M2a1 PR (auth-storage setup + 4 route budget spec)
- [ ] GHA workflow gate-m2a-auth-route-budget
- [ ] Codex peer review (cross-AI HARD RULE)
- [ ] CI yeşil + AGREE → merge
- [ ] V2.1 #3 closure evidence PR

### V2.1 Closure Final

- [ ] V2.1 9/9 DONE (100%)
- [ ] Faz G freeze gate full unlocked
- [ ] D30 atomic cutover sign-off mümkün

---

## 5. Codex Option B Daraltılmış Scope — Pragmatik Execution

> "Sonuçlar iyi/kötü diye değil, ölçüm zincirini ve route baseline'ı başlatmak."

M2a için **hedef değil** — sadece **baseline measurement chain**'i kurmak. Eğer 4 route budget aşarsa V3 trigger §1 (Auth route hard fail) input olur, V2.1 closure'ı engellemez.

PMD v9.1 wording: M2a1 ilk ölçüm **warn-only baseline seed** (G2 sliding baseline pattern).

---

## 6. Faz G Freeze Gate Impact

Bu runbook execution sonrası:

| Gate | Pre | Post |
|---|---|---|
| #3 M2a authenticated | 🟡 Owner | 🟢 DONE |
| #4 Receiver E2E | 🟢 DONE (PR #666) | 🟢 |
| #6 ABM-1 acceptance | 🟢 DONE (PR #660) | 🟢 |
| #7 Branch protection | 🟢 DONE (PR #671) | 🟢 |

**4/4 hard gate DONE** → D30 atomic cutover sign-off mümkün.

---

## 7. Codex Audit Trail

- Thread `019e2a4f` V2.1 closure stratejik consensus chain
- Q1 Option B verdict M2a yapılmalı
- "M2a0 owner step daraltılmış scope" pragmatik öneri
- ABM-1 reclassification ≠ M2a (kategori farkı)
- Cross-AI peer review: Claude (autonomous prep + runbook) + Codex (verdict)

---

## 8. Audit Referansları

- PMD v9.1 §2.1 PR-V2.1-M2a0 + M2a1 + M2a2 chain
- Codex thread `019e2a4f` Q1 Option B verdict
- Faz G transition plan §2.1 #3 hard gate
- PR #642 (V2.1 #4 partial waiver pattern referans — temporary waiver dili)
- HARD RULE — Kullanıcı Aktif Credential'ına Dokunma YASAK (admin password)
