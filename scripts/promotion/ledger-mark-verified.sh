#!/usr/bin/env bash
# scripts/promotion/ledger-mark-verified.sh
#
# Codex Sprint A P0 — D29 evidence pipeline. Reads a smoke-evidence JSON
# from `scripts/smoke/d29-smoke-runner.sh` and updates the matching ledger
# entry's `promotion.<env>.smoke_evidence` block + verified_at field.
#
# Auto-detects the right ledger entry by:
#   1. Reading current overlay digest for each service from kustomize render
#   2. Finding the ledger entry whose image.digest matches
#   3. Updating that entry only (one entry per service per cluster state)
#
# After update, opens a PR via gh CLI (auto-promotion bot pattern) since
# release-candidates/ is treated as gitops-managed (PR-mediated changes).
#
# Designed for staging-sw systemd integration:
#
#   ExecStart=/bin/bash d29-smoke-runner.sh test
#   ExecStartPost=/bin/bash ledger-mark-verified.sh /tmp/smoke-report-test-<ts>.json
#
# Or invoked manually for ad-hoc evidence backfill.
#
# Auth: requires gh CLI logged in (or GITHUB_TOKEN env). Read+write contents
# scope on platform-k8s-gitops repo for the auto-promotion branch.

set -euo pipefail

REPORT="${1:-/tmp/smoke-report-test-latest.json}"
[[ ! -f "$REPORT" ]] && { echo "ERR: smoke report not found: $REPORT"; exit 1; }

ENV=$(jq -r '.environment' "$REPORT")
EXIT_CODE=$(jq -r '.exit_code' "$REPORT")
TS=$(jq -r '.timestamp' "$REPORT")
# Variant marker (added 2026-05-21 — DiD-3 frontend-variant report-driven mode).
# Empty for backend smoke reports; "frontend-prod-variant" for
# d29-frontend-variant-smoke.sh (ADR-0022) which runs the env-baked prod
# artifact transiently in the test cluster.
VARIANT=$(jq -r '.variant // empty' "$REPORT")

# Only mark verified if smoke was GREEN
if [[ "$EXIT_CODE" -ne 0 ]]; then
  echo "[ledger-mark-verified] smoke FAILED (exit_code=$EXIT_CODE) — NOT marking ledger entries verified"
  echo "                       Operator should investigate before promotion"
  # Still useful: log the failure to a separate audit trail file
  exit 0
fi

# Policy-tier gating moved into the per-(service,digest) loop below. The
# previous pre-flight blanket NON_GREEN reject was correct for backend cluster
# smoke (every tier strict GREEN) but wrong for frontend prod-variant smoke
# where d29_zanzibar is intrinsically AMBER (ADR-0022 — SPA has no JWT decoder
# / OpenFGA plane). Per-service policy now mirrors gate-evidence-check.py:
# services.yaml jwt_validates=false → d29_zanzibar GREEN-or-AMBER accepted;
# every other service / unknown service → strict GREEN. See helper:
# scripts/promotion/d29_evidence_policy.py (check-tiers subcommand).

REPO_ROOT="${PLATFORM_GITOPS_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OVERLAY="$REPO_ROOT/kustomize/overlays/${ENV}"
LEDGER_DIR="$REPO_ROOT/release-candidates"
GH_REPO="${GITHUB_REPO:-Halildeu/platform-k8s-gitops}"
# Policy helper lives next to this script (resolved from BASH_SOURCE — does
# NOT follow PLATFORM_GITOPS_REPO override; tests can isolate the ledger dir
# without re-shipping the helper).
POLICY_HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/d29_evidence_policy.py"

[[ ! -d "$LEDGER_DIR" ]] && { echo "ERR: ledger dir not found: $LEDGER_DIR"; exit 1; }
[[ ! -f "$POLICY_HELPER" ]] && { echo "ERR: policy helper not found: $POLICY_HELPER"; exit 1; }

echo "[ledger-mark-verified] env=$ENV report=$REPORT variant=${VARIANT:-<none>}"

# --- Target resolution -------------------------------------------------------
# Two modes drive which (service, digest) pairs we attempt to mark verified:
#
#   1. report-driven (variant == "frontend-prod-variant"):
#        Frontend prod-variant transient smoke runs the env-baked prod image
#        directly in the test cluster. The test overlay still pins the
#        testai variant digest, so an overlay render would produce the WRONG
#        digest for ledger lookup. Take service+digest from the report
#        itself: .image_digest (resolved from pod imageID, identical to the
#        prod-variant image we'd promote).
#
#   2. overlay-render (backend / generic cluster smoke):
#        Default behavior — render the test overlay and walk every
#        Deployment+StatefulSet container image. Each (service, digest)
#        pair maps 1:1 to a release-candidates/<repo>/<sha>.json entry.
#
# Within mode (1) the entry lookup is digest-primary; git_sha is fallback
# (single-match required) when the runner could not resolve a digest from
# the pod imageID (rare — port-forward / API failure during smoke).
if [[ "$VARIANT" == "frontend-prod-variant" ]]; then
  TARGET_MODE="report_driven"
  REPORT_IMAGE=$(jq -r '.image // empty' "$REPORT")
  REPORT_DIGEST=$(jq -r '.image_digest // empty' "$REPORT")
  REPORT_GIT_SHA=$(jq -r '.git_sha // empty' "$REPORT")
  # If image_digest is empty, parse it out of the image ref.
  if [[ -z "$REPORT_DIGEST" && -n "$REPORT_IMAGE" ]]; then
    REPORT_DIGEST=$(printf '%s' "$REPORT_IMAGE" | sed -nE 's|^.*@(sha256:[a-f0-9]{64})$|\1|p')
  fi
  if [[ -z "$REPORT_DIGEST" && -z "$REPORT_GIT_SHA" ]]; then
    echo "[ledger-mark-verified] ERR: frontend-prod-variant report has neither image_digest nor git_sha — cannot resolve ledger entry"
    exit 1
  fi
  # Single (service, digest) pair — digest may be empty (git_sha fallback only).
  # The image path comes from the report's image ref (registry/path[:tag]@digest);
  # the documented default is the prod-variant frontend package.
  REPORT_IMAGE_PATH=$(printf '%s' "$REPORT_IMAGE" | sed -nE 's|^[^/]+/([^@:]+)(:[^@]+)?(@sha256:[a-f0-9]{64})?$|\1|p')
  RENDERED="frontend ${REPORT_IMAGE_PATH:-halildeu/platform-web-frontend} ${REPORT_DIGEST:-<git-sha-fallback>}"
  echo "[ledger-mark-verified] target-mode=report_driven svc=frontend digest=${REPORT_DIGEST:-<none>} git_sha=${REPORT_GIT_SHA:-<none>}"
else
  TARGET_MODE="overlay_render"
  [[ ! -d "$OVERLAY" ]] && { echo "ERR: overlay not found: $OVERLAY"; exit 1; }
  RENDERED=$(kubectl kustomize "$OVERLAY" 2>/dev/null | python3 -c "
import sys, yaml, re
docs = list(yaml.safe_load_all(sys.stdin))
seen = set()
for d in docs:
    if not isinstance(d, dict): continue
    if d.get('kind') not in ('Deployment', 'StatefulSet'): continue
    svc = d.get('metadata', {}).get('labels', {}).get('app.kubernetes.io/name')
    if not svc: continue
    for c in d.get('spec', {}).get('template', {}).get('spec', {}).get('containers', []):
        img = c.get('image', '')
        # <registry>/<path>[:<tag>]@sha256:<hex> — the tag is NOT part of the
        # GHCR package name (Codex 01a09219 P2: newTag + digest render as path:tag@digest).
        # The first component is a registry host only when it looks like one
        # ('.' or ':' inside, or 'localhost'); a bare 'halildeu/pkg@sha256:…'
        # ref is owner/package on the default registry (gitops#3677 follow-up:
        # audio-gateway rendered that way and the owner was lost).
        m = re.match(r'^(?P<first>[^/]+)/(?P<rest>[^@:]+)(?::[^@]+)?@(?P<dig>sha256:[a-f0-9]+)\$', img)
        if m:
            first, rest = m.group('first'), m.group('rest')
            path = rest if ('.' in first or ':' in first or first == 'localhost') else f\"{first}/{rest}\"
            key = (svc, m.group('dig'))
            if key not in seen:
                seen.add(key)
                print(f\"{svc} {path} {m.group('dig')}\")
")
  if [[ -z "$RENDERED" ]]; then
    echo "[ledger-mark-verified] no service+digest pairs in render; nothing to mark"
    exit 0
  fi
  echo "[ledger-mark-verified] target-mode=overlay_render pairs=$(echo "$RENDERED" | wc -l | tr -d ' ')"
fi

# Entry lookup by (service, digest) across every ledger file.
find_entry() {
  local svc="$1" digest="$2" f
  for f in "$LEDGER_DIR"/*/*.json; do
    [[ -f "$f" ]] || continue
    if jq -e --arg s "$svc" --arg d "$digest" 'select(.service == $s and .image.digest == $d)' "$f" >/dev/null 2>&1; then
      echo "$f"
      return 0
    fi
  done
  return 0
}

# --- gitops#3677: derive a missing ledger entry from the registry ---------
# The entry's git_sha comes from the sha-<7> tags GHCR attaches to the exact
# digest the overlay pins (the pull digest); several tags share one digest when
# consecutive commits rebuild identically, so the NEWEST commit wins. The repo
# comes from docs/operations/services.yaml. Writes through generate-ledger.sh
# (per-service file name) and prints the file path; prints nothing and returns
# 1 when the digest cannot be attributed (no sha-* tag, unknown service).
autogenerate_entry() {
  local svc="$1" image_path="$2" digest="$3"
  local repo
  repo=$(python3 - "$svc" "$REPO_ROOT/docs/operations/services.yaml" <<'PY'
import sys, yaml
svc, path = sys.argv[1], sys.argv[2]
for s in yaml.safe_load(open(path)).get("services", []):
    if s.get("name") == svc:
        print(s.get("repo", ""))
        break
PY
)
  if [[ -z "$repo" ]]; then
    echo "  [GEN-SKIP] $svc: no repo in services.yaml" >&2
    return 1
  fi
  local owner="${image_path%%/*}" pkg="${image_path#*/}"
  # ADR-0022: the env-baked testai frontend variant is never promoted — the
  # prod-variant transient smoke (report-driven mode) records the promotable
  # artifact under the same commit + service; recording the testai digest too
  # would put two artifacts under one (commit, service) identity.
  if [[ "$pkg" == *-testai ]]; then
    echo "  [GEN-SKIP] $svc: $pkg is the env-baked testai variant — not promotable (ADR-0022); the prod-variant smoke records the ledger entry" >&2
    return 1
  fi
  local versions tags
  # A failed registry query is reported as such — not as "no tags"; a partial
  # page could otherwise pick an older commit silently.
  if ! versions=$(gh api --paginate "users/${owner}/packages/container/${pkg}/versions?per_page=100" \
      --jq ".[] | select(.name==\"$digest\") | .metadata.container.tags[]" 2>/dev/null); then
    echo "  [GEN-SKIP] $svc: GHCR package query failed for ${owner}/${pkg}" >&2
    return 1
  fi
  # sha-<7> (backend/web CI) or sha-<40> (the Etik Speak web images tag the full commit)
  tags=$(printf '%s\n' "$versions" | grep -E '^sha-[a-f0-9]{7,40}$' || true)
  if [[ -z "$tags" ]]; then
    echo "  [GEN-SKIP] $svc: digest $digest carries no sha-* tag on GHCR" >&2
    return 1
  fi
  local best="" best_ts=0 tag short line sha ts
  while read -r tag; do
    [[ -z "$tag" ]] && continue
    short="${tag#sha-}"
    line=$(gh api "repos/${owner}/${repo}/commits/${short}" --jq '.sha + " " + .commit.committer.date' 2>/dev/null) || continue
    sha="${line%% *}"
    ts=$(python3 -c 'import sys, datetime; print(int(datetime.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).timestamp()))' "${line##* }" 2>/dev/null || echo 0)
    if [[ "$ts" -gt "$best_ts" ]]; then best="$sha"; best_ts="$ts"; fi
  done <<< "$tags"
  if [[ -z "$best" ]]; then
    echo "  [GEN-SKIP] $svc: none of the tags ($(echo "$tags" | tr '\n' ' ')) resolves to a commit in $repo" >&2
    return 1
  fi
  local gen_out gen_rc file
  gen_out=$(PLATFORM_GITOPS_REPO="$REPO_ROOT" bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/generate-ledger.sh" \
    "$repo" "$svc" "$best" "$image_path" "$digest" 2>&1)
  gen_rc=$?
  if [[ $gen_rc -ne 0 ]]; then
    echo "  [GEN-SKIP] $svc: generate-ledger refused (exit $gen_rc): $(printf '%s\n' "$gen_out" | tail -1)" >&2
    return 1
  fi
  file=$(printf '%s\n' "$gen_out" | tail -1)
  [[ -f "$file" ]] || return 1
  echo "  [GEN] $svc → ${file#"$REPO_ROOT"/} (git_sha ${best:0:8}, from GHCR tags: $(echo "$tags" | tr '\n' ' '))" >&2
  echo "$file"
}

# Auto-create branch for ledger updates
TS_FILE=$(date -u +%Y%m%dT%H%M%SZ)
BRANCH="auto-verified/${ENV}-${TS_FILE}"
UPDATED_FILES=()

cd "$REPO_ROOT" || exit 1

# Iterate (service, digest) pairs and find matching ledger entries
while IFS=' ' read -r svc image_path digest; do
  [[ -z "$svc" ]] && continue

  # --- Locate ledger entry ---------------------------------------------------
  # report-driven (frontend prod variant): search release-candidates/platform-web/
  # with repo+service+image.path constraints, then digest-primary, git_sha fallback.
  # overlay-render: digest-primary across all release-candidates/*/*.json.
  match=""
  if [[ "$TARGET_MODE" == "report_driven" && "$svc" == "frontend" ]]; then
    # Primary: digest match constrained to platform-web/halildeu/platform-web-frontend.
    if [[ -n "$REPORT_DIGEST" ]]; then
      for f in "$LEDGER_DIR"/platform-web/*.json; do
        [[ -f "$f" ]] || continue
        ledger_repo=$(jq -r '.repo // empty' "$f")
        ledger_svc=$(jq -r '.service // empty' "$f")
        ledger_path=$(jq -r '.image.path // empty' "$f")
        ledger_digest=$(jq -r '.image.digest // empty' "$f")
        if [[ "$ledger_repo" == "platform-web" \
              && "$ledger_svc" == "frontend" \
              && "$ledger_path" == "halildeu/platform-web-frontend" \
              && "$ledger_digest" == "$REPORT_DIGEST" ]]; then
          match="$f"; break
        fi
      done
    fi
    # Fallback: git_sha single-match — ONLY when the report carries no digest.
    # With a digest, "no exact artifact" must stay empty so the common
    # autogenerate path (or an honest SKIP) runs instead of matching the same
    # commit's OTHER artifact (Codex 01a09219 iter-2 P2).
    if [[ -z "$match" && -z "$REPORT_DIGEST" && -n "$REPORT_GIT_SHA" ]]; then
      candidates=()
      for f in "$LEDGER_DIR"/platform-web/*.json; do
        [[ -f "$f" ]] || continue
        ledger_repo=$(jq -r '.repo // empty' "$f")
        ledger_svc=$(jq -r '.service // empty' "$f")
        ledger_path=$(jq -r '.image.path // empty' "$f")
        ledger_git=$(jq -r '.git_sha // empty' "$f")
        if [[ "$ledger_repo" == "platform-web" \
              && "$ledger_svc" == "frontend" \
              && "$ledger_path" == "halildeu/platform-web-frontend" \
              && "$ledger_git" == "$REPORT_GIT_SHA" ]]; then
          candidates+=("$f")
        fi
      done
      if [[ "${#candidates[@]}" -eq 1 ]]; then
        match="${candidates[0]}"
        echo "  [INFO] $svc git_sha=$REPORT_GIT_SHA fallback matched ${match} (single candidate, digest=$REPORT_DIGEST not yet in any ledger)"
      elif [[ "${#candidates[@]}" -gt 1 ]]; then
        echo "  [SKIP] $svc git_sha=$REPORT_GIT_SHA matches multiple ledger entries (${#candidates[@]}); refusing ambiguous match" >&2
        continue
      fi
    fi
  else
    # overlay-render mode (backend / generic cluster smoke). Lookup is by
    # service + digest: several services can run one image (the ethics
    # workers share ethics-service's), so a digest-only grep would hand
    # another service's entry back (Codex 01a09219 P2).
    [[ -z "$digest" ]] && continue
    match=$(find_entry "$svc" "$digest")
  fi

  # gitops#3677: no CI feeds the ledger (backend/web image workflows are
  # build-only), so with LEDGER_AUTOGENERATE=1 a missing entry is derived here
  # from what is observable — the digest's GHCR tags → the newest source
  # commit. Both target modes, only with a real digest to attribute.
  if [[ -z "$match" && "${LEDGER_AUTOGENERATE:-0}" == "1" && "$digest" == sha256:* ]]; then
    match=$(autogenerate_entry "$svc" "$image_path" "$digest" || true)
  fi

  if [[ -z "$match" ]]; then
    echo "  [SKIP] $svc digest=$digest — no ledger entry yet (CI hasn't generated one; LEDGER_AUTOGENERATE=1 derives it from GHCR tags)"
    continue
  fi

  # Verify the entry is THIS artifact: service AND digest (when the target has
  # one) must match — evidence must never land on another build's entry
  # (Codex 01a09219 P1).
  ledger_svc=$(jq -r '.service' "$match")
  if [[ "$ledger_svc" != "$svc" ]]; then
    echo "  [WARN] ledger $match has service='$ledger_svc' but render service='$svc' — skipping"
    continue
  fi
  ledger_digest=$(jq -r '.image.digest // empty' "$match")
  if [[ "$digest" == sha256:* && "$ledger_digest" != "$digest" ]]; then
    echo "  [WARN] ledger $match has digest='$ledger_digest' but target digest='$digest' — skipping (different artifact)"
    continue
  fi

  # Check if already verified for this env
  already_verified=$(jq -r ".promotion.$ENV.verified_at // empty" "$match")
  if [[ -n "$already_verified" ]]; then
    echo "  [SKIP] $svc already verified for $ENV at $already_verified"
    continue
  fi

  # --- Apply per-service D29 tier policy via shared helper -------------------
  # Policy: d29_up + d29_functional always strict GREEN; d29_zanzibar policy
  # depends on services.yaml jwt_validates (frontend SPA gets GREEN-or-AMBER;
  # backend default strict GREEN). Exit codes:
  #   0 = pass → mark verified
  #   1 = fail → skip with reason from helper stderr
  #   2 = setup error → log + skip
  set +e
  policy_msg=$(python3 "$POLICY_HELPER" check-tiers \
    --service "$svc" --report "$REPORT" --repo-root "$REPO_ROOT" 2>&1 >/dev/null)
  policy_exit=$?
  set -e
  if [[ "$policy_exit" != "0" ]]; then
    echo "  [SKIP] $svc policy reject (exit=$policy_exit): $policy_msg"
    continue
  fi
  echo "  [POLICY] $svc passed: $policy_msg"

  echo "  [MARK] $svc → $match (env=$ENV)"

  # Patch the ledger entry with smoke evidence
  python3 <<PYEOF
import json
from pathlib import Path

ledger_path = Path("$match")
report_path = Path("$REPORT")

ledger = json.loads(ledger_path.read_text())
report = json.loads(report_path.read_text())

# Update promotion.<env> block
env_block = ledger['promotion']['$ENV']
env_block['smoke_evidence'] = report['tiers']
env_block['verified_at'] = report['timestamp']

# Audit
ledger['audit']['last_updated_at'] = report['timestamp']

ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
print(f"    updated {ledger_path}")
PYEOF

  UPDATED_FILES+=("$match")
done <<< "$RENDERED"

if [[ ${#UPDATED_FILES[@]} -eq 0 ]]; then
  echo "[ledger-mark-verified] no ledger entries updated (no matches or all already verified)"
  exit 0
fi

echo
echo "[ledger-mark-verified] ${#UPDATED_FILES[@]} ledger entries updated"
for f in "${UPDATED_FILES[@]}"; do
  echo "  - $f"
done

# Commit + push + open PR
if [[ "${LEDGER_DRY_RUN:-0}" == "1" ]]; then
  echo "[ledger-mark-verified] LEDGER_DRY_RUN=1 — skipping git push + PR"
  exit 0
fi

git checkout -b "$BRANCH" 2>&1 | tail -2
for f in "${UPDATED_FILES[@]}"; do
  git add "$f"
done

git commit -m "auto: mark $ENV-verified — D29 smoke GREEN at $TS

Smoke report: $REPORT
Updated ledger entries:
$(printf '  - %s\n' "${UPDATED_FILES[@]}")

🤖 Auto-generated by ledger-mark-verified.sh (Codex P0 #2 / Sprint A Item 3)
" 2>&1 | tail -3

git push origin "$BRANCH" 2>&1 | tail -3

# Open PR via gh
gh pr create --repo "$GH_REPO" \
  --base main \
  --head "$BRANCH" \
  --title "auto(ledger): $ENV-verified after D29 smoke GREEN ($TS)" \
  --body "Auto-generated by smoke gate after D29 GREEN on **$ENV** cluster at $TS.

## Smoke evidence

\`\`\`
$(jq -c '.tiers' "$REPORT")
\`\`\`

## Ledger entries updated

$(printf -- '- %s\n' "${UPDATED_FILES[@]}")

## Auto-merge

This PR is safe to auto-merge after CI ledger-validate gate passes — content
is generated, schema-validated, and represents observable cluster state.

## Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [x] none of the above

Ledger evidence update only — patches release-candidates/<repo>/<sha>.json
with observed D29 smoke evidence; no cluster mutation, no credential I/O.

## Cross-AI

Automation source: scripts/promotion/ledger-mark-verified.sh
Cross-AI exempt reason: Machine-generated D29-evidence ledger PR; no AI peer-review claim is made (issue 827 automation-PR governance contract).
Automation evidence: D29 smoke report $REPORT (GREEN at $TS)
" \
  --label "auto-promotion,smoke-verified,env:$ENV" 2>&1 || echo "[WARN] PR creation failed (may already exist or auth missing)"

echo "[ledger-mark-verified] DONE"
