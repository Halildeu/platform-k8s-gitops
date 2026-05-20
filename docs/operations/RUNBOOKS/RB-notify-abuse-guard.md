# RB-notify-abuse-guard — NotifyAbuseStorm Triage

> **Alert**: `NotifyAbuseStorm` (severity: warning, P2)
> **Sub-faz**: Faz 23.2.F T1.6 (abuse prevention guards)
> **Source**: `AbuseGuardService` returns HTTP 429 on rate-limit or
> webhook fan-out cap; counter `notify_abuse_blocked_total{reason=...}`.
> **Codex audit**: previous thread `019e0c28` P2 deferred → current
> thread `019e42c1` iter-1 REVISE absorbed.

This runbook covers the 5-step triage when the alert fires.

## When to use

Alert expression: `sum by (namespace) (rate(notify_abuse_blocked_total[5m])) > 0.5` for 5 minutes.
Roughly **150+ abuse-block (HTTP 429) responses across the service in 5 minutes**. The guard is doing its job; this is a P2 signal that something upstream is misbehaving — either real abuse or a caller regression that needs investigation.

`NotifyAbuseStorm` is **not** the same class as `NotifyOrgAccessDeniedStorm` (which is a security-boundary fail-close indicating an active attack or auth-chain regression). AbuseGuard is the working-as-designed return path: HTTP 429 is the contract, not an outage.

## 1. Inspect reason distribution

Fan-out cap hits are higher priority than rate-limit hits because the cap is a hard safety limit (severity=critical cannot bypass it). Inspect:

```promql
sum by (namespace, reason) (rate(notify_abuse_blocked_total[5m]))
```

Two label namespaces are emitted by `AbuseGuardService` — keep them straight:

- **Prometheus counter labels** (low cardinality, alert-shaped):
  - `rate_limit` — sliding-window rate hit per (orgId, topicKey)
  - `webhook_fanout_cap` — single-intent fan-out exceeds the cap (default 10)
- **Audit / log decision reasons** (full string, evidence-shaped):
  - `rate_limit_exceeded`
  - `webhook_fanout_cap_exceeded`

The PromQL above queries Prometheus labels. Audit-row queries (step 3) use the log/audit decision reason.

If `webhook_fanout_cap` dominates in the Prometheus distribution: jump to step 4 first (critical bypass sanity). Otherwise continue with step 2.

## 2. Identify the noisy caller(s)

The Prometheus counter intentionally keeps low cardinality — it only carries the `reason` label, NOT `org_id` or `topic_key`. Per-caller breakdown must come from logs / audit, not PromQL. The orchestrator log lines and audit rows do include `orgId/topic/reason` context.

Recent pod logs (last 10 min) show the actual (org, topic) pairs being rejected:

```bash
kubectl --context k3d-prod -n platform-prod logs deploy/notification-orchestrator \
  --since=10m \
  | grep -E "AbuseGuard blocked|AbuseGuardBlockedException" \
  | tail -40
```

Look for the most repeated `(orgId, topic)` combination — that is the noisy caller. Cross-reference with recent deploys:

```bash
# Recent platform-backend deploys (notification-orchestrator)
gh run list --repo Halildeu/platform-backend --workflow ci-mvn-build-push.yml --limit 5

# Caller-side: depends on which service owns the noisy (org, topic) — check the
# `source` field in the intent payload via orchestrator log context.
```

> **Future follow-up**: org/topic-level breakdown is intentionally absent from Prometheus to avoid label-cardinality explosion. A dedicated metric with bounded label set (e.g. top-N orgs only) could be added in a future PR if the log-based investigation pattern proves insufficient at operational scale.

## 3. Org/topic log inspection

Pod logs show the blocked exception with org + topic context:

```bash
kubectl --context k3d-prod -n platform-prod logs deploy/notification-orchestrator \
  --since=10m \
  | grep -E "AbuseGuard|429" \
  | tail -50
```

Audit row (KVKK + ops trail) is written via `AuditEventPublisher.publishStandaloneRequiresNew` — independent transaction, survives outer rollback. The audit event surface uses an event-type-keyed schema with the contextual fields packed into a `details` JSONB column, NOT a flat `decision_reason` column. To verify the audit row was written for a specific block event, run the following from an operator shell or a known Postgres client with notify DB credentials — **do not assume the application container contains `psql`** (the orchestrator image carries only the JRE + app jar):

```sql
SELECT
  occurred_at,
  event_type,
  org_id,
  details->>'topic_key'     AS request_topic_key,
  details->>'reason'        AS decision_reason,
  details->>'count'         AS count,
  details->>'limit'         AS rate_limit,
  details->>'webhook_count' AS webhook_count,
  details->>'cap'           AS fanout_cap
FROM notify.audit_event
WHERE event_type IN ('RATE_LIMITED', 'WEBHOOK_FANOUT_CAPPED')
ORDER BY occurred_at DESC
LIMIT 20;
```

`event_type` is the canonical audit signal; `details->>'reason'` carries the full decision reason (`rate_limit_exceeded` or `webhook_fanout_cap_exceeded`) — the audit/log namespace, not the Prometheus label namespace.

To cross-check the Prometheus metric scrape itself (no audit data, just the counter state):

```bash
kubectl --context k3d-prod -n platform-prod exec deploy/notification-orchestrator -- \
  wget -qO- localhost:8081/actuator/prometheus | grep "^notify_abuse_blocked_total"
```

This returns counter series keyed by `reason=rate_limit|webhook_fanout_cap` (Prometheus label namespace) — matches the alert expression's data source.

## 4. Critical bypass sanity check

`severity=critical` bypasses rate-limit but **NOT** the webhook fan-out cap (HARD safety limit per Codex previous-thread `019e0c28` iter-2 P1 absorb).

Verify the bypass counter is incrementing only for legitimate severity=critical traffic:

```promql
sum by (namespace, reason) (rate(notify_abuse_bypassed_total[5m]))
```

If `bypassed{reason="critical_severity"}` is incrementing along with `blocked{reason="webhook_fanout_cap"}` for the same (org, topic) — cross-correlate via the logs in step 2/3, not via Prometheus since the counter only carries `reason`: a critical-severity event is hitting fan-out cap. The intent is rejected before insert / dispatch and the caller receives HTTP 429 (NOT a silent drop — the rejection is observable both to the caller and to audit). Escalate operationally: the cap may need to be lifted for this org, or the recipient list reduced upstream.

## 5. Rollback direction

The fix depends on where the regression is:

- **Caller side**: the upstream service onboarded too aggressively (e.g. a batch job emitting 1000 intents in 60s instead of paginating). Rollback or throttle the caller, NOT the guard.
- **Guard config side**: a recent ConfigMap change reduced `NOTIFY_ABUSE_RATE_LIMIT_MAX_PER_WINDOW` below the legitimate steady-state caller rate. Verify recent ConfigMap diff:

  ```bash
  kubectl --context k3d-prod -n platform-prod get cm notification-orchestrator-config -o yaml \
    | grep -E "ABUSE|RATE_LIMIT|FANOUT"
  ```

- **Real abuse**: caller is malicious or compromised. AbuseGuard is doing its job; coordinate with security team on whether to block at gateway layer too.

**Do NOT** raise the rate-limit globally as a knee-jerk response. The guard's role is to surface this signal; the fix is upstream or in a per-tenant override (future Faz 23.5/23.6 work — multi-tenant rate-limit config).

## Effective limit math

The AbuseGuard is in-process per pod (ConcurrentHashMap + AtomicLong, no shared backend). Service-wide effective limit:

```
effective_limit = pod_count × per_pod_limit
```

Default: 100/window per (org,topic) per pod. With HPA `min=1 max=3` on notification-orchestrator, the effective limit is 100–300 per 60s window service-wide. Multi-pod soft enforcement is explicit in the design (Codex previous-thread iter-2 P1 absorb). A future PR may move state to PostgreSQL or Redis for hard cross-pod enforcement; out of scope for MVP.

## Related

- Alert: `NotifyAbuseStorm` in `kustomize/base/apps/notification-orchestrator/prometheusrule.yaml`
- Service: `notification-orchestrator/src/main/java/com/serban/notify/abuse/AbuseGuardService.java`
- Audit doc: `docs/notify/m3-stale-audit-2026-05-09.md` (T1.6.5 PrometheusRule alert ticked here)
- Strict-cutover runbook (different mechanism): `RB-notify-strict-subscriberid-cutover.md`
