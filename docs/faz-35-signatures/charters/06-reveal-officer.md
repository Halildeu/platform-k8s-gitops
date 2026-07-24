# Reveal Officer — Charter (Faz 35 ES-311)

**Rol**: Kanunî ifşa talebi 4-göz onayı + muhbir kimlik gizliliği koruma.

**KRİTİK**: Reveal Officer **2 kişi** olmalıdır (4-göz gereği). Aynı departmandan olmaması tercih edilir. Her Reveal talebi **iki farklı Reveal Officer** tarafından bağımsız değerlendirilir + onaylanır. Tek Officer onayı yeterli DEĞİLDİR.

## Neyi taahhüt ediyorum

### Kanunî ifşa 4-göz süreci

- [ ] Reveal talebi geldiğinde (mahkeme kararı, savcılık talebi, KVKK Md.28 istisnası):
  1. Hukuki geçerlilik incelemesi (Legal Owner ile koordineli)
  2. Bağımsız değerlendirme — talep gerçekten kanunî mi?
  3. Alternatif reddin gerekçesi (ör. talep kapsamı geniş, orantısız)
  4. Diğer Reveal Officer'ın bağımsız onayı — hem approve
  5. WORM audit'e her adım kalıcı kayıt
- [ ] Reveal Officer #1 yalnız approve **RE Officer #2 approve YOKSA ifşa yapılmaz**
- [ ] Şüphe durumunda **her zaman refuse** — sonradan legal review

### Muhbir kimlik gizliliği

- [ ] Muhbir kimliği kanunî istisnalar dışında **hiçbir şart altında** ifşa edilmez (KVKK Md.9 + TCK Md.257 kapsamında suç)
- [ ] Şirket-içi baskı (yönetici talep) reddedilir + audit'e kaydedilir
- [ ] Şüpheli baskı → derhal Legal Owner + DPO'ya bildir
- [ ] Kimlik verisi yalnız Reveal API üzerinden erişilir (backend ES-303 endpoint) — direct DB erişim YASAK
- [ ] Reveal Officer'a verilen session key 24 saat TTL — kullanımdan sonra revoke

### Ifşa sonrası koruma

- [ ] Ifşa kararı verilen muhbir için misilleme koruması aktif
- [ ] İK ile koordinasyonlu izleme (iş sözleşmesi + performans değerlendirme + terfi gibi risk alanları)
- [ ] Yıllık misilleme audit (ilk 12 ay içinde muhbir statüsündeki çalışanların durumu)
- [ ] Misilleme tespit edilirse: iş hukuku + KVKK ihlali + ceza hukuku (TCK Md.257) süreci

### Erişim kontrolü

- [ ] Reveal API kullanma yetkisi yalnız 2 atanmış Officer'da
- [ ] Erişim WORM audit'te kalıcı (session_start, action, timestamp, target_report_id, decision_hash)
- [ ] MFA zorunlu
- [ ] Cross-check: aynı Reveal Officer aynı talebe yalnız 1 kez oy verebilir (double-vote engelli)

### İhbar sonrası dönüş

- [ ] Muhbir 3 ay içinde durum güncelleme alır (EU 2019/1937 Art.9(1)(f)):
  - Şikâyet kabul edildi mi?
  - Inceleme başladı mı?
  - Sonuç ne?
- [ ] Anonim muhbir için: mailbox'a güncelleme mesajı (staff manager UI üzerinden)
- [ ] Isim beyan eden muhbir için: aydınlatma metni belirtilen kanal üzerinden

### Sınırlamalar

- [ ] Reveal Officer kendi departmanıyla ilgili bildiriyi göremez (conflict of interest)
- [ ] Reveal Officer üst yöneticisi ile ilgili bildiriyi göremez
- [ ] Bu durumlarda Business Owner **geçici vekil** atar (audit'te işaretlenir)

## Süre + yenileme

- 1 yıl geçerli
- Rol değişimi 24 saat succession + eski Officer erişim revoke
- Reveal Officer rolü **maaşlı ek görev** kabul edilir (Business Owner koordineli)

## Bağlı runbook'lar

- [RB-faz35-legal-reveal-request.md](../../runbooks/RB-faz35-legal-reveal-request.md) — kanunî ifşa süreci
- [RB-faz35-incident-response.md](../../runbooks/RB-faz35-incident-response.md) — muhbir kimlik ihlali SEV1

## Backend teknik akış (ES-303)

Reveal API `POST /api/v1/staff/ethics/reports/{id}/reveal`:
1. RevealOfficer #1 approve → tuple write OpenFGA (`reveal:pending:approver1`)
2. RevealOfficer #2 approve → tuple write (`reveal:pending:approver2`)
3. Her iki approve tuple varsa → reveal endpoint identity payload döner
4. WORM audit'e her tuple write + reveal execution kalıcı kayıt
5. Session 24h expiry sonrası revoke

## Kişisel mesuliyet

**Uyarı**: Muhbir kimlik ihlali TCK Md.257 kapsamında görev suistimali suçudur. Ceza hukuku sorumluluğu şahsen üzerinizdedir. İhmal yeterli değil, kasıt gerekli.

---

**Kabul beyanı**: <PENDING>

```
Tarih: YYYY-MM-DD
İsim: AD SOYAD
Email: name@company.com
Rol: Reveal Officer (#1 veya #2 — roster'da belirt)
Departman: <ilgili departman, conflict of interest kontrol için>
Kabul yöntemi: git commit / PDF ıslak / DocuSign
Charter versiyon: 2026-07-22 v1.0
```

**KRİTİK**: İki Reveal Officer aynı charter'ı ayrı ayrı imzalar (roster'da #1 ve #2 olarak ayrılmış).
