# Promotion Contract (Faz 17.4)

> 3-tier akış: **Lokal dev (Mac)** → **Test (staging-sw k3d-test)** → **Prod (staging-sw k3d-prod + compose)**
>
> Her tier bağımsız smoke gate. "Lokal PASS ≠ testai PASS ≠ prod PASS" — alt tier'deki
> başarı üst tier'de garanti değil; her tier kendi D29 3-katman kanıtını yapar.

---

## 1. Üç Tier Mimarisi

| Tier | Host | Cluster / Stack | Domain | Amaç | Vault Scope | Secret Source |
|---|---|---|---|---|---|---|
| **Lokal dev** | Mac developer machine | k3d-dev (Docker Desktop) | `*.localtest.me` (RFC2606 127.0.0.1) | Kod geliştirme, hızlı inner-loop, smoke test | Yok (fake fixtures) | `bootstrap/local-fixtures/` (NOT_FOR_PROD) |
| **Test (stage)** | staging-sw (Ubuntu 10.9.10.53) | k3d-test | `testai.acik.com` | Merge gate, CI/CD'den çıkan artifact stage smoke | Vault test namespace | ESO ClusterSecretStore `vault-platform-gitops` → test PG/KC |
| **Prod** | staging-sw | k3d-prod + compose stateful | `ai.acik.com` | Canlı trafik | Vault prod namespace | ESO prod + compose PG/KC/Vault (ADR-0002 D31) |

---

## 2. Promotion Akışı

```
┌─────────────────┐
│  Lokal dev      │  dev-up → kod değiştir → dev-smoke PASS
│  k3d-dev        │
└────────┬────────┘
         │ git commit + push
         ▼
┌─────────────────┐
│  PR + CI        │  CI gates:
│                 │  - kustomize build (test/prod/local-* overlay)
│                 │  - yaml/shell lint
│                 │  - no-closure language
│                 │  - placeholder leak check
└────────┬────────┘
         │ merge (Codex AGREE + green CI)
         ▼
┌─────────────────┐
│  ArgoCD sync    │  otomatik:
│  (staging-sw)   │  - platform-test Application → k3d-test reconcile
│                 │  - platform-prod Application → k3d-prod reconcile
└────────┬────────┘
         │
         ├─► Test (testai.acik.com) — D29 3-katman smoke
         │   - Up: pod Running
         │   - Functional: endpoint response shape (401 JWT vs 500)
         │   - Zanzibar-ready: allow + deny enforce authoritative synthetic
         │
         ├─► Prod approval gate (manuel veya otomatik testai PASS)
         │
         └─► Prod (ai.acik.com) — D29 3-katman smoke + 72h rollback-window
```

---

## 3. Her Tier İçin Gate Kriterleri

### 3.1 Lokal dev (k3d-dev)

**Gate: `dev-smoke.sh --profile X` exit 0**

| Profile | Workload | Gates (D29 muadili) |
|---|---|---|
| `authn-min` | 2 | (a) OIDC discovery 200 · (b) Token mint JWT · (c) auth-service :8081 readiness |
| `zanzibar-min` | 6 | authn-min + (d) OpenFGA synthetic allow + (e) /variants scope-aware allow/deny |
| `full` | 10 | zanzibar-min + (f) frontend / render + (g) 9-app actuator |

**Failure handling**: Geliştirici lokalinde fix, commit, re-run dev-smoke. PR'a lokal PASS olmadan göndermez.

**Rollback**: `dev-down.sh` tek saniye (reversible). `--delete` için hiç kalmaz.

**Secret source**: `bootstrap/local-fixtures/` (NOT_FOR_PROD). Gerçek Vault'a erişim YOK. KC realm `dev-local`, dev@localtest.me / viewer@localtest.me users.

### 3.2 Test (staging-sw k3d-test, testai.acik.com)

**Gate: D29 3-katman authoritative synthetic**

1. **Up**: `kubectl get pods -n platform-test` → tüm deployment 1/1 Ready (shared responsibility ArgoCD + staging-sw operator)
2. **Functional**:
   - `curl https://testai.acik.com/` → 200 (frontend)
   - `curl https://testai.acik.com/api/v1/theme-registry` → 200 (report-service)
   - `curl https://testai.acik.com/api/auth/me` (no token) → 401 (JWT required — auth chain aktif)
3. **Zanzibar-ready**:
   - OpenFGA synthetic: `scope_check(admin_user, project:test-1) == allow`
   - Negatif: `scope_check(canary_user, project:test-1) == deny` (authoritative tuple check, fake PASS olmaz)

**Failure handling**: ArgoCD rollback (commit revert) veya kubectl scale replicas=0 emergency stop. current-state.md delta.

**Rollback window**: Test tier'de 24h soak değil, functional gate + Codex post-impl review. Fail → PR revert veya hotfix PR.

**Secret source**: Vault test namespace. ESO ile sync. Manual Vault kv put TEST admin yetkisiyle.

### 3.3 Prod (staging-sw k3d-prod + compose, ai.acik.com)

**Gate: Test PASS + D29 3-katman prod authoritative + 72h rollback-window**

1. Test tier PASS kanıtı (testai 200 + Zanzibar synthetic allow/deny)
2. **Up** (prod): `kubectl get pods -n platform-prod` → 2 replica her backend + 1 openfga StatefulSet + frontend HA
3. **Functional**:
   - `https://ai.acik.com/` → 200 frontend HA byte-perfect
   - `https://ai.acik.com/api/v1/theme-registry` → 200
   - `https://ai.acik.com/realms/serban/.well-known/openid-configuration` → compose KC issuer
4. **Zanzibar-ready**: Prod synthetic tuple check (authoritative, fake PASS YOK).

**Rollback**: Session 28 T0 Hybrid GO pattern — ArgoCD revert + compose rollback pointer 72h warm.

**Secret source**: Vault prod + compose PG/KC/Vault bind-mount state.

---

## 4. Lokal PASS ≠ Testai PASS ≠ Prod PASS

Her tier'in kendi özgün riski vardır:

| Tier | Özgün Risk | Açıklama |
|---|---|---|
| Lokal | Fake data drift | Fake fixtures gerçek source şemasıyla sync değil; lokal PASS, gerçek ERP'de patlayabilir (Faz 16.1 annex 2A source-surface coverage gap) |
| Test | Compose IP drift | Endpoints 172.19.0.x deterministic değil; compose recreate sonrası reconnect-compose-to-test-net.sh |
| Prod | Compose stateful dependency | PG/KC/Vault compose'da (ADR-0002 D31); k3d prod ↔ compose köprü Endpoints sağlığı kritik |

**Kural**: Her tier'de BAĞIMSIZ smoke gate. Alt tier'den gelen PASS propagate edilmez; ispat tier-scope.

---

## 5. Secret Propagation (TEK YÖNLÜ)

```
Lokal fixtures (NOT_FOR_PROD) ─────❌─────> Test/Prod (ASLA)
                    ▲                          │
                    │                          │
                    └──────── Vault test ──────┘
                           (izole, ayrı Vault namespace)
                                  │
                                  ▼
                                Prod (ayrı Vault namespace)
```

- Lokal fixtures → gerçek Vault'a **asla sync edilmez**
- Test Vault → prod Vault **ayrı KV mount** (kesişim yok)
- Prod secret rotation → PR sonrası manuel Vault kv put prod admin yetkisiyle

---

## 6. Ownership Matrix (cross-repo)

| Sorumluluk | `platform-k8s-gitops` | `platform-ssot` |
|---|---|---|
| Inner-loop tooling (Tilt, code watch, image build) | — | **Authoritative** (Faz 17.2) |
| Env/smoke/scaffolding (overlays, scripts, fixtures) | **Authoritative** (Faz 17) | — |
| Application code (Java backend + MFE frontend) | — | **Authoritative** |
| K8s manifest (Deployment/Service/ConfigMap/SA/PDB) | **Authoritative** | — |
| Dockerfile | — | **Authoritative** |
| CI build (image → GHCR) | — | **Authoritative** |
| CI manifest lint/render | **Authoritative** | — |

**Ownership değişirse her iki repo CONTRIBUTING senkron güncellenir** (Faz 17.6).

---

## 7. Codex AGREE Referansları

Bu contract PLAN.md §17.4 deliverable'ı. Plan ping-pong ile mutabakat:
- Thread `019dbe80` iter-1 → iter-4 AGREE (Faz 17 tamamı)
- Key decisions: 3-tier ayrım, profile-based dev smoke, CRD-free lokal, Vault izolasyon, ownership matrix

## 8. Relationship to ADR-0002

- ADR-0002 D6: stateful tier compose'da (PG/KC/Vault) — prod tier için kritik
- ADR-0002 D31: PG primary, MSSQL secondary/opsiyonel — Faz 16 migration scope
- ADR-0002 single-host dual-cluster: staging-sw hostunda test + prod k3d

Bu contract ADR-0002'yi değiştirmez; **operasyonel akış** (kim, ne zaman, nasıl) tanımlar.
