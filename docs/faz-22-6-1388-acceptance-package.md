# Faz 22.6 — #1388 Sensitive Endpoint Ops Governance Gate · Acceptance Package

> **Amaç:** [#1388](https://github.com/Halildeu/platform-k8s-gitops/issues/1388)
> gate kabulü için gereken **tüm policy artifact'larını sign-off-ready** taslak
> haline getirmek; geriye yalnız **owner / DPO / Hukuk imzası** kalsın.
> **Status:** DRAFT — owner/DPO/legal sign-off bekliyor. Bu paket kabul edilmeden
> 22.6 (ve 22.8) runtime başlamaz.
> **Tarih:** 2026-06-09 · **Cross-AI:** Codex `019ea961` REVISE→AGREE.
> **İlişkili:** [ADR-0033 broker](adr/0033-faz-22-6-remote-access-bridge-broker.md), [ADR-0034 owner-decision](adr/0034-1388-sensitive-endpoint-ops-owner-decision.md), [22.6 plan](faz-22-remote-access-bridge-plan.md), ADR-0012-EA §0, [docs/22-2-kvkk-data-inventory.md](22-2-kvkk-data-inventory.md), BE-019.

> **HARD RULE — Tam Otonom:** Bu paket agent tarafından **tam taslaklandı**;
> sadece gerçek hukuki/owner kararı (legal basis onayı + imza) owner-gated. Agent
> hiçbir runtime erişimi açmaz.

---

## 1. Legal Basis Matrix (KVKK / GDPR) — DPO karar verir, kilitli değil

> **Kilitlenmemiştir.** Aşağıdaki "candidate" sütunu öneridir; bağlayıcı dayanak
> **DPO/Hukuk** tarafından operasyon sınıfı bazında belirlenir.

| Operasyon sınıfı | Candidate KVKK | Candidate GDPR | Not |
|---|---|---|---|
| Attended IT support session (no recording) | m.5/2-f meşru menfaat | Art.6(1)(f) legitimate interest | balancing test + aydınlatma |
| Session recording (4-F) | m.6 açık rıza **veya** m.5/2-f + balancing | Art.6(1)(a)/(f) + Art.9 (özel nitelikli olabilir) | DPO karar; recording yüksek hassasiyet |
| Unattended / break-glass | m.5/2-f + m.5/2-ç hukuki yükümlülük (olası) | Art.6(1)(c)/(f) | acil/güvenlik gerekçesi + post-use review |
| BYOD (22.2.A kişisel cihaz) | iş sözleşmesi VEYA açık rıza (DPO) | Art.6(1)(b)/(a) | cihaz sahibi hakları güçlü |

**Açık karar (DPO):** Tek madde erken mühürlenmez; recording için m.6 mı, m.5/2-f
+ balancing mi — DPO belirler.

## 2. RBAC Scope Catalog (statik OpenFGA perm — yalnız permission-service yazar)

> Tüm scope'lar **statik OpenFGA permission**'dır; **yalnız permission-service**
> yazar (DD-EA-2). Broker/endpoint-admin **tuple yazmaz**.

| Scope | Açıklama |
|---|---|
| `session:request` | Oturum talebi açma |
| `session:approve` | Dual-control onaylama (maker≠checker) |
| `session:join` | Onaylı oturuma katılma/relay |
| `capability:tier-grant` | Capability tier yetkisi (4-E / 4-F) |
| `recording:download` | Kayıt erişimi (least-priv + per-view audit) |

> **`retention-override` SCOPE DEĞİLDİR.** Retention değişimi runtime tuple grant'i
> değil, **DPO-gated governance süreci**dir (§5). Grantable override güvenlik/KVKK
> riski → kaldırıldı.

## 3. Dual-Control Matrix

| Tier | Kontrol |
|---|---|
| 0–3 | tek admin + audit (3 = yalnız non-destructive/reversible config) |
| 4-A bounded-remediation | maker ≠ checker |
| 4-B uninstall/decommission (**4-B-WIPE** stricter) | dual-control + short-TTL + device-bound + single-use |
| 4-C tamper-bypass | M-of-N (2/3) + time-box + auto-reenable + post-action audit |
| 4-D password-reset | test persona / IT-live M-of-N + ticket consent |
| 4-E arbitrary/constrained-cmd | per-command allowlist + transcript |
| 4-F-PTY / 4-F-REMOTE-CONTROL | attended + M-of-N + recording mandatory + cooldown + max-duration |
| 4-F break-glass (unattended) | explicit break-glass policy objesi (§7) + M-of-N |

**Anti-coercion invariant:** approver insan + role-distinct + asla requester
(break-glass dahil). SOC2 CC6.1.

## 4. Append-only Audit Schema (NIST AU-3 + AU-10, BE-016 hash-chain)

```
remote_session_audit (append-only, WORM):
  event_id, prev_event_hash (SHA256 chain), event_hash,
  actor, approver (actor≠approver), device_id, tenant_id,
  reason, scope, capability_tier, session_id,
  start_ts, end_ts, result, evidence_links[], abort_reason,
  signed_approval_payload (command_digest + device_id + TTL, immutable)
```
- DELETE/UPDATE role-deny; 365d retention; non-repudiation imza.

## 5. Retention Policy (KVKK inventory ile hizalı + recording eklenir)

> Değerler **`docs/22-2-kvkk-data-inventory.md`** canonical'ı ile birebir; bu
> paket onları override etmez. (Standart, BYOD-özel değil.)

| Veri | Retention |
|---|---|
| Heartbeat / metadata | 90d → delete |
| Raw inventory / IP / UPN / SID | 30d-raw → 90d-hashed → delete |
| Local user / software | 30d → delete |
| Audit log | 365d (BE-016 immutable) |
| **Session transcript (4-E/4-F-PTY)** *(YENİ — inventory'ye eklenecek)* | **90d, access-audited** |
| **Session video recording (4-F-REMOTE-CONTROL)** *(YENİ)* | **90d-raw → crypto-erase**, access-audited, DPIA-bound |

> **REQUIRED DOC EDIT:** session-transcript + session-recording kategorileri
> `docs/22-2-kvkk-data-inventory.md`'ye **eklenmelidir** (DPO-confirm); aksi halde
> KVKK inventory drift devam eder. (Bu PR'da inventory edit'i yapılır.)
> Otomatik enforcement **BE-019** MERGE'e bağlı; o zamana dek manuel DPO süreci.

## 6. Chain-of-Custody Template

`request_id · approver · device_id · capability_tier · manifest_SHA256 ·
transfer_hash · storage_URI · timestamp · access_log[]` — 6 custody point
(request → approval → broker relay → upload → storage → disposal), her transferde
hash/imza doğrulama; **72h min immutability** (silme deny). 22.8 ile **unified
evidence-storage-contract v0** (object storage + ACL + encryption + access audit).

## 7. Break-glass Policy Object (NIST AC-2(11)/AC-6, ISO A.5.18)

```
break_glass_policy:
  actor, reason, scope, capability_tier, TTL,
  m_of_n_quorum, auto_revoke_condition,
  breach_notification_trigger, mandatory_post_use_review
```
- DB governance table; **2-person quorum** ile oluşturulur; auto-expiry;
  kullanım sonrası **zorunlu review**. Requester'ı self-elevate edemez.

## 8. Redaction Rules (KVKK m.5 / GDPR Art.5)

- `UPN → sha256:…`, `SID → S-1-5-21-***-***-***-NNNN`, `IP → 192.168.1.***`
  (30d sonrası), `operator → initials`.
- **Asla plaintext:** password / token / JWT / session-cookie / enrollment-cred.
- **CI grep-fail-closed** redaction gate; cross-AI (Codex/Mavis) yalnız
  anonymized hash+enum metadata alır — raw PII asla.

## 9. Attended Consent UX Spec (G8)

- Modal banner (oturum başlangıcı): operator identity + recording notice +
  **local abort button** (her zaman görünür).
- Recording onayı **4-F için zorunlu gate** (no-recording-4-F-deny) — opsiyonel
  checkbox değil.
- Timing (tek tablo): consent-accept 30s → auto-abort; user-objection abort
  immediate (≤5s graceful); approver-revocation immediate kill (≤10s graceful
  save); idle timeout configurable.

## 10. Abort Rules

user objection · network anomaly · scope expansion · EDR block · data-volume ·
audit failure · approver revocation · TTL expiry · device offline → graceful
close + transcript save + operator notify; revocation propagation ≤30s.

---

## 11. Acceptance Checklist (sign-off-ready, unchecked)

### 11.1 Governance / Security
- [ ] §0 ADR-0012-EA extended-ladder + DD-EA-8 reconciliation MERGED (runtime önkoşulu)
- [ ] DD-EA-8 CI gate spec onaylandı (capability→tier, recording-required, no-unattended-without-break-glass, no-advertise-disabled)
- [ ] G7 broker isolation (SA/RBAC/NetPol/RQ/ESO/DB-role/ArgoCD) review
- [ ] G9 D18 scoped passthrough exception onaylandı (cert-bound, no header-trust)
- [ ] Global kill-switch + acil runbook hazır
- [ ] Anti-coercion invariant (human, role-distinct, never-requester) doğrulandı

### 11.2 Privacy / Legal (DPO + Hukuk)
- [ ] Legal basis matrix (§1) DPO/Hukuk kararı — operasyon sınıfı bazında
- [ ] Session-recording + transcript kategorileri KVKK inventory'ye eklendi (§5 REQUIRED EDIT)
- [ ] DPIA (recording, olası 3rd-party PII) tamamlandı + VERBİS notu
- [ ] Retention + crypto-erase vs silme (Madde 7 ↔ ISO immutability) çözümü onaylandı
- [ ] Attended consent UX + local abort + operator identity (§9) onaylandı
- [ ] Recording access-control (DPO/redaction-mediated, raw self-service değil) onaylandı

### 11.3 Runtime acceptance (migration + sign-off sonrası)
- [ ] D29 Up / Functional / Secured ayrı kanıt
- [ ] D35-EA-4-F live-evidence gate (stale-token/same-user/tenant-mismatch/no-recording/no-cert/orphan/timeout/reconnect-TTL) yeşil
- [ ] BE-019 enforcement (veya manuel DPO süreci açık beyanı)

### 11.4 Owner / DPO / Legal Sign-off
| Rol | İsim | İmza | Tarih | Durum |
|---|---|---|---|---|
| Owner | Halil Koçoğlu | `[ ]` | | `[ ] Approved` |
| DPO | [placeholder] | `[ ]` | | `[ ] Approved` `[ ] Conditions` `[ ] Rejected` |
| Hukuk | [placeholder] | `[ ]` | | `[ ] Approved` `[ ] Conditions` `[ ] Rejected` |
| Security/Governance | [placeholder] | `[ ]` | | `[ ] Approved` |

**Re-review:** yıllık + tetikleyici (yeni operasyon sınıfı / scope expansion /
retention değişimi / EDR kural değişimi / ihlal).

---

## 12. Standards Cited

KVKK m.5/6/7/11 · GDPR Art.5/6/7/17/32/33 · NIST SP 800-53 AC-2/AC-6/AC-12/AC-17/AU-3/AU-10 · NIST 800-207 · ISO/IEC 27001:2022 A.5.15/16/18/23/34 · SOC2 CC6.1/CC7.2 · OWASP API4:2023 · SPIFFE/SVID · BE-016 hash-chain.
