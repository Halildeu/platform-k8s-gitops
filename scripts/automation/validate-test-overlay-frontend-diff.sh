#!/usr/bin/env bash
set -euo pipefail

KUSTOMIZATION="${1:-kustomize/overlays/test/kustomization.yaml}"

changed_files=$(git diff --name-only)
if [[ "$changed_files" != "$KUSTOMIZATION" ]]; then
  echo "frontend overlay diff may change only ${KUSTOMIZATION}; got: ${changed_files//$'\n'/, }" >&2
  exit 1
fi

offending=$(git diff -U0 -- "$KUSTOMIZATION" \
  | grep -E '^[-+]' \
  | grep -vE '^(\+\+\+|---) ' \
  | grep -vE '^[-+][[:space:]]+#[[:space:]]+sourceRevision: [a-f0-9]{40}$' \
  | grep -vE '^[-+][[:space:]]+newTag: sha-[a-f0-9]{7}$' \
  | grep -vE '^[-+][[:space:]]+digest: sha256:[a-f0-9]{64}$' || true)
if [[ -n "$offending" ]]; then
  echo "frontend overlay diff contains fields outside sourceRevision/newTag/digest:" >&2
  printf '%s\n' "$offending" >&2
  exit 1
fi

added_tag=$(git diff -U0 -- "$KUSTOMIZATION" | grep -cE '^\+[[:space:]]+newTag: sha-[a-f0-9]{7}$' || true)
deleted_tag=$(git diff -U0 -- "$KUSTOMIZATION" | grep -cE '^-[[:space:]]+newTag: sha-[a-f0-9]{7}$' || true)
added_source=$(git diff -U0 -- "$KUSTOMIZATION" | grep -cE '^\+[[:space:]]+#[[:space:]]+sourceRevision: [a-f0-9]{40}$' || true)
deleted_source=$(git diff -U0 -- "$KUSTOMIZATION" | grep -cE '^-[[:space:]]+#[[:space:]]+sourceRevision: [a-f0-9]{40}$' || true)
added_digest=$(git diff -U0 -- "$KUSTOMIZATION" | grep -cE '^\+[[:space:]]+digest: sha256:[a-f0-9]{64}$' || true)
deleted_digest=$(git diff -U0 -- "$KUSTOMIZATION" | grep -cE '^-[[:space:]]+digest: sha256:[a-f0-9]{64}$' || true)

if [[ "$added_source" -ne 1 || "$deleted_source" -gt 1 \
  || "$added_tag" -ne 1 || "$deleted_tag" -gt 1 \
  || "$added_digest" -ne 1 || "$deleted_digest" -ne 1 ]]; then
  echo "unexpected frontend pin diff counts: source +${added_source}/-${deleted_source}, tag +${added_tag}/-${deleted_tag}, digest +${added_digest}/-${deleted_digest}" >&2
  exit 1
fi

echo "frontend overlay diff guard PASS"
