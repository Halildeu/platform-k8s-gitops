# Session 29 Wrap — Faz 18 Full Closure Handoff (2026-04-24)

**Status:** Session 29 FINAL — Faz 18 Compose Dependencies Retirement TAMAMEN KAPANDI.
**Scope:** Faz 18.1 → 18.12 tümü COMPLETE (except 18.8 non-blocking user-Mac trigger).
**Next:** Faz 19 split-repo authority transfer (Codex thread `019dc033` ready).

---

## Bağlam

Session 29 açılışı (2026-04-24 09:55 UTC+3): 3-realm izolasyon netleşmesi (dev lokal Mac / ubuntu test / ubuntu prod). Oturum boyunca Faz 16.8 MSSQL decommission runbook + Faz 17 Local Dev Parity + Faz 18 Compose Retirement zinciri ardı ardına kapandı.

**User direktifleri locked:**
1. "düzgün çalışan sistemleri bozma" (non-destructive pattern)
2. "bekleme yok hızlı güvenli" (24h soak + 72h rollback kaldırıldı)
3. "raporları da taşıyacağız" (ssot vault runbook migration)
4. "discovery service i almayı unutma" (Faz 19 scope note)
5. "Kaynak repo tek amacı geliştirme taşıma" (Faz 19 split-repo hedef)

## İddia: Faz 18 COMPLETE

12 sub-faz tümü tamamlandı (18.8 hariç, Mac user trigger bekleyecek):

| Sub-Faz | Kapsam | Durum | PR |
|---|---|---|---|
| 18.0 | Compose Dependencies Retirement plan + D34 contract | COMPLETE | #98 |
| 18.1 | A0 Live Preflight | COMPLETE | #99 |
| 18.2 | `/api/services/` 410 tombstone | COMPLETE | #100 #101 |
| 18.3 | service-manager retirement (cross-repo) | COMPLETE | #550 #551 + host rm |
| 18.4 | Vault ops replacement (host cron) | COMPLETE | #104 #105 #106 #552 |
| 18.5-18.7 | 11 app stateless compose retirement | COMPLETE | #107 #108 #553 |
| 18.8 | Local k3d-dev clean smoke | **PENDING** (user-Mac trigger) | — |
| 18.9 | Observability retirement | COMPLETE | #109 #554 |
| 18.10 | Legacy network cleanup (host-only) | COMPLETE | (host rm) |
| 18.11 | Frontend canonical truth seal (18.11.a) | COMPLETE | #109 |
| 18.12 | Truth closure + handoff | COMPLETE | #109 (bu) |

## İspatlar (canlı kanıtlar)

### 1. 14 compose container retire (staging-sw)

- Faz 18.2: 0 container (tombstone route-level)
- Faz 18.3: 1 container (service-manager-1)
- Faz 18.4: 2 container (vault-snapshot-1 + vault-audit-init-1)
- Faz 18.5-18.7: 11 container (9 app + permission-service + openfga-migrate)
- Faz 18.9: 5 container (grafana + prometheus + tempo + loki + promtail)
- Faz 18.10: 4 Created zombie (keycloak-1 + vault-1 + postgres-db-1 + vault-unseal-1)
- **Toplam:** 23 container retired (14 active + 4 zombie + 5 observability)

### 2. Final staging-sw compose state (9 containers)

```
platform-pg-prod          (D6 ✓)
platform-kc-prod          (D6 ✓)
platform-vault-prod       (D6 ✓)
platform-pg-test          (D6 ✓)
platform-kc-test          (D6 ✓)
platform-vault-test       (D6 ✓)
platform-web-nginx        (edge prod ✓)
platform-web-nginx-stage  (edge test ✓)
platform-test-registry    (k3d-test registry ✓)
```

ADR-0002 D6 UPHELD + edge ayakta + 3-realm izolasyon korundu.

### 3. K8s pod sağlık (zero regression tüm retirement boyunca)

- platform-prod: **19 Running** + 1 Completed (stabil 8d+)
- platform-test: **10 Running** + 1 Completed (stabil)
- monitoring: **11 Running** (kube-prometheus-stack 8d uptime)

### 4. Edge routing (unchanged)

- `ai.acik.com` → K8s prod NodePort `127.0.0.1:30443`
- `testai.acik.com` → K8s test NodePort `127.0.0.1:31080` + `127.0.0.1:5545`
- `/api/` → 401 JWT flow (auth chain K8s alive)
- `/realms/master/` → 200 (KC compose stateful)
- `/api/v1/authz/version` → 401 "JWT token zorunludur" (OpenFGA parity PASS)

### 5. 31 cross-repo PR Session 29

- **platform-k8s-gitops**: 25 merged (PR #84-#108) + 1 open (#109 bu)
- **platform-ssot**: 4 merged (#550-#553) + 1 open (#554)
- **Total:** 30 merged + 2 open = 31 cross-repo PR 4-gün

### 6. 9 Codex AGREE thread Session 29

Bkz. current-state.md Session 29 +22 delta.

## İspatlamaz (henüz kanıtlanmamış / pending)

### Faz 18.8 — Mac k3d-dev clean smoke

**Neden pending:** Mac host bağımsız trigger gerekli (Session 29 staging-sw focused).

**User action:**
```bash
cd <clean-worktree>
./bootstrap/setup-clusters.sh dev
./scripts/dev-up.sh --profile authn-min
./scripts/dev-seed.sh --profile authn-min
./scripts/dev-smoke.sh --profile authn-min
```

Sonuç `docs/phase18-evidence/local-dev-smoke-<date>.md` dosyasına yazılır.

## Bilinen boşluklar (next session öncelik)

1. **Faz 18.8 Mac smoke** (non-blocking evidence lane)
2. **Faz 19 plan-time Codex iter** (`019dc033` ready, impl blocks on truth closure → TAMAMLANDI)
3. **Faz 19.1-19.9 impl** (kaynak kod migration: discovery-server + Java backends + Zanzibar + reports)
4. **Vault AppRole scoped policy** (Faz 18.4 Codex guardrail, 18.4.b hardening DEFERRED)

## Faz 19 hazırlık (next session)

**Hedef:** platform-ssot kaynak kod → yeni `app-source` repo migration.

**Codex `019dc033` 10-step önerisi:**
- 19.0: Authority reset (platform-k8s-gitops = manifest/docs/ops)
- 19.1: Yeni app-source repo oluşturma + git filter-repo history preservation
- 19.2-19.3: Backend Java migration batch 1 (auth-service + user-service + variant-service)
- 19.4: Zanzibar plane migration (permission-service + OpenFGA Java + common-auth/openfga)
- 19.5: Core + report + schema services
- 19.6: **discovery-server** (user note) + api-gateway
- 19.7: Frontend source (Option B canonical → new repo as non-authoritative backup)
- 19.8: Reports + observability K8s manifest
- 19.9 (OPTIONAL): platform-ssot repo delete

**Commitment:** 19.2+ execution blocks on 18.12 truth closure ← **TAMAMLANDI**.

## Session 30 aç

Yeni session açıldığında:
1. Okuma sırası: AGENTS.md → context-priority-rules.md → current-state.md → bu handoff
2. İlk aksiyon: Faz 19 plan-time detaylı Codex consult (`019dc033` thread devam) veya Faz 18.8 Mac smoke (kullanıcı hangisini isterse)
3. Mac smoke başka sessionda yapılıyorsa paralel Faz 19.1 (app-source repo create + git filter-repo preflight)

## Referanslar

- [PLAN.md §Faz 18](../PLAN.md) (tümü COMPLETE marker)
- [docs/state/current-state.md](state/current-state.md) (Session 29 +22 delta)
- [ADR-0002](adr/0002-single-host-dual-cluster.md) §0.5 D6 stateful tier
- [docs/phase18-evidence/](phase18-evidence/) (4 evidence doc)
- [docs/RB-vault-ops-host-cron.md](RB-vault-ops-host-cron.md) (Faz 18.4 runbook)
- Codex threads 019dc04d + 019dc07c + 019dc09c + 019dc033

## User kapanış notu

> "düzgün çalışan sistemleri bozmdan yapalım" — UPHELD
> "bekleme yok hızlı güvenli" — UPHELD (no-soak, 3-dakika retirement pattern)
> "raporları da taşıyacağız" — UPHELD (4 vault runbook migrated)
> "discovery service i almayı unutma" — UPHELD (Faz 19 scope note)
> "Kaynak repo tek amacı geliştirme taşıma" — UPHELD (Faz 19 ready)

Zero regression + 3-realm izolasyon + ADR-0002 D6 + Codex adversarial AGREE + user hard rules.
