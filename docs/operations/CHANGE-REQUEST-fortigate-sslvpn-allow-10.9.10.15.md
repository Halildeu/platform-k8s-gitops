# Değişiklik talebi — FortiGate SSL-VPN: `10.9.10.15` izinli hedeflere eklenmesi

**Tarih:** 2026-07-27 · **Sahip:** platform ekibi · **Uygulayan:** ağ/IT (FortiGate yönetimi)
**Etki:** SSL-VPN kullanıcıları yeni platform sunucusuna erişemiyor · **Risk:** düşük (tek adres, mevcut gruba ekleme)

## İstenen değişiklik — tek satır

SSL-VPN politikasının **izinli hedef adres grubuna** `10.9.10.15` eklenmesi — `10.9.10.53`'ün hâlihazırda bulunduğu grup.

Sunucu 2026-07-23'te `10.9.10.53` → `10.9.10.15`'e taşındı. Servisler taşındı, VPN politikası taşınmadı.

## Belirti

SSL-VPN'e bağlı bir istemciden `10.9.10.15` **hiçbir portta** yanıt vermiyor (TCP 22 ve 443 denendi, timeout). Aynı oturumda `10.9.10.53` normal çalışıyor.

## Sunucunun suçsuz olduğunun kanıtı

Aşağıdakiler 2026-07-27'de, VPN bağlıyken, iki bağımsız örnekte ölçüldü (istemci dış ağda, `utun6 = 10.250.250.10`).

**1. İstemci tarafı ve tünel kapsamı doğru — iki host birebir aynı**

```
10.9.10.0/24 split-tunnel listesinde VAR
route to 10.9.10.15 → gateway 10.250.250.10, interface utun6
route to 10.9.10.53 → gateway 10.250.250.10, interface utun6      (AYNI)
```

**2. Aynı oturumda `.53` erişilebilir, `.15` değil**

```
nc -z 10.9.10.53 22 → başarılı ;  ssh → OK (hostname: stagingsw)
nc -z 10.9.10.15 22 → timeout
```

**3. Paket sunucuya HİÇ ULAŞMIYOR** (en keskin kanıt)

`10.9.10.15` üzerinde 20 saniye boyunca VPN havuzundan gelen paket örneklendi; aynı anda istemciden **12 SYN** gönderildi (6 × tcp/22, 6 × tcp/443):

```
/proc/net/nf_conntrack içinde 10.250.250.* kaydı : 0
ss -tan içinde 10.250.250.*                      : 0
```

Bir SYN sunucunun ağ yığınına ulaşsaydı — kabul edilsin ya da düşürülsün — conntrack girdisi oluşurdu. Sıfır kayıt, paketin concentrator'dan sonra düşürüldüğü anlamına gelir.

**4. Sunucuda hiçbir filtre yok**

```
ufw                                  : inactive
iptables filter INPUT policy         : ACCEPT
tcp/22 üzerinde kaynak kısıtı        : yok
iptables raw PREROUTING DROP (9 adet): tamamı Docker anti-spoof
                                       (container IP'leri + 127.0.0.1:5432/5433/8200)
                                       hiçbiri 10.9.10.15:22 ile eşleşmiyor
iptables mangle PREROUTING           : boş
nftables ayrı ruleset                : yok
```

**5. Dönüş yolu `.53` ile aynı — asimetri yok**

```
.15 : ens160 10.9.10.15/24 · default via 10.9.10.1
      ip route get 10.250.250.10 → via 10.9.10.1 dev ens160 src 10.9.10.15
.53 : ens160 10.9.10.53/24 · default via 10.9.10.1
      ip route get 10.250.250.10 → via 10.9.10.1 dev ens160 src 10.9.10.53
```

**6. `.15`'in SSH'ı sağlıklı** — LAN içinden çalışıyor

```
.53 → .15:22  → ssh OK (hostname: aiserver)
```

## Değerlendirme

İki host aynı L2 subnet'te (`10.9.10.0/24`), aynı gateway'in (`10.9.10.1`) arkasında, dönüş rotaları birebir aynı, hedef host hiçbir şey engellemiyor ve aynı VPN oturumundan biri erişilebilir diğeri değil. Geriye tek değişken kalıyor: **FortiGate'in SSL-VPN politikasındaki izinli hedef kümesi**.

## Doğrulama (değişiklik sonrası, 10 saniye)

SSL-VPN'e bağlı bir istemciden:

```bash
nc -G 5 -z 10.9.10.15 22 && echo "ACIK"
ssh aiadmin@10.9.10.15 'hostname'      # beklenen: aiserver
```

## O zamana kadarki geçici yol (platform tarafı, kurulu)

`~/.ssh/config` içinde üç senaryo ölçüm notuyla tanımlı:

| Konum | Komut |
|---|---|
| Kurum LAN'ı, VPN kapalı | `ssh aiserver` |
| Kurum LAN'ı, VPN açık | `ssh aiserver-lan` (trafiği `en0`'a bağlar) |
| Dışarıda, VPN açık | `ssh aiserver-vpn` (`.53` üzerinden ProxyJump) |

Politika düzeltildikten sonra `aiserver-vpn` bloğu gereksiz kalır ve silinebilir.

## Not — bu talep bir güvenlik gevşetmesi değil

İstenen şey yeni bir servis açmak değil, **taşımada geride kalan bir eşlemenin tamamlanması**: aynı erişim `.53` için zaten verilmiş durumda. `.15` ek olarak `.53`'ten daha kapalı bir yüzeye sahip değil; aksine host güvenlik duvarı katmanının da taşınmadığı ayrı bir bulgu olarak kayıtlı (bkz. `FINDING-2026-07-26-host15-firewall-registry-exposure.md`) ve ayrıca kapatılıyor.
