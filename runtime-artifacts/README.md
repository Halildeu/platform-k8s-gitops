# `runtime-artifacts/` — Non-Image Artifact Ledger

ADR-0023 Guardrail PR-6. Sibling to `release-candidates/` (image artifact ledger). Tracks runtime artifacts that are NOT container images but still need a test→prod promotion chain with D29-style evidence.

**Currently supported kinds**: `openfga-model`

## Why a separate ledger?

The image ledger at `release-candidates/<repo>/<sha>.json` is image-specific: it requires a `service` name, a `git_sha`, and an `image.{registry, path, digest, tag}` block. OpenFGA authorization models, ConfigMaps with runtime semantics, and similar non-image artifacts don't fit that shape:

- No `git_sha` (artifact is data, not code)
- No container image registry / digest / tag
- Different identity model: env-specific runtime IDs (e.g. OpenFGA ULIDs) that differ across test and prod stores even for byte-identical canonical content

This ledger uses **content digest** (sha256 of canonicalized JSON) as the cross-env identity anchor, with env-specific runtime IDs tracked per promotion block.

## File layout

```
runtime-artifacts/
├── README.md                                 (this file)
└── <artifact_kind>/
    └── <content-digest-without-sha256:>.json
```

Examples:
- `runtime-artifacts/openfga-model/abc123...def.json` — an OpenFGA authorization model
- `runtime-artifacts/openfga-model/00000...001.json` (test fixtures use these placeholder digests)

Schema: [`schema/runtime-artifact-ledger-v1.schema.json`](../schema/runtime-artifact-ledger-v1.schema.json).

## Canonical digest algorithm (NORMATIVE)

```
artifact_content_digest = "sha256:" + hex(sha256(RFC8785_canonicalize(artifact_json)))
```

RFC 8785 (JSON Canonicalization Scheme) ensures whitespace, key ordering, and number-formatting differences across stores produce the same digest for byte-equivalent canonical content. This is critical: when the same model JSON is written to test and prod OpenFGA stores, each store assigns its own ULID (`model_id_env`), but the canonical content digest is identical.

### Worked example: OpenFGA model

1. Fetch the authorization model from a store:
   ```bash
   curl -sf "$OPENFGA_API/stores/$STORE_ID/authorization-models/$MODEL_ID" | jq '.authorization_model'
   ```
2. Strip the wrapper — pass only the inner `authorization_model` object to canonicalization.
3. Canonicalize (Python reference; production code may use a vetted RFC8785 library):
   ```python
   import json, hashlib
   # NOTE: full RFC 8785 includes number normalization; this snippet is illustrative.
   canonical = json.dumps(model_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
   digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
   ```
4. Use that digest in the filename and as `artifact_content_digest` in the ledger entry.

> The exact canonicalization helper will be standardized in a follow-up PR (canonicalize helper + backfill tool). Until then, the validator only checks digest **format** and **filename ↔ field consistency**, not recomputation.

## Ledger entry contract

Per the schema (`additionalProperties: false` everywhere):

| Top-level | Required | Notes |
|---|---|---|
| `schema_version` | yes | `"1.0"` |
| `artifact_kind` | yes | Currently `"openfga-model"` |
| `artifact_content_digest` | yes | `sha256:` + 64 hex |
| `source` | yes | `{kind, canonical_source_ref}` — digest provenance only |
| `runtime_selector` | no | `oneOf [null, vault, openfga-store-direct]` — where consumers find current id at runtime |
| `promotion` | yes | `{test, prod}` env blocks (see below) |
| `metadata` | yes | `{rollback_safe, ...}` |
| `audit` | yes | `{implementer, reviewer, created_at, approval_pathway, ...}` |

### Promotion block

| Field | Required | Notes |
|---|---|---|
| `status` | yes | `pending` / `verified` / `promoted` / `rolled-back` |
| `method` | yes | `pr-promotion` / `manual-prod-migration` / `historical-backfill` |
| `store_ref` | yes | Env-specific runtime store (e.g. `platform-test`, `platform-prod`) |
| `model_id_env` | conditional | Crockford ULID; null while `status=pending`; required + non-null for `verified`/`promoted` |
| `evidence` | conditional | `null` while pending; strict `evidence_openfga_model` shape for verified/promoted |
| `evidence_completeness` | yes | `complete` / `partial-import` / `unverified` |
| `source_docs` | yes | Array; `minItems=1` for verified/promoted |
| `verified_at` | conditional | Required for `verified`/`promoted` |
| `promoted_at` | conditional | Required for `promoted` |

### Approval pathway guards

- `approval_pathway = emergency-bypass` → requires `audit.bypass_justification` (minLength ≥ 20)
- `approval_pathway = historical-backfill` → requires `audit.backfill = true` AND `audit.imported_at`

## Validator

[`scripts/promotion/validate-runtime-artifact-schema.py`](../scripts/promotion/validate-runtime-artifact-schema.py).

```bash
# All under runtime-artifacts/
python3 scripts/promotion/validate-runtime-artifact-schema.py

# PR diff only (CI uses this for pull_request runs)
python3 scripts/promotion/validate-runtime-artifact-schema.py --pr-only

# Single file (fixture matrix)
python3 scripts/promotion/validate-runtime-artifact-schema.py --single path/to/ledger.json
```

Exit codes: 0 (valid), 1 (violation), 2 (tool/setup error).

## Test fixtures

[`tests/runtime-artifacts/fixtures/`](../tests/runtime-artifacts/fixtures/) — covers:

| Fixture | Expected | Tests |
|---|---|---|
| `valid-openfga-model.json` | rc=0 | Happy path: pending test + promoted prod |
| `invalid-bad-digest.json` | rc=1 | digest missing `sha256:` prefix |
| `invalid-missing-required.json` | rc=1 | top-level required field missing |
| `invalid-loose-evidence.json` | rc=1 | extra field in `evidence` (strict additionalProperties:false) |
| `invalid-bad-ulid.json` | rc=1 | `model_id_env` contains I/L/O/U (forbidden in Crockford base32) |
| `invalid-pending-with-evidence.json` | rc=1 | pending status with non-null evidence (conditional violation) |
| `invalid-emergency-bypass-no-justification.json` | rc=1 | `approval_pathway=emergency-bypass` without `bypass_justification` |
| `invalid-historical-backfill-no-imported-at.json` | rc=1 | `approval_pathway=historical-backfill` without `imported_at` |

Naming convention: `valid-*.json` → validator must accept (rc=0); `invalid-*.json` → validator must reject (rc=1).

## CI gate

[`.github/workflows/gate-runtime-artifact-ledger.yml`](../.github/workflows/gate-runtime-artifact-ledger.yml).

Three jobs:
1. `validate-pr` — PR-time diff scan (fetch-depth:0 + `--pr-only`)
2. `validate-main-full` — push-to-main full scan
3. `fixtures` — positive+negative fixture matrix; ensures the validator distinguishes shapes correctly

## Adding a new artifact kind

When introducing a new kind (e.g. `runtime-configmap`):

1. **Schema** — extend `artifact_kind` enum + add `$defs.evidence_<kind>` strict object (mirror `evidence_openfga_model` shape).
2. **Validator** — add per-kind format hook in `validate_kind_format_hooks()` (e.g. content-specific ULID/UUID/path regex checks beyond what the schema enforces).
3. **Fixtures** — at least one positive (`valid-<kind>.json`) + relevant negative cases (digest, required, conditional violations).
4. **Workflow** — add new fixtures to the matrix in `gate-runtime-artifact-ledger.yml`.
5. **This README** — extend the "Currently supported kinds" line + add a worked example for the new kind's canonical content.

## PR-7 wiring (next step)

PR-7 (`deploy-prod-gitops.yml` artifact-dependency preflight) will consume this ledger:

- Before prod deploy, look up the artifact_content_digest referenced by the deploy manifest
- Require a ledger entry with `promotion.prod.status == "promoted"` (or accepted waiver)
- Block the deploy if missing/pending/rolled-back

PR-6 only sets up the schema infrastructure; PR-7 is the enforcement layer.

## P0-c backfill (separate follow-up issue)

The 2026-05-20 P0-c migration (`01KPXCVBMDKXXRPGKFGPDRVBQX` → `01KS15PF531R1P99BMMM7SFMV1` adding `report_group` type) is NOT backfilled in PR-6. Reason: honest evidence chain requires fetching the canonical model JSON from the test store, computing the RFC 8785 digest, and recording the full evidence shape — that's its own PR with its own Codex review chain. Tracked in a follow-up issue with `approval_pathway: historical-backfill`.

## References

- ADR-0023 `docs/adr/0023-promotion-pipeline-test-overlay-authoritative.md`
- Image ledger sibling: `schema/promotion-ledger-v1.schema.json`, `scripts/promotion/validate-ledger-schema.py`
- RFC 8785 JSON Canonicalization Scheme: https://datatracker.ietf.org/doc/html/rfc8785
- Codex plan thread: `019e44d9` (iter-1 REVISE → iter-2 REVISE → iter-3 AGREE ready_for_impl:true)
