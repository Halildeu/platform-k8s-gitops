# On-Call Engineer — Charter (Faz 35 ES-311)

**Rol**: 24×7 SEV1 alert cevap + incident coordination + servis sürekliliği.

## Neyi taahhüt ediyorum

### SLA + hazır bulunma

- [ ] SEV1 alert → 30 dakika içinde cevap (initial ack)
- [ ] SEV2 alert → 2 saat içinde cevap
- [ ] SEV3 alert → 1 iş günü içinde cevap
- [ ] Vardiya öncesi PagerDuty/OpsGenie login + test alert alma
- [ ] Vardiya sonrası devir → sonraki mühendise açık incident'lar

### Severity tanımları (Faz 35 için)

- **SEV1 (30dk cevap)**:
  - Ethics-service down (pod not Ready > 5dk)
  - Public reporter POST 5xx > 50% (5dk window)
  - Reveal API down (Reveal Officer erişemiyor)
  - WORM audit trail write failure
  - Backup CronJob 2 gün üst üste fail
  - Vault ESO sync başarısız (secret expire riski)
- **SEV2 (2sa cevap)**:
  - Elevated 5xx (10-50%)
  - Latency p95 > 3sn (baseline < 500ms)
  - Rate-limit false-positive (meşru trafiğin bloklanması)
  - Certificate expiry < 7 gün
- **SEV3 (1 iş günü)**:
  - Non-blocker warnings (disk > 70%, memory > 80%)
  - Grafana dashboard bozulması
  - Documentation drift

### Vardiya rotasyonu

- [ ] Primary + secondary rotation (2 kişi minimum)
- [ ] Vardiya süresi: 1 hafta primary + 1 hafta secondary
- [ ] Vardiya değişimi Pazartesi 09:00 TR
- [ ] Vardiya devir dokümanı (open incident'lar + devam eden iş)

### Response akışı

Her alert için:
1. **Ack** (0-30dk): PagerDuty ack + Slack #faz35-oncall'e bildir
2. **Triage** (5-30dk): Runbook aç, semptom + severity teyit
3. **Mitigate** (30dk-2sa): Servisi kurtarmak öncelik (root cause sonra)
4. **Communicate** (SEV1 için sürekli): Status Update 30dk aralıklarla
5. **Resolve** (mitigate sonrası): Servis dönüş + monitor 30dk
6. **Post-mortem** (SEV1 için 48 saat içinde): Root cause + iyileştirme action item'lar

### Kanunî delil koruma (kritik)

- [ ] Herhangi bir incident sırasında **muhbir verisi silme YASAK** (retention policy dışına çıkar)
- [ ] Database recovery gerektiğinde: **kanıt zinciri korunur** (backup restore öncesi mevcut state snapshot)
- [ ] Reveal Officer talebiyle ilgili acil müdahale: **her adım WORM audit'te**

### Eskalasyon

- [ ] SEV1 30dk cevap alınmazsa → secondary on-call + Business Owner
- [ ] 2 saat çözümsüzse → Legal Owner + DPO (potential veri kaybı)
- [ ] Muhbir kimlik ihlali şüphesi → Reveal Officer + Legal Owner + Compliance derhal
- [ ] Kanunî talep gelirse → Legal Owner + Reveal Officer

### Bilgi + eğitim

- [ ] Vardiya öncesi runbook'ları oku (`docs/runbooks/RB-faz35-*.md`)
- [ ] Aylık drill (tabletop exercise) katılım
- [ ] Yıllık chaos engineering (planned outage recovery)
- [ ] Yeni team member için 2 hafta shadow

### Erişim gereksinimi

- [ ] Kubernetes cluster erişimi (kubectl config)
- [ ] Vault UI + emergency secret erişim (limited scope)
- [ ] Grafana + Alertmanager + Loki
- [ ] PagerDuty/OpsGenie hesabı
- [ ] Slack #faz35-oncall channel
- [ ] Runbook repo erişim + git commit yetkisi (post-mortem yazımı için)

### Vardiya dışı

- [ ] Vardiya dışı zamanda pager kapatılır ama e-mail açık
- [ ] Vardiya devir sonrası çağrı almazsa: rotasyon disiplini kabul edilir

## Süre + yenileme

- 1 yıl geçerli
- Rol değişimi 24 saat succession (yeni engineer'ın runbook okuma + drill katılım gerekli)

## Bağlı runbook'lar

- [RB-faz35-incident-response.md](../../runbooks/RB-faz35-incident-response.md) — Full SEV1/2/3 response
- [RB-faz35-emergency-kill-switch.md](../../runbooks/RB-faz35-emergency-kill-switch.md) — Panic-off
- [RB-faz35-legal-reveal-request.md](../../runbooks/RB-faz35-legal-reveal-request.md) — Kanunî talep sırasında on-call iş
- [RB-faz35-real-reporter-open.md](../../runbooks/RB-faz35-real-reporter-open.md) — Muhbir açık dönemi normal ops

## Compensation

Business Owner koordineli:
- Vardiya bonusu (aylık maaş yüzdesi olarak)
- Callout ödemesi (SEV1 30dk cevap sonrası)
- Comp time (vardiya sonrası ek izin)

## Kişisel mesuliyet

**Uyarı**: On-call sırasında ihmal → servis kesintisi → potansiyel muhbir bildirim kaybı → hukuki sorumluluk zinciri. Kabul etmeden vardiya alma.

---

**Kabul beyanı**: <PENDING>

```
Tarih: YYYY-MM-DD
İsim: AD SOYAD
Email: name@company.com
Rol: On-Call Engineer (Primary veya Secondary — roster'da belirt)
Telefon (SEV1 cevap için ZORUNLU): +90 XXX XXX XXXX
PagerDuty/OpsGenie login: <username>
Kabul yöntemi: git commit / PDF ıslak / DocuSign
Charter versiyon: 2026-07-22 v1.0
```
