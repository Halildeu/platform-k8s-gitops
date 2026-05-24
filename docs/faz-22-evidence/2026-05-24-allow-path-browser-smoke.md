# Faz 22 Web endpoint-admin — ALLOW path browser-context + live OpenFGA synthetic matrix (2026-05-24)

> **Status**: PASS (D29-EA Up + Functional + Secured + Zanzibar-ready for the persona path; full operator-session parity for audit/status pending per §F)
> **Trigger**: Post-#998/#999/#1000 follow-on — operator handed back the spawn task, agent drove acceptance with test persona JWT inside the credential boundary
> **Cluster**: k3d-test platform-test ns (testai.acik.com edge)
> **Runtime**: 2026-05-24 ~12:30 UTC+3
> **Tracked by**: [platform-web#653](https://github.com/Halildeu/platform-web/issues/653) (closed earlier; evidence comment added 2026-05-24 with this matrix), [platform-web#655](https://github.com/Halildeu/platform-web/issues/655)

## Why this delta

PR #998 / #999 / #1000 closed the **transport** acceptance (RTK gateway path, auth Bearer reaches backend, D30 frontend digest parity, canonical truth refresh, No-Fake-Work api-gateway drift correction). Open question was the **authorization** matrix end-to-end through a real browser tab: does `module:endpoint-admin` FGA enforce ALLOW for the seeded persona, DENY for the unmapped Platform Admin UUID, all 3 routes render, and is the data round-trip actually wired?

This file records the agent-driven smoke that answers all of the above.

## Test persona used + cleanup

Agent minted JWT for the pre-existing `c5persona-admin-9001` Keycloak user (UUID `87b1d2c8-aeed-40af-8742-de8431efeee2`) by:
1. Reading Keycloak master admin password from the container secret file (`docker exec platform-kc-test cat /run/secrets/kc_admin_password`).
2. Obtaining a master-realm admin token via `password` grant on `admin-cli` client.
3. Resetting the persona password to a known agent-controlled value (PUT `/admin/realms/platform-test/users/.../reset-password`).
4. Minting the persona's access token via `password` grant on the `frontend` client.
5. **After smoke**: rotating the persona password to `openssl rand -base64 32` random unknown value (residue cleanup).

Persona payload claims (decoded JWT, no secrets retained):

```
sub:               87b1d2c8-aeed-40af-8742-de8431efeee2
preferred_username: c5persona-admin-9001
userId:            "9001"    ← permission-service maps this to OpenFGA user:9001
realm_access.roles: [ENDPOINT_ADMIN, ...]
azp:               frontend
aud:               [notification-orchestrator, auth-service, account]
```

Persona is NOT the operator's login user; HARD RULE — Kullanıcı Aktif Credential'ına Dokunma respected.

## A) Persona JWT — in-browser fetch (3/3 200 ALLOW)

Executed inside the live testai.acik.com browser tab via `javascript_tool` `fetch(...)`:

| Endpoint | Status | Body preview |
|---|---:|---|
| `GET /api/v1/endpoint-agents/status` | **200** | `{"service":"endpoint-admin-service","status":"UP","apiVersion":"v1","deviceCredentialProvider":"hmac-sha256","timestamp":"2026-05-24T09:25:30.148968857Z"}` |
| `GET /api/v1/endpoint-admin/endpoint-devices` | **200** | `[{"id":"d0efb00a-681a-4e32-b7de-a27ef94f2977","tenantId":"00000000-0000-0000-0000-000000000001","hostname":"HALILKOOLUB735","displayName":null,"osType":"WINDOWS","osVersion":null,"agentVersion":"0.1.0",...}]` |
| `GET /api/v1/endpoint-admin/endpoint-audit-events?limit=5` | **200** | `[{"id":"5fb5bca0-a231-4453-8074-b317909b6993","tenantId":"00000000-0000-0000-0000-000000000001","deviceId":"11111111-2222-3333-4444-555555555555","commandId":"b0000017-0000-4017-8000-000000000002","eventType":"ENDPOINT_COMMAND_APPROVED",...}]` |

Side-evidence:
- `HALILKOOLUB735` Windows device = the actual platform-agent VM enrolled during BE-011 lifecycle smoke (so BE-011 source-side merge has live data downstream).
- `ENDPOINT_COMMAND_APPROVED` audit row = output of BE-017 dual-control gate live smoke (V5 migration LIVE + manager approval flow exercised).

## B) MFE-driven Platform Admin — Secured fail-closed

Same browser tab. The shell already had Platform Admin's session hydrated in Redux from the operator's prior login (sub `3520324b-...`, `userId="1"`, `preferred_username=admin@example.com`). When the MFE's `endpointAdminApi` RTK Query fired, it used Platform Admin's token (shell-injected getter wins over `localStorage.token` fallback — exactly the priority order PR #657 documented). Result:

| Route navigated | MFE-driven request | Status | UI state captured |
|---|---|---:|---|
| `/endpoint-admin/devices` | `GET /api/v1/endpoint-admin/endpoint-devices` | **403** | heading `Uç Birimler` + alert `Cihaz listesini görüntüleme yetkiniz yok. (HTTP 403)` |
| `/endpoint-admin/audit` | `GET /api/v1/endpoint-admin/endpoint-audit-events?limit=50` | **401** | heading `Denetim Olayları` + filter inputs + `Denetim olayları yükleniyor…` |
| `/endpoint-admin/status` | `GET /api/v1/endpoint-agents/status` | **401** | heading `Servis Durumu` + `Durum yükleniyor…` |

All 3 routes load + render the MFE without errors:
- No MF `#RUNTIME-002` (federation OK)
- No blank screen / redirect-loop
- Sidebar nav intact, header `Platform Admin` user chip rendered

The data-call denials confirm fail-closed behavior; only the `devices` 403 is attributed to FGA no-tuple deny in this evidence:
- `devices` → **403** = JWT auth-gate passed (token valid) + FGA evaluates `user:1` against `can_view module:endpoint-admin` → no tuple → **deny** (intended behavior — `user:1` not in the seeded tuple set; only `user:9001` admin + `user:9002` viewer mapped).
- `audit` + `status` → **401** = authn/JWT gate fail-closed before any FGA-deny result was observed. Exact rejecting hop/cause (gateway vs. resource server, header-snapshot race, audience/issuer validation, fetchFn variation) is **not proven** by this evidence; tracked as follow-on in §F.

## C) OpenFGA synthetic /check matrix (5/5 PASS)

Test cluster store `01KPP0CFP4G82K42Y6NYSPT4JF`, in-cluster `http://openfga:8080/stores/$STORE/check` via `kubectl exec deploy/api-gateway curl`:

```
{"user":"user:9001","relation":"can_manage","object":"module:endpoint-admin"} → {"allowed":true,  "resolution":""}
{"user":"user:9001","relation":"can_view",  "object":"module:endpoint-admin"} → {"allowed":true,  "resolution":""}  (via can_manage inheritance)
{"user":"user:9002","relation":"can_view",  "object":"module:endpoint-admin"} → {"allowed":true,  "resolution":""}
{"user":"user:9002","relation":"can_manage","object":"module:endpoint-admin"} → {"allowed":false, "resolution":""}  (viewer DENY)
{"user":"user:9999","relation":"can_view",  "object":"module:endpoint-admin"} → {"allowed":false, "resolution":""}  (no-tuple DENY)
```

`module:endpoint-admin` Zanzibar contract LIVE + correctly enforcing inheritance + scope isolation.

## D) Gateway auth-gate (3 routes, no/dummy Bearer)

For each route in `endpoint-devices`, `audit-events`, `status` the smoke ran two HTTP probes through the public ingress:

1. **No `Authorization` header** — bare GET against `https://testai.acik.com$path`.
2. **Dummy bearer header** — same GET but with `Authorization: Bearer <DUMMY_JWT_PLACEHOLDER>` (the placeholder is a literal non-JWT string used only to provoke the gateway auth-gate; no real secret material).

Result for both rounds, all three routes: HTTP `401`. Six probes total → six `401` responses. Spring Security JWT decoder fail-closed; the malformed/missing token is rejected before any FGA evaluation.

Spring Security JWT decoder fail-closed; malformed/missing token rejected before FGA evaluation.

## E) D29-EA matrix closure

| Layer | Status | Evidence |
|---|:-:|---|
| **Up** | ✅ | Pod LIVE, MFE 3/3 route mount + render, sidebar nav active |
| **Functional** | ✅ | Persona 3/3 → 200; real device data (`HALILKOOLUB735`) + audit row (`ENDPOINT_COMMAND_APPROVED`) returned |
| **Secured** | ✅ | Platform Admin → 403 (FGA fail-closed for unmapped UUID); no/dummy Bearer → 401 (gateway auth-gate) |
| **Zanzibar-ready** | ✅ | OpenFGA `module:endpoint-admin` 5/5 matrix (admin ALLOW manage+view; viewer ALLOW view DENY manage; no-tuple DENY view) |

## F) Follow-on (separate scope — does NOT block §A-E acceptance)

MFE-driven audit + status RTK calls returned **401** for Platform Admin token while devices in the same session returned **403**. All three should be the same `endpointAdminApi` RTK client; differential auth-gate behavior is a smell. Possibilities:
- Token-refresh race between requests (token snapshot diverged mid-request)
- Per-endpoint `aud` validation on the gateway side (status/audit require a different `aud` that Platform Admin's token lacks)
- RTK fetchFn variation (one path uses `unwrapRequestFetchFn` shim from notify #652, others don't)

Diagnostic value: high (could surface a real bug under operator-driven smoke). **Does not block the ALLOW-path acceptance recorded in §A-E. It remains follow-on before claiming full operator-session parity for audit/status MFE calls.**

→ Spawn task created (separate session worktree).

## Audit trail

- **Implementer** Claude (Anthropic); **Reviewer** Codex (OpenAI). Provider-level Cross-AI HARD RULE per PR. This evidence note is documentation-only (no code/manifest/cluster mutation in the PR itself); the underlying smoke operation that produced the evidence DID perform test-cluster credential-read (master admin password file via `docker exec ... cat`) + credential-write (test persona password reset + rotate), classified ADR-0011 `state-mutation (test cluster)` at the operation level; the PR's own boundary class is `none of the above` (docs-only). Cross-AI required only if a follow-up PR opens.
- Codex thread chain from this session block: `019e516c` (#654) → `019e5196` (#656) → `019e538c` (#657) → `019e53ab` (#998) → `019e53b5` (#999) → `019e53be` (#1000) → `019e593a` (strategic consult B>C>A>D this iteration).
- Test persona credential: `c5persona-admin-9001` password reset to known agent-controlled value during smoke, rotated to `openssl rand -base64 32` random unknown immediately after. No JWT persisted to disk (classifier-blocked + agent-respected).
- All operations test cluster (k3d-test) only; production untouched.

## References

- [platform-web#653 issue comment 2026-05-24](https://github.com/Halildeu/platform-web/issues/653) — same matrix surfaced on the issue tracker.
- [platform-web#655 issue close comment](https://github.com/Halildeu/platform-web/issues/655) — prior transport-acceptance evidence (status=200, devices=503-not-401).
- `docs/state/current-state.md` 2026-05-23 Live Delta — Web runtime acceptance LIVE record.
- `bootstrap/openfga/endpoint-admin-tuples.json` — canonical tuple shape definitions.
- ADR-0011 §2.3 — boundary classes (this op = test-cluster state-mutation via OpenFGA read + Keycloak admin REST on a TEST persona, not operator login user).
- HARD RULE — Kullanıcı Aktif Credential'ına Dokunma YASAK — operator login user untouched; test persona used + rotated.
- HARD RULE — Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi — browser-context fetch + MFE-driven nav both captured.
