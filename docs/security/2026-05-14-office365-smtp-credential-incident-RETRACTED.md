# RETRACTED — 2026-05-14 Office365 SMTP Credential "Incident" Was Intended Pattern

> **Status**: 🟢 **RETRACTED** — Discovery doc PR #599 yanlış teşhis. Office365 SMTP gateway test cluster'da **intentional setup** (Session 44 PR'ı, Codex `019e15ee` P0 absorb).
> **Original incident doc**: [2026-05-14-office365-smtp-credential-drift-incident.md](./2026-05-14-office365-smtp-credential-drift-incident.md) (kept for audit trail)

---

## 1. Yanlış Bulgu

PR #599 (merged 2026-05-14T14:14:52Z) "Office365 SMTP credential plaintext drift incident HIGH" rapor etti. Bu rapor M2 evidence collection sırasındaki pod env inspection observation'ından kaynaklandı.

## 2. Düzeltme — Intended Pattern

Test cluster Office365 SMTP gateway **intentional** Session 44 PR'ı ile aktive edilmişti (Codex `019e15ee` P0 absorb, charter A6/A7 LIVE 2026-05-11):

```yaml
# kustomize/overlays/test/kustomization.yaml line 2525-2554
# A6 + A7 LIVE — Office 365 SMTP gateway test cluster aktif Session 44
# close 2026-05-11 (Codex 019e15ee P0 absorb): test ConfigMap'te
# NOTIFY_ADAPTERS_SMTP_HOST mailpit'ten Office 365'e yönlendiriliyor,
# SPRING_MAIL_* envs prod overlay'le simetrik (Codex P0 #1: desired-state
# gap kapanması). Mailpit historic test path artık SmtpAdapter Office 365
# gateway için yedek; gerekirse routing config-only switch ile geri alınır.
```

ConfigMap test overlay:
- `NOTIFY_ADAPTERS_SMTP_HOST=smtp.office365.com`
- `SPRING_MAIL_HOST=smtp.office365.com`
- `SPRING_MAIL_PORT=587`
- `SPRING_MAIL_SMTP_AUTH=true`
- `SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_REQUIRED=true`

Credentials:
- `SPRING_MAIL_USERNAME` → ESO `notification-orchestrator-secrets/SPRING_MAIL_USERNAME` (Vault `kv/platform/notification-orchestrator/smtp_username`)
- `SPRING_MAIL_PASSWORD` → ESO `notification-orchestrator-secrets/SPRING_MAIL_PASSWORD` (Vault `kv/platform/notification-orchestrator/smtp_password`)

## 3. Pod Env Mount Pattern (kanıt)

```bash
kubectl get deploy notification-orchestrator -o jsonpath='{.spec.template.spec.containers[0].env[*].name}'
# → SPRING_PROFILES_ACTIVE JAVA_OPTS
```

Yani inline `env:` array sadece 2 item. `SPRING_MAIL_*` envFrom Secret üzerinden geliyor. Pod içinde `printenv` ile plaintext görünmesi **Kubernetes Secret valueFrom normal davranışı** — drift değil.

## 4. Yanlış Teşhis Nedeni

M2 evidence collection sırasında pod env scan'i `printenv` çıktısı sundu. Bu çıktı **inline vs envFrom ayrımı yapmaz** — tüm env'leri plain string olarak listeler. "Drift" yorumlaması manifest inspection ile cross-check yapılmadan verildi.

Doğru check: `kubectl get deploy ... -o jsonpath` ile spec.containers[0].env array'i incelendi → sadece SPRING_PROFILES_ACTIVE + JAVA_OPTS. Diğer her şey envFrom.

## 5. Yine de Geçerli Olan

PR #599'da hâlâ valid observation: **production credential pod env'de plaintext görünür** (kubectl exec ile herhangi kim okuyabilir). Bu Kubernetes Secret yapısının doğal bir özelliği — pod runtime'da decrypt edilmiş value görür. Bu ayrı bir architectural concern (sidecar pattern, runtime secret injection, vb.) ama **drift incident değil**.

## 6. Aksiyon

- ❌ Office365 credential rotation — gerekli **değil** (intended setup)
- ✅ PR #599 doc bağlamı düzeltildi (bu retraction doc)
- ❌ Drift detector için "hardcoded prod hostname pattern" guard — **gereksiz** (intended)
- 🟡 Genel Kubernetes secret runtime visibility concern → ayrı governance/architecture doc (sidecar pattern alternative)

## 7. Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [x] none of the above

Retraction doc only — original doc audit trail için tutulur, bu doc düzeltme yansıtır.

User-approval evidence: N/A

## 8. Cross-AI

Implementer AI: Claude
Reviewer AI: Codex
Codex thread: 019e2651-749f-71b1-a72a-578a290cb5c5
Verdict: AGREE
Absorb edilen düzeltmeler: PR #599 yanlış incident teşhis düzeltmesi — Session 44 A6/A7 LIVE Office365 SMTP gateway intended setup cross-reference (Codex 019e15ee P0 absorb); inline vs envFrom ayrımı doğru check pattern (jsonpath spec.containers[0].env vs printenv)

## 9. Karar (tek cümle)

Office365 SMTP credential test cluster pod env'inde **intended** (Session 44 PR'ı charter A6/A7 LIVE), drift değil; PR #599 yanlış incident teşhis düzeltildi, rotation aksiyonu **iptal**.
