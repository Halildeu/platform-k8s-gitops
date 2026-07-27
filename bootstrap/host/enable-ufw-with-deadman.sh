#!/usr/bin/env bash
# aiserver (10.9.10.15) host firewall'unu deadman switch ile aç. Faz 22 güvenlik.
#
# NEDEN DEADMAN
#   `.15`'e tek erişim yolu SSH. Yanlış bir ufw kuralı onu keser ve host'a
#   uzaktan dönüş yolu kalmaz — FortiGate SSL-VPN politikası `.15`'i hedef
#   almadığı için VPN'den de girilemez (2026-07-27 ölçüldü), tek yol `.53`
#   üzerinden jump. Bu yüzden `enable`'dan ÖNCE zamanlanmış bir `ufw disable`
#   kurulur: operatör 10 dakika içinde erişimi doğrulayıp iptal etmezse
#   firewall kendini kapatır. `iptables-apply`'ın kanonik deseni.
#
# ⚠️ UFW DOCKER-PUBLISHED PORTLARI FİLTRELEMEZ — bunu bilerek aç
#   Docker `-p` ile yayınlanan portlar `nat PREROUTING` DNAT'ından geçip
#   `FORWARD`/`DOCKER-USER` zincirinde ilerler; ufw'nin `INPUT` zincirine HİÇ
#   girmez. `.15` üzerinde 2026-07-27 ölçümü:
#
#     ufw'nin KAPSADIĞI (host süreçleri)      : 22 sshd · 80/443/5544/5545/8444 nginx · 443/udp wg0
#     ufw'nin KAPSAMADIĞI (docker-proxy)      : 5000 · 5001 · 6379 · 9100 · 9101
#
#   Yani ufw açmak registry LAN açıklığını (5000/5001) KAPATMAZ. Onun çözümü
#   binding değişimidir: bootstrap/k3d-*.yaml `host: "127.0.0.1"` (gitops #2974,
#   PR #2975) + çalışan container'lar için
#   bootstrap/host/rebind-k3d-registry-loopback.sh. Docker portlarını firewall
#   katmanında kapatmak isteniyorsa kural `DOCKER-USER` zincirine yazılmalı
#   (bkz. bootstrap/host/k3d-wg-masq/ — bu repoda sahipli-zincir deseni var).
#
# ⚠️ `.53`'ÜN PROFİLİNİ KOPYALAMA
#   Eski host'ta `22/tcp ALLOW IN 10.9.0.0/16` + `22/tcp DENY IN Anywhere` vardı.
#   FortiClient VPN havuzu `10.250.250.0/24` LAN dışı olduğu için DENY'e düşüyordu
#   → ~4 GÜNLÜK SSH OUTAGE. Bu script 22'yi kaynak kısıtı OLMADAN açar; kısıtlamak
#   isteniyorsa VPN havuzu AÇIKÇA eklenmeli (aşağıdaki SSH_SOURCES).
#
# KULLANIM
#   bash enable-ufw-with-deadman.sh --check          # sadece planı yaz, DOKUNMA
#   bash enable-ufw-with-deadman.sh --apply          # kuralları yaz + deadman + enable
#   bash enable-ufw-with-deadman.sh --cancel-deadman # erişim doğrulandıktan sonra kalıcı yap
#   bash enable-ufw-with-deadman.sh --rollback       # hemen kapat + deadman'i iptal et
#
# APPLY SONRASI ZORUNLU DOĞRULAMA (Mac'ten, YENİ bir bağlantı ile)
#   ssh -o ControlPath=none aiserver-vpn 'echo OK'      # veya LAN'daysa: ssh aiserver
#   curl -sk -o /dev/null -w '%{http_code}\n' https://testai.acik.com/
#   Her ikisi de çalışıyorsa: --cancel-deadman
#   Çalışmıyorsa: HİÇBİR ŞEY YAPMA — deadman 10 dakikada firewall'u kapatır.
set -euo pipefail

DEADMAN_MIN="${DEADMAN_MIN:-10}"
DEADMAN_UNIT="ufw-deadman"

# Ölçülmüş açık yüzey (2026-07-27, `ss -tlnp` / `ss -ulnp` / `wg show`).
# Değiştirmeden önce yeniden ölç: bootstrap/host/ portları burada sabit değil, olgudur.
TCP_ALLOW=(80 443 5544 5545 8444)   # nginx edge (host süreci → ufw kapsar)
UDP_ALLOW=(443)                     # wg0 listening port 443
# SSH kaynak kısıtı: boş = herkes (en güvenli başlangıç, kilitlenme riski yok).
# Kısıtlanacaksa VPN havuzunu ATLAMA:  SSH_SOURCES=("10.9.0.0/16" "10.250.250.0/24")
SSH_SOURCES=()

MODE=""
case "${1:-}" in
  --check|--apply|--cancel-deadman|--rollback) MODE="${1#--}" ;;
  *) echo "kullanım: $0 [--check|--apply|--cancel-deadman|--rollback]" >&2; exit 1 ;;
esac

need_root() { [ "$(id -u)" = 0 ] || SUDO=sudo; }
SUDO=""
need_root

plan() {
  echo "== planlanan kurallar =="
  if [ ${#SSH_SOURCES[@]} -eq 0 ]; then
    echo "  ufw allow 22/tcp                       # kaynak kısıtı YOK (kilitlenme riski yok)"
  else
    for s in "${SSH_SOURCES[@]}"; do
      echo "  ufw allow from $s to any port 22 proto tcp"
    done
    echo "  (DİKKAT: kısıtlı liste — VPN havuzu 10.250.250.0/24 dahil mi?)"
  fi
  for p in "${TCP_ALLOW[@]}"; do echo "  ufw allow ${p}/tcp"; done
  for p in "${UDP_ALLOW[@]}"; do echo "  ufw allow ${p}/udp"; done
  echo "  ufw default deny incoming / allow outgoing"
  echo "  ufw --force enable"
  echo
  echo "== ufw'nin KAPSAMADIĞI docker-published portlar (ölçülmüş) =="
  $SUDO ss -tlnH 2>/dev/null | awk '{split($4,a,":"); p=a[length(a)]; if ($4 ~ /^(0\.0\.0\.0|\[::\]|\*)/) print p}' | sort -n -u \
    | while read -r p; do
        if $SUDO ss -tlnpH "sport = :$p" 2>/dev/null | grep -q docker-proxy; then
          echo "  :$p  → docker-proxy — ufw ETKİSİZ (binding değişimi ya da DOCKER-USER gerek)"
        fi
      done
  echo
  echo "== deadman =="
  echo "  systemd-run --on-active=${DEADMAN_MIN}min --unit=${DEADMAN_UNIT} ufw disable"
}

case "$MODE" in
  check)
    echo "mevcut durum: $($SUDO ufw status | head -1)"
    echo
    plan
    echo
    echo "HİÇBİR ŞEY DEĞİŞTİRİLMEDİ (--check)."
    ;;

  apply)
    echo "mevcut durum: $($SUDO ufw status | head -1)"
    plan
    echo
    echo "== kurallar yazılıyor (enable'dan ÖNCE — sıra kritik) =="
    if [ ${#SSH_SOURCES[@]} -eq 0 ]; then
      $SUDO ufw allow 22/tcp
    else
      for s in "${SSH_SOURCES[@]}"; do $SUDO ufw allow from "$s" to any port 22 proto tcp; done
    fi
    for p in "${TCP_ALLOW[@]}"; do $SUDO ufw allow "${p}/tcp"; done
    for p in "${UDP_ALLOW[@]}"; do $SUDO ufw allow "${p}/udp"; done
    $SUDO ufw default deny incoming
    $SUDO ufw default allow outgoing

    echo
    echo "== deadman kuruluyor (${DEADMAN_MIN} dk) =="
    $SUDO systemctl stop "${DEADMAN_UNIT}.timer" 2>/dev/null || true
    $SUDO systemd-run --on-active="${DEADMAN_MIN}min" --unit="${DEADMAN_UNIT}" \
        /usr/sbin/ufw --force disable >/dev/null
    echo "  kuruldu: ${DEADMAN_UNIT}.timer"

    echo
    echo "== enable =="
    $SUDO ufw --force enable
    $SUDO ufw status verbose | head -20

    cat <<'MSG'

################ ŞİMDİ DOĞRULA — YENİ bir bağlantı ile ################
Mac'ten:
  ssh -o ControlPath=none aiserver-vpn 'echo OK'
  curl -sk -o /dev/null -w '%{http_code}\n' https://testai.acik.com/

ÇALIŞIYORSA:   bash enable-ufw-with-deadman.sh --cancel-deadman
ÇALIŞMIYORSA:  hiçbir şey yapma — deadman firewall'u kendisi kapatacak.
#######################################################################
MSG
    ;;

  cancel-deadman)
    $SUDO systemctl stop "${DEADMAN_UNIT}.timer" 2>/dev/null || true
    $SUDO systemctl reset-failed "${DEADMAN_UNIT}.service" 2>/dev/null || true
    if $SUDO systemctl list-timers --all 2>/dev/null | grep -q "$DEADMAN_UNIT"; then
      echo "UYARI: deadman timer hâlâ listede — elle: systemctl stop ${DEADMAN_UNIT}.timer"
      exit 1
    fi
    echo "deadman iptal edildi; ufw kalıcı."
    $SUDO ufw status | head -1
    ;;

  rollback)
    $SUDO ufw --force disable
    $SUDO systemctl stop "${DEADMAN_UNIT}.timer" 2>/dev/null || true
    $SUDO systemctl reset-failed "${DEADMAN_UNIT}.service" 2>/dev/null || true
    echo "ufw kapatıldı + deadman iptal."
    $SUDO ufw status | head -1
    ;;
esac
