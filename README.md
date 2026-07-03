# platform-k8s-gitops

Kubernetes GitOps manifest'leri — autonomous-orchestrator platformu. Bu repo, platform'un Docker Compose'dan Kubernetes'e tam geçişi için **tek desired-state repo**'dur; karar, canlı durum ve tarihsel handoff belgeleri ayrı katmanlarda tutulur.

---

## Amaç

Docker Compose tabanlı `autonomous-orchestrator` platformunu Kubernetes'e taşımak. 2 k3d cluster (test + prod) topoloji, ArgoCD GitOps, Zanzibar authz plane (permission-service + OpenFGA + Keycloak), ESO + Vault secret management.

## Canonical Giriş ve Otorite Zinciri

Bu repo için ilk giriş yüzeyi artık:

1. [AGENTS.md](./AGENTS.md) — repo-geneli bağlam önceliği ve HARD RULE
2. [docs/context-priority-rules.md](./docs/context-priority-rules.md) — otorite zinciri, repo sınırı ve promotion semantiği

Soru tipine göre otoriter kaynak:

1. Canlı truth için [Current State](./docs/state/current-state.md) + live evidence
2. Aktif mimari karar için [ADR-0002](./docs/adr/0002-single-host-dual-cluster.md)
3. Yol haritası ve done kriterleri için [PLAN.md](./PLAN.md)
4. Operasyon adımları için ilgili runbook

`README.md` ve `docs/README.md` navigator'dur; handoff belgeleri tarihsel bağlam taşır ama karar kaynağı değildir.

## Mimari Özet (ADR-0002 sonrası)

> **Ana karar:** [`docs/adr/0002-single-host-dual-cluster.md`](./docs/adr/0002-single-host-dual-cluster.md) — same-host + full stateful isolation

- **Test cluster:** k3d-test (staging-sw, testai.acik.com) — **replicas=1 default** (2026-05-10: HARD RULE — Scale-to-Zero YASAK, D17 deprecated; multi-Claude paralel session güvenliği)
- **Prod cluster:** k3d-prod (**staging-sw aynı host**, ai.acik.com) — D32 separate-host SUPERSEDED
- **Host compose (ayrı instance prod/test):** PG/KC/Vault prod + PG/KC/Vault test (full isolation, `/srv/platform/stateful/{prod,test}/...`)
- **K8s manifest:** 8 backend (auth/gateway/user/variant/core-data/report/schema/permission) + OpenFGA + frontend
- **Secret flow:** Vault AppRole → ESO ExternalSecret → K8s Secret → Pod env (env-neutral path `kv/platform/<svc>`, 2 ayrı Vault daemon)
- **Edge:** host nginx (SSL) → k3d serverlb → ingress-nginx → api-gateway → backend
- **ArgoCD:** prod-hub-only (tek hub prod cluster'da, 2 cluster yönetir; test cred Vault/out-of-band)
- **Observability:** prod kube-prom-stack + test cluster minimal metrics + remote_write prod

### Dev vs Test vs Prod — 3-Tier Model (Faz 17)

> Tam detay: [docs/promotion-contract.md](./docs/promotion-contract.md)

| Tier | Host | Cluster / Stack | Domain | Amaç |
|---|---|---|---|---|
| **Lokal dev** | Mac developer | `k3d-dev` (Docker Desktop) | `*.localtest.me` | Kod geliştirme, inner-loop smoke |
| **Test** | staging-sw | `k3d-test` | `testai.acik.com` | Merge gate, D29 3-katman |
| **Prod** | staging-sw | `k3d-prod` + compose | `ai.acik.com` | Canlı trafik, 72h rollback-window |

**Kural:** `k3d-prod` + `k3d-test` staging-sw runtime target'larıdır (dev değil). Lokal dev için **ayrı** `k3d-dev` cluster (Faz 17.0: `bootstrap/k3d-dev.yaml`, namespace `platform-dev`). Mac'te `k3d-prod`/`k3d-test` çalıştırmak çakışma üretir → YASAK.

Promotion akışı: `dev-smoke.sh PASS` → PR + CI → ArgoCD sync → testai D29 3-katman → prod approval → ai.acik.com.

### Lokal Dev Quick Start (Faz 17)

```bash
# k3d-dev cluster + namespace + overlay apply + fixtures
./bootstrap/setup-clusters.sh dev    # veya: ./scripts/dev-up.sh --profile authn-min
./scripts/dev-seed.sh --profile authn-min
./scripts/dev-smoke.sh --profile authn-min

# Profile seçimi:
#   authn-min    — 2 workload (api-gateway + auth-service), Up + Functional (auth-only)
#   zanzibar-min — 6 workload (+ permission + user + variant + openfga), D29 3-katman
#   full         — 10 workload (9 app + openfga), testai desen paritesi

# Tear-down
./scripts/dev-down.sh              # stop (reversible)
./scripts/dev-down.sh --delete     # tam silme
```

Fake fixtures (`bootstrap/local-fixtures/`): fake RSA PEM, KC realm `dev-local` (dev@localtest.me / viewer@localtest.me), OpenFGA tuples, PG seed SQL. `.env.example` root'ta — `.env` gitignored.

## Dizin Yapısı

```
kustomize/
├── base/
│   ├── apps/<svc>/          # 8 backend + openfga + frontend manifest
│   ├── eso/                 # ClusterSecretStore (overlay patch ile FQDN)
│   └── monitoring/          # PrometheusRule + Blackbox probe + Grafana dashboard
└── overlays/
    ├── test/                # k3d-test patches + eso/ (platform-test ns)
    └── prod/                # k3d-prod patches + eso/ (platform-prod ns)

helm-values/
├── ingress-nginx/           # values-test.yaml + values-prod.yaml (metrics enabled)
├── external-secrets/        # ESO operator values
├── argocd/                  # ArgoCD helm values
├── kube-prometheus-stack/   # Prometheus + Grafana + Alertmanager
├── loki/                    # log aggregation
├── tempo/                   # tracing
└── promtail/                # log shipper

host-compose/
├── postgres/                # prod + test postgres compose
├── keycloak/                # prod + test keycloak compose
├── vault/                   # prod + test vault compose
└── proxy/                   # nginx SSL SNI reverse proxy (D18)

argocd/applications/         # 6 Application (root + test + prod + system + eso-test + eso-prod)

bootstrap/
├── install-on-staging-sw.sh    # same-host dual-cluster bootstrap
├── install-eso-helm.sh         # ESO Helm install + NEXT STEPS
├── install-calico.sh + install-ingress.sh + install-argocd.sh + install-monitoring.sh + install-logs-traces.sh
├── apply-eso-switch.sh         # per-service secret-stub → externalsecret swap
├── backup-freshness-exporter.sh # node_exporter textfile (backup metric)
└── vault-policies/             # eso-runtime.hcl + README

docs/                        # Runbook + handoff + plan pack (aşağıda listeli)

tests/k6/                    # k6 load test profile (S3 soak)
```

## Dokümantasyon

### Runbook'lar

| Dosya | Amaç |
|---|---|
| [docs/state/current-state.md](./docs/state/current-state.md) | Canlı truth snapshot, blocker'lar ve aktif fazlar |
| [PLAN.md](./PLAN.md) | Master roadmap, operasyon kontratı, karar logu ve appendix'ler |
| [docs/semantic-architecture.md](./docs/semantic-architecture.md) | Runtime topoloji + testten proda promotion semantiği |
| [docs/D32-bootstrap-runbook.md](./docs/D32-bootstrap-runbook.md) | Historical / superseded: staging-sw-2 ayrı host bootstrap yolu |
| [docs/prod-cutover-smoke-runbook.md](./docs/prod-cutover-smoke-runbook.md) | S4-D atomic cutover (dış proxy switch + T+5/T+30/T+60 smoke) |
| [docs/S4-rollback-runbook.md](./docs/S4-rollback-runbook.md) | D30 72h warm rollback (5 dk trafik geri alma + teşhis) |
| [docs/S1-S2-acceptance-smoke-runbook.md](./docs/S1-S2-acceptance-smoke-runbook.md) | D29 3-katman smoke (Up/Functional/Zanzibar-ready) |
| [docs/S2-A1-shortname-apply-plan.md](./docs/S2-A1-shortname-apply-plan.md) | Shortname refactor selective apply + rolling restart |
| [docs/S2-X2-nginx-edge-migration.md](./docs/S2-X2-nginx-edge-migration.md) | D18 nginx edge migration (pre-D32 + D32 sonrası) |
| [docs/S5-cert-renewal-runbook.md](./docs/S5-cert-renewal-runbook.md) | Sectigo wildcard yıllık yenileme |
| [docs/S5-capacity-expansion-runbook.md](./docs/S5-capacity-expansion-runbook.md) | Disk/memory/CPU darboğaz + K8s PVC/Quota |
| [docs/S5-disaster-recovery-runbook.md](./docs/S5-disaster-recovery-runbook.md) | Backup + restore drill (PG/KC/Vault/K8s) |
| [docs/S5-vault-audit-retention.md](./docs/S5-vault-audit-retention.md) | Vault audit log retention + review |
| [docs/S5-privileged-access-review.md](./docs/S5-privileged-access-review.md) | AppRole + K8s RBAC + SSH + GHCR PAT review |
| [docs/on-call-triage-playbook.md](./docs/on-call-triage-playbook.md) | 8 alert karar matrisi (ROLLBACK/INVESTIGATE/OBSERVE) |

### Plan & Pack

| Dosya | Amaç |
|---|---|
| [docs/context-priority-rules.md](./docs/context-priority-rules.md) | Canonical bağlam önceliği, authority zinciri ve testten proda promotion semantiği |
| [docs/S2-B1-vault-property-matrix.md](./docs/S2-B1-vault-property-matrix.md) | ESO Vault path + property matrisi + preflight |
| [docs/S2-B2-digest-pin-ci-template.md](./docs/S2-B2-digest-pin-ci-template.md) | Platform-ssot deploy-backend.yml digest pin CI snippet |
| [docs/S2-C-argocd-install-plan.md](./docs/S2-C-argocd-install-plan.md) | ArgoCD install + app-of-apps plan |
| [docs/S2-X3-security-hygiene.md](./docs/S2-X3-security-hygiene.md) | IP sanitize HARD RULE + güvenlik best practice |
| [docs/S3-stability-soak-pack.md](./docs/S3-stability-soak-pack.md) | S3 7-günlük stability soak |
| [docs/promql-query-pack.md](./docs/promql-query-pack.md) | PromQL günlük ops + S3 soak query'leri |

### Handoff

| Dosya | Amaç |
|---|---|
| [docs/session-handoff-2026-04-19.md](./docs/session-handoff-2026-04-19.md) | Son session özeti (D28 5-alan, commit pool, pending iş) |
| [docs/dev-repo-handoff-bundle.md](./docs/dev-repo-handoff-bundle.md) | Dev repo (platform-ssot) için 3 PR konsolide prompt |
| [docs/handoff-S2-B-artifact-hardening.md](./docs/handoff-S2-B-artifact-hardening.md) | W1 ghcr-pull ESO + W3 digest pin CI |
| [docs/handoff-smoke-client-keycloak.md](./docs/handoff-smoke-client-keycloak.md) | Keycloak smoke-client confidential client |
| [docs/handoff-auth-hardcoded-ns-fix.md](./docs/handoff-auth-hardcoded-ns-fix.md) | auth-service application-k8s.yml NS default |

## Başlarken

### Ön Gereksinimler

- Docker 24+ + Docker Compose v2.20+
- kubectl 1.28+ + helm 3.12+ + k3d v5.6+ + kustomize 5.0+
- GitHub SSH deploy key (repo read-only) — `~/.ssh/k8s-gitops-deploy`

### Hızlı Kurulum

```bash
# 1. Cluster'ları oluştur
bash bootstrap/setup-clusters.sh

# 2. Calico CNI
bash bootstrap/install-calico.sh test
bash bootstrap/install-calico.sh prod

# 3. Ingress-nginx
bash bootstrap/install-ingress.sh test
bash bootstrap/install-ingress.sh prod

# 4. ESO + Vault ClusterSecretStore (test pilot)
bash bootstrap/install-eso-helm.sh test
kubectl --context k3d-test -n external-secrets create secret generic \
  vault-approle-secret --from-literal=secret-id=<VAULT_SECRET_ID>
kubectl --context k3d-test apply -k kustomize/overlays/test/eso

# 5. Workload overlay apply
kubectl --context k3d-test apply -k kustomize/overlays/test

# 6. Smoke
# docs/S1-S2-acceptance-smoke-runbook.md 3 katman D29
```

Ana yol kurulumu: `bootstrap/install-on-staging-sw.sh` ve ilgili same-host dual-cluster runbook'ları.
Historical / superseded yol: `bootstrap/install-on-staging-sw-2.sh` + `docs/D32-bootstrap-runbook.md`.

## Karar Logu (Highlights)

- **D1/D16:** 2 k3d cluster (test + prod) aynı host pattern
- ~~**D17:** Test scale-to-zero (yoğun saatlerde RAM=0)~~ **DEPRECATED 2026-05-10** (HARD RULE: TEST Scale-to-Zero YASAK; multi-Claude paralel session safety)
- **D18:** Host nginx SNI SSL termination
- **D20:** Host bridge (test 172.19.0.x platform-test-net, prod 10.9.10.53)
- **D28:** Handoff 5-alan (Bağlam/İddia/İspatlar/İspatlamaz/Bilinen boşluk)
- **D29:** Up ≠ Functional ≠ Zanzibar-ready 3 katman (tek "yeşil" yasak)
- **D30:** Atomic cutover + 72h warm rollback + immutable artifact (digest pin zorunlu)
- **D31:** PG primary, MSSQL secondary/opsiyonel external
- **D32:** Historical / forward-extension path; current main path değil

Tam liste: [PLAN.md](./PLAN.md) Bölüm "Karar Logu".

## Kurallar (HARD RULE)

Canonical kaynak: [AGENTS.md](./AGENTS.md) + [docs/context-priority-rules.md](./docs/context-priority-rules.md). Aşağıdaki maddeler kısa özet niteliğindedir.

- **No closure language:** "kapandı/bitti/gün sonu/pause" YASAK — kullanıcı "dur/yeter/bitti" demedikçe iş devam
- **IP sanitize:** Dış kullanıcı-facing response/doc'ta IP görünmemeli
- **D30 Immutable artifact:** Overlay tag sha-<short> zorunlu, moving tag (`main-stable`) yasak
- **D29 Up ≠ Functional ≠ Zanzibar-ready:** 3 katman ayrı kanıtlanır
- **D30 Weighted YASAK:** Atomic cutover + 72h warm rollback (weighted DNS %10/50/100 YASAK)

## Ana Repo

Backend kaynak kodu + Dockerfile + `application-k8s.yml` profilleri ayrı repoda:
- **platform-ssot** (`/Users/halilkocoglu/Documents/dev/platform-ssot/`)

## Codex Adversarial Protokol

Her büyük delta sonrası Codex MCP adversarial review (plan-time istişare). Detay: [CLAUDE.md](./CLAUDE.md).

## Makefile Ops Wrappers

```bash
make help                    # hedef listesi
make sanity                  # kustomize build all overlays
make lint                    # yaml + shell + kustomize
make apply-test              # canlı apply k3d-test
make apply-prod              # interactive confirm (D30 atomic)
make smoke-test              # testai edge sanity
make install-eso-test        # ESO Helm install
make es-switch-test          # per-service secret-stub → externalsecret
```

Detay: [Makefile](./Makefile) + [CONTRIBUTING.md](./CONTRIBUTING.md)

## Pre-commit Hooks (lokal)

```bash
pip install pre-commit
pre-commit install           # repo hook'u aktif
pre-commit run --all-files   # manuel çalıştır
```

Hooks: no-closure-language (HARD RULE) + kustomize-build-sanity + yamllint + shellcheck + trailing-whitespace.

## Lisans

Internal — ERP/CRM-agnostic platform.
