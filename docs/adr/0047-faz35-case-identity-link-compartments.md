# ADR-0047 — Faz 35 Case, Reporter Identity ve IdentityLinkVault kompartımanları

**Status:** Accepted for TEST implementation
**Date:** 2026-07-24
**Decision owners:** Product/Platform Engineering; production key-custody activation
ayrıca named Secret Owner, Privacy Officer ve Reveal Officer kabulü gerektirir
**Tracks:** ES-004, ES-203, ES-206, ES-209
**Supersedes:** Etik Speak verisini tek veritabanı, tek Vault snapshot'ı veya tek
backup operatörü altında yeniden birleştiren tüm taslak/örnek yollar
**Related:** [ADR-0046](./0046-faz35-etik-speak-product-cell-topology.md),
[privacy contract](../faz-35-etik-speak-product-charter.md),
[ES-209](https://github.com/Halildeu/platform-k8s-gitops/issues/2661)

## 1. Karar özeti

Etik Speak üç ayrı güvenlik alanı olarak işletilir:

| Kompartıman | Tutabileceği veri | Tutamayacağı veri |
|---|---|---|
| `Case` | vaka içeriği, mesajlar, sınıflandırma, assignment ve redacted audit referansı | ad, e-posta, telefon, çalışan kimliği, identity ciphertext veya link çözüm anahtarı |
| `ReporterIdentity` | reporter iletişim/kimlik ciphertext'i, doğrulama durumu ve kendi retention metadata'sı | vaka narrative'i, vaka mesajı, vaka numarası veya link |
| `IdentityLinkVault` | opaque `case_ref ↔ identity_ref` bağlantısı ve reveal workflow durumu | açık kimlik, iletişim bilgisi, narrative veya case payload |

Her alanın storage principal'ı, Vault Transit key'i, policy'si, backup
artifact'ı, decrypt/restore rolü ve break-glass akışı ayrıdır. Hiçbir workload,
operatör veya kalıcı token iki alanı aynı anda decrypt/unwrap edemez.

`ANONYMOUS` bildirimde `ReporterIdentity` ve `IdentityLinkVault` yazımı
**yapılmaz**. Boş/sentinel/pseudonymous link üretmek de yasaktır. Confidential
bildirimde Case servisi yalnız rastgele opaque referans görür; açık kimlik veya
identity ciphertext görmez.

## 2. Neden

Whistleblowing ürününde uygulama seviyesinde rol kontrolü tek başına yeterli
değildir. Yanlış DB grant'i, backup restore'u, Vault snapshot'ı veya ayrıcalıklı
operatör hesabı case narrative'i ile reporter kimliğini yeniden birleştirebilir.
Bu ADR, iç tehdit ve restore kopyasını birinci sınıf tehdit yüzeyi sayar.

Karar; ISO 37002 gizlilik/need-to-know ilkesi, ISO 27001 least privilege ve
separation of duties, GDPR Art. 5(1)(c)/(f), KVKK Md. 12 teknik tedbirleri ve
EU 2019/1937 kimlik gizliliği beklentisiyle uyumludur. Hukuki süre veya named
owner kararı bu teknik ayrımı gevşetmez.

## 3. Runtime kimlikleri ve storage sınırı

TEST ve production için ayrı isimlerle aşağıdaki service identity'ler kurulur:

- `ethics-case-runtime`: yalnız Case schema/database ve `transit-ethics-case`
  encrypt/decrypt yoluna erişir.
- `ethics-identity-runtime`: yalnız ReporterIdentity store ve
  `transit-ethics-identity` encrypt/decrypt yoluna erişir.
- `ethics-link-runtime`: yalnız IdentityLinkVault store ve
  `transit-ethics-link` encrypt/decrypt yoluna erişir.
- `ethics-reveal-broker`: storage okuyamaz; yalnız iki onayı doğrulanmış,
  tek kullanımlık, kısa TTL'li reveal grant'ini consume eder ve üç servisten
  gerekli minimum projection'ı ayrı çağrılarla alır.

Bir Kubernetes ServiceAccount'a iki runtime secret bağlanamaz. Aynı Pod'a iki
kompartımanın DB credential'ı veya Transit decrypt policy'si enjekte edilemez.
NetworkPolicy her identity'yi yalnız kendi store/Transit endpoint'ine ve
zorunlu control-plane endpoint'lerine sınırlar.

Database-level defence in depth:

- ayrı database veya ayrı PostgreSQL instance tercih edilir;
- TEST geçişinde aynı instance kullanılırsa ayrı database + ayrı owner/login
  zorunludur; cross-database FDW, dblink, shared superuser ve ortak search path
  yasaktır;
- application migration rolleri runtime rollerinden ayrıdır;
- runtime rollerinde `CREATEDB`, `CREATEROLE`, `BYPASSRLS`, replication,
  extension ve schema-owner yetkisi bulunmaz.

## 4. Opaque link sözleşmesi

Confidential intake sırası:

1. Public intake Case kaydını üretir ve rastgele `case_ref` alır.
2. Identity API açık kimliği kendi alanında şifreleyip rastgele
   `identity_ref` döndürür.
3. Link API yalnız iki opaque referansı bağlar. İstek idempotency anahtarı,
   channel ve policy version dışında payload taşımaz.
4. Case alanı en fazla `has_confidential_identity=true` bilgisi tutabilir;
   `identity_ref` veya link row ID tutamaz.

`case_ref` ve `identity_ref` UUID olsa bile birbirinden türetilemez. Hash,
e-posta hash'i, employee ID hash'i veya deterministik token link olarak
kullanılamaz; bunlar offline korelasyon oracle'ı üretir.

## 5. Reveal ve split custody

Reveal varsayılan olarak deny'dır. Başarılı reveal için aynı request digest'i
üzerinde iki farklı insan principal'ın onayı gerekir:

1. `Reveal Officer`
2. `Privacy Officer` veya policy'nin izin verdiği named Legal Owner

Ek koşullar:

- subject, assignee, triager, reporting-line veya conflicted approver kendini
  onaylayamaz; recusal OpenFGA ve backend'de fail-closed doğrulanır;
- onaylar farklı principal ve farklı session olmalıdır;
- grant tek kullanımlık, request-bound ve en fazla 10 dakika TTL'li olur;
- reveal broker storage credential veya Transit key taşımaz;
- sonuç minimum projection'dır; toplu export/download üretmez;
- request, approvals, deny/recusal, consume ve result metadata'sı ES-207 WORM
  zincirine yazılır; açık kimlik veya narrative audit payload'ına girmez.

Production'da owner imzası olmadan reveal broker ve decrypt policy'leri
etkinleştirilmez. TEST sentetik persona ve sentetik kimlikle çalışabilir.

## 6. Backup ve restore kararı

Her kompartıman ayrı content-addressed artifact üretir:

| Artifact | Encryption recipient/key | Restore principal |
|---|---|---|
| Case backup | `backup-ethics-case` | `restore-ethics-case` |
| Identity backup | `backup-ethics-identity` | `restore-ethics-identity` |
| Link backup | `backup-ethics-link` | `restore-ethics-link` |
| OpenFGA export | `backup-ethics-authz` | `restore-ethics-authz` |

Kurallar:

- plaintext dump hiçbir PVC/object üzerinde kalıcılaşmaz; dump stdout'u
  streaming AEAD/age/KMS envelope encryption'a bağlanır ve yalnız ciphertext
  yazılır;
- artifact'lar ayrı bucket/prefix ACL veya ayrı PVC+principal altında tutulur;
  tek Pod/ServiceAccount bütün artifact'ları mount edemez;
- checksum, schema version, source digest, row count ve timestamp içeren
  manifest PII/narrative/identity taşımaz ve imzalanır;
- full Vault raft snapshot'ı Etik Speak product backup'ı sayılmaz; tüm secret
  alanlarını tek operatöre verdiği için bu akışta yasaktır;
- restore role'leri backup write role'lerinden ayrıdır ve kalıcı decrypt token
  taşımaz;
- Case-only rehearsal'da vaka akışı açılabilir fakat kimlik projection'ı
  üretilemez; Identity-only ve Link-only restore'larda narrative okunamaz;
- join kanıtı, eksik diğer domain key/credential ile fail-closed denial ve
  cross-store sorgu yolunun yokluğu üzerinden üretilir.

Mevcut `etik-speak-backup-archive` ortak PVC ve plaintext CronJob'ları
non-compliant referanstır; TEST aktivasyonuna eklenemez. ES-209 bunları
ayrı-encrypted artifact tasarımıyla değiştirmeden kabul üretmez.

## 7. Logging, telemetry ve data minimization

- access log, trace, metric label, exception ve WORM payload'ına identity,
  contact, narrative, receipt/access secret, `identity_ref` veya link row ID
  yazılmaz;
- metrikler yalnız compartment, outcome, reason class ve bounded counter taşır;
- backup/restore kanıtı presence, size, digest, key version, role, denial ve
  row-count seviyesindedir;
- debugging için ham dump, kubectl Secret, Vault response veya SQL row çıktısı
  issue/CI artifact'ına alınmaz.

## 8. Failure ve break-glass

- Identity veya Link alanı kapalıysa anonymous intake ve Case mailbox çalışmaya
  devam eder; confidential identity write kabul edilmez ve anonim moda sessiz
  downgrade yapılmaz.
- WORM sink kapalıysa mevcut ES-207 bounded outbox davranışı geçerlidir.
- Domain-specific break-glass yalnız o domain'in kısa TTL'li credential'ını
  üretir; ikinci domain için ayrı onay ve ayrı incident gerekir.
- Root token, PostgreSQL superuser, cluster-admin veya Vault operator snapshot
  tek başına ürün reveal yetkisi değildir.
- Backup/restore başarısızlığı canlı Case store'u değiştirmez; rehearsal yalnız
  isolated scratch namespace/database üzerinde yürür.

## 9. TEST uygulama sırası

1. Ayrı database/role/Transit policy ve ServiceAccount/NetworkPolicy'leri kur.
2. Anonymous intake için “identity/link write yok” negatif kanıtını çalıştır.
3. Sentetik confidential intake ile opaque referans sözleşmesini doğrula.
4. Dual-approval reveal allow; self/proxy/replay/same-approver deny testlerini
   çalıştır ve WORM eventlerini doğrula.
5. Dört ayrı encrypted backup artifact'ı üret; plaintext persistence taramasını
   çalıştır.
6. Scratch restore'ları ayrı principal'larla çalıştır; tek domain restore'dan
   cross-domain join'in mümkün olmadığını kanıtla.
7. Exact TEST customer journey regression'ını iki public host ve
   `testai.acik.com` üzerinde yeniden çalıştır.

## 10. Acceptance invariants

CI ve live gate aşağıdakileri fail-closed doğrular:

- `ANONYMOUS => identity_rows_delta=0 && link_rows_delta=0`;
- hiçbir Pod/ServiceAccount/role iki `transit-ethics-*` decrypt yoluna sahip
  değildir;
- hiçbir backup/restore principal iki artifact decrypt yetkisine sahip değildir;
- shared plaintext archive ve product-scoped full Vault snapshot yoktur;
- same-principal, self-approval, proxy, replay, expired grant ve wrong-org reveal
  reddedilir;
- reveal ve restore denemeleri redacted WORM event üretir;
- Case-only restore sonrası identity projection ve cross-store join fail-closed;
- exact artifact/digest, TEST runtime ve gerçek sentetik persona E2E ayrı
  kanıtlanır.

## 11. Sonuçlar ve sınırlar

Bu karar operasyon maliyetini ve secret/policy sayısını artırır; buna karşılık
DB dump, Vault snapshot veya tek ayrıcalıklı hesabın reporter kimliği ile vaka
içeriğini birleştirmesi önlenir.

ADR'nin kabulü source/design kapısıdır; runtime/deployment/restore kanıtı
değildir. Production key activation, named owner imzaları ve yasal reveal
kararı insan sınırı olarak kalır.
