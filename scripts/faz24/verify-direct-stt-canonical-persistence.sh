#!/usr/bin/env bash
# verify-direct-stt-canonical-persistence.sh — Faz 24 direct-STT canonical
# persistence zincirinin uçtan uca regresyon guard'ı (gitops#2568).
#
# NE KANITLAR
#   audio-gateway'in yazdığı Redis akışındaki bir direct-STT sonucu,
#   transcript-service tarafından tüketilip meeting-service'e resolve
#   ettirilerek CANONICAL kayda (association + segment) yazılıyor mu.
#
# NEDEN VAR
#   2026-07-25'te zincir sessizce kırıktı: stream'de 1650 mesaj, consumer
#   group lag=0 — ama DLQ'da da 1650. Yani her mesaj okunup dead-letter'a
#   atılıyordu (reason=RESOLVE), çünkü stream tüketimi açıkken RESOLVER
#   kapalıydı (kaynak koddaki belgelenmiş fail-closed davranış).
#   "Consumer çalışıyor" ölçümü bunu YAKALAMAZDI; asıl soru sonucun canonical
#   kayda ULAŞIP ULAŞMADIĞI. Bu script tam onu sorar.
#
# NEDEN SENTETİK FIXTURE
#   Gerçek bir toplantıya test transkripti yazmak canonical veriyi kirletir.
#   Var olmayan bir meeting ise resolve'da 404 verir ve "resolver bozuk" ile
#   "meeting yok" ayrımı yapılamaz. Bu yüzden amaca özel, etiketli, ÇALIŞMA
#   SONUNDA SİLİNEN bir fixture kullanılır (standart entegrasyon-testi pratiği).
#
# KULLANIM
#   bash scripts/faz24/verify-direct-stt-canonical-persistence.sh            # test
#   SSH_HOST=aiserver bash scripts/faz24/verify-direct-stt-canonical-persistence.sh
#
# ÇIKIŞ KODU
#   0 = zincir sağlam · 1 = zincir kırık (canonical kayıt oluşmadı) · 2 = ön koşul yok
#
# GÜVENLİK
#   Secret/token hiçbir zaman ekrana basılmaz (yalnız uzunluk/varlık).
#   Gerçek ses veya gerçek transkript kullanılmaz; metin sabit sentetiktir.
set -uo pipefail

SSH_HOST="${SSH_HOST:-aiserver}"
CTX="${KUBE_CONTEXT:-k3d-test}"
NS="${NAMESPACE:-platform-test}"
PG="${PG_CONTAINER:-platform-pg-test}"
REDIS="${REDIS_CONTAINER:-platform-redis-streams-test}"

# Sabit, tanınabilir sentetik kimlikler — çakışma olmasın diye 2568 öneki.
MEETING_ID="2568c0de-0000-4000-8000-000000000001"
SESSION_ID="2568c0de-0000-4000-8000-000000000002"
TENANT_ID="2568c0de-0000-4000-8000-0000000000aa"
EXT_SESSION="SES-PROOF-2568-SYNTHETIC"

STREAM="transcript:direct-stt-results"
DLQ="${STREAM}:dlq"

log() { printf '%s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; }

remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST" "$@"; }

# --- Ön koşul: uzak host + araçlar --------------------------------------
if ! remote true 2>/dev/null; then
    fail "SSH_HOST='$SSH_HOST' erişilemiyor."
    exit 2
fi

# Tüm iş uzak tarafta tek oturumda koşar: kimlik bilgisi ağdan geçmez,
# ve fixture temizliği trap ile GARANTİ edilir (script yarıda kesilse de).
remote 'bash -s' <<EOSSH
set -uo pipefail

CTX="$CTX"; NS="$NS"; PG="$PG"; REDIS="$REDIS"
MEETING_ID="$MEETING_ID"; SESSION_ID="$SESSION_ID"
TENANT_ID="$TENANT_ID"; EXT_SESSION="$EXT_SESSION"
STREAM="$STREAM"; DLQ="$DLQ"

RC=0

cleanup() {
    # Fixture ve ürettiği canonical kayıtlar HER DURUMDA silinir.
    docker exec "\$PG" psql -U platform -d transcript -q -c \
      "DELETE FROM transcript_service.transcript_segments WHERE session_id IN
         (SELECT session_id FROM transcript_service.transcript_session_associations
          WHERE source_session_id='\$EXT_SESSION');
       DELETE FROM transcript_service.transcript_session_associations
         WHERE source_session_id='\$EXT_SESSION';" >/dev/null 2>&1 || true
    docker exec "\$PG" psql -U platform -d meeting -q -c \
      "DELETE FROM meeting_service.meeting_sessions WHERE id='\$SESSION_ID';
       DELETE FROM meeting_service.meetings WHERE id='\$MEETING_ID';" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# --- Redis parolası (ASLA basılmaz) -------------------------------------
PW=\$(kubectl --context "\$CTX" -n "\$NS" get secret transcript-service-secrets \
      -o jsonpath='{.data.TRANSCRIPT_REDIS_PASSWORD}' 2>/dev/null | base64 -d)
if [ -z "\${PW:-}" ]; then
    echo "FAIL: Redis parolası okunamadı (transcript-service-secrets)." >&2
    exit 2
fi
R() { docker exec -e RP="\$PW" "\$REDIS" sh -c "redis-cli -a \\"\\\$RP\\" --no-auth-warning \$1" 2>/dev/null; }

# --- Ön koşul: resolver açık mı ----------------------------------------
RESOLVER=\$(kubectl --context "\$CTX" -n "\$NS" exec deploy/transcript-service -- \
  sh -c 'echo \$TRANSCRIPT_MEETING_SESSION_RESOLVER_ENABLED' 2>/dev/null | tr -d '\r')
echo "  resolver_enabled=\${RESOLVER:-tanimsiz}"
if [ "\${RESOLVER:-false}" != "true" ]; then
    echo "FAIL: TRANSCRIPT_MEETING_SESSION_RESOLVER_ENABLED != true — zincir fail-closed DLQ'ya düşer." >&2
    exit 1
fi

# --- 1) Sentetik fixture ------------------------------------------------
docker exec "\$PG" psql -U platform -d meeting -q -c \
 "INSERT INTO meeting_service.meetings
    (id,tenant_id,title,status,organizer_subject,created_by_subject,last_updated_by_subject,created_at,updated_at,version)
  VALUES ('\$MEETING_ID','\$TENANT_ID','SYNTHETIC-PROOF-2568 (regression guard)','SCHEDULED',
          'persistence-guard','persistence-guard','persistence-guard',now(),now(),0)
  ON CONFLICT (id) DO NOTHING;
  INSERT INTO meeting_service.meeting_sessions
    (id,meeting_id,tenant_id,org_id,session_label,external_session_id,transcript_status,
     created_by_subject,last_updated_by_subject,created_at,updated_at,version)
  VALUES ('\$SESSION_ID','\$MEETING_ID','\$TENANT_ID','\$TENANT_ID','SYNTHETIC-PROOF-2568',
          '\$EXT_SESSION','PENDING','persistence-guard','persistence-guard',now(),now(),0)
  ON CONFLICT (id) DO NOTHING;" >/dev/null 2>&1

FIX=\$(docker exec "\$PG" psql -U platform -d meeting -t -A -c \
  "select count(*) from meeting_service.meeting_sessions where id='\$SESSION_ID';" 2>/dev/null | tr -d '[:space:]')
echo "  fixture_session=\${FIX:-0}"
[ "\${FIX:-0}" = "1" ] || { echo "FAIL: fixture kurulamadı." >&2; exit 2; }

# --- 2) Sonuç mesajını akışa yaz ---------------------------------------
BEFORE_DLQ=\$(R "XLEN \$DLQ" | tr -d '[:space:]')
NOW=\$(date +%s%3N)
SHA=\$(printf 'persistence-guard' | sha256sum | cut -d' ' -f1)

R "XADD \$STREAM '*' \
 schemaVersion audioGateway.directSttTranscriptResult.v1 eventType DIRECT_STT_TRANSCRIPT_RESULT \
 sessionId \$EXT_SESSION tenantId \$TENANT_ID userId persistence-guard meetingId \$MEETING_ID \
 deviceId guard-device chunkSeq 1 chunkStartedAtMs \$NOW windowSeq 1 firstChunkSeq 1 lastChunkSeq 1 \
 windowStartedAtMs \$NOW windowEndedAtMs \$NOW audioDurationMs 1000 flushReason synthetic-guard \
 correlationId persistence-guard-2568 sha256 \$SHA byteLength 32000 requestedLanguage tr \
 audioFormat pcm16 sampleRateHz 16000 channels 1 textDraft 'Sentetik dogrulama cumlesi.' \
 textLength 27 sttLanguage tr languageProbability 0.99 durationSeconds 1.0 elapsedMs 100 \
 model guard computeType int8 device cpu status DRAFT receivedAtMs \$NOW" >/dev/null

# --- 3) Tüketiciyi bekle (canonical kayıt görünene kadar) ---------------
ASSOC=0; SEG=0
for _ in \$(seq 1 12); do
    sleep 5
    ASSOC=\$(docker exec "\$PG" psql -U platform -d transcript -t -A -c \
      "select count(*) from transcript_service.transcript_session_associations
       where source_session_id='\$EXT_SESSION' and status='RESOLVED';" 2>/dev/null | tr -d '[:space:]')
    [ "\${ASSOC:-0}" != "0" ] && break
done
SEG=\$(docker exec "\$PG" psql -U platform -d transcript -t -A -c \
  "select count(*) from transcript_service.transcript_segments where session_id in
     (select session_id from transcript_service.transcript_session_associations
      where source_session_id='\$EXT_SESSION');" 2>/dev/null | tr -d '[:space:]')
AFTER_DLQ=\$(R "XLEN \$DLQ" | tr -d '[:space:]')
DELTA=\$(( \${AFTER_DLQ:-0} - \${BEFORE_DLQ:-0} ))

echo "  dlq_delta=\$DELTA  association_resolved=\${ASSOC:-0}  segments=\${SEG:-0}"

# --- 4) Karar (üçü birden şart) ----------------------------------------
if [ "\$DELTA" -ne 0 ]; then
    REASON=\$(R "XREVRANGE \$DLQ + - COUNT 1" | grep -A1 '_dlqReason' | tail -1)
    echo "FAIL: mesaj DLQ'ya düştü (reason=\${REASON:-?}) — canonical persistence KIRIK." >&2
    RC=1
fi
[ "\${ASSOC:-0}" = "0" ] && { echo "FAIL: RESOLVED association oluşmadı." >&2; RC=1; }
[ "\${SEG:-0}" = "0" ]  && { echo "FAIL: transcript segment yazılmadı." >&2; RC=1; }

[ "\$RC" = "0" ] && echo "PASS: direct-STT -> canonical persistence zinciri sağlam."
exit \$RC
EOSSH
