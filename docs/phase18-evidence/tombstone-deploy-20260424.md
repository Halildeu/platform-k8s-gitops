# Faz 18.2 — `/api/services/` Tombstone Canlı Deploy Evidence

> **Timestamp**: 2026-04-24T14:03:35Z (nginx reload signal)
> **Deploy authorized**: User 30-day sandbox permission ("geçici olarak izin veriyorum 30 gün")
> **Parent**: PLAN.md §Faz 18.2 (Codex thread 019dbfa5 iter-3 AGREE)
> **Config source**: `host-compose/web-nginx/default.conf` (PR #100 merged `5040249`)

## Özet

Faz 18.2 deliverable **canlı edge deploy tamamlandı**. Her iki domain (ai.acik.com + testai.acik.com) `/api/services/` endpoint'i **HTTP 410 Gone + JSON tombstone** döndürüyor. Tüm diğer route'lar regression-free.

## Deploy Adımları (executed)

### 1. Config sync

```bash
scp host-compose/web-nginx/default.conf staging-sw:/home/halil/platform/web/nginx/default.conf
```

Başarılı.

### 2. Remote nginx syntax test

```bash
ssh staging-sw 'docker exec platform-web-nginx nginx -t'
```

Output:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### 3. Reload

```bash
ssh staging-sw 'docker exec platform-web-nginx nginx -s reload'
```

Output:
```
2026/04/24 14:03:35 [notice] 213#213: signal process started
reload exit: 0
```

## Live Verification

### Tombstone routes (expect 410)

| URL | HTTP | Response body |
|---|---|---|
| `https://ai.acik.com/api/services/` | **410** ✅ | `{"status":"gone","message":"/api/services endpoint retired. Use ArgoCD UI, Grafana dashboards, or runbook references.","phase":"18.2"}` |
| `https://testai.acik.com/api/services/` | **410** ✅ | Aynı JSON tombstone |

### Regression check (expect unchanged)

| URL | HTTP | Notlar |
|---|---|---|
| `https://ai.acik.com/api/v1/theme-registry` | **200** ✅ | K8s report-service unchanged |
| `https://ai.acik.com/realms/serban/.well-known/openid-configuration` | **200** ✅ | KC compose prod stateful (ADR-0002 D6 korunur) |
| `https://testai.acik.com/` | **200** ✅ | Test edge unchanged |

**Zero regression** — sadece `/api/services/` drift'i kapandı.

## Post-Deploy State

### Edge nginx config delta

```
ai.acik.com location /api/services/:
  BEFORE: proxy_pass http://127.0.0.1:8795 (platform-service-manager-1)
  AFTER:  return 410 '{tombstone JSON}'

testai.acik.com location /api/services/:
  BEFORE: proxy_pass http://127.0.0.1:8795 (same service-manager)
  AFTER:  return 410 '{tombstone JSON}'
```

### Downstream etki

- `platform-service-manager-1` container **hâlâ Up** (Docker socket mount, Node.js API)
- Ancak edge routing artık ona gitmiyor — canlı trafik kesildi
- Container retirement **Faz 18.3 cross-repo ssot PR zinciri** ile:
  - platform-ssot web PR: MFE admin UI + widget cleanup + "Ops Links" replace
  - platform-ssot backend/deploy PR: service-manager-api.js retire + compose blok clean + deploy scripts
  - bu repo PR: 7 gün sonra route tam silme

## Tombstone Deprecation Window

**Start**: 2026-04-24T14:03:35Z
**Target removal**: 2026-05-01T14:03:35Z (7 takvim günü)
**Kriter**: 7 gün + son 24h 0 hit → Faz 18.3 ile birlikte `location /api/services/` block tam silme

### Monitoring

```bash
# Günlük consumer count check
ssh staging-sw "grep '/api/services' /var/log/nginx/access.log | awk '{print \$1,\$7,\$9}' | tail -20"

# Son 24h hit sayısı
ssh staging-sw "grep '/api/services' /var/log/nginx/access.log | awk -v d=\"\$(date -u -d '24 hours ago' +%Y-%m-%dT%H)\" '\$0 >= d' | wc -l"
```

Hit sayısı non-zero kalırsa consumer MFE tarafında ek temizlik gerek (Faz 18.3 ssot PR kapsamı).

## Codex AGREE Uyumluluk

Faz 18 thread 019dbfa5 iter-3 guardrail'ları:
- ✅ 410 Gone semantic (resource permanently gone)
- ✅ 7 gün + 0 hit → route full remove (18.3 birlikte)
- ✅ JSON replacement metni ArgoCD + Grafana + runbook links yönlendirir
- ✅ Compose stateful (PG/KC/Vault) dokunulmaz (ADR-0002 D6)
- ✅ K8s prod routes unchanged (zero regression)

## A0 Preflight vs Deploy Evidence Zincir

| Aşama | Evidence Dosyası | Durum |
|---|---|---|
| A0 Preflight | `a0-preflight-20260424.md` | ✅ PR #99 merged `73d1d42` |
| Deploy | bu doc (`tombstone-deploy-20260424.md`) | Bu PR |
| Tombstone Monitoring | `tombstone-monitor-<daily>.md` | Günlük follow-up |
| Full Removal | `tombstone-removal-<YYYY-MM-DD>.md` | Faz 18.3 ssot complete sonrası |

## Go/No-Go — Sıradaki Sub-Faz

**Faz 18.2 COMPLETE** — tombstone canlı, zero regression, monitor başladı.

Sıradaki: **Faz 18.3 cross-repo service-manager-1 retirement** (platform-ssot + platform-k8s-gitops multi-PR zinciri).

## Referanslar

- PLAN.md §Faz 18.2
- PR #100 (`5040249`): host-compose/web-nginx/default.conf import + patch
- PR #99 (`73d1d42`): A0 preflight evidence
- Codex thread 019dbfa5 iter-3 AGREE
- ADR-0002 D6 stateful tier kontratı (değişmez)
