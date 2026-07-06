# BL-015-B/C — Grafana per-template analytics PROD LIVE end-to-end (2026-05-24)

> **Status**: R9 follow-up T4.3.7 BL-015 chain (P0 preflight ✓ + A activation PR #1035 ✓ + **B serial live ops ✓** + **C evidence PR (this doc)**)
> **Scope**: prod cluster k3d-prod monitoring namespace + platform-pg-prod docker container; Pre-Production Full Authority HARD RULE (user explicit auth 2026-05-24)
> **Codex strategic verdict**: thread `019e5a75-ebf3-7860-9832-2776a6d185b6` (BL-015 prod activation path)
> **Codex post-impl A verdict**: thread `019e5aad-8a08-7270-bded-86b5641ba276` AGREE iter-3 (PR #1035)

---

## 1. Bağlam

BL-015-A PR #1035 MERGED (helm-values envValueFrom + ESO remoteRef uncomment). Operator B step zincirinin agent infazı için kullanıcı 2026-05-24 explicit auth verdi (prod cluster state-mutation + Vault credential write izni). G1-G8 verify chain end-to-end.

## 2. B Step Execution Timeline (UTC 2026-05-24)

| Step | Action | Result |
|---|---|---|
| Vault state preflight | `kv/platform/notification-orchestrator` 21-key inventory; root token `/home/halil/bootstrap-drill/vault-init-prod.json` valid | ✅ unsealed initialized |
| PG state preflight | notify schema 3 table mevcut (audit_event_v2 + notification_intent + notification_delivery) | ✅ tables exist |
| **Step A**: Vault seed | `vault kv put kv/platform/grafana/notify-pg-ro password=<32-char>` (random alnum, in-shell only, no terminal log) | ✅ version=1 |
| **Step B**: PG role create | `CREATE USER grafana_notify_ro WITH LOGIN PASSWORD` + GRANT chain | ✅ CREATE ROLE + 3 GRANT |
| ESO not-found preflight | `kubectl get externalsecret grafana-notify-pg-secret -n monitoring` | ❌ NotFound (PR #1035 merge Argo henüz sync etmedi) |
| Manual apply | `kubectl apply -k kustomize/overlays/prod/eso/grafana` | ✅ externalsecret.external-secrets.io/grafana-notify-pg-secret created |
| ESO sync verify | force-sync annotation + ready condition probe | ✅ Ready=True |
| Helm chart version | `kube-prometheus-stack-65.8.0` v0.77.2 (mevcut release) | (helm upgrade 75.4.0 chart incompatibility; alternative manual patch) |
| Strategic merge patch | grafana container envFrom secretRef (sidecar containers'a değil ana grafana'ya) | ✅ rolled out |
| Grafana rollout | `deployment "kube-prometheus-stack-grafana" successfully rolled out` | ✅ Running 1/1 |

## 3. G1-G8 Gate Verification Results

### G1 PASS — DB role auth
```
$ docker exec -i -e PGPASSWORD=$PG_PWD platform-pg-prod psql -U grafana_notify_ro -d notify_db -h localhost -tAc "SELECT current_user, current_database(), 1"
grafana_notify_ro|notify_db|1
```

### G2 PASS — RO-only privilege (direct PG meta-query probe)

**Canonical PG sertifikası — `has_table_privilege` 4-permission matrix**:
```
$ docker exec -u postgres platform-pg-prod psql -d notify_db -tAc "
SELECT 
  has_table_privilege('grafana_notify_ro', 'notify.audit_event_v2', 'SELECT'),
  has_table_privilege('grafana_notify_ro', 'notify.audit_event_v2', 'INSERT'),
  has_table_privilege('grafana_notify_ro', 'notify.audit_event_v2', 'UPDATE'),
  has_table_privilege('grafana_notify_ro', 'notify.audit_event_v2', 'DELETE')"
t|f|f|f
```

Result: SELECT=true, INSERT=false, UPDATE=false, DELETE=false. **Mutating privileges YOK** — RO-only canonical confirmation. PG kendi authorization layer'ı tarafından doğrulandı.

**Supporting evidence (GRANT verify çıktısı)**:
```
grafana_notify_ro|audit_event_v2|SELECT
grafana_notify_ro|notification_delivery|SELECT
grafana_notify_ro|notification_intent|SELECT
```

### G3 PASS — Vault key present + length
```
$ vault kv get -format=json kv/platform/grafana/notify-pg-ro | jq -r '.data.data.password | length'
32
```

### G4 PASS — ESO Ready=True
```
$ kubectl get externalsecret grafana-notify-pg-secret -n monitoring -o jsonpath='{.status.conditions[0].type}={.status.conditions[0].status}'
Ready=True
```

### G5 PASS — K8s Secret key non-empty + length
```
$ kubectl get secret grafana-notify-pg-secret -n monitoring -o jsonpath='{.data.NOTIFY_PG_RO_PASSWORD}' | base64 -d | wc -c
32
```

### G6 PASS — Grafana env injected
```
$ kubectl exec deploy/kube-prometheus-stack-grafana -c grafana -- sh -c 'echo "${#NOTIFY_PG_RO_PASSWORD}"'
32
```

### G7 PASS — Datasource health
```
$ curl -u admin:$PWD http://localhost:3000/api/datasources/3/health
{"message":"Database Connection OK","status":"OK"}
```

Datasource UID: `notify_pg_ro`, type: `grafana-postgresql-datasource`, id: 3.

### G8 PASS (datasource-level) — Per-template SQL query routing LIVE

**Scope**: Datasource-level rawSql via Grafana `/api/ds/query` endpoint. **UI panel-render verify BL-011 ext-gated** (audit_event_v2 son 24h empty data; BL-011 prod canary smoke sonrası data populated panel render UI testi).

```sql
SELECT template_id, COUNT(*) AS send_count
FROM notify.audit_event_v2
WHERE occurred_at > NOW() - INTERVAL '24 hours'
GROUP BY template_id
ORDER BY send_count DESC
LIMIT 20
```

Response: `{"results":{"G8":{"status":200,"frames":[{...,"data":{"values":[]}}]}}}` — Status 200, frames=1, data empty (son 24 saatte audit_event_v2 verisi yok — normal pre-canary state). **Query executed + datasource routing live + SELECT privilege working.**

**Sertifikat**: G8 (a) datasource query API çalışıyor + (b) SELECT privilege ile notify schema reachable + (c) HTTP 200 + JSON response valid. Real dashboard UI panel-render (frame data populated görünür) için BL-011 prod SMS canary smoke sonrası audit_event_v2 row populated olunca yapılır.

## 4. Configuration Drift Notes

### Helm chart version constraint
Release `kube-prometheus-stack-65.8.0` (v0.77.2 — mevcut). helm-values/kube-prometheus-stack/values-prod.yaml envValueFrom değişimi prod overlay'de PR #1035 ile merged. Helm upgrade chart 75.4.0 incompatibility (sizeLimit type mismatch + dashboardsConfigMapRefEnabled nil pointer). **Workaround**: kubectl strategic merge patch ile grafana container envFrom direkt.

**Follow-up**: Helm release chart version 65.8.0'dan upgrade ayrı operator scope. helm-values envValueFrom canonical kalır; gelecekte chart upgrade gerçekleştiğinde otomatik picked up.

### ArgoCD sync state
`platform-eso-prod` application OutOfSync + Degraded — PR #1035 merge Argo henüz auto-sync etmedi. Manual `kubectl apply -k` ile bypass; ArgoCD reconcile aktive olduğunda canonical state match (ExternalSecret mevcut + ESO Ready=True).

**Follow-up**: ArgoCD auto-sync activation veya manuel `argocd app sync platform-eso-prod` operator scope.

### Deploy patch drift
Grafana deployment'a kubectl strategic merge patch (envFrom secretRef) eklendi. Helm release ile drift — gelecek helm upgrade overrides yapacak. Patch survival için helm-values envValueFrom değeri zaten PR #1035 ile present (chart support edince picked up).

## 5. Pre-Production Full Authority Compliance

Kullanıcı 2026-05-24 explicit auth: "Evet, BL-015-B + BL-004 + BL-006b + BL-011 hepsi (Recommended)" — prod cluster state-mutation + Vault credential write izni. Codex iter-2 thread `019e5a75` `agent-actionable conditional` durumunu unblock etti (Vault token doğru path tespit + user explicit auth chain).

Multi-session safety: monitoring namespace (grafana restart) + Vault path (yeni KV entry) — geliştirme workspace etkisi yok.

## 6. Closure

R9 T4.3.7 BL-015 prod end-to-end **LIVE**:
- ✅ G1-G8 8/8 PASS (G2 direct via `has_table_privilege` matrix `t|f|f|f` — SELECT-only canonical)
- ✅ Datasource health "Database Connection OK"
- ✅ Per-template SQL query 200 OK
- ✅ Vault path canonical + ESO sync + Grafana env populated
- ✅ Pre-Production Full Authority compliance + user explicit auth chain

**Operator follow-up (non-blocker)**:
- Helm chart upgrade (65.8.0 → 75.4.0+) chart compatibility fix (kubectl patch drift kalkar)
- ArgoCD auto-sync activation for `platform-eso-prod` application
- audit_event_v2 verisi son 24 saatte 0 row — prod canary smoke (BL-011) sonrası data populated; G8 frame data populated panel render UI testi BL-011 ile birlikte
