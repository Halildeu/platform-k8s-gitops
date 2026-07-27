# Legal Owner — Charter (Faz 35 ES-311)

**Rol**: Şirketin whistleblowing kanalının hukuki sorumluluk sahibi.

## Neyi taahhüt ediyorum

### KVKK + GDPR uyumu

- [ ] Şirketin Etik Speak kanalını **veri işleyen** olarak KVKK Md.3 kapsamında beyan ederim
- [ ] KVKK Md.5 uyarınca işleme şartlarının en az bir tanesine dayanan işleme sağlanır (Md.5(2)(a) açık rıza veya Md.5(2)(ç) sözleşmeden kaynaklanan işleme — muhbir bildiriminde varsayılan Md.5(2)(f) veri sorumlusunun meşru menfaati)
- [ ] KVKK Md.10 aydınlatma metni (`docs/legal/faz35-privacy-notice-tr.md`) whistleblower'a başvuru öncesi görünür kılınır
- [ ] Muhbir kimliği kanunî istisnalar dışında **hiçbir şart altında** üçüncü kişilerle paylaşılmaz (KVKK Md.9 + TCK Md.257)
- [ ] Ilgili kişi hakları (KVKK Md.11) 30 gün içinde cevaplanır
- [ ] Silme + yok etme yükümlülüğü (KVKK Md.7 + retention policy) izlenir

### EU 2019/1937 Whistleblowing Directive

- [ ] Iç raporlama kanalı Art.5 gereklilikleri karşılar (kabul + inceleme + geri bildirim + koruma)
- [ ] Muhbir 3 ay içinde durum güncelleme alır (Art.9(1)(f))
- [ ] Misilleme yasağı iş sözleşmelerine yansıtılır
- [ ] Kanunî istisnalar dışında ifşa YASAK (Reveal Officer 4-göz zorunlu)

### VERBİS + Kişisel Verileri Koruma Kurulu

- [ ] Şirketin VERBİS envanterine "13-İşitsel Kayıtlar" ve "Yazılı Şikâyet Bildirimleri" data kategorileri eklenir (Kurul karar tarih değişikliğinde 30 gün içinde güncelleme)
- [ ] Yıllık VERBİS raporu Nisan sonuna kadar sunulur
- [ ] Veri sızıntısı olduğu takdirde 72 saat içinde Kurul'a bildirim + ilgili kişilere iletişim (Md.12(5))

### Kanunî ifşa (Reveal) süreci

- [ ] Mahkeme kararı, savcılık talebi, kanunî istisnalar (KVKK Md.28) gelirse Reveal Officer 4-göz gate'inden geçer
- [ ] Ifşa öncesi hukuki incelemenin sorumluluğu bendedir
- [ ] WORM audit trail (backend ES-303) her ifşa için kalıcı kayıt üretir; audit'te bulunması zorunlu

### Şirket-içi hukuki koordinasyon

- [ ] İş sözleşmelerinin whistleblowing anti-misilleme maddesi güncellenir
- [ ] İK süreçleriyle koordinasyon (bildiri geldiğinde iş akışı)
- [ ] Cezai / hukuki dava riski takibi

## Süre + yenileme

- Bu charter **1 yıl geçerlidir** (2026-07-22 → 2027-07-22)
- Yıllık yenileme gerekir; rol değişimi durumunda 24 saat içinde succession commit
- Kanun değişikliği durumunda charter revizyonu + tekrar imza gerekir

## Bağlı runbook'lar

- [RB-faz35-legal-reveal-request.md](../../runbooks/RB-faz35-legal-reveal-request.md) — Reveal talebi süreci
- [faz35-privacy-notice-tr.md](../../legal/faz35-privacy-notice-tr.md) — Aydınlatma metni
- [faz35-retention-policy.md](../../legal/faz35-retention-policy.md) — Saklama politikası

## Kişisel mesuliyet

**Uyarı**: Yukarıdaki yükümlülükleri okuduğumu, anladığımı ve kabul ettiğimi beyan ederim. Ihmal veya kasıt sonucu doğacak zararlardan hukuken sorumluyum (KVKK Md.18, TCK Md.257, İş Kanunu Md.25).

---

**Kabul beyanı**: <PENDING — imzalayan bu satırı doldurup git commit ile taahhüt eder>

```
Tarih: YYYY-MM-DD
İsim: AD SOYAD
Email: name@company.com
Rol: Legal Owner
Kabul yöntemi: git commit / PDF ıslak / DocuSign
Charter versiyon: 2026-07-22 v1.0
```
