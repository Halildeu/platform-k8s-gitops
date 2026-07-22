# Faz 35 ES-311 — İmza Toplama Tracker

**Son güncelleme**: 2026-07-22 13:20 UTC (agent template oluşturuldu)
**Hedef**: 7 imza (Reveal Officer 2 kişi dahil = 8 satır)
**Şu anki durum**: **0/8** imza toplandı
**Geçici mode**: Owner (halildeu@gmail.com) 7 rolü acting olarak taahhüt eder, 7 gün içinde resmi imza toplanır.

## Progress

| # | Rol | Kişi | Tarih | Method | Hash / Reference |
|---|---|---|---|---|---|
| 1 | Legal Owner | 🔲 pending | — | — | — |
| 2 | Privacy Officer / DPO | 🔲 pending | — | — | — |
| 3 | Secret Owner | 🔲 pending | — | — | — |
| 4 | Compliance Manager | 🔲 pending | — | — | — |
| 5 | Business Owner | 🔲 pending | — | — | — |
| 6a | Reveal Officer #1 | 🔲 pending | — | — | — |
| 6b | Reveal Officer #2 | 🔲 pending | — | — | — |
| 7 | On-Call Engineer (Primary) | 🔲 pending | — | — | — |
| 7b | On-Call Engineer (Secondary — opsiyonel) | 🔲 pending | — | — | — |

## History log

| Tarih | Event | Kim |
|---|---|---|
| 2026-07-22T13:20:00Z | ES-311 imza pack template oluşturuldu | agent |
| — | Ilk imza (Legal Owner)| pending |
| — | 4/7 milestone | pending |
| — | 7/7 tam imza | pending |
| — | ES-312 go-live authorization | pending |

## İmza yönergesi

1. **Roster** (`roster.md`) doldur — kişi + email
2. Her imzalayan **charter**'ını (`charters/<N>-<role>.md`) okur
3. Kabul beyanı satırını charter dosyasının **sonuna** yaz (`<PENDING>` yerine)
4. Git commit + push (subject: `sign(faz35): <ROL> - <İSİM>`)
5. Agent tracker'ı otomatik günceller (post-merge hook)

## Hızlı script (agent-doable, seçenek A - git commit method)

Imzalayan lokal olarak çalıştırabilir:
```bash
export ROLE="legal-owner"        # veya privacy-officer / secret-owner / vs.
export NAME="Ad Soyad"
export EMAIL="name@company.com"
export METHOD="git-commit"

CHARTER="docs/faz-35-signatures/charters/01-${ROLE}.md"
git checkout -b sign/faz35-${ROLE}-$(echo $NAME | tr '[:upper:]' '[:lower:]' | tr ' ' '-')

# Kabul beyanını ekle
cat <<EOF >> "$CHARTER"

**Kabul beyanı — 2026-$(date +%m-%d)**:
- İsim: ${NAME}
- Email: ${EMAIL}
- Rol: ${ROLE}
- Kabul yöntemi: ${METHOD}
- Charter versiyon: 2026-07-22 v1.0
- SHA256 (charter): $(sha256sum "$CHARTER" | cut -c1-16)
EOF

git add "$CHARTER"
git commit -m "sign(faz35): ${ROLE} kabul beyanı - ${NAME}"
git push -u origin HEAD
gh pr create --title "sign(faz35): ${ROLE} - ${NAME}" --body "Kabul beyanı ${CHARTER}"
```

## Aylık status raporu

Her ayın 1'inde agent otomatik rapor üretir (CronJob):
- Kaç imza güncel + kaç imza yenileme gereksinimli (< 30 gün)
- Rol boşluk risk uyarısı
- Rotation health (on-call vardiya adilliği)

## Failure modes + response

- **Rol boş kalırsa** → Business Owner 24 saat içinde vekil atar
- **Vekil bulunamazsa** → Owner (halildeu@gmail.com) acting olarak devralır
- **Imza charter değişikliği geçmeyen kişi** → yeni charter versiyon + tekrar imza gerekir
- **Rol devir sırasında audit trail** → succession commit ile kayıt korunur
