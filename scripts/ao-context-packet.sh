#!/usr/bin/env bash
#
# scripts/ao-context-packet.sh
#
# Render an ao-kernel *governed context packet* from this repo's .md-managed
# context. The bundled default mapping scans AGENTS.md,
# docs/context-priority-rules.md, docs/adr/[0-9]*.md and
# docs/state/current-state.md (extend with --mapping for more, e.g.
# decisions/*), then renders a packet for any AI agent (Claude / Codex / Mavis).
#
# This is the CONTEXT-management complement to host-compose/ao-gate (which runs
# the AO *runtime* gate services). It does NOT touch the cluster, secrets, or
# the repo working tree: the repo is scanned read-only and the governed store
# lives in an ephemeral workspace that is deleted on exit.
#
# Why: this repo carries thousands of .md files. ao-kernel ingests them into a
# confidence + freshness + provenance + tier governed store, then renders a
# SHORT, fail-closed packet (fresh + high-confidence only, provenance-tagged,
# secrets skipped, unverified "done" excluded) — instead of dumping raw .md
# into an agent's context window.
#
# Usage:
#   make context-packet
#   scripts/ao-context-packet.sh [--max-items N] [--min-conf F] [--include-doc-claims]
#
# Env:
#   AO_KERNEL_VERSION   pinned ao-kernel release (default: 4.3.0)
#   AO_CONTEXT_PROFILE  context profile label (default: TASK_EXECUTION)
#
# Requires: python3 (>= 3.11) with venv + network access to PyPI.

set -euo pipefail

AO_KERNEL_VERSION="${AO_KERNEL_VERSION:-4.3.0}"
AO_CONTEXT_PROFILE="${AO_CONTEXT_PROFILE:-TASK_EXECUTION}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
	echo "error: python3 not found (need >= 3.11)" >&2
	exit 1
fi

workspace="$(mktemp -d "${TMPDIR:-/tmp}/ao-context-XXXXXX")"
cleanup() { rm -rf "${workspace}"; }
trap cleanup EXIT

# Isolated venv so the host Python environment is untouched. PYTHONPATH is
# cleared for the ao-kernel calls so the pinned wheel in this venv is always
# the one that runs (never a stray source checkout on PYTHONPATH).
#
# NOTE: this is NOT a sandbox. `pip install` (and ao-kernel itself) run real
# Python from PyPI under the caller's env/file/network privileges — only the
# ao-kernel version is pinned, not the supply chain. Run from a trusted shell;
# do NOT export cluster/Vault/cloud secrets into this process's environment.
python3 -m venv "${workspace}/venv"
"${workspace}/venv/bin/python" -m pip install --quiet "ao-kernel==${AO_KERNEL_VERSION}"

ao() { env -u PYTHONPATH "${workspace}/venv/bin/ao-kernel" "$@"; }

( cd "${workspace}" && ao init >/dev/null )

echo "==> ao-kernel ${AO_KERNEL_VERSION}: ingesting ${repo_root} (read-only) ..." >&2
ao context ingest --root "${workspace}" --repo "${repo_root}" --output json >&2

echo "==> rendering governed context packet (profile=${AO_CONTEXT_PROFILE}) ..." >&2
ao context packet \
	--root "${workspace}" \
	--repo "${repo_root}" \
	--profile "${AO_CONTEXT_PROFILE}" \
	"$@"
