# Runbook — D1.1a auth-service Vault Password Rotation Containment

> ⚠️ **RETRACTED (2026-05-16, D1.1c Phase 3 RCA)** — Bu runbook'un hedef değeri (inline override hash `6f765b6d…`'i Vault'a yazma) **misdiagnosis**'ti: o inline değer hiç `scram-sha-256` ağ-auth'una karşı doğrulanmamıştı (aynı masking tuzağı — D1.1c §2.1 false positive, local `trust` hattı). D1.1c Phase 3 canlı kanıtı: gerçek kök neden credential drift; auth-service'in kullanması gereken doğru canonical `platform` password'ü hash prefix `808bc9ef…`. **Bu runbook'un Adım 1-3'ünü (inline extraction + `6f765b6d` Vault write) UYGULAMA.** Güncel fix runbook'u: [`RB-d1.1c-auth-service-credential-convergence.md`](./RB-d1.1c-auth-service-credential-convergence.md). RCA: `docs/d1.1c-flyway-rca-discovery-2026-05-14.md` §5.Y. Bu doküman audit/tarihçe için tutulur.

> Codex 019e234e + 019e256f + 019e258a Session 48/49 strategic consultation — D dalga 1.1 containment.
> Authority boundary: ADR-0010 §2.5 + ADR-0011 §2.3 + CLAUDE.md HARD RULE Pre-Production Full Authority + Kullanıcı Aktif Credential.

## Bağlam

2026-05-14 Session 48 supplement'inde tespit edildi: auth-service test cluster pod inline `SPRING_DATASOURCE_PASSWORD` ile çalışıyor (hash `6f765b6d1cc2317f`); Vault canonical secret farklı hash (`808bc9ef23cfa266`). Sibling servisler (user-service, permission-service) Vault canonical ile uyumlu.

**Risk:** Inline override aktif; eğer kaldırılırsa envFrom Secret'tan farklı password gelir → PG auth fail → CrashLoop. Plus ConfigMap'te `SPRING_JPA_HIBERNATE_DDL_AUTO=update + SPRING_FLYWAY_ENABLED=false` schema mutation tehlikesi (inline `none` ile override edilmiş).

## Authority Boundary

ADR-0011 §2.3'e göre **credential material read/write** user-approval gate'i ister; agent-yapısal kapsamı dışında. CLAUDE.md HARD RULE Pre-Production Full Authority kubectl/system credential ops'i kapsar; **plaintext credential extraction veya Vault write** kapsamı dışında.

| Step | Aktör | Sebep |
|---|---|---|
| 1. Inline password value extraction (plaintext read) | **Operator** | Plaintext credential material handling — ADR-0011 §2.3 user-approval gate |
| 2. Plaintext password'ü Vault'a yaz | **Operator** | Plaintext credential + Vault root token; ADR-0010 §2.5 Vault credential ops gate |
| 3. Vault root token / unseal material handling | **Operator** | Codex 019e256f §3: "agent'ın root token üretmesi/unseal yoluna girmesine izin verme" |
| 4. ESO force-sync (kubectl annotate) | **Agent** | System credential ops; kubectl-level, plaintext yok |
| 5. Secret hash parity verify | **Agent** | Read-only hash prefix kanıt, plaintext yok |
| 6. Overlay ConfigMap safety hold PR | **Agent** | GitOps PR akışı; HARD RULE cross-AI peer review |
| 7. Selective apply auth-service | **Agent** | Pre-prod Full Authority kapsamı |
| 8. Rollout smoke + browser/API verify | **Agent** | Standard verification |
| 9. Drift detector re-run | **Agent** | Read-only |

**Hidden shell protokolü:** Operator adımları **agent transcript dışında** çalıştırılır. Agent'a yalnızca **hash prefix (16 char)** + status sinyali verilir; plaintext password, dosya yolu, veya başka credential material agent transcript'ine düşmez.

## Operatör Adımları (Hidden Shell, agent context dışı)

### Adım 1: Inline password'ü güvenli geçici dosyaya çıkar

```bash
# Operatör staging-sw shell'de (agent context dışında):
umask 077
TMP=$(mktemp /dev/shm/auth-pw.XXXXXX)
trap 'shred -u "$TMP" 2>/dev/null || rm -f "$TMP"' EXIT

# jq -rj newline eklemez; head -c truncate riski; tam string al
kubectl --context k3d-test -n platform-test get deploy auth-service \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SPRING_DATASOURCE_PASSWORD")].value}' \
  > "$TMP"

# Hash prefix önizleme (plaintext değil; sadece prefix agent'a paylaşılacak)
HASH_PREFIX=$(sha256sum "$TMP" | head -c 16)
echo "inline-password-hash-prefix: $HASH_PREFIX"
# Beklenen: 6f765b6d1cc2317f
```

### Adım 2: Vault'a yaz

```bash
# Vault unseal gerekirse (operatör shamir unseal keys ile)
docker exec -it platform-vault-test vault operator unseal <key1>
docker exec -it platform-vault-test vault operator unseal <key2>
docker exec -it platform-vault-test vault operator unseal <key3>

# Root login (init token; operatör elinde olmalı)
docker exec -it platform-vault-test vault login <root-token>

# Patch — container'a stdin ile pipe (host /tmp ↔ container /tmp eşleşmiyor)
cat "$TMP" | docker exec -i platform-vault-test sh -c 'vault kv patch \
  kv/platform/auth-service db_password=-'
# Vault CLI `-` ile stdin'den value okur; `@file` host path container'da yok

# Verify (hash prefix only — plaintext değil)
docker exec platform-vault-test vault kv get -field=db_password \
  kv/platform/auth-service | sha256sum | head -c 16
# Beklenen: 6f765b6d1cc2317f (inline ile match — agent'a iletilecek prefix)
```

### Adım 3: Onay sinyali

Operatör adımları tamamlayıp agent'a şunu iletir (chat/Slack/komentar):

> Vault rotation tamamlandı. Hash parity PASS — prefix `6f765b6d1cc2317f` (Vault canonical = live inline).

Plaintext password, dosya yolu, Vault token agent transcript'ine asla yazılmaz.

`trap` cleanup tmpfs file'i kapanışta shred eder.

## Agent Adımları

### Adım 4: ESO force-sync

```bash
# Pre-state snapshot (audit için resourceVersion)
PRE_RV=$(ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get secret auth-service-secrets -o jsonpath='{.metadata.resourceVersion}'")
echo "PRE_RV=$PRE_RV"

# Force sync annotate
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test annotate \
  externalsecret auth-service-secrets force-sync=\"\$(date +%s)\" --overwrite"
```

### Adım 5: Hash parity verify (hash-authoritative polling)

`scripts/ops/rotate-pg-vault-user.sh` pattern'ini takip eder: resourceVersion bump audit, hash karşılaştırma authoritative.

```bash
EXPECTED="6f765b6d1cc2317f"  # operatörden gelen prefix
DEADLINE=$(($(date +%s) + 120))
while [[ $(date +%s) -lt $DEADLINE ]]; do
  CUR_HASH=$(ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
    get secret auth-service-secrets \
    -o jsonpath='{.data.SPRING_DATASOURCE_PASSWORD}' | base64 -d | \
    sha256sum | head -c 16")
  CUR_RV=$(ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
    get secret auth-service-secrets -o jsonpath='{.metadata.resourceVersion}'")
  if [[ "$CUR_HASH" == "$EXPECTED" ]]; then
    echo "PASS — hash parity (resourceVersion $PRE_RV → $CUR_RV)"
    break
  fi
  sleep 3
done
if [[ "$CUR_HASH" != "$EXPECTED" ]]; then
  echo "FAIL — hash parity not reached in 120s; CUR=$CUR_HASH EXPECTED=$EXPECTED"
  echo "  inspect: kubectl describe externalsecret auth-service-secrets -n platform-test"
  exit 1
fi
```

### Adım 6: Overlay ConfigMap safety hold PR

Hash parity PASS sonrası agent şu PR'ı açar:

**Branch**: `codex/d1.1a-auth-service-config-safety-hold`

**Değişiklikler:**
- `kustomize/overlays/test/kustomization.yaml` auth-service ConfigMap patch:
  - `SPRING_JPA_HIBERNATE_DDL_AUTO: "none"` (live effective ile uyum — geçici safety hold)
  - `SPRING_FLYWAY_ENABLED: "false"` (live effective ile uyum)
  - Inline yorum: "Codex 019e234e iter-5 — temporary safety hold; D1.1b restoration (`validate + Flyway=true`) Flyway state kanıtı sonrası"

**Cross-AI peer review** zorunlu (Claude impl ↔ Codex review). VERDICT AGREE sonrası selective apply.

### Adım 7: Selective apply

```bash
# Pre-apply ConfigMap snapshot (rollback B kaynağı). Live ConfigMap'i
# kaydet; sonradan rollback gerekirse bu snapshot'ı uygula. NOT: kustomize
# HEAD~1 base ile yetinilemez — test overlay'in KEYCLOAK_ISSUER_URI /
# SECURITY_JWT_* / audience patch'leri base'de yok.
#
# Codex 019e258a iter-3 — DEPLOY SNAPSHOT ALMA YASAK: live Deployment
# inline SPRING_DATASOURCE_PASSWORD plaintext taşıyor; agent /tmp'ye
# Deployment YAML yazarsa boundary ihlal olur. Rollback A için
# `kubectl rollout undo` yeterli; deploy snapshot gerekmez.
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test get cm \
  auth-service-config -o yaml > /tmp/auth-cm.pre-d1.1a.yaml"
echo "Pre-apply ConfigMap snapshot: staging-sw:/tmp/auth-cm.pre-d1.1a.yaml"

# Render auth-service deployment + ConfigMap'i izole et
kubectl kustomize kustomize/overlays/test > /tmp/test-overlay.yaml
python3 -c "
import yaml
docs = list(yaml.safe_load_all(open('/tmp/test-overlay.yaml')))
out = {'cm': None, 'deploy': None}
for d in docs:
    if d and d.get('kind') == 'Deployment' and d.get('metadata',{}).get('name') == 'auth-service':
        out['deploy'] = d
    if d and d.get('kind') == 'ConfigMap' and d.get('metadata',{}).get('name') == 'auth-service-config':
        out['cm'] = d
if out['cm']: yaml.safe_dump(out['cm'], open('/tmp/auth-cm.yaml','w'))
if out['deploy']: yaml.safe_dump(out['deploy'], open('/tmp/auth-deploy.yaml','w'))
"

# Apply ConfigMap önce (Deployment env değişimi rollout tetikler)
scp /tmp/auth-cm.yaml /tmp/auth-deploy.yaml halil@staging-sw:/tmp/
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test apply \
  -f /tmp/auth-cm.yaml -f /tmp/auth-deploy.yaml"

# Rollout
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test rollout \
  status deploy/auth-service --timeout=300s"
```

### Adım 8: Smoke

```bash
# Pod state
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test get pod \
  -l app.kubernetes.io/name=auth-service -o wide"
# Beklenen: 1/1 Running, restartCount=0

# Inline env temizliği doğrula
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test get deploy \
  auth-service -o jsonpath='{.spec.template.spec.containers[0].env[*].name}'"
# Beklenen: SPRING_PROFILES_ACTIVE JAVA_TOOL_OPTIONS (sadece 2 inline env)

# Log check
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test logs \
  deploy/auth-service --tail=80 | grep -E 'ERROR|Exception|Hibernate|Flyway|HikariPool'"
# Beklenen: HikariPool-1 Started successfully; ZERO Hibernate update/validate warnings; ZERO Flyway exception

# Stability window
./scripts/deploy/gate-stability-window.sh \
  --service auth-service --context k3d-test --namespace platform-test \
  --catalog docs/operations/services.yaml
# Beklenen: PASS — 180s window (jvm_warmup_extra=true)

# Browser smoke
# testai.acik.com → admin login → /api/v1/authz/me 200 doğrula
```

### Adım 9: Runtime drift detector verify

```bash
ssh halil@staging-sw "cd /home/halil/platform/platform-k8s-gitops && \
  python3 scripts/drift_detection/check_deployment_contracts.py \
  --mode runtime --env test \
  --render-source kustomize/overlays/test --live-context k3d-test \
  --live-namespace platform-test --catalog docs/operations/services.yaml \
  --output text 2>&1 | tail -10"
# Beklenen: 7→6 P1 (auth-service env drift düşmeli)
```

## D1.1b Entry Gate

D1.1b restoration başlamadan önce aşağıdaki D1.1a kapanış şartları sağlanmış olmalı:

- ☑️ Adım 5 hash parity PASS
- ☑️ Adım 7 rollout success
- ☑️ Adım 8 stability window PASS (180s, restartCount=0)
- ☑️ Adım 9 runtime drift detector 7→6 P1 (auth-service env drift kapandı)
- ☑️ Browser smoke testai admin login + `/api/v1/authz/me` 200

Bu şartlar tutturulmadan D1.1b (DDL_AUTO=validate + Flyway=true geçişi) başlatılmaz.

## D1.1b Restoration (Ayrı PR, Daha Sonra)

Bu runbook sadece D1.1a containment'i kapsar. D1.1b kapsamı:
- Flyway migration history doğrulama (`select * from flyway_schema_history limit 10`)
- `SPRING_JPA_HIBERNATE_DDL_AUTO=validate` + `SPRING_FLYWAY_ENABLED=true` geçişi
- Gerekirse V-series migration cleanup

Plan-time consultation D1.1b başlangıcında ayrı Codex thread'de.

## Rollback

D1.1a apply (Adım 7) sırasında pod CrashLoop veya PG auth fail oluştuysa:

### Rollback A: Deployment revision'ı geri al

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test rollout undo \
  deploy/auth-service"
# Pod template eski state'e döner (ConfigMap referansı aynı ama env spec eski)
# Bu yalnız Deployment revision'ı etkiler; ConfigMap data aynı kalır
```

### Rollback B: ConfigMap'i geri al + restart

`kubectl rollout undo` ConfigMap'i revert etmez. Yeni ConfigMap envFrom üzerinden zaten okunuyor. Geri almak için **Adım 7'de alınan live snapshot** kullanılır:

```bash
# B-1 (authoritative): pre-apply snapshot'ı uygula. Live state'i yakaladığı
# için test overlay'in KEYCLOAK_ISSUER_URI / SECURITY_JWT_AUDIENCE / impersonation
# realm patch'lerini koruyor. base render kullanmak YASAK — test overlay
# patch'leri base'de yok.
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test apply \
  -f /tmp/auth-cm.pre-d1.1a.yaml"

# Sonra restart (envFrom değişikliği otomatik rollout tetiklemez)
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test rollout \
  restart deploy/auth-service"

# B-2 (manuel düzeltme; sadece pre-apply snapshot kaybolmuşsa):
# kubectl edit ile DDL_AUTO=update + FLYWAY=false yaz (live effective değerleri
# Adım 1 öncesi neyse onları manuel restore et)
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test edit cm auth-service-config"
```

### Rollback C: Inline env restore (operatör)

Eğer Vault rotation bozulduysa veya Vault canonical farklı bir değere drift olmuşsa, Vault'a güvenmek yerine **Adım 1'de tmpfs'te tutulan known-good inline password** ile inline override geri konur:

```bash
# OPERATOR shell — agent transcript dışı; hidden shell protokolü
# ÖN ŞART: Adım 1'deki $TMP dosyası D1.1a smoke (Adım 8) PASS olana
# kadar tmpfs'te tutulmuş olmalı; trap cleanup smoke PASS sonrasına
# kadar deferred. Smoke PASS ise dosya zaten silindi → rollback C için
# eski Deployment revision template'inden çıkar (kubectl get rs).

# Yöntem 1 — $TMP hâlâ mevcutsa (smoke henüz tamamlanmadı).
# ÖNEMLİ: operator Adım 1'i staging-sw hidden shell'de çalıştırıyor; $TMP
# o shell scope'unda var. ssh wrapper KULLANMA — remote shell $TMP'i göremez
# ve command substitution boş dönerek SPRING_DATASOURCE_PASSWORD="" set eder.
# Komut doğrudan staging-sw hidden shell'de:
kubectl --context k3d-test -n platform-test set env \
  deploy/auth-service SPRING_DATASOURCE_PASSWORD="$(cat "$TMP")"
# NOT: kubectl set env --from-file FLAG DESTEKLEMİYOR; --env-file destekliyor
# ama formatı KEY=VALUE.  Tek key için inline shell substitution kullanılır.

# Yöntem 2 — $TMP silinmişse (smoke PASS sonrası): eski ReplicaSet'ten çıkar
OLD_RS=$(ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get rs -l app.kubernetes.io/name=auth-service \
  --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-2].metadata.name}'")
OLD_PW=$(ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get rs \"$OLD_RS\" -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name==\"SPRING_DATASOURCE_PASSWORD\")].value}'")
# Hidden shell — OLD_PW agent transcript'ine yazılmaz; sadece operator shell'de
# inline substitution ile uygulanır:
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test set env \
  deploy/auth-service SPRING_DATASOURCE_PASSWORD=\"$OLD_PW\""
unset OLD_PW

# YANLIŞ KAYNAK: Vault canonical değeri kullanma — Vault rotation bozulduysa
# orada da yanlış password olabilir. Authoritative kaynak: çalışan eski RS.
```

Inline restore sadece **Vault sync bozulduğunda son çare**; tipik durumda Rollback A+B yeterli.

NOT: `kubectl set env --from-file` flag'i **yok**; sadece `--env-file` (KEY=VALUE formatı) ve inline `KEY=value` substitution destekleniyor. Tek key restore için inline substitution + shell variable kullan.

## Cross-References

- Codex thread: `019e234e-77a5-7e01-8481-57d131512223` (Session 48 D1.1a strategy)
- Codex thread: `019e256f-9219-7951-837f-e4e35c6a0666` (Session 49 boundary clarification)
- Codex thread: `019e258a-9965-70a3-ab14-002353743cbf` (PR #564 peer review iter-1 REVISE absorb)
- Hash-authoritative polling pattern: [`scripts/ops/rotate-pg-vault-user.sh:341-355`](../scripts/ops/rotate-pg-vault-user.sh)
- Drift detector: `scripts/drift_detection/check_deployment_contracts.py`
- Gate 1d: `scripts/deploy/gate-stability-window.sh`
- Runbook (alarm response): `docs/runbooks/deploy-stability-window.md`
- ADR-0010 §2.5 Vault credential lifecycle + boundary matrix
- ADR-0011 §2.3 boundary declaration + GA-002 (ESO approle reads)
- CLAUDE.md HARD RULE Pre-Production Full Authority (2026-04-29)
- CLAUDE.md HARD RULE Kullanıcı Aktif Credential (2026-04-29)

## Authority Statement (özet)

> Pre-prod context'inde agent ESO sync, GitOps PR, selective apply, smoke için tam yetkili (kubectl/system credential ops). **Plaintext credential extraction veya Vault write** scope dışı — operator hidden-shell'de yapılır, agent yalnızca hash prefix (16 char) + status sinyali alır.
