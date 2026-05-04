# Promotion scripts (Codex P0 #2 + Sprint B B1 implementation)

PR-first promotion bot implementation per Codex Sprint B B1 retrospective.
See `docs/operations/promotion-ledger-design.md` and
`docs/operations/d29-evidence-pipeline-design.md` for full architecture.

## Scripts

### Schema + validation
- **`validate-ledger-schema.py`** — JSON schema validation; runs in CI
  on any PR touching `release-candidates/**`. Cross-checks: file path
  matches manifest content, service name in services.yaml catalog,
  digest format, short-sha consistency.

### Build → ledger entry
- **`generate-ledger.sh`** — invoked by platform-backend/platform-web CI
  after image build + GHCR push. Creates initial
  `release-candidates/<repo>/<sha>.json` with status="built".
  Idempotent: existing entries preserved.
  Args: repo, service, git_sha, image_path, image_digest.
  Optional env: PUSH_RUN_ID, ROLLBACK_TO, CI_RUN_URL.

### Test verify → ledger update
- **`ledger-mark-verified.sh`** — invoked by smoke runner ExecStartPost
  after D29 GREEN on test cluster. Reads smoke JSON, finds matching
  ledger entries by digest, updates `promotion.test.smoke_evidence` +
  `verified_at`, opens auto-promotion PR (auto-merge after schema
  validation).

### Scan → prod candidate PR
- **`scan-promotion-candidates.sh`** — invoked by daily scheduled
  workflow OR manual. Finds verified-in-test ledger entries without
  open prod-candidate PR, opens **DRAFT** PR with prod overlay digest
  bump. Operator reviews + merges manually.
  Skips: not test-verified, already in prod, candidate PR open.

### Prod sync → ledger close
- **`ledger-close-prod.sh`** — invoked by smoke-prod ExecStartPost OR
  scheduled. Reads live prod cluster pod imageIDs, walks ledger entries
  with `promoted_by_pr` set but no `promoted_at`, updates ledger when
  digest is observed running in prod.

### D30 enforcement gate
- **`gate-evidence-check.py`** — used by `gate-d29-evidence-required.yml`
  CI workflow. Blocks prod overlay PRs without test smoke evidence
  (D29 GREEN per Zanzibar policy from services.yaml).

## CI integration (Sprint B B2/B3 follow-up)

After this PR, platform-backend + platform-web CI workflows need to call
`generate-ledger.sh` after their image build + GHCR push step. That
integration is a separate PR per Sprint B sequencing (B2: GitHub App
registration → B3: backend/web CI workflow update).

## Operator usage

### Manual ledger entry creation (canary or backfill)
```bash
PUSH_RUN_ID=$RUN_ID CI_RUN_URL=$URL \
bash scripts/promotion/generate-ledger.sh \
  platform-backend \
  user-service \
  $GIT_SHA \
  halildeu/platform-backend-user-service \
  $IMAGE_DIGEST
```

### Manual prod-candidate scan
```bash
PROMOTION_DRY_RUN=1 bash scripts/promotion/scan-promotion-candidates.sh
# Review what would happen, then drop DRY_RUN to actually open PRs
bash scripts/promotion/scan-promotion-candidates.sh
```

### Manual prod ledger close
```bash
bash scripts/promotion/ledger-close-prod.sh --dry-run
# Review which entries would close, then run for real
bash scripts/promotion/ledger-close-prod.sh
```

## Design references

- `docs/operations/promotion-ledger-design.md` — full architecture spec
- `docs/operations/d29-evidence-pipeline-design.md` — D29 evidence pipeline
- `schema/promotion-ledger-v1.schema.json` — strict ledger entry shape
- `tests/promotion/fixtures/` — positive/negative ledger fixtures

P0c (GitHub App registration) is operator manual; secret naming convention
documented in promotion-ledger-design.md.
