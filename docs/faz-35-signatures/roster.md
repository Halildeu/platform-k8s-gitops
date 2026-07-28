# Faz 35 ES-311 — Rol Roster

**Son güncelleme**: 2026-07-22T13:35Z — **ACTING MODE** aktif
**Owner acting**: halildeu@gmail.com (7 rol geçici taahhüt)
**Resmi imza deadline**: 2026-07-29 (7 gün)

---

## Şu anki durum — Geçici mode (2026-07-22)

Kanal LIVE (ES-313 2026-07-22T13:14 UTC). Aşağıdaki 7 rol için resmi imza toplanana kadar:

> **halildeu@gmail.com** (owner) tüm 7 rolü **acting** olarak taahhüt eder.

- Audit trail'de "acting: halildeu@gmail.com since 2026-07-22" olarak işaretlenir
- SEV1 alert email → halildeu@gmail.com
- Reveal talebi 4-göz için: **acting mode'da 2. göz olarak bir kurumsal başka kişi belirlenmeli** (aynı kişi 4-göz'ün iki tarafı olamaz)
- Resmi imzalar 7 gün içinde toplanır; toplanmadığı takdirde owner tekrar 7 gün acting uzatabilir

---

## Kalıcı rol atamaları (owner doldurur)

### 1. Legal Owner
- **İsim**: `<TBD>` — owner atar
- **Email**: `<TBD>`
- **Öneri**: Şirket avukatı / dış hukuk müşaviri (retainer sözleşmeli). Kadrolu değilse, KVKK + iş hukuku uzmanı bir hukuk bürosuyla yıllık danışmanlık anlaşması.
- **Zaman kaybı**: bulunmazsa Legal Owner rolü Business Owner'a devredilir (uzman değil ama kabul edilebilir geçici)
- **Kabul yolu**: charter git commit / PDF ıslak / DocuSign
- **Charter**: [01-legal-owner.md](charters/01-legal-owner.md)

### 2. Privacy Officer / DPO
- **İsim**: `<TBD>` — owner atar
- **Email**: `<TBD>`
- **Öneri**: İç aday (IK/hukuk koordineli) → yoksa dış KVKK danışmanı (Compliance Manager ile aynı kişi olabilir küçük şirkette)
- **Kanunî zorunluluk**: 100+ çalışan veya yıllık 25M TL ciro veya özel nitelikli veri işleyen şirket → DPO ZORUNLU
- **Kabul yolu**: charter git commit / PDF ıslak / DocuSign
- **Charter**: [02-privacy-officer.md](charters/02-privacy-officer.md)

### 3. Secret Owner
- **İsim**: `<TBD>` — owner atar (**öneri: halildeu@gmail.com** — mevcut sistem yöneticisi)
- **Email**: `<TBD>`
- **Öneri**: DevOps/SRE lead. Küçük ekipte owner kendisi olabilir; ancak MFA + audit trail zorunlu.
- **Not**: Bu rol teknik + operasyonel — halildeu@gmail.com şu anda de-facto Secret Owner (Vault'a erişim var); resmi kabul beyanı ile role taşı
- **Kabul yolu**: charter git commit / PDF ıslak / DocuSign
- **Charter**: [03-secret-owner.md](charters/03-secret-owner.md)

### 4. Compliance Manager
- **İsim**: `<TBD>` — owner atar
- **Email**: `<TBD>`
- **Öneri**: İç denetim / kalite yönetim sistemi sorumlusu. Şirket ISO 27001 sertifikalı ise ISO koordinatörü ile aynı olabilir. Dış audit firma opsiyonu.
- **Zaman kaybı**: bulunmazsa Business Owner + DPO ortak devralır (subtandart ama işleyen)
- **Kabul yolu**: charter git commit / PDF ıslak / DocuSign
- **Charter**: [04-compliance-manager.md](charters/04-compliance-manager.md)

### 5. Business Owner
- **İsim**: `<TBD>` — owner atar (**öneri: halildeu@gmail.com**)
- **Email**: `<TBD>`
- **Öneri**: Şirket kurucusu / yönetici / bölüm müdürü. Faz 35 ürününün ticari sahibi.
- **Not**: halildeu@gmail.com şu anda tüm platform-k8s-gitops'un ürün yöneticisi; resmi kabul beyanı ile rol taşı
- **Kabul yolu**: charter git commit / PDF ıslak / DocuSign
- **Charter**: [05-business-owner.md](charters/05-business-owner.md)

### 6a. Reveal Officer #1
- **İsim**: `<TBD>` — owner atar
- **Email**: `<TBD>`
- **Öneri**: Legal Owner ile aynı kişi olabilir (küçük şirket) VEYA General Manager. Farklı departmandan olmak tercih edilir.
- **Telefon (kanunî ifşa emergency)**: `<TBD>`
- **Departman**: `<TBD>` — conflict of interest kontrol için
- **Kabul yolu**: charter git commit / PDF ıslak / DocuSign
- **Charter**: [06-reveal-officer.md](charters/06-reveal-officer.md)

### 6b. Reveal Officer #2
- **İsim**: `<TBD>` — owner atar
- **Email**: `<TBD>`
- **Öneri**: HR Director / IT Director / Yönetici asistanı. **Reveal Officer #1 ile farklı departmandan**.
- **Telefon (kanunî ifşa emergency)**: `<TBD>`
- **Departman**: `<TBD>` — Reveal Officer #1 ile farklı olmalı
- **Kabul yolu**: charter git commit / PDF ıslak / DocuSign
- **Charter**: [06-reveal-officer.md](charters/06-reveal-officer.md)

### 7. On-Call Engineer (Primary)
- **İsim**: `<TBD>` — owner atar (**öneri: halildeu@gmail.com** — mevcut sistem yöneticisi)
- **Email**: `<TBD>`
- **Telefon (SEV1 30dk cevap için ZORUNLU)**: `<TBD>`
- **PagerDuty/OpsGenie login**: `<TBD>` (opsiyonel — küçük ekipte email + telefon yeter)
- **Öneri**: DevOps/SRE. Küçük ekipte owner + 1 kişi rotasyon minimum.
- **Not**: halildeu@gmail.com şu anda de-facto on-call; resmi kabul beyanı ile role taşı + secondary bulunca rotate
- **Kabul yolu**: charter git commit / PDF ıslak / DocuSign
- **Charter**: [07-on-call-engineer.md](charters/07-on-call-engineer.md)

### 7b. On-Call Engineer (Secondary — kritik, en geç 30 gün içinde bulun)
- **İsim**: `<TBD>` — owner atar
- **Email**: `<TBD>`
- **Telefon**: `<TBD>`
- **Öneri**: DevOps ekip üyesi, dış freelance, veya karşılıklı anlaşmalı başka şirket engineer'ı.
- **Zaman kaybı**: bulunmazsa owner tek başına 24×7 (sürdürülebilir DEĞİL) — 30 gün maksimum
- **Kabul yolu**: charter git commit / PDF ıslak / DocuSign
- **Charter**: [07-on-call-engineer.md](charters/07-on-call-engineer.md)

---

## Öneri özeti — küçük şirket varsayılan

Küçük şirket (< 20 çalışan) için pratik minimum:

| Rol | Öneri kişi | Neden |
|---|---|---|
| Legal Owner | Dış hukuk müşaviri | Kadrolu değilse retainer |
| DPO | halildeu@gmail.com (KVKK sertifikalı danışman ile) | İç sorumlu + dış uzman |
| Secret Owner | halildeu@gmail.com | De-facto teknik yönetici |
| Compliance Manager | halildeu@gmail.com | Küçük şirkette Business Owner ile birleşebilir |
| Business Owner | halildeu@gmail.com | Kurucu |
| Reveal Officer #1 | Dış hukuk müşaviri | Legal Owner ile aynı |
| Reveal Officer #2 | Kurumsal 2. kişi (yönetici asistanı, ortak, vs.) | 4-göz gereği farklı olmalı |
| On-Call Primary | halildeu@gmail.com | Mevcut sistem yöneticisi |
| On-Call Secondary | Dış freelance / anlaşmalı | Owner çıkış izni için |

Bu setup **başlangıç için legal-uyumlu**. Ölçek büyüdükçe (50+ çalışan, ISO sertifikasyon, birden fazla müşteri) rolleri ayrık kişilere böl.

---

## Yardım templete

- Email davet templeti: [templates/invitation-email-tr.md](templates/invitation-email-tr.md)
- PDF export komut: [templates/pdf-export.sh](templates/pdf-export.sh) (pandoc gerekir)

## Roster commit yönergesi

Owner bu dosyayı doldurup commit ettiğinde agent otomatik olarak:
1. Tracker'da "acting" → "assigned pending signature" değiştir
2. Her imzalayana email davet gönder (SMTP kanal hazır olduğunda) — şu an owner manuel gönderir
3. Kabul beyanları geldikçe tracker güncellenir (post-merge hook)
