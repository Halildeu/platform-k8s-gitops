# Session Handoff — 2026-08-02 — Faz 35 vaka yaşam döngüsü (b) + iki canlı arıza

> D28 5-alan. Kapsam: `/goal` (b) — atama → inceleme → karar → yaptırım → misilleme takibi.

---

## 1. Bağlam

Hedef (b): vaka yaşam döngüsünü tamamlamak, sektör standartlarına ve yasal düzenlemelere
uygun biçimde. Referanslar: Direktif (AB) 2019/1937 (md. 9, 16, **19**, 21), ISO 37002,
Açık Holding MDL14 / MDL32-35 ve **İHLAL AĞIRLIK CETVELİ**.

Oturum sırasında kullanıcı iki canlı arıza bildirdi; ikisi de bu handoff kapsamında.

---

## 2. İddia (merge edilenler)

**platform-backend**

| PR | Ne |
|---|---|
| #1091 | Misilleme sorusunu ihbarcıya soran dağıtıcı (md. 19'un 15 biçimi kapalı sözlük) |
| #1092 | Gizli/isimli bildirimde NPE — yalnız ad soyad girilince form düşüyordu |
| #1093 | Otomatik eskalasyon listesi yazılıydı, **hiçbir karar yolunda okunmuyordu** |
| #1097 | Eski `companyId` kanonik `org_id` ile karşılaştırılmıyor artık |

**platform-web**

| PR | Ne |
|---|---|
| #1116 | Yaptırım kaydı + kontrol sonuçlandırma (yazma yarısı) |
| #1117 | Yaptırım uygulama + itiraz ilerletme |
| #1118 | İhlal kategorisi alanı + otomatik taban aynası |
| #1119 | `.ethics-form` stilleri + kapsayıcı sorgusu |

**platform-k8s-gitops** — #3388, #3389, #3390, #3392, #3394, #3398

---

## 3. İspatlar

### Canlı imajlar (hepsi gerçek çekişle çözülmüş digest)

| Servis | Digest |
|---|---|
| ethics-service | `sha256:9619cfc7…` |
| etik-speak-manager | `sha256:1687dab5…` |
| frontend | `sha256:e3df4628…` |
| meeting-service | `sha256:a6b2bb8c…` |
| transcript-service | `sha256:3c4dd2b5…` |
| endpoint-admin-service | `sha256:3775ac0e…` |

### Uçtan uca, tarayıcıdan

- **Gizli bildirim → makbuz ekranı** (etik.acik.com, konsol temiz)
- **Kapanış → misilleme çizelgesi kendiliğinden açıldı**: 3 / 6 / 12 ay
- **Yaptırım**: kayıt 201 → uygulama 200 → itiraz 200/200 → geri alma 409
- **Otomatik taban**, açığı bulan sondanın aynısıyla:

  | Sonda | Önce | Sonra |
  |---|---|---|
  | Rüşvet, HAFİF bantta | 201 | **400** |
  | Rüşvet, AĞIR bantta | 201 | **400** |
  | ÇOK AĞIR ama gerekçesiz (puan 6) | — | **400** |
  | Kategori yok | 201 | **400** |
  | ÇOK AĞIR + gerekçe | — | **201** |

- **Paneller `/admin/ethics`'te görünür**; form dar sütunda okunur
  (aynı satırı paylaşan etiket **0**, panel 305px → 681px, yatay taşma yok)
- **`/admin/meetings` → 200**, 7 toplantı. Ağ kaydında geçiş görünüyor:
  `401 · 401 · 401 · 401 · 503` → **`200 · 200 · 200`**. Sunucuda son 2 dk'da
  sıfır "Conflicting tenant claims".

### Veritabanı

`V24` canlıda koştu: `violation_category NOT NULL`,
`ck_sanction_automatic_escalation_floor` yerinde, mevcut iki satır `UNSPECIFIED`'a taşındı.
Göç, **uygulanmadan önce** canlı tablonun geçici kopyasında prova edildi (rollback'li):
kısıt listedeki kategoriyi `HAFIF` bantta reddetti.

---

## 4. İspatlamaz

- **Misilleme mesajının Türkçe hukuki metni gözden geçirilmedi.** Direktif md. 19'un
  biçimlerini adlandırıyor ama bir hukukçu okumadı. Ajan işi değil.
- **Prod'a hiç dokunulmadı.** Her şey test hücresi. Prod overlay'de bu değişikliklerin
  hiçbiri yok.
- **`enforce-claim-consistency` prod davranışı** ayrıca doğrulanmadı; düzeltme namespace
  ayrımını kaldırdı ama prod token şekli test edilmedi.
- Yaptırım/misilleme uçlarının **çoklu-kiracı izolasyonu** ayrı sınanmadı; mevcut
  `can()` yolundan geçiyorlar ama bu oturumda bağımsız kanıt üretilmedi.

---

## 5. Bilinen boşluk + sıradaki

**P0**
1. Misilleme mesajı hukuk incelemesi (insan kapısı).
2. Prod overlay'e taşıma kararı — (b) test'te kanıtlandı, prod ayrı karar.

**P1**
3. ES-409 — bağımsız dağıtım/geri alma + paylaşılan çekirdek artık riski (açık).
4. Faz 26 / gp-core: Etik & Uyum'u ilk dikey yapma kararı verildi, başlanmadı.

---

## Bu oturumda öğrenilenler (hafızaya yazıldı)

| Ders | Neden önemli |
|---|---|
| `mfe-ethic` **iki** imajda taşınıyor (`/ethic` ≠ `/admin/ethics`) | Eşleşen pod digest'i doğru yüzeyi kanıtlamaz |
| Hash'lenmiş eski kimlik rakip iddia değil | `md5("company:35")` ≠ org UUID → kalıcı 401 |
| `container-type` bir flex öğesini çökertir | 729px → **48px**, hatasız |
| 401 yönlendirmeden önce gelir | Sahte yol da 401 der; ayırt etmeyen prob |
| SSH'ta üç sessiz düşüş | stdin hırsızlığı · pipefail+SIGPIPE · zsh bölmez |
| `vi.mock` sabitleri **ve** yardımcı fonksiyonları siler | `bandForScore` baştan beri `undefined` dönüyormuş |

Ortak çizgi: bu oturumdaki hataların çoğu **sessizdi** — hata vermediler, yanlış davrandılar.
Yeşil bir test, eşleşen bir digest ve 401'lerin hepsi, ölçmediğim sürece hiçbir şey
kanıtlamadı.

---

## Sıradaki oturum için ilk komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-08-02-faz35-case-lifecycle.md
bash scripts/board-sync.sh list
```
