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

expect_failure() {
  local label="$1" expected="$2"
  shift 2

  set +e
  "$GENERATOR" "$@" >"$tmp_dir/$label.out" 2>"$tmp_dir/$label.err"
  rc="$?"
  set -e
  if [ "$rc" = "0" ]; then
    echo "expected $label to fail" >&2
    exit 1
  fi
  grep -q "$expected" "$tmp_dir/$label.err"
}

cat >"$audit_file" <<'EOF'
F22_6_AUDIT_SCOPE=remote-ops-autonomous-completion
GATE_22_6_1_OPERATION_CATALOG=pass state=CLOSED issue=Halildeu/platform-backend#701
GATE_B1_4_HARDWARE_ATTESTATION=blocked state=OPEN expected=CLOSED-or-bounded-risk-accepted issue=Halildeu/platform-backend#548 reason=missing-acceptance-marker
GATE_VIEW_ONLY_SCREEN_SHARE=blocked state=OPEN expected=CLOSED-with-view-only-acceptance issue=Halildeu/platform-k8s-gitops#1580 reason=missing-acceptance-marker
REMOTE_BRIDGE_LIVE=pass mode=local-kubectl expected_digest=sha256:6b12276cea912345dcfbcf2e5e920931de813b8aa483b6b2351c75e4b5331a9c
RELEASE_LINEAGE_WAIVER=blocked ref=Halildeu/platform-k8s-gitops#1901 reason=marker,scope,release_tag,artifact_host_digest,owner_approved_by,accepted_findings:GITHUB_RELEASE_IMMUTABLE,accepted_findings:GITHUB_RELEASE_DENSE_TRAIN,forbidden_claims:5-device,forbidden_claims:50-device,forbidden_claims:800-device,forbidden_claims:production,forbidden_claims:broad-rollout,approved_at,expires_at
AGENT_RELEASE_TRAIN=needs_hygiene latest=v0.2.28 recent_series=v0.2 recent_series_count=20 isImmutable=false reason=rapid-release-train-or-mutable-release-requires-lineage-waiver
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

expect_failure \
  "missing-file" \
  "audit-file does not exist" \
  --audit-file "$tmp_dir/missing.txt" \
  --output-dir "$out_dir/missing"

expect_failure \
  "missing-arg" \
  "audit-file is required" \
  --output-dir "$out_dir/missing-arg"

expect_failure \
  "bad-prefix" \
  "prefix must contain only" \
  --audit-file "$audit_file" \
  --output-dir "$out_dir/bad-prefix" \
  --prefix "bad prefix"

expect_failure \
  "bad-generated-at" \
  "generated-at must be UTC ISO8601" \
  --audit-file "$audit_file" \
  --output-dir "$out_dir/bad-generated-at" \
  --generated-at "2026-06-23 11:06:47"

pass_audit="$tmp_dir/faz22-6-completion-audit-pass.txt"
pass_out_dir="$tmp_dir/pass-out"
cat >"$pass_audit" <<'EOF'
REMOTE_BRIDGE_LIVE=pass mode=local-kubectl expected_digest=sha256:6b12276cea912345dcfbcf2e5e920931de813b8aa483b6b2351c75e4b5331a9c
GATE_B1_4_HARDWARE_ATTESTATION=bounded_pilot_risk_accepted state=OPEN issue=Halildeu/platform-backend#548 owner=example expires_at=2026-07-23
GATE_VIEW_ONLY_SCREEN_SHARE=pass state=CLOSED issue=Halildeu/platform-k8s-gitops#1580 evidence_package_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
RELEASE_LINEAGE_WAIVER=bounded_pilot_pass ref=Halildeu/platform-k8s-gitops#1901 owner=example expires_at=2026-07-23
AGENT_RELEASE_TRAIN=surprising-state latest=v0.2.28
F22_6_COMPLETION=pass
F22_6_NEXT_REQUIRED=
EOF

"$GENERATOR" \
  --audit-file "$pass_audit" \
  --output-dir "$pass_out_dir" \
  --prefix "custom.package" \
  --generated-at 2026-06-23T12:00:00Z \
  >"$tmp_dir/pass-generator.out"

pass_json="$pass_out_dir/custom.package.json"
pass_markdown="$pass_out_dir/custom.package.md"
grep -q "^json=$pass_json$" "$tmp_dir/pass-generator.out"
grep -q "^markdown=$pass_markdown$" "$tmp_dir/pass-generator.out"

jq -e '
  .completion.status == "pass"
  and .completion.remote_bridge.status == "pass"
  and (.completion.next_required | length) == 0
  and (.decisions[] | select(.id == "b1_4_hardware_attestation").current_status) == "bounded_pilot_risk_accepted"
  and (.decisions[] | select(.id == "view_only_screen_share").current_status) == "pass"
  and (.decisions[] | select(.id == "release_lineage").current_status) == "bounded_pilot_pass"
  and (.decisions[] | select(.id == "release_lineage").agent_release_train_status) == "unparsed"
' "$pass_json" >/dev/null

grep -Fq "Completion status: \`pass\`" "$pass_markdown"

echo "completion-decision-package-ok"
