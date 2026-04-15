# Sysadmin DNS Ticket — `testai.acik.com`

> Sysadmin'e iletilecek talep. Aşağıdaki iki bölüm var: kısa mesaj
> (Slack/email gövdesi) ve detaylı sürüm (sorulara yanıt için).

---

## 📨 Kısa Mesaj (Slack / e-posta gövdesi)

**Konu:** DNS A kaydı talebi — `testai.acik.com` (intranet-only)

Selam,

Kubernetes geçişi için **paralel** bir test ortamı kuruyoruz. `staging-sw` sunucusunda mevcut canlı `ai.acik.com` (Compose stack) **HİÇ DOKUNULMADAN** çalışmaya devam edecek; yanına izole bir K8s tabanlı test ortamı ekleyeceğiz.

**Talep:** Windows AD DNS'e tek bir A kaydı eklenmesi
- **FQDN:** `testai.acik.com`
- **A → IP:** `10.9.10.53` (= staging-sw iç IP, mevcut `ai.acik.com` ile aynı)
- **Kapsam:** SADECE iç AD DNS (`acikdc01.acik.local`). Dış DNS'e (8.8.8.8 vs.) **yazılmamalı** — bu test ortamı sadece intranet/VPN'den erişilebilir kalmalı.

**Etkilenecek mevcut servis:** Hiçbiri.
- `ai.acik.com` aynı IP'de aynı şekilde çalışmaya devam eder.
- Dış proxy (`212.115.26.190`) `testai.acik.com` için herhangi bir kayıt almayacak — public'e açılmayacak.

**Beklenen tarih:** Mümkünse 1-2 iş günü içinde. Engelleyici değil ama K8s test ortamını canlıya alabilmemiz için gerekli.

Teşekkürler.

---

## 📝 Detaylı Sürüm (sorulara cevap için)

### Neden gerekli?

- Mevcut platform Docker Compose ile çalışıyor (`ai.acik.com`); bunu Kubernetes'e taşıyoruz.
- Geçiş sırasında **mevcut canlıyı bozmamak** için yeni K8s ortamı PARALEL kurulacak (ayrı hostname: `testai.acik.com`).
- Stabilite sağlanınca (1-3 hafta gözlem) cutover yapılacak: `ai.acik.com` DNS'i değişmeyecek, sadece staging-sw'de Compose stack'i durdurup K8s'e geçeceğiz.

### Neden `testai.acik.com` (4 seviyeli subdomain)?

- 2 seviyeli `test.acik.com` zaten daha geniş bir kullanıma rezerve edilebilir.
- `testai.acik.com` (4 seviyeli) açıkça "AI platformunun test ortamı" anlamına gelir, çakışma yok.
- Mevcut Sectigo wildcard cert'i (`*.acik.com`) bu subdomain'i de kapsar (SAN: `*.acik.com` + `acik.com`). Yeni cert almaya gerek yok.

### Güvenlik / izolasyon

| Soru | Cevap |
|---|---|
| Public erişime açılacak mı? | **HAYIR** — sadece iç AD DNS'e eklenmeli. Dış DNS / Cloudflare / dış proxy'ye yazılmamalı. |
| Mevcut `ai.acik.com` etkilenir mi? | Hayır. Aynı IP, aynı port (443), aynı cert; sadece yeni hostname için reverse proxy server block eklenecek. |
| Cert? | Mevcut Sectigo wildcard `*.acik.com` (geçerli 2026-10-01 sonuna kadar). Yeni cert satın alımı YOK. |
| Erişim yetkisi? | Mevcut intranet/VPN ağındaki dev ekibi. Ek IAM gerekmez. |
| Geri alma? | DNS kaydını silmeniz yeterli. K8s tarafı `bootstrap/uninstall-on-staging-sw.sh` ile tek komutta temizlenir. |

### Teknik detaylar (curious sysadmin için)

- staging-sw iç IP: `10.9.10.53` (ens160 interface)
- Staging-sw dış (NAT) IP: `31.145.18.18` (mevcut, 80/443 dış proxy üzerinden)
- Mevcut DNS:
  - `ai.acik.com` → iç DNS: `10.9.10.53`, dış DNS: `212.115.26.190` (dış proxy)
  - `testai.acik.com` → **YENİ**: iç DNS: `10.9.10.53`, dış DNS: yok (eklenmesin)
- `*.acik.com` wildcard A kaydı YOK (önceki kontrol). Per-host kayıt tercih ediyoruz.

### Doğrulama (ticket kapatma kriteri)

Sysadmin tarafından kapatılırken aşağıdaki komut başarılı dönmeli:

```bash
# Dahili DNS sorgusu
dig +short testai.acik.com @acikdc01.acik.local
# Beklenen çıktı: 10.9.10.53

# Dış DNS sızıntı kontrolü (BU BOŞ DÖNMELİ — public'e yayılmamalı)
dig +short testai.acik.com @8.8.8.8
# Beklenen çıktı: (boş)
```

---

## 📌 Ticket sonrası bizim adımlarımız

1. ✅ DNS kaydı doğrulanır (yukarıdaki dig komutları)
2. `bootstrap/install-on-staging-sw.sh` çalıştırılır (14 adımlı paralel kurulum)
3. Test ortamı stabilite testleri (Dilim 1+2+3) yeşil olunca cutover değerlendirilir
4. Cutover günü: `ai.acik.com` DNS'i değişmez; sadece compose stack durdurulur, K8s ingress 80/443'ü devralır
