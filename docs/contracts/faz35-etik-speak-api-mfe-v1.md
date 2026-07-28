# Faz 35 Etik Speak public/staff API, event ve MFE compatibility contract v1

> **Owner:** ES-007 / [#2653](https://github.com/Halildeu/platform-k8s-gitops/issues/2653)
>
> **Status:** Implemented on draft source heads; exact-head review, merge ve runtime compatibility evidence bekleniyor
>
> **Version:** `1.0.0`
> **Compatibility:** server N supports public/staff clients N and N-1

## 1. Invariants

- Public base path: `/api/v1/public/ethics`.
- Staff base path: `/api/v1/ethics`.
- Public credential and suite credential are different types and never
  interchangeable.
- `orgId` is resolved server-side from channel/tenant configuration for public
  intake; client cannot select an arbitrary org.
- `productId` is server-owned constant `etik-speak`.
- Success for intake means Report, Case, ReporterAccessGrant hash and outbox
  rows committed in one product-local DB transaction.
- The browser generates the reporter access secret with a cryptographically
  secure RNG before intake. The same secret and idempotency key are reused only
  for an identical retry. The server stores only its slow-KDF hash and never
  returns the raw secret in a response, later read, event or log.
- JSON ignores additive unknown response fields. Required field removal/type
  change needs `/v2` or a new media-type major.
- `Idempotency-Key` is required for intake and message creation; same key and
  same canonical request returns the original result, same key with different
  payload returns `409 IDEMPOTENCY_CONFLICT`. Conditional case updates use
  `If-Match` against the case version and return `412 CASE_VERSION_MISMATCH` on
  stale writes.

## 2. Common protocol

The first test slice uses UTF-8 JSON and an explicit content type:

```http
Content-Type: application/json
Accept: application/json
```

Sensitive API responses use `Cache-Control: no-store`. The service creates an
opaque `X-Request-Id` for every public/staff API response and repeats it inside
the error envelope without accepting caller text as trusted telemetry.
Conditional case detail/update responses carry a quoted version `ETag`; the
next write supplies the same value as `If-Match`. Timestamps are RFC 3339 UTC.
IDs are opaque UUID strings and contain no tenant, date, identity or sequence
information.

Error envelope:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Gönderilen bilgiler doğrulanamadı.",
    "requestId": "opaque",
    "fields": [{"name": "description", "code": "REQUIRED"}]
  }
}
```

Public errors do not reveal whether a case, receipt, address, employee or org
exists. `404`, secret mismatch and locked mailbox share a bounded generic
response/timing class.

## 3. Public API

Public routes reject suite `Authorization` and suite cookies as credentials.
If present they are ignored for identity and removed before app handling; an
ambiguous credential combination returns `400 CREDENTIAL_CONFUSION`.

### 3.1 Create report

`POST /api/v1/public/ethics/reports`

Headers: `Idempotency-Key` required. The service derives the public channel
only from the trusted ingress host/server name and accepts only
`etik.acik.com` or `speakup.acik.com`; no caller-controlled business header is
tenant or channel input.

```json
{
  "mode": "ANONYMOUS",
  "category": "WORKPLACE_CONDUCT",
  "subject": "Kısa konu",
  "description": "Bildirim metni",
  "locale": "tr",
  "accessSecret": "browser-generated-32-byte-base64url-value",
  "noticeVersion": "tr-test-pilot-v1"
}
```

`mode` is `ANONYMOUS`, `CONFIDENTIAL` or `NAMED`. Reporter fields are rejected
for `ANONYMOUS`; contact/identity data is written to an identity compartment,
not narrative, for the other modes.

The first deployable test slice enables `ANONYMOUS` only. The public UI visibly
disables `CONFIDENTIAL`, `NAMED` and attachment collection until the separate
identity compartment and quarantine/scanner path are activated. Unsupported
data is not silently collected or stored in narrative. This is a truthful
slice boundary, not evidence that those CORE capabilities are complete.

`201 Created`:

```json
{
  "receiptId": "01...",
  "createdAt": "2026-07-18T12:00:00Z",
  "mailboxPath": "/mailbox",
  "idempotentReplay": false
}
```

No `caseId`, internal status, assignee or org identifier is exposed.

### 3.2 Open mailbox session

`POST /api/v1/public/ethics/mailbox/sessions`

```json
{"receiptId":"01...","accessSecret":"user-entered"}
```

The access secret is accepted only in the request body over TLS. It is never a
query/path parameter. Successful verification returns a short-lived,
case-scoped, host-only HttpOnly Secure `SameSite=Strict` mailbox cookie or a
single-use response capability. Cookie responses must not include a `Domain`
attribute. Rate limit and lockout metadata is not case-enumerable.

### 3.3 Mailbox messages

- `GET /api/v1/public/ethics/mailbox/messages`
- `POST /api/v1/public/ethics/mailbox/messages`
- `DELETE /api/v1/public/ethics/mailbox/session`

`GET` returns a case-scoped envelope:

```json
{
  "status": "IN_REVIEW",
  "messages": [
    {
      "id": "01...",
      "authorType": "STAFF",
      "visibility": "REPORTER_VISIBLE",
      "body": "Sentetik yanıt",
      "createdAt": "2026-07-18T12:30:00Z"
    }
  ]
}
```

`status` is restricted to the reporter-safe `NEW`, `IN_REVIEW` and
`CLOSED` vocabulary. Reporter sees only staff messages marked public and its
own messages. Case/org identifiers, internal notes, assignee, staff identity
beyond the configured display label, reporter identity/link and evidence
custody details are absent.

## 4. Staff API

Staff routes require suite host-only session/bearer, `ETHIC` product entitlement,
server-resolved org and OpenFGA decision. Reporter receipt/access secret is
rejected. Authz outage fails closed for read and mutation.

- `GET /api/v1/ethics/cases?status=&cursor=&limit=`
- `GET /api/v1/ethics/cases/{caseId}`
- `PATCH /api/v1/ethics/cases/{caseId}` with quoted case-version `If-Match`
- `POST /api/v1/ethics/cases/{caseId}/assignments`
- `POST /api/v1/ethics/cases/{caseId}/messages`
- `POST /api/v1/ethics/cases/{caseId}/internal-notes`

Minimal roles/relations:

| Action | Required relation | Explicit deny |
|---|---|---|
| list/read case | product `case_viewer` + DB org scope | technical admin |
| assign | product `case_triager` + DB org scope | cross-org |
| reply reporter | product `case_handler` + DB org scope | closed/held policy deny |
| internal note | product `case_handler` + DB org scope | reporter/public credential |
| sealed original | product `evidence_reveal_approved` | normal handler/triager |
| product config | `ethics_product_admin` | does not imply case content read |

The first synthetic test slice evaluates the staff subject against the
org-owned `ethics_product:<orgId>` object, filters every query by the
server-resolved `org_id`, and checks direct `conflicted` plus `recused` deny
relations on `ethics_case:<caseId>`. Product allow, DB org scope and absence of
both object-level deny relations are jointly required. Any policy-engine
failure is indistinguishable from deny; list/detail/mutation do not reveal case
existence after a deny.

## 5. Domain and transaction contract

Required compartments/entities:

- `reports`: immutable submission envelope and narrative reference;
- `cases`: mutable workflow state, org/product boundary and version;
- `reporter_access_grants`: receipt lookup, slow-KDF secret hash, lockout state;
- `reporter_identities` and `case_identity_links`: separately encrypted and
  separately authorized;
- `messages`: `REPORTER`, `STAFF_PUBLIC`, `INTERNAL_NOTE` visibility;
- `evidence_artifacts`: quarantine/sealed/sanitized digests and derivation;
- `audit_outbox`: product-local durable audit intents.

Anonymous intake atomically writes exactly the report, case,
reporter-access-grant hash, audit-outbox event and idempotency marker. It writes
no reporter-identity or case-identity-link row. Confidential/named modes add
their separately authorized identity/link rows only when that compartment is
enabled. Notification outbox creation and downstream audit publication are
later integration gates; provider delivery, Keycloak, suite entitlement, WORM
sink and external scanner are not synchronous success dependencies. Attachment state may be
`QUARANTINED` until scan/sanitize finishes; it is never silently `CLEAN`.

## 6. Event contract

Envelope media type: `application/vnd.acik.etik-speak.event.v1+json`.

```json
{
  "eventId": "opaque",
  "eventType": "ethics.report.created",
  "schemaVersion": 1,
  "occurredAt": "2026-07-18T12:00:00Z",
  "orgId": "opaque",
  "productId": "etik-speak",
  "aggregateType": "case",
  "aggregateId": "opaque",
  "aggregateVersion": 1,
  "correlationId": "opaque",
  "data": {"mode":"ANONYMOUS","category":"WORKPLACE_CONDUCT"}
}
```

Event data never contains narrative, name, contact, access secret, attachment
bytes, IP, UA or referrer. Consumers deduplicate by `eventId`; ordered state
updates require monotonic `aggregateVersion`. Unknown additive fields are
ignored; incompatible changes use new `schemaVersion` and parallel publish
during N/N-1 window.

Initial event types:

- `ethics.report.created`
- `ethics.case.status.changed`
- `ethics.case.assigned`
- `ethics.mailbox.message.created`
- `ethics.evidence.scan.completed`
- `ethics.evidence.reveal.recorded`
- `ethics.retention.action.requested`

## 7. Manager UI contract

### ES-1 TEST isolated manager

ES-1'in canonical staff yüzeyi `testai.acik.com/ethic` üzerindeki ayrı
`etik-speak-manager` artifact/deployment/service'tir. Shared suite frontend
digest'i bu aktivasyonda değişmez. Manager:

- Keycloak `frontend` client ile same-origin `check-sso` ve PKCE S256 kullanır;
- login/upgrade isteğinde `openid ethics-manager-audience ethics:case:manage`
  scope'unu ister ve redirect'i yalnız same-origin `/ethic` deep-link'ine bağlar;
- hassas UI'yi yalnız token `aud=ethics-manager`, scope
  `ethics:case:manage` ve realm role `ethics-manager` üçlüsünün tamamıyla
  render eder;
- staff API bearer'ını kendi token provider'ından ekler, `credentials: omit`
  kullanır ve caller-supplied `Authorization`/`Cookie` başlığını reddeder;
- logout, refresh error, eksik claim veya API `401/403` halinde token
  provider'ını temizler ve protected case content'i derhal unmount eder;
- source workflow unit testleri ve digest-içi Chromium smoke; deployment sonrası
  ise wrong-org/OpenFGA-deny ve kapalı-döngü browser acceptance ile kanıtlanır.

Bu isolated TEST kararı bir production promotion yetkisi değildir. Production
route'u ayrı değişiklik, secret-owner ve live acceptance kapılarına tabidir.

### ES-4 optional suite integration adapter

Staff remote:

```text
name: mfe_ethic
expose: ./EthicApp
route: /ethic
remoteEntry: /remotes/ethic/remoteEntry.js
```

- remote artifact is immutable and content-addressed;
- `remoteEntry.js` uses `Cache-Control: no-store`; hashed chunks use immutable
  caching;
- React, React DOM, router, Redux and React Query remain strict singleton/host
  contracts matching the shell version matrix;
- remote exports a valid React component and owns a product error boundary;
- remote unavailable/incompatible shows a classified Etik Speak fallback and
  does not white-screen or block other suite routes;
- runtime `MFE_ETHIC_URL` is environment-scoped; test and prod promotion do not
  rebuild API behavior into the bundle;
- public reporter artifact is not a federation remote and imports no shell auth
  runtime.

ES-4 etkinleştirilirse compatibility gate shell N ile remote N/N-1 ve remote N ile API
N/N-1. Breaking remote expose/shared singleton changes require a new expose key
or coordinated shell major; silent replacement is forbidden. Bu remote kontratı
ES-1 isolated manager acceptance'ının ön koşulu değildir.

## 8. Security and privacy negative contract

The following are release-blocking expected-denial tests:

1. suite bearer/cookie cannot list/open public cases;
2. reporter secret cannot call any staff route;
3. public route cannot list cases or read identity;
4. cross-org staff token gets no existence signal;
5. conflicted/recused staff gets no narrative before disclosure;
6. normal handler cannot retrieve sealed original;
7. raw access secret/narrative/identity is absent from logs, traces and events;
8. neither public host receives a `.acik.com` domain cookie;
9. public host CSP/header behavior is equivalent and artifact digest identical;
10. notification/audit sink outage does not lose the report transaction;
11. duplicate idempotency retry does not create a second report/message;
12. MFE failure leaves the suite and public hosts functional.

## 9. Deprecation and rollback

- Deprecation is documented for at least one supported minor/N-1 window.
- DB migrations are expand/contract; destructive contract runs only after N-1
  is outside rollback window and backup/restore evidence exists.
- Rollback re-pins previous immutable service/public/MFE digests. Moving tags are
  not evidence.
- Event consumers tolerate old schema during the published dual-read window.
- Runtime acceptance is recorded separately for source, rendered desired state,
  deployment, browser journey, security/privacy and recoverability.
