# Compose Stack Allowed List (D6 Final State)

> **Status**: SEALED 2026-04-25 (Faz 20 bridge proxy decommission sonrası)
> **Authority**: ADR-0002 D6 (stateful tier compose) + bu doc
> **Scope**: staging-sw Ubuntu host'ta çalışan Docker container'lar
> **Update**: Yeni container ekleme/çıkarma → ayrı PR + ADR addendum

---

## Allowed Containers (13 — TAMAMI BİLİNÇLİ)

### Kategori 1: D6 Stateful Tier (6 container)

State migration K8s'e karmaşık + risk; **bilinçli compose'da tutulur** (ADR-0002 D6):

| Container | Image | Network | Amaç |
|---|---|---|---|
| `platform-pg-prod` | postgres:16-alpine | platform-prod-net | Prod PostgreSQL state |
| `platform-pg-test` | postgres:16-alpine | platform-test-net | Test PostgreSQL state |
| `platform-kc-prod` | quay.io/keycloak/keycloak:26.5.5 | platform-prod-net | Prod Keycloak realm |
| `platform-kc-test` | quay.io/keycloak/keycloak:26.5.5 | platform-test-net | Test Keycloak realm |
| `platform-vault-prod` | hashicorp/vault:1.17 | platform-prod-net | Prod secrets store |
| `platform-vault-test` | hashicorp/vault:1.17 | platform-test-net | Test secrets store |

K8s pod'ları bu container'lara **bridge Endpoints** (172.X.0.X) üzerinden bağlanır.

### Kategori 2: Edge SSL Termination (2 container)

D8/D18 host nginx pattern — wildcard cert `*.acik.com` Sectigo manuel; cert-manager defer.

| Container | Image | Network | Amaç |
|---|---|---|---|
| `platform-web-nginx` | nginx:1.27-alpine | host | ai.acik.com edge SSL termination |
| `platform-web-nginx-stage` | nginx:1.27-alpine | host | testai.acik.com edge SSL termination |

### Kategori 3: K3d Cluster Infrastructure (4 container)

K3d cluster'lar Docker container olarak çalışır. K3d kendi yönetir, manuel müdahale yok.

| Container | Image | Network | Amaç |
|---|---|---|---|
| `k3d-prod-server-0` | rancher/k3s:v1.31.2-k3s1 | platform-prod-net | Prod k3s control plane |
| `k3d-prod-serverlb` | ghcr.io/k3d-io/k3d-proxy:5.7.5 | platform-prod-net | Prod k3d load balancer |
| `k3d-test-server-0` | rancher/k3s:v1.31.2-k3s1 | platform-test-net | Test k3s control plane |
| `k3d-test-serverlb` | ghcr.io/k3d-io/k3d-proxy:5.7.5 | platform-test-net | Test k3d load balancer |

### Kategori 4: Test Registry (1 container)

K3d test cluster image'lar için local registry (Faz 17.4 promotion contract).

| Container | Image | Network | Amaç |
|---|---|---|---|
| `platform-test-registry` | registry:2 | bridge,platform-test-net | Test image registry |

---

## FORBIDDEN — Eski Compose App Stack (RETIRED)

Faz 18.5-18.7 stateless app retirement + Faz 18.4 Vault ops sidecar retirement + Faz 18.9 observability retirement ile **kalıcı olarak compose'dan çıkarıldı**:

```text
platform-service-manager           → Faz 18.4 (Vault ops K8s'e taşındı)
platform-api-gateway               → Faz 18.5-7 (K8s pod)
platform-auth-service              → Faz 18.5-7 (K8s pod)
platform-user-service              → Faz 18.5-7 (K8s pod)
platform-variant-service           → Faz 18.5-7 (K8s pod)
platform-permission-service        → Faz 18.5-7 (K8s pod)
platform-report-service            → Faz 18.5-7 (K8s pod)
platform-schema-service            → Faz 18.5-7 (K8s pod)
platform-core-data-service         → Faz 18.5-7 (K8s pod)
platform-discovery (Eureka)        → D7 (K8s native DNS)
platform-openfga                   → Faz 18 (K8s pod)
platform-grafana                   → Faz 18.9 (K8s kube-prometheus-stack)
platform-prometheus                → Faz 18.9 (K8s)
platform-tempo                     → Faz 18.9 (K8s)
platform-loki                      → Faz 18.9 (K8s)
platform-promtail                  → Faz 18.9 (K8s)
```

**Public debug endpoint'ler tombstoned**:
```
ai.acik.com/api/services/      → 410 Gone
testai.acik.com/api/services/  → 410 Gone
```

---

## DECOMMISSIONED — Faz 20 Bridge Proxy

Faz 20 LIVE GREEN (Calico containerIPForwarding=Enabled) sonrası bridge proxy gereksiz; pod direct → 10.9.193.201:1433:

```text
workcube-mssql-proxy-test          → Faz 20 PR #138 (silindi)
workcube-mssql-proxy-prod          → Faz 20 PR #138 (silindi)
tmp-old-pg                         → 2026-04-25 cleanup (kalıntı pgvector volume)
```

**Bridge proxy cleanup tarihi**: 2026-04-25 19:30 UTC

Rollback path (warm): `bootstrap/archived/workcube-mssql-proxy.sh.faz-20-decommissioned` script'i restore edip çalıştır + manifest revert PR.

---

## Aşama 2 Roadmap (gelecek decommission hedefleri)

### Aşama 2A — D6 Stateful Tier K8s Migration (orta vadeli)

PG/KC/Vault'u K8s StatefulSet'e taşıma:

| Container | Hedef K8s pattern | Risk |
|---|---|---|
| Vault | StatefulSet + Raft storage + cert-manager TLS | Düşük (data migration script + rotate) |
| Keycloak | KC operator + StatefulSet | Orta (realm export/import + downtime ~10 dak) |
| PostgreSQL | StatefulSet + PVC + PgBouncer | Yüksek (data dump/restore + Flyway compat) |

**Neden**: D6 ADR'sının revize edilmesi gerek (state migration K8s'e gerçekleştirildiğinde).

### Aşama 2B — Edge nginx → ingress-nginx K8s (uzun vadeli)

| Adım | Hedef |
|---|---|
| ingress-nginx K8s controller install | Helm chart, NodePort 32080/32443 |
| cert-manager + Let's Encrypt HTTP-01 | Wildcard yerine per-host cert |
| DNS / dış proxy bypass | Edge tamamen K8s ingress |

**Neden**: D8/D18 host nginx pattern revize.

---

## Operasyonel Gözden Geçirme

| Tetikleyici | Doğrulama |
|---|---|
| Yeni container çalışmaya başladı | Bu listede mi? Yoksa **forbidden** olarak ek bilgi gerek |
| Eski container retire edilecek | Aşama 2A/2B planlamasında mı? Ayrı PR + ADR addendum |
| Hard rule: max 13 container | `ssh halil@staging-sw "docker ps -q \| wc -l"` ≤ 13 |

## Bağlantılar

- ADR-0002 D6 (stateful tier compose)
- D8/D18 (host nginx edge — D18 K8s ingress alternatifi planlanır)
- Faz 18.4-18.9 (compose retirement aşamaları)
- Faz 20 (bridge proxy decommission)
- PR #138 (atomic decommission swap)
