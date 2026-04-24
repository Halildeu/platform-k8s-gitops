# ADR-0004: Split-repo Authority Transfer (platform-ssot → platform-backend + platform-web + platform-k8s-gitops)

**Status**: Accepted (2026-04-24, Faz 19.0)
**Superseded by**: —
**Date**: 2026-04-24
**Context owner**: Faz 19 Split-repo Authority Transfer
**Codex review**: thread `019dc033` (initial) + `019dc0ac` (detailed 10-step, conditional AGREE) — 6 stratejik default kabul edildi

---

## Context

Faz 18 Compose Dependencies Retirement TAMAMEN KAPANDI (2026-04-24, 31 cross-repo PR Session 29 merged). Platform-ssot repo'nun rolü operasyonel olarak bitti; tek kalan amacı **eski geliştirmeleri yeni sisteme taşıma kaynağı** (user direktif 2026-04-24).

Son 4 günde 14 compose container retire edildi + 9 container ADR-0002 D6 stateful tier korundu. Platform-k8s-gitops authoritative manifest/docs/ops repo pozisyonunda.

**User direktifleri (Session 29 locked, ADR sabitlenir):**
1. "Kaynak raporu tek amacı geliştirme taşıma. Başka amaç yok." (2026-04-24)
2. "discovery service i almayı unutma o da çok önemli." (2026-04-24)
3. "raporları da taşıyacağız." (2026-04-24)

Platform-ssot kaynak kod sınıflandırması:
- **Backend Java**: auth + user + variant + core-data + report + schema + api-gateway + discovery-server + permission-service + common-auth/openfga + openfga-runtime
- **Frontend**: web/apps/* (MFE shell + mfe-admin + mfe-reporting + mfe-workbench + design-system)
- **Zanzibar plane**: permission-service + common-auth/openfga + openfga-runtime DSL (fonksiyonel olarak backend'e bağlı)
- **Reports**: mfe-reporting (frontend) + report-service (backend) + migration annex 2A-2B crawler
- **Docs**: 04-operations/RUNBOOKS/* 40+ runbook
- **Build**: Dockerfile + CI workflows + Flyway migrations

---

## Decision

**Faz 19 kapsamında kaynak kod üç repo'ya bölünür:**

### Repo 1: `platform-k8s-gitops` (mevcut, authoritative)
- Kustomize manifests + Helm values + ArgoCD ApplicationSet
- Day-2 ops scripts (pg-dump-cron, vault-snapshot-cron, kc-export-cron, backup-freshness-exporter)
- Grafana dashboards + PrometheusRule
- ADR-0002 + ADR-0003 + **ADR-0004 (bu)** + PLAN.md + docs/state/current-state.md
- host-compose (vault/pg/kc/nginx/web-nginx)
- **Ops runbook canonical**: 40+ ssot runbook'tan ops-level olanlar buraya taşınır (Faz 18.4 vault pattern)
- **Data contract**: docs/migration/mssql-pg-data-contract + report-source-annex **burada kalır** (DRAFT durumu korunur, Faz 16.1 dışa bağımlı)

### Repo 2: `platform-backend` (yeni)
- 8 Java mikroservis: auth + user + variant + core-data + report + schema + api-gateway
- **Zanzibar plane**: permission-service + common-auth/openfga + openfga-runtime (monorepo backend, lockstep coordination; separate repo lockstep PR sayısını patlatır — Codex uyarı)
- **discovery-server**: backend repo içinde `legacy/` veya deprecated module marker ile (runtime D7 Eureka kaldırılmış ama kaynak kod user direktifi ile taşınır)
- Flyway migrations + CI workflow (dual-build transition dönemi)
- Backend-level docs (API specs, modül READMEs)

### Repo 3: `platform-web` (yeni)
- MFE shell + mfe-admin + mfe-reporting + mfe-workbench
- design-system packages + i18n-dicts
- Frontend build CI + promotion-contract uyumlu image pattern
- **Frontend delivery Option B canonical** (host-static nginx); web repo sadece source + build otoritesi olur
- **Faz 18.11.b Option A (K8s frontend authoritative)** migration sonrası karar kapısı (DEFERRED)

### Repo 4 (negative): `platform-zanzibar` **AÇILMAZ**
- Codex uyarı: permission-service/OpenFGA model değişiklikleri diğer backend servisleriyle sık lockstep gerektiriyor
- Ayrı repo PR koordinasyon maliyeti Faz 19 için yüksek
- Backend repo içinde subdirectory olarak kalır

## History Preservation Strategy

**Path-filtered full history** (Codex default AGREE):
- `git filter-repo --path backend/ --path .github/workflows/... --path-rename backend/:/` (backend için)
- `git filter-repo --path web/ --path-rename web/:/` (web için)
- Tek `--subdirectory-filter` YETMEZ (root `.github/workflows`, Dockerfile, CI, migration dosyaları kaybolur)
- **sha-map saklanır**: `docs/faz-19-evidence/sha-map-<repo>.txt` (commit SHA rewrite map; downstream audit için)
- Migration süresince tüm path'lerin tam geçmişi korunur

## Transition Model

**Dual-build + single-consumer** (Codex default AGREE):
- Geçiş döneminde hem ssot hem yeni repo aynı service image'ını üretir (veya farklı image adlarıyla)
- `platform-k8s-gitops` tek bir image digest tüketir (D29 D30 koruma)
- Cutover atomic: sadece gitops overlay `sha-<short>` değişimi + D29 3-layer kanıt
- Moving tag YASAK (D30 kuralı)

## 10-Step Implementation (Faz 19.0 → 19.9)

**Codex thread `019dc0ac` detaylı plan** (ready_for_impl=true conditional):

| Step | Title | Authority | Key Files | Rollback | Evidence |
|---|---|---|---|---|---|
| 19.0 | Authority reset (bu ADR) | gitops | ADR-0004 + docs/context-priority-rules + README pointers | git revert | Repo sınır cümleleri + linkler |
| 19.1 | Yeni repo(lar)ı oluştur + policy kilitle | org policy | GitHub repo settings + branch protections | repo delete | Default branch, required checks |
| 19.1b | git filter-repo preflight dry-run | ssot read-only | Path listesi mühürle (sha-map) | Lokal clone sil | `git ls-tree` path kontrolü |
| 19.2 | Backend batch 1: auth + user + variant | platform-backend | backend/{auth,user,variant}-service/ | filter-repo re-run | `mvn -q -DskipTests package` compile |
| 19.3 | Backend batch 2: permission + Zanzibar | platform-backend | backend/permission-service + common-auth/openfga + openfga-runtime | filter-repo re-run | D29 authz kanıtı (`/api/v1/authz/version` 401) |
| 19.4 | Backend batch 3: core + report + schema | platform-backend | backend/{core-data,report,schema}-service/ | filter-repo re-run | CI build artefact |
| 19.5 | Backend batch 4: api-gateway + discovery-server | platform-backend | backend/{api-gateway,discovery-server}/ | filter-repo re-run | Gateway routing smoke |
| 19.6 | Frontend migration | platform-web | web/apps/* + packages | filter-repo re-run | Host edge smoke (`testai.acik.com/` 200) |
| 19.7 | Reports code split | backend + web + gitops | mfe-reporting + report-service + data contract (docs/migration) | doc revert | Data contract gates "pending" |
| 19.8 | CI + image immutability pipeline migration | yeni repolar CI | .github/workflows/* + gitops image ref | gitops PR revert | `docker manifest inspect` digest |
| 19.9 | Cutover (test→prod atomic) | gitops overlays | kustomize/overlays/{test,prod}/kustomization.yaml | git revert + ArgoCD sync | D29 Up/Functional/Zanzibar-ready ayrı kanıt |
| 19.10 (opt) | Source repo lock/archive | org policy + repo settings | ssot README pointer + read-only flag | archive kaldır | Write disabled confirm |

**Commitment**: 19.2+ execution blocks on 18.12 truth closure ← TAMAMLANDI 2026-04-24 18:04 UTC (PR #109 merged).

---

## Consequences

### Pozitif
- 3-realm izolasyon UPHELD + D6 stateful korundu
- Manifest/docs/ops separation clean (ADR-0003 inner-loop uyumlu)
- Backend + web ayrı CI hızlı iterasyon (cross-cutting change yok)
- Zanzibar plane backend repo'sunda lockstep coordination korunur
- History preservation (blame/audit/debugging için)

### Negatif
- 40+ ssot runbook sınıflandırma iş yükü (ops vs code-level)
- Dual-build dönemi 1-2 hafta CI/registry maliyeti
- Frontend authority belirsizliği (18.11.b defer)
- git filter-repo SHA rewrite → downstream referanslar bozulur (evidence doc PR numaraları gibi); sha-map saklanır ama manuel audit gerekebilir

### Nötr
- Platform-ssot repo read-only kalır (opsiyonel delete Faz 19.10)
- Cross-repo CI workflow coordinated değil (her repo kendi CI'sına sahip)

---

## Alternatives Considered

### Alternative 1: Tek monorepo (`platform-app-source`)
- Reddedildi: Codex öneri "2 repo (backend + web) en az sürpriz". Monorepo CI yavaşlar, lockstep overhead her branch'te.
- Ancak: Faz 19.1 handoff doc'ta "yeni app-source repo" tek hedef diye tarif ediyor. Alternative 1 user'ın ilk tercihi olabilir. **Default 2 repo seçildi; monorepo alternatif user kararı için açık**.

### Alternative 2: Üç repo (backend + web + **zanzibar**)
- Reddedildi: Zanzibar lockstep backend ile sık → PR koordinasyon maliyeti yüksek
- Faz 19 scope için overkill; backend içinde subdirectory yeterli

### Alternative 3: Kaynak kod hiç taşımamak (ssot archive, K8s sadece manifest'ten image build)
- Reddedildi: User direktif "geliştirme taşıma" → aktif development gelecekte olacak
- Ayrıca "discovery service i almayı unutma" → kod taşıma zorunlu

### Alternative 4: Full history rewrite (tek commit squash)
- Reddedildi: Blame/audit kaybolur; Codex "path-filtered full history" en az sürpriz

---

## Implementation Status

**Faz 19.0**: TAMAMLANDI 2026-04-24 (bu ADR'nin merge'i).

**Faz 19.1-19.10**: Implementation blocks on user decision points (aşağıda).

### User decision points (Faz 19.1 öncesi)

Kullanıcı aşağıdaki kararları onaylayınca 19.1 başlar:

| Decision | Codex default | User override? |
|---|---|---|
| Repo count | **2 repo** (backend + web) | Alternative 1 (monorepo) eğer user "tek repo istiyorum" derse |
| Repo naming | `platform-backend` + `platform-web` | User alternative isim önerebilir |
| History scope | Path-filtered full history + sha-map | User "squash history" tercih edebilir (Codex uyarı: blame kaybı) |
| Transition timing | Dual-build 1-2 hafta | Cold-switch daha risky ama tek-gün mümkün |
| Frontend Option A timing | Migration SONRASI | User "aynı pencere" tercih edebilir (Codex uyarı: rollback karmaşık) |
| Reports data migration timing | Kod taşı + data contract gitops'ta DRAFT | User "aynı faza sıkıştır" tercih edebilir (Codex uyarı: annex 2A pending_manual_validation) |

---

## Reversal Conditions

Bu ADR supersede edilirse:
1. User "split-repo değil, mega monorepo istiyorum" derse → Alternative 1'e geç
2. Zanzibar coordination faz boyunca sürekli lockstep breakage üretirse → Alternative 2 (platform-zanzibar ayrı repo) reconsider
3. git filter-repo history corruption kanıtlanırsa → squash history'ye geç + blame kaybı kabul

---

## References

- Faz 19 parent: PLAN.md §Faz 19 (2026-04-24 placeholder, bu ADR ile doldurulacak)
- ADR-0002 §0.5 D6 stateful tier (compose PG/KC/Vault permanent — split-repo bunu etkilemez)
- ADR-0003 inner-loop tooling ownership (Faz 17.6 — split-repo sonrası dev workflow koruma)
- Codex thread `019dc033` (initial 10-step) + `019dc0ac` (detailed 10-step conditional AGREE)
- Session 29 handoff: `docs/session-handoff-2026-04-24-faz-18-truth-closure.md`
- Faz 18 closure: PLAN.md §Faz 18 COMPLETE marker + docs/phase18-evidence/*
