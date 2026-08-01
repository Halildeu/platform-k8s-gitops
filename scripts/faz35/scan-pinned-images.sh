#!/bin/bash
# Faz 35 ES-306 (#2665) — scan every image the TEST activation pins.
#
# Reads the digests from the rendered activation rather than a hand-kept list: a list
# would drift, and the whole point is to scan what the cluster will actually run. Any
# Critical or High fails the run; the exceptions live in an explicit allowlist below,
# each with a reason and each re-examined whenever this gate is touched.
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ACTIVATION="$REPO_ROOT/kustomize/overlays/test/activation/etik-speak"
OUT="${SCAN_OUT_DIR:-/tmp/faz35-scan}"
mkdir -p "$OUT"

for command_name in syft grype kustomize jq; do
  command -v "$command_name" >/dev/null || { echo "FATAL: missing $command_name" >&2; exit 1; }
done

# Accepted findings. An entry means: measured, understood, and judged not to put the
# reporter at risk in THIS product — never "we could not fix it so we stopped looking".
# Each line names the component and why the code path is unreachable or the risk bounded.
#
#   libtiff (CVE-2023-52356, CVE-2026-4775) — present only as a base package of the
#   nginx image, which serves static files and never decodes an image. The product's
#   image parsing happens in the ethics-service JVM, not here, and has its own gates.
#
#   sqlite (CVE-2026-11822, CVE-2026-11824) — carried by the eclipse-temurin JRE base.
#   No fix exists in any distribution as of 2026-08-02, so there is nothing to bump to.
#   ethics-service speaks to PostgreSQL and never opens an SQLite database; the library
#   is present as a transitive base package and no code path in this product loads it.
#   Re-check when a fixed sqlite lands: this is an acceptance with an expiry, not a
#   permanent exemption.
ACCEPTED_IDS="CVE-2023-52356 CVE-2026-4775 CVE-2026-11822 CVE-2026-11824"

# Quarantined images: pinned in the repository but deliberately scaled to zero because
# the scan refused them. Listing one here is not an exemption — it is a RECORD, and the
# gate still fails if a quarantined image ever gets a replica. That inversion is the
# point: a zero-replica pin carrying 80 Criticals is not "not running", it is a loaded
# gun the next person may pick up without knowing.
#
#   h2non/imaginary — HEIC converter, 2020 build, 80 Critical / 386 High including
#   libwebp CVE-2023-4863. Lane closed 2026-08-01; replacement tracked in #3335.
QUARANTINED_IMAGES="h2non/imaginary"

is_quarantined() {
  local image=$1
  for quarantined in $QUARANTINED_IMAGES; do
    case "$image" in *"$quarantined"*) return 0 ;; esac
  done
  return 1
}

echo "Reading pinned images and their replica counts from the rendered TEST activation"
rendered=$(kustomize build "$ACTIVATION")

# image → scheduled? The question the gate must ask is not "is this pinned" but "will
# the cluster run it", and those two diverge exactly where the risk hides. Parsed as YAML
# rather than by line matching: a Deployment with a sidecar carries two images, and a
# line-based reader keeps only the last one — which would let a sidecar slip through
# unscheduled-looking while the cluster runs it.
scheduled_images=$(printf '%s\n' "$rendered" | python3 -c '
import sys, yaml
seen = []
for doc in yaml.safe_load_all(sys.stdin):
    if not doc or doc.get("kind") != "Deployment":
        continue
    if doc.get("spec", {}).get("replicas") == 0:
        continue
    spec = doc.get("spec", {}).get("template", {}).get("spec", {})
    for container in (spec.get("containers") or []) + (spec.get("initContainers") or []):
        image = container.get("image", "")
        if "@sha256:" in image:
            seen.append(image)
print("\n".join(sorted(set(seen))))
')

all_images=$(printf '%s\n' "$rendered" \
  | grep -oE 'image: [^ ]+@sha256:[0-9a-f]{64}' | sed 's/^image: //' | sort -u)

[ -n "$all_images" ] || {
  echo "FATAL: no digest-pinned images found — the gate proved nothing" >&2
  exit 1
}

# A quarantined image that gained a replica is the failure this list exists to catch.
while read -r image; do
  [ -n "$image" ] || continue
  if is_quarantined "$image"; then
    echo "FATAL: a quarantined image is scheduled to run: ${image%%@*}" >&2
    echo "       It was scaled to zero because the scan refused it. Replace it (#3335)" >&2
    echo "       or remove it from QUARANTINED_IMAGES only after it passes this gate." >&2
    exit 4
  fi
done <<<"$scheduled_images"

# read -a rather than mapfile: mapfile is bash 4+, and this script has to stay runnable
# on the macOS bash 3.2 where it gets debugged before it ever reaches the ubuntu runner.
images=()
while IFS= read -r line; do [ -n "$line" ] && images+=("$line"); done <<<"$all_images"
scheduled_count=$(printf '%s\n' "$scheduled_images" | grep -c . || true)
echo "Found ${#images[@]} pinned images, ${scheduled_count:-0} of them scheduled"

total_blocking=0
summary="[]"

for image in "${images[@]}"; do
  short=$(printf '%s' "$image" | sed 's|.*/||; s|@sha256:|-|; s|\(.\{28\}\).*|\1|')
  echo "--- $image"
  syft -q -o spdx-json "$image" > "$OUT/sbom-$short.json" || {
    echo "FATAL: SBOM generation failed for $image — unknown is not clean" >&2
    exit 2
  }
  grype -q "sbom:$OUT/sbom-$short.json" -o json > "$OUT/vuln-$short.json" || {
    echo "FATAL: vulnerability scan failed for $image — unknown is not clean" >&2
    exit 2
  }

  blocking=$(jq --argjson accepted "$(printf '%s\n' $ACCEPTED_IDS | jq -R . | jq -s .)" '
    [ .matches[]
      | select(.vulnerability.severity == "Critical" or .vulnerability.severity == "High")
      | select(([.vulnerability.id] | inside($accepted)) | not)
    ]' "$OUT/vuln-$short.json")
  count=$(printf '%s' "$blocking" | jq 'length')
  crit=$(printf '%s' "$blocking" | jq '[.[] | select(.vulnerability.severity == "Critical")] | length')

  echo "    Critical/High (kabul edilmeyenler): $count (bunlarin $crit tanesi Critical)"
  if [ "$count" -gt 0 ]; then
    # Sliced inside jq rather than piped through `head`: head closes the pipe after 25
    # lines, jq takes SIGPIPE, and `set -o pipefail` turns that into exit 141 — a gate
    # that fails for its own plumbing rather than for a finding. Caught on the first
    # real run against a 465-finding image.
    printf '%s' "$blocking" | jq -r '.[:25][] | "      \(.vulnerability.severity) \(.vulnerability.id) \(.artifact.name) \(.artifact.version)"'
    # A plain `[ ... ] && echo` here would be the last command of this branch, and under
    # `set -e` a false test would abort the whole run when there is nothing to report.
    if [ "$count" -gt 25 ]; then
      echo "      ... ve $((count - 25)) bulgu daha (tam liste: $OUT/vuln-$short.json)"
    fi
    if is_quarantined "$image"; then
      # Recorded, not counted: this image is already refused and scaled to zero, and
      # the scheduled-check above is what keeps that true. Counting it here would make
      # the gate permanently red, and a permanently red gate is a gate nobody reads.
      echo "    (karantinada — #3335 ile degistirilecek; 0 replika oldugu yukarida dogrulandi)"
    else
      total_blocking=$((total_blocking + count))
    fi
  fi

  summary=$(jq -nc --argjson acc "$summary" --arg img "$image" \
    --argjson n "$count" --argjson c "$crit" \
    --argjson q "$(is_quarantined "$image" && echo true || echo false)" \
    '$acc + [{image:$img, blocking:$n, critical:$c, quarantined:$q}]')
done

printf '%s\n' "$summary" | jq . > "$OUT/summary.json"

if [ "$total_blocking" -gt 0 ]; then
  cat >&2 <<'REASON'

FATAL: pinned images carry unaccepted Critical/High findings.

This gate exists because of what happened on 2026-08-01: a converter image was chosen,
deployed, and only afterwards scanned by hand — it was a 2020 build with 80 Criticals,
including an actively-exploited RCE in the very library that parses attacker-supplied
input. Container isolation was strong and still did not make that acceptable.

Two ways forward, both honest: bump to a base/version that carries the fix, or add the
finding to ACCEPTED_IDS in this script WITH the reason its code path cannot be reached
in this product. There is no third way that leaves the pin as it is.
REASON
  exit 3
fi

echo "All ${#images[@]} pinned images clear of unaccepted Critical/High findings"
