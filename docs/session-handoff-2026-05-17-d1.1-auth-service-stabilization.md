# Session Handoff — 2026-05-17 — D1.1 auth-service Stabilization Wave KAPANDI

> **Format**: D28 5-alan + sıradaki agent P0 aksiyon listesi
> **Status**: 🟢 D1.1 dalgası KAPANDI — credential ✅ + config ✅ + Flyway ✅ (Codex `019e3386` ratified)
> **Trigger**: pre-completion natural break + context derinliği — HARD RULE Session Otomatik Açma (2026-05-09)
> **Sıradaki**: credential consolidation EXECUTION — ayrı odaklı sprint (D1.1 kuyruğuna eklenmez; Codex açık verdict)

---

## 1. Bağlam — neden bu handoff

D1.1 dalgası, auth-service'in DB katmanının **sessizce kırık** olduğu RCA bulgusuyla başladı: auth-service Vault `kv/platform/auth-service` `db_password`'ü, paylaşımlı `platform` PG rolünün gerçek password'ünden drift etmişti. Bu oturum üç fazı sırayla kapattı:

- **D1.1c** — Phase 3 RCA: kök neden credential drift olarak kanıtlandı; operator Vault patch + agent ESO sync/rollout ile düzeltildi.
- **D1.1d** — credential-drift döneminden kalan 2 gereksiz Hibernate dialect env'i temizlendi.
- **D1.1e** — Flyway yeniden etkinleştirildi (`ddl-auto: validate` + `flyway.enabled: true`).

Dalga kapandı. Sıradaki yapısal iş — N servisin tek `platform` PG rolünü ayrı Vault kopyalarıyla paylaşmasından doğan **drift sınıfını** ortadan kaldıracak credential consolidation — Codex `019e3386` tarafından **ayrı odaklı multi-faz sprint** olarak kapsamlandı; D1.1c/d/e kuyruğuna eklenecek kadar düşük riskli değil.

## 2. İddia — bu oturumda ne yapıldı (MERGED PR'lar)

| PR | Merge (UTC) | Delta | Kapsam |
|---|---|---|---|
| [#727](https://github.com/Halildeu/platform-k8s-gitops/pull/727) | 2026-05-16 22:36 | +246/-6 | D1.1c Phase 3 RCA — credential drift kök neden + `RB-d1.1c` convergence runbook; `RB-d1.1a` RETRACTED banner |
| [#731](https://github.com/Halildeu/platform-k8s-gitops/pull/731) | 2026-05-16 23:52 | +15/-1 | D1.1c §5.Y.6 — credential drift fix **executed + verified** kanıt bloğu |
| [#734](https://github.com/Halildeu/platform-k8s-gitops/pull/734) | 2026-05-17 00:40 | +12/-16 | D1.1d — auth-service gereksiz Hibernate dialect env cleanup |
| [#737](https://github.com/Halildeu/platform-k8s-gitops/pull/737) | 2026-05-17 01:11 | +13/-21 | D1.1e — auth-service Flyway re-enable (`ddl-auto: validate`, `flyway.enabled: true`) |
| [#738](https://github.com/Halildeu/platform-k8s-gitops/pull/738) | 2026-05-17 01:30 | +106/-0 | credential-consolidation-plan doc — Faz A/B/C, P0 policy allowlist, ayrı sprint |

Her PR cross-AI peer review zincirinden geçti (Claude implementer + Codex reviewer). Codex thread'leri: `019e32d8` (D1.1c — sonradan expire), `019e335c` (D1.1d diff-confirm), `019e3386` (consolidation plan + D1.1 conclusion ratify).

## 3. İspatlar — canlı kanıt (test cluster, 2026-05-17 probe)

auth-service test cluster'da sağlıklı ve stabil — fresh probe:

- **Pod** `auth-service-64f8d7f4bc-s4f25`: `1/1 Running`, **0 restart**, boot `2026-05-17 01:12:13Z` (D1.1e rollout). Deploy `auth-service` `1/1` ready.
- **D1.1c credential fix LIVE** — `HikariPool-1 - Added connection org.postgresql.jdbc.PgConnection@...` boot log'da: eager connection başarılı → drift düzeldi (eskiden lazy path "çalışıyor" görünüp hiç bağlanmıyordu).
- **D1.1d dialect cleanup güvenli** — `HHH035001: Using dialect: org.hibernate.dialect.PostgreSQLDialect, version: 16.13`: Hibernate dialect'i **auto-detect** ediyor; kaldırılan explicit env'ler gereksizdi.
- **D1.1e Flyway re-enable LIVE** — `auth_flyway_history` tablosu: `rank 1 / v1 / BASELINE / success=t`, `rank 2 / v2 / "create auth audit events" / SQL / success=t`.
- **Steady state temiz** — 6h+ pencerede gerçek `ERROR/Exception/FATAL` yok (geniş grep'in yakaladığı 10 satır netty DNS/connection DEBUG trace gürültüsü; uygulama hatası değil — 0 restart bunu doğruluyor).

## 4. İspatlamaz — henüz kanıtlanmamış

- **PROD auth-service**: bu dalga **yalnız test cluster**. Prod auth-service Vault path'i / Flyway state'i / `ddl-auto` config'i doğrulanmadı. Prod ayrı test/prod-split tekrar gerektirir (`docs/context-priority-rules.md` test/prod truth ayrımı); prod credential write açık user approval (ADR-0010).
- **Credential consolidation EXECUTION**: yalnız plan doc merged. 7-servis canonical path repoint + Vault `pg-platform-role` create + policy allowlist — **hiçbiri yapılmadı**.
- **Kardeş 6 platform-role servisi** (user / core-data / variant / permission / notification-orchestrator / endpoint-admin): aynı credential-drift sınıfı için kontrol **edilmedi**. auth-service yüzeye çıkan tek servisti; consolidation sınıfı yapısal kapatana kadar herhangi birinde sessiz drift tekrar mümkün.
- **Browser/UI smoke**: D1.1 backend-only bir dalga (frontend flow yok) → browser verify uygulanmadı (bu dalgaya uygulanabilir değil).

## 5. Bilinen Boşluk + Sıradaki Agent P0 Aksiyon Listesi

### P0 — credential consolidation execution sprint

`docs/architecture/runtime/credential-consolidation-plan.md` §8'deki 5 parça. Codex `019e3386`: **fresh worktree/session** — D1.1 oturumunun derin context'inde yürütülmez. `spawn_task` chip'i bu execution için zaten oluşturuldu.

- **PR-0 (ilk parça)**: policy allowlist diff (`bootstrap/vault-policies/common/eso-runtime.hcl` + `bootstrap-writer.hcl`) + `docs/S2-B1-vault-property-matrix.md` update + preflight checklist runbook. **Runtime repoint YOK.** Bu plan'ın §5'i P0 ön koşul — herhangi bir repoint'ten ÖNCE.
- Sonra: operator Vault gate (`pg-platform-role` create+populate) → pilot tek servis → kademeli rollout → Faz B (`AlUser_App`) → Faz C (per-service roles ADR).

### P1 — drift sınıfı genişletme kontrolü

- **P1-1**: PROD auth-service parity — prod Vault `kv/platform/auth-service` `db_password` ↔ prod `platform` PG rolü eşleşmesi + prod Flyway/`ddl-auto` config. Operator gate.
- **P1-2**: kardeş 6 platform-role servisini aynı credential-drift sınıfı için tara (auth-service tek surfacing'ti; siblings unverified).

### P2 — temizlik

- `docs/d1.1c-flyway-rca-discovery-2026-05-14.md` consolidation sınıfı kapanınca arşivlenebilir/özetlenebilir.

## 6. Yeni Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops/.claude/worktrees/gallant-driscoll-2844e3
cat docs/session-handoff-2026-05-17-d1.1-auth-service-stabilization.md   # bu doc — tam context
cat docs/architecture/runtime/credential-consolidation-plan.md           # P0 sprint planı
```

Consolidation execution → Codex `019e3386` ayrı worktree öneriyor; `spawn_task` chip hazır.

## 7. Referanslar

- D1.1c RCA: `docs/d1.1c-flyway-rca-discovery-2026-05-14.md` §5.Y
- D1.1c convergence runbook: `docs/runbooks/RB-d1.1c-auth-service-credential-convergence.md`
- Credential consolidation plan: `docs/architecture/runtime/credential-consolidation-plan.md`
- Codex thread'leri: `019e32d8` (D1.1c, expired), `019e335c` (D1.1d), `019e3386-f41e-7820-861a-0ab90255e09c` (consolidation + D1.1 conclusion)
- ADR-0010 Vault credential lifecycle + DR; ADR-0011 §2.3 boundary declaration
