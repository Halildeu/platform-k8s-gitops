# Faz 35 ES-311 — 7-İmza Paketi

**Amaç**: Etik Speak (whistleblowing) kanalı 2026-07-22 anonim erişime açıldı (ES-313 LIVE). Bu paket, kanalın hukuki + operasyonel + teknik sorumluluğunu 7 isimli role bağlar. Her imza kişisel taahhüttür.

**Yasal dayanak**:
- **KVKK** Md.3 (veri işleyen sorumluluk), Md.5 (işleme şartları), Md.7 (silme yükümlülüğü), Md.10 (aydınlatma), Md.11 (ilgili kişi hakları), Md.28 (istisnalar)
- **EU 2019/1937 Whistleblowing Directive** Art.5 (internal reporting channels), Art.9 (persona designation), Art.12 (follow-up + feedback)
- **ISO 37002:2021** Whistleblowing Management Systems
- **ISO 27002:2022** Annex A.5.24 (incident response), A.6.6 (confidentiality agreements), A.8.16 (monitoring)
- **6698 sayılı KVKK Kurulu Kararları** (VERBİS bildirim yükümlülüğü)
- **TCK Md.257** (görev suistimali) — hukuki koruma bekleyen muhbir gizliliğinin ihlali suç sayılır

---

## 7 Rol

| # | Rol | Neyi taahhüt eder | Charter | İmzalayan |
|---|---|---|---|---|
| 1 | **Legal Owner** | KVKK/GDPR uyumu, VERBİS güncel, hukuki mesuliyet | [charter](charters/01-legal-owner.md) | 🔲 pending |
| 2 | **Privacy Officer / DPO** | Aydınlatma metni, ilgili kişi hakları, veri envanteri | [charter](charters/02-privacy-officer.md) | 🔲 pending |
| 3 | **Secret Owner** | Vault key rotation, secret lifecycle, gizlilik ihlali response | [charter](charters/03-secret-owner.md) | 🔲 pending |
| 4 | **Compliance Manager** | ISO 27002/37002 kontrol, iç denetim, audit trail | [charter](charters/04-compliance-manager.md) | 🔲 pending |
| 5 | **Business Owner** | Ürünün ticari sorumluluğu, sürdürebilirlik, bütçe | [charter](charters/05-business-owner.md) | 🔲 pending |
| 6 | **Reveal Officer** (2 kişi) | Kanunî ifşa 4-göz onayı, muhbir kimlik gizliliği | [charter](charters/06-reveal-officer.md) | 🔲 pending (×2) |
| 7 | **On-Call Engineer** | 24×7 SEV1 30dk SLA cevap, incident coordination | [charter](charters/07-on-call-engineer.md) | 🔲 pending |

---

## İmza toplama süreci

### Aşama 1 — Rol atama (owner iş, ~1 gün)

Her role bir kişi ata:
```
docs/faz-35-signatures/roster.md dosyasını doldur:
  - İsim + soyisim
  - Kurumsal email
  - Rol (yukarıdaki tablodan)
  - Telefon (on-call için) veya "kabul beyanı yeter"
```

### Aşama 2 — Charter okuma + kabul (imzalayan iş, ~3 gün)

Her imzalayan kendi charter'ını (`docs/faz-35-signatures/charters/<role>.md`) okur. Charter'da yazan yükümlülükleri kabul ediyorsa:

**Seçenek A — Git commit imza (agent-doable)**
```bash
# İmzalayan git kullanıcısı charter dosyasının sonuna imza satırı ekler:
echo "" >> docs/faz-35-signatures/charters/01-legal-owner.md
echo "**Kabul beyanı**: 2026-XX-XX, <İSİM SOYİSİM> <email> — bu charter'ı okudum, kabul ediyorum." >> ...
git commit -m "sign(faz35): <ROL> kabul beyanı - <İSİM>"
```

**Seçenek B — PDF ıslak imza (fiziksel)**
1. Charter'ı PDF export'la (agent yardım eder)
2. İmzalayan ıslak imza atar + tarih
3. PDF'i `docs/faz-35-signatures/signed-pdfs/<role>-<name>.pdf` olarak commit (agent yardım eder)
4. PDF hash'i tracker'a yazılır (SHA-256)

**Seçenek C — Google Doc / DocuSign (uzaktan)**
1. Google Doc'a charter kopyala (agent yardım eder)
2. İmzalayan Google hesabıyla "Onaylıyorum" comment atar
3. Doc export → PDF → repo'ya

### Aşama 3 — Tracker güncelleme (agent iş)

Her imza sonrası agent:
1. `README.md` tablosunda 🔲 → ✅ değiştir
2. `docs/faz-35-signatures/tracker.md` timestamp + method + hash yaz
3. Project #8 issue #<ES-311> comment
4. 7/7 dolduğunda ES-311 → Done + ES-312 (go-live authorization) issue'ya bağla

### Aşama 4 — Denetim (yıllık, agent hatırlatır)

- Her yıl 12 ay sonra charter yenileme (`docs/faz-35-signatures/renewals/<YYYY>-<role>.md`)
- Rol devir olduğunda eski imzalayan revoke commit + yeni imzalayan yeni charter kabul
- ISO 37002:2021 sürekli iyileştirme gereği çeyrek yıllık review

---

## Kalıcı adres — imza değişimi

Rol değişimi olduğunda **eski imza revoke edilir + yeni imzalayan charter'ı sıfırdan kabul eder**. Kesintisiz vekil düzeni:

```
docs/faz-35-signatures/succession/<YYYY-MM-DD>-<role>-<from>-to-<to>.md:
  - Eski imzalayan revoke tarihi + sebep
  - Yeni imzalayan charter kabul tarihi
  - Vekil dönemi (kimin ne zamanki karar aldığı audit için)
```

---

## Boşluk toleransı

**Sıfır boşluk** (ISO 37002:2021 uyumu): rol değişimi sırasında eski imzalayan ile yeni imzalayan arasında en fazla 24 saat vekil boşluğu olabilir. Uzatma → geçici acting imzalayan ata (email onayı yeter).

## Şu anki durum (2026-07-22)

- Kanal LIVE (ES-313)
- 0/7 imza toplandı
- **Geçici mode**: owner (halildeu@gmail.com) 7 rolün tümünü **geçici olarak** taahhüt eder (audit trail'de "acting" olarak); resmi imzalar 7 gün içinde toplanır
- İlk gerçek report gelirse: owner Reveal Officer yetkisiyle 4-göz'ün 2. kişisi olur — 2. kişi (Reveal Officer duplicate) agent'la koordineli bir başka kurumsal iletişim gerekir

## Referanslar

- [ES-303 Reveal API + WORM](../adr/) — Reveal Officer'ın kullanacağı teknik akış
- [RB-faz35-legal-reveal-request](../runbooks/RB-faz35-legal-reveal-request.md) — Reveal Officer runbook
- [RB-faz35-incident-response](../runbooks/RB-faz35-incident-response.md) — On-call Engineer runbook
- [faz35-privacy-notice-tr](../legal/faz35-privacy-notice-tr.md) — Aydınlatma metni (Privacy Officer sahip)
- [faz35-retention-policy](../legal/faz35-retention-policy.md) — Saklama politikası (DPO + Legal Owner)
