# RELEASE-NOTES-access-mvp – Access Modülü MVP Release Notu

Bu doküman, Access modülü MVP sürümünün prod ortama çıkışına ait özet notları
ve ilişkili dokümanları içerir.

-------------------------------------------------------------------------------
1. SÜRÜM BİLGİSİ
-------------------------------------------------------------------------------

- Sürüm: 2025.01-access-mvp  
- Tarih: 2025-01-XX  
- Ortam: prod  
- Sorumlu: @team/delivery, @team/platform-fe

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Access UI:
  - İlk MVP grid ve detay ekranları.
  - Manifest tabanlı rol/policy yönetim akışının devreye alınması.
- Backend:
  - Permission servisinde ilgili rol/izin uçlarının stabil hale getirilmesi.

İlgili Test Plan:
- `docs/03-delivery/TEST-PLANS/TP-9002-access-mvp.md`

-------------------------------------------------------------------------------
3. ÖNE ÇIKAN DEĞİŞİKLİKLER
-------------------------------------------------------------------------------

- Access modülü ile kullanıcı/rol bazlı erişim matrisinin UI üzerinden
  yönetilebilmesi.
- Permission API sözleşmesinin `docs/03-delivery/api/permission.api.md` altında
  dokümante edilmesi.
- MFE Access runbook’unun (`RB-mfe-access`) ilk versiyonunun hazırlanması.

-------------------------------------------------------------------------------
4. RİSKLİ ALANLAR VE ROLLBACK
-------------------------------------------------------------------------------

- Riskler:
  - Yanlış rol/policy konfigürasyonu sonucunda yetkisiz erişim veya yetki
    kaybı.
  - Access grid isteklerinin permission-service üzerindeki yükü artırması.

- Rollback:
  - Access UI için:
    - `docs/04-operations/RUNBOOKS/RB-mfe-access.md` rehberindeki rollback
      adımlarını uygula (manifest disable, feature flag fallback vb.).
  - Kritik flag’ler için:
    - `docs/04-operations/RUNBOOKS/RB-feature-flags.md` altında tanımlı
      flag rollback stratejilerini kullan.

-------------------------------------------------------------------------------
5. SMOKE TEST CHECKLIST
-------------------------------------------------------------------------------

- [ ] Access grid ana listeleme sorgusu başarıyla çalışıyor.  
- [ ] Temel rol atama/iptal akışı Permission API üzerinden sorunsuz.  
- [ ] MFE Access için kritik metrikler (TTFA, error rate) beklenen aralıkta.  

Detaylı testler için:
- `docs/03-delivery/TEST-PLANS/TP-9002-access-mvp.md`

-------------------------------------------------------------------------------
6. İLGİLİ RUNBOOK’LAR
-------------------------------------------------------------------------------

- `docs/04-operations/RUNBOOKS/RB-mfe-access.md`
- `docs/04-operations/RUNBOOKS/RB-feature-flags.md`

