#!/usr/bin/env bash
# Faz 35 ES-311 — Charter PDF Export
#
# Usage: docs/faz-35-signatures/templates/pdf-export.sh <role-file>
#
# Requires pandoc + xelatex (or wkhtmltopdf): brew install pandoc basictex
#
# Example:
#   ./pdf-export.sh charters/01-legal-owner.md
#   → Output: charters/01-legal-owner.pdf
#
# Owner PDF'i imzalayanına gönderir, ıslak imza + taranıp geri gelir, agent
# signed-pdfs/<role>-<name>.pdf olarak commit'ler.

set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <role-charter.md>"
  echo "Example: $0 charters/01-legal-owner.md"
  exit 1
fi

INPUT="$1"
if [ ! -f "$INPUT" ]; then
  echo "Error: $INPUT not found"
  exit 1
fi

OUTPUT="${INPUT%.md}.pdf"

pandoc "$INPUT" \
  --from markdown \
  --to pdf \
  --pdf-engine=xelatex \
  -V geometry:margin=2cm \
  -V mainfont="Georgia" \
  -V sansfont="Arial" \
  -V monofont="Menlo" \
  -V documentclass=article \
  -V colorlinks=true \
  --toc \
  --metadata title="Faz 35 ES-311 Charter" \
  --metadata date="2026-07-22" \
  -o "$OUTPUT"

echo "PDF exported: $OUTPUT"
echo "Send to signer, receive back with ıslak imza + tarama, commit as:"
echo "  docs/faz-35-signatures/signed-pdfs/${INPUT##*/}-<signer-name>.pdf"

# SHA-256 hash (tracker için)
if command -v sha256sum >/dev/null; then
  echo "SHA-256: $(sha256sum "$OUTPUT" | cut -d' ' -f1)"
else
  echo "SHA-256: $(shasum -a 256 "$OUTPUT" | cut -d' ' -f1)"
fi
