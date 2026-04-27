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

Bir feature canlı ürün davranışı kanıtlı sayılması için **5 bağımsız
adımın hepsi staging-sw k3d-test üzerinde gerçekleşmeli ve kanıt
toplanmalı**:

1. **UI scope grant**: admin Veri Erişimi panel üzerinden user'a
   scope atar (örn. `company:wc-company-1001` viewer).
2. **REST INSERT**: backend `/api/v1/access/scope` POST 200 döner;
   response body `scope_id` + `openfga_tuple_id` içerir.
3. **PG INSERT**: `data_access.scope` tablosunda satır görünür;
   trigger fire etmiş (`validate_scope_ref` lineage var; kötü
   scope_ref denenmişse RAISE EXCEPTION ile geri dönmüş).
4. **OpenFGA tuple write**: `permission-service` tuple writer
   outbox/sync ile `company:wc-company-1001#viewer@user:<uid>`
   tuple'ını yazar; OpenFGA `/check` aynı tuple'ı görür.
5. **Authz check**: business endpoint (`/api/v1/reports/...`) veya
   `/authz/me` ilgili user için **allow** döner; başka bir user
   için **deny** döner. Allow + deny her ikisi kanıtlanmalı.

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
