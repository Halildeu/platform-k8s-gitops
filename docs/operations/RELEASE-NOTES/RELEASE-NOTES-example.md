# RELEASE-NOTES-example – Örnek Release Notu

Bu doküman, yeni release-notes yapısı için örnek bir şablon görevi görür.
Gerçek projelerde her release için benzer bir doküman oluşturulmalıdır.

-------------------------------------------------------------------------------
1. SÜRÜM BİLGİSİ
-------------------------------------------------------------------------------

- Sürüm: 2025.01.0-example  
- Tarih: 2025-01-XX  
- Ortam: prod  
- Sorumlu: @team/delivery

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Backend:
  - STORY-0001: Backend Docs Refactor (tamamlandı).
  - STORY-0002: Backend Keycloak JWT Hardening (tamamlandı).
- API:
  - STORY-0003: API Docs Refactor (users/auth/permission/audit).
- Operasyon:
  - RB-keycloak ve RB-vault runbook güncellemeleri.

İlgili Test Plan:
- `docs/03-delivery/TEST-PLANS/TP-0001-release-template.md`

-------------------------------------------------------------------------------
3. ÖNE ÇIKAN DEĞİŞİKLİKLER
-------------------------------------------------------------------------------

- Backend dokümantasyonu yeni `docs/` hiyerarşisine taşındı.
- Keycloak JWT sertleştirme (yalnız RS256 token’ların kabul edilmesi) devreye alındı.
- API sözleşmeleri `docs/03-delivery/api/*.md` altında tek kaynağa toplandı.

-------------------------------------------------------------------------------
4. RİSKLİ ALANLAR VE ROLLBACK
-------------------------------------------------------------------------------

- Keycloak JWT Sertleştirme:
  - Risk: Eski client’ların yeni JWT kurallarına uyumsuz olması.
  - Rollback:
    - İlgili release’i CI/CD üzerinden bir önceki stabil versiyona al.
    - Ayrıntılar için:
      - `docs/04-operations/RUNBOOKS/RB-keycloak.md`
      - `docs/03-delivery/TEST-PLANS/TP-0002-backend-keycloak-jwt.md`

- Vault İşlemleri:
  - Risk: Yanlış rekey veya unseal işlemleri.
  - Rollback:
    - `docs/04-operations/RUNBOOKS/RB-vault.md` içindeki prosedürleri uygula.

-------------------------------------------------------------------------------
5. SMOKE TEST CHECKLIST
-------------------------------------------------------------------------------

- [ ] Login ve temel kullanıcı akışları çalışıyor (TP-0002’e göre).  
- [ ] Kritik backend endpoint’ler (users/permission/auth) 200 dönüyor.  
- [ ] Vault health check metrikleri yeşil.  
- [ ] MFE Access temel grid yükleme ve mutation akışları çalışıyor.  

Ayrıntılı test akışları için:
- `docs/03-delivery/TEST-PLANS/TP-0001-release-template.md`
- `docs/03-delivery/TEST-PLANS/TP-0002-backend-keycloak-jwt.md`

-------------------------------------------------------------------------------
6. İLGİLİ RUNBOOK’LAR
-------------------------------------------------------------------------------

- `docs/04-operations/RUNBOOKS/RB-keycloak.md`
- `docs/04-operations/RUNBOOKS/RB-vault.md`
- `docs/04-operations/RUNBOOKS/RB-mfe-access.md`
- `docs/04-operations/RUNBOOKS/RB-feature-flags.md`

