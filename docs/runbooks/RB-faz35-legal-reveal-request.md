# RB-faz35 — Legal reveal request (identity disclosure ceremony)

> **Scope:** Faz 35 Etik Speak whistleblower kimlik açığa çıkarma (legal reveal) prosedürü. Bu prosedür yalnız **ES-303 Reveal API + WORM attribution** implement edilmiş + **ES-311 Reveal Officer atanmış** olduğu durumda uygulanabilir. Sektör-standardı: **EU 2019/1937 Art.16(2) confidentiality with legal exception**, **ISO 37002:2021 §7.4.3 confidentiality management**, **KVKK Md.5(2)(a) hukuki yükümlülük istisnası**, **KVKK Md.28 açıklama istisnası**.

## Ne zaman uygulanır

Reveal, whistleblower'ın **anonimlik hakkının** ancak aşağıdaki hukuki-etik gerekçelerle geri alınabileceği kritik bir yetki devridir:

- **Yargı kararı** (mahkeme + savcılık + hakim onaylı) — Türk hukukunda CMK Md.135 benzeri, ya da diğer yetkili yargı organı.
- **Bilinçli sahte bildirim** (kötü niyet + kişilere iftira) — iç soruşturma sonrası ortaya çıkarsa, whistleblower korumasına hak kazanmamış olur.
- **Whistleblower'ın kendi rızası** (yazılı + tanıklı).
- **Hayati tehlike** (whistleblower veya üçüncü şahıslar için ani ve acil tehlike, yaşam kurtarma amaçlı) — yalnız Reveal Officer + Legal + hospital/emergency-service tanıklığında.

## Kimler yetkilidir

- **Reveal Officer** (ES-311 atanmış) — reveal talebini alır + değerlendirir + ceremony yürütür.
- **Legal counsel** (in-house veya external) — yasal gerekçenin uygun olduğunu doğrular.
- **Secret owner / Security lead** — reveal grant TTL + auto-reseal + audit chain sağlığını doğrular.
- **Business owner** — reveal kararını final onaylar (business risk + reputation risk balance).

**Hiçbir tekli aktör** (tek başına Legal, tek başına Reveal Officer) reveal başlatamaz. **Minimum 3 imza** (Reveal Officer + Legal + Business Owner) + sistem-enforced (backend RBAC: `ethics-reveal-officer` role + owner-approved permission grant).

## Ceremony akışı

### 1. Talep kabul + kayıt

- Reveal talebi Reveal Officer'a **imzalı doküman** olarak gelir (yargı kararı fotokopisi + sarıraflı vs).
- Reveal Officer talebi `docs/faz-35-evidence/reveal-requests/YYYY-MM-DD-<case-id>.md` içine kayıt eder:
  ```markdown
  # Reveal request — case <UUID>
  ## Received: YYYY-MM-DD HH:MM
  ## Requester: <isim + kurum + iletişim>
  ## Legal ground: <yargı kararı / sahte bildirim / rıza / hayati tehlike>
  ## Legal doc ref: <mahkeme kararı numarası / diğer>
  ## Sworn statement attached: [dosya path — encrypted]
  ```

### 2. Legal + Business review

- Legal counsel değerlendirir: yasal gerekçe geçerli mi? Hukuki gereklilik + orantılılık + gerekçe testi.
- Business owner değerlendirir: reputation risk + reporter'a ex-post koruma.
- Karar: **APPROVE** / **REJECT** — yazılı gerekçe.

### 3. Reveal grant issue

APPROVE ise:

```bash
# Backend Reveal API çağrısı (ES-303 implementation):
# POST /api/v1/ethics/cases/{caseId}/reveal-requests
# Body: {
#   "legalGroundCode": "COURT_ORDER",
#   "legalDocRef": "İstanbul 3. Ağır Ceza Mahkemesi 2026/1234 K.",
#   "revealOfficerSignature": "<KC user + timestamp>",
#   "legalCounselSignature": "<KC user + timestamp>",
#   "businessOwnerSignature": "<KC user + timestamp>",
#   "grantTtlMinutes": 30,
#   "revealScope": "REPORTER_IDENTITY"  # veya "FULL_CASE"
# }
```

Backend fail-closed davranış:
- Signature'lardan biri eksik → **403 REVEAL_INCOMPLETE_APPROVAL**
- Grant TTL max 60 dakika (config'te sabitlenmiş).
- WORM audit log entry oluşur: hash-chained + tamperproof + secret-owner-signed.

### 4. Reveal execution + audit

- Reveal Officer + Legal counsel + Business owner (opsiyonel) **birlikte** oturumu başlatır.
- Reveal grant TTL içinde reporter identity gösterilir; **screenshot alınmaz**, **kopyalanmaz**.
- WORM audit log her `read` event'i kayıt eder (kim, ne zaman, hangi alan).
- Talebeye teslim: Legal counsel yazılı özet + ilgili yasal delillerle Requester'a teslim eder; **raw reporter identity Etik Speak dışına çıkmaz** (sadece Legal'in özet + yasal koruma sözleşmesi çerçevesinde).

### 5. Auto-reseal + notification

- Grant TTL sonrası backend otomatik **reseal** — Reveal Officer da erişimi kaybeder.
- Reveal event'i audit log'a append (immutable).
- **Reporter'a bildirim gönderilir mi?** Yasal duruma bağlı:
  - Yargı kararı: bildirim erteleme (CMK gizlilik) mümkün.
  - Sahte bildirim: reporter'a discipline procedure başlatılır (HR + Legal).
  - Hayati tehlike: post-event bildirim (hayat kurtarma sonrası).
- Bildirim kararı **Business owner + Legal** tarafından ceremony sırasında verilir.

### 6. Post-reveal audit review

- 30 gün içinde: audit log review (Reveal Officer + external auditor).
- Reveal grant'in orantılılığı (talep ve verilen kapsam).
- WORM audit log integrity check (hash chain verify).
- Board issue **ES-303 audit trail** kayıt.

## Whistleblower koruması

**Reveal ≠ discipline / retaliation authorization.** EU 2019/1937 Art.19 gereği reveal edildikten sonra bile whistleblower:

- İşten çıkarma
- Terfi engeli
- Ücret indirim
- Sosyal dışlanma

gibi retaliation'lardan **yasal olarak korunur**. Reveal Officer bu koruma çerçevesini requester'a **açıkça hatırlatır** (yazılı acknowledgement).

Retaliation tespit edilirse:

- Reporter'a: yasal koruma + iş güvenliği yeniden tesis.
- Requester'a: sözleşme ihlali + hukuki takip.

## Rollback / iptal

Reveal kararı iptal edilebilir (revoke) yalnız TTL süresi içinde:

```bash
# DELETE /api/v1/ethics/cases/{caseId}/reveal-requests/{grantId}
# Reason: <text>
# Signatures: Reveal Officer + Legal + Business owner (3-of-3)
```

TTL sonrası reseal otomatik.

## Kayıt + evidence artifact

Her reveal ceremony sonrası:

- `docs/faz-35-evidence/reveal-requests/YYYY-MM-DD-<case-id>.md` — full talep + karar + WORM audit hash.
- Backend WORM audit log — hash-chained (verify script: `scripts/faz35/verify-reveal-audit.sh` — Codex Reveal API implementation ile birlikte gelir).
- Legal doc archive (encrypted) — external legal document storage (S3 Object Lock veya legal hold).
- Board issue **ES-303 audit trail** update — Reveal history summary (aggregate, non-secret).

## Referanslar

- `docs/legal/faz35-privacy-notice-tr.md` — KVKK aydınlatma metni (reveal koşulları belirtili).
- `docs/legal/faz35-retention-policy.md` — Reveal grant + audit log retention.
- Backend: `ethics-service/src/main/java/com/example/ethics/reveal/*` (Codex spawn task #378f775d ile implement edilecek).
- Board: [Project #8 ES-303](https://github.com/users/Halildeu/projects/8).
