# Endpoint-Admin-Service ↔ platform-k8s-gitops Uyum Mutabakatı

> **Status:** AGREE (mutabakat sağlandı) | **Severity:** Plan-time governance review | **Codex thread:** `019dd895-17c1-79f0-b652-e316f64d4d79` (iter-1 PARTIAL → iter-2 PARTIAL → **iter-3 AGREE** + 4 non-blocking precision edit)
> **Tarih:** 2026-04-29
> **Kapsam:** Ayrı repo'da geliştirilen endpoint-admin-service (Go agent + Windows + REST/queue admin API) projesinin platform-k8s-gitops governance modeline uyumu
> **Türev karar:** ADR-0012-EA (Endpoint Admin Service Governance Charter) açılması zorunlu

---

## TL;DR

Endpoint-admin-service mevcut platform-k8s-gitops kurallarına **şartlı uyabilir**. Mutabık kalınan ana kararlar:

1. **Manifest aynı repo, izolasyon repo değil G7 ile**: `kustomize/base/apps/endpoint-admin-service` ve overlay'ler bu repo'ya gelir; `platform-{test,prod}` namespace'ini paylaşır; izolasyon ayrı ServiceAccount + NetworkPolicy + ResourceQuota + ExternalSecret path + DB role + OpenFGA writer credential + ArgoCD application boundary ile sağlanır.
2. **OpenFGA shared store + dedicated validated tuple writer**: Mevcut store paylaşılır (cross-resource policy gereği), ama endpoint domain tuple yazımı validation katmanlı **dedicated writer** üzerinden olur. Tenant anchor `OUR_COMPANY` (V25 semantiği) zorunlu; `organization:default` tek başına yeterli değil.
3. **Spring miras yok — Go-tier governance gap**: Permission-service annotation/middleware örüntüsü Go için kanıt sayılmaz; equivalent contract gerekli (`RequireModule(...)` middleware + `/v1/authz/me` Go eşdeğeri + JWT validation + outbox payload + DD-EA-6 alignment guard).
4. **7×3 uyum matrisi**: D29 üçlüsü (Up/Functional/Zanzibar-ready) endpoint domain için 7 boyuta genişletilir (G1-G7); 21 hücre × 3 katman, P0/P1/P2 etiketli, ilgisiz hücreler "N/A gerekçeli".
5. **8 governance guard**: ADR-0011 analoğu DD-EA-1..7 + BG-EA-1.
6. **D35-EA ladder**: 6 katman; D35-EA-2 yalnızca **benign command flow** (`collect_status`/`inventory_ping`); destructive komutlar D35-EA-4-A..E olarak sınıf-spesifik dual-control gate'lerde.
7. **Code signing supply-chain RoT**: Vault/ESO ile taşınmaz; Azure Trusted Signing default, on-prem HSM regülasyon fallback'i; lab tier'da self-signed `lab-only-evidence` etiketi zorunlu.
8. **Pilot tier matrisi**: Parallels = lab-only, IT-owned domain-joined VM = pilot, gerçek kullanıcı makinesi = restricted. İmzasız binary / tamper bypass / password reset sadece lab tier'da kabul.
9. **Password reset 4 connector**: Lokal Windows / Domain AD / Entra / M365 ayrı domain; identity discovery paralel read-only başlasın.
10. **ADR-0012-EA + Faz 22 PLAN.md**: Bu rapor charter draft'ı; 5 açık nokta kullanıcı clarify ile dolduruldukça ADR'a indirilir.

**Bloklayıcı**: ADR-0012-EA açılmadan + DD-EA-1..7 + BG-EA-1 yeşil olmadan + D35-EA P0 gate koşulmadan canlı deploy yapılmaz. Mevcut "BE-009 / BE-013 / BE-011 live smoke açık" tek satır kanıt sayılmaz.

---

## 1. Bağlam

### 1.1 Tetik

Kullanıcı 2026-04-29 oturumunda, ayrı bir Codex/Claude session'ında geliştirdiği "endpoint-admin-service" projesinin yol haritasını paylaştı (Windows agent + Go backend + REST admin API + command queue + audit + maintenance token + OpenFGA RBAC). Soru: **Bu backend bizim platform-k8s-gitops repo kuralları ile uyumlu mu?**

Backend kodu görülmedi; sadece roadmap özeti + status tablosu + 4 connector password reset planı + identity discovery paketi önerisi temel alındı. Kullanıcının paylaştığı bilgiler şunları içeriyordu:

- Go agent foundation (enrollment, signed heartbeat, command poll, result submit) DONE.
- Windows service install/uninstall Parallels Win11'de doğrulanmış.
- BE-009 RBAC/OpenFGA: lokal kod/test/docker kanıtı var; **OpenFGA live store/model tuple seed + k8s smoke açık**.
- BE-013 maintenance/uninstall token: lokal kod/test kanıtı var; **image/GitOps/live smoke açık**.
- GitOps handoff: eski image digest ile test runtime smoke alınmış.
- Web MFE TODO; Pilot WAITING_IT; Password reset BLOCKED.

### 1.2 Süreç

Mutabakat üç tur Codex MCP ping-pong ile sağlandı:

| Iter | Verdict | Konu |
|---|---|---|
| 1 | PARTIAL | A/C koşullandırma, B sertleşme (Go-tier gap), +2 governance ek (DD-EA-6, BG-EA-1), 8 eksik boyut, 10 açık soru |
| 2 | PARTIAL | G7 ayrı boyut talebi, D35-EA-2 benign-only sınırlama, DD-EA-7 update governance ekleme, 2 caveat (`organization:default` global, tuple writer validation) |
| 3 | **AGREE** | `ready_for_user_report=true`, 4 non-blocking precision edit (tuple syntax, writer claim yumuşatma, 63-noktası bürokrasi, ArgoCD boundary netlik) |

Codex'in sağladığı değer: ön-değerlendirmedeki "ortak store + namespace izolasyon" varsayımının yanlışlığı, "Spring kuralları Go için geçerli değil" çıkarımının yanlışlığı, "audit boundary repo ile çözülür" varsayımının yanlışlığı, ve "auto-update wormhole" gibi G6 supply-chain'inde gözden kaçan boyutlar.

### 1.3 Bu raporun amacı

Bu doküman:
- Mutabakat noktalarını **kalıcı referans** olarak korur.
- ADR-0012-EA için **charter draft** sağlar.
- Kullanıcı clarify gerektiren 5 noktayı **fill-in placeholder** ile işaretler.
- Pilot ön-koşulu olan governance guard ve D35-EA ladder'ı **uygulanabilir kapı listesi** olarak yazar.
- Endpoint-admin-service ekibine (kullanıcı + ayrı Codex session'ı) **AGENTS.md/CLAUDE.md import** öncesi temel uyum sözleşmesi oluşturur.

### 1.4 Bu rapor ADR DEĞİLDİR

ADR-0012-EA henüz açılmadı çünkü 5 açık noktada kullanıcı clarify gerekli (endpoint repo URL, admin auth realm, pilot tier, code signing provider, 5 domain inventory). Bu rapor charter draft + mutabakat protokolü; ADR oluşturulduğunda referans verilecek.

---

## 2. Kapsam ve Sınırlamalar

### 2.1 Kapsam

| Konu | Kapsam dahil | Kapsam dışı |
|---|---|---|
| Endpoint backend governance | ✅ | Backend kodu inceleme |
| Go agent governance | ✅ (kullanıcı özetinden inference) | Agent kod review |
| Windows service governance | ✅ (lab/pilot/user tier) | Windows COM/registry detayları |
| GitOps deploy modeli | ✅ (manifest + namespace + isolation) | Cluster ops detayları |
| OpenFGA model tasarımı | ✅ (tuple syntax + writer + tenant anchor) | Permission catalog tam tasarım |
| Audit/forensik tasarım | ✅ (outbox + WORM + hash chain seviyesinde) | KVKK hukuk metni |
| Code signing | ✅ (provider tier + RoT + ADR exception) | HSM tedarikçi seçimi |
| Password reset domain | ✅ (4 connector + dual-control class) | AD/Entra/M365 connector mimarisi |

### 2.2 Sınırlamalar (kabul edilen belirsizlikler)

- **Endpoint-admin-service kodu görülmedi**: tüm değerlendirme kullanıcı özeti + Codex adversarial inference üzerine. Kod paylaşılırsa mutabakat noktaları **doğrulanmalı**, çelişki çıkarsa `revize` iter açılmalı.
- **Endpoint repo URL bilinmiyor**: AGENTS.md / CLAUDE.md / context-priority kopyası mevcut mu, mevcut platform PR boundary template'i kullanılıyor mu doğrulanmadı.
- **5 domain + Entra tenant** envanteri kullanıcı/IT tarafında; identity discovery paralel read-only başlatılarak boşluk doldurulmalı.
- **Pilot Windows tier** kararı kullanıcı clarify gerektirir (Parallels lab kabul ama IT-owned VM = pilot mı yoksa daha sıkı isolation mı?).

### 2.3 Yorumlama gate

Bu rapor canonical kural seti DEĞİLDİR. [AGENTS.md](../AGENTS.md) + [docs/context-priority-rules.md](context-priority-rules.md) önce okunur. Çelişki halinde:
1. Global CLAUDE.md HARD RULE (Pre-Production Full Authority + Türkçe + No Fake Work + Plan Consensus + kullanıcı login user şifresi yasağı)
2. Repo CLAUDE.md HARD RULE (D29, D30, D17, ADR-0010, ADR-0011, Continuous Autonomous Mode)
3. ADR-0010 + ADR-0011 + ADR-0012-EA (eklenmemiş, draft bu rapor)
4. Bu rapor (cross-repo governance assessment)

---

## 3. Codex Iter Timeline (özet)

### 3.1 İter-1 PARTIAL — Adversarial baseline

**Codex'in sertleştirdiği 5 nokta**:

1. **OpenFGA "ortak store + namespace" → koşullu**: 6 senaryoda ayrı store daha güvenli (destructive command, role separation, tuple churn, model rollout, compromised backend, regülasyon). **Namespace ≠ izolasyon** kritik nüans.
2. **"Spring kuralları Go için geçerli değil" → YANLIŞ**: kurallar dil bağımsız; Go equivalent contract gerek (`RequireModule` middleware + JWT validation + `/v1/authz/me` eşdeğeri + outbox + DD-5 analog).
3. **"Single-repo audit boundary" → repo bölünmeyle çözülmez**: 4 koşul gerçekleşince ayrı GitOps; aksi halde aynı repo + ayrı app/SA/netpol/quota/ExternalSecret boundary.
4. **"Pre-prod full authority Windows pilot" → lab-only**: tier matrisi (lab VM / IT-owned / gerçek kullanıcı); imzasız binary lab kabul ama "unsigned/lab evidence" etiketli.
5. **Password freeze + identity paralel read-only kabul**.

**Codex'in eklediği 8 eksik boyut**: endpoint identity modeli, command authz modeli, dual-control/break-glass, agent binary supply chain, audit immutability, Go CI guard seti, operational isolation, D35-EA ladder.

**Codex'in eklediği 2 ek governance**: DD-EA-6 (Go route-authz metadata guard) + BG-EA-1 (endpoint-device boundary).

### 3.2 İter-2 PARTIAL — Framework refinement

**3 revizyon talebi**:
- **G7 Operational Isolation ayrı boyut** (G1-G6'ya dağıtılmamalı)
- **D35-EA-2 yalnızca benign command** (`collect_status`/`inventory_ping`); destructive komutlar D35-EA-4-A..E sınıf-spesifik gate
- **DD-EA-7 Update Channel Governance Guard** ekleme (auto-update wormhole'u TUF analog ile kapat)

**2 caveat**:
- `organization:default` endpoint cihaz sahipliği için fazla global → tenant `OUR_COMPANY` predicate zorunlu
- Dedicated tuple writer endpoint DB outbox'ını körü körüne tüketirse compromised backend dolaylı yazar → validation invariant'ları gerekli

**Codex skeleton'ları**:
- D35-EA-2 11-step (benign command, signed heartbeat, replay nonce reject)
- 5 sınıf dual-control hibrit tier (read-only / bounded / uninstall / tamper / password / arbitrary exec)
- Code signing tier (Azure Trusted Signing / Azure KV HSM / DigiCert / on-prem HSM)
- Lab VM 7 minimum kriter

### 3.3 İter-3 AGREE — Konsolide framework + 4 precision edit

**AGREE + `ready_for_user_report=true`**. 4 non-blocking precision edit (rapora absorb edildi):

1. **OpenFGA tuple syntax**: `OUR_COMPANY:<tenant_id>` literal object type yazma riski → mevcut platform pattern'i `wc-our-company-<COMP_ID>` namespace formuna yakın; tercih `device:<id>#owned_by@company:wc-our-company-<tenant_id>` veya yeni type `our_company:<tenant_id>` (ADR-0012-EA model genişlemesi).
2. **Tuple writer "imkansız" → yumuşatma**: business-domain blast radius kapatılır; endpoint-domain misuse riski tenant predicate + device binding + schema validation + hash chain + signed approval + class-specific dual-control ile sınırlandırılır.
3. **63 atomik kanıt → bürokrasi engeli**: 21 hücre × 3 katman; her BE-item her hücreye girmek zorunda değil; **N/A gerekçeli** + **P0/P1/P2 etiketli**.
4. **G7 ArgoCD boundary netlik**: ayrı GitOps repo yok + aynı namespace + ayrı ArgoCD app + ayrı SA + netpol + ExternalSecret + DB role + OpenFGA writer cred + explicit ResourceQuota.

---

## 4. Tezler — Detaylı Mutabakat

### 4.1 Tez A — OpenFGA store kararı

**Ön-değerlendirme**: "Ortak store + endpoint namespace (`device:`, `command:`)"; cross-resource policy için yeterli.

**Codex itirazı**: Namespace izolasyon değil. Ortak store ancak şu koşullarda doğru: aynı identity, aynı tenant anchor, aynı admin/persona modeli, gerçek cross-resource policy ihtiyacı. Ayrı store 6 senaryoda daha güvenli:

1. Endpoint komutları destructive (uninstall, tamper bypass, password reset, remote command).
2. Endpoint admin rolü platform admin'den ayrılmalı.
3. Tuple churn yüksek (heartbeat/device state authz tuple'larına karışmamalı).
4. Model rollout/rollback bağımsız yürümeli.
5. Compromised endpoint backend business-domain tuple yazma yetkisinde olmamalı.
6. Audit/regülasyon endpoint command-plane'i ayrı tutmayı gerektiriyor.

**Mutabakat (son hâl)**:

- **Karar**: Mevcut `openfga` store **paylaşılır** (cross-resource policy gereği — örn. `organization:default#superAdmin` zaten mevcut PR #20 architectural unification ile çalışıyor).
- **Dedicated validated tuple writer**: endpoint-admin-service backend **doğrudan OpenFGA write yapmaz**. Outbox poller (mevcut platform pattern) endpoint domain için ya ikinci instance ya da namespace-segregated channel olarak deploy edilir. Compromised endpoint backend → outbox row sızar ama writer validation business tuple yazımını engeller.
- **Tenant anchor zorunlu**: `device:<id>#owned_by@company:wc-our-company-<tenant_id>` (V25 semantiği). `organization:default` tek başına yetersiz; multi-tenant pre-prod future-proof.
- **Object types**: `device:`, `agent:`, `command:`, `maintenance_token:` ayrı; cross-resource yetki için existing types (`organization:`, `module:`, `user:`) ek tier olarak bağlanır.
- **Conditional**: 6 senaryon dan herhangi biri "evet" olursa ayrı store fallback'i ADR-0012-EA içinde belgelenir; karar plan-time Codex iter ile yeniden açılır.

**Kanıt katmanı**: G3 (Identity/Auth) Zanzibar-Secured + G4 (Command/Authz) Zanzibar-Secured + G7 (Operational Isolation) Zanzibar-Secured.

### 4.2 Tez B — Spring/Go governance gap

**Ön-değerlendirme**: Spring `@RequireModule` annotation guard mevcut; Go backend için "Spring-only kurallar geçerli değil mi?" sorusu açık.

**Codex itirazı**: Yanlış. Kurallar dil bağımsız; Spring guard implementasyonu Spring'e özgü ama **kural** Go için aynı geçerli. Spring annotation varlığı Go servis için kanıt üretmez.

**Mutabakat (Go equivalent contract)**:

| Spring (mevcut) | Go (zorunlu eşdeğer) |
|---|---|
| `@RequireModule("ENDPOINT_ADMIN", "can_manage")` | Middleware: `RequireModule("ENDPOINT_ADMIN", "can_manage")` (chi/echo/gin) |
| Keycloak `serban` issuer JWT validation | Aynı issuer + JWKS overlay-specific config (Yaygın Pitfall #1: `OVERLAY_MUST_OVERRIDE` placeholder) |
| `/v1/authz/me` interceptor superAdmin bypass (PR #20) | Go eşdeğeri: `/v1/authz/me` endpoint + tenant anchor query + frontend cache contract |
| Outbox payload `{user, relation, objectType, objectId}` | Go canonical JSON marshaling + retry/dead-letter/idempotency |
| RELATION_ALIASES (DD-5: `viewer→can_view`) | Go eşdeğer alias map + DD-EA-6 CI guard |

**Kanıt katmanı**: G3 + G4 üç katmanı her biri Go tarafında ayrı kanıt; permission-service Spring kanıtı endpoint-admin-service için **carry over edilmez**.

### 4.3 Tez C — Repo boundary

**Ön-değerlendirme**: Single-repo target memory'si gereği manifest bu repo'ya gelir.

**Codex itirazı (koşullu)**: Default doğru, ama **audit boundary repo bölünmesiyle değil G7 ile** sağlanır. Aşağıdaki 4 koşul gerçekleşince ayrı GitOps repo'ya geçilir:

1. Ayrı ekip/onay zinciri ve repo-level access control gerekiyor.
2. Endpoint domain için ayrı ArgoCD project + sync policy + release cadence + audit trail isteniyor.
3. Platform deploy değişikliği endpoint control-plane'i etkilememeli şartı.
4. Endpoint domain ayrı cluster/namespace/secret authority'ye taşınacak.

Aksi halde ayrı repo D17/D29/D30/BG-1/ESO/placeholder/pull-secret kurallarını **kopyalama riski** üretir.

**Mutabakat**:

- **Karar**: Aynı `platform-k8s-gitops` repo + `kustomize/base/apps/endpoint-admin-service` + overlay `platform-{test,prod}` namespace ortak.
- **Operational boundary** (G7): Ayrı ArgoCD application + ServiceAccount + RBAC + NetworkPolicy + ResourceQuota + ExternalSecret path + DB role + OpenFGA writer credential.
- **Not**: Endpoint için ayrı namespace istenirse mevcut `platform-{test,prod}` namespace pattern'i etkilenir → ADR/D-karar gerekir.

### 4.4 Tez D — Pre-prod authority Windows pilot tier

**Ön-değerlendirme**: Pre-prod full authority kuralı Windows pilot için de geçerli (kullanıcı session'ı yok, credentials cutover'da değişecek).

**Codex itirazı**: Lab-only okunmalı. Windows endpoint gerçek kullanıcı makinesi ise "endpoint-device state mutation" sınıfına geçer; pre-prod credential serbestliği yetmez.

**Mutabakat — Tier Matrisi**:

| Sınıf | Lab VM (Parallels) | IT-owned domain-joined VM | Gerçek kullanıcı makinesi |
|---|---|---|---|
| **İmzasız binary** | ✅ (lab-only etiket) | ❌ | ❌ |
| **Tamper bypass** | ✅ (snapshot ile) | ❌ | ❌ |
| **Password reset (test persona)** | ✅ | ❌ | ❌ |
| **Password reset (kullanıcı login)** | ❌ HARD RULE (global) | ❌ HARD RULE | ❌ HARD RULE |
| **Functional smoke (benign command)** | ✅ | ✅ | ❌ |
| **Identity discovery (read-only)** | ✅ | ✅ | ✅ (onam ile) |
| **Pilot canlı evidence (D35-EA-5)** | ❌ | ✅ | ❌ ilk fazda |

**Kullanıcının login user'ının şifresine dokunma yasağı** her tier'da geçerli (global HARD RULE 2026-04-29).

### 4.5 Tez E — Password freeze + identity paralel

**Ön-değerlendirme**: Password reset BLOCKED + identity discovery paralel read-only.

**Codex onayı**: Doğru, ama **password reset roadmap'te ayrı satır olarak görünmeli** ve 4 connector ayrıştırılmalı. Yoksa "lokal şifre" ile "M365 reset" karıştırılır.

**Mutabakat — Sıralama**:

1. Backend governance gap kapat (DD-EA-1..7 + BG-EA-1 + G1-G7 yeşil).
2. Paralel: identity discovery read-only (AG-021 Windows identity inventory + AG-022 logged-in classification + ID-001/ID-002 IT clarify).
3. Karar gate: AG-016 lokal-only mı, yoksa AD/Entra/M365 ayrı domain mi?
4. **4 connector** ayrı paket:
   - C1: Lokal Windows user (agent SAM API)
   - C2: Domain AD user (LDAPS connector)
   - C3: Entra user (Microsoft Graph)
   - C4: M365 / Hybrid sync (Graph + writeback awareness)
5. Her connector için **ayrı dual-control sınıfı** (D35-EA-4-D varyantı).

---

## 5. 7×3 Uyum Matrisi

D29 üçlüsü (Up / Functional / Zanzibar-ready) endpoint domain için 7 boyuta genişletildi.

### 5.1 Kullanım disiplini

- **21 hücre × 3 katman** = atomik kanıt noktası havuzu.
- BE-009 / BE-013 / BE-011 her biri bu matrise **map edilir**.
- İlgisiz hücreler **N/A gerekçeli** kabul edilir (zorla doldurulmaz).
- **P0** = deploy blocker (canlı çıkmaz). **P1** = pilot öncesi gate. **P2** = destructive command class öncesi gate.
- "Smoke geçti" tek satırı kanıt sayılmaz; minimum bir hücre + üç katman birleşimi gerekir.

### 5.2 G1 Governance

| Katman | Kanıt |
|---|---|
| **Up** | AGENTS.md + CLAUDE.md + context-priority-rules.md endpoint repo'da mevcut; Codex thread referansı PR body'de |
| **Functional** | PR boundary template (BG-1 6 class checkbox + label hard gate) endpoint repo'da uygulanıyor; per-PR boundary CI gate yeşil |
| **Zanzibar/Auth** | DD-EA-1..7 + BG-EA-1 hepsi pass; CI workflow her PR'da koşuyor |

**P0**: AGENTS.md + CLAUDE.md import. **P1**: BG-1 PR boundary CI gate. **P2**: DD-EA-7 update governance guard.

### 5.3 G2 Secret/Vault

| Katman | Kanıt |
|---|---|
| **Up** | `kv/platform/endpoint-admin-service/...` Vault path mevcut; ExternalSecret manifest test+prod overlay'de render olur |
| **Functional** | ESO sync OK kanıtı (`kubectl get externalsecret -o yaml`); envFrom ConfigMap pickup için rolling restart yapıldı (Yaygın Pitfall #3) |
| **Zanzibar/Auth** | Sealed key rotation runbook + grace window; HMAC key version sync (DD-EA-4) test edildi |

**P0**: HMAC signing key + maintenance token signing key + DB credential + JWT validation Vault üzerinden. **P0**: Hardcoded key/PFX yok (CI scan). **P1**: Key rotation runbook.

### 5.4 G3 Identity/Auth

| Katman | Kanıt |
|---|---|
| **Up** | Keycloak `serban` realm JWT validation overlay-specific (Yaygın Pitfall #1: ISSUER_URI/JWKS_URI = `OVERLAY_MUST_OVERRIDE` base'de) |
| **Functional** | `/v1/authz/me` Go eşdeğeri 200; persona JWT chain (curl + Keycloak frontend client direct grants) D35-3 pattern |
| **Zanzibar/Auth** | OpenFGA Allow + Deny synthetic enforce (D35-EA-2 step 5+6 negative deny) |

**P0**: Aynı realm. **P1**: persona JWT chain test. **P2**: superAdmin bypass + tenant anchor (`organization:default#superAdmin` + `OUR_COMPANY` ek predicate).

### 5.5 G4 Command/Authz

| Katman | Kanıt |
|---|---|
| **Up** | Route metadata middleware (`RequireModule("ENDPOINT_ADMIN", "can_manage")`); annotation-equivalent map endpoint repo'da |
| **Functional** | Allow path canonical (mevcut admin → 200); deny synthetic (yetkisiz persona → 403 + audit deny row) |
| **Zanzibar/Auth** | DD-EA-6 model alignment guard CI yeşil; sınıf-spesifik dual-control (5 sınıf D35-EA-4-A..E) |

**P0**: Middleware register tüm command endpoint'lerinde. **P1**: deny synthetic CI test. **P2**: dual-control class-specific gate.

### 5.6 G5 Audit/Forensik

| Katman | Kanıt |
|---|---|
| **Up** | Outbox table + WORM partition + hash chain schema migrate edildi |
| **Functional** | Append-only invariant test (DELETE/UPDATE PG role permission yok); retention policy aktif; PII redaction logger seviyesinde |
| **Zanzibar/Auth** | Replay nonce reject test (D35-EA-2 step 10); non-repudiation signed receipt agent'tan döner |

**P0**: Outbox + append-only DB role. **P1**: hash chain advance. **P2**: retention + PII redaction.

### 5.7 G6 Supply Chain

| Katman | Kanıt |
|---|---|
| **Up** | Authenticode signed binary (Azure Trusted Signing default); image digest pin (`sha-<short>` overlay tag, D30) |
| **Functional** | SBOM generated + cert timestamping + revocation runbook; `pod imageID == GHCR digest` (D30 invariant) |
| **Zanzibar/Auth** | EDR allowlist + signed release manifest verification + DD-EA-7 update channel governance |

**P0**: Image digest pin. **P0**: lab-only etiketli imzasız binary için kanıt etiketi. **P1**: Authenticode chain. **P2**: TUF-analog release approval.

### 5.8 G7 Operational Isolation

| Katman | Kanıt |
|---|---|
| **Up** | Ayrı SA + RBAC + NetworkPolicy + ResourceQuota render (`kubectl kustomize` build sanity) |
| **Functional** | Vault path scoped + DB role least-priv + egress allowlist canlı (`kubectl get networkpolicy`) |
| **Zanzibar/Auth** | OpenFGA writer credential scope (object type allowlist) + ArgoCD application boundary + deny synthetic blast-radius test |

**P0**: Ayrı SA + RBAC. **P0**: NetworkPolicy egress allowlist (backend ↔ DB ↔ OpenFGA ↔ Vault; dış internet yalnız update channel). **P1**: ArgoCD app entry. **P2**: writer credential allowlist enforce test.

---

## 6. 8 Governance Guard

ADR-0011 `DD-1..DD-5 + AC-1 + BG-1 + BG-2` analoğu. Endpoint-admin-service için zorunlu CI gate seti.

### 6.1 DD-EA-1 — Agent binary signing chain integrity

**Risk**: İmzasız binary deploy edilirse SmartScreen + EDR red flag + AppLocker reject. Kötü niyetli aktör imza zincirine sahte cert sokarsa pilot kanıt boşa çıkar.

**CI gate**:
- Binary build sonrası Authenticode signature verify (lab tier'da self-signed; pilot için Azure Trusted Signing).
- Cert pinning: publisher CN + thumbprint allowlist.
- Timestamp validity check (CRL geçersiz olduğunda da çalışsın).
- Lab tier binary'sinde `lab-only-evidence` metadata tag CI tarafında zorunlu.

**Başarı kriteri**: PR'da imzasız binary ve etiketsiz lab binary block; revocation list ihlali olan cert block.

### 6.2 DD-EA-2 — OpenFGA model annotation alignment (Spring DD-5 analog Go-tier)

**Risk**: Go route metadata'daki `RequireModule(...)` çağrılarındaki module/relation değerleri OpenFGA model'de canonical-or-alias değilse silent authz bypass.

**CI gate**:
- Build-time scan: tüm `RequireModule("X", "y")` çağrıları extract et.
- OpenFGA model'de X type + y relation (canonical or `RELATION_ALIASES` map) bulunmazsa fail.
- DD-5 Spring equivalent: alias map mirror.

**Başarı kriteri**: Annotation drift sıfır.

### 6.3 DD-EA-3 — Maintenance/uninstall token rotation/expiry policy

**Risk**: Süresi dolmuş token panel'de hâlâ kullanılıyor; tek kullanım yerine yeniden kullanılıyor; cihaz-bound olmayan token başka cihazda işliyor.

**CI gate**:
- Token issue → `expires_at` zorunlu (max TTL config'den).
- `single_use` flag default true.
- `device_bound` claim zorunlu.
- Test: süresi dolmuş token reject + replay reject + farklı cihaz reject.

**Başarı kriteri**: Token misuse 0 vector.

### 6.4 DD-EA-4 — HMAC key version sync (agent ↔ backend grace window)

**Risk**: Key rotasyonunda agent fleet sessiz dropout (eski key invalidate, fleet yeni key'i alamamış).

**CI gate**:
- Key versioning header (`x-hmac-key-version`).
- Grace window N minute (config) — eski + yeni key paralel kabul.
- Agent rotation request runtime; result: yeni key acknowledge.
- Test: rotation sırasında 0 dropout.

**Başarı kriteri**: Rotation drill kanıtı (AC-1 analog drill cadence).

### 6.5 DD-EA-5 — Command schema canonical JSON (DD-2 analog)

**Risk**: Agent versiyonları arası protokol drift; ETL canonical JSON V25/V26 pattern'inin endpoint analoğu.

**CI gate**:
- Command payload schema `command-schema.json` repo'da.
- Backend serialize → schema validate.
- Agent deserialize → schema validate.
- Schema drift CI fail (DD-2 ETL pattern).

**Başarı kriteri**: Cross-version compatibility test pass.

### 6.6 DD-EA-6 — Go route-authz metadata guard

**Risk**: Go middleware annotation eksik route'lar veya yanlış module/relation.

**CI gate**:
- Static analysis: tüm HTTP handler'lar `RequireModule(...)` middleware'i taşıyor mu?
- Public route allowlist (`/healthz`, `/metrics` vb.) explicit.
- Allowlist dışı route middleware'siz → fail.

**Başarı kriteri**: Authz bypass route 0.

### 6.7 DD-EA-7 — Update Channel Governance Guard

**Risk**: Auto-update wormhole — backend ele geçirilirse fleet'e malicious update push edilebilir.

**CI gate** (TUF analog):
- Unsigned update config red.
- Release manifest signature verify (publisher cert pin).
- Backend image içinde signing material yok (CI scan).
- Downgrade/rollback-prevention test (version monotonicity).
- Staged rollout policy aktif (canary ring + rate limit + kill switch).
- Artifact digest/SBOM alignment.
- M-of-N release approval (TUF threshold).

**Başarı kriteri**: Auto-update wormhole closed; backend tek başına fleet update edemez.

### 6.8 BG-EA-1 — Endpoint-device state mutation boundary CI gate

**Risk**: PR endpoint-device state'i değiştiren change içerir, ama BG-1 boundary declaration eksik.

**CI gate** (BG-1 analog 6 class checkbox endpoint domain için adapte):
- [ ] Read-only inventory query
- [ ] Bounded remediation command
- [ ] Uninstall / tamper bypass
- [ ] Password reset (lab persona / kullanıcı login)
- [ ] Arbitrary command exec
- [ ] Update channel / release manifest

PR body'de en az bir kutu işaretli + label hard gate.

**Başarı kriteri**: Endpoint mutation PR'larında boundary declaration zorunlu.

---

## 7. D35-EA Ladder + Destructive Command Tier

### 7.1 Ladder genel

| Ladder | İçerik | Dual-control sınıfı |
|---|---|---|
| **D35-EA-0** | Backend Runtime Preflight | — |
| **D35-EA-1** | Agent Enrollment Anchor | Read-only |
| **D35-EA-2** | Benign Command Flow (11-step) | Tek admin + audit |
| **D35-EA-3** | UI Persona Chain (web MFE) | Read-only |
| **D35-EA-4-A** | Bounded Remediation | İki aşamalı onay (farklı user/rol) |
| **D35-EA-4-B** | Uninstall | Dual-control + short-TTL token + device-bound + single-use |
| **D35-EA-4-C** | Tamper Bypass | M-of-N (2-of-3) + time-box + auto-reenable + post-action audit |
| **D35-EA-4-D** | Password Reset (lab persona) | Test persona only; IT-live için M-of-N + ticket consent |
| **D35-EA-4-E** | Arbitrary Command Exec | DEFAULT RED; gerekirse M-of-N + cooldown + per-command allowlist |
| **D35-EA-5** | Pilot Endpoint Functional | Tier-restricted (IT-owned domain-joined VM) |

### 7.2 D35-EA-0 — Backend Runtime Preflight

Backend deploy sonrası bekledikten sonra koşulan smoke. Kapsam:

- Vault sync OK (ESO ExternalSecret status `SecretSynced`).
- DB migrate clean (`flyway info` veya equivalent).
- OpenFGA model load (model ID + store ID env'de set).
- Keycloak JWKS reachable (issuer probe).
- Outbox poller alive (N successful poll cycle, zero exception).

**Çıkış**: Pod Running + log temiz + dependencies reachable.

### 7.3 D35-EA-1 — Agent Enrollment Anchor

Agent ilk enrollment + signed heartbeat seed:

- Agent enrollment token alır (admin tarafından issue).
- Agent first heartbeat signed (HMAC v1).
- Backend outbox row eklenir (PROCESSED).
- OpenFGA tuple yazılır (`agent:<id>#owned_by@device:<id>`, `device:<id>#owned_by@company:wc-our-company-<tenant_id>`).
- Audit row append-only.

**Çıkış**: Bir agent fleet'e dahil + tuple consistency.

### 7.4 D35-EA-2 — Benign Command Flow (11-step)

Codex iter-2 skeleton'ı. Yalnızca **benign** komutlar (`collect_status`, `inventory_ping`); destructive komutlar bu ladder'da değil.

| # | Step | Kanıt türü |
|---|---|---|
| 1 | Backend artifact | `pod imageID == GHCR digest`, overlay `sha-<short>` |
| 2 | Agent artifact | Windows agent binary hash + Authenticode (lab=self-signed etiketli) |
| 3 | Runtime preflight | ESO synced + HMAC version + JWT/JWKS + DB + queue config |
| 4 | OpenFGA preflight | Object types loaded + writer cred scoped + model/store ID kanıtı |
| 5 | Authorized admin command create | `POST /api/v1/endpoint/commands` → 202/201 + `commandId` + idempotency key |
| 6 | Negative admin deny | Yetkisiz persona → 403 + audit deny row |
| 7 | DB command state | `commands` row QUEUED + canonical JSON payload + device binding + audit append |
| 8 | Outbox transition | Command/outbox PENDING → PROCESSED + retry count normal + zero dead-letter |
| 9 | Agent signed poll | Enrolled device signed heartbeat ile yalnız kendi command'ını alır |
| 10 | Result submit | Signed result accepted + replay nonce rejected + command SUCCEEDED |
| 11 | Final invariants | Audit hash chain advanced + unauthorized device poll deny + FAILED=0 + queue empty/no orphan |

### 7.5 D35-EA-3 — UI Persona Chain

Web MFE + persona JWT chain (frontend açılınca). D35-3 pattern uygulanır:

- Persona JWT al (Keycloak frontend client direct grants).
- `/v1/authz/me` → 200 + persona claim'leri.
- Endpoint listele (`GET /api/v1/endpoint/devices`) → 200 + tenant-scoped sonuç.
- Benign command create UI flow → 202.

**Çıkış**: UI ↔ backend ↔ OpenFGA chain doğrulandı.

### 7.6 D35-EA-4 — Destructive Command Class Gates

Sınıf-spesifik dual-control. **Self-approval invariant**: aynı session/user ikinci approval veremez; approval payload command digest + device ID + TTL imzalı, sonradan mutate edilemez.

#### 7.6.1 D35-EA-4-A Bounded Remediation

Service restart, log collect, registry read. Dual-control: iki aşamalı onay; ikinci approver farklı user veya farklı rol.

#### 7.6.2 D35-EA-4-B Uninstall

Agent self-uninstall + Windows service remove. Dual-control + short-TTL maintenance token (örn. 15 min) + device-bound + single-use. BE-013 bu sınıfa map'lenir.

#### 7.6.3 D35-EA-4-C Tamper Bypass

Tamper protection geçici devre dışı (örn. AV exclusion, file lock kaldırma). M-of-N (2-of-3 admin) + time-box (max 30 min) + auto-reenable + post-action audit.

#### 7.6.4 D35-EA-4-D Password Reset

**Lab tier**: Test persona only. **IT-live tier**: M-of-N + ticket consent + kullanıcı self-onay (e-posta/SMS). **Kullanıcı login user'ı yasak** (global HARD RULE).

4 connector ayrı:
- C1 lokal Windows user (agent SAM API)
- C2 Domain AD user (LDAPS connector)
- C3 Entra user (Microsoft Graph)
- C4 M365 / Hybrid sync (Graph + writeback awareness)

#### 7.6.5 D35-EA-4-E Arbitrary Command Exec

Default `RED`. Gerekirse M-of-N + cooldown + per-command allowlist. Generic "execute arbitrary updater" command yasak (DD-EA-7).

### 7.7 D35-EA-5 — Pilot Endpoint Functional

IT-owned domain-joined Windows test cihazı. Signed binary + tamper policy + EDR allowlist. Lab kanıtlarının pilot'a tekrar koşulması.

---

## 8. OpenFGA Tasarımı

### 8.1 Tenant anchor (V25 semantiği)

Mevcut platform `OUR_COMPANY` anchor table + `wc-our-company-<COMP_ID>` namespace formu. Endpoint domain için iki seçenek:

**Seçenek A** (mevcut pattern'e yapış):
```text
device:<id>#owned_by@company:wc-our-company-<tenant_id>
```

**Seçenek B** (yeni type):
```text
type our_company
device:<id>#owned_by@our_company:<tenant_id>
```

Karar ADR-0012-EA model genişlemesinde verilecek. **Seçenek A önerilir** (mevcut platform encoding pattern'i ile birebir uyumlu, V25 semantiği bozulmaz).

### 8.2 Object types

```text
type device
  relations
    define owned_by: [company]
    define admin: [user]
    define can_manage: [user] or admin or owned_by->superAdmin

type agent
  relations
    define owned_by: [device]

type command
  relations
    define target_device: [device]
    define created_by: [user]

type maintenance_token
  relations
    define issued_for: [device]
    define authorized_by: [user]
```

`organization:default#superAdmin` cross-resource yetki için ek tier; tek başına sufficient değil — `OUR_COMPANY` tenant predicate ek kontrol.

### 8.3 Tuple writer validation invariant'ları (5 madde)

Dedicated writer compromised endpoint backend için izolasyon katmanı:

1. **Outbox payload canonical JSON** (DD-EA-5) — schema ihlali → DEAD_LETTER.
2. **Hash chain doğrulama** — payload[N].prev_hash == payload[N-1].hash (G5 audit).
3. **Writer-bound signature** — endpoint-admin-backend imzalı outbox row; signature mismatch → reject.
4. **Object type allowlist** — writer cred sadece `device:`, `agent:`, `command:`, `maintenance_token:` types yazabilir; `organization:`, `module:`, `report:` write yetkisi YOK.
5. **Tuple sanity check** — `<tenant_id>` valid `OUR_COMPANY` entity'si mi, agent-id format uuid+device-bound mu.

### 8.4 Compromised backend blast radius (yumuşatılmış cümle)

> Writer validation business-domain tuple blast radius'unu kapatır; endpoint-domain misuse riski ise tenant predicate, device binding, schema validation, hash chain, signed approval payload ve class-specific dual-control ile sınırlandırılır.

Mutlak iddia ("imkansız") yapılmaz; çok katmanlı savunma derinliği mantığı.

---

## 9. G7 Operational Isolation — Detay

### 9.1 Boundary öğeleri

| Öğe | Karar |
|---|---|
| GitOps repo | Aynı `platform-k8s-gitops` (ayrı YOK) |
| Namespace | Aynı `platform-{test,prod}` |
| ArgoCD application | Ayrı entry (`endpoint-admin-service` app-of-apps içinde) |
| ServiceAccount | Ayrı (`endpoint-admin-service-sa`) |
| RBAC | Least-priv (sadece kendi resource'ları) |
| NetworkPolicy | Ayrı + egress allowlist |
| ResourceQuota | Ortak namespace içinde explicit hesaplanmış endpoint payı |
| ExternalSecret path | Ayrı `kv/platform/endpoint-admin-service/...` |
| DB role | Ayrı, least-priv |
| OpenFGA writer credential | Ayrı, object type allowlist |

### 9.2 NetworkPolicy egress allowlist

```yaml
egress:
  - # Backend → DB (kendi PG instance'ı veya shared)
    to:
      - podSelector: { matchLabels: { app: endpoint-admin-db } }
    ports: [{ port: 5432, protocol: TCP }]
  - # Backend → OpenFGA writer endpoint
    to:
      - namespaceSelector: { matchLabels: { name: platform-{test,prod} } }
        podSelector: { matchLabels: { app: openfga-writer-endpoint } }
    ports: [{ port: 8080, protocol: TCP }]
  - # Backend → Vault (ESO sidecar veya direct)
    to:
      - namespaceSelector: { matchLabels: { name: external-secrets } }
    ports: [{ port: 8200, protocol: TCP }]
  - # Backend → Update channel (signed manifest fetch — DD-EA-7)
    to:
      - ipBlock: { cidr: <update-cdn-cidr> }
    ports: [{ port: 443, protocol: TCP }]
  # Internet egress YOK; arbitrary outbound sadece update channel
```

### 9.3 ResourceQuota hesaplaması

Ortak namespace `platform-test` halihazırda permission-service + auth-service + api-gateway + ... pod'larını barındırıyor. Endpoint-admin-service eklendiğinde:

- CPU request payı: `<X>` (mevcut quota - mevcut tüketim)
- Memory request payı: `<Y>`
- Pod count payı: `<Z>` (replicas + headroom)

Bu rakamlar ADR-0012-EA fill-in. Ortak namespace içinde endpoint platform'u boğmasın.

### 9.4 ArgoCD app boundary

```yaml
# argocd/apps/endpoint-admin-service.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: endpoint-admin-service
  namespace: argocd
spec:
  project: endpoint  # ayrı project
  source:
    repoURL: https://github.com/Halildeu/platform-k8s-gitops
    path: kustomize/overlays/{test,prod}/endpoint-admin-service
  destination:
    namespace: platform-{test,prod}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**ArgoCD project**: `endpoint` ayrı project (RBAC izolasyon); platform deploy değişikliği endpoint sync'i tetiklemesin.

---

## 10. Code Signing Supply-Chain RoT

### 10.1 Tier matrisi

| Tier | Mekanizma | Kullanım |
|---|---|---|
| **Default (Production)** | Azure Trusted Signing | Windows/Entra ağırlıklı kurumsal ortam; short-lived OIDC; CI runner'da PFX yok |
| **Fallback (Production)** | Azure Key Vault HSM / DigiCert KeyLocker / on-prem HSM (YubiHSM) | Regülasyon "key fiziksel kontrol bizde" der |
| **Lab-only** | Self-signed | `lab-only-evidence` etiket zorunlu; pilot/production'a girmez |

### 10.2 ADR-0012-EA istisnası

Code signing key **Vault/ESO ile taşınmaz** çünkü:

- Runtime secret değil, supply-chain root-of-trust.
- ESO sync'i runtime workload için tasarlandı; CI imzalama pipeline'ı farklı domain.
- Key non-exportable HSM içinde; ESO bu mekanizmaya dokunmamalı.

Mevcut "tüm secret Vault'tan ESO" kuralına aykırı değil; ayrı domain. ADR-0012-EA içinde **açık istisna kaydı** olarak belgelenir.

### 10.3 CI signing pipeline OIDC short-lived

- GitHub Actions OIDC token → Azure Trusted Signing federated identity.
- Short-lived access token (max 1h).
- PFX file repo/runner/Vault KV'de **bulunmaz**.
- Timestamping aktif (CRL geçersiz olduğunda da imza geçerli).
- Cert rotation runbook + revocation runbook (ADR-0012-EA fill-in).

---

## 11. Lab VM Tier — 7 Kriter

### 11.1 Codex'in minimum lab kriteri

Parallels Win11 ya da herhangi bir lab VM için:

1. **Snapshot/rollback var** — her destructive test öncesi snapshot, sonra revert.
2. **Synthetic local user/test persona** — `test-admin@`, `d35-admin-persona` formatında ayrı hesap.
3. **Kullanıcının gerçek login user'ına dokunulmaz** — global HARD RULE 2026-04-29.
4. **Corporate/domain account yok** (veya read-only onamlı discovery only).
5. **Network sınırlı** — test backend'e + minimal external; prod/internal geniş erişim yok.
6. **Host shared folder/clipboard/secrets kapalı** veya kontrollü.
7. **Unsigned/tamper/password-reset kanıtları açıkça `lab-only` etiketli**.

### 11.2 Parallels Win11 değerlendirme

| Kriter | Parallels Win11 Durum |
|---|---|
| Snapshot | ✅ var |
| Synthetic persona | ✅ uygulanabilir |
| Kullanıcı login user'ına dokunmama | ✅ (HARD RULE uyum) |
| Corporate account yok | ⚠️ kullanıcı clarify |
| Network sınırlı | ⚠️ kullanıcı clarify |
| Host shared kontrol | ⚠️ Parallels default'ları override edilmeli |
| Lab-only etiket | ⚠️ disiplin gerekli |

**Pratik karar**: Parallels lab tier kabul edilebilir AMA kriter 4-5-6-7 disiplinli uygulanmalı. ADR-0012-EA içinde "Parallels lab tier checklist" runbook'u referans verilir.

### 11.3 IT-owned domain-joined pilot tier

D35-EA-5 pilot için Parallels yeterli değil. Gerekenler:

- Ayrı domain-joined Windows cihaz (kullanıcının kendi makinesi DEĞİL).
- Code signing imzalı agent binary (Authenticode chain valid).
- EDR allowlist tanımlı.
- Tamper policy aktif (sadece signed update channel).
- IT veya ops tarafında yönetilen test cihazı (kullanıcı session'ı yok, monitoring var).

---

## 12. Açık 5 Nokta — Kullanıcı Clarify Rehberi

ADR-0012-EA fill-in için kullanıcı yanıtları gerekli.

### 12.1 Clarify tablosu

| # | Soru | Bağlam | Önerim | Beklenen yanıt formu |
|---|---|---|---|---|
| 1 | Endpoint repo URL + AGENTS.md/CLAUDE.md/context-priority kopyası var mı? | Repo boundary + governance import için | Repo URL paylaş; eksikse 1. PR olarak doc-import | URL + mevcut doc listesi |
| 2 | Admin API auth: Keycloak `serban` realm mi, ayrı OIDC mi? | Auth fragmentation engellemek için | Aynı realm; ayrı client ID OK | Realm + client ID |
| 3 | Pilot Windows tier (lab/IT/user)? | Tier matrisi clarification | Parallels=lab, IT-owned=pilot, gerçek user=D35-EA-5 sonrası | Cihaz envanteri |
| 4 | Code signing provider seçimi? | G6 supply-chain RoT için | Azure Trusted Signing default; on-prem HSM regülasyon fallback | Provider + cert authority |
| 5 | 5 domain + Entra tenant inventory? | Identity discovery + 4 connector tasarımı | IT clarify; identity discovery paralel read-only başlasın | Domain listesi + Entra tenant ID + sync model (PHS/PTA/Federation) |

### 12.2 Clarify olmadan yapılabilecekler

- ADR-0012-EA skeleton draft (placeholder'larla).
- `kustomize/base/apps/endpoint-admin-service` boş skeleton (deployment yok henüz; namespace boş base + overlay placeholders).
- DD-EA-6 + DD-EA-7 CI workflow placeholder.
- PLAN.md "Faz 22 Endpoint Admin Service Governance" entry.
- 7×3 matris template (her hücre için kanıt türü).

### 12.3 Clarify gerektirenler

- ADR-0012-EA decision section fill-in.
- `OVERLAY_MUST_OVERRIDE` placeholder değerlerin gerçek değerleri.
- ResourceQuota hesabı.
- 5 domain için ID-001 + ID-002 detayı.
- Identity connector mimarisi (4 ayrı paket).

---

## 13. ADR-0012-EA Skeleton

### 13.1 Title

ADR-0012-EA: Endpoint Admin Service Governance Charter

### 13.2 Context

(Bu raporun §1 + §2 kısalmış hâli)

### 13.3 Decision

(Bu raporun §3-§11 mutabakat noktaları)

### 13.4 Consequences

**Olumlu**:
- Endpoint-admin-service governance pre-deploy aşamasında düzeltilir.
- Compromised endpoint backend platform business-domain tuple yazma yetkisini alamaz.
- Auto-update wormhole DD-EA-7 ile kapatılır.
- Code signing supply-chain RoT ESO ile karıştırılmaz.

**Olumsuz / maliyet**:
- 8 governance guard CI eklenmesi 1-2 sprint iş yükü.
- Code signing provider tedariki (Azure Trusted Signing onboarding 1-2 hafta).
- Pilot tier IT-owned cihaz tedariki yeni proje.
- BE-009/BE-013/BE-011 her biri 7×3 matris altında 21-satır kanıt zorunluluğu (mevcut "live smoke" yetersiz).

### 13.5 Open items

(§12.1 5 nokta fill-in)

### 13.6 References

- Bu rapor (referans)
- Codex thread `019dd895-17c1-79f0-b652-e316f64d4d79`
- ADR-0010 (Vault Credential Lifecycle + DR + Operator/Agent Authority)
- ADR-0011 (Drift Detection + Audit Cadence + Boundary Governance)
- CLAUDE.md global HARD RULE'lar (Pre-Production Full Authority + Türkçe + No Fake Work)

---

## 14. Sıradaki Adımlar

### 14.1 Hemen (agent-actionable, kullanıcı clarify beklemeden)

1. **Bu rapor commit** + PR aç (kalıcı referans).
2. **ADR-0012-EA draft** (`docs/adr/0012-endpoint-admin-service-governance-charter.md`) — bu rapordan derlenmiş; 5 açık nokta placeholder.
3. **PLAN.md update** — "Faz 22 Endpoint Admin Service Governance" yeni faz başlığı + 8 governance guard + D35-EA ladder + 7×3 matris referans.
4. **`kustomize/base/apps/endpoint-admin-service` skeleton** (boş Deployment + ConfigMap + ServiceAccount + ExternalSecret placeholder).
5. **CI workflow placeholder** (DD-EA-6 + DD-EA-7 boş workflow file'ları).

### 14.2 Kullanıcı clarify sonrası

6. ADR-0012-EA fill-in (5 nokta cevaplanınca).
7. Endpoint repo'ya AGENTS.md/CLAUDE.md/context-priority import PR'ı.
8. Codex thread `019dd895` referans + ADR-0012-EA review iter (yeni Codex thread + adversarial gözden geçirme).
9. BE-009/BE-013/BE-011 her biri 7×3 matris altında 21-satır kanıt zorunluluğu (mevcut "live smoke" tek satır revize).

### 14.3 Pilot ön-koşulu (P0 gate, ardışık zorunlu)

| Kapı | Durum | Doğrulama |
|---|---|---|
| ADR-0012-EA AGREE | ⬜ | Codex iter + kullanıcı |
| DD-EA-1..7 + BG-EA-1 hepsi yeşil | ⬜ | CI workflow run |
| D35-EA-0 PASS | ⬜ | Backend runtime preflight kanıtı |
| D35-EA-1 PASS | ⬜ | Agent enrollment anchor kanıtı |
| D35-EA-2 PASS | ⬜ | Benign command flow 11-step kanıtı |
| D35-EA-3 PASS | ⬜ | UI persona chain kanıtı |
| G6 + G7 yeşil | ⬜ | Code signing + operational isolation kanıtı |
| IT-owned domain-joined VM hazır | ⬜ | IT clarify |

### 14.4 Pilot sonrası (D35-EA-5+)

- D35-EA-5 evidence (IT-owned VM, signed binary, gerçek Win)
- AG-016 lokal password reset (D35-EA-4-D test persona)
- AD/Entra/M365 connector ayrı paket (4 ayrı C1-C4)
- Identity discovery → karar gate

---

## 15. Risk Envanteri

| Risk | Olasılık | Etki | Mitigation |
|---|---|---|---|
| Backend kodu uyumlu değil (mevcut implementation görülmedi) | Orta | Yüksek | Endpoint repo paylaşımı + line-by-line audit; ADR-0012-EA review iter |
| Kullanıcı clarify gecikir → ADR-0012-EA blocked | Yüksek | Orta | Skeleton draft placeholder ile commit; clarify gelince ramp |
| Code signing provider onboarding gecikir | Orta | Yüksek | Lab tier self-signed devam; pilot için Azure Trusted Signing kritik path |
| OpenFGA shared store conflict (endpoint tuple churn business model'i etkiler) | Düşük | Yüksek | 6 senaryon dan biri gerçekleşirse ayrı store fallback ADR'da hazır |
| Auto-update wormhole exploit (DD-EA-7 yokken pilot başlarsa) | Düşük | Çok Yüksek | DD-EA-7 P0 pilot ön-koşul; pilot başlamadan kapı kapanmazsa pilot iptal |
| Password reset 4 connector kapsam genişlemesi | Yüksek | Orta | Roadmap'te 4 ayrı paket olarak görünür; tek "password reset" karışımı engellenir |
| Compromised endpoint backend tuple sızdırma | Düşük | Yüksek | Tuple writer validation 5 invariant + dual-control class-specific |
| Pilot Windows kullanıcının gerçek hesabıyla yapılır | Düşük | Çok Yüksek | HARD RULE 2026-04-29 + tier matrisi + IT-owned VM zorunlu |
| 5 domain + Entra inventory eksik kalır | Yüksek | Orta | Identity discovery paralel read-only; AD/Entra connector ID-001/002 dependency |
| Pre-prod full authority kuralı pilot'a yanlış taşınır | Orta | Yüksek | Lab/IT/user tier matrisi her PR'da boundary declaration zorunlu |

---

## 16. Glossary

| Terim | Anlam |
|---|---|
| **AGREE** | Codex adversarial verdict — plan iterasyonu tamamlandı, impl başlanabilir |
| **PARTIAL** | Codex verdict — kısmi kabul, küçük revizyon talebi |
| **REVISE** | Codex verdict — strüktürel revizyon talebi |
| **RED** | Codex verdict — stratejik blocker, kullanıcıya yön sor |
| **D29** | Up ≠ Functional ≠ Zanzibar-ready üç kanıt katmanı |
| **D30** | Immutable artifact (`sha-<short>`) + 72h warm rollback |
| **D17** | Selective apply koruma (full overlay apply yasak) |
| **D35-EA** | Endpoint Admin Canlı Evidence Ladder (D35 analog) |
| **DD-EA** | Drift Detection Endpoint Admin (ADR-0011 DD-x analog) |
| **BG-EA** | Boundary Governance Endpoint Admin (ADR-0011 BG-x analog) |
| **OUR_COMPANY** | V25 anchor table tenant predicate (multi-tenant) |
| **Authenticode** | Microsoft code signing standard |
| **TUF** | The Update Framework — supply chain integrity spec |
| **HSM** | Hardware Security Module (key non-exportable) |
| **WORM** | Write-Once-Read-Many storage (audit immutability) |
| **PHS** | Password Hash Sync (Entra hybrid identity) |
| **PTA** | Pass-Through Authentication (Entra hybrid) |
| **WHfB** | Windows Hello for Business |
| **G1-G7** | 7 governance boyut (Governance, Secret/Vault, Identity/Auth, Command/Authz, Audit/Forensik, Supply Chain, Operational Isolation) |
| **C1-C4** | 4 password reset connector (Lokal Win / Domain AD / Entra / M365) |

---

## 17. Codex Iter Tam Timeline

| Iter | Verdict | Konu | Süre |
|---|---|---|---|
| 1 | PARTIAL | Adversarial baseline; A/C/D koşullandırma, B sertleştirme (Go-tier gap), +DD-EA-6 + BG-EA-1, 8 eksik boyut, 10 açık soru | ~60s |
| 2 | PARTIAL | G7 ayrı boyut talebi, D35-EA-2 benign-only, DD-EA-7 update governance ekleme, 2 caveat (`organization:default`, tuple writer validation), D35-EA-2 11-step skeleton, 5 sınıf dual-control, code signing tier, lab VM 7 kriter | ~90s |
| 3 | **AGREE** | Konsolide framework + 4 non-blocking precision edit (tuple syntax, writer claim yumuşatma, 63-noktası bürokrasi, ArgoCD boundary netlik) + `ready_for_user_report=true` | ~45s |

Toplam Codex süresi ~3.5 dakika, 3 tur iterasyon.

---

## 18. References

### 18.1 Bu repo

- [AGENTS.md](../AGENTS.md) — repo girişi
- [docs/context-priority-rules.md](context-priority-rules.md) — canonical kural seti
- [docs/state/current-state.md](state/current-state.md) — canlı truth snapshot
- [PLAN.md](../PLAN.md) — D-kararlar log
- [docs/adr/0010-vault-credential-lifecycle-and-dr.md](adr/0010-vault-credential-lifecycle-and-dr.md)
- [docs/adr/0011-drift-detection-audit-cadence-boundary-governance.md](adr/0011-drift-detection-audit-cadence-boundary-governance.md)
- [docs/adr/0011-gray-areas/](adr/0011-gray-areas/) — sandbox-blocking pattern
- [docs/RB-adr-0011-bg-1-pr-boundary-declaration.md](RB-adr-0011-bg-1-pr-boundary-declaration.md)
- [docs/RB-adr-0011-bg-2-sandbox-blocking-playbook.md](RB-adr-0011-bg-2-sandbox-blocking-playbook.md)
- [docs/postmortem-2026-04-29-admin-role-restore-cycle.md](postmortem-2026-04-29-admin-role-restore-cycle.md) — Session 34 Codex 9 iter pattern referansı

### 18.2 Global

- `~/.claude/CLAUDE.md` HARD RULE'lar:
  - Pre-Production Full Authority (2026-04-29)
  - Cevap Dili Türkçe (2026-04-28)
  - No Fake Work / No Cosmetic Operations (2026-04-25)
  - Plan Consensus Autonomy (2026-04-17)
  - Codex MCP default (2026-04-17)

### 18.3 Codex thread

`019dd895-17c1-79f0-b652-e316f64d4d79` (3 iter; iter-3 AGREE; 2026-04-29 mutabakatı)

### 18.4 İlgili PR pattern referansları (mevcut platform)

- [platform-backend #18](https://github.com/Halildeu/platform-backend/pull/18) — RequireModuleInterceptor relation alias (Go middleware için pattern)
- [platform-backend #19](https://github.com/Halildeu/platform-backend/pull/19) — DD-5 alignment guard (DD-EA-2 + DD-EA-6 için referans)
- [platform-backend #20](https://github.com/Halildeu/platform-backend/pull/20) — interceptor superAdmin bypass (G3 architectural unification için referans)
- [platform-k8s-gitops #233](https://github.com/Halildeu/platform-k8s-gitops/pull/233) — BG-1 self-validating gate (BG-EA-1 için referans)

---

**Son Söz**: Bu rapor `AGREE` mutabakat noktasıdır; ADR-0012-EA + PLAN.md Faz 22 + skeleton kod commit'leri sıradaki agent-actionable iş paketleridir. Kullanıcı 5 açık nokta clarify ettikçe ADR fill-in yapılır; pilot ön-koşulu olan governance + ladder yeşil olunca D35-EA-5 IT-owned VM kanıtına geçilir.
