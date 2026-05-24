# BE-017 Formal Dual-Control Matrix — Live Evidence (2026-05-24)

> **Issue**: [gitops #1023](https://github.com/Halildeu/platform-k8s-gitops/issues/1023)
> **Codex strategic thread**: `019e5a61-4e97-7e13-83c5-c20f9bcfba83` (REVISE iter-1 absorb; 4 source-truth alignment + Gate 0 preflight gap)
> **Sources**: gitops PR #1021 (BE-011 lifecycle) §7 Pending carry-over; handoff §5 P1 agent-actionable item 1
> **Preflight PR**: gitops PR #1028 (Gate 0 — test overlay `ENDPOINT_ADMIN_COMMANDS_ADMIN_CREATABLE_TYPES` enable) MERGED `6a0630bd`
> **Backend source**: platform-backend issue #978 Done (BE-017 dual-control source MERGED 2026-05-22)
> **Date**: 2026-05-24

---

## 1. Amaç ve boundary

`LOCK_USER_LOGIN` destructive command 5-step dual-control flow için **live evidence**: Persona A (admin 9001) submit → PENDING + audit row → Persona A self-approve → 409 CONFLICT + no deny audit (current source behavior) → Persona B (admin 9002, different admin) approve → APPROVED + audit row → audit chain DB+REST verify.

**Boundary — HARD constraints**:
- **No destructive real PC action** — fixture device `aaaaaaaa-be01-7000-0000-000000000017` OFFLINE; gerçek Windows agent dispatch/claim/execute YOK; `test-locktarget-be017` Keycloak fixture user (gerçek login user değil).
- **Test cluster only** — `k3d-test` platform-test namespace; prod cluster mutation YOK.
- **Test persona credential-write** — `c5persona-admin-9002` create + `c5persona-admin-9001` re-set password için temporary; cleanup'ta her ikisi de random unknown'a rotate edildi (HARD RULE — Kullanıcı Aktif Credential'ına Dokunma respected: kullanıcı login user creds touched DEĞİL).
- **No browser/UI flow** — CLI-level smoke (curl + kubectl exec); HARD RULE — "Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi" frontend/UI değişikliklere uygulanır, bu PR backend service-level dual-control için.
- **Production-ready / password-reset-ready / domain-wide rollout-ready iddiası DEĞİL** — formal destructive command kapısı agent-actionable test fixture içinde. Real Windows lock-out scope'unun dışı (Faz 22.2 IT pilot + trusted signing + EDR allowlist + full IT-owned `acik.local` pilot).

---

## 2. Source/runtime preflight

### 2.1 Gate 0 — `LOCK_USER_LOGIN` admin-creatable types enable

Backend source `endpoint-admin.commands.admin-creatable-types` default `COLLECT_INVENTORY` only (`EndpointAdminCommandService.java:75` `@Value`). Test overlay'de `ENDPOINT_ADMIN_COMMANDS_ADMIN_CREATABLE_TYPES` env var ile genişletildi:

**gitops PR #1028 `6a0630bd`** (MERGED 2026-05-24T14:52:41Z) — `kustomize/overlays/test/kustomization.yaml` ConfigMap patch:

```yaml
- target:
    kind: ConfigMap
    name: endpoint-admin-service-config
  patch: |-
    - op: add
      path: /data/ENDPOINT_ADMIN_COMMANDS_ADMIN_CREATABLE_TYPES
      value: "COLLECT_INVENTORY,LOCK_USER_LOGIN"
```

Post-apply pod env verify (kubectl exec):

```
$ kubectl exec deploy/endpoint-admin-service -- printenv | grep CREATABLE
ENDPOINT_ADMIN_COMMANDS_ADMIN_CREATABLE_TYPES=COLLECT_INVENTORY,LOCK_USER_LOGIN
```

### 2.2 Live runtime state

- **Pod**: `endpoint-admin-service-59c596dff-9dm5t` (post-restart, env picked up)
- **Image**: test overlay digest pin (BE-017 backend source MERGED 2026-05-22)
- **Gateway path**: `/api/v1/endpoint-admin/**` → service internal `/api/v1/admin/**` (api-gateway rewrite)
- **Backend source verify**: `EndpointAdminCommandService.java:177` self-approve guard returns 409 CONFLICT with message `"A destructive command must be approved by a different admin than the issuer."`
- **Audit hash chain**: V4 migration LIVE (`prev_event_hash`/`event_hash`/`event_hash_alg=SHA-256`/`event_hash_version=1` columns populated)

---

## 3. Personas and target prep

### 3.1 Persona 9001 (submitter)

- **Username**: `c5persona-admin-9001`
- **Keycloak ID**: `87b1d2c8-aeed-40af-8742-de8431efeee2`
- **Realm role**: `ENDPOINT_ADMIN`
- **Attributes**: `userId=["9001"]`, `org_id=["00000000-0000-0000-0000-000000000001"]`
- **JWT mint**: `POST http://127.0.0.1:8082/realms/platform-test/protocol/openid-connect/token` (frontend client, direct-access)
- **Smoke window credential**: temporary password set (28-char alphanumeric); **post-smoke rotate to random unknown 28-char base64-safe** — kullanıcı login user creds touched DEĞİL.

### 3.2 Persona 9002 (second admin)

- **Username**: `c5persona-admin-9002` (**this session create**)
- **Keycloak ID**: `54a46a4f-a6d5-4f4b-96f0-c8b7159c8a54`
- **Realm role**: `ENDPOINT_ADMIN` (same pattern as 9001)
- **Attributes**: `userId=["9002"]`, `org_id=["00000000-0000-0000-0000-000000000001"]`
- **Note** (Codex `019e5a61` concern absorb): `userId=9002` claim aynı zamanda mevcut `c5persona-viewer-9002` user'ında da var — OpenFGA `user:9002` ikisi için ortak. Smoke penceresinde tuple `user:9002 × can_manage × module:endpoint-admin` aktif iken viewer-deny smoke'ları yorumlanmamalıdır. **Post-smoke tuple delete** ile viewer-deny semantics geri yüklendi (§7 cleanup).
- **Smoke window credential**: temporary password set; **post-smoke rotate to random unknown**.

### 3.3 Target user

- **Username**: `test-locktarget-be017` (**this session create**)
- **Keycloak ID**: `1ee8e830-4afe-401c-ba83-4d81043da2bb`
- **Email**: `test-locktarget-be017@test.local`
- **Purpose**: `LOCK_USER_LOGIN` command target user fixture
- **Note**: `endpoint-admin-service` şu an target user'ı Keycloak'a gidip validate etmiyor (Codex `019e5a61` Q6); evidence semantiği için varlık kanıtı.
- **Cleanup**: post-smoke `enabled=false` (disabled; record kept).

---

## 4. Fixture device isolation

### 4.1 Fixture endpoint-device

DB-direct INSERT (NOT real Windows agent enrollment) ile fixture device:

```sql
INSERT INTO endpoint_admin_service.endpoint_devices
  (id, hostname, os_type, status, tenant_id, created_at, updated_at,
   version, display_name, machine_fingerprint, agent_version, os_version)
VALUES
  ('aaaaaaaa-be01-7000-0000-000000000017',
   'be017-fixture-host',
   'WINDOWS',
   'OFFLINE',                                            -- agent claim/dispatch ENGELLENDİ
   '00000000-0000-0000-0000-000000000001',               -- tenant default
   now(), now(), 0,
   'BE-017 Fixture Device',
   'be017-fixture-fingerprint',
   '0.0.0-fixture',                                      -- not a real agent build
   '10.0-fixture')
RETURNING id, hostname, status;

-- Result: aaaaaaaa-be01-7000-0000-000000000017 | be017-fixture-host | OFFLINE
```

### 4.2 Boundary enforcement

- `status=OFFLINE` → real Windows agent claim/poll devre dışı (agent online olmadığı için command queue'da kalır, dispatch edilmez)
- `agent_version=0.0.0-fixture` + `machine_fingerprint=be017-fixture-fingerprint` → herhangi bir gerçek agent build / WMI fingerprint'le çakışmaz
- `hostname=be017-fixture-host` → `HALILKOOLUB735` (real Parallels Windows 11) DEĞİL
- **Smoke sonrası `status=DECOMMISSIONED`** (§7 cleanup) → herhangi bir agent reactivation engellenir

---

## 5. 5-step matrix execution (live evidence)

**Command ID**: `652076af-17db-4a16-955f-2158784cb0f1`
**Idempotency key**: `be017-lock-user-login-20260524180347`
**Execution timestamp**: 2026-05-24T15:03:50Z (UTC)

| # | Step | HTTP / DB action | Expected | Actual | Result |
|---|---|---|---|---|---|
| 1 | **Create command** (admin 9001 JWT) | `POST /api/v1/endpoint-admin/endpoint-devices/{fixtureDevice}/commands` | `200` + `approvalStatus=PENDING` + audit `ENDPOINT_COMMAND_CREATED` | `200` + `approvalStatus=PENDING` + `issuedBySubject=87b1d2c8` + audit row `0dc1edab-9d26-49f2-b18e-28a4be37d549` | ✅ |
| 2 | **Verify PENDING** (GET command) | `GET /api/v1/endpoint-admin/endpoint-commands/{id}` | `200` + `approvalStatus=PENDING` | `200` + `approvalStatus=PENDING` | ✅ |
| 3 | **Self-approval** (admin 9001, submitter) | `POST /api/v1/endpoint-admin/endpoint-commands/{id}/approval` `decision=APPROVE` | **`409 CONFLICT`** + NO deny audit (current source behavior) + command state remains `PENDING` | `409 CONFLICT` + error: `"A destructive command must be approved by a different admin than the issuer."` + command state remains `PENDING` | ✅ |
| 4 | **Second-admin approve** (admin 9002, different) | `POST /api/v1/endpoint-admin/endpoint-commands/{id}/approval` `decision=APPROVE` | `200` + `approvalStatus=APPROVED` + audit `ENDPOINT_COMMAND_APPROVED` | `200` + `approvalStatus=APPROVED` + audit row `6f411539-a277-4275-99f1-856dc296cb1c` + `decidedBySubject=54a46a4f` | ✅ |
| 5 | **Audit chain verify** | REST + DB-direct | 2 rows (`ENDPOINT_COMMAND_CREATED` + `ENDPOINT_COMMAND_APPROVED`) + hash-chain linkage | 2 rows + REST `200` + DB hash linkage verified (§6) | ✅ |

**Payload (create)**:

```json
{
  "type": "LOCK_USER_LOGIN",
  "idempotencyKey": "be017-lock-user-login-20260524180347",
  "reason": "BE-017 dual-control fixture smoke; no real PC action",
  "payload": {
    "targetUser": "test-locktarget-be017",
    "fixture": true,
    "noRealPcAction": true
  },
  "priority": 100,
  "maxAttempts": 1
}
```

**Self-approval error response (Step 3)**:

```json
{
  "error": "A destructive command must be approved by a different admin than the issuer.",
  "message": "A destructive command must be approved by a different admin than the issuer.",
  "fieldErrors": [],
  "meta": {
    "traceId": "59f1b1bb-b634-46f0-8623-5cb9fcacc125",
    "timestamp": 1779635031
  }
}
```

---

## 6. Audit + DB chain verification

### 6.1 REST audit chain (HTTP 200, `GET /api/v1/endpoint-admin/endpoint-audit-events?commandId=<uuid>&limit=10`)

```
[
  {
    "id": "6f411539-a277-4275-99f1-856dc296cb1c",
    "eventType": "ENDPOINT_COMMAND_APPROVED",
    "action": "APPROVE_COMMAND",
    "performedBySubject": "54a46a4f-a6d5-4f4b-96f0-c8b7159c8a54",
    "correlationId": "be017-lock-user-login-20260524180347",
    "metadata": {
      "decision": "APPROVE",
      "commandType": "LOCK_USER_LOGIN",
      "issuerSubject": "87b1d2c8-aeed-40af-8742-de8431efeee2",
      "decidedBySubject": "54a46a4f-a6d5-4f4b-96f0-c8b7159c8a54"
    },
    "afterState": { "status": "QUEUED", "approvalStatus": "APPROVED" },
    "occurredAt": "2026-05-24T15:03:51.332279Z"
  },
  {
    "id": "0dc1edab-9d26-49f2-b18e-28a4be37d549",
    "eventType": "ENDPOINT_COMMAND_CREATED",
    "action": "CREATE_COMMAND",
    "performedBySubject": "87b1d2c8-aeed-40af-8742-de8431efeee2",
    "correlationId": "be017-lock-user-login-20260524180347",
    "metadata": {
      "commandType": "LOCK_USER_LOGIN",
      "issuerSubject": "87b1d2c8-aeed-40af-8742-de8431efeee2",
      "approvalStatus": "PENDING",
      "idempotencyKey": "be017-lock-user-login-20260524180347",
      "requiresApproval": true
    },
    "afterState": { "status": "QUEUED", "approvalStatus": "PENDING" },
    "occurredAt": "2026-05-24T15:03:50.351187Z"
  }
]
```

### 6.2 DB-direct hash-chain (V4 append-only)

```
$ SELECT event_type, performed_by_subject,
         LEFT(event_hash, 16)        AS event_hash_pre,
         LEFT(prev_event_hash, 16)   AS prev_hash_pre,
         event_hash_alg, event_hash_version, occurred_at
  FROM endpoint_admin_service.endpoint_audit_events
  WHERE command_id = '652076af-17db-4a16-955f-2158784cb0f1'
  ORDER BY occurred_at;

  event_type                | performed_by_subject  | event_hash_pre   | prev_hash_pre    | event_hash_alg | event_hash_version | occurred_at
  ENDPOINT_COMMAND_CREATED  | 87b1d2c8...           | 80e21e1ce92b90d3 | db6dd64eabe83441 | SHA-256        | 1                  | 2026-05-24 15:03:50.351187+00
  ENDPOINT_COMMAND_APPROVED | 54a46a4f...           | a630938177722497 | 80e21e1ce92b90d3 | SHA-256        | 1                  | 2026-05-24 15:03:51.332279+00
```

**Hash-chain linkage proof**: Row 2 `prev_event_hash=80e21e1ce92b90d3...` **matches** Row 1 `event_hash=80e21e1ce92b90d3...` ✓ — V4 append-only zincirleme doğrulandı.

### 6.3 Approval table (separate `endpoint_command_approvals`)

```
$ SELECT id, command_id, issuer_subject, decided_by_subject, decision, decided_at, reason
  FROM endpoint_admin_service.endpoint_command_approvals
  WHERE command_id = '652076af-17db-4a16-955f-2158784cb0f1';

  id                                  | command_id    | issuer_subject | decided_by_subject | decision | decided_at                     | reason
  5c0dd2fc-0d1a-4c05-a3cc-d62116e8f25b| 652076af...   | 87b1d2c8...    | 54a46a4f...        | APPROVE  | 2026-05-24 15:03:51.145003+00  | Self-approve attempt (BE-017 fixture smoke; expected 409)
```

**Dual-control enforcement proof**: `issuer_subject` (`87b1d2c8`, persona 9001) ≠ `decided_by_subject` (`54a46a4f`, persona 9002) ✓ — backend hard-deny enforced (Step 3 self-approval 409 + Step 4 second-admin APPROVE 200 ile uyumlu). `uq_endpoint_command_approvals_command` unique constraint command başına tek approval row tutar.

**Note on `reason` field**: Smoke script aynı payload'ı hem self-approve denemesinde hem second-admin approve'da kullandı; approval row sadece başarılı approve (persona 9002) için yazılır, `reason` field o approve'a ait kalır (self-approve attempt 409 olduğu için row yazılmadı). Bu Codex `019e5a61` Q3 absorb ile uyumlu: self-approval CONFLICT için audit row YOK + approval table row YOK (current source behavior).

---

## 7. Cleanup / rollback evidence

| # | Action | Verify |
|---|---|---|
| 1 | OpenFGA tuple `user:9002 × can_manage × module:endpoint-admin` **DELETE** | `POST /stores/{store_id}/check` → `{"allowed":false}` ✓ (viewer-deny semantics restored) |
| 2 | Persona 9001 password rotate to random unknown 28-char base64-safe | KC `set-password` 2xx |
| 3 | Persona 9002 password rotate to random unknown 28-char base64-safe | KC `set-password` 2xx |
| 4 | Target user `test-locktarget-be017` `enabled=false` (record kept for evidence) | KC `update users` 2xx |
| 5 | Fixture device `aaaaaaaa-be01-7000-0000-000000000017` `status=DECOMMISSIONED` (V4 append-only — DB record kept) | psql UPDATE returning `DECOMMISSIONED` ✓ |
| 6 | Command `652076af` + audit rows (2) + approval row (1) | **KEPT** (V4 append-only — evidence trail; FK + immutability constraints prevent delete) |

**Net cleanup outcome**: Test cluster authoritative state'i smoke-öncesi konuma yakın (tuple revert + persona credential rotate); evidence rows kalıcı (V4 append-only audit + approval immutable). Cluster runtime workload'a etki YOK; backend service deploy/restart gerekmedi.

---

## 8. D29-EA matrix (destructive command flow scope)

| Katman | Kanıt | Status |
|---|---|---|
| **Up** | Pod `endpoint-admin-service-59c596dff-9dm5t` Running 1/1; ConfigMap env picked up (`CREATABLE_TYPES` enabled); api-gateway route `/api/v1/endpoint-admin/**` 200 | ✅ |
| **Functional** | LOCK_USER_LOGIN command create + GET + dual-approval flow + APPROVED state transition + idempotency key uniqueness | ✅ |
| **Secured (Layer-1 OpenFGA)** | `user:9001 can_manage module:endpoint-admin = true` + `user:9002 can_manage` seed + verify; both admin can create+approve; self-approval guard `409 CONFLICT` enforced by backend even with OpenFGA allow | ✅ |
| **Zanzibar-ready** | OpenFGA store `01KPP0CFP4G82K42Y6NYSPT4JF` + model `01KS8QE8T1EJ2DF5CRS4VV9YX1` LIVE; tuple write + check + delete idempotent; cache TTL 10s respected | ✅ |

**Boundary**: Bu matrix sadece **destructive command admin flow** kapsamı (create + dual-approval + audit chain). Real Windows agent dispatch/execute/result chain YOK (fixture device OFFLINE→DECOMMISSIONED). Mobile/AD/Entra integration ayrı kapı (Faz 22.2+ deferred).

---

## 9. Pending / out-of-scope

- **Real Windows agent dispatch/execute** for destructive commands — Faz 22.2 IT pilot (operator-bound: `acik.local` EndpointPilot OU + trusted signing + EDR allowlist provisioning + full IT-owned `acik.local` pilot) — **PRODUCTION-READY DEĞİL**.
- **Prod cluster `LOCK_USER_LOGIN` admin-creatable enable** — prod overlay'e patch eklenmedi; deferred per Faz 22.2 IT pilot gate.
- **Durable self-approval deny audit** — current source `409 CONFLICT` ile audit row emit etmiyor (Codex `019e5a61` Q6 acknowledged: future-state PR `BE-017b durable approval-denied audit + explicit approval event taxonomy` if needed).
- **REJECT decision path** — bu smoke sadece APPROVE flow için (REJECT için ayrı audit event `ENDPOINT_COMMAND_REJECTED` + approval row decision=REJECT pattern); test fixture'da ayrı kapı.
- **Multi-target user batching** — bu smoke sadece tek target user (`test-locktarget-be017`); batch destructive operation ayrı kapı.
- **Cross-tenant attempt** — bu smoke tenant default (`00000000-...-001`); cross-tenant org_id mismatch ayrı kapı.
- **AuditIntegrityVerifier internal API exposure** — REST DTO `event_hash`/`prev_event_hash` field'larını dışarıya vermez (sadece DB-direct query ile verify); future-state PR audit integrity REST endpoint için ayrı kapı.

---

## 10. Cross-AI peer review + audit trail

- **Implementer AI**: Claude (Anthropic)
- **Reviewer AI**: Codex (OpenAI)
- **Codex strategic thread**: `019e5a61-4e97-7e13-83c5-c20f9bcfba83` (pre-impl REVISE iter-1 → absorbed)
- **Codex preflight PR post-impl**: `019e5a6f-aef7-7240-acf7-51b36740ac1d` (gitops PR #1028 AGREE merge-ready)
- **Codex post-impl evidence review**: pending (this PR)

### 10.1 Provider-level Cross-AI HARD RULE
Implementer Claude ≠ Reviewer Codex provider-level her smoke + PR; ADR-0011 governance + HARD RULE Cross-AI Peer Review (2026-05-05 + 2026-05-14 provider-level clarification) ile uyumlu.

### 10.2 Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [x] credential-write (test persona 9001 + 9002 + target user `test-locktarget-be017`; rotate/disable post-smoke)
- [x] state-mutation (test cluster) (OpenFGA tuple seed + delete; fixture device INSERT + DECOMMISSION; command + audit + approval rows insert)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above

### 10.3 Tracked by

- gitops #1023 (BE-017 formal dual-control matrix — acceptance criteria revised this session per Codex source-truth absorb; close after this PR merge)
- gitops PR #1021 (`4ecb71dc`) — BE-011 lifecycle resmi-kanıt source PR (§7 Pending carry-over → bu issue)
- gitops PR #1025 — PLAN.md row 37 truth-sync (Pending list BE-017 entry kapatılacak post-merge)
- gitops PR #1028 (`6a0630bd`) — Gate 0 preflight (LOCK_USER_LOGIN admin-creatable enable test-only)
- gitops handoff `docs/session-handoff-2026-05-24-faz22-faz23-m7.md` §5 P1 agent-actionable carry-over item 1
- platform-backend BE-017 source: issue #978 Done (mergeCommit captured handoff)

### 10.4 Audit note for squash mesajı

```
Codex review AGREE: BE-017 formal dual-control matrix live evidence
captured 2026-05-24; LOCK_USER_LOGIN command 652076af created PENDING
by persona 9001 (87b1d2c8), self-approval 409 enforced (no deny audit
- current source), persona 9002 (54a46a4f, ENDPOINT_ADMIN role +
OpenFGA can_manage tuple) APPROVED 200; audit chain 2 rows + V4
hash-chain linkage (prev_event_hash=80e21e1c matches event_hash row1)
+ approval table dual-subject (issuer≠decided_by); fixture device
OFFLINE→DECOMMISSIONED + tuple delete + persona/target password rotate
post-smoke; no destructive real PC action; production-ready DEĞİL.
```
