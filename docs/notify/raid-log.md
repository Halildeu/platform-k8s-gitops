# Notification Platform — RAID Log

> **Status**: ACTIVE (Session 39 PM bootstrap iter-2 + Codex thread `019e0c28` F5 absorb)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)
> **Risk register**: [risk-register.md](risk-register.md) — sadece **risk** boyutunu tutar
> **Cross-ref**: stakeholder-plan + sprint-plan + milestones

Bu doküman **Risks / Assumptions / Issues / Dependencies** dört boyutu ayrı tutar. Risk register zaten 22 risk takipli; RAID log onu **assumption + issue + dependency** ile genişletir.

> **Faz 2 — GitHub Project migration (2026-05-17)** — Aktif Issue (I-serisi) takibi [platform Roadmap board](https://github.com/users/Halildeu/projects/2) (`Faz 23` view · `Kind=issue`) üzerinde. Assumption (A) + Dependency (D) boyutları canonical olarak yalnız bu dokümanda. Aktif issue board mapping: I2 #775 · I4 #776. (I1 #774 + I6 #777 resolved → board item closed; bu dokümanda kayıtlı.)

## Neden Ayrı?

Codex iter-2 finding F5 (thread `019e0c28`):
> "PM capability set yeterli, ama execution reporting için 3 küçük ek lazım. RAID log: risk dışındaki assumption, issue, dependency ve decision-action ayrımı için."

- **Risk**: Henüz olmamış ama olabilecek olaylar (probability × impact)
- **Assumption**: Plan'ın **dayandığı varsayım** — yanlış çıkarsa scope/effort/timeline değişir
- **Issue**: Şu anda yaşanan, çözüm bekleyen olay (risk materialized)
- **Dependency**: Dış aktör/ekip/contract'a bağlı engel — internal kontrol dışı

---

## A — Active Assumptions

| ID | Assumption | Confidence | Validation | Last Review | Owner |
|---|---|:---:|---|---|---|
| A1 | SMS primary JetSMS canlı sözleşme aktif (2026-05-19 kullanıcı kararı); **NetGSM secondary contract kısa vadede yapılmayacak — R1 ⏳ DEFER (kullanıcı kararı 2026-05-23)**; JetSMS-only degraded mode = kabul edilen kalıcı işletim durumu; NetGSM altyapısı asset-preserved (sözleşme olursa reactivation) | Low | — (DEFER; sözleşme imzalanırsa re-aktive) | 2026-05-23 | ops |
| A2 | KVKK Art.11 erasure pattern legal review — **R2 CLOSED 2026-05-23** (Codex `019e5189` final legal verdict AGREE = kabul edilen hukuk onayı; kullanıcı kararı) | High (validated) | Codex `019e5189` verdict + 6/7 K-PR MERGED | 2026-05-23 | — |
| A3 | Browser SSO verify user availability 2026-05-12 öncesi | Low | Pre-Production Full Authority — agent headless alternative kullanır | 2026-05-09 | agent |
| A4 | Faz 22.2 endpoint-admin Lab tier 23.7 (Push) öncesi hazır | Medium | endpoint-admin PR list cross-faz coord | 2026-05-09 | dev |
| A5 | Velocity baseline ~10-15h/session block tutar | Medium | Sprint cycle başı vs bitişi gerçekleşen saat audit | 2026-05-09 | agent |
| A6 | T1 ~100h aggressive target M3 2026-06-08 imkansız değil | Low | Codex iter-3 review verdict + R2 KVKK gate | 2026-05-09 | agent |
| A7 | Cross-AI peer review HARD RULE her PR için Codex AGREE/REVISE iter ortalama 2-3 round | Medium | PR #439, #441 history (3 ve 5 iter) | 2026-05-09 | agent |
| A8 | Pre-prod cluster stable; D17 koruma + selective apply pattern outage üretmez | High | Session 35-39 deploy history clean | 2026-05-09 | ops |
| A9 | DKIM/SPF/DMARC prod domain config 23.2 closure öncesi ops tarafından yapılır | Medium | ops drill scheduling — TBD | 2026-05-09 | ops |
| A10 | T+72h observation window 2026-05-11 19:42Z'da incident-free kapanır | Medium | 25 PrometheusRule + 4 SLO alert + dashboard | 2026-05-09 | ops + agent |

**Assumption invalidation prosedürü**: Bir assumption yanlış çıkarsa → ilgili milestone target re-baseline + risk register'a yeni risk olarak transfer + sprint-plan effort revize.

---

## I — Active Issues (Risk Materialized veya Live Problem)

| ID | Issue | Detected | Severity | Mitigation in Progress | Related Risk | Owner | Status |
|---|---|---|:---:|---|---|---|:---:|
| I1 | Prod SMTP connection refused (notification-orchestrator pod logs 2026-05-09) | 2026-05-09 | Medium | Session 44 çözüldü: A6 Office 365 prod SMTP gateway + A7 NOTIFY_DISPATCH_ENABLED=true + A8 Microsoft Graph port-443 bypass LIVE; root-cause ISP/datacenter outbound 587 block | R3 (🟢 Mitigated) | ops + dev | 🟢 Resolved |
| I2 | platform-prod ArgoCD application "OutOfSync" gösteriyor ama "successfully synced (all tasks run)" mesajı | 2026-05-09 | Low | ArgoCD diff hesaplama farkı, gerçek drift yok; manuel `argocd app diff` ile doğrulanmalı | None — ops/gitops cosmetic issue | gitops | 🟡 Active |
| I3 | Charter sub-faz % rakamları PM bootstrap iter-1'de iyimser (Codex verdict PARTIAL) | 2026-05-09 | Low | Yorumlama disiplini düzeltildi (Codex thread `019e0c28` retrospective); rakamlar revize tablosuyla sunum | None — PM-doc reporting issue | agent | 🟢 Mitigated |
| I4 | Feature matrix literal marker pass deferred (~178 row sweep) — semantic estimate ile literal marker drift | (devam) | Low | Marker discipline note eklendi; planlı follow-up (sub-faz closure'larında inline) | None — PM-doc tracking issue | agent | 🟡 Active |
| I5 | TodoWrite session-scoped, kalıcı değil | (yapısal) | Low | PM artifact set kalıcı yazılı + Update Discipline HARD RULE her PR'da senkron tutar | None — process limitation | — | 🟢 Mitigated |
| I6 | Keycloak test realm admin credential unavailable — Docker compose env password invalid, Vault'ta yok; M2 D29 authenticated intent-submit BLOCKED | 2026-05-09 | High | **RESOLVED 2026-05-18** (board #777 closed): `scripts/ops/kc-bootstrap-admin-recovery.sh` ile master admin password canonical değere re-align edildi — evidence `docs/faz-23-evidence/2026-05-14-m2-credential-gate-unblocked.md`; 2026-05-18 live re-verify — `platform-kc-test` healthy, `kcadm` master login OK, D29 personaları (`notify-d29-test-persona`, `d29-evidence-tester`) realm'de mevcut. Cross-AI: Codex `019e3c74` AGREE (stale credential blocker; persona credential Vault formalization ayrı hardening — normal user, realm-admin değil). M2 D29 evidence/acceptance reconciliation ayrı item #754 | None — credential boundary issue (test cluster auth state); admin@example.com kullanıcı login user'ı dokunma yasak | ops + user | 🟢 Resolved |

**Issue eskime prosedürü**: 14 gün üzerinde 🟡 Active issue → owner-level escalation + retrospective.

---

## D — External Dependencies (Internal Kontrol Dışı)

| ID | Dependency | Required By | ETA | Provider | Status |
|---|---|---|---|---|:---:|
| D-N1 | Faz 22.1.1b III review verdict | 23.1 başlangıç | bypassed pre-prod 2026-05-08 user onayı | dev (Faz 22.1.1b) | 🟡 |
| D-N2 | Faz 22.2 endpoint-admin Lab tier readiness signal | 23.7 (Push) | TBD | dev (Faz 22.2) | ⏳ |
| D-N3 | JetSMS provider canlı sözleşme + API erişim (SMS primary, 2026-05-19 kullanıcı kararı) | 23.3 (SMS primary) | aktif (sözleşme var) | JetSMS commercial | 🟢 |
| D-N3b | NetGSM provider sözleşme + sandbox account (SMS secondary failover) | 23.3 (SMS secondary) | ⏳ DEFER — kısa vadede yok (kullanıcı kararı 2026-05-23); asset-preserved | NetGSM commercial | ⏳ |
| D-N4 | İletimerkezi tertiary SMS provider — DEFERRED (JetSMS primary + NetGSM secondary kararı sonrası kapsam dışı; gelecekte 3. provider gerekirse) | future | — | İletimerkezi commercial | ⏳ deferred |
| D-N5 | Legal KVKK Art.11 erasure pattern review | 23.2.B | **CLOSED 2026-05-23** — Codex `019e5189` final legal verdict (kullanıcı kararı: Codex istişare verdict'i = kabul edilen hukuk onayı) | legal / Codex AI proxy | 🟢 |
| D-N6 | DKIM/SPF/DMARC prod domain config (operator manual setting) | 23.2 closure | TBD ops | ops | 🟡 |
| D-N7 | Browser SSO user availability (testai.acik.com + ai.acik.com) | 23.9 closure | per-cutover | user | 🟡 |
| D-N8 | GHCR registry availability (Halildeu org packages) | tüm deploy | continuous | GitHub | 🟢 |
| D-N9 | Vault prod token rotation policy | post-cutover credential rotation | TBD | ops | ⏳ |
| D-N10 | OpenFGA tuple drift consistency (cross-repo: auth-service ↔ permission-service ↔ notify-orch) | continuous | continuous | dev (3 repo coordination) | 🟢 |

**Dependency ETA slip prosedürü**: ETA 7+ gün geçtiyse milestone target re-baseline + stakeholder notification + Codex strategic retrospective.

---

## R — Cross-Reference: Risk Register

Risk boyutu ayrı [`risk-register.md`](risk-register.md) içinde tutulur (22 risk: R1-R22). RAID log onu **çoğaltmaz**.

**Issue tablosu risk-register'ı çoğaltmaz**: `Related Risk` kolonu varsa R-N bağlantısını gösterir (örn. I1 → R3 partial); R-N karşılığı olmayan issue'lar **issue-only** olarak kalır (ops/gitops cosmetic, PM-doc tracking, process limitation gibi). Issue **escalate olursa** yeni risk satırına taşınır (severity Medium → High geçişi veya production-impact tespit edilirse).

| RAID Boyutu | Doküman | Sayı |
|---|---|---:|
| Risks | risk-register.md | 22 |
| Assumptions | this doc §A | 10 |
| Issues | this doc §I | 6 |
| Dependencies | this doc §D | 10 |

**Toplam aktif izleme**: 48 ayrı boyut (M2 evidence collection sırasında I6 eklendi).

---

## RAID Review Cadence

- **Per-PR**: Yeni assumption/issue/dependency çıkarsa eklenir
- **Weekly** (her Cuma stakeholder summary ile): Tüm RAID girdileri review (status değişimi + eskime kontrolü)
- **Per-milestone**: Milestone closure öncesi RAID temizliği (closed assumption + closed issue + dependency satisfied)
- **Per-incident**: Issue olarak eklenir, severity tag, owner assignment

---

## Last Update

- **2026-05-09 (Session 39 iter-2)**: Initial RAID log oluşturuldu (Codex `019e0c28` F5 absorb). 10 assumption + 5 issue + 10 dependency.
- **2026-05-09 (M2 D29 partial evidence + credential blocker)**: Yeni issue I6 — Keycloak test realm admin credential unavailable; M2 D29 authenticated full pipeline BLOCKED. PR #444 lab-deps MERGED; lab dependency smoke LIVE: Mailpit + webhook receiver + Slack mock transport; authenticated notify-orch intent-submit path still BLOCKED. 23.1 sub-faz marker 🟡 partial kalır. Toplam: 10 A + 6 I + 10 D = 48 active boyut (önceki 47'ye +I6).
- **2026-05-18 (I6 stale-resolved → board #777 closed)**: RAID I6 Keycloak credential blocker 🔴 Active → 🟢 Resolved. Kanıt: 2026-05-14 `m2-credential-gate-unblocked.md` (`kc-bootstrap-admin-recovery.sh` master admin recovery) + 2026-05-18 live re-verify (`platform-kc-test` healthy, `kcadm` master login OK, D29 personaları mevcut). Codex `019e3c74` AGREE — stale credential blocker; M2 D29 evidence/acceptance reconciliation ayrı item #754, persona credential Vault formalization ayrı hardening backlog'u (normal user, realm-admin değil). Board açık I-serisi issue mapping'i I2/I4'e düştü; I6 satırı tarihsel kayıt olarak 🟢 Resolved.
- **2026-05-23 (R1 DEFER + R2 closure RAID sync)**: A1 + D-N3b → NetGSM secondary contract **⏳ DEFER** (kullanıcı kararı: sözleşme kısa vadede yapılmayacak; JetSMS-only degraded mode kabul edilen kalıcı işletim durumu; `NetGsmProvider` + Vault/ESO altyapısı asset-preserved — kaldırılmaz, sözleşme olursa reactivation). A2 + D-N5 → R2 KVKK legal review **CLOSED** (Codex `019e5189` final legal verdict AGREE = kabul edilen hukuk onayı; kullanıcı kararı 2026-05-23); D-N5 🔴 → 🟢.

## Next Review

- **2026-05-12**: M1/M2 closure öncesi RAID review (A3, A8, A10 + I1, I2 + D-N7, D-N9)
- **2026-05-16**: İlk weekly stakeholder summary
- ~~2026-05-25: D-N5 KVKK legal review ETA gate~~ — **D-N5 CLOSED 2026-05-23** (R2 Codex `019e5189` final legal verdict); review gate gerekmiyor
