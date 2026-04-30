# Prod Compose Inventory — 2026-05-01

> Sprint "Prod post-cutover compliance" PR-6.
>
> **Scope**: D30 atomic cutover sonrası (T+7 day stable) staging-sw host'unda
> çalışan compose container'larının inventory + sınıflandırma. Bu doküman
> SİLME değil, **sınıflandırma**'dır. Silme/retire planı için PR-7
> (workload compose retire plan) ayrı.
>
> **Live snapshot**: `ssh halil@staging-sw "docker ps"` 2026-05-01 ~01:30 UTC+3.

## Sınıflandırma kriterleri

3 sınıf:

1. **Stateful (D6 — KALICI)**: ADR-0002 D6 contract; prod K8s-dışı, cutover'dan etkilenmez. Kalıcı korunur.
2. **Edge / Proxy (Aktif)**: Public flow için zorunlu; host nginx, k3d ingress proxy gibi.
3. **Ops / CI runtime (Aktif)**: GitHub Actions runner, k3d cluster servers, registry — operasyonel.
4. **Workload residue (CANDIDATES for retire)**: Eski compose pattern'inden kalan stateless workload (varsa).

## Inventory tablosu

| Container | Image | Status | Kategori | Aksiyon |
|---|---|---|---|---|
| `platform-pg-prod` | postgres:16-alpine | Up 7d (healthy) | **Stateful (D6)** | Korunur |
| `platform-kc-prod` | quay.io/keycloak/keycloak:26.5.5 | Up 7d (healthy) | **Stateful (D6)** | Korunur |
| `platform-vault-prod` | hashicorp/vault:1.17 | Up 7d (healthy) | **Stateful (D6)** | Korunur |
| `platform-pg-test` | postgres:16-alpine | Up 9d (healthy) | **Stateful (D6 test)** | Korunur |
| `platform-kc-test` | quay.io/keycloak/keycloak:26.5.5 | Up 8d (healthy) | **Stateful (D6 test)** | Korunur |
| `platform-vault-test` | hashicorp/vault:1.17 | Up 10d (healthy) | **Stateful (D6 test)** | Korunur |
| `platform-web-nginx` | nginx:1.27-alpine | Up 5d | **Edge / Proxy** | Korunur (host nginx, ai.acik.com + testai.acik.com SNI routing) |
| `k3d-prod-serverlb` | ghcr.io/k3d-io/k3d-proxy:5.7.5 | Up 2w | **Ops / CI runtime** | Korunur (k3d-prod cluster ingress proxy 30443) |
| `k3d-prod-server-0` | rancher/k3s:v1.31.2-k3s1 | Up 2w | **Ops / CI runtime** | Korunur (k3d-prod cluster server) |
| `k3d-test-serverlb` | ghcr.io/k3d-io/k3d-proxy:5.7.5 | Up 9d | **Ops / CI runtime** | Korunur (k3d-test cluster ingress proxy 31080/31443) |
| `k3d-test-server-0` | rancher/k3s:v1.31.2-k3s1 | Up 9d | **Ops / CI runtime** | Korunur (k3d-test cluster server) |
| `platform-test-registry` | registry:2 | Up 9d | **Ops / CI runtime** | Korunur (lokal Docker registry, k3d ctr import için) |
| `platform-gha-runner-testai-deploy` | gha-runner-testai-deploy:latest | Up 5h | **Ops / CI runtime** | Korunur (self-hosted GitHub Actions runner, deploy-{backend,frontend}-testai.yml ve deploy-{backend,frontend}-prod.yml için) |

### Workload residue check

```bash
# Eski compose pattern'inden kalan workload var mı?
ssh halil@staging-sw 'docker ps -a --format "{{.Names}}\t{{.Status}}\t{{.Image}}" \
  | grep -iE "platform-(api-gateway|auth|user|variant|core|report|schema|permission|frontend|nginx-stage)" \
  | head -20'
```

**Sonuç (2026-05-01 ~01:30)**: Workload compose container YOK.

`docker ps -a` çıktısında platform-{api-gateway,auth,user,...} veya platform-nginx-stage container'ı bulunmuyor. Bu, geçmişte var olduysa bile T+7 day point'inde (cutover sonrası) kaldırıldığı veya hiç yaratılmadığı anlamına geliyor.

> **Önemli not**: Session 28 cutover'dan önce eski iki-host (`staging-sw-1` + `staging-sw-2`) akışı vardı; o akışta workload compose `staging-sw-1` üzerindeydi. Same-host atomic cutover (Codex AGREE 019dbc86) ile workload compose hiç kullanılmadı; doğrudan k3d-prod cluster'a deploy edildi. **Bu yüzden workload residue yok**.

## Compose dosya inventarı

| Dosya | Amaç | Status |
|---|---|---|
| `/home/halil/platform/repo/deploy/docker-compose.prod.yml` | **Eski platform-ssot prod compose** (discovery-server + postgres-db + openfga + 8 backend + frontend) | **DEAD CODE** — referans yok, container yok. Retire candidate (PR-7'de). |
| `/home/halil/platform/repo/backend/docker-compose.yml` | platform-ssot lokal dev backend compose | Lokal-dev only (staging-sw'de aktif değil) |
| `/home/halil/platform/platform-k8s-gitops/gha-runner/docker-compose.yml` | GitHub Actions self-hosted runner compose | **Aktif** (platform-gha-runner-testai-deploy container) |

## Network inventarı

```bash
ssh halil@staging-sw 'docker network ls --format "{{.Name}}\t{{.Driver}}\t{{.Scope}}"'
```

(çıkmaz: bu PR-6 sınıflandırma scope'unda; canlı detay PR-7'de operator runbook'a girer)

## D6 invariant verify (rollback öncesi/sonrası)

```bash
# Stateful tier sağlık check (deploy öncesi/sonrası, daima)
ssh halil@staging-sw 'docker ps --format "{{.Names}}\t{{.Status}}" \
  | grep -E "platform-(pg|kc|vault)-(prod|test)"'
```

Beklenen output:
```
platform-pg-prod      Up X days (healthy)
platform-kc-prod      Up X days (healthy)
platform-vault-prod   Up X days (healthy)
platform-pg-test      Up X days (healthy)
platform-kc-test      Up X days (healthy)
platform-vault-test   Up X days (healthy)
```

Herhangi biri unhealthy / down → **D6 contract violation, immediate escalation**.

## Sonraki PR (PR-7) scope

PR-7 retire plan'ı hedefler:
- `docker-compose.prod.yml` dead code dosyası retire prosedürü (git history'den çıkarma değil; sadece /home/halil/platform/repo/deploy/ dizininden archive)
- Compose pattern'inden eski referansların docs/ ve scripts/ taramayla
- "Workload residue YOK" kanıtının kalıcı dokümantasyonu (postmortem-style)
- Decommission **canlı aksiyonu**: PR-7 plan-only; canlı silme operator runbook (ayrı ssh + onay) ile

## Codex önerisi (019de00f)

> "Doğrudan silme bu sprint'in başında yapılmamalı. Önce inventory, sonra
> sınıflandırma. Stateful D6 korunur, stateless residue ayrılır. Edge/proxy
> aktif rota ve testai/prod SNI path'leri live evidence ile doğrulanmadan
> kaldırılmaz."

Bu PR exactly **inventory + sınıflandırma** kapsamı; canlı silme operasyonu YOK.

## Referans

- ADR-0002 D6 contract: stateful prod K8s-dışı kalıcı
- ADR-0002 Faz D6: same-host hibrit pattern
- `docs/prod-cutover-runbook-v2.md` — cutover scope (T-24h → T+72h)
- `docs/RB-prod-deploy-rollback.md` — post-T+72h deploy rollback (PR-5)
- Codex thread: `019de00f-4b40-75c1-8ead-01b79c5819c1`
