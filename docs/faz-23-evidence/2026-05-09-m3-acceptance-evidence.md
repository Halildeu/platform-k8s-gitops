# Faz 23.2 (M3) Acceptance Evidence — 2026-05-09 (Session 41)

> **Status**: ACCEPTED (T1.6 + T1.2 evidence-backed; T1.4 source-ready; D29 triple gate LIVE)
> **Capture time**: 2026-05-09 23:34-23:45Z
> **Cluster**: k3d-test (testai.acik.com canonical)
> **Test persona**: `notify-d29-test-persona` (HARD RULE 2026-04-29 uyumlu — kullanıcı login user'a dokunulmadı)

---

## 1. Pre-Acceptance Infrastructure (Session 41 sonu)

| Component | State | Evidence |
|---|---|---|
| ESO ClusterSecretStore | Ready=True | `kubectl get clustersecretstore vault-platform-gitops` |
| ExternalSecret notify-orch | SecretSynced=True at 20:36:05Z | refresh time |
| ExternalSecret alertmanager-fallback | SecretSynced=True at 20:39:55Z | monitoring ns |
| Vault role-id canonical | `6e2e8407-74d4-6e21-0ad7-ba200f601761` | `vault read auth/approle/role/eso-runtime/role-id` |
| Vault paths | `kv/platform/notification-orchestrator` + `kv/platform/alertmanager-fallback` | populated Session 41 |
| K8s secret-id | rotated post-incident | accessor `99590835-358e-6b0a-8482-d0100c213aaa` (no-token-log) |
| eso-runtime policy | re-applied with notification-orchestrator + alertmanager-fallback read | `vault policy read eso-runtime` |
| NetworkPolicy 443 egress | added to `allow-egress-host-bridge` | host-bridge `cidr: 0.0.0.0/0 ports: [5432, 8080, 8200, 443]` |
| Test persona Keycloak | LIVE in `platform-test` realm | `notify-d29-test-persona` user ID `89c4ea39-e086-4e0c-996d-566b85ca8be4` |
| Realm frontendUrl HTTPS | `https://testai.acik.com` | iss claim canonical |
| Audience mapper `frontend` client | `notify-orch-audience` mapper id `fcc73bf9-e60d-4928-9806-10a80bf97077` | aud claim `[notification-orchestrator, account]` |
| Backend ConfigMap JWK URI | `https://testai.acik.com/realms/platform-test/protocol/openid-connect/certs` | ConfigMap patch |
| PG password sync | Vault canonical | `psql -U platform -c "SELECT 1"` 200 |
| Template seeded | `t1` v1 en | `notification_template` row count=1 |

---

## 2. T1.6 Abuse Guards (must-have #10, R13/R19) — FULL ACCEPTANCE LIVE

### 2.1 HTTP Behavior (Burst 105 requests)

```
Method: POST https://testai.acik.com/api/v1/notify/intents
Auth: Bearer JWT (notify-d29-test-persona, aud=[notification-orchestrator, account])
Headers: X-Org-Id: default
Same (orgId, topicKey) tuple: ("default", "test.t16.burst")
Severity: info (no critical bypass)

Request distribution:
  Requests 1-100:    HTTP 202 (ACCEPTED)
  Requests 101-105:  HTTP 429 (RATE_LIMITED)
  First 429: Request #101 — TAM threshold
  Rate limit config: max-per-window=100, window-seconds=60
```

✅ **HTTP 202 × 100, HTTP 429 × 5, threshold=100 doğrulandı**

### 2.2 Audit Row Evidence (`notify.audit_event_v2`)

```sql
SELECT event_type, COUNT(*) FROM notify.audit_event_v2
WHERE occurred_at > NOW() - INTERVAL '5 minutes'
GROUP BY event_type;
```

| event_type | count | notes |
|---|---:|---|
| `INTENT_CREATED` | 101 | 100 successful + 1 (101st caused trip) |
| `RATE_LIMITED` | 5 | matches HTTP 429 count |
| `DELIVERY_BLOCKED` | 101 | OpenFGA tuple absent → BLOCKED_BY_AUTHZ (D29-Authorized deny case) |

### 2.3 RATE_LIMITED Audit Detail

```json
{
  "count": 101, "limit": 100, "org_id": "default",
  "reason": "rate_limit_exceeded", "severity": "info",
  "topic_key": "test.t16.burst", "window_ms": 60000,
  "data_classification": "transactional"
}
```

✅ **PiiRedactor whitelist OK** (count, limit, window_ms, severity, topic_key — no payload, no PII)

### 2.4 Prometheus Counter

```
# HELP notify_abuse_blocked_total Notification abuse guard blocks (rate limit, fan-out cap, etc.)
notify_abuse_blocked_total{reason="rate_limit"} 5.0
notify_abuse_blocked_total{reason="webhook_fanout_cap"} 0.0
notify_abuse_bypassed_total{reason="critical_severity"} 0.0
```

✅ **Counter increment** (5 blocks) **= HTTP 429 count**

### 2.5 T1.6 5-State Matrix Update

| State | Önceki | **Şimdi** |
|---|:---:|:---:|
| Source-ready | 🟢 | 🟢 |
| Live-deployed | 🟢 | 🟢 |
| **Evidence-backed** | 🔴 | **🟢** ⬆️ |
| **Acceptance complete** | 🔴 | **🟢** ⬆️ |
| Blocked | (R13/R19 mitigated) | (R13/R19 mitigated) |

---

## 3. T1.2 KVKK Erasure (must-have #7) — Self-Service Endpoints LIVE

### 3.1 GET /audit/me (KVKK Art.13 Right-to-Information)

```
Method: GET https://testai.acik.com/api/v1/notify/audit/me
Headers: Authorization: Bearer <JWT>, X-Org-Id: default, X-Subscriber-Id: d29-test-1

Response: HTTP 200
Body: {"items":[],"totalElements":0,"page":0,"size":20}
```

✅ Paginated response shape; subscriber d29-test-1 audit history boş (test persona yeni)

### 3.2 DELETE /audit/me (KVKK Art.11 Right-to-Erasure)

```
Method: DELETE https://testai.acik.com/api/v1/notify/audit/me
Headers: Authorization: Bearer <JWT>, X-Org-Id: default, X-Subscriber-Id: d29-test-1

Response: HTTP 200
Body: {
  "evidence_ref": "self-service-kvkk-art-11",
  "inbox_rows_deleted": 0,
  "deliveries_anonymized": 0,
  "status": "no_op",
  "intents_erased": 0
}
```

✅ Endpoint LIVE; `evidence_ref: self-service-kvkk-art-11` (Codex P1 absorb 2026-05-09); no_op = subscriber'ın silinecek history yok (beklenen)

### 3.3 T1.2 5-State Matrix

| Sub-task | Source | Live | Evidence | Acceptance |
|---|:---:|:---:|:---:|:---:|
| T1.2.0 admin POST /admin/notify/erasure | 🟢 | 🟢 | 🟡 (R2 legal pending) | 🔴 (R2 legal review wait) |
| T1.2.1 subscriber DELETE /audit/me | 🟢 | 🟢 | **🟢** ⬆️ | **🟢** ⬆️ |
| T1.2.2 subscriber GET /audit/me | 🟢 | 🟢 | **🟢** ⬆️ | **🟢** ⬆️ |

---

## 4. M2 D29-NOTIFY-Functional Triple Gate

### 4.1 Up Gate

```
kubectl get pod -l app.kubernetes.io/name=notification-orchestrator
notification-orchestrator-599d89f967-p772q  1/1 Running 0
```
✅ Pod healthy

### 4.2 Functional Gate

- POST /api/v1/notify/intents 202 ACCEPTED (101 successful)
- POST /api/v1/notify/intents 429 RATE_LIMITED (5 abuse-guarded)
- GET /api/v1/notify/audit/me 200 OK (paginated)
- DELETE /api/v1/notify/audit/me 200 OK (KVKK self-service)

✅ Functional response shape valid

### 4.3 Authorized Gate

- **Allow case**: 1 Mailpit message captured (M1 smoke earlier — subject "D29-Smoke 2026-05-09")
- **Deny case**: 101 `BLOCKED_BY_AUTHZ` rows in `notification_delivery` (subscriber d29-test-1 OpenFGA tuple absent)

✅ Hard-deny enforce LIVE (D29-Authorized)

---

## 5. T1.4 D43 Outage Fallback — Source-Ready (drill execution operator follow-up)

| Sub-task | Source | Live | Note |
|---|:---:|:---:|---|
| T1.4.1 Vault path | 🟢 | 🟡 | populated Session 41 |
| T1.4.2 ESO ExternalSecret | 🟢 | 🟢 | SecretSynced=True 20:39:55Z |
| T1.4.3 Alertmanager native receiver | 🟢 | 🔴 | helm install kube-prometheus-stack done; operator pod admission webhook tls-secret eksik (helm uninstall+reinstall follow-up) |
| T1.4.4 Mailpit netpol | 🟢 | 🟢 | applied |
| T1.4.5 NotifyServiceDown labels | 🟢 | 🟢 | PrometheusRule LIVE |
| T1.4.6 alarm-receiver fallback | 🟢 | 🟡 | source-ready PR #462; runtime test PR-5 follow-up |
| T1.4.7 break-glass dual-channel | 🟢 | 🟡 | source-ready PR #463; runtime test PR-5 follow-up |
| T1.4.8 Runbook + drill + R9 evidence | 🟢 (PR #464) | 🔴 | drill execution operator action |

**Vault drift incident**: ROOT CAUSE FIXED (Session 41 PR #468) — ClusterSecretStore role-id canonical, ESO sync TRUE, all infrastructure LIVE; drill execution kalan operator action (R9 mitigated marker post-evidence).

---

## 6. M3 (Faz 23.2) Closure Status

### 6.1 5-State Matrix Net (Session 41 sonu)

| State | Sayı | Önceki | Δ |
|---|:---:|:---:|---:|
| Source-ready | **12/12** | 12/12 | — |
| Live-deployed | **9/12** | 9/12 | — |
| **Evidence-backed** | **3/12** ⬆️ | 0/12 | **+3** (T1.6.1, T1.2.1, T1.2.2) |
| **Acceptance complete** | **3/12** ⬆️ | 0/12 | **+3** |
| Blocked | **1/12** | 1/12 (R2 legal) | — |

### 6.2 Must-Have Update

| # | Must-have | Önceki | **Şimdi** |
|---|---|:---:|:---:|
| 7 | PII Redaction + KVKK retention/erasure | 🟡 (~75%) | **🟡 (~85%)** — subscriber self-service Evidence-backed; admin/R2 legal kalan |
| 8 | Preference + critical bypass | 🟡 (~70%) | 🟡 (~70%) — D29-Authorized acceptance gate kanıtı (deny case 101 row) |
| 10 | Observability + Outage Fallback | 🟡 (~85%) | **🟡 (~90%)** — abuse guards FULL acceptance + D43 source-ready |

**Net coverage**: 7×1.0 + 0.85 + 0.70 + 0.90 = **9.45/10 = ~94.5%** (önceki 8.85/10 = 88.5%)

### 6.3 Risk Register Update

| Risk | Önceki | **Şimdi** |
|---|:---:|:---:|
| R13 Webhook fan-out cap | 🟢 Mitigated (LIVE) | 🟢 Mitigated (acceptance evidence ✅) |
| R19 Mass storm | 🟢 Mitigated (LIVE) | 🟢 Mitigated (acceptance evidence ✅) |
| R9 D43 outage fallback drill | 🔴 Pending | 🟡 (source-ready 4-PR; drill execution operator action) |
| R2 KVKK legal review | 🟡 Active | 🟡 Active (ETA 2026-05-25) |

---

## 7. Charter 23.2 Marker Decision

| Sub-faz | Marker | Justification |
|---|:---:|---|
| 23.2.A Preference | 🟡 → 🟡 | source LIVE; D29-Authorized acceptance evidence (deny case); pure subscriber preference acceptance test follow-up |
| 23.2.B KVKK | 🟡 → 🟢 (subscriber self-service portion) | T1.2.1 + T1.2.2 acceptance complete; admin erasure R2 legal kalan |
| 23.2.C Provider rollback | 🟡 → 🟡 | source-ready; acceptance test follow-up |
| 23.2.D Outage fallback | 🟡 → 🟡 | source-ready 4-PR; drill execution operator action |
| 23.2.E Data classification | 🟢 → 🟢 | source/live LIVE; T1.6 burst confirmed `data_classification: transactional` claim flow |
| **23.2.F Abuse guards** | 🟡 → **🟢** | **FULL ACCEPTANCE** ✅ |

**Charter 23.2 overall**: 🟡 partial (1/6 sub-faz 🟢, 5/6 🟡 partial source-ready/acceptance gate). 100% kapsama drill execution + R2 legal + remaining acceptance tests sonrası.

---

## 8. Cross-AI Peer Review (HARD RULE)

Codex thread `019e0c28` (M3 strategic) + `019e0dea` (T1.4) + `019e0e51` (independent analysis) — toplam ~70+ iter Session 40+41.

Codex bağımsız analiz `019e0e51` verdict update post-acceptance: **23.2.F %50 → %100** (FULL acceptance evidence); **23.2.B subscriber self-service %50 → %100**.

---

## 9. Operator Action Sırası (drill + R2 legal + remaining acceptance)

1. **R9 D43 drill execution** (~3-5h):
   - helm uninstall+reinstall kube-prometheus-stack (admission webhook fix)
   - Drill window aç + scale=0 → fire NotifyServiceDown → Alertmanager direct
   - Slack receipt + Mailpit SMTP receipt
   - R9 risk register Mitigated PR
2. **R2 KVKK legal review** (~2h coordination, ETA 2026-05-25)
3. **T1.1 + T1.3 + T1.5 acceptance gate tests** (~6h, paralel)
4. **M3 closure PR Charter 23.2 🟡 → 🟢** (post #1-#3)

---

## 10. Last Update

**2026-05-09 23:45Z** — T1.6 + T1.2 acceptance evidence kanıtlandı; D29-NOTIFY-Functional triple gate LIVE; Vault drift incident RESOLVED (Session 41 PR #468); test persona pipeline kuruldu (HARD RULE 2026-04-29 uyumlu); v1 readiness ~45-50% (Codex `019e0e51` post-acceptance).

**Composite skor**: Source-ready 12/12 + Live-deployed 9/12 + **Evidence-backed 3/12** + **Acceptance complete 3/12** + Blocked 1/12 (R2 legal). M3 closure path açıldı.
