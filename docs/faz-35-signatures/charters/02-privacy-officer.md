# Privacy Officer / DPO — Charter (Faz 35 ES-311)

**Rol**: Kişisel veri koruma sorumlusu (KVKK Md.10 kapsamında aydınlatma sahibi).

## Neyi taahhüt ediyorum

### Aydınlatma metni sahipliği

- [ ] `docs/legal/faz35-privacy-notice-tr.md` içeriği **tarafımdan onaylanmıştır**
- [ ] Metnin her sürüm değişikliği için yeni sürüm numarası + değişiklik nedeni + kayıt oluşturulur
- [ ] Whistleblower başvuru sayfasında (etik.acik.com + speakup.acik.com) metin görünür olmalı (KVKK Md.10 gereği)
- [ ] Yıllık gözden geçirme + gerektiğinde revizyon

### İlgili kişi hakları (KVKK Md.11)

- [ ] Ilgili kişi başvuruları için tek irtibat noktasıyım
- [ ] 30 gün cevap yükümlülüğü izlenir
- [ ] Silme, düzeltme, itiraz, veri taşıma taleplerinin operasyonel karşılığı hazır
- [ ] Whistleblowing bağlamında **muhbir kimliği ilgili kişi hakları kapsamında ifşa edilmez** (kanunî istisna: mahkeme kararı → Reveal Officer 4-göz)

### Veri envanteri + VERBİS

- [ ] Şirketin VERBİS envanterine Faz 35 kapsamı eklenir (13-İşitsel Kayıtlar için Legal Owner'la koordineli)
- [ ] Data kategorileri: İsim (opsiyonel), IPvX (log), Zaman damgası, Kayıt içeriği, Access secret hash, Ekler (opsiyonel)
- [ ] Amaç: Şikâyet inceleme + hukuki takip + yasal saklama
- [ ] Retention süresi: `docs/legal/faz35-retention-policy.md` referans

### Gizlilik ve teknik korumalar

- [ ] Anonimlik teknik olarak korunur (Basic Auth kaldırıldı, IP tracking sadece rate-limit için, kayıt sonrası IP hash'lenir)
- [ ] Muhbir kimliği ile PII veriler ayrı **veri katmanlarında** tutulur (Ethics Reports vs Mailbox Sessions ayrı tablo)
- [ ] Şifreleme at-rest (Postgres pgcrypto + Vault-managed keys) ve in-transit (TLS 1.3) doğrulanmıştır
- [ ] Erişim log'ları WORM audit trail'e yazılır (Reveal Officer ve DPO görebilir)

### Veri ihlali response

- [ ] Kişisel veri ihlali tespit edildiğinde:
  1. 72 saat içinde KVK Kurulu'na bildirim (Md.12(5))
  2. Ilgili kişilere iletişim (mümkün olduğunda)
  3. Root cause analiz + iyileştirme
  4. WORM audit trail'e ihlal kaydı
- [ ] Yıllık ihlal simülasyonu (tabletop exercise) katılırım

### İç eğitim + farkındalık

- [ ] Şirket çalışanlarına whistleblowing kanal aydınlatması yapılır (iç iletişim)
- [ ] İK ve yöneticilere anti-misilleme farkındalık eğitimi verilir

## Süre + yenileme

- 1 yıl geçerli (2026-07-22 → 2027-07-22)
- KVKK Kurulu karar değişikliklerinde revizyon
- DPO ataması iş sözleşmesiyle bağlıdır — rol değişimi 24 saat succession

## Bağlı runbook'lar

- [RB-faz35-legal-reveal-request.md](../../runbooks/RB-faz35-legal-reveal-request.md) — DPO ilgili kişi hakları başvurusu bölümü
- [faz35-privacy-notice-tr.md](../../legal/faz35-privacy-notice-tr.md) — Aydınlatma metni sahibiyim
- [faz35-retention-policy.md](../../legal/faz35-retention-policy.md) — Retention Legal Owner ile ortak sahip

## Kişisel mesuliyet

**Uyarı**: KVKK Md.18 yönetici sorumluluğu bendedir; ihmal veya kasıt sonucu ihlallerde idari para cezası + rücu riski vardır.

---

**Kabul beyanı**: <PENDING>

```
Tarih: YYYY-MM-DD
İsim: AD SOYAD
Email: name@company.com
Rol: Privacy Officer / DPO
Kabul yöntemi: git commit / PDF ıslak / DocuSign
Charter versiyon: 2026-07-22 v1.0
```
