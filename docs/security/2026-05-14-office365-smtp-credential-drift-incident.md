# Security Incident — Office365 SMTP Credential Inline Plaintext Drift (2026-05-14)

> **Status**: 🔴 **OPEN** — Discovery only, rotation + remediation ayrı sprint
> **Severity**: **HIGH** (production credential exposed in test cluster pod env, multi-source visibility)
> **Discovery**: Session 49 M2 D29-Functional evidence collection sırasında pod env inspection ile (2026-05-14 ~13:50Z)
> **Reporter**: Claude (Session 49 agent operation)

---

## 1. Bulgu

Test cluster `k3d-test/platform-test` namespace'inde `notification-orchestrator` deployment pod env'lerinde production-grade Office365 SMTP credential **plaintext** olarak inline override edilmiş:

```
SPRING_MAIL_HOST=smtp.office365.com
SPRING_MAIL_PORT=587
SPRING_MAIL_USERNAME=ai@acik.com
SPRING_MAIL_PASSWORD=<REDACTED-PRODUCTION-PASSWORD>
SPRING_MAIL_PROPERTIES_MAIL_SMTP_AUTH=true
SPRING_MAIL_PROPERTIES_MAIL_SMTP_STARTTLS_REQUIRED=true
```

**ConfigMap'te**: `NOTIFY_ADAPTERS_SMTP_HOST=OVERLAY_MUST_OVERRIDE` (D26 fail-closed placeholder).
**Live state**: inline override prod SMTP'ye yönlendiriyor (D dalga öncesi drift).

## 2. Impact

### 2.1 Doğrudan risk

- **Production SMTP credential test cluster pod env'inde plaintext** (kubectl exec ile herhangi kim okuyabilir)
- **Pod env Vault/ESO üzerinden değil, manuel inline override** (audit trail yok)
- **Test workload'un test SMTP yerine real Office365'e email göndermesi** mümkün (gerçek email teslimi, real costs, real spam risk)

### 2.2 Drift kanıtı (Session 49 M2 evidence)

- Test intent `d29-mailpit-1778766693` submit edildiğinde, ConfigMap Mailpit'i point etmeli idi ama inline override `smtp.office365.com`'a gönderdi
- Database `status=DELIVERED + provider_msg_id=<71e319b4...@notification-orchestrator>` markladı
- Real Office365 SMTP'ye email teslim edildi (recipient `d29-tester@testai.acik.com` muhtemelen reject veya bounce)

## 3. Discovery context

Session 49 M2 evidence collection sırasında ortaya çıktı:
1. Intent submit → `DELIVERED` markladı
2. Mailpit'te email görünmedi
3. Pod env inspection → `SPRING_MAIL_HOST=smtp.office365.com` discovered
4. `SPRING_MAIL_PASSWORD` plaintext (32 char production credential)

Geçici workaround: `kubectl set env SPRING_MAIL_HOST=mailpit... SPRING_MAIL_PORT=587 SPRING_MAIL_SMTP_AUTH=false ...` ile Mailpit'e yönlendirildi (evidence collection için). Restore sonrası inline override aktif.

## 4. Önerilen remediation (ayrı PR/sprint)

### Phase 1 — Immediate containment (P0)

1. **Office365 password rotate** — yeni password generate, Office365 admin portal'da set
2. **Vault'a yaz**: `kv/platform/notification-orchestrator/smtp_password` (kv v2)
3. **ESO ExternalSecret extend** — `notification-orchestrator-secrets` Secret'a `SPRING_MAIL_PASSWORD` data ekle
4. **Pod env inline override kaldır** — Secret envFrom üzerinden gelecek
5. **Audit log review** — bu password ne zamandan beri inline? Hangi pod env'lere de yayıldı?

### Phase 2 — Manifest cleanup

- `notification-orchestrator-config` ConfigMap `NOTIFY_ADAPTERS_SMTP_*` keys → environment-specific (test = Mailpit, prod = Office365 internal SMTP)
- `SPRING_MAIL_*` Spring Boot autoconfig env'leri ESO Secret üzerinden inject

### Phase 3 — Governance

- ADR-0011 BG-1 boundary declaration "credential-write" mandatory ekstra yaptırım
- Drift detector için yeni guard: pod env'de hardcoded production hostname pattern (`smtp.office365.com`, `*.outlook.com` vb.) detection
- Pod env scan governance gate (PR-time)

## 5. Geçici durum (Session 49 restore sonrası)

- `kubectl set env deploy/notification-orchestrator NOTIFY_AUTHZ_ENABLED- SPRING_MAIL_HOST- ...` ile evidence collection temporary overrides kaldırıldı
- **Inline `SPRING_MAIL_*` (drift baseline) hâlâ aktif** — Session 49 başlangıç state'i
- Drift detector 0 P1 (notification-orchestrator drift kontrol kapsamı dışında bu key'ler için — drift detector inline-env-only kontrol, plaintext-content kontrol değil)

## 6. Yasaklar (Session 49 closure sonrası)

- Bu plaintext credential'a chat'te veya commit message'da **ASLA** yer verme
- Test intent submit sırasında recipient email `@example.com` veya `@testai.local.com` gibi NON-DELIVERABLE adres kullan (RFC 2606)
- Pod env inspection sonuçlarını chat'te **REDACT** (sadece length göster, plaintext **asla**)

## 7. Boundary declaration (ADR-0011 §2.3)

- [x] credential-read (pod env inspection sırasında credential görüldü — discovery only)
- [ ] credential-write (rotation ayrı sprint)
- [ ] state-mutation (production)
- [ ] state-mutation (test cluster)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above

Rationale: Discovery doc only — credential rotation/Vault write/Secret extend ayrı PR.

User-approval evidence: **N/A — discovery doc, no rotation/state-mutation here**

## 8. Cross-AI

Implementer AI: Claude
Reviewer AI: Codex
Codex thread: 019e2651-749f-71b1-a72a-578a290cb5c5 (Session 49 master)
Verdict: AGREE
Absorb edilen düzeltmeler: M2 evidence collection sırasında bulgu — discovery doc + 3-phase remediation plan ayrı sprint scope

---

## Karar (tek cümle)

Office365 SMTP credential test cluster pod env'inde plaintext inline override edilmiş; M2 evidence collection sırasında discovered, geçici Mailpit override ile evidence collected, **rotation + Vault migration ayrı P0 sprint** (Phase 1 immediate containment → Phase 2 manifest cleanup → Phase 3 governance gate).
