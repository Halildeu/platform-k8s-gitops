# Runbook — D1.1a auth-service Vault Password Rotation Containment

> Codex 019e234e + 019e256f Session 48/49 strategic consultation — D dalga 1.1 containment.
> Plus boundary: agent vs operator authority per CLAUDE.md HARD RULE Pre-Production Full Authority + ADR-0011 §2.5.

## Bağlam

2026-05-13 Session 48 supplement'inde tespit edildi: auth-service test cluster pod inline `SPRING_DATASOURCE_PASSWORD` ile çalışıyor (hash `6f765b6d1cc2317f`); Vault canonical secret farklı hash (`808bc9ef23cfa266`). Sibling servisler (user-service, permission-service) Vault canonical ile uyumlu.

**Risk:** Inline override aktif; eğer kaldırılırsa envFrom Secret'tan farklı password gelir → PG auth fail → CrashLoop. Plus ConfigMap'te `SPRING_JPA_HIBERNATE_DDL_AUTO=update + SPRING_FLYWAY_ENABLED=false` schema mutation tehlikesi (inline `none` ile override edilmiş).

## Authority Boundary

| Step | Aktör | Sebep |
|---|---|---|
| 1. Inline password değerini çıkar (kubectl jsonpath) | **Agent** | Read-only system credential metadata; CLAUDE.md Pre-Production Full Authority kapsamı |
| 2. Plaintext password'ü Vault'a yaz | **Operator** | Plaintext credential handling + Vault root token; ADR-0011 §2.5 user-approval gate |
| 3. Vault root token / unseal material handling | **Operator** | Codex 019e256f: "agent'ın root token üretmesi/unseal yoluna girmesine izin verme" |
| 4. ESO force-sync (kubectl annotate) | **Agent** | System credential ops; kubectl-level operation |
| 5. Secret hash parity verify | **Agent** | Read-only verification (hash prefix kanıt, plaintext değil) |
| 6. Overlay ConfigMap safety hold PR | **Agent** | GitOps PR akışı; HARD RULE cross-AI peer review |
| 7. Selective apply auth-service | **Agent** | Pre-prod Full Authority kapsamı |
| 8. Rollout smoke + browser/API verify | **Agent** | Standard verification |

## Operatör Adımları (Hidden Shell)

Bu kısım kullanıcı/operatörün **agent context dışında** çalıştırması gereken adımlardır. Plaintext password agent transcript'inde, log'da veya commit history'de görünmemeli.

### Adım 1: Inline password'ü çıkar

```bash
# Operatör staging-sw'da:
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test get deploy auth-service \
  -o json | jq -r ".spec.template.spec.containers[0].env[] | \
  select(.name==\"SPRING_DATASOURCE_PASSWORD\") | .value"' \
  | head -c 100 > /tmp/auth-pw.tmp
# hash önizleme (plaintext değil):
sha256sum /tmp/auth-pw.tmp | head -c 16
# Beklenen: 6f765b6d1cc2317f
```

### Adım 2: Vault'a yaz

Vault unseal + temp token. Operatör shell:
```bash
# Eğer Vault sealed ise unseal (3 unseal key gerekli):
docker exec -it platform-vault-test vault operator unseal <key1>
docker exec -it platform-vault-test vault operator unseal <key2>
docker exec -it platform-vault-test vault operator unseal <key3>

# Root login (init token):
docker exec -it platform-vault-test vault login <root-token>

# Password patch:
docker exec -i platform-vault-test vault kv patch \
  kv/platform/auth-service db_password=@/tmp/auth-pw.tmp

# Verify (hash prefix only):
docker exec platform-vault-test vault kv get -field=db_password \
  kv/platform/auth-service | sha256sum | head -c 16
# Beklenen: 6f765b6d1cc2317f (inline ile match)

# Cleanup:
rm /tmp/auth-pw.tmp
```

### Adım 3: Onay sinyali

Operatör adımları tamamlayıp agent'a şunu söyler:
- "Vault rotation tamamlandı"
- "Hash parity PASS (16 char prefix: 6f76b6d1cc2317f)"

Agent bundan sonra Adım 4'ten devam eder.

## Agent Adımları

### Adım 4: ESO force-sync

```bash
kubectl --context k3d-test -n platform-test annotate externalsecret \
  auth-service-secrets force-sync="$(date +%s)" --overwrite
sleep 5
# Doğrula:
kubectl --context k3d-test -n platform-test get externalsecret auth-service-secrets \
  -o jsonpath='{.status.refreshTime}{"\n"}{.status.conditions[0].status}{"\n"}'
# Beklenen: yeni refreshTime + status: "True"
```

### Adım 5: Hash parity verify (agent-side)

```bash
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test \
  get secret auth-service-secrets -o jsonpath="{.data.SPRING_DATASOURCE_PASSWORD}" \
  | base64 -d | sha256sum | head -c 16'
# Beklenen: 6f765b6d1cc2317f
```

Eşleşmezse: ESO sync gecikmeli olabilir; 30s bekle + retry. 2 retry sonrası fail ise operator escalation.

### Adım 6: Overlay ConfigMap safety hold PR

Hash parity PASS sonrası agent şu PR'ı açar:

**Branch**: `codex/d1.1a-auth-service-config-safety-hold`

**Değişiklikler**:
- `kustomize/overlays/test/kustomization.yaml` auth-service ConfigMap patch:
  - `SPRING_JPA_HIBERNATE_DDL_AUTO=none` (live effective ile uyum — geçici safety hold)
  - `SPRING_FLYWAY_ENABLED=false` (live effective ile uyum)
  - Yorum: "Codex 019e234e iter-5 — temporary safety hold; D1.1b restoration (`validate + Flyway=true`) Flyway state kanıtı sonrası"

**Cross-AI peer review** zorunlu (Claude impl → Codex review). VERDICT AGREE sonrası selective apply.

### Adım 7: Selective apply

```bash
# Render auth-service deployment'ı izole et
kubectl kustomize kustomize/overlays/test > /tmp/test-overlay.yaml
python3 -c "
import yaml
docs = list(yaml.safe_load_all(open('/tmp/test-overlay.yaml')))
for d in docs:
    if d and d.get('kind') == 'Deployment' and d.get('metadata',{}).get('name') == 'auth-service':
        yaml.safe_dump(d, open('/tmp/auth-deploy.yaml', 'w')); break
    if d and d.get('kind') == 'ConfigMap' and d.get('metadata',{}).get('name') == 'auth-service-config':
        yaml.safe_dump(d, open('/tmp/auth-cm.yaml', 'w'))
"

# Apply
scp /tmp/auth-deploy.yaml halil@staging-sw:/tmp/
scp /tmp/auth-cm.yaml halil@staging-sw:/tmp/
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test apply -f /tmp/auth-cm.yaml -f /tmp/auth-deploy.yaml"

# Rollout
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test rollout status deploy/auth-service --timeout=180s"
```

### Adım 8: Smoke

```bash
# Pod state
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test get pod \
  -l app.kubernetes.io/name=auth-service -o wide"
# Beklenen: 1/1 Running, restartCount=0

# Inline env temizliği doğrula
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test get deploy auth-service \
  -o jsonpath='{.spec.template.spec.containers[0].env[*].name}'"
# Beklenen: SPRING_PROFILES_ACTIVE JAVA_TOOL_OPTIONS (sadece 2 inline env)

# Log check
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test logs deploy/auth-service \
  --tail=50 | grep -E 'ERROR|Exception|Hibernate|Flyway|HikariPool'"
# Beklenen: No ERROR/Exception; HikariPool-1 Started successfully; no Hibernate validate/update warnings

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

## D1.1b Restoration (Ayrı PR, Daha Sonra)

Bu runbook sadece D1.1a containment'i kapsar. D1.1b kapsamı:
- Flyway migration history doğrulama (`select * from flyway_schema_history limit 10`)
- `SPRING_JPA_HIBERNATE_DDL_AUTO=validate` + `SPRING_FLYWAY_ENABLED=true` geçişi
- Gerekirse V-series migration cleanup

Codex thread sırada açılacak D1.1b başlangıcında.

## Rollback

Eğer Adım 7-8 sırasında pod CrashLoop veya PG auth fail:

```bash
# Rollback deployment
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test rollout undo \
  deploy/auth-service"

# Veya ConfigMap restore (eğer ConfigMap patch sebep oldu)
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test get cm \
  auth-service-config -o yaml | grep -A2 SPRING_JPA"
# DDL_AUTO eski değere döndü mü kontrol
```

Plus inline env restoration (Vault sync bozulduysa):
```bash
# Live inline override geri koy (operatör)
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test set env \
  deploy/auth-service SPRING_DATASOURCE_PASSWORD=<original-value>"
```

## Cross-References

- Codex thread: `019e234e-77a5-7e01-8481-57d131512223` (Session 48 D1.1a strategy)
- Codex thread: `019e256f-9219-7951-837f-e4e35c6a0666` (Session 49 boundary clarification)
- Drift detector script: `scripts/drift_detection/check_deployment_contracts.py`
- Gate 1d script: `scripts/deploy/gate-stability-window.sh`
- Runbook (related): `docs/runbooks/deploy-stability-window.md`
- ADR-0010 §2.5 boundary matrix
- ADR-0011 §2.3 boundary declaration
- CLAUDE.md HARD RULE Pre-Production Full Authority (2026-04-29)
- CLAUDE.md HARD RULE Kullanıcı Aktif Credential (2026-04-29) — admin@example.com login user'a dokunma; ama auth-service DB credential system credential, agent kapsamı

## Authority Statement (özet)

> Pre-prod context'inde agent system credential ops için tam yetkili (kubectl, SSH, ESO sync). Vault root token üretimi/unseal material handling **plaintext credential exposure** sınıfı; bu adım operatör hidden-shell'de yapılır, agent redacted output ile işine devam eder.
