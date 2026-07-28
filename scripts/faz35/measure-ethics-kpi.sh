#!/usr/bin/env bash
# Faz 35 — Etik Speak yönetici yüzeyinin ölçülebilir eşikleri.
#
# "Hızlandı" bir iddiadır; bu betik ölçümdür. Aynı komut değişiklikten önce ve
# sonra koşulur, çıktı yan yana konur. Her eşik tek bir kök nedene bağlıdır, çünkü
# bir eşik düştüğünde hangi düzeltmenin geri alındığını bilmek gerekir:
#
#   K1  vaka listesi gecikmesi   ← yetki çağrısının istek başına sabit kalması
#   K2  açılış süresi            ← CPU bütçesi (throttling)
#   K3  OOMKill sayısı           ← bellek bütçesi
#   K4  bellek doluluk oranı     ← aynı; K3 gerçekleşmeden önce uyarır
#   K5  CPU throttle oranı       ← aynı K2; K2 gerçekleşmeden önce uyarır
#
# K4 ve K5 öncü göstergedir: K3 ve K2 arıza anında ölçülür, bunlar arıza
# yaklaşırken. Sadece K1-K3'e bakan bir eşik seti, sistem sınırın hemen altında
# otururken "yeşil" der.
set -euo pipefail
set +x

CTX=${CTX:-k3d-test}
NS=${NS:-platform-test}
SAMPLES=${SAMPLES:-5}

# Eşikler. Ölçülen kötü değerler yorumda; hedefler tahmin değil, kardeş
# servislerin gözlenen davranışından ve kullanıcının fiilen beklediğinden türetildi.
K1_MS=${K1_MS:-800}      # ölçülen: 5886 ms  (138 vaka, 6 KB yanıt)
K2_S=${K2_S:-45}         # ölçülen: 88 s
K3_MAX=${K3_MAX:-0}      # ölçülen: 90 dakikada 3 OOMKill
K4_PCT=${K4_PCT:-80}     # ölçülen: %98.7 (379/384 MiB), durağan halde
K5_PCT=${K5_PCT:-10}     # ölçülen: %41 (1186/2866 period)

fail=0
report() { # ad, deger, esik, yon(lt|le), birim
  local name=$1 value=$2 limit=$3 dir=$4 unit=${5:-}
  local ok
  if [ "$dir" = lt ]; then [ "$value" -lt "$limit" ] && ok=GEÇTİ || ok=KALDI
  else [ "$value" -le "$limit" ] && ok=GEÇTİ || ok=KALDI; fi
  [ "$ok" = KALDI ] && fail=1
  printf '%-28s %10s%-4s  eşik %s%-4s  %s\n' "$name" "$value" "$unit" "$limit" "$unit" "$ok"
}

pod=$(kubectl --context "$CTX" -n "$NS" get pod -l app.kubernetes.io/name=ethics-service \
        --field-selector=status.phase=Running \
        -o jsonpath='{.items[0].metadata.name}')
[ -n "$pod" ] || { echo "FATAL: çalışan ethics-service pod'u yok" >&2; exit 1; }
echo "pod: $pod"
echo

# --- K1: vaka listesi gecikmesi -------------------------------------------------
# Servis içinden ölçülür: ağ kenarını ve TLS'i dışarıda bırakır, böylece sayı
# yalnız sunucu tarafının işini gösterir. Jeton çağıranın işi (LIVE_TOKEN);
# verilmezse bu eşik atlanır — uydurma sayı üretmektense boşluk dürüsttür.
if [ -n "${LIVE_TOKEN:-}" ]; then
  total=0
  for _ in $(seq 1 "$SAMPLES"); do
    ms=$(kubectl --context "$CTX" -n "$NS" exec "$pod" -- sh -c \
        "start=\$(date +%s%3N); wget -q -O /dev/null --header='Authorization: Bearer $LIVE_TOKEN' \
         http://localhost:8099/api/v1/ethics/cases 2>/dev/null; echo \$((\$(date +%s%3N)-start))")
    total=$((total + ms))
  done
  report "K1 vaka listesi" $((total / SAMPLES)) "$K1_MS" lt ms
else
  echo "K1 vaka listesi              ATLANDI  (LIVE_TOKEN verilmedi)"
fi

# --- K2: açılış süresi ----------------------------------------------------------
started=$(kubectl --context "$CTX" -n "$NS" get pod "$pod" -o jsonpath='{.status.containerStatuses[0].state.running.startedAt}')
readyat=$(kubectl --context "$CTX" -n "$NS" get pod "$pod" \
            -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastTransitionTime}')
if [ -n "$started" ] && [ -n "$readyat" ]; then
  report "K2 açılış" $(( $(date -d "$readyat" +%s) - $(date -d "$started" +%s) )) "$K2_S" le s
fi

# --- K3: OOMKill --------------------------------------------------------------
# restartCount tek başına yetmez: OOM dışı bir restart da onu artırır. Sebep
# ayrıca okunur, yoksa "3 restart" görüp yanlış kök nedene gidilir.
restarts=$(kubectl --context "$CTX" -n "$NS" get pod "$pod" -o jsonpath='{.status.containerStatuses[0].restartCount}')
reason=$(kubectl --context "$CTX" -n "$NS" get pod "$pod" \
           -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}' 2>/dev/null || true)
report "K3 restart" "$restarts" "$K3_MAX" le ""
[ -n "$reason" ] && echo "     son sonlanma nedeni: $reason"

# --- K4 / K5: cgroup öncü göstergeleri -----------------------------------------
read -r cur max thr per <<EOF
$(kubectl --context "$CTX" -n "$NS" exec "$pod" -- sh -c '
  printf "%s %s %s %s" \
    "$(cat /sys/fs/cgroup/memory.current)" \
    "$(cat /sys/fs/cgroup/memory.max)" \
    "$(awk "/nr_throttled/{print \$2}" /sys/fs/cgroup/cpu.stat)" \
    "$(awk "/nr_periods/{print \$2}" /sys/fs/cgroup/cpu.stat)"' 2>/dev/null)
EOF
[ -n "${max:-}" ] && [ "$max" != max ] && report "K4 bellek doluluk" $((cur * 100 / max)) "$K4_PCT" le %
[ -n "${per:-}" ] && [ "$per" -gt 0 ] && report "K5 cpu throttle" $((thr * 100 / per)) "$K5_PCT" le %

echo
[ "$fail" = 0 ] && echo "TÜM EŞİKLER GEÇTİ" || echo "EŞİK ALTINDA KALAN VAR"
exit "$fail"
