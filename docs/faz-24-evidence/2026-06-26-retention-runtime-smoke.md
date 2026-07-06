# Faz 24 #156 Retention Runtime Smoke — 2026-06-26

> Scope: `platform-ai#156`, `k3d-test` / `platform-test`,
> `meeting-service`, `transcript-service`.
>
> Boundary: test-only synthetic fixture. This evidence does not record VERBIS
> status, does not prove production deletion, does not include raw audio,
> transcript, prompt, response, token, cookie, private key, packet capture, or
> raw command dump, and does not satisfy #156 acceptance by itself.

## Runtime Image State

Live deployments were read from `staging-sw`:

| Service | Live imageID | Ready | Restarts |
|---|---|---:|---:|
| `meeting-service` | `ghcr.io/halildeu/platform-backend-meeting-service@sha256:e9e45ac39ca53a7986a84c49ff8422077b20acdbc5a84b560b95e893845517cf` | true | 0 |
| `transcript-service` | `ghcr.io/halildeu/platform-backend-transcript-service@sha256:af97f1aa1b3212e0461288f53c1e1a16395e9ed2e80923d0cc4a1137bf2249ba` | true | 0 |

Flyway retention migrations were present:

| DB | Migration | Installed |
|---|---|---|
| `meeting` | `V2 meeting retention destruction audit` | `2026-06-25 21:18:09.463874` |
| `transcript` | `V3 transcript retention destruction audit` | `2026-06-25 21:18:13.696855` |

## Fixture

Synthetic expired rows were inserted into test databases only:

| Layer | Fixture row | ID | Text/content boundary |
|---|---|---|---|
| `db.meeting-intelligence` | `meeting_actions` | `eee16a68-6bb3-42b8-945b-818eda3d9435` | Synthetic row only; not copied into evidence |
| `db.meeting-intelligence` | `meeting_decisions` | `c33d4831-d210-4b06-b5a9-7fd646d63685` | Synthetic row only; not copied into evidence |
| `db.transcript-records` | `transcript_segments` | `85576988-420f-43a7-8508-a9b96fb2cf3a` | `text_draft IS NULL` and `text_final IS NULL` |
| `db.kvkk-access-log` | `transcript_access_audit` | `9d585f45-b36c-4ba2-9378-10f860eeac7e` | Metadata-only access row |

The first transient smoke Job attempt intentionally produced no deletion because
the pod labels did not include `app.kubernetes.io/part-of=platform`, so
default-deny egress blocked DNS/Postgres access. The second attempt kept
`app.kubernetes.io/name` distinct from the live Deployment Service selector while
adding `app.kubernetes.io/part-of=platform`, giving the smoke pod the same
egress class without routing service traffic to it.

Transient Jobs:

| Job | Result | Notes |
|---|---|---|
| `faz24-retention-smoke-meeting-20260626t004240z` | Succeeded | Derived from live `meeting-service` Deployment; only cleanup cron overridden for the smoke window |
| `faz24-retention-smoke-transcript-20260626t004240z` | Succeeded | Derived from live `transcript-service` Deployment; only cleanup cron overridden for the smoke window |

Both transient Jobs were deleted after evidence collection.

## Observed Cleanup

Meeting retention service log metadata:

```text
meeting retention cleanup completed layer=db.meeting-intelligence
actionDeletedCount=1 decisionDeletedCount=1 deletedCount=2
jobId=meeting-intelligence-retention-cleanup
```

Transcript retention service log metadata:

```text
transcript retention cleanup completed layer=db.transcript-records
deletedCount=1 jobId=transcript-records-retention-cleanup

transcript retention cleanup completed layer=db.kvkk-access-log
deletedCount=1 jobId=kvkk-access-log-retention-cleanup
```

## DB Verification

Post-smoke residue checks:

| Fixture | Residue |
|---|---:|
| expired `meeting_actions` row | 0 |
| expired `meeting_decisions` row | 0 |
| parent synthetic `meetings` row after cleanup | 0 |
| expired `transcript_segments` row | 0 |
| expired `transcript_access_audit` row | 0 |

Destruction audit rows written:

| Layer | Job | Deleted count | Payload |
|---|---|---:|---|
| `db.meeting-intelligence` | `meeting-intelligence-retention-cleanup` | 2 | `metadata-only` |
| `db.transcript-records` | `transcript-records-retention-cleanup` | 1 | `metadata-only` |
| `db.kvkk-access-log` | `kvkk-access-log-retention-cleanup` | 1 | `metadata-only` |

The meeting service also wrote a later zero-count audit row during the bounded
smoke window after the expired fixture had already been deleted. This is
expected scheduled-job behavior and did not create content-bearing evidence.

## Remaining #156 Boundary

This smoke narrows the #156 DB-cleanup runtime gap for test by proving deployed
`meeting-service` and `transcript-service` cleanup jobs can delete expired rows
and write metadata-only destruction audit rows.

Still open before #156 can pass:

- VERBIS status must be recorded or explicitly exempt-confirmed.
- MinIO lifecycle runtime evidence for the configured retention buckets must be
  attached.
- Production/legal owner acceptance remains separate.
- This evidence does not prove direct-STT, G-WER/DER, G-INT, app-mTLS,
  desktop mic/loopback, or production readiness.
