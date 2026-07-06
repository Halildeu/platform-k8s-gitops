# RB-grafana-notify-pg-datasource — M7 T4.3.7 Per-Template Analytics Activation

> **Status**: source-ready 2026-05-22 (Codex 019e4ee2 plan-time AGREE — Anthropic/OpenAI cross-AI provider-different)
>
> **Scope**: Operator chain — Grafana PG datasource provisioning + per-template analytics panel activation
>
> **ADR referansı**: ADR-0013 notification-orchestration; ADR-0002 §3.8 (prod = observability hub topology)
>
> **PR-1 (gitops, this repo)**: ConfigMap + ExternalSecret (defer-aware) + per-tenant dashboard panel + runbook + sprint-plan update
>
> **PR-2 (backend, platform-backend repo)**: PostgreSQL index migration on audit_event_v2 (org_id + occurred_at + template_id + event_type)
>
> **Owner**: gitops + ops

## 1. Bağlam

Faz 23.8 M7 T4.3.7 per-template analytics closure scope. Codex 019e4ee2 plan-time verdict:

**Recommended pattern**: `RECOMMEND_PG_FULL_BREAKDOWN_NO_TEMPLATE_PROM_LABEL` — Grafana PostgreSQL datasource read-only query (PG aggregate) + per-tenant dashboard panel + 0 new Prometheus series.

**Why not Prometheus Counter with `template_id` tag**:
- channel(6) × status(8) × org_id(500) × template_id(200) = **4.8M peak series**
- Prometheus default cardinality budget < 100K → 48x patlama
- Reject pattern (Codex 019e4ee2)

**Why PG aggregate read-time approach**:
- audit_event_v2 table mevcut data (Faz 23 LIVE 30+ gün) — schema değişimi gerekmez
- Storage cost: PG row aggregate (cluster-local; no central explosion)
- Query cost: ≤ 2s p95 hedef (24h window, LIMIT 20, tenant scope filter)
- Cardinality safe: tenant-filtered + time-bounded query

## 2. Acceptance Criteria

### PR-1 (gitops, this PR)

- [x] `kustomize/base/monitoring/grafana-datasources/notify-pg-datasource.yaml` (Grafana sidecar datasource ConfigMap)
- [x] `kustomize/base/monitoring/grafana-datasources/kustomization.yaml`
- [x] `kustomize/base/monitoring/kustomization.yaml` (add grafana-datasources/)
- [x] `kustomize/overlays/prod/eso/grafana/externalsecret-grafana-notify-pg.yaml` (defer-aware comment-out)
- [x] Per-tenant dashboard `Top 20 Templates by Send Volume + Success Rate` panel
- [x] `docs/runbooks/RB-grafana-notify-pg-datasource.md` (this file)
- [x] `docs/notify/sprint-plan.md` T4.3.7 row + totals updated
- [x] kustomize build sanity PASS
- [x] Codex cross-AI peer review AGREE

### PR-2 (backend, platform-backend repo — separate PR)

- [ ] `V_next__notify_template_analytics_index.sql` Flyway migration (CONCURRENTLY INDEX; online; low-lock)
- [ ] EXPLAIN ANALYZE p95 ≤ 2s 24h/7d tenant-filtered Top 20 query
- [ ] Index migration online + Flyway transaction handling correct

### Operator activation (PR-1 merge sonrası — ext-gated)

- [ ] DB RO role `grafana_notify_ro` created in prod PG
- [ ] Vault seed: `vault kv put kv/platform/grafana/notify-pg-ro password=<random_32_alnum>`
- [ ] ExternalSecret uncomment in prod overlay
- [ ] Grafana env Secret-backed env var injection
- [ ] helm upgrade kube-prometheus-stack (sidecar reload)
- [ ] Grafana `/api/datasources` includes `uid=notify_pg_ro`
- [ ] Per-tenant dashboard panel renders (24h window; tenant=ai.acik.com test)

## 3. Operator Activation Chain (sequential — DO NOT SKIP STEPS)

### 3.1 DB RO Role Creation (prod cluster PG)

```bash
ssh halil@staging-sw 'kubectl --context k3d-prod -n platform-prod exec deploy/postgres -- psql -U postgres -c "
CREATE USER grafana_notify_ro WITH LOGIN PASSWORD '"'"'<TO_BE_GENERATED>'"'"';
GRANT USAGE ON SCHEMA notify TO grafana_notify_ro;
GRANT SELECT ON notify.audit_event_v2, notify.notification_intent, notify.notification_delivery TO grafana_notify_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA notify GRANT SELECT ON TABLES TO grafana_notify_ro;
-- Verify privileges
SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants WHERE grantee='"'"'grafana_notify_ro'"'"';"'
```

**Beklenen output**: 3 row (audit_event_v2, notification_intent, notification_delivery) × SELECT privilege.

**Password generation** (random_32_alnum):
```bash
openssl rand -hex 16 | head -c 32
# Veya:
< /dev/urandom tr -dc 'A-Za-z0-9' | head -c 32
```

⚠️ **Password güvenliği**: Sadece Vault'a seedle. Terminal log/clipboard temizle. Audit trail için `Vault audit device` enable.

### 3.2 Vault Seed (test cluster Vault'a operator seed — prod ext OAuth)

```bash
docker exec -e VAULT_TOKEN="$PROD_ROOT_TOKEN" platform-vault-prod \
  vault kv put kv/platform/grafana/notify-pg-ro \
    password='<step 3.1 password output>'
```

**Doğrulama (PII-safe — password value'yu terminale basmaz)**:

```bash
docker exec -e VAULT_TOKEN="$PROD_ROOT_TOKEN" platform-vault-prod \
  sh -c 'vault kv get -mount=kv -format=json platform/grafana/notify-pg-ro \
    | jq -e ".data.data | has(\"password\")"'
```

Beklenen output: `true`. Length check:

```bash
docker exec -e VAULT_TOKEN="$PROD_ROOT_TOKEN" platform-vault-prod \
  sh -c 'vault kv get -mount=kv -format=json platform/grafana/notify-pg-ro \
    | jq -r ".data.data | {pw_len: (.password|length)}"'
```

Beklenen: `pw_len = 32`.

### 3.3 ExternalSecret Uncomment (prod overlay)

`kustomize/overlays/prod/eso/grafana/externalsecret-grafana-notify-pg.yaml` aç → defer-aware comment-out block'unu uncomment:

```yaml
# spec.data entry uncomment:
- secretKey: NOTIFY_PG_RO_PASSWORD
  remoteRef:
    key: kv/platform/grafana/notify-pg-ro
    property: password
```

PR aç + merge.

### 3.4 Grafana Env Injection (deployment patch)

kube-prometheus-stack Grafana sub-chart `grafana.envValueFrom` veya `grafana.env` ile env Secret-backed inject:

`helm-values/kube-prometheus-stack/values-prod.yaml` içine:

```yaml
grafana:
  envValueFrom:
    NOTIFY_PG_RO_PASSWORD:
      secretKeyRef:
        name: grafana-notify-pg-secret
        key: NOTIFY_PG_RO_PASSWORD
```

### 3.5 Helm Upgrade (manual sync per ADR-0002 §3.7)

```bash
ssh halil@staging-sw 'helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring -f /home/halil/platform-k8s-gitops/helm-values/kube-prometheus-stack/values-prod.yaml \
  --kubeconfig ~/.kube/config'
```

Grafana sidecar provisioner ConfigMap `grafana-notify-pg-datasource` (label `grafana_datasource=1`) detect eder + Grafana'ya inject eder.

### 3.6 Verification

```bash
# Datasource Grafana'da görünüyor mu?
ssh halil@staging-sw 'kubectl --context k3d-prod -n monitoring \
  port-forward svc/kube-prometheus-stack-grafana 3000:80 &
sleep 2
curl -s -u admin:<grafana_admin_password> http://localhost:3000/api/datasources \
  | jq -r ".[] | {uid, name, type}" | grep notify_pg_ro
kill %1'
```

Beklenen: `{uid: "notify_pg_ro", name: "notify-pg-ro", type: "postgres"}`.

**Panel render test** (Grafana UI veya API):

```bash
# Per-tenant dashboard UID al
curl -s -u admin:<password> http://localhost:3000/api/search?query=notification-orchestrator+per-tenant
# Dashboard JSON çek + Top 20 Templates panelinin "datasource.uid=notify_pg_ro" + query çalıştır
```

Veya Grafana UI: Dashboard → Top 20 Templates panel → 24h time range default → ≤ 2s response.

### 3.7 Hard Verification Gates (Codex 019e4f10 P2 #5 absorb)

Activation chain her adımı **gate** ile doğrulanır — adım atlanmaz, gate
geçmeden sonraki adıma geçilmez.

| Gate | Komut | Beklenen | Fail aksiyonu |
|---|---|---|---|
| **G1 DB role auth** | `psql "host=postgres user=grafana_notify_ro dbname=notify_db" -c 'SELECT 1'` | `1` döner | Role/password yanlış → §3.1 tekrar |
| **G2 DB role RO-only** | (a) datasource ile **aynı connection target**: `PGPASSWORD="$NOTIFY_PG_RO_PASSWORD" psql "host=postgres.platform-prod.svc.cluster.local port=5432 dbname=notify_db user=grafana_notify_ro sslmode=disable" -v ON_ERROR_STOP=1 -c "INSERT INTO notify.audit_event_v2(intent_id,event_type,org_id,topic_key) VALUES('x','x','x','x')"` (b) admin-side: `psql -U postgres -d notify_db -tAc "SELECT has_table_privilege('grafana_notify_ro','notify.audit_event_v2','INSERT') OR has_table_privilege('grafana_notify_ro','notify.audit_event_v2','UPDATE') OR has_table_privilege('grafana_notify_ro','notify.audit_event_v2','DELETE')"` | (a) `ERROR ... SQLSTATE 42501` (`permission denied for table audit_event_v2`) — **yalnız 42501 PASS**; başka error tipi (auth fail, connection fail) PASS DEĞİL (b) `f` (false) | Yazma yetkisi var (`t`) veya 42501 dışı error → GRANT'ları gözden geçir (§3.1 SELECT-only) |
| **G3 Vault key present** | `vault kv get -format=json kv/platform/grafana/notify-pg-ro \| jq -e '.data.data.password \| length == 32'` | `true` | Vault seed eksik → §3.2 |
| **G4 ESO Ready=True** | `kubectl -n monitoring get externalsecret grafana-notify-pg-secret -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'` | `True` | ESO force-sync: `kubectl annotate es grafana-notify-pg-secret force-sync=$(date +%s) --overwrite` |
| **G5 Secret key non-empty** | `kubectl -n monitoring get secret grafana-notify-pg-secret -o jsonpath='{.data.NOTIFY_PG_RO_PASSWORD}' \| base64 -d \| wc -c` | `32` | Secret boş → ESO data uncomment kontrolü (§3.3) |
| **G6 Grafana env injected** | `kubectl -n monitoring exec deploy/kube-prometheus-stack-grafana -- sh -c 'test -n "$NOTIFY_PG_RO_PASSWORD" && echo SET'` | `SET` | helm-values envValueFrom eksik → §3.4 + helm upgrade |
| **G7 Datasource query smoke** | Grafana `/api/datasources/uid/notify_pg_ro/health` (POST) | `{"status":"OK"}` | Connection fail → sslmode/url/credential gözden geçir |
| **G8 Panel data render** | Grafana UI Top 20 Templates panel 24h window | Satır döner (veya tenant-data-yoksa boş, hata YOK) | `column does not exist` → dashboard SQL drift; `permission denied` → G2 |

**Gate disiplini**: G1-G8 sıralı; her gate geçmeden sonraki adım YAPILMAZ.
G2 (RO-only negative probe) **zorunlu** — Grafana datasource read-only
iddiasının DB-level enforce edildiğini kanıtlar (Grafana UI `editable:false`
tek başına yetmez; mutating query DB role privilege ile bloklanmalı).

## 4. Query Design (panel SQL — Codex 019e4ee2 + 019e4f10 iter-2 absorb)

> **Source-of-truth**: aşağıdaki SQL, dashboard ConfigMap panel id=8 `rawSql`
> ile **birebir hizalıdır** (kustomize/base/monitoring/grafana-dashboards/
> notification-orchestrator-per-tenant-dashboard.yaml). Drift olursa dashboard
> rawSql canonical kabul edilir; bu §4 ona göre güncellenir (Codex 019e4f10
> iter-2 P3 absorb — eski event_type-based success wording düzeltildi).

**Source table**: `notify.audit_event_v2` (Faz 23 schema; `template_id` column
mevcut) + `notify.notification_delivery` JOIN (terminal status truth).

**Template key resolution** (null-safe fallback — `WHERE COALESCE(...) IS NOT
NULL`, `template_id IS NOT NULL` DEĞİL; iter-2 P1 absorb — fallback reachable):

```sql
COALESCE(ae.template_id, ae.details->>'template_id', ae.topic_key) AS template_key
```

**Send volume**: `COUNT(DISTINCT ae.delivery_id)` (retry'leri tek seferden saymaz).

**Success rate**: `notification_delivery.status` terminal truth üzerinden
(audit_event_v2 `event_type` DLR async flow için terminal DEĞİL — iter-2 P1
absorb). LEFT JOIN `nd.id = ae.delivery_id` (notification_delivery PK = `id`):
- success: `nd.status = 'DELIVERED'`
- rate: `success_count / NULLIF(total_count, 0) * 100`

**Grafana SQL pattern** (panel datasource query — dashboard rawSql ile aynı):

```sql
SELECT
  COALESCE(ae.template_id, ae.details->>'template_id', ae.topic_key) AS template_key,
  COUNT(DISTINCT ae.delivery_id) AS total_count,
  COUNT(DISTINCT nd.id) FILTER (WHERE nd.status = 'DELIVERED') AS success_count,
  (COUNT(DISTINCT nd.id) FILTER (WHERE nd.status = 'DELIVERED')::numeric
    / NULLIF(COUNT(DISTINCT ae.delivery_id), 0) * 100)::numeric(5,2) AS success_rate_pct
FROM notify.audit_event_v2 ae
LEFT JOIN notify.notification_delivery nd ON nd.id = ae.delivery_id
WHERE
  ae.org_id = ${tenant:sqlstring}
  AND ae.occurred_at BETWEEN $__timeFrom() AND $__timeTo()
  AND COALESCE(ae.template_id, ae.details->>'template_id', ae.topic_key) IS NOT NULL
GROUP BY template_key
ORDER BY total_count DESC
LIMIT 20;
```

> Not: `${tenant:sqlstring}` Grafana SQL-safe escape (manual single-quote
> YASAK — SQL injection); tenant variable `multi=false`/`includeAll=false`
> single-select (equality predicate uyumu — iter-2 P2 absorb).
> `$__timeFrom()`/`$__timeTo()` Grafana time range macros.

**Guardrails**:
- Default time window: 24h
- Max time window: 7d
- Datasource jsonData `timeout: 2` (Grafana PostgreSQL plugin connection timeout)
- LIMIT 20 (top-K)
- Tenant variable **zorunlu** single-select (`$tenant` selector; all-tenant YOK)

## 5. Cardinality + Performance Budget

| Metric | Budget | Source |
|---|---|---|
| Prometheus series eklenen | **0** | PG datasource, no template_id Prometheus label |
| PG query p95 (24h window, tenant scope) | ≤ 2s | Codex 019e4ee2 acceptance |
| PG query p95 (7d window, tenant scope) | ≤ 5s | PR-2 index sonrası |
| Connection pool | maxOpenConns=5 | datasource ConfigMap |
| Grafana statement_timeout | 1500-2000ms | datasource jsonData |

## 6. Multi-Tenant Hardening (M8 Pre-Req)

Per-template panel **tenant variable filtered**; per-tenant izolasyon Grafana-side dashboard variable + folder model üzerinden değil **datasource-level enforcement** ile (M8 acceptance gate):

- [ ] M8 trigger sonrası: Grafana org/team/folder per-tenant + tenant-scoped datasource credential
- [ ] PR-2 backend acceptance test: cross-tenant query reject (RLS veya app-level filter)
- [ ] Grafana app user `grafana_notify_ro` SELECT-only; UPDATE/DELETE/INSERT yetkisi YOK

## 7. Rollback (Operator)

### 7.1 Datasource Disable

helm-values'tan envValueFrom kaldır + helm upgrade:

```bash
# helm-values/kube-prometheus-stack/values-prod.yaml içinden NOTIFY_PG_RO_PASSWORD env entry sil
# PR aç + merge
helm upgrade kube-prometheus-stack ... # §3.5 same pattern
```

Datasource Grafana'da kalır ama `password` env unset → connection fail; panel "no data".

### 7.2 Datasource Tam Sil

`kustomize/base/monitoring/grafana-datasources/` directory'sini kaldır + base/monitoring kustomization.yaml'dan reference sil:

PR aç + ArgoCD reconcile → ConfigMap silinince sidecar provisioner datasource'u kaldırır.

### 7.3 DB Role Revoke

```bash
ssh halil@staging-sw 'kubectl --context k3d-prod -n platform-prod exec deploy/postgres -- psql -U postgres -c "
REVOKE ALL ON SCHEMA notify FROM grafana_notify_ro;
REVOKE ALL ON ALL TABLES IN SCHEMA notify FROM grafana_notify_ro;
DROP USER grafana_notify_ro;"'
```

## 8. Çapraz-referans

- Codex thread `019e4ee2` (plan-time AGREE — RECOMMEND_PG_FULL_BREAKDOWN_NO_TEMPLATE_PROM_LABEL)
- ADR-0013 notification-orchestration
- ADR-0002 §3.8 (single Grafana prod hub topology)
- Backend PR-2 (separate platform-backend repo) — `V_next__notify_template_analytics_index.sql` Flyway migration
- audit_event_v2 schema (`template_id`, `occurred_at`, `org_id`, `event_type`, `delivery_id` columns)
- Per-tenant dashboard PR #951 (M7 T4.3.6 skeleton)
- B.1 PR #289 (org_id Counter Tag retrofit M8 pre-req)
- Grafana sidecar provisioner pattern (kube-prometheus-stack default)
