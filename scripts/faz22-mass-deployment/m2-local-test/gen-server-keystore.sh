#!/usr/bin/env bash
# Faz 22.5 Step-2 — build the backend mTLS server keystore + CA truststore for
# the domain-free PASSTHROUGH test (ADR-0029 #1501).
#
# From the test CA produced by gen-test-certs.sh, mints a server cert
# (CN=localhost, SAN DNS:localhost + IP:127.0.0.1 so the client verifies the
# hostname — no `-k`) into a PKCS12 keystore, and a PKCS12 truststore holding
# ONLY the test CA (dedicated issuing CA — NOT a broad root). These feed the
# backend's endpoint-admin.mtls.passthrough.{key-store,trust-store}.
#
# Usage:  ./gen-server-keystore.sh [CERTS_DIR] [STORE_PASSWORD]
#   CERTS_DIR       dir containing testca.crt/testca.key (default ./certs)
#   STORE_PASSWORD  keystore/truststore password (default: changeit)
set -euo pipefail
CERTS="${1:-./certs}"
PW="${2:-changeit}"
cd "$CERTS"
[ -f testca.crt ] && [ -f testca.key ] || { echo "ERROR: run gen-test-certs.sh first ($CERTS/testca.* missing)"; exit 1; }
command -v keytool >/dev/null || { echo "ERROR: keytool (JDK) not found on PATH"; exit 1; }

cat > server.cnf <<'EOF'
[v3]
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,IP:127.0.0.1
EOF
openssl req -new -newkey rsa:2048 -nodes -keyout server.key -subj "/CN=localhost" -out server.csr 2>/dev/null
openssl x509 -req -in server.csr -CA testca.crt -CAkey testca.key -CAcreateserial -days 30 \
  -extfile server.cnf -extensions v3 -out server.crt 2>/dev/null
# PKCS12 server keystore (cert + key + CA chain)
openssl pkcs12 -export -in server.crt -inkey server.key -certfile testca.crt -name server \
  -out server-keystore.p12 -passout "pass:$PW" 2>/dev/null
# PKCS12 truststore: ONLY the test CA
rm -f truststore.p12
keytool -import -noprompt -trustcacerts -alias testca -file testca.crt \
  -keystore truststore.p12 -storetype PKCS12 -storepass "$PW" 2>/dev/null
echo "Built in $CERTS: server-keystore.p12 + truststore.p12 (password: $PW)"
echo "Backend start (passthrough), from <platform-backend>/endpoint-admin-service:"
cat <<EOF
  ...mvn spring-boot:run -Dspring-boot.run.arguments="\\
    --endpoint-admin.mtls.forward-header.enabled=false \\
    --endpoint-admin.mtls.passthrough.enabled=true \\
    --endpoint-admin.mtls.passthrough.port=8443 \\
    --endpoint-admin.mtls.passthrough.fixed-tenant-id=00000000-0000-0000-0000-000000000001 \\
    --endpoint-admin.mtls.passthrough.key-store=$PWD/server-keystore.p12 \\
    --endpoint-admin.mtls.passthrough.key-store-password=$PW \\
    --endpoint-admin.mtls.passthrough.trust-store=$PWD/truststore.p12 \\
    --endpoint-admin.mtls.passthrough.trust-store-password=$PW"
EOF
