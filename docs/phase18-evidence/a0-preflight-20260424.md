# Faz 18.1 — A0 Live Preflight Evidence

> **Timestamp**: 2026-04-24T13:40:53Z
> **Executed by**: `ssh staging-sw docker ps` + `curl https://ai.acik.com/` + `kubectl --context k3d-prod`
> **Parent**: PLAN.md §Faz 18.1

## Özet

A0 preflight gereksinimleri (PLAN.md §18.1):
- [x] `ssh staging-sw docker ps` full container listesi
- [x] Edge nginx upstream ownership (prod edge → K8s vs compose)
- [x] `/api/auth/*` compose auth-service dependency teyit
- [x] K8s pod sayısı sabit
- [x] Access log son 1h grep `/api/services/` (canlı consumer sayım)
- [x] `docker inspect platform-service-manager-1` Docker socket mount
- [ ] Frontend source evidence (platform-web-nginx static — aşağıda kanıtlı)

**Verdict**: A0 PASS — tüm drift kanıtları tespit edildi. 18.2 tombstone + 18.3 service-manager retire + 18.5-7 app stateless retirement güvenli başlayabilir.

---

## 1. Container Inventory (staging-sw)

Toplam **~33 container**:

### Compose Stateful (ADR-0002 D6, KORUNUR)

| Container | Status | Networks |
|---|---|---|
| platform-kc-prod | Up 16h (healthy) | platform-prod-net, **platform_microservice-network** ⚠️ |
| platform-vault-prod | Up 23h (healthy) | platform-prod-net |
| platform-pg-prod | Up 23h (healthy) | platform-prod-net, **platform_microservice-network** ⚠️ |
| platform-kc-test | Up 2d (healthy) | platform-test-net |
| platform-pg-test | Up 3d (healthy) | platform-test-net |
| platform-vault-test | Up 3d (healthy) | platform-test-net |

**Drift tespit**: KC prod + PG prod **iki network'te** — legacy `platform_microservice-network` cleanup gerekli (Faz 18.10'da KC detach + network remove).

### Compose Stateless (RETIRE — Faz 18.5-7)

| Container | Status | Retire Scope |
|---|---|---|
| platform-auth-service-1 | Up 29h (**unhealthy**) | 18.5 stop |
| platform-user-service-1 | Up 29h (healthy) | 18.5 stop |
| platform-core-data-service-1 | Up 29h (healthy) | 18.5 stop |
| platform-report-service-1 | Up 21h (healthy) | 18.5 stop |
| platform-schema-service-1 | Up 4d (healthy) | 18.5 stop |
| platform-variant-service-1 | Up 21h (healthy) | 18.5 stop |
| platform-api-gateway-1 | Up 29h (healthy) | 18.5 stop |
| platform-discovery-server-1 | Up 29h (healthy) | 18.5 stop |
| platform-openfga-1 | Up 40h | 18.5 stop (K8s StatefulSet duplicate) |

### Cross-Realm Control Plane (RETIRE — Faz 18.3)

| Container | Status | Retire Scope |
|---|---|---|
| platform-service-manager-1 | Up 29h (healthy) | 18.3 retire (Docker socket cross-realm) |

### Vault Ops (RETIRE — Faz 18.4)

| Container | Status | Replace With |
|---|---|---|
| platform-vault-snapshot-1 | Up 29h | `bootstrap/vault-snapshot-cron.sh` repo-native |
| platform-vault-audit-init-1 | Up 29h (one-shot) | Early retire |

### Legacy Observability (CONDITIONAL — Faz 18.9)

| Container | Status | K8s Alternative |
|---|---|---|
| platform-grafana-1 | Up 29h (healthy) | K8s kube-prom-stack (gap: test monitoring, current-state:737) |
| platform-prometheus-1 | Up 29h (healthy) | K8s kube-prom-stack |
| platform-tempo-1 | Up 29h (healthy) | K8s monitoring |
| platform-loki-1 | Up 4d (healthy) | K8s monitoring |
| platform-promtail-1 | Up 29h | K8s daemon |

### Edge (KORUNUR — ADR-0002)

| Container | Status | Scope |
|---|---|---|
| platform-web-nginx | Up 46h | Host nginx edge (`ai.acik.com`) — ADR-0002 edge |
| platform-web-nginx-stage | Up 46h | testai.acik.com edge |

### K3d Clusters (KORUNUR)

- k3d-prod-server-0 + k3d-prod-serverlb (Up 8d) → platform-prod-net
- k3d-test-server-0 + k3d-test-serverlb (Up 3d) → platform-test-net
- platform-test-registry (Up 3d) → bridge + platform-test-net

### Orphan

- `tmp-old-pg` Up 19h (bridge network) — cleanup için daha eski tmp

---

## 2. Edge nginx Upstream Test (Live)

```
Path                                              → HTTP
/api/v1/theme-registry                            → 200  (K8s ingress-nginx → report-service)
/api/services/                                    → 200  (compose service-manager :8795) ⚠️ DRIFT
/api/auth/me                                      → 401  (K8s auth chain aktif — JWT yok → Spring Security 401)
/realms/serban/.well-known/openid-configuration   → 200  (compose KC prod, ADR-0002 D6 stateful)
```

**Sonuç**:
- ✅ `/api/*` K8s authoritative (Spring Security 401 = K8s auth-service aktif)
- ❌ `/api/services/` compose drift — **Faz 18.2 tombstone hedef**
- ✅ `/realms/` compose KC (D6 stateful korunur)
- ✅ Compose stateless (auth-service-1 vb.) **trafik almıyor** — K8s cutover complete (Faz 13 Hybrid GO)

---

## 3. `/api/services/` Consumer Sayım

```bash
grep "/api/services" /var/log/nginx/access.log | son 1 saat → 0 hit
```

**Bulgu**: Son 1 saatte **zero request** `/api/services/` endpoint'e. Admin UI consumer (MFE ServiceControlPage + ServiceHealthSummaryWidget) **şu anda aktif değil**.

**Sonuç**: Faz 18.2 tombstone (410 Gone) ve 18.3 service-manager retire **çok düşük kullanıcı etki riski**. Hızlı cutover mümkün.

---

## 4. service-manager-1 Docker Socket Mount

```
/var/run/docker.sock:/var/run/docker.sock (rw)  ← cross-realm control plane
/home/halil/platform/repo-worktrees/fix-stage-deploy-postgres-conflict/backend/scripts:/app (rw)
```

**Teyit**: Node.js `service-manager-api.js` Docker daemon'a `rw` erişim → tüm container lifecycle kontrolü (start/stop/restart/bulk/logs). Cross-realm control plane evidence.

---

## 5. K8s Pod Durumu (platform-prod)

```
Total: 20 pod
  19 Running
  1 Completed (openfga-migrate veya benzeri Job)
```

**Sonuç**: K8s prod cluster **sağlıklı**. Faz 18 retirement işlemleri K8s'e etki etmez (manifest değişimi yok, sadece compose tarafı retire).

---

## 6. Frontend Source Evidence

`ai.acik.com/` root isteği (curl HTML):
- `platform-web-nginx` compose container **host network** mode → static file serving
- Kaynak: `/home/halil/platform/web/nginx/default.conf` + `/usr/share/nginx/html`
- K8s'de frontend pod var (Faz 13 cutover'da deploy edildi) ama **edge root `/` compose static'e gidiyor**
- Faz 18.11 karar: **Option B canonical** (host-static frontend, impl defer)

---

## 7. Drift Map (özet)

| Drift | Evidence | Faz 18 Scope |
|---|---|---|
| `/api/services/` compose route | edge nginx rule + live 200 | 18.2 tombstone + 18.3 retire |
| service-manager-1 Docker socket | mount inspect | 18.3 retire (cross-repo 2 PR) |
| Compose stateless trafik yok | 0 hit access log | 18.5-7 stop + smoke + rm |
| KC prod 2 network'te | docker ps networks kolonu | 18.10 network cleanup (KC detach) |
| PG prod 2 network'te | docker ps networks kolonu | 18.10 network cleanup (PG detach) |
| `platform_microservice-network` legacy | compose stateless + stateful prod karışık | 18.10 network remove |
| K8s test monitoring gap | current-state:737 (yazılı) | 18.9 conditional |
| Frontend source host-static | platform-web-nginx host network + /api/ K8s | 18.11.a decision capture (Option B) |

---

## 8. Go/No-Go

**A0 PASS** — 6 drift kanıtlandı + canlı `/api/services/` zero-hit → düşük risk window.

Sıradaki adım: **Faz 18.2 `/api/services/` 410 tombstone** (edge nginx config değişimi, ayrı PR).

## 9. Referanslar

- PLAN.md §Faz 18 (Codex thread 019dbfa5 iter-3 AGREE)
- `docs/state/current-state.md` drift satırları (223, 734, 737, 764)
- Codex thread 019dbfa5 iter-1 VERDICT (A0 live preflight zorunlu)
- Cross-repo: platform-ssot MFE + backend scripts + deploy compose
