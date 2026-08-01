# Faz 35 ES-311 — İmza Toplama Tracker

**Son güncelleme**: 2026-08-01 (acting mode 2. dönem)
**Hedef**: 7 imza (Reveal Officer 2 kişi dahil = 8 satır)
**Şu anki durum**: **0/8 resmi imza + 7/7 acting** (owner halildeu@gmail.com)
**Deadline**: 2026-08-08 (2. uzatma; ilk deadline 2026-07-29 dolmuştu — 3 gün kayıtsız aşım roster.md'de not edildi)

## Progress

| # | Rol | Kişi | Tarih | Method | Hash / Reference |
|---|---|---|---|---|---|
| 1 | Legal Owner | 🟡 acting: halildeu@gmail.com | 2026-07-22 | interim | roster.md pending |
| 2 | Privacy Officer / DPO | 🟡 acting: halildeu@gmail.com | 2026-07-22 | interim | roster.md pending |
| 3 | Secret Owner | 🟡 acting: halildeu@gmail.com | 2026-07-22 | interim | roster.md pending |
| 4 | Compliance Manager | 🟡 acting: halildeu@gmail.com | 2026-07-22 | interim | roster.md pending |
| 5 | Business Owner | 🟡 acting: halildeu@gmail.com | 2026-07-22 | interim | roster.md pending |
| 6a | Reveal Officer #1 | 🟡 acting: halildeu@gmail.com | 2026-07-22 | interim | roster.md pending |
| 6b | Reveal Officer #2 | 🔴 GAP — 4-göz için ayrı kişi lazım | — | — | owner atar (bkz. roster.md) |
| 7 | On-Call Engineer (Primary) | 🟡 acting: halildeu@gmail.com | 2026-07-22 | interim | roster.md pending |
| 7b | On-Call Engineer (Secondary) | 🔴 GAP — 30 gün içinde bulun | — | — | owner atar |

**Legend**:
- 🟢 signed (resmi kabul beyanı)
- 🟡 acting (owner geçici taahhüt, 7 gün max)
- 🔴 GAP (kritik boşluk, en kısa sürede kapatılmalı)
- 🔲 pending (henüz atama yok)

## History log

| Tarih | Event | Kim |
|---|---|---|
| 2026-07-22T13:20Z | ES-311 imza pack template oluşturuldu | agent |
| 2026-07-22T13:40Z | Acting mode aktif — owner 7 rolü geçici taahhüt | halildeu@gmail.com |
| 2026-07-29 | İlk acting dönemi doldu; kayıt güncellenmedi (aşım) | — |
| 2026-08-01 | Acting 2. dönem — owner 2026-08-08'e uzattı; görevler ayrılığı kuralı (vaka yürüten ≠ secret owner) roster'a işlendi; 4-göz ayrı-kişi zorlamasının kodda+testte mevcut olduğu doğrulandı (RevealService/RevealServiceTest) | halildeu@gmail.com |
| — | Owner roster.md doldurur (7 rol × isim/email) | pending |
| — | Ilk resmi imza (Legal Owner) | pending |
| — | 4/8 milestone | pending |
| — | 7/8 tam resmi imza (secondary on-call hariç OK) | pending |
| — | 8/8 tam resmi imza | pending |
| — | ES-312 go-live authorization | pending |

## Şu anki kritik açıklıklar

- 🔴 **Reveal Officer #2** — 4-göz gate işlemez (aynı kişi 2 tarafı olamaz). Owner bugün 2. kişi bul.
- 🔴 **On-Call Engineer Secondary** — 30 gün max owner tek başına 24×7. Secondary bulunmadan resmi ES-312 verilemez.
- 🟡 **Kanunî ifşa talebi gelirse** — acting mode owner tek Officer, 4-göz sağlanmadığı için ifşa **REDDEDİLİR** (default deny — hukuki koruma).

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
