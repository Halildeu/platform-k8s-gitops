#!/bin/sh
# redis-streams ACL bootstrap — gitops#1457 (Codex 019ebb70 REVISE absorb)
#
# Persistence YOK (appendonly no + save "") → runtime `ACL SETUSER` restart'ta
# uçar; bu yüzden aclfile ŞART. aclfile'ı git'e plaintext koymak yerine
# container start'ta .env parolalarından tmpfs'e (/run/redis, umask 077)
# ÜRETİLİR — secret artifact diske kalıcı düşmez (Codex S2).
#
# Default user: requirepass YERİNE aclfile'da tek otorite (Codex S1 —
# requirepass + aclfile çift-otorite YASAK). audio-gateway eski
# `AUTH <REDIS_PASSWORD>` ile default user olarak bağlanır (davranış değişmez).
# exporter: ayrı read-only `exporter` user (REDIS_USER=exporter), keyspace
# yalnız audio:chunks:p00..p31, -@all + explicit read-class subcommand.
set -eu

: "${REDIS_PASSWORD:?REDIS_PASSWORD .env'de zorunlu}"
: "${EXPORTER_PASSWORD:?EXPORTER_PASSWORD .env'de zorunlu}"

ACL_DIR=/run/redis
ACL_FILE="${ACL_DIR}/users.acl"

umask 077
mkdir -p "${ACL_DIR}"

# Keyspace: p00..p31 iki pattern (Codex S4 — ~* DEĞİL, least-privilege).
# Komut seti: -@all + explicit (Codex S3 — +@read YASAK payload yüzeyi açar;
# +xrange/+scan ÇIKARILDI: check-single-streams XINFO/XLEN kullanır, payload
# okumaz; exporter NOPERM verirse kanıtla eklenir). +@dangerous YOK.
cat > "${ACL_FILE}" <<EOF
user default reset on >${REDIS_PASSWORD} ~* &* +@all
user exporter reset on >${EXPORTER_PASSWORD} ~audio:chunks:p[0-2][0-9] ~audio:chunks:p3[0-1] resetchannels -@all +@connection +info +config|get +client|list +client|info +client|getname +command|docs +command|count +command|info +cluster|info +dbsize +type +xlen +xinfo|stream +xinfo|groups +xinfo|consumers +slowlog|len +slowlog|get +latency|latest +latency|histogram +memory|stats
EOF

exec redis-server \
  --appendonly no \
  --save "" \
  --maxmemory 512mb \
  --maxmemory-policy noeviction \
  --aclfile "${ACL_FILE}"
