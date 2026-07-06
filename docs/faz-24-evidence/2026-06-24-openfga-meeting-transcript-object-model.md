# Faz 24 OpenFGA Meeting/Transcript Object Model Evidence

Date: 2026-06-24

Scope: platform-test OpenFGA model extension for recorder e2e blocker
`platform-k8s-gitops#1660`.

Canonical backend source alignment: `platform-backend#742`.

## Starting Truth

- Store: `01KPP0CFP4G82K42Y6NYSPT4JF`
- Active selector before this evidence:
  `kv/platform/openfga#model_id = 01KS8QE8T1EJ2DF5CRS4VV9YX1`
- Live model `01KS8QE8T1EJ2DF5CRS4VV9YX1` had 15 types:
  `user`, `organization`, `company`, `project`, `warehouse`, `branch`,
  `module`, `action`, `report`, `report_group`, `subscriber`,
  `service_account`, `notification_topic`, `notification_template`, `template`.
- Missing object types: `meeting`, `transcript`.

The runtime failure motivating this was:

```text
Invalid tuple 'meeting:<uuid>#owner@user:990001'. Reason: type 'meeting' not found
```

That failure blocks canonical meeting UUID creation through `meeting-service`,
so recorder e2e cannot proceed honestly by bypassing the app path.

## Model Extension

New model ID written append-only to the same test store:

```text
01KVXG15ETYAHMHANFD0E5CVK8
```

Content digest:

```text
sha256:34d59b2230ea944ae1c2a1d9d27dc36baf3ee90f5514600cd007b215b7e642df
```

Note: an earlier append-only validation write produced
`01KVXFD5ZQB4EQWCH8YF9J1H8T`, but that request body still carried the
env-specific source model `id`. It is intentionally superseded by
`01KVXG15ETYAHMHANFD0E5CVK8` and is not the ledger artifact or selector target.

Only two type definitions were appended:

- `meeting`
- `transcript`

Both use the same object ReBAC relation surface:

- `owner: [user] but not blocked`
- `participant: [user] but not blocked`
- `viewer: [user] or participant or owner but not blocked`
- `blocked: [user]`

Existing module-level gates remain unchanged. `module:MEETING` and
`module:TRANSCRIPT` are still instances of the existing `module` type.

Claude CLI review returned `AGREE`: additive-only, safe to write to the test
store for validation; transcript-to-meeting parent inheritance can be a later
additive iteration if product needs it.

## Verification

The new model was checked explicitly with `authorization_model_id` set to
`01KVXG15ETYAHMHANFD0E5CVK8`; the runtime selector was not changed during this
verification.

Persistent module tuple checks:

```text
PASS check user:1 can_view module:MEETING allowed=true
PASS check user:1 can_manage module:TRANSCRIPT allowed=true
PASS check user:9102 can_manage module:MEETING allowed=false
PASS check user:0 can_view module:MEETING allowed=false
```

Transient object tuple checks:

```text
PASS write user:990001 owner meeting:00000000-0000-0000-0000-000000001660 HTTP=200
PASS check user:990001 owner meeting:00000000-0000-0000-0000-000000001660 allowed=true
PASS check user:990001 viewer meeting:00000000-0000-0000-0000-000000001660 allowed=true
PASS check user:0 viewer meeting:00000000-0000-0000-0000-000000001660 allowed=false
PASS write user:990001 owner transcript:00000000-0000-0000-0000-000000001660 HTTP=200
PASS check user:990001 owner transcript:00000000-0000-0000-0000-000000001660 allowed=true
PASS check user:990001 viewer transcript:00000000-0000-0000-0000-000000001660 allowed=true
PASS check user:0 viewer transcript:00000000-0000-0000-0000-000000001660 allowed=false
PASS delete user:990001 owner meeting:00000000-0000-0000-0000-000000001660 HTTP=200
PASS delete user:990001 owner transcript:00000000-0000-0000-0000-000000001660 HTTP=200
PASS check user:990001 owner meeting:00000000-0000-0000-0000-000000001660 allowed=false
PASS check user:990001 owner transcript:00000000-0000-0000-0000-000000001660 allowed=false
```

## Boundary

This proves the new model is present and valid in the test store, and that it
supports the `meeting:<uuid>#owner@user:<id>` write path needed by
`meeting-service`.

It does not yet prove recorder runtime readiness. The shared runtime selector
still has to be promoted from `01KS8QE8T1EJ2DF5CRS4VV9YX1` to
`01KVXG15ETYAHMHANFD0E5CVK8`, ExternalSecrets must sync, model-consuming pods
must roll, then meeting create and recorder session lifecycle smoke must pass.
