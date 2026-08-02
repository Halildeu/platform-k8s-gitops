# ADR-0050 — İhbarcı erişimi tasarım gereği kurtarılamaz

## Status

Accepted — 2026-08-02. ES-010 ([#2657](https://github.com/Halildeu/platform-k8s-gitops/issues/2657)).
Bu ADR yeni bir davranış getirmiyor; **zaten uygulanan** bir kararı kayda geçiriyor ve
makine-zorunlu invaryantlarla aşınmaya karşı sabitliyor.

**İlgili:** [ADR-0047 dava–kimlik bağı bölmeleri](0047-faz35-case-identity-link-compartments.md),
[ADR-0046 ürün hücresi topolojisi](0046-faz35-etik-speak-product-cell-topology.md),
`ethics-service` `ReporterAccessGrant` + `SecretHasher`,
`apps/etik-speak-public` makbuz ekranı

---

## 1. Bağlam

İhbarcı anonim ihbar bıraktığında iki değer alır: **bildirim numarası** (receipt) ve
**erişim sırrı**. Bu ikisi, kendi davasına geri dönüp etik ekibin cevabını okumasının ve
yazışmayı sürdürmesinin tek yoludur.

Her üründe olağan olan şey burada olamaz: "sırrınızı mı unuttunuz?" akışı. Çünkü böyle
bir akışın çalışabilmesi için sistemin önce **kimin sorduğunu** bilmesi gerekir. Bunu
bilmenin her yolu — e-posta adresi, telefon numarası, güvenlik sorusu cevabı — davadan
bir kişiye giden bir bağdır. İhbarcının bizden tutmamamızı beklediği şey tam olarak o
bağdır.

Yani kurtarma ile anonimlik aynı anda var olamaz. Biri seçilmek zorundadır.

Bir ek gerekçe daha var ve daha serttir: **mümkün olan şey, talep edilebilir.** Sırrı
geri verebilen bir mekanizma varsa, o mekanizma bir gün yasal bir talebin hedefi olur.
Var olmayan bir kapı ise teslim edilemez.

## 2. Karar

**İhbarcı erişim sırrı kurtarılamaz; hiçbir kurtarma yolu inşa edilmez.**

1. **Kurtarma ucu yok.** Public API yüzeyinde sırrı yeniden gönderen, sıfırlayan,
   hatırlatan veya kimliğe dayalı erişim veren hiçbir uç bulunmaz.
2. **Kimlik bağı yok.** `ReporterAccessGrant` yalnız şunları tutar: `receiptId`,
   `caseId`, `channel` (alım host'u — kişi değil), `secretHash`, `failedAttempts`,
   `lockedUntil`, `createdAt`. E-posta, telefon, ad, güvenlik sorusu, IP **yoktur** ve
   "yalnızca bildirim için" gerekçesiyle de eklenemez.
3. **Yalnız doğrulanabilir saklama.** Sır hash'lenerek (tuzlu, iterasyonlu) saklanır.
   Saklanan değer "bu sır mı?" sorusuna cevap verebilir; "sır neydi?" sorusuna **asla**.
4. **Dürüst arayüz.** Sır ekrandan gitmeden önce ihbarcıya doğrusu söylenir; makbuz
   indirilmeden ya da "kaydettim" onayı verilmeden akış ilerlemez.
5. **Dava yaşamaya devam eder.** Erişimini kaybeden ihbarcı yazışmasını kaybeder;
   **ihbarı değil**. Etik ekip dava üzerinde çalışmayı sürdürür.

### Yasak geri-dönüş yolları (açıkça)

| Yasak | Neden |
|---|---|
| E-posta ile sıfırlama bağlantısı | dava ↔ kişi bağı yaratır |
| Güvenlik sorusu / cevabı | aynı bağ, üstelik zayıf |
| "Destek ekibi doğrulayıp verir" | insan doğrulaması da kimlik doğrulamasıdır |
| Sırrı geri çevrilebilir şifrelemeyle saklamak | anahtar teslim edilebilir |
| Personelin ihbarcı adına posta kutusu açması | anonim kanalın kendisi çöker |

## 3. Ölçülen mevcut durum (2026-08-02, TEST hücresi)

Bu ADR iddia değil, kayıt: karar zaten uygulanıyor.

| kontrol | ölçüm |
|---|---|
| public yüzeyde kurtarma ucu | `mailbox/recover`, `mailbox/reset`, `mailbox/forgot`, `reports/resend`, `mailbox/sessions/recover`, `access/recover` → **hepsi 404** |
| çapa (kontrol) | var olan `POST /mailbox/sessions` → **400** — yani 404'ler gerçek yokluk, blanket-404 değil |
| `ReporterAccessGrant` alanları | kimlik-şekilli alan **yok** |
| saklama biçimi | `secretHash`; `SecretHasher` API'si yalnız `verify` döndürür (boolean) |
| arayüz | *"Erişim sırrı tekrar gösterilmeyecek ve kaybolursa geri alınamayacaktır."* + indirme + onay kutusu + kaydedilmeden posta kutusuna geçiş kapalı |

## 4. Sonuçlar

**Kabul edilen maliyet.** Sırrını kaybeden ihbarcı geri dönemez. Bu bir kusur değil,
seçilen güvencenin bedelidir — ve ihbarcıya **önceden** söylenir. Böyle bir kullanıcı
yeni bir ihbar bırakabilir; eski davasına bağlanamaz.

**Operasyonel sonuç.** Destek ekibinin "erişimimi kaybettim" talebine verebileceği tek
dürüst cevap vardır: geri getirilemez. Runbook'lar ve destek metinleri bu cümleyi
yumuşatmamalıdır; yumuşatılmış bir cevap, olmayan bir umut satar.

**Kaba kuvvet sınırı.** `failedAttempts` + `lockedUntil` alanları, kurtarma yokluğunun
tahmin saldırısına davetiye olmamasını sağlar.

## 5. Uygulama (makine-zorunlu)

ADR bir kararı kaydeder; kararı ayakta tutan şey başarısız olan bir derlemedir.
`ethics-service` içindeki `ReporterAccessNonRecoverabilityTest` üç aşınma yolunu da kapatır:

- public controller'ın **tüm** mapping'leri ve metot adları taranır; `recover|reset|forgot|
  resend|restore|retrieve|remind|unlock` anlamı taşıyan hiçbiri bulunamaz
- `ReporterAccessGrant` alan adları camelCase kelimelerine bölünerek kimlik sözcükleriyle
  karşılaştırılır (alt-dize değil: çıplak `ip` deseni `receiptId` içindeki harflere takılır
  — ilk koşumda tam bunu yaptı)
- `SecretHasher` yüzeyinde geri-çevirme metodu bulunamaz ve `verify` yalnız `boolean` döner

Bu testler, altı ay sonra "kullanıcılar makbuzlarını kaybediyor, bir sıfırlama e-postası
ekleyelim" değişikliğini **sessizce** geçmesin diye vardır.

## 6. Kapsam dışı

- Yasal ifşa (reveal) yolu — ayrı kapı, ADR-0047 ve ES-303 kapsamında; ihbarcının kendi
  erişimini geri kazanması ile ilgisi yoktur.
- Etik ekip tarafındaki dava erişimi — Keycloak + entitlement + OpenFGA zinciri, ES-308'de
  fail-closed olarak ölçüldü.
- İhbarcının **kendi isteğiyle** kimlik paylaştığı mod (varsa) — bu ADR anonim modu bağlar.
