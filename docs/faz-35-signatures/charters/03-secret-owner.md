# Secret Owner — Charter (Faz 35 ES-311)

**Rol**: Vault key management + secret rotation + gizlilik ihlali response.

## Neyi taahhüt ediyorum

### Vault + secret lifecycle

- [ ] `platform-test` (test cell) ve gelecekteki `platform-prod` cluster'larındaki **tüm Faz 35 secret'larının** lifecycle sahibiyim:
  - Postgres user/password (ethics-service DB)
  - Vault AppRole role_id + secret_id (ESO sync)
  - JWT signing keys (Reveal Officer session)
  - Mailbox session cookie encryption key
  - OpenFGA store_id + credential
  - MinIO WORM bucket access key
- [ ] Vault policy'ler her secret için least-privilege (write only oluşturma sırasında, read-only runtime)
- [ ] `d35-*` persona'ları yalnız test amaçlı; prod'da farklı persona zorunlu

### Rotation politikası

- [ ] Postgres password: 90 günde bir otomatik rotate (Vault database engine)
- [ ] Vault AppRole secret_id: 30 günde bir otomatik rotate (TTL=30d)
- [ ] JWT signing key: 60 günde bir manual rotate (backend restart gerekir)
- [ ] Reveal Officer session key: 24 saat TTL (hard-coded)
- [ ] MinIO WORM access key: yıllık rotate (compliance gereği)

### Ihlal response

- [ ] Vault access log haftalık review
- [ ] Anomali tespiti (mesai dışı erişim, yeni IP, farklı user-agent)
- [ ] Compromise şüphesi:
  1. Hemen shared secret revoke
  2. Vault AppRole ve token'ları invalidate
  3. Kompromize olduğu düşünülen key'i acil rotate
  4. WORM audit trail'e ihlal kaydı
  5. Legal Owner + DPO + Compliance Manager'a bildirim
  6. 72 saat kural: KVK Kurulu bildirim (Legal Owner ile koordineli)

### Erişim kontrolü

- [ ] Vault root token yalnız acil durum (ör. cluster recovery) — kullanım sonrası revoke + audit
- [ ] Sadece atanmış Secret Owner + On-call Engineer (limited scope) Vault UI'ye erişebilir
- [ ] MFA zorunlu (Google Authenticator veya HW token)
- [ ] Owner (halildeu@gmail.com) her zaman glass-break erişimi vardır (audit'te işaretlenir)

### Backup + restore

- [ ] Vault snapshot günlük alınır (ES-309 CronJob)
- [ ] Yılda 1 kez restore drill (test cluster'ında geri yükleme testi)
- [ ] Backup şifrelenmiş (age + Vault-managed key) + off-site (S3 + local NAS)

### Cluster boundary

- [ ] Test cluster secret'ları ↔ prod cluster secret'ları **tamamen ayrık**
- [ ] Test'ten kopyalanmış secret prod'a girmez (ayrı Vault namespace)
- [ ] Cross-cluster ESO sync YASAK (namespace boundary'yi ihlal eder)

## Süre + yenileme

- 1 yıl geçerli
- Devir sırasında **tam güvenlik audit** (kim ne zaman ne değiştirdi) + eski owner erişim revoke

## Bağlı runbook'lar

- [RB-faz35-incident-response.md](../../runbooks/RB-faz35-incident-response.md) — Secret ihlali SEV1
- [RB-vault-ops.md](../../runbooks/RB-vault-ops.md) (varsa) — genel Vault operasyonları
- [RB-faz35-emergency-kill-switch.md](../../runbooks/RB-faz35-emergency-kill-switch.md) — panic-off durumunda secret revoke

## Kişisel mesuliyet

**Uyarı**: Secret gizliliği kişisel taahhüttür. İhmal → şirket + muhbir + hedef kişi zararı doğar; rücu riski vardır.

---

**Kabul beyanı**: <PENDING>

```
Tarih: YYYY-MM-DD
İsim: AD SOYAD
Email: name@company.com
Rol: Secret Owner
Kabul yöntemi: git commit / PDF ıslak / DocuSign
Charter versiyon: 2026-07-22 v1.0
```
