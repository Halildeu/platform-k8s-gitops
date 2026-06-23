#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GENERATOR="$ROOT/scripts/faz22-remote-ops/faz22-6-completion-decision-package.sh"

tmp_root="${TMPDIR:-$ROOT/.codex-tmp}"
mkdir -p "$tmp_root"
tmp_dir="$(mktemp -d "$tmp_root/completion-decision-package.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

audit_file="$tmp_dir/faz22-6-completion-audit.txt"
out_dir="$tmp_dir/out"

cat >"$audit_file" <<'EOF'
F22_6_AUDIT_SCOPE=remote-ops-autonomous-completion
GATE_22_6_1_OPERATION_CATALOG=pass state=CLOSED issue=Halildeu/platform-backend#701
GATE_B1_4_HARDWARE_ATTESTATION=blocked state=OPEN expected=CLOSED-or-bounded-risk-accepted issue=Halildeu/platform-backend#548 reason=missing-acceptance-marker
GATE_VIEW_ONLY_SCREEN_SHARE=blocked state=OPEN expected=CLOSED-with-view-only-acceptance issue=Halildeu/platform-k8s-gitops#1580 reason=missing-acceptance-marker
REMOTE_BRIDGE_LIVE=pass mode=local-kubectl expected_digest=sha256:6b12276cea912345dcfbcf2e5e920931de813b8aa483b6b2351c75e4b5331a9c
RELEASE_LINEAGE_WAIVER=blocked ref=Halildeu/platform-k8s-gitops#1901 reason=marker,scope,release_tag,artifact_host_digest,owner_approved_by,accepted_findings:GITHUB_RELEASE_IMMUTABLE,accepted_findings:GITHUB_RELEASE_DENSE_TRAIN,forbidden_claims:5-device,forbidden_claims:50-device,forbidden_claims:800-device,forbidden_claims:production,forbidden_claims:broad-rollout,approved_at,expires_at
AGENT_RELEASE_TRAIN=needs_hygiene latest=v0.2.28 recent_v0_2_count=20 isImmutable=false reason=rapid-v0.2-train-or-mutable-release-requires-lineage-waiver
F22_6_COMPLETION=blocked
F22_6_NEXT_REQUIRED=close-or-risk-accept-548-with-marker,close-1580-with-view-only-marker,fix-release-lineage-hygiene
EOF

output="$(
  "$GENERATOR" \
    --audit-file "$audit_file" \
    --output-dir "$out_dir" \
    --generated-at 2026-06-23T11:06:47Z
)"
printf '%s\n' "$output" | tee "$tmp_dir/generator.out"
grep -q "^json=$out_dir/faz22-6-completion-decision-package.json$" "$tmp_dir/generator.out"
grep -q "^markdown=$out_dir/faz22-6-completion-decision-package.md$" "$tmp_dir/generator.out"

json="$out_dir/faz22-6-completion-decision-package.json"
markdown="$out_dir/faz22-6-completion-decision-package.md"

jq -e '
  .schema_version == "faz22.6-completion-decision-package-v1"
  and .generated_at == "2026-06-23T11:06:47Z"
  and .completion.status == "blocked"
  and .completion.remote_bridge.status == "pass"
  and (.completion.next_required | length) == 3
  and (.decisions | length) == 3
  and (.decisions[] | select(.id == "b1_4_hardware_attestation").current_status) == "blocked"
  and (.decisions[] | select(.id == "view_only_screen_share").current_status) == "blocked"
  and (.decisions[] | select(.id == "release_lineage").current_status) == "blocked"
  and (.decisions[] | select(.id == "release_lineage").agent_release_train_status) == "needs_hygiene"
' "$json" >/dev/null

jq -e '
  any(.decisions[] | select(.id == "b1_4_hardware_attestation").acceptance_paths[].helper_command; contains("faz22-6-b1-4-acceptance-package.sh --mode risk"))
  and any(.decisions[] | select(.id == "view_only_screen_share").acceptance_paths[].helper_command; contains("faz22-6-view-only-evidence-package.sh"))
  and any(.decisions[] | select(.id == "release_lineage").acceptance_paths[].helper_command; contains("faz22-6-release-lineage-waiver-package.sh"))
' "$json" >/dev/null

grep -q '^# Faz 22.6 Completion Decision Package' "$markdown"
grep -q 'Halildeu/platform-backend#548' "$markdown"
grep -q 'Halildeu/platform-k8s-gitops#1580' "$markdown"
grep -q 'Halildeu/platform-k8s-gitops#1901' "$markdown"
grep -q 'does not approve risk' "$markdown"
grep -q 'faz22-6-b1-4-acceptance-package.sh --mode risk' "$markdown"
grep -q 'faz22-6-view-only-evidence-package.sh' "$markdown"
grep -q 'faz22-6-release-lineage-waiver-package.sh' "$markdown"

set +e
"$GENERATOR" \
  --audit-file "$tmp_dir/missing.txt" \
  --output-dir "$out_dir/missing" \
  >"$tmp_dir/missing.out" 2>"$tmp_dir/missing.err"
rc="$?"
set -e
if [ "$rc" = "0" ]; then
  echo "expected missing audit file to fail" >&2
  exit 1
fi
grep -q 'audit-file does not exist' "$tmp_dir/missing.err"

echo "completion-decision-package-ok"
