# RB-bl028b-prod-openfga-notification-model-cutover — Prod OpenFGA Notification Model Cutover (Lane B)

> **Status**: ✅ **LIVE EXECUTED 2026-05-25 12:01 UTC** (M4.6 trigger; 10/10 acceptance gate PASS; new prod model `01KSFFK9K3V43DD211Z79K3FYA`; 5 ExternalSecret consumer aligned; permission-service internal allow=true reason=tuple_match; ERP regression preserved). Evidence: `docs/faz-23-evidence/2026-05-25-bl028b-lane-b-prod-openfga-cutover-evidence.md`. Bu RB historical execute reference olarak kalır.
> **Parent**: BL-028 (M4.5/23.3.3 Lane A LIVE + M4.6/23.3.4 Lane B)
> **Pattern**: B-with-lanes (Codex 019e5ebe iter-3 AGREE B-with-lanes; bu RB Lane B detayı)
> **Codex peer review chain (Lane B specific)**: thread `019e5ee5-4da5-7713-9dbe-8567d83e1ef2` iter-1 PARTIAL → iter-2 AGREE/ready_for_impl=true
> **Cross-AI**: implementer Anthropic Claude / reviewer OpenAI Codex (HARD RULE 2026-05-05/14 compliance)
> **Trigger condition**: BL-028a Lane A LIVE ✅ (PR #1067 MERGED) + M4.6 milestone start + operator+architecture gate açık
> **No-SMS guarantee**: Bu runbook'taki hiçbir adım SMS göndermez. SMS gönderimi BL-028b PASS sonrası BL-011 ayrı authorization gate ile.

---

## 1. Bağlam — Lane B prereq + impact

**BL-028a Lane A LIVE EXECUTED 2026-05-25** (PR #1067 `aa84d0a` MERGED):
- prod notify_db functional data seed COMPLETED (template + subscriber)
- R28 status: 🟡 Partial Mitigated

**Lane A acceptance ile BL-011 hâlâ blocked** (Layer-2 fail-closed):
- Prod OpenFGA model `01KS15PF531R1P99BMMM7SFMV1` sadece D35 ERP types
- Notification types (subscriber/notification_topic/template) prod'a cutover EDİLMEDİ
- Backend `AuthzClient`: permission-service non-200/exception → `deny("authz_<code>")` → `BLOCKED_BY_AUTHZ` → SMS gitmez

**Lane B = critical path**: Prod OpenFGA notification model cutover + topic-inheritance tuple seed + permission ALLOW. Bu runbook Lane B execute path'i.

**Impact scope — 5 ExternalSecret consumer** `kv/platform/openfga model_id`:

| Service | Path |
|---|---|
| permission-service | `kustomize/base/apps/permission-service/ops/externalsecret.yaml:48` |
| core-data-service | `kustomize/base/apps/core-data-service/ops/externalsecret.yaml:42` |
| report-service | `kustomize/base/apps/report-service/ops/externalsecret.yaml:45` |
| user-service | `kustomize/base/apps/user-service/ops/externalsecret.yaml:42` |
| variant-service | `kustomize/base/apps/variant-service/ops/externalsecret.yaml:40` |

Vault `model_id` patch 5 K8s Secret + 5 pod env'i etkiler.

---

## 2. Step 0 — Preflight snapshot + backup (single evidence bundle)

> **Zorunlu** — execute öncesi single bundle olarak kaydedilmeli.

```bash
NS=platform-prod
SNAPSHOT_DIR="/tmp/bl028b-snapshot-$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$SNAPSHOT_DIR"

# 2.1 Old model_id + Vault state
OLD_MODEL_ID="01KS15PF531R1P99BMMM7SFMV1"
STORE_ID="01KPXCVBHCY2TQ6YHVK009NS1C"

# 2.2 Live old model JSON fetch
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/permission-service -- \
  curl -sS http://openfga:8080/stores/$STORE_ID/authorization-models/$OLD_MODEL_ID" \
  > "$SNAPSHOT_DIR/old-model.json"

# 2.3 Canonical digest of old model (RFC8785 / jq -S sorted)
jq -S . "$SNAPSHOT_DIR/old-model.json" | sha256sum > "$SNAPSHOT_DIR/old-model-digest.txt"

# 2.4 5 K8s Secret current values (ERP_OPENFGA_MODEL_ID base64 read)
for svc in permission-service core-data-service report-service user-service variant-service; do
  ssh halil@staging-sw "kubectl --context k3d-prod -n $NS get secret ${svc}-secrets -o jsonpath='{.data.ERP_OPENFGA_MODEL_ID}'" | base64 -d \
    > "$SNAPSHOT_DIR/${svc}-model-id-current.txt"
done

# 2.5 5 pod env state (ERP_OPENFGA_MODEL_ID runtime value)
for svc in permission-service core-data-service report-service user-service variant-service; do
  ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/$svc -- env" 2>/dev/null | \
    grep -E "^ERP_OPENFGA_(MODEL_ID|STORE_ID)" \
    > "$SNAPSHOT_DIR/${svc}-pod-env.txt"
done

# 2.6 Tuple absence/readback (canary tuples should NOT exist yet)
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/permission-service -- \
  curl -sS -X POST http://openfga:8080/stores/$STORE_ID/read \
  -H 'Content-Type: application/json' \
  -d '{\"tuple_key\":{\"object\":\"notification_topic:marketing.campaign\",\"relation\":\"can_receive\"}}'" \
  > "$SNAPSHOT_DIR/canary-tuple-absence.json"

# 2.7 Affected deployments list (rollout history checkpoint)
for svc in permission-service core-data-service report-service user-service variant-service; do
  ssh halil@staging-sw "kubectl --context k3d-prod -n $NS rollout history deploy/$svc" \
    > "$SNAPSHOT_DIR/${svc}-rollout-history.txt"
done

# 2.8 Vault current model_id state (operator action — agent log'lamaz raw token)
# Operator: vault kv get -mount=kv -field=model_id platform/openfga
# Snapshot'a manuel append edilir; agent secret loglamaz
echo "Vault kv/platform/openfga#model_id current value: <OPERATOR-FILL>" \
  > "$SNAPSHOT_DIR/vault-model-id-current.txt"

# Evidence bundle integrity check
ls -la "$SNAPSHOT_DIR/"
sha256sum "$SNAPSHOT_DIR"/*.json "$SNAPSHOT_DIR"/*.txt > "$SNAPSHOT_DIR/SHA256SUMS"
```

**Snapshot bundle**: `/tmp/bl028b-snapshot-<timestamp>/` — rollback anchor + audit evidence.

---

## 3. 5 Consumer impact inventory

Bu cutover **sadece permission-service'i değil 5 servisi** etkiler. Her birinin Vault selector flip + ESO sync + pod env alignment + rollout restart gate'i ayrı.

| Servis | Vault key | K8s Secret | Pod env | Bağımlılık | Rollout sırası |
|---|---|---|---|---|---|
| permission-service | `kv/platform/openfga` model_id | `permission-service-secrets` | `ERP_OPENFGA_MODEL_ID` | OpenFGA direct check | 1️⃣ Önce (kritik path; BL-011 unblock) |
| user-service | `kv/platform/openfga` model_id | `user-service-secrets` | `ERP_OPENFGA_MODEL_ID` | OpenFGA direct check (ERP D35) | 2️⃣ Sonra |
| variant-service | `kv/platform/openfga` model_id | `variant-service-secrets` | `ERP_OPENFGA_MODEL_ID` | OpenFGA direct check (ERP D35) | 3️⃣ Sonra |
| core-data-service | `kv/platform/openfga` model_id | `core-data-service-secrets` | `ERP_OPENFGA_MODEL_ID` | OpenFGA direct check (ERP D35) | 4️⃣ Sonra |
| report-service | `kv/platform/openfga` model_id | `report-service-secrets` | `ERP_OPENFGA_MODEL_ID` | OpenFGA direct check (ERP D35) | 5️⃣ Sonra |

> **Why sequential rollout**: Single-replica prod posture (BL-006b kanıt); paralel restart blast radius riski büyütür. New model ERP-equivalent olduğu için kısa mixed-window kabul edilebilir. Permission-service'i önce restart etmek BL-011 unblock kritik path'ini erken açar.

---

## 4. ERP type semantic diff (canonical JSON normalize compare)

> **Acceptance hard gate**: 10 ERP type_definitions yeni modelde **byte/semantic identical** olmalı. Aksi RED → no cutover.

```bash
# 4.1 Live current prod model fetch (snapshot already has, re-use)
OLD_MODEL_JSON="$SNAPSHOT_DIR/old-model.json"

# 4.2 DSL render to OpenFGA JSON
# (Operator: openfga CLI transform veya prior model evidence renderer)
fga model write --file docs/notify/openfga-notification-model.dsl --dry-run > /tmp/new-model.json
# Veya: pre-render edilmiş runtime-artifacts/openfga-model/<digest>.json

# 4.3 Extract ERP subset (10 types)
ERP_TYPES='["action","branch","company","module","organization","project","report","report_group","user","warehouse"]'

extract_erp_subset() {
  jq --argjson erp "$ERP_TYPES" '
    .type_definitions[]? // .authorization_model.type_definitions[]?
    | select(.type as $t | $erp | index($t))
  ' "$1" | jq -s 'sort_by(.type) | map(. | {type, relations, metadata})'
}

extract_erp_subset "$OLD_MODEL_JSON" > "$SNAPSHOT_DIR/old-erp-subset.json"
extract_erp_subset /tmp/new-model.json > "$SNAPSHOT_DIR/new-erp-subset.json"

# 4.4 Canonical compare
diff <(jq -S . "$SNAPSHOT_DIR/old-erp-subset.json") \
     <(jq -S . "$SNAPSHOT_DIR/new-erp-subset.json") \
     > "$SNAPSHOT_DIR/erp-subset-diff.txt"

if [ -s "$SNAPSHOT_DIR/erp-subset-diff.txt" ]; then
  echo "❌ ERP SUBSET DRIFT — RED → no cutover"
  cat "$SNAPSHOT_DIR/erp-subset-diff.txt"
  exit 1
else
  echo "✅ ERP subset normalized equality PASS (10 types identical)"
fi

# 4.5 Notification types presence check (yeni modelde olmalı)
EXPECTED_NEW_TYPES='["subscriber","service_account","notification_topic","notification_template","template"]'
jq -e --argjson new "$EXPECTED_NEW_TYPES" '
  ([.type_definitions[]? // .authorization_model.type_definitions[]? | .type] | tojson) as $present
  | ($new | map(. as $t | $present | contains($t | tojson))) | all
' /tmp/new-model.json && echo "✅ Notification types present" || { echo "❌ Notification types MISSING"; exit 1; }

# 4.6 Canonical full-model digest
NEW_DIGEST=$(jq -S . /tmp/new-model.json | sha256sum | awk '{print $1}')
echo "New model canonical digest: $NEW_DIGEST"
echo "Existing artifact digest: a48a49198c70bd3f928bbac2b87ef3fd83903f00691996c04778f892146f0f9c"
if [ "$NEW_DIGEST" = "a48a49198c70bd3f928bbac2b87ef3fd83903f00691996c04778f892146f0f9c" ]; then
  echo "→ Existing ledger dosyası prod block update"
else
  echo "→ Yeni runtime-artifacts/openfga-model/${NEW_DIGEST}.json oluştur"
fi
```

**Acceptance**: ERP subset diff EMPTY + Notification types present + canonical digest computed.

---

## 5. Internal API key alignment preflight

> Önceki BL-028a Lane A'da `POST /api/v1/internal/authz/check` → 401 (auth filter active). BL-028b'de **ALLOW dönmesi gerek** — bunun için `X-Internal-Api-Key` header'ı backend `NOTIFY_AUTHZ_INTERNAL_API_KEY` ile **hash-equal** olmalı.

```bash
# 5.1 Backend env'den internal_api_key effective hash
BACKEND_KEY_HASH=$(ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/notification-orchestrator -- \
  printenv NOTIFY_AUTHZ_INTERNAL_API_KEY" 2>/dev/null | sha256sum | awk '{print $1}')

# 5.2 Permission-service env'den internal_api_key effective hash
PERM_KEY_HASH=$(ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/permission-service -- \
  printenv INTERNAL_API_KEY" 2>/dev/null | sha256sum | awk '{print $1}')

# 5.3 Hash comparison (raw value LOG'lanmaz)
if [ "$BACKEND_KEY_HASH" = "$PERM_KEY_HASH" ]; then
  echo "✅ Internal API key alignment PASS (hash match)"
else
  echo "❌ Internal API key DRIFT — RED → no cutover (BL-004 align repeat gerek)"
  exit 1
fi
```

> **Security note**: Raw API key **asla loglanmaz/dump'lanmaz**. Sadece sha256 hash karşılaştırma. BL-004 (PR önceki) bu align'ı yapmıştı; preflight bunun korunduğunu kanıtlar.

---

## 6. Execute steps (revize sıra — Codex iter-1 P0 absorb)

> **Tuple seed BEFORE Vault selector flip** — model write append-only, tuple+check yeni model_id altında, sonra selector flip.

### 6.1 Model write (append-only)

```bash
# Operator action — agent payload hazırlar
curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/authorization-models" \
  -H "Content-Type: application/json" \
  -d @/tmp/new-model.json \
  > /tmp/new-model-response.json

NEW_MODEL_ID=$(jq -r .authorization_model_id /tmp/new-model-response.json)
echo "✅ New prod model_id: $NEW_MODEL_ID"

# Fetch verify
curl -sS "http://openfga:8080/stores/$STORE_ID/authorization-models/$NEW_MODEL_ID" \
  | jq -r '.authorization_model.type_definitions[] | .type' | sort
# Beklenen: 15 type (10 ERP + 5 notification)
```

### 6.2 Tuple seed (direct OpenFGA write, explicit new model_id)

> **Idempotency note**: Tuple zaten varsa OpenFGA `Write` API 400 `tuple_already_exists` döner. Bu **benign**; readback ile fact-check yap.

```bash
# Tuple 1: notification_topic#can_receive@subscriber
curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/write" \
  -H "Content-Type: application/json" \
  -d "{
    \"authorization_model_id\": \"$NEW_MODEL_ID\",
    \"writes\": {
      \"tuple_keys\": [
        {\"user\": \"subscriber:bl028-prod-canary-001\", \"relation\": \"can_receive\", \"object\": \"notification_topic:marketing.campaign\"}
      ]
    }
  }" | tee /tmp/tuple1-response.json

# Tuple 2: template#topic@notification_topic
curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/write" \
  -H "Content-Type: application/json" \
  -d "{
    \"authorization_model_id\": \"$NEW_MODEL_ID\",
    \"writes\": {
      \"tuple_keys\": [
        {\"user\": \"notification_topic:marketing.campaign\", \"relation\": \"topic\", \"object\": \"template:canary-prod-marketing-v1\"}
      ]
    }
  }" | tee /tmp/tuple2-response.json

# Readback acceptance (canonical evidence)
curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/read" \
  -H "Content-Type: application/json" \
  -d "{\"tuple_key\":{\"object\":\"notification_topic:marketing.campaign\",\"relation\":\"can_receive\"}}" \
  | jq -e '.tuples | length >= 1' && echo "✅ Tuple 1 readback PASS"

curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/read" \
  -H "Content-Type: application/json" \
  -d "{\"tuple_key\":{\"object\":\"template:canary-prod-marketing-v1\",\"relation\":\"topic\"}}" \
  | jq -e '.tuples | length >= 1' && echo "✅ Tuple 2 readback PASS"
```

### 6.3 Direct OpenFGA allow + deny check (under new model)

```bash
# ALLOW: canary subscriber → canary template
curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/check" \
  -H "Content-Type: application/json" \
  -d "{
    \"authorization_model_id\": \"$NEW_MODEL_ID\",
    \"tuple_key\": {
      \"user\": \"subscriber:bl028-prod-canary-001\",
      \"relation\": \"can_receive\",
      \"object\": \"template:canary-prod-marketing-v1\"
    }
  }" | jq -e '.allowed == true' && echo "✅ ALLOW PASS"

# DENY-1: no-grant subscriber → canary template (Codex Q9 hard gate)
curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/check" \
  -H "Content-Type: application/json" \
  -d "{
    \"authorization_model_id\": \"$NEW_MODEL_ID\",
    \"tuple_key\": {
      \"user\": \"subscriber:nobody-control-bl028b\",
      \"relation\": \"can_receive\",
      \"object\": \"template:canary-prod-marketing-v1\"
    }
  }" | jq -e '.allowed == false' && echo "✅ DENY-1 PASS (no-grant subscriber)"

# DENY-2: canary subscriber → unlinked template (Codex Q9 hard gate)
curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/check" \
  -H "Content-Type: application/json" \
  -d "{
    \"authorization_model_id\": \"$NEW_MODEL_ID\",
    \"tuple_key\": {
      \"user\": \"subscriber:bl028-prod-canary-001\",
      \"relation\": \"can_receive\",
      \"object\": \"template:canary-prod-other-v1\"
    }
  }" | jq -e '.allowed == false' && echo "✅ DENY-2 PASS (unlinked template)"
```

### 6.4 Vault selector flip (operator action)

```bash
# Operator authorize
# vault kv patch -mount=kv platform/openfga model_id="$NEW_MODEL_ID"
# Agent NOT executing — operator hands.

# Verify Vault state post-patch (operator paste output)
# Expected: kv/platform/openfga#model_id = $NEW_MODEL_ID
```

### 6.5 ESO force-sync 5 ExternalSecrets

```bash
for svc in permission-service core-data-service report-service user-service variant-service; do
  ssh halil@staging-sw "kubectl --context k3d-prod -n $NS \
    annotate externalsecret ${svc}-secrets force-sync=$(date +%s) --overwrite"
done

# Wait for sync
sleep 30

# 6.5.1 ExternalSecret status check
for svc in permission-service core-data-service report-service user-service variant-service; do
  ssh halil@staging-sw "kubectl --context k3d-prod -n $NS get externalsecret ${svc}-secrets -o jsonpath='{.status.conditions[?(@.type==\"Ready\")].status}'"
  echo " — $svc"
done
# Beklenen: 5x True

# 6.5.2 K8s Secret value hash check (HARD GATE — Codex iter-2 minor add)
EXPECTED_NEW_HASH=$(echo -n "$NEW_MODEL_ID" | sha256sum | awk '{print $1}')

for svc in permission-service core-data-service report-service user-service variant-service; do
  SECRET_HASH=$(ssh halil@staging-sw "kubectl --context k3d-prod -n $NS get secret ${svc}-secrets -o jsonpath='{.data.ERP_OPENFGA_MODEL_ID}'" | base64 -d | sha256sum | awk '{print $1}')
  if [ "$SECRET_HASH" = "$EXPECTED_NEW_HASH" ]; then
    echo "✅ ${svc} Secret hash match"
  else
    echo "❌ ${svc} Secret hash DRIFT — ESO not synced"
    exit 1
  fi
done
```

### 6.6 Rollout restart (sequential, permission-service ÖNCE)

```bash
# 6.6.1 Permission-service first (critical path)
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS rollout restart deploy/permission-service"
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS rollout status deploy/permission-service --timeout=180s"

# 6.6.2 Verify permission-service pod env alignment
PSVC_POD_ENV=$(ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/permission-service -- printenv ERP_OPENFGA_MODEL_ID")
[ "$PSVC_POD_ENV" = "$NEW_MODEL_ID" ] && echo "✅ permission-service pod env aligned"

# 6.6.3 Permission-service internal allow check (acceptance preflight)
# (Operator authorizes BL-011 gate after this PASS)

# 6.6.4 ERP services sequential (user → variant → core-data → report)
for svc in user-service variant-service core-data-service report-service; do
  ssh halil@staging-sw "kubectl --context k3d-prod -n $NS rollout restart deploy/$svc"
  ssh halil@staging-sw "kubectl --context k3d-prod -n $NS rollout status deploy/$svc --timeout=180s"
  POD_ENV=$(ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/$svc -- printenv ERP_OPENFGA_MODEL_ID")
  [ "$POD_ENV" = "$NEW_MODEL_ID" ] && echo "✅ $svc pod env aligned"
done
```

### 6.7 Pod env alignment final verify

```bash
echo "=== 5 consumer pod env alignment final ==="
for svc in permission-service user-service variant-service core-data-service report-service; do
  POD_ENV=$(ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/$svc -- printenv ERP_OPENFGA_MODEL_ID")
  printf "%-25s %s\n" "$svc" "$POD_ENV"
done | tee "$SNAPSHOT_DIR/post-cutover-pod-env-alignment.txt"
```

Beklenen: 5 satır hepsi `$NEW_MODEL_ID` ile eşit.

### 6.8 Permission-service internal allow + deny

```bash
INTERNAL_API_KEY=$(ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/notification-orchestrator -- printenv NOTIFY_AUTHZ_INTERNAL_API_KEY")

# Internal ALLOW
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/notification-orchestrator -- curl -sS -X POST \
  -H 'X-Internal-Api-Key: $INTERNAL_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{\"principal_type\":\"subscriber\",\"principal_id\":\"bl028-prod-canary-001\",\"relation\":\"can_receive\",\"object_type\":\"template\",\"object_id\":\"canary-prod-marketing-v1\"}' \
  http://permission-service:8090/api/v1/internal/authz/check" \
  | jq -e '.allowed == true' && echo "✅ Internal ALLOW PASS"

# Internal DENY (no-grant subscriber)
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec deploy/notification-orchestrator -- curl -sS -X POST \
  -H 'X-Internal-Api-Key: $INTERNAL_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{\"principal_type\":\"subscriber\",\"principal_id\":\"nobody-control-bl028b\",\"relation\":\"can_receive\",\"object_type\":\"template\",\"object_id\":\"canary-prod-marketing-v1\"}' \
  http://permission-service:8090/api/v1/internal/authz/check" \
  | jq -e '.allowed == false' && echo "✅ Internal DENY PASS"
```

### 6.9 ERP regression smoke

```bash
# Faz 21.3 D35 ERP test tuple set replay
# (Source: docs/D35-acceptance-smoke.md veya scripts/d35-3/openfga-access-tuple-seed.sh)

# Örnek ERP test:
curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/check" \
  -H "Content-Type: application/json" \
  -d "{
    \"authorization_model_id\": \"$NEW_MODEL_ID\",
    \"tuple_key\": {
      \"user\": \"user:test-erp-user\",
      \"relation\": \"viewer\",
      \"object\": \"warehouse:test-warehouse\"
    }
  }"

# Bunu D35 evidence set'ten replay et — eski model ile aynı sonuçlar bekleniyor
# Acceptance: zero new authz errors in logs/metrics (5 dakika window)
```

---

## 7. Acceptance gate (10 hard madde — Codex iter-1 acceptance criteria)

> **Bu doc-only PR'da kanıt YOK**. M4.6 live execute turunda evidence doc PR'ında doldurulur.

- [ ] **1. Backup snapshot captured**: old model_id + old model JSON + Vault/Secret/pod env + canary tuple absence + 5 affected consumer list — `/tmp/bl028b-snapshot-<timestamp>/` bundle SHA256SUMS
- [ ] **2. New model write PASS**: 26-char ULID returned + fetch by id success
- [ ] **3. 15 expected types visible**: subscriber + service_account + notification_topic + notification_template + template + 10 ERP types
- [ ] **4. ERP subset normalized equality PASS**: 10 ERP types byte/semantic identical
- [ ] **5. Tuple write/readback PASS**: 2 tuple inserted (`notification_topic#can_receive@subscriber` + `template#topic@notification_topic`)
- [ ] **6. Direct OpenFGA ALLOW + DENY-1 + DENY-2 PASS**: 3 check (canary allow + nobody deny + unlinked template deny)
- [ ] **7. Vault=K8s Secret=pod env alignment PASS**: 5 consumer hepsi `$NEW_MODEL_ID` ile aligned (Secret hash + pod env match)
- [ ] **8. Permission-service internal allow + deny PASS**: X-Internal-Api-Key + snake_case payload + canary allow + control deny
- [ ] **9. ERP regression smoke PASS**: D35 test tuple set replay + no authz error spike/circuit-open signal in logs/metrics
- [ ] **10. Runtime-artifact ledger update PASS**: prod block `pending → promoted` + `model_id_env=<new_prod_model_id>` + evidence/source_docs

---

## 8. Runtime-artifact ledger promotion

> **Digest guard (Codex iter-2 minor add)**:
> - Eğer new model canonical digest `a48a49198c70bd3f928bbac2b87ef3fd83903f00691996c04778f892146f0f9c` (existing artifact) ile eşitse → **existing ledger file edit**
> - Eğer farklıysa → **yeni** `runtime-artifacts/openfga-model/<new-digest>.json` oluştur

Existing artifact file: `runtime-artifacts/openfga-model/a48a49198c70bd3f928bbac2b87ef3fd83903f00691996c04778f892146f0f9c.json`

Prod block update:
```json
{
  "prod": {
    "status": "promoted",     // pending → promoted
    "model_id_env": "<new_prod_model_id>",
    "evidence": "docs/faz-23-evidence/2026-XX-XX-bl028b-prod-openfga-cutover-evidence.md",
    "source_docs": [
      "docs/notify/openfga-notification-model.dsl",
      "docs/runbooks/RB-bl028b-prod-openfga-notification-model-cutover.md"
    ],
    "evidence_completeness": "verified"
  }
}
```

---

## 9. Rollback strategy

> **Pre-rollback check**: yeni model artık herhangi bir intent/delivery/audit tarafından kullanılıyor mu?

```bash
# Eğer kullanıyor → rollback YASAK; new model üzerinde fix
# Eğer kullanmıyor → rollback safe
```

### 9.1 Vault selector revert

```bash
# Operator: vault kv patch -mount=kv platform/openfga model_id="$OLD_MODEL_ID"
# Sonra 5 ExternalSecret force-sync + 5 rollout restart (revize sıra: permission-service önce, sonra ERP)
```

### 9.2 Tuple delete (eğer rollback gerekli)

```bash
# Direct OpenFGA delete (model_id explicit)
curl -sS -X POST "http://openfga:8080/stores/$STORE_ID/write" \
  -H "Content-Type: application/json" \
  -d "{
    \"authorization_model_id\": \"$NEW_MODEL_ID\",
    \"deletes\": {
      \"tuple_keys\": [
        {\"user\": \"subscriber:bl028-prod-canary-001\", \"relation\": \"can_receive\", \"object\": \"notification_topic:marketing.campaign\"},
        {\"user\": \"notification_topic:marketing.campaign\", \"relation\": \"topic\", \"object\": \"template:canary-prod-marketing-v1\"}
      ]
    }
  }"
```

### 9.3 Model revision append-only (silinmez)

Yeni model `$NEW_MODEL_ID` OpenFGA store'da kalır. Aktif selector revert ile etkisiz. Re-attempt için yeni model write **gerekmez** — aynı `$NEW_MODEL_ID` re-promote edilebilir.

---

## 10. BL-011 separate authorization gate

> **Codex iter-2 hard gate (Q5 minor add)**: BL-028b PASS **sadece BL-011 eligibility açar**. SMS POST otomatik tetiklenmez.

BL-028b acceptance gate (10 madde) PASS sonrası:
- ✅ BL-011 eligibility OPEN (Layer-2 fail-closed kalktı)
- ⏳ BL-011 execute için **ayrı operator authorization**:
  - Operator window scheduled
  - Recipient `+905551815564` re-confirm
  - Cost cap ≤3 SMS confirm
  - max_count=1 (recommended)
  - notify_delivery row evidence
  - audit_event_v2 row evidence
  - Provider DLR evidence
  - No unexpected duplicate delivery

**BL-011 RB**: `docs/runbooks/RB-bl011-prod-sms-canary-execute.md` — Lane B PASS sonrası execute path.

---

## 11. Evidence doc template (post-Lane-B live execute için placeholder)

> M4.6 live execute turunda `docs/faz-23-evidence/<YYYY-MM-DD>-bl028b-prod-openfga-cutover-evidence.md` ile evidence doc yazılır. İçerik şablonu:

```markdown
# Evidence — BL-028b Lane B Live Execute — <YYYY-MM-DD>

## §1 Pre-execute snapshot bundle
[/tmp/bl028b-snapshot-<timestamp>/ SHA256SUMS]

## §2 ERP semantic diff
[erp-subset-diff.txt EMPTY + canonical digest]

## §3 Model write output
[NEW_MODEL_ID ULID + 15 type count]

## §4 Tuple seed + readback
[2 tuple inserted + readback success]

## §5 Direct OpenFGA allow + 2 deny
[ALLOW canary + DENY-1 nobody + DENY-2 unlinked]

## §6 Vault selector flip
[Vault state post-patch — operator paste]

## §7 ESO sync + 5 Secret hash match
[5 consumer hash table]

## §8 Rollout restart sequence
[5 consumer rollout history + completion time]

## §9 5 pod env alignment
[5 consumer env table — all $NEW_MODEL_ID]

## §10 Permission-service internal allow + deny
[X-Internal-Api-Key allow + control deny]

## §11 ERP regression smoke
[D35 test set replay — zero error]

## §12 Runtime-artifact ledger promotion
[prod block pending → promoted + digest guard kararı]

## §13 R28 status post Lane B
[🟡 partial → 🟢 Mitigated]

## §14 BL-011 eligibility opens
[Operator separate authorization gate references]

## §15 Cross-AI peer review
[Codex thread 019e5ee5 iter-2 AGREE]

## §16 Audit trail
[Snapshot bundle archive + git commit + PR + board claim + operator + agent split note]
```

---

## 12. Cross-AI peer review chain

- **Implementer**: Anthropic Claude (Opus 4.7 1M context)
- **Reviewer**: OpenAI Codex
- **Codex iter chain**:
  - iter-1: PARTIAL (6 blocker — preflight backup, 5 consumer impact, execution order, ERP semantic diff, ledger promotion, internal API key alignment)
  - iter-2: **AGREE** / ready_for_impl=true / recommended_milestone_path=M4.6-with-ops-window
- **Provider farkı**: Anthropic ↔ OpenAI (HARD RULE 2026-05-05/14 compliance)

---

## Referanslar

- BL-028 parent runbook: `docs/runbooks/RB-bl028-prod-data-seed-execute.md` (B-with-lanes; Lane A LIVE 2026-05-25)
- BL-011 RB: `docs/runbooks/RB-bl011-prod-sms-canary-execute.md` (Lane B PASS sonrası execute path)
- Risk register R28: `docs/notify/risk-register.md`
- Closure handoff backlog: `docs/runbooks/RB-faz-23-v1-closure-operator-handoff.md`
- Charter: `docs/runbooks/RB-faz-23-charter.md`
- OpenFGA notification model DSL: `docs/notify/openfga-notification-model.dsl`
- Runtime-artifact ledger: `runtime-artifacts/openfga-model/a48a49198c70bd3f928bbac2b87ef3fd83903f00691996c04778f892146f0f9c.json`
- BL-006b multi-cluster Vault topology resolution: PR #1048 + Codex `019e5b3d`
- BL-004 internal API key align: PR #1051 + evidence `docs/faz-23-evidence/2026-05-24-bl004-prod-authz-internal-api-key-align.md`
- BL-028a Lane A evidence: `docs/faz-23-evidence/2026-05-25-bl028a-lane-a-prod-data-seed-execute.md`
- Codex peer review thread (Lane B): `019e5ee5-4da5-7713-9dbe-8567d83e1ef2`
