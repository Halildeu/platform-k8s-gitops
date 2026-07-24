# Compliance Manager — Charter (Faz 35 ES-311)

**Rol**: ISO 27002:2022 + ISO 37002:2021 + KVKK denetim uyumu + iç kontrol.

## Neyi taahhüt ediyorum

### ISO 37002:2021 Whistleblowing Management System

- [ ] Sistem tasarımı standardın gerekliliklerini karşılar:
  - Liderlik + politika bildirimi (madde 5)
  - Planlama + risk (madde 6)
  - Destek (kaynak, yetkinlik, farkındalık — madde 7)
  - Operasyon (kanal, alma, değerlendirme — madde 8)
  - Performans değerlendirme (madde 9)
  - Iyileştirme (madde 10)
- [ ] Yıllık iç denetim + sürekli iyileştirme cycle'ı
- [ ] Standardın güncellemeleri izlenir

### ISO 27002:2022 Information Security Controls

- [ ] Uygulanabilir kontroller Faz 35 için haritalandırıldı:
  - **A.5.24** Bilgi güvenliği olay yönetimi planlaması → RB-faz35-incident-response
  - **A.5.34** Gizlilik ve kişisel verilerin korunması → DPO + Legal Owner
  - **A.6.6** Gizlilik veya ifşa etmeme sözleşmeleri → bu charter + çalışan sözleşmeleri
  - **A.8.16** İzleme faaliyetleri → observability + WORM audit
  - **A.8.28** Güvenli kodlama → backend PR review + Codex adversarial
  - **A.8.31** Geliştirme, test ve prod ortamlarının ayrılması → k3d-test / k3d-prod izolasyon

### KVKK denetim + Kurul kararları

- [ ] Kurul kararları izlenir + repo'ya uygulanır (`docs/compliance/kvkk-kurul-decisions.md` maintain)
- [ ] Denetim geldiğinde 5 iş günü içinde:
  - Aydınlatma metni ✅ Live PDF export
  - Veri envanteri ✅ VERBİS güncel
  - Silme kayıtları ✅ retention policy uyum kanıtı
  - Erişim log'ları ✅ WORM audit trail export
  - İhlal geçmişi ✅ event log
- [ ] Yıllık compliance report leadership'e

### Denetim iz + audit trail

- [ ] WORM audit trail (backend ES-303) **integrity** düzenli kontrol edilir
- [ ] Her Reveal talebi audit'e girer (Reveal Officer koordineli)
- [ ] Aylık audit trail sample review (rastgele 10 kayıt inceleme)
- [ ] Anomali → Compliance incident açılır

### İç denetim + üçüncü taraf denetim

- [ ] Yıllık iç denetim (Compliance Manager execute)
- [ ] 2 yılda bir üçüncü taraf denetim (ISO 37002 sertifikasyonu için gerekirse)
- [ ] Kalıcı iyileştirme + bulgular action item'lar

### Farkındalık + eğitim

- [ ] Şirket çalışanlarının whistleblowing kanal farkındalığı yıllık ölçülür (survey)
- [ ] Anti-misilleme + gizlilik + doğru kullanım eğitimi
- [ ] Yönetici eğitimi (özellikle bildiri geldiğinde nasıl hareket etmemesi gerektiği)

## Süre + yenileme

- 1 yıl geçerli
- Standart revizyonları izlenir
- Rol devir → yeni compliance manager tam envanter devri (~4 saat)

## Bağlı runbook'lar

- [RB-faz35-incident-response.md](../../runbooks/RB-faz35-incident-response.md)
- [RB-faz35-legal-reveal-request.md](../../runbooks/RB-faz35-legal-reveal-request.md)
- [RB-faz35-emergency-kill-switch.md](../../runbooks/RB-faz35-emergency-kill-switch.md)

## Kişisel mesuliyet

**Uyarı**: Compliance görevi ihlali → şirket denetim başarısızlığı → idari + hukuki risk.

---

**Kabul beyanı**: <PENDING>

```
Tarih: YYYY-MM-DD
İsim: AD SOYAD
Email: name@company.com
Rol: Compliance Manager
Kabul yöntemi: git commit / PDF ıslak / DocuSign
Charter versiyon: 2026-07-22 v1.0
```
