#!/usr/bin/env bash
# Faz 22.5 M2 — domain-FREE test cert generator.
#
# Mints a throwaway test CA + machine certs that carry the EXACT fields the
# backend MachineCertExtractor requires (EKU clientAuth + SAN
# URI:adcomputer:{lowercase-guid}). This stands in for AD CS so the M2
# auto-enroll flow can be exercised LOCALLY with no Active Directory / no
# Certificate Services / no prod DNS. ONLY production go-live needs the real
# AD CS PKI; acceptance testing does not.
#
# NB: macOS LibreSSL `openssl verify` rejects the `adcomputer:` URI scheme
# (error 53 "invalid name syntax"). That is a CLI-parser quirk ONLY — the Java
# backend reads the SAN via getSubjectAlternativeNames() (GeneralName type 6 =
# URI) and parses `URI:adcomputer:{guid}` correctly. In forward-header mode the
# backend does NOT chain-validate at all (that is the gateway's job), so the
# test CA needs no real trust anchor for the forward-header path.
#
# Usage:  ./gen-test-certs.sh [OUT_DIR]      (default: ./certs)
set -euo pipefail
OUT="${1:-./certs}"
mkdir -p "$OUT"; cd "$OUT"
lc() { tr 'A-Z' 'a-z'; }
# Random GUIDs by default so each gen run is a FRESH device identity — the
# matrix stays re-runnable against a persistent DB (no stale already-enrolled).
GUID_A="${M2_GUID_A:-$(uuidgen | lc)}"
GUID_B="${M2_GUID_B:-$(uuidgen | lc)}"

# --- test CA ---
openssl req -x509 -newkey rsa:2048 -nodes -keyout testca.key -out testca.crt \
  -days 3650 -subj "/CN=Faz22 M2 Test CA" 2>/dev/null

mint() { # name CN ext-body validity-days
  local name="$1" cn="$2" ext="$3" days="${4:-14}"
  printf '[v3]\n%s\n' "$ext" > "$name.cnf"
  openssl req -new -newkey rsa:2048 -nodes -keyout "$name.key" -subj "/CN=$cn" -out "$name.csr" 2>/dev/null
  openssl x509 -req -in "$name.csr" -CA testca.crt -CAkey testca.key -CAcreateserial \
    -days "$days" -extfile "$name.cnf" -extensions v3 -out "$name.crt" 2>/dev/null
  echo "  minted $name.crt ($cn)"
}

echo "Generating test certs in $OUT:"
# POSITIVE: clientAuth + adcomputer SAN  -> 201 enrolled
mint dev   WIN11-TESTPC   "keyUsage=digitalSignature
extendedKeyUsage=clientAuth
subjectAltName=URI:adcomputer:$GUID_A"
# POSITIVE-B (different GUID, same fingerprint at request time -> 409)
mint devb  WIN11-TESTPC-B "keyUsage=digitalSignature
extendedKeyUsage=clientAuth
subjectAltName=URI:adcomputer:$GUID_B"
# NEGATIVE: no clientAuth EKU  -> 401 CERT_EKU_MISSING_CLIENT_AUTH
mint noeku WIN11-NOEKU    "keyUsage=digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=URI:adcomputer:$GUID_A"
# NEGATIVE: clientAuth but no adcomputer SAN  -> 401 CERT_SAN_URI_MISSING
mint nosan WIN11-NOSAN    "keyUsage=digitalSignature
extendedKeyUsage=clientAuth"

echo "Done. PEMs: dev.crt (positive), devb.crt (positive/conflict), noeku.crt, nosan.crt"
