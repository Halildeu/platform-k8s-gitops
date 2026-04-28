# 0009 — Canlı Scoped E2E Gate (D29 Synthetic'in Karşılığı)

## Status

**Accepted** (2026-04-27) — Session 30 + user 2026-04-26 değerlendirmesi.

Related:
- D29 (PLAN.md) — 3-katman raporlama: Up + Functional + Zanzibar-ready;
  **synthetic allow + deny enforce** kabul edilen kanıt formu.
- ADR-0008 — Multi-org explicit-scope Zanzibar contract (UI mandate +
  PG ↔ OpenFGA tuple writer).
- Faz 21.3 + 21.A within-repo cycle (PR #167-#177) — D29 fixture
  enforcement track.

## Context

Session 30 (`docs/state/current-state.md` Live Delta) bitiminde
şu CI gate set'i landed:

- `openfga-model-drift.yml` — model drift vs platform-backend upstream.
- `openfga-fixture-smoke.yml` — ephemeral OpenFGA + dev-seed.sh + 10
  smoke check (5 allow + 3 deny + 2 containment-deny).
- `data-access-migrations.yml` — V16→V17→V19→V20 + 11-assertion suite
  (CHECK + trigger + UPDATE-smuggling guard + partial UNIQUE).
- `etl-worker-tests.yml` — 159 pytest + ruff + mypy strict.

Bu kanıtlar **D29 (Zanzibar-ready) tanımının "synthetic allow+deny
enforce" gereğini karşılar** — PLAN.md D29 satırının lafzı bu.

Ancak aynı kanıtlar **canlı ürün davranışı** için yeterli değil:
- Kullanıcı UI'dan scope atadığında backend gerçekten `data_access.scope`
  INSERT atıyor mu?
- INSERT trigger fire ediyor mu (lineage validate, kötü scope_ref reject)?
- permission-service tuple writer outbox/sync OpenFGA tuple yazıyor mu?
- Yazılan tuple business endpoint authz check'inde gerçekten allow/deny
  üretiyor mu?

Bu zincirin canlı kanıtı, fixture container içinde değil **staging-sw
cluster'ında** çalışan permission-service + report-service + UI
üzerinden alınır.

User 2026-04-26 değerlendirmesi (Session 30 retrospective):

> "synthetic Zanzibar-ready" ile "canlı scoped access" aynı kapı değil;
> birinciyi geçmek diğerini garanti etmez. Bu ayrım netleşmezse
> fixture sonucu canlıymış gibi rapor edilebilir.

## Decision

**D35 = Canlı scoped E2E gate**, D29 synthetic kapısının üstünde
ayrı + bağımsız bir doğrulama kapısı olarak tanımlanır.

### D29 (synthetic) gereği — değişmez

PLAN.md D29 satırının lafzı korunur:

> Zanzibar-ready = Functional + permission-service hub yayında +
> OpenFGA enabled + `/authz/me`+`/authz/version` + **synthetic allow/
> deny enforce kanıtlı**.

Session 30 itibarıyla **synthetic** bar `openfga-fixture-smoke.yml`
+ 10 smoke check (ephemeral OpenFGA container, CI'da koşar) ile
karşılanır. Bu kalıcı CI gate'tir.

### D35 (canlı) bar — yeni

**2026-04-28 update (V22+V23+PR-G outbox merge sonrası)**: D35 bar 5 adımdan
**11 adıma** genişledi. Outbox transactional pattern (ADR-0008 Tuple writer
flow + Codex `019dd0e0` iter-2) sync-grant semantiğini eventual-consistency
ile değiştirdiği için "POST → immediate allow" assertion artık geçersiz —
"POST → outbox row → poller processed → eventual allow" kanıtlanmalı.

Bir feature canlı ürün davranışı kanıtlı sayılması için **11 bağımsız adımın
hepsi staging-sw k3d-test üzerinde gerçekleşmeli ve kanıt toplanmalı**.
Detay komut sequence'i: `docs/openfga-multi-org-rollout.md` Step 9.

1. **Artifact digest match**: `kubectl get pod permission-service` imageID
   ile gitops kustomize digest pin eşleşmesi.
2. **REPORTS_DB_ENABLED + datasource env**: `REPORTS_DB_*` env vars present,
   `ERP_OPENFGA_ENABLED=true` confirmed.
3. **Outbox poller enabled + config visible**: HikariPool-2 (reports_db)
   started + OutboxPoller scheduler log line.
4. **POST grant creates `data_access.scope` row**: REST 201 + scopeId +
   outboxId + `tupleSyncStatus="PENDING"`.
5. **`data_access.scope` row visible in PG**: scope_ref JSON canonical form
   (`["1001"]`), revoked_at NULL.
6. **Matching `data_access.scope_outbox` PENDING row**: V23 typed columns
   (tuple_user, tuple_relation, tuple_object) populated, attempt_count 0.
7. **Outbox row reaches `PROCESSED`** (eventual consistency): poll PG until
   status flips PENDING/PROCESSING → PROCESSED + processed_at non-null.
8. **OpenFGA `/check` allows granted user**: `{"allowed": true}` for
   `user:<uid>#viewer@company:wc-company-1001`.
9. **Negative user remains denied**: `{"allowed": false}` for non-granted
   user. (D29 third-level synthetic deny enforce — D35 canlı'da da kalır.)
10. **Revoke creates REVOKE outbox row + allow flips to deny**: DELETE 204 +
    REVOKE outbox row PROCESSED + originally-granted user `/check` now
    `{"allowed": false}`.
11. **Zero terminal `FAILED` rows**: `data_access.scope_outbox WHERE status='FAILED'
    AND created_at >= now() - 10min` count = 0.

Önceki 5-adım kontratın değişim haritası:
- Old step 1 (UI grant) → new step 4 (REST grant — UI flow operator tarafından
  Veri Erişimi panel üzerinden yapılır, REST trigger aynı).
- Old step 2 (REST INSERT) → new step 4 (response semantik genişledi:
  `tupleSyncStatus`, `outboxId`, `processedAt`).
- Old step 3 (PG INSERT) → new step 5 (scope_ref V21 JSON canonical).
- Old step 4 (FGA tuple write) → new steps 6+7 (outbox row PENDING → PROCESSED
  eventual; sync-write artık yok).
- Old step 5 (allow + deny) → new steps 8+9 (allow + deny ayrı assertion;
  her ikisi de eventual-consistency sonrası ölçülür).

Yeni adımlar: 1 (digest), 3 (poller config), 6 (outbox row), 7 (PROCESSED),
10 (revoke + flip), 11 (FAILED rows).

### D35 Evidence Ladder (ADR-0010 §2.3)

**2026-04-28 update — ADR-0010 yan ürünü**: Yukarıdaki 11 adımı tek atışta
canlı koşmak için tüm prereq'lerin (image digest, ESO secret delivery,
permission-service pod ready, outbox poller alive, V22+V23 schema applied,
real Workcube `workcube_mikrolink.company` row mevcut, OpenFGA store/model
seeded, JWT actor) eş zamanlı tutulması gerekir. Pratik durumda bu
prereq'ler farklı zamanlarda tamamlanır; "her şey tamam → 11 adımı koş"
beklemek "hiç kanıt yok" durumuna yol açar (PR #192 outbox preflight
sırasında yaşandığı gibi).

ADR-0010 D35 bar'ı **azaltmaz**, ama altına stratifiye edilmiş
**evidence ladder**'ı tanımlar:

| Tier | İsim | Captures | Synthetic data toleransı | D35 bar tatmin? |
|---|---|---|---|---|
| **D35-0** | Runtime Preflight | Image digest, env vars, HikariPool startup, OutboxPoller scheduler, V22+V23 schema present, outbox empty (no rows yet) | Yok (canlı cluster) | Hayır — preflight |
| **D35-1** | Scope Anchor Prereq | Real Workcube `COMPANY` row(s) loaded into `workcube_mikrolink.company` via `etl_worker`; reconcile + audit row produced | Yok — gerçek Workcube | Hayır — prereq satisfaction |
| **D35-2** | Scoped Grant/Revoke E2E | 11-step sequence with real `source_pk`; outbox PROCESSED + OpenFGA allow→deny chain | Yok | **EVET — D35 first evidence** |
| **D35-3** | Product Path | UI panel + real user persona; scope-grant flow product behavior beyond REST-only | Yok — real user identity | Tatmin et + product confidence |

**Per-tier kontrat**:

- **D35-0** examples: PR #192 evidence file (`docs/faz-21-3-evidence/2026-04-28-outbox-isolated-preflight.md`) → tier marker `D35-0`. Yeni image rolling sonrası her zaman bir D35-0 alınır (regression-detect lane).
- **D35-1** kontrat: `etl_worker` Faz 16.2.A "Scope Anchor Load" runbook (DR-6 PR'sında). Ürettiği audit row + `workcube_mikrolink.company.source_pk` örneği D35-1 evidence olarak commit edilir.
- **D35-2** kontrat: `docs/openfga-multi-org-rollout.md` Step 9.1-9.11 hep birlikte (yukarıdaki 11 madde). DR-7'de yapılır.
- **D35-3** kontrat: UI flow + real persona → scope-grant + revoke + check; ayrı evidence dosyası, D35-2'den bağımsız (UI'nın endpoint'leri farklı; D35-2 REST-only, D35-3 UI-driven).

**Per-PR declaration template** (`docs/d35-evidence-template.md`):

PR description'ında D35-X tier(s) advance veya affect ediliyorsa açıkça
beyan edilir. Format:

```text
## D35 ladder declaration

This PR (advances | affects | does NOT touch) the following D35 tier(s):

- [ ] D35-0 — Runtime preflight (regression-detect)
- [ ] D35-1 — Scope anchor prereq (real Workcube row)
- [ ] D35-2 — Scoped grant/revoke E2E (= D35 first evidence)
- [ ] D35-3 — Product path (UI persona)

If "advances": evidence file path + tier marker.
If "affects": brief explanation.
If "does NOT touch": no annotation needed.
```

**Stub data ban (Kural #9 + 2026-04-26 user mandate)**:

Canlı `workcube_mikrolink.company`'ye stub row INSERT YASAK. Stub data
yalnızca:
- Ephemeral CI fixtures (e.g., `data-access-migrations.yml` test PG container)
- `D29-integration-smoke` etiketli evidence içinde (synthetic kanıt formu, **D35 değil**)

D35-0/1/2/3 tier'lerinin hiçbiri stub data ile geçemez.

### Failure modu ayrımı

D29 fail (fixture smoke kırılır) **canlı sistemde** scope assignment
broken **demek değil** — model.fga drift veya tuples.json yanlış
relation kullanmış olabilir; canlı flow yine çalışıyor olabilir.

D35 fail (canlı E2E zincirinde herhangi bir adım kopuk) **canlı
sistemde** kullanıcı yanlış görüntü görüyor demek — gerçek prod
risk.

İki ayrı failure mode = iki ayrı kapı. Aynı CI sembolüyle örtüşmemeli.

### Gate ownership

- **D29 (synthetic)**: agent owns (CI-only, GitHub Actions runner).
- **D35 (canlı)**: operator owns (staging-sw cluster smoke). Agent
  yardımcı: runbook drafts, evidence aggregation, Codex iter
  feedback. Cluster mutate operations operator confirmation gate'li.

### İlk D35 örneği

Faz 21.3 multi-org explicit-scope için D35 tam zincir kanıtı şu
adımları gerektirir (sıralı):

1. **PR-C platform-backend** — permission-service multi-datasource
   (DataAccessScope JPA + ReportsDbDataSourceConfig + tuple writer
   service) merge + image build.
2. **PR-D platform-backend** — `/api/v1/access/scope` REST API
   merge + image build.
3. **PR-E platform-web** — `apps/mfe-access` Veri Erişimi UI panel
   + auth chain + i18n merge + image build.
4. **Staging-sw apply**: gitops PR ile yeni image digest'leri pin
   + ESO `ERP_OPENFGA_MODEL_ID` rotate + 4 service rollout (Faz
   21.3 rollout runbook).
5. **D35 smoke**: yukarıdaki 5 adımı staging-sw'de bir gerçek user
   ile yürüt, her adımda kanıt topla (curl çıktıları + psql query
   sonuçları + OpenFGA `/check` yanıtları).

Sırasız yapılırsa D35 kapısı tam doğrulanmaz; kısmi kanıt fixture
seviyesinde kalır (yine D29 alanına düşer, D35 olmaz).

## Consequences

### Pozitif

- D29 ile D35 net ayrı; CI yeşil = canlı yeşil **iddiası yapılmaz**.
- Fixture/synthetic gate'ler hâlâ değerli (regression safety net) —
  D29 alanında kalmaya devam eder.
- Canlı ürün kapısı operator bilinciyle açılır; surprise prod fail
  riski düşer.

### Negatif / dikkat

- 2 kapı = 2 ayrı raporlama discipline'i. Reviewer bir PR'da "D29
  geçti" gördüğünde otomatik "D35 de geçti" sayamaz.
- D35 her feature için ayrı tetiklenir; ETL run, scope assignment,
  authz check vb. her birinin kendi D35 evidence kümesi olur.
- Tek-bar CI yeterli demek "agent self-completing" iddiasına yol
  açar; D35 explicit operator confirmation kalmalı.

### Rollout etkisi

- PLAN.md D35 satırı eklendi (D32 sonrası).
- Bu ADR (`docs/adr/0009-canli-scoped-e2e-gate.md`).
- Gelecek session handoff dokümanlarında D29 ile D35 ayrı bölüm
  olarak ele alınır.
- Faz 21.3 multi-org explicit-scope canlı E2E için yeni runbook:
  `docs/D35-faz-21-3-canli-scoped-smoke.md` (sonraki PR — bu ADR
  sadece kapı tanımı).

## Alternatives Considered

### A. D29'u genişlet (synthetic + canlı tek bar)

PLAN.md D29 satırına "ve canlı E2E enforce kanıtlı" eklenir.

**Reddedildi**. D29 lafzı şu an mevcut PR/handoff'larda referans;
onu yükseltmek geçmiş "D29 geçti" iddialarını retrospektif
geçersiz kılar. Yeni bar yerine yeni kapı temiz.

### B. D29'u inline derecelen (D29.synthetic, D29.live)

D29 alt-kapılı ifade edilir.

**Reddedildi**. Reviewer cognitive load yüksek; failure mode'ları
ayrı raporlamak için ayrı sembol daha temiz.

### C. ADR yerine PLAN.md tek satır

D35 sadece PLAN.md table row, ADR yazılmaz.

**Reddedildi (kısmen)**. Hem PLAN.md row hem ADR var. Row özet
referans, ADR detay rationale + alt-örnek; gelecekte D35 evidence
patterns adapt edilirken referans noktası gerek.

## Doğrulama

- [x] PLAN.md D-decisions table'a D35 satırı eklendi.
- [x] ADR-0009 dosyası ile detay yazıldı.
- [ ] İlk gerçek D35 evidence kümesi: Faz 21.3 multi-org canlı E2E
      (PR-C/D/E + staging-sw apply + smoke). Bu ADR scope'unun
      DIŞINDA — ayrı runbook + handoff + Codex iter.
- [ ] Gelecek handoff dokümanları D29 ile D35 ayrı bölümlerde
      raporlamayı disiplin haline getirir (D28 5-alan template'in
      "İspatlamaz" alanı bu ayrımı destekler).

## References

- PLAN.md D29 satırı (line 167) + D35 satırı (yeni, D32 sonrası).
- `docs/adr/0008-multi-org-explicit-scope-zanzibar.md` — multi-org
  explicit-scope contract.
- `docs/openfga-multi-org-rollout.md` — staging/prod rollout
  runbook (D35 evidence için zorunlu adımları içerir).
- `docs/session-handoff-2026-04-26-faz-21-3-zanzibar-fixture-sealed.md`
  — D29 synthetic kapısı kapatılan oturum.
- `docs/session-handoff-2026-04-26-supplement-pr-172-175.md` — Session
  30 supplement.
- User 2026-04-26 değerlendirme mesajı (Session 30 retrospective):
  "synthetic Zanzibar-ready" ile "canlı scoped access" aynı kapı
  değil; ayrım netleşmezse fixture sonucu canlıymış gibi rapor
  edilebilir.
